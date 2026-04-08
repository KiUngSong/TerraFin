"""Tests for Mandelbrot Fractal Dimension analytics."""

import math

from TerraFin.analytics.analysis.technical import mandelbrot_fractal_dimension


def test_mfd_smooth_exponential_trend_stays_near_one():
    """A smooth directional trend should have minimal path complexity."""
    prices = [100.0 * math.exp(0.002 * i) for i in range(320)]
    offset, values = mandelbrot_fractal_dimension(prices, window=65)

    assert offset == 65
    assert len(values) == len(prices) - 65
    assert abs(values[-1] - 1.0) < 1e-9


def test_mfd_choppy_series_is_above_one():
    """A zigzag path should be more complex than a smooth trend."""
    prices = []
    price = 100.0
    for idx in range(320):
        price += 1.4 if idx % 2 == 0 else -1.1
        prices.append(price)

    offset, values = mandelbrot_fractal_dimension(prices, window=65)

    assert offset == 65
    assert len(values) == len(prices) - 65
    assert values[-1] > 1.0


def test_mfd_too_short_returns_empty():
    """Insufficient history should return no values."""
    offset, values = mandelbrot_fractal_dimension([100.0, 101.0, 102.0], window=65)
    assert offset == 65
    assert values == []
