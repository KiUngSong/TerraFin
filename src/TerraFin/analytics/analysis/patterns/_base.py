"""Shared types + helpers for pattern school modules.

Each ``patterns/*.py`` school module exports an
``evaluate(ticker, ohlc) -> list[Signal]``. The package ``__init__``
aggregates them.

The OHLC frame is expected to follow the ``TimeSeriesDataFrame`` contract
(lowercase ``time / open / high / low / close / volume`` columns). Pattern
functions are stateless: same input frame, same verdict.
"""

import threading
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

import pandas as pd

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


Severity = Literal["high", "medium", "low"]


@dataclass
class Signal:
    name: str
    ticker: str
    severity: Severity
    message: str
    snapshot: dict = field(default_factory=dict)


# ─── OHLC column accessors ───────────────────────────────────────────────────
#
# All columns are lowercase per the TimeSeriesDataFrame contract — the
# accessors are kept as a thin layer so pattern code reads
# ``closes(ohlc)`` instead of ``ohlc["close"].dropna().astype(float).tolist()``
# at every callsite, and so a future contract change has one place to land.
#
# When ``evaluate()`` in __init__ pre-populates ``ohlc.__dict__["_tf_ohlcv"]``
# each accessor short-circuits to the cached list, avoiding 6× redundant
# pandas series operations per ticker.

_OHLCV_CACHE_KEY = "_tf_ohlcv"


def closes(ohlc: TimeSeriesDataFrame) -> list[float]:
    try:
        return ohlc.__dict__[_OHLCV_CACHE_KEY]["closes"]
    except (KeyError, TypeError):
        pass
    return ohlc["close"].dropna().astype(float).tolist()


def opens(ohlc: TimeSeriesDataFrame) -> list[float]:
    try:
        return ohlc.__dict__[_OHLCV_CACHE_KEY]["opens"]
    except (KeyError, TypeError):
        pass
    return ohlc["open"].dropna().astype(float).tolist()


def highs(ohlc: TimeSeriesDataFrame) -> list[float]:
    try:
        return ohlc.__dict__[_OHLCV_CACHE_KEY]["highs"]
    except (KeyError, TypeError):
        pass
    return ohlc["high"].dropna().astype(float).tolist()


def lows(ohlc: TimeSeriesDataFrame) -> list[float]:
    try:
        return ohlc.__dict__[_OHLCV_CACHE_KEY]["lows"]
    except (KeyError, TypeError):
        pass
    return ohlc["low"].dropna().astype(float).tolist()


def volumes(ohlc: TimeSeriesDataFrame) -> list[float] | None:
    try:
        cache = ohlc.__dict__.get(_OHLCV_CACHE_KEY)
        if cache is not None:
            return cache["volumes"]
    except (KeyError, TypeError):
        pass
    if "volume" not in ohlc.columns:
        return None
    series = ohlc["volume"].dropna()
    if series.empty:
        return None
    return series.astype(float).tolist()


# ─── Indicator primitives ────────────────────────────────────────────────────


def sma(values: list[float], n: int) -> list[float]:
    """Simple moving average — output length = len(values) - n + 1."""
    if len(values) < n or n <= 0:
        return []
    out: list[float] = []
    s = sum(values[:n])
    out.append(s / n)
    for i in range(n, len(values)):
        s += values[i] - values[i - n]
        out.append(s / n)
    return out


def ema(values: list[float], n: int) -> list[float]:
    """Exponential moving average seeded by the first SMA."""
    if len(values) < n or n <= 0:
        return []
    k = 2.0 / (n + 1)
    out: list[float] = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append((v - out[-1]) * k + out[-1])
    return out


def true_ranges(highs_: list[float], lows_: list[float], closes_: list[float]) -> list[float]:
    if len(highs_) != len(lows_) or len(highs_) != len(closes_):
        return []
    out: list[float] = []
    for i in range(len(highs_)):
        h, l = highs_[i], lows_[i]
        if i == 0:
            out.append(h - l)
        else:
            pc = closes_[i - 1]
            out.append(max(h - l, abs(h - pc), abs(l - pc)))
    return out


def atr(highs_: list[float], lows_: list[float], closes_: list[float], n: int = 14) -> list[float]:
    """Wilder ATR. Output aligned to bars from index n-1 onward."""
    trs = true_ranges(highs_, lows_, closes_)
    if len(trs) < n:
        return []
    out: list[float] = [sum(trs[:n]) / n]
    for tr in trs[n:]:
        out.append((out[-1] * (n - 1) + tr) / n)
    return out


