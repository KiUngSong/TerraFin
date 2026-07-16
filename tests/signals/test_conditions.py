"""Tests for signal detection via the real analytics patterns engine."""
import pandas as pd

from TerraFin.analytics.analysis.patterns import evaluate


def _make_ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1_000_000] * len(closes),
    })


def test_insufficient_data_returns_empty():
    assert evaluate("TEST", _make_ohlc([100.0] * 5)) == []


# ─── MA crossover (close-vs-MA grid) ─────────────────────────────────────────
# Grid fires on the last-bar close-vs-MA transition, min_gap 0.5%.


def test_ma20_golden_cross():
    # Close dips below then recovers above the 20-day MA on the last bar.
    closes = [100.0] * 25 + [98.0, 103.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MA20_GOLDEN_CROSS" in names


def test_ma20_death_cross():
    closes = [100.0] * 25 + [102.0, 97.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MA20_DEATH_CROSS" in names


# ─── evaluate() integration ──────────────────────────────────────────────────


def test_evaluate_returns_list():
    assert isinstance(evaluate("TEST", _make_ohlc([100.0 + i for i in range(50)])), list)


def test_evaluate_signal_has_required_fields():
    closes = [100.0 + i * 2 for i in range(50)]
    for s in evaluate("TEST", _make_ohlc(closes)):
        assert s.ticker == "TEST"
        assert s.name
        assert s.severity in ("high", "medium", "low")
        assert s.message
        assert isinstance(s.snapshot, dict)
