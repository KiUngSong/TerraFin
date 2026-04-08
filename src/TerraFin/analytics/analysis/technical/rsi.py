"""Relative Strength Index computation."""


def rsi(closes: list[float], window: int = 14) -> tuple[int, list[float]]:
    """Compute RSI using exponential moving average of gains/losses.

    Args:
        closes: List of close prices.
        window: Lookback period.

    Returns:
        ``(offset, values)`` where *offset* is the index into *closes*
        at which the first RSI value starts.
    """
    n = len(closes)
    if n < window + 2:
        return (0, [])

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]

    avg_gain = sum(max(d, 0) for d in deltas[:window]) / window
    avg_loss = sum(max(-d, 0) for d in deltas[:window]) / window

    values: list[float] = []
    for i in range(window, len(deltas)):
        d = deltas[i]
        avg_gain = (avg_gain * (window - 1) + max(d, 0)) / window
        avg_loss = (avg_loss * (window - 1) + max(-d, 0)) / window
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        values.append(100.0 - (100.0 / (1.0 + rs)))

    # deltas[i] corresponds to closes[i+1]; first computed at deltas[window]
    offset = window + 1
    return (offset, values)
