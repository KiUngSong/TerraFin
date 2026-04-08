"""Moving average computation."""


def moving_average(closes: list[float], window: int) -> tuple[int, list[float]]:
    """Compute simple moving average.

    Args:
        closes: List of close prices.
        window: Rolling window size.

    Returns:
        ``(offset, values)`` where *offset* is the index into *closes*
        at which the first value starts.  ``values[i]`` corresponds to
        ``closes[offset + i]``.
    """
    n = len(closes)
    if n < window:
        return (0, [])

    values: list[float] = []
    running = sum(closes[:window])
    values.append(running / window)
    for i in range(window, n):
        running += closes[i] - closes[i - window]
        values.append(running / window)
    return (window - 1, values)
