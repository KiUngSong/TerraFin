"""Volatility regime classification via percentile rank.

Based on Antonio Mele (2017) — implied volatility indices for market timing.
Computes rolling percentile rank (0-100) of a volatility series with
hysteresis-based regime switching.
"""


def percentile_rank(
    values: list[float],
    window: int = 126,
) -> tuple[int, list[float]]:
    """Rolling percentile rank (0-100) over a lookback window.

    For each point, computes where the current value falls within the
    min-max range of the past *window* observations.

    Args:
        values: List of values (e.g., VIX closes, MOVE closes).
        window: Rolling lookback period (default 126 ~ 6 months).

    Returns:
        ``(offset, ranks)`` where each rank is in [0, 100].
        0 = lowest in window, 100 = highest in window.
    """
    n = len(values)
    if n < window:
        return (0, [])

    ranks: list[float] = []
    for i in range(window - 1, n):
        chunk = values[i - window + 1 : i + 1]
        lo = min(chunk)
        hi = max(chunk)
        if hi == lo:
            ranks.append(50.0)
        else:
            ranks.append(100.0 * (values[i] - lo) / (hi - lo))

    offset = window - 1
    return (offset, ranks)


def vol_regime(
    values: list[float],
    window: int = 126,
    *,
    entry_threshold: float = 20.0,
    exit_threshold: float = 80.0,
) -> tuple[int, list[int]]:
    """Classify volatility regime using percentile rank with hysteresis.

    Regime states:
        1 = Stable (vol rank dropped below entry_threshold)
        0 = Unstable (vol rank crossed above exit_threshold)

    Hysteresis prevents whipsaw: once in a regime, stays there until
    the opposite threshold is crossed.

    Args:
        values: List of volatility index values (e.g., VIX closes).
        window: Rolling lookback period for percentile rank.
        entry_threshold: Rank below which regime becomes Stable (default 20).
        exit_threshold: Rank above which regime becomes Unstable (default 80).

    Returns:
        ``(offset, regimes)`` where each regime is 1 (stable) or 0 (unstable).
    """
    offset, ranks = percentile_rank(values, window)
    if not ranks:
        return (0, [])

    regimes: list[int] = []
    # Start with unknown — classify based on first rank
    current = 1 if ranks[0] < entry_threshold else 0

    for rank in ranks:
        if current == 1 and rank >= exit_threshold:
            current = 0
        elif current == 0 and rank <= entry_threshold:
            current = 1
        regimes.append(current)

    return (offset, regimes)
