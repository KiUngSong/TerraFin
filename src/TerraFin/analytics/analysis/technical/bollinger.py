"""Bollinger Bands computation."""


def bollinger_bands(
    closes: list[float],
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[int, list[float], list[float]]:
    """Compute Bollinger Bands using running sum/sum-of-squares — O(n).

    Returns:
        ``(offset, upper, lower)`` where *offset* is the index into
        *closes* at which the first band value starts.
    """
    n = len(closes)
    if n < window:
        return (0, [], [])

    upper: list[float] = []
    lower: list[float] = []

    run_sum = 0.0
    run_sq = 0.0
    for j in range(window):
        run_sum += closes[j]
        run_sq += closes[j] * closes[j]

    mean = run_sum / window
    var = max(0.0, run_sq / window - mean * mean)
    std = var**0.5
    upper.append(mean + num_std * std)
    lower.append(mean - num_std * std)

    for i in range(window, n):
        old = closes[i - window]
        new = closes[i]
        run_sum += new - old
        run_sq += new * new - old * old
        mean = run_sum / window
        var = max(0.0, run_sq / window - mean * mean)
        std = var**0.5
        upper.append(mean + num_std * std)
        lower.append(mean - num_std * std)

    return (window - 1, upper, lower)
