"""Volatility analysis functions for financial data."""

import math

import numpy as np
import pandas as pd

from TerraFin.data import TimeSeriesDataFrame

from ..base_analytics import get_returns


# ── Pure computation (list in, list out) ────────────────────────────────


def realized_vol(closes: list[float], window: int = 21) -> tuple[int, list[float]]:
    """Annualized realized volatility from log returns.

    Args:
        closes: List of close prices.
        window: Rolling window (21 ~ 1 month daily).

    Returns:
        ``(offset, values)`` aligned to *closes*.
    """
    n = len(closes)
    if n < window + 1:
        return (0, [])
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    sqrt252 = math.sqrt(252)
    values: list[float] = []
    # Running sum / sum-of-squares for O(n)
    run_sum = 0.0
    run_sq = 0.0
    for j in range(window):
        run_sum += log_returns[j]
        run_sq += log_returns[j] * log_returns[j]
    mean = run_sum / window
    var = max(0.0, run_sq / window - mean * mean)
    values.append(math.sqrt(var) * sqrt252)
    for i in range(window, len(log_returns)):
        old = log_returns[i - window]
        new = log_returns[i]
        run_sum += new - old
        run_sq += new * new - old * old
        mean = run_sum / window
        var = max(0.0, run_sq / window - mean * mean)
        values.append(math.sqrt(var) * sqrt252)
    return (window, values)


def range_vol(highs: list[float], lows: list[float], window: int = 20) -> tuple[int, list[float]]:
    """Annualized Parkinson's range volatility from high/low prices.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        window: Rolling window.

    Returns:
        ``(offset, values)`` aligned to the input arrays.
    """
    n = len(highs)
    if n < window:
        return (0, [])
    log_ratios = [math.log(h / l) for h, l in zip(highs, lows)]
    sqrt252 = math.sqrt(252)
    ln2x4 = 4 * math.log(2)
    values: list[float] = []
    # Running sum-of-squares for O(n)
    run_sq = 0.0
    for j in range(window):
        run_sq += log_ratios[j] * log_ratios[j]
    values.append(math.sqrt(run_sq / window / ln2x4) * sqrt252)
    for i in range(window, n):
        old = log_ratios[i - window]
        new = log_ratios[i]
        run_sq += new * new - old * old
        values.append(math.sqrt(max(0.0, run_sq / window) / ln2x4) * sqrt252)
    return (window - 1, values)


# ── Pandas wrappers (for direct analytics use) ─────────────────────────


def _to_timeseries(df: TimeSeriesDataFrame, values: pd.Series) -> TimeSeriesDataFrame:
    """Convert a computed Series back to TimeSeriesDataFrame aligned with *df*."""
    timeline = df.time[values.index]
    result = pd.DataFrame(values, columns=["close"])
    result.index = timeline
    return TimeSeriesDataFrame(result)


def realized_volatility(df: TimeSeriesDataFrame, window_size: int = 21) -> TimeSeriesDataFrame:
    """Calculate annualized realized volatility from log returns.

    Args:
        df: DataFrame with price data.
        window_size: Rolling window (21 = ~1 month daily).

    Returns:
        TimeSeriesDataFrame of realized volatility values.
    """
    returns = get_returns(df) + 1
    log_returns = np.log(returns)
    vol = (log_returns.rolling(window=window_size).std(ddof=0) * np.sqrt(252)).dropna()
    return _to_timeseries(df, vol)


def range_volatility(df: TimeSeriesDataFrame, window: int = 20) -> TimeSeriesDataFrame:
    """Parkinson's range-based volatility estimator using OHLC data.

    Args:
        df: TimeSeriesDataFrame with high/low columns.
        window: Rolling window.

    Returns:
        TimeSeriesDataFrame of annualized range volatility.

    Raises:
        ValueError: If required columns are missing.
    """
    missing = [c for c in ("close", "high", "low") if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    log_ratio = (df.high.astype(float) / df.low.astype(float)).apply(np.log)
    parkinson = np.sqrt((1 / (4 * np.log(2))) * (log_ratio**2).rolling(window=window).mean())
    vol = (parkinson * np.sqrt(252)).dropna()
    return _to_timeseries(df, vol)
