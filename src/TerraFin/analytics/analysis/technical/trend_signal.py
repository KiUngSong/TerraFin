"""Delta-Straddle trend following signal.

Based on J.P. Morgan's "Designing Robust Trend-Following Systems".
Computes a t-statistic of rolling log returns, transforms via CDF to a
-1 to +1 signal that replicates straddle payoff characteristics.
"""

import math
from typing import Literal

from scipy.stats import norm
from scipy.stats import t as t_dist


def _normal_cdf(x: float) -> float:
    """Standard normal CDF."""
    return float(norm.cdf(x))


def _t_cdf(x: float, df: int) -> float:
    """Student-t CDF."""
    return float(t_dist.cdf(x, df))


def trend_signal(
    closes: list[float],
    window: int = 126,
    *,
    distribution: Literal["normal", "t"] = "normal",
    df: int = 5,
) -> tuple[int, list[float]]:
    """Compute Delta-Straddle trend following signal for a single lookback window.

    Args:
        closes: List of close prices.
        window: Rolling lookback period for t-statistic.
        distribution: CDF distribution — "normal" (standard) or "t" (fat-tailed).
        df: Degrees of freedom for Student-t CDF (only used when distribution="t").

    Returns:
        ``(offset, values)`` where each value is in [-1, +1].
        Positive = uptrend conviction, negative = downtrend conviction.
    """
    n = len(closes)
    if n < window + 2:
        return (0, [])

    # Compute log returns
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]

    cdf_fn = _normal_cdf if distribution == "normal" else lambda x: _t_cdf(x, df)

    values: list[float] = []
    sqrt_w = math.sqrt(window)

    for i in range(window, len(log_returns) + 1):
        chunk = log_returns[i - window : i]
        mean_r = sum(chunk) / window
        var_r = sum((r - mean_r) ** 2 for r in chunk) / (window - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 1e-10

        t_stat = mean_r / (std_r / sqrt_w)
        prob = cdf_fn(t_stat)
        signal = 2.0 * prob - 1.0
        values.append(signal)

    # The first signal aligns with closes[window]. The log-return shift is
    # already accounted for by the rolling window over returns, so we do not
    # add an extra index step here.
    offset = window
    return (offset, values)


def trend_signal_composite(
    closes: list[float],
    windows: list[int] | None = None,
    *,
    distribution: Literal["normal", "t"] = "normal",
    df: int = 5,
) -> tuple[int, list[float]]:
    """Multi-timeframe averaged Delta-Straddle signal.

    Averages trend signals across multiple lookback windows to reduce
    overfitting to any single parameter choice.

    Args:
        closes: List of close prices.
        windows: List of lookback periods. Default: [32, 64, 126, 252, 504].
        distribution: CDF distribution for each window.
        df: Degrees of freedom for Student-t CDF.

    Returns:
        ``(offset, values)`` where each value is the average signal across
        all windows, in [-1, +1].
    """
    if windows is None:
        windows = [32, 64, 126, 252, 504]

    if not windows:
        return (0, [])

    # Compute each window's signal
    signals: list[tuple[int, list[float]]] = []
    for w in windows:
        offset, vals = trend_signal(closes, w, distribution=distribution, df=df)
        signals.append((offset, vals))

    # Find the common range (all windows must have a value)
    max_offset = max(s[0] for s in signals)
    min_end = min(s[0] + len(s[1]) for s in signals)

    if max_offset >= min_end:
        return (0, [])

    # Average signals over the common range
    values: list[float] = []
    for i in range(max_offset, min_end):
        total = 0.0
        for offset, vals in signals:
            total += vals[i - offset]
        values.append(total / len(signals))

    return (max_offset, values)
