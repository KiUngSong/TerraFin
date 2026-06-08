"""Relative Strength Index computation (Cutler's / simple-average variant)."""


def rsi(closes: list[float], window: int = 14) -> tuple[int, list[float]]:
    """Compute Cutler's RSI: a simple moving sum of gains and losses.

    RSI = 100 * sum(gains) / (sum(gains) + sum(losses)) over the last *window*
    price changes. Unlike Wilder's recursive smoothing this is path-independent
    — the value at any bar depends only on the preceding *window* changes, not
    on how much history was loaded — so it matches the convention most Korean
    brokerage apps display and is stable across chart zoom levels.

    Args:
        closes: List of close prices.
        window: Lookback period.

    Returns:
        ``(offset, values)`` where *offset* is the index into *closes*
        at which the first RSI value starts.
    """
    n = len(closes)
    if n < window + 1:
        return (0, [])

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]

    values: list[float] = []
    for i in range(window - 1, len(deltas)):
        win = deltas[i - window + 1 : i + 1]
        gain = sum(d for d in win if d > 0)
        loss = sum(-d for d in win if d < 0)
        total = gain + loss
        # Flat window (no movement either way) → neutral 50.
        values.append(100.0 * gain / total if total != 0 else 50.0)

    # win ends at deltas[i] = closes[i+1]; first window is deltas[0:window],
    # so the first RSI value lands on closes[window].
    offset = window
    return (offset, values)


def rsi_wilder(closes: list[float], window: int = 14) -> tuple[int, list[float]]:
    """Compute Wilder's RSI using recursive (RMA) smoothing of gains/losses.

    The original 1978 definition and the default on TradingView/most pro
    platforms. Path-dependent (effectively infinite memory), so its value at a
    bar depends on how much history precedes it — feed a long warmup for parity
    with other Wilder implementations. Offered alongside Cutler's ``rsi`` so the
    chart can show either convention.

    Returns ``(offset, values)`` like :func:`rsi`.
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
