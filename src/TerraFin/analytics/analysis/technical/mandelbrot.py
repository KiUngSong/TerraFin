"""Mandelbrot Fractal Dimension (MFD) for market path complexity.

This module implements the rolling Mandelbrot Fractal Dimension variant used in
the referenced Valley / BCA write-up about market "fragility" versus
"anti-fragility".

In TerraFin terms, MFD is a quantitative measure of how fragile or
anti-fragile the recent price path has been:

- lower ``D``  -> smoother, one-sided move -> lower complexity -> more fragile
- higher ``D`` -> choppier, two-way move  -> higher complexity -> more
  anti-fragile

The intuition is simple:

- If price travels from A to B along a smooth, mostly one-directional path, the
  path is not much longer than the straight-line move. The fractal dimension
  stays close to ``1``.
- If price gets to the same endpoint through a jagged, back-and-forth path, the
  cumulative travelled distance becomes much larger than the net displacement.
  The fractal dimension rises toward ``2``.

This implementation intentionally follows the article's TradingView / Pine
version, which computes:

    r_i      = ln(P_i / P_{i-1})
    R_{t,n}  = ln(P_t / P_{t-n})
    N_{t,n}  = n * sum(|r_i| over the last n steps) / |R_{t,n}|
    D_{t,n}  = ln(N_{t,n}) / ln(n)

for rolling windows such as 65, 130, and 260 trading days.

Two practical notes matter for a chart product:

1. The formula assumes strictly positive prices because it uses logarithms.
2. Some rare windows are mathematically degenerate, especially when the net
   move over the full window is ~0. To keep TerraFin's chart and agent outputs
   stable, we bound those cases instead of emitting gaps:
   - perfectly flat path -> ``D = 1.0``
   - choppy path with near-zero net displacement -> ``D = 2.0``

That keeps the output in the interpretable finance range ``[1, 2]`` while still
reflecting the article's "smooth versus jagged" idea.
"""

import math


DEFAULT_MFD_WINDOWS = (65, 130, 260)
_EPSILON = 1e-12


def _bounded_dimension(*, window: int, sum_abs_returns: float, abs_net_move: float) -> float:
    """Convert the path ratio into a bounded fractal-dimension value.

    ``D`` should live in ``[1, 2]`` for this one-dimensional price-path use case.
    We clip to that range to keep chart output stable and easy to interpret.
    """
    if sum_abs_returns <= _EPSILON:
        return 1.0
    if abs_net_move <= _EPSILON:
        return 2.0

    path_ratio = (sum_abs_returns * float(window)) / abs_net_move
    if path_ratio <= 1.0:
        return 1.0

    dimension = math.log(path_ratio) / math.log(float(window))
    return max(1.0, min(2.0, dimension))


def mandelbrot_fractal_dimension(
    closes: list[float],
    window: int = 65,
) -> tuple[int, list[float]]:
    """Compute a rolling Mandelbrot Fractal Dimension series.

    Args:
        closes: Close prices in chronological order.
        window: Lookback length ``n``. The article uses 65, 130, and 260.

    Returns:
        ``(offset, values)`` where ``offset == window`` and each value aligns to
        ``closes[offset + i]``.
    """
    if window < 2 or len(closes) <= window:
        return (window, [])
    if any(price <= 0 for price in closes):
        return (window, [])

    # Prefix sums let us get the rolling sum of absolute log returns in O(1)
    # per bar instead of re-summing each window.
    abs_prefix = [0.0]
    for idx in range(1, len(closes)):
        log_return = math.log(closes[idx] / closes[idx - 1])
        abs_prefix.append(abs_prefix[-1] + abs(log_return))

    values: list[float] = []
    for idx in range(window, len(closes)):
        sum_abs_returns = abs_prefix[idx] - abs_prefix[idx - window]
        abs_net_move = abs(math.log(closes[idx] / closes[idx - window]))
        values.append(
            _bounded_dimension(
                window=window,
                sum_abs_returns=sum_abs_returns,
                abs_net_move=abs_net_move,
            )
        )

    return (window, values)
