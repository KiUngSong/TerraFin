"""MACD (Moving Average Convergence Divergence) computation."""


def ema(values: list[float], span: int) -> list[float]:
    """Exponential moving average."""
    alpha = 2.0 / (span + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_window: int = 9,
) -> tuple[int, list[float], list[float], list[float]]:
    """Compute MACD line, signal line, and histogram.

    Args:
        closes: List of close prices.
        fast: Fast EMA period.
        slow: Slow EMA period.
        signal_window: Signal line EMA period.

    Returns:
        ``(offset, macd_values, signal_values, histogram)`` where
        *offset* is the index into *closes* at which the output starts.
    """
    if len(closes) < slow + signal_window:
        return (0, [], [], [])

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]

    macd_from_slow = macd_line[slow - 1 :]
    signal_line = ema(macd_from_slow, signal_window)
    histogram = [m - s for m, s in zip(macd_from_slow, signal_line)]

    return (slow - 1, macd_from_slow, signal_line, histogram)
