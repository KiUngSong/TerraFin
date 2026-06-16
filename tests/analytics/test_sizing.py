"""Tests for deterministic risk-aware position sizing (portfolio/sizing.py)."""

import math

from TerraFin.analytics.analysis.portfolio.sizing import (
    SizingInput,
    annualized_volatility,
    size_book,
)

_EPS = 1e-9


# ── annualized_volatility ───────────────────────────────────────────────


def test_vol_insufficient_data_returns_none():
    assert annualized_volatility([100.0] * 10, min_obs=40) is None


def test_vol_constant_series_returns_none():
    # zero variance → degenerate → None
    assert annualized_volatility([100.0] * 200) is None


def test_vol_higher_swings_higher_vol():
    lo = [100.0 * (1 + 0.001 * (-1) ** i) for i in range(200)]   # ±0.1%/day
    hi = [100.0 * (1 + 0.02 * (-1) ** i) for i in range(200)]    # ±2%/day
    v_lo = annualized_volatility(lo)
    v_hi = annualized_volatility(hi)
    assert v_lo is not None and v_hi is not None
    assert v_hi > v_lo > 0


def test_vol_only_uses_window():
    # calm for 300 days, then the window should reflect only recent calm
    calm = [100.0 * (1 + 0.001 * (-1) ** i) for i in range(300)]
    v = annualized_volatility(calm, window=126)
    assert v is not None and v < 0.10  # ~0.1%/day annualizes well under 10%


# ── size_book: structure / budget ───────────────────────────────────────


def _eq(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_empty_book():
    b = size_book([])
    assert b.positions == [] and b.gross == 0.0 and b.cash == 1.0


def test_standalone_not_normalized():
    # equal vol, distinct sectors → each name sized standalone at ~base_weight; the
    # book total is N x base_weight, NOT forced to 100%. (The whole point: no
    # normalization — cash is the residual.)
    items = [SizingInput(t, sec, 0.30) for t, sec in
             [("A", "Tech"), ("B", "Energy"), ("C", "Health"), ("D", "Financials")]]
    b = size_book(items, base_weight=0.13, max_gross=1.0, per_name_cap=0.20, sector_cap=0.40)
    assert all(_eq(p.weight, 0.13) for p in b.positions)   # standalone, equal vol → factor 1.0
    assert _eq(b.gross, 0.52) and _eq(b.cash, 0.48)         # 4 x 0.13, NOT 1.0
    assert all(p.capped_by is None for p in b.positions)


def test_small_book_leaves_cash():
    # THE key property: a few names are NOT inflated to fill the budget; cash floats.
    items = [SizingInput("A", "X", 0.3), SizingInput("B", "Y", 0.3)]
    b = size_book(items, base_weight=0.13, max_gross=1.0)
    assert _eq(b.gross, 0.26) and _eq(b.cash, 0.74)


def test_none_vol_is_neutral_base():
    items = [SizingInput(t, f"S{i}", None) for i, t in enumerate(["A", "B", "C"])]
    b = size_book(items, base_weight=0.13)
    assert all(_eq(p.vol_factor, 1.0) for p in b.positions)
    assert all(_eq(p.weight, 0.13) for p in b.positions)
    assert _eq(b.gross, 0.39)


# ── size_book: down-only caps ──────────────────────────────────────────


def test_per_name_cap_binds():
    # base_weight above the per-name cap → each trimmed to the cap, marked "name"
    items = [SizingInput(t, s, 0.3) for t, s in [("A", "X"), ("B", "Y"), ("C", "Z")]]
    b = size_book(items, base_weight=0.30, per_name_cap=0.20, sector_cap=0.40)
    assert all(_eq(p.weight, 0.20) for p in b.positions)
    assert all(p.capped_by == "name" for p in b.positions)


def test_sector_cap_trims_down():
    # 4 names one sector: 4 x 0.13 = 0.52 > 0.40 sector cap → trimmed down to 0.40 total
    items = [SizingInput(t, "Energy", 0.3) for t in ["A", "B", "C", "D"]]
    b = size_book(items, base_weight=0.13, per_name_cap=0.20, sector_cap=0.40)
    assert _eq(sum(p.weight for p in b.positions), 0.40)
    assert all(p.capped_by == "sector" for p in b.positions)


def test_max_gross_trims_down():
    # 8 standalone targets (0.13 each = 1.04) exceed a 0.6 regime cap → trimmed to 0.6
    items = [SizingInput(t, f"S{i}", 0.3) for i, t in enumerate("ABCDEFGH")]
    b = size_book(items, base_weight=0.13, max_gross=0.6, per_name_cap=0.20, sector_cap=1.0)
    assert _eq(b.gross, 0.6) and _eq(b.cash, 0.4)
    assert any("trimmed" in n for n in b.notes)


def test_caps_never_violated():
    items = [SizingInput(t, s, v) for t, s, v in [
        ("A", "Tech", 0.25), ("B", "Tech", 0.55), ("C", "Energy", 0.40),
        ("D", "Energy", 0.30), ("E", "Health", 0.20), ("F", "Health", 0.6),
        ("G", "Financials", 0.35),
    ]]
    b = size_book(items, base_weight=0.13, max_gross=1.0, per_name_cap=0.15, sector_cap=0.30)
    assert all(p.weight <= 0.15 + _EPS for p in b.positions)
    from collections import defaultdict
    sec = defaultdict(float)
    for p in b.positions:
        sec[p.sector] += p.weight
    assert all(tot <= 0.30 + _EPS for tot in sec.values())


# ── size_book: standalone vol tilt ─────────────────────────────────────


def test_lower_vol_sized_larger():
    # standalone: the calmer name gets a larger target than the choppier one, bounded.
    items = [SizingInput("A", "X", 0.20), SizingInput("B", "Y", 0.60)]
    b = size_book(items, base_weight=0.13, per_name_cap=0.20, sector_cap=0.40,
                  vol_bounds=(0.6, 1.1))
    wa = next(p.weight for p in b.positions if p.ticker == "A")
    wb = next(p.weight for p in b.positions if p.ticker == "B")
    fa = next(p.vol_factor for p in b.positions if p.ticker == "A")
    assert wa > wb                       # calmer A sized larger than choppier B
    assert _eq(fa, 1.1)                  # median/vol = 2.0 → clamped to the 1.1 ceiling
    assert _eq(wa, 0.13 * 1.1)           # 0.143, standalone (no normalization)


def test_factor_clamp_caps_extreme_vol_ratio():
    # a 10x vol gap must still clamp the factor to the [0.6, 1.1] band
    items = [SizingInput("A", "X", 0.05), SizingInput("B", "Y", 0.50)]
    b = size_book(items, base_weight=0.13, vol_bounds=(0.6, 1.1))
    fa = next(p.vol_factor for p in b.positions if p.ticker == "A")
    fb = next(p.vol_factor for p in b.positions if p.ticker == "B")
    assert _eq(fa, 1.1) and _eq(fb, 0.6)
