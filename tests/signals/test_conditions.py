"""Tests for alerting condition evaluators."""

import pandas as pd
import pytest

from TerraFin.signals.alerting.conditions import _check_bollinger, _check_ma_cross, _check_macd, _check_rsi, evaluate


def _make_ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _ramp(start: float, end: float, n: int) -> list[float]:
    step = (end - start) / max(n - 1, 1)
    return [start + i * step for i in range(n)]


# ─── RSI ─────────────────────────────────────────────────────────────────────


def test_rsi_overbought_triggered():
    # Strongly rising prices → high RSI
    closes = [100.0 + i * 2 for i in range(50)]
    signals = _check_rsi("TEST", closes)
    names = {s.name for s in signals}
    assert "RSI_OVERBOUGHT" in names


def test_rsi_oversold_triggered():
    # Strongly falling prices → low RSI
    closes = [100.0 - i * 2 for i in range(50)]
    signals = _check_rsi("TEST", closes)
    names = {s.name for s in signals}
    assert "RSI_OVERSOLD" in names


def test_rsi_no_signal_mid_range():
    # Oscillating → RSI stays mid-range
    closes = [100 + (i % 5) for i in range(60)]
    signals = _check_rsi("TEST", closes)
    assert signals == []


def test_rsi_insufficient_data():
    closes = [100.0] * 5
    signals = _check_rsi("TEST", closes)
    assert signals == []


# ─── MACD ────────────────────────────────────────────────────────────────────


def test_macd_bull_cross_triggered():
    # Trend reversal: first falling then rising → MACD crosses up
    falling = _ramp(150.0, 50.0, 60)
    rising = _ramp(50.0, 120.0, 40)
    closes = falling + rising
    signals = _check_macd("TEST", closes)
    names = {s.name for s in signals}
    assert "MACD_BULL_CROSS" in names


def test_macd_bear_cross_triggered():
    # Rising then falling → MACD crosses down
    rising = _ramp(50.0, 150.0, 60)
    falling = _ramp(150.0, 80.0, 40)
    closes = rising + falling
    signals = _check_macd("TEST", closes)
    names = {s.name for s in signals}
    assert "MACD_BEAR_CROSS" in names


def test_macd_insufficient_data():
    closes = [100.0] * 20
    signals = _check_macd("TEST", closes)
    assert signals == []


# ─── Bollinger ───────────────────────────────────────────────────────────────


def test_bollinger_breakout_up():
    # Stable then spike up beyond upper band
    base = [100.0] * 30
    spike = base + [200.0]
    signals = _check_bollinger("TEST", spike)
    names = {s.name for s in signals}
    assert "BB_BREAKOUT_UP" in names


def test_bollinger_breakout_down():
    base = [100.0] * 30
    drop = base + [0.0]
    signals = _check_bollinger("TEST", drop)
    names = {s.name for s in signals}
    assert "BB_BREAKOUT_DOWN" in names


def test_bollinger_no_breakout():
    closes = [100.0 + (i % 3) for i in range(30)]
    signals = _check_bollinger("TEST", closes)
    assert signals == []


# ─── MA crossover ────────────────────────────────────────────────────────────


def test_ma_golden_cross():
    # 50-day crosses above 200-day: long bear then bull (need 50+ bars to produce cross)
    bear = _ramp(200.0, 50.0, 201)
    bull = _ramp(50.0, 200.0, 50)
    closes = bear + bull
    signals = _check_ma_cross("TEST", closes)
    names = {s.name for s in signals}
    assert "MA_GOLDEN_CROSS" in names


def test_ma_death_cross():
    # 50-day crosses below 200-day: long bull then bear (need 50+ bars to produce cross)
    bull = _ramp(50.0, 200.0, 201)
    bear = _ramp(200.0, 50.0, 50)
    closes = bull + bear
    signals = _check_ma_cross("TEST", closes)
    names = {s.name for s in signals}
    assert "MA_DEATH_CROSS" in names


def test_ma_cross_insufficient_data():
    closes = [100.0] * 100
    signals = _check_ma_cross("TEST", closes)
    assert signals == []


# ─── evaluate() integration ──────────────────────────────────────────────────


def test_evaluate_returns_list():
    closes = [100.0 + i for i in range(50)]
    ohlc = _make_ohlc(closes)
    signals = evaluate("TEST", ohlc)
    assert isinstance(signals, list)


def test_evaluate_too_short_returns_empty():
    ohlc = _make_ohlc([100.0] * 10)
    assert evaluate("TEST", ohlc) == []


def test_evaluate_signal_has_required_fields():
    closes = [100.0 + i * 2 for i in range(50)]
    ohlc = _make_ohlc(closes)
    signals = evaluate("TEST", ohlc)
    for s in signals:
        assert s.ticker == "TEST"
        assert s.name
        assert s.severity in ("high", "medium", "low")
        assert s.message
        assert isinstance(s.snapshot, dict)
