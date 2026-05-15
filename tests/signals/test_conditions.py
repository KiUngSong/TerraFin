"""Tests for signal detection via the real analytics patterns engine."""
import pandas as pd

from TerraFin.analytics.analysis.patterns import evaluate


def _make_ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1_000_000] * len(closes),
    })


# ─── RSI ─────────────────────────────────────────────────────────────────────


def test_rsi_overbought_triggered():
    closes = [100.0 + i * 2 for i in range(50)]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "RSI_OVERBOUGHT" in names


def test_rsi_oversold_triggered():
    closes = [100.0 - i * 2 for i in range(50)]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "RSI_OVERSOLD" in names


def test_rsi_no_signal_mid_range():
    closes = [100 + (i % 5) for i in range(60)]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "RSI_OVERBOUGHT" not in names
    assert "RSI_OVERSOLD" not in names


def test_insufficient_data_returns_empty():
    assert evaluate("TEST", _make_ohlc([100.0] * 5)) == []


# ─── MACD ────────────────────────────────────────────────────────────────────
# Real _macd_cross checks only the last-bar transition (histogram[-2] vs [-1]).
# Spike/crash at the final bar forces the crossover to land there.


def test_macd_bull_cross_triggered():
    closes = [100.0 - i * 0.8 for i in range(80)] + [200.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MACD_BULL_CROSS" in names


def test_macd_bear_cross_triggered():
    closes = [20.0 + i * 0.8 for i in range(80)] + [0.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MACD_BEAR_CROSS" in names


# ─── Bollinger ───────────────────────────────────────────────────────────────


def test_bollinger_breakout_up():
    names = {s.name for s in evaluate("TEST", _make_ohlc([100.0] * 30 + [200.0]))}
    assert "BB_BREAKOUT_UP" in names


def test_bollinger_breakout_down():
    names = {s.name for s in evaluate("TEST", _make_ohlc([100.0] * 30 + [0.0]))}
    assert "BB_BREAKOUT_DOWN" in names


def test_bollinger_no_breakout():
    closes = [100.0 + (i % 3) for i in range(30)]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "BB_BREAKOUT_UP" not in names
    assert "BB_BREAKOUT_DOWN" not in names


# ─── MA crossover ────────────────────────────────────────────────────────────
# Real _ma_cross checks only the last-bar transition (diffs[-2] vs diffs[-1]).


def test_ma_golden_cross():
    # 200 stable bars → MA50 ≈ MA200. Bar 201: dip makes MA50 < MA200.
    # Bar 202: recovery makes MA50 = MA200 → transition fires at last bar.
    closes = [100.0] * 200 + [99.0, 101.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MA_GOLDEN_CROSS" in names


def test_ma_death_cross():
    closes = [100.0] * 200 + [101.0, 99.0]
    names = {s.name for s in evaluate("TEST", _make_ohlc(closes))}
    assert "MA_DEATH_CROSS" in names


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
