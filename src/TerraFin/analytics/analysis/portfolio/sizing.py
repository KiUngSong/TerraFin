"""Deterministic, risk-aware position sizing for an already-ranked long-only book.

Design:

  - **Equal-weight base, not expected-return optimization.** The picks are already
    curated/ranked upstream; sizing expresses NO additional return view (the only
    validated edge is the momentum/RS rank, which stays in list order). So the base
    weight is 1/N.
  - **Bounded inverse-vol adjustment.** Each name is nudged by a vol factor clamped
    to ``vol_bounds`` (default ±30%). Bounding is deliberate: unbounded inverse-vol /
    risk-parity on a small momentum book imposes a low-vol tilt that fights the very
    signal being traded and is dominated by covariance estimation error at N≈5. The
    clamp lets vol smooth sizing without letting it re-rank the book.
  - **No cross-name covariance.** Per-name vol only — robust at small N, and it
    sidesteps the FX/calendar problems of a mixed-currency covariance. Correlation is
    controlled bluntly via the sector cap + (upstream) the gross budget, not estimated.
  - **Caps via two-level water-fill** (sectors, then names within sector): long-only,
    per-name cap, sector cap, gross budget. Provably terminates; ``gross`` is first
    capped to the feasible maximum given the caps so it never loops or ships an
    infeasible point.

This module is pure (no I/O, no data fetching). Callers supply per-name trailing
volatility (via ``annualized_volatility``) and the sector map; policy inputs (the
gross budget, region split) live in the consuming pipeline, not here.
"""
from dataclasses import dataclass, field
from statistics import median
from typing import Optional, Sequence

_TRADING_DAYS = 252


def annualized_volatility(
    closes: Sequence[float],
    *,
    window: int = 126,
    min_obs: int = 40,
) -> Optional[float]:
    """Annualized trailing volatility from a daily close series.

    Uses the last ``window`` simple daily returns (sample std, annualized by
    sqrt(252)). Returns None when there are fewer than ``min_obs`` usable returns
    or the series is degenerate (non-positive / constant) — callers treat None as
    "no vol view", i.e. a neutral factor of 1.0. NaNs are dropped before counting.
    """
    cs = [float(c) for c in closes if c is not None and c == c and c > 0]
    if len(cs) < min_obs + 1:
        return None
    cs = cs[-(window + 1):]
    rets = [cs[i] / cs[i - 1] - 1.0 for i in range(1, len(cs))]
    if len(rets) < min_obs:
        return None
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    vol = (var ** 0.5) * (_TRADING_DAYS ** 0.5)
    return vol if vol > 0 else None


@dataclass
class SizingInput:
    ticker: str
    sector: str
    vol: Optional[float]  # annualized trailing vol; None = no vol view (neutral)


@dataclass
class SizedPosition:
    ticker: str
    sector: str
    weight: float          # absolute fraction of full capital (book sums to `gross`)
    vol: Optional[float]
    vol_factor: float      # bounded factor actually applied (1.0 = neutral)
    capped_by: Optional[str]  # "name" | "sector" | None


@dataclass
class SizedBook:
    positions: list[SizedPosition]
    gross: float            # achieved gross (sum of weights)
    requested_gross: float
    cash: float             # 1 - gross (>=0)
    notes: list[str] = field(default_factory=list)


def _bounded_vol_factors(
    vols: dict[str, Optional[float]],
    bounds: tuple[float, float],
) -> dict[str, float]:
    """factor = clamp(ref_vol / vol, lo, hi); ref = median of present vols. Names
    with no/degenerate vol get 1.0 (neutral). Lower-vol names tilt up (≤ hi),
    higher-vol names tilt down (≥ lo) — bounded so vol cannot dominate equal weight."""
    lo, hi = bounds
    present = [v for v in vols.values() if v is not None and v > 0]
    if not present:
        return {t: 1.0 for t in vols}
    ref = median(present)
    out: dict[str, float] = {}
    for t, v in vols.items():
        if v is None or v <= 0:
            out[t] = 1.0
        else:
            f = ref / v
            out[t] = lo if f < lo else hi if f > hi else f
    return out


