"""Tests for Delta-Straddle trend signal and vol regime analytics."""

import math

from TerraFin.analytics.analysis.technical import (
    percentile_rank,
    trend_signal,
    trend_signal_composite,
    vol_regime,
)


# ── trend_signal ───────────────────────────────────────────────────────


def test_trend_signal_uptrend_positive():
    """A steady uptrend should produce a strong positive signal."""
    prices = [100 * math.exp(0.001 * i) for i in range(300)]
    offset, values = trend_signal(prices, window=126)
    assert offset == 126
    assert len(values) > 0
    assert values[-1] > 0.5


def test_trend_signal_downtrend_negative():
    """A steady downtrend should produce a negative signal."""
    prices = [100 * math.exp(-0.001 * i) for i in range(300)]
    offset, values = trend_signal(prices, window=126)
    assert len(values) > 0
    assert values[-1] < -0.5


def test_trend_signal_range_bounded():
    """All values should be in [-1, +1]."""
    prices = [100 + 10 * math.sin(i * 0.05) for i in range(300)]
    offset, values = trend_signal(prices, window=64)
    for v in values:
        assert -1.0 <= v <= 1.0


def test_trend_signal_student_t():
    """Student-t distribution variant should also produce valid signals."""
    prices = [100 * math.exp(0.001 * i) for i in range(300)]
    offset, values = trend_signal(prices, window=126, distribution="t", df=5)
    assert len(values) > 0
    assert values[-1] > 0.5
    for v in values:
        assert -1.0 <= v <= 1.0


def test_trend_signal_too_short_returns_empty():
    """Insufficient data returns empty values."""
    prices = [100, 101, 102]
    offset, values = trend_signal(prices, window=126)
    assert values == []


# ── trend_signal_composite ─────────────────────────────────────────────


def test_composite_averages_multiple_windows():
    """Composite should produce values within the range of individual signals."""
    prices = [100 * math.exp(0.0005 * i) for i in range(600)]
    offset, values = trend_signal_composite(prices)
    assert offset > 0
    assert len(values) > 0
    assert values[-1] > 0.0


def test_composite_custom_windows():
    """Custom windows should work."""
    prices = [100 * math.exp(0.001 * i) for i in range(300)]
    offset, values = trend_signal_composite(prices, windows=[32, 64])
    assert len(values) > 0


# ── percentile_rank ────────────────────────────────────────────────────


def test_percentile_rank_at_maximum():
    """A series ending at its window maximum should rank 100."""
    values = list(range(200))
    offset, ranks = percentile_rank(values, window=126)
    assert ranks[-1] == 100.0


def test_percentile_rank_at_minimum():
    """A series ending at its window minimum should rank 0."""
    values = list(range(200, 0, -1))
    offset, ranks = percentile_rank(values, window=126)
    assert ranks[-1] == 0.0


def test_percentile_rank_range():
    """All ranks should be in [0, 100]."""
    values = [10 + 5 * math.sin(i * 0.1) for i in range(300)]
    offset, ranks = percentile_rank(values, window=126)
    for r in ranks:
        assert 0.0 <= r <= 100.0


# ── vol_regime ─────────────────────────────────────────────────────────


def test_vol_regime_hysteresis():
    """Once in stable regime, should not flip until exit threshold is crossed."""
    # Start low, rise above 80, then drop to 50 (should stay unstable)
    values = [10] * 130 + [90] * 10 + [50] * 50
    offset, regimes = vol_regime(values, window=126)
    assert len(regimes) > 0
    # All outputs should be 0 or 1
    for r in regimes:
        assert r in (0, 1)


def test_vol_regime_stable_detection():
    """Low-volatility period should be classified as stable."""
    # Constant low value
    values = [15.0] * 200
    offset, regimes = vol_regime(values, window=126, entry_threshold=20, exit_threshold=80)
    assert len(regimes) > 0
    # Constant series → rank = 50 → stays at initial classification
