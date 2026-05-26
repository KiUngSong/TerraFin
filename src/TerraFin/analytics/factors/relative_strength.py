"""Cross-sectional relative-strength momentum (12-1).

Pure computation + a cross-sectional ranker. The caller supplies prices, so this
module does no I/O and stays testable — feed it live prices (get_market_data) for
a live signal, or historical slices for a backtest. Universe membership can come
from `analytics.similarity.pool` (symbol lists), but prices must be supplied by
the caller (pool's own price cache is year-end-frozen, wrong for a live signal).

"12-1" = trailing 12-month return skipping the most recent month, the standard
momentum-factor definition (skipping the last month avoids short-term reversal).
"""
from typing import Optional, Sequence


# Trading-day conventions for the 12-1 window.
LOOKBACK_DAYS = 252
SKIP_DAYS = 21


def relative_strength_score(
    closes: Sequence[float],
    *,
    lookback: int = LOOKBACK_DAYS,
    skip: int = SKIP_DAYS,
) -> Optional[float]:
    """12-1 momentum for one symbol: close[-skip] / close[-lookback] - 1.

    Returns None if the series is too short (cannot form the window). Older→newer
    so a positive number means the price rose over the window.
    """
    n = len(closes)
    if n <= lookback or lookback <= skip:
        return None
    old = closes[n - 1 - lookback]
    recent = closes[n - 1 - skip]
    if old is None or old <= 0:
        return None
    return recent / old - 1.0


# IBD Relative-Strength rating: most-recent quarter double-weighted.
# raw = 2*(C/C63) + (C/C126) + (C/C189) + (C/C252), then percentile-ranked 1-99
# across the universe. Minervini Trend Template criterion 8 wants rating >= 70.
_RS_QUARTERS = (63, 126, 189, 252)
_RS_WEIGHTS = (2.0, 1.0, 1.0, 1.0)


def ibd_rs_raw(closes: Sequence[float]) -> Optional[float]:
    """IBD-style raw relative-strength figure for one symbol (pre-percentile).

    Weighted blend of 3/6/9/12-month price ratios, recent quarter 2x. Returns
    None if the series is too short. This is the canonical SEPA RS input — NOT
    the same as the plain 12-1 `relative_strength_score` (which is for simple
    momentum ordering).
    """
    n = len(closes)
    if n <= _RS_QUARTERS[-1]:
        return None
    c = closes[n - 1]
    total = 0.0
    for w, q in zip(_RS_WEIGHTS, _RS_QUARTERS):
        past = closes[n - 1 - q]
        if past is None or past <= 0:
            return None
        total += w * (c / past)
    return total


def rs_rating(prices_by_symbol: dict[str, Sequence[float]]) -> dict[str, float]:
    """IBD RS rating (1-99 percentile) per symbol, ranked across the universe.

    Cross-sectional: a symbol's rating is its percentile rank of `ibd_rs_raw`
    among all symbols with enough history. Minervini criterion 8: keep rating
    >= 70 (top ~30%). Symbols too short to score are omitted.
    """
    raw = {s: r for s, c in prices_by_symbol.items()
           if (r := ibd_rs_raw(c)) is not None}
    if not raw:
        return {}
    ordered = sorted(raw, key=lambda s: raw[s])  # weakest → strongest
    m = len(ordered)
    if m == 1:
        return {ordered[0]: 99.0}
    return {s: 1.0 + 98.0 * (i / (m - 1)) for i, s in enumerate(ordered)}