def wilder_rsi(values: list[float], n: int = 14) -> list[float]:
    if len(values) < n + 1:
        return []
    gains = []
    losses = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    out: list[float] = []
    rs = (avg_g / avg_l) if avg_l > 0 else float("inf")
    out.append(100 - 100 / (1 + rs))
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        rs = (avg_g / avg_l) if avg_l > 0 else float("inf")
        out.append(100 - 100 / (1 + rs))
    return out


# ─── Oscillator extreme entry (indicator-agnostic) ───────────────────────────


def entered_extreme(series: list[float], *, threshold: float, low: bool, lookback: int) -> bool:
    """FRESH entry into an extreme zone within the trailing ``lookback`` bars.

    True when the latest value is in the extreme zone AND the series was outside it
    at some point across the window (the latest value plus the ``lookback`` before
    it) — i.e. it CROSSED IN during the window, not merely sitting in the zone.
    The whole window is scanned (min/max), so a bounce-out-and-back still counts.

    Indicator-agnostic: pass any oscillator series — RSI (Cutler's ``rsi`` or
    ``wilder_rsi``), MFI, etc. ``low=True`` tests the lower extreme (in-zone =
    ``<= threshold``, e.g. oversold); ``low=False`` the upper (``>= threshold``,
    e.g. overbought). The zone boundary is INCLUSIVE (``<=`` / ``>=``), matching the
    app's RSI/MFI extreme convention. Any NaN in the window returns ``False`` (NaN
    makes ``min``/``max`` order-dependent, so it cannot be trusted).
    """
    if lookback < 1 or len(series) <= lookback:
        return False
    now = series[-1]
    window = series[-(lookback + 1):]
    if now != now or any(v != v for v in window):  # NaN-safe: NaN != NaN
        return False
    if low:
        return now <= threshold and max(window) > threshold
    return now >= threshold and min(window) < threshold


# ─── Swing pivots (fractal ±half) ────────────────────────────────────────────


class SwingPivot(NamedTuple):
    bar_index: int
    price: float
    side: int  # +1 = high, -1 = low


def swing_pivots(values: list[float], half: int = 3) -> list[SwingPivot]:
    """±half-bar fractal pivots over a single value series.

    Confirmed when the centre bar's value is strictly the highest (or lowest)
    within the window of size ``2*half + 1``. Pivots are returned in the order
    they confirm.
    """
    out: list[SwingPivot] = []
    n = len(values)
    if n < 2 * half + 1:
        return out
    for i in range(half, n - half):
        window = values[i - half : i + half + 1]
        v = values[i]
        if v == max(window) and window.count(v) == 1:
            out.append(SwingPivot(i, v, +1))
        elif v == min(window) and window.count(v) == 1:
            out.append(SwingPivot(i, v, -1))
    return out


# ─── Resampling ──────────────────────────────────────────────────────────────


def _ensure_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    if "time" in df.columns:
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"])
        return out.set_index("time")
    raise ValueError("OHLC frame needs DatetimeIndex or 'time' column for resampling.")


_SPY_REGIME_CACHE: dict = {"date": None, "ok": None}
_SPY_REGIME_LOCK = threading.Lock()


def spy_trend_ok(period: int = 50) -> bool | None:
    """SPY close > N-day SMA — used as a regime gate by bullish-entry detectors.

    Cached per calendar day to avoid hammering the data pipeline on every
    detector call. Returns ``None`` if SPY data isn't available.
    """
    from datetime import date as _date

    today = _date.today()
    with _SPY_REGIME_LOCK:
        if _SPY_REGIME_CACHE["date"] == today and _SPY_REGIME_CACHE["ok"] is not None:
            return _SPY_REGIME_CACHE["ok"]
    try:
        from TerraFin.data import get_data_factory

        df = get_data_factory().get_market_data("SPY")
        cs = closes(df)
        if len(cs) < period + 1:
            return None
        ma = sum(cs[-period:]) / period
        ok = bool(cs[-1] > ma)
    except Exception:
        return None
    with _SPY_REGIME_LOCK:
        _SPY_REGIME_CACHE["date"] = today
        _SPY_REGIME_CACHE["ok"] = ok
    return ok


def resample(ohlc: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV to a calendar rule (e.g. 'W-FRI', 'ME').

    Returned frame keeps DatetimeIndex; callers can iterate or pass back into
    the column-accessor helpers (which work on either index style).
    """
    df = _ensure_dt_index(ohlc)
    agg: dict[str, str] = {}
    for col, how in (("open", "first"), ("high", "max"), ("low", "min"), ("close", "last"), ("volume", "sum")):
        if col in df.columns:
            agg[col] = how
        elif col.capitalize() in df.columns:
            agg[col.capitalize()] = how
    out = df.resample(rule).agg(agg).dropna(how="all")
    if "close" in out.columns:
        out = out[out["close"].notna()]
    elif "Close" in out.columns:
        out = out[out["Close"].notna()]
    return out
