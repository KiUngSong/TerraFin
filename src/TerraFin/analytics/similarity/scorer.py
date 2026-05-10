"""Similarity scoring — slide a target template across full pool history.

Method: z-normalized Euclidean distance on cumulative log returns via STUMPY
(MASS algorithm, O(n log n)).  For each pool symbol the distance profile across
all sliding windows is computed; the minimum distance position is the best match.

Score is mapped to [0, 1]:  score = 1 - (min_dist / sqrt(2 * N))
where sqrt(2*N) is the maximum possible z-norm Euclidean distance.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np


if TYPE_CHECKING:
    import pandas as pd


log = logging.getLogger(__name__)


@dataclass
class SimilarityResult:
    symbol: str
    name: str
    score: float          # [0, 1], higher = more similar
    match_start: str      # date where best match window begins (YYYY-MM-DD)
    match_end: str        # date where best match window ends   (YYYY-MM-DD)
    overlap_days: int     # template length (trading days)


def score_pool(
    target: "pd.Series",
    pool: "dict[str, pd.Series]",
    *,
    names: "dict[str, str] | None" = None,
    top_n: int = 20,
) -> list[SimilarityResult]:
    """Slide *target* template across every pool series; return top_n by similarity.

    Args:
        target: Close-price Series (DatetimeIndex) — the template to search for.
        pool:   {symbol → full history close-price Series} from SimilarityPool.prices().
        names:  Optional {symbol → display name} from SimilarityPool.names().
        top_n:  Number of results to return.
    """

    n = len(target)
    if n < 10:
        raise ValueError(f"Target too short: {n} days (min 10)")

    target_cumlog = _cumlog(target.dropna().values)
    max_dist = float(np.sqrt(2 * n))  # theoretical max z-norm Euclidean distance

    results: list[SimilarityResult] = []

    for sym, series in pool.items():
        clean = series.dropna()
        if len(clean) < n + 1:
            log.debug("scorer: %s skipped — series too short (%d < %d)", sym, len(clean), n + 1)
            continue

        dist_profile, idx_profile = _mass(target_cumlog, _cumlog(clean.values))
        best_i = int(np.argmin(dist_profile))
        min_dist = float(dist_profile[best_i])

        score = max(0.0, 1.0 - min_dist / max_dist)

        match_start = clean.index[best_i]
        match_end   = clean.index[min(best_i + n - 1, len(clean) - 1)]

        results.append(SimilarityResult(
            symbol=sym,
            name=(names or {}).get(sym, sym),
            score=round(score, 4),
            match_start=str(match_start.date()),
            match_end=str(match_end.date()),
            overlap_days=n,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cumlog(prices: np.ndarray) -> np.ndarray:
    """Cumulative log returns anchored at 0: log(p[t] / p[0])."""
    prices = prices.astype(np.float64)
    prices = np.where(prices <= 0, np.nan, prices)
    with np.errstate(divide="ignore", invalid="ignore"):
        cl = np.log(prices / prices[0])
    return np.nan_to_num(cl, nan=0.0)


def _mass(query: np.ndarray, series: np.ndarray) -> "tuple[np.ndarray, np.ndarray]":
    """Compute z-normalized Euclidean distance profile via STUMPY MASS.

    Falls back to a numpy sliding-window implementation if stumpy is not installed.
    """
    try:
        import stumpy
        profile = stumpy.mass(query.astype(np.float64), series.astype(np.float64))
        idx = np.arange(len(profile))
        return profile, idx
    except ImportError:
        log.warning("stumpy not installed — using slower numpy fallback")
        return _mass_numpy(query, series)


def _mass_numpy(query: np.ndarray, series: np.ndarray) -> "tuple[np.ndarray, np.ndarray]":
    """Vectorized sliding z-norm Euclidean distance (O(M*N), numpy only)."""
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(query)
    q = query - query.mean()
    q_std = query.std()
    if q_std < 1e-8:
        q_std = 1e-8
    q = q / q_std

    windows = sliding_window_view(series, n).copy()        # (M-n+1, n)
    mu    = windows.mean(axis=1, keepdims=True)
    sigma = windows.std(axis=1, keepdims=True)
    sigma[sigma < 1e-8] = 1e-8
    windows_z = (windows - mu) / sigma

    # z-norm Euclidean: sqrt(sum((q - w)^2))
    diff = windows_z - q
    dist = np.sqrt((diff ** 2).sum(axis=1))
    return dist, np.arange(len(dist))
