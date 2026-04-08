"""Chart indicator display adapter.

Thin layer that calls analytics computation and formats results
as chart series dicts for the lightweight-charts frontend.
"""

from .adapter import (
    compute_bollinger_bands,
    compute_macd,
    compute_mandelbrot_fractal_dimension,
    compute_moving_averages,
    compute_range_volatility,
    compute_realized_volatility,
    compute_rsi,
    compute_trend_signal,
)


__all__ = [
    "compute_moving_averages",
    "compute_rsi",
    "compute_bollinger_bands",
    "compute_mandelbrot_fractal_dimension",
    "compute_macd",
    "compute_realized_volatility",
    "compute_range_volatility",
    "compute_trend_signal",
]