def _waterfill(masses: dict[str, float], budget: float, caps: dict[str, float]) -> dict[str, float]:
    """Distribute ``budget`` proportional to ``masses``, each key bounded above by
    ``caps[key]``. Standard water-fill: tentatively allocate proportionally; any key
    whose share exceeds its cap is fixed at the cap and removed; redistribute the
    remainder among the rest. Terminates in <= len(masses)+1 rounds. Assumes the
    problem is feasible (sum of caps >= budget) — the caller guarantees this by
    capping ``budget`` first; any residual from infeasibility is simply left
    unallocated rather than looping."""
    alloc = {k: 0.0 for k in masses}
    free = {k for k in masses if masses[k] > 0}
    remaining = budget
    for _ in range(len(masses) + 1):
        if not free or remaining <= 1e-12:
            break
        tm = sum(masses[k] for k in free)
        if tm <= 0:
            break
        newly = [k for k in free if remaining * masses[k] / tm > caps[k] + 1e-15]
        if not newly:
            for k in free:
                alloc[k] = remaining * masses[k] / tm
            remaining = 0.0
            break
        for k in newly:
            alloc[k] = caps[k]
            remaining -= caps[k]
            free.discard(k)
    return alloc


def size_book(
    items: list[SizingInput],
    *,
    base_weight: float = 0.13,
    max_gross: float = 1.0,
    per_name_cap: float = 0.20,
    sector_cap: float = 0.40,
    vol_bounds: tuple[float, float] = (0.6, 1.1),
) -> SizedBook:
    """Size a long-only book — each name sized on its OWN merits, NOT normalized to
    a fixed gross.

      target_i = base_weight x bounded-vol-factor(name), capped at per_name_cap

    The book total is simply whatever the per-name targets sum to; the remainder is
    cash. We only ever trim DOWN — a sector total to `sector_cap`, and the whole book
    to `max_gross` (the regime budget) — never inflate to "fill" a number. So a
    handful of names naturally leaves cash; sizing does not force you fully invested.

    base_weight: a normal-conviction standalone position (fraction of total capital).
    vol_bounds: clamp on the vol factor (median_vol/vol) — calmer names sized up to
      the high bound, choppier names down to the low bound.
    """
    if not items:
        return SizedBook([], gross=0.0, requested_gross=max_gross, cash=1.0,
                         notes=["no names to size"])

    def _bucket(it: SizingInput) -> str:
        return it.sector if it.sector and it.sector != "Unknown" else f"_unknown::{it.ticker}"

    factors = _bounded_vol_factors({it.ticker: it.vol for it in items}, vol_bounds)
    # Standalone per-name target — independent of how many other names there are.
    target = {it.ticker: min(per_name_cap, base_weight * factors[it.ticker]) for it in items}
    capped = {it.ticker: ("name" if base_weight * factors[it.ticker] > per_name_cap + 1e-9 else None)
              for it in items}
    notes: list[str] = []

    # Down-only sector trim: if one sector's standalone targets pile past sector_cap.
    buckets: dict[str, list[str]] = {}
    for it in items:
        buckets.setdefault(_bucket(it), []).append(it.ticker)
    for sec, tks in buckets.items():
        s = sum(target[t] for t in tks)
        if s > sector_cap and s > 0:
            sc = sector_cap / s
            for t in tks:
                target[t] *= sc
                if capped[t] is None:
                    capped[t] = "sector"

    total = sum(target.values())
    # Down-only book trim to the regime budget — never inflate to fill it.
    if total > max_gross and total > 0:
        sc = max_gross / total
        for t in target:
            target[t] *= sc
        notes.append(f"book trimmed to {max_gross:.0%} (regime cap)")
        total = max_gross

    positions = [
        SizedPosition(ticker=it.ticker, sector=it.sector, weight=target[it.ticker],
                      vol=it.vol, vol_factor=factors[it.ticker], capped_by=capped[it.ticker])
        for it in items
    ]
    return SizedBook(
        positions=positions, gross=total, requested_gross=max_gross,
        cash=max(0.0, 1.0 - total), notes=notes,
    )
