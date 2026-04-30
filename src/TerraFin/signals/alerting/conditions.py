"""Signal conditions evaluated from OHLC data using existing indicator modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from TerraFin.analytics.analysis.technical.bollinger import bollinger_bands
from TerraFin.analytics.analysis.technical.ma import moving_average
from TerraFin.analytics.analysis.technical.macd import macd
from TerraFin.analytics.analysis.technical.rsi import rsi


Severity = Literal["high", "medium", "low"]


@dataclass
class Signal:
    name: str
    ticker: str
    severity: Severity
    message: str
    snapshot: dict = field(default_factory=dict)


def _closes(ohlc: pd.DataFrame) -> list[float]:
    col = "close" if "close" in ohlc.columns else "Close"
    return ohlc[col].dropna().tolist()


def evaluate(ticker: str, ohlc: pd.DataFrame) -> list[Signal]:
    """Evaluate all named conditions against OHLC data; return triggered signals."""
    closes = _closes(ohlc)
    if len(closes) < 30:
        return []

    signals: list[Signal] = []
    signals.extend(_check_rsi(ticker, closes))
    signals.extend(_check_macd(ticker, closes))
    signals.extend(_check_bollinger(ticker, closes))
    signals.extend(_check_ma_cross(ticker, closes))
    return signals


# ─── RSI ─────────────────────────────────────────────────────────────────────

def _check_rsi(ticker: str, closes: list[float]) -> list[Signal]:
    offset, values = rsi(closes)
    if not values:
        return []
    latest = values[-1]
    snapshot = {"rsi": round(latest, 2)}
    if latest >= 70:
        return [Signal(
            name="RSI_OVERBOUGHT",
            ticker=ticker,
            severity="high",
            message=f"RSI {latest:.1f} — overbought territory (≥70).",
            snapshot=snapshot,
        )]
    if latest <= 30:
        return [Signal(
            name="RSI_OVERSOLD",
            ticker=ticker,
            severity="high",
            message=f"RSI {latest:.1f} — oversold territory (≤30).",
            snapshot=snapshot,
        )]
    return []


# ─── MACD ────────────────────────────────────────────────────────────────────

def _check_macd(ticker: str, closes: list[float]) -> list[Signal]:
    offset, macd_line, signal_line, histogram = macd(closes)
    if len(histogram) < 2:
        return []
    snapshot = {
        "macd": round(macd_line[-1], 4) if macd_line else None,
        "signal": round(signal_line[-1], 4) if signal_line else None,
        "histogram": round(histogram[-1], 4),
    }
    # Find most recent sign change in histogram
    for i in range(len(histogram) - 1, 0, -1):
        if histogram[i - 1] < 0 and histogram[i] >= 0:
            return [Signal(
                name="MACD_BULL_CROSS",
                ticker=ticker,
                severity="medium",
                message="MACD crossed above signal line (bullish).",
                snapshot=snapshot,
            )]
        if histogram[i - 1] > 0 and histogram[i] <= 0:
            return [Signal(
                name="MACD_BEAR_CROSS",
                ticker=ticker,
                severity="medium",
                message="MACD crossed below signal line (bearish).",
                snapshot=snapshot,
            )]
    return []


# ─── Bollinger Bands ─────────────────────────────────────────────────────────

def _check_bollinger(ticker: str, closes: list[float]) -> list[Signal]:
    offset, upper, lower = bollinger_bands(closes)
    if not upper or not lower:
        return []
    last_close = closes[-1]
    last_upper = upper[-1]
    last_lower = lower[-1]
    snapshot = {
        "close": round(last_close, 4),
        "bb_upper": round(last_upper, 4),
        "bb_lower": round(last_lower, 4),
    }
    if last_close > last_upper:
        return [Signal(
            name="BB_BREAKOUT_UP",
            ticker=ticker,
            severity="medium",
            message=f"Price {last_close:.2f} broke above Bollinger upper band {last_upper:.2f}.",
            snapshot=snapshot,
        )]
    if last_close < last_lower:
        return [Signal(
            name="BB_BREAKOUT_DOWN",
            ticker=ticker,
            severity="medium",
            message=f"Price {last_close:.2f} broke below Bollinger lower band {last_lower:.2f}.",
            snapshot=snapshot,
        )]
    return []


# ─── MA crossover ────────────────────────────────────────────────────────────

def _check_ma_cross(ticker: str, closes: list[float]) -> list[Signal]:
    if len(closes) < 202:
        return []
    _, fast = moving_average(closes, 50)
    _, slow = moving_average(closes, 200)
    if len(fast) < 2 or len(slow) < 2:
        return []
    trim = len(fast) - len(slow)
    fast_aligned = fast[trim:]
    diffs = [f - s for f, s in zip(fast_aligned, slow)]
    snapshot = {
        "ma50": round(fast_aligned[-1], 4),
        "ma200": round(slow[-1], 4),
    }
    # Find most recent sign change
    for i in range(len(diffs) - 1, 0, -1):
        if diffs[i - 1] < 0 and diffs[i] >= 0:
            return [Signal(
                name="MA_GOLDEN_CROSS",
                ticker=ticker,
                severity="high",
                message="50-day MA crossed above 200-day MA (golden cross).",
                snapshot=snapshot,
            )]
        if diffs[i - 1] > 0 and diffs[i] <= 0:
            return [Signal(
                name="MA_DEATH_CROSS",
                ticker=ticker,
                severity="high",
                message="50-day MA crossed below 200-day MA (death cross).",
                snapshot=snapshot,
            )]
    return []
