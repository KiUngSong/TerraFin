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


def bar_date(frame: pd.DataFrame, index: int) -> str | None:
    """ISO date of one bar, or None when the frame carries no usable time.

    Positional, and resolved through `_ensure_dt_index`: a `TimeSeriesDataFrame`
    keeps time as a column under a `RangeIndex`, so reading `frame.index`
    directly would yield an integer on every production frame.
    """
    try:
        return _ensure_dt_index(frame).index[index].date().isoformat()
    except (IndexError, AttributeError, TypeError, ValueError):
        return None


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
    window = series[-(lookback + 1) :]
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


# Each market's own broad index: a name is gated on the market it trades in.
# KOSPI and KOSDAQ are separate reads — their close-vs-SMA50 verdicts disagree
# on roughly a fifth of sessions, so one cannot stand in for the other.
_KOSPI_INDEX = "^KS11"
_KOSDAQ_INDEX = "^KQ11"

# symbol -> (calendar date, above its SMA)
_REGIME_CACHE: dict[str, tuple[object, bool]] = {}
_REGIME_LOCK = threading.Lock()


def index_trend_ok(symbol: str, period: int = 50) -> bool | None:
    """Index close > N-day SMA — the regime read a bullish-entry gate uses.

    Cached per symbol per calendar day to avoid hammering the data pipeline on
    every detector call. Returns ``None`` when the index is unavailable, which
    a caller must treat as "unknown" rather than "bad regime".
    """
    from datetime import date as _date

    today = _date.today()
    with _REGIME_LOCK:
        cached = _REGIME_CACHE.get(symbol)
        if cached is not None and cached[0] == today:
            return cached[1]
    try:
        from TerraFin.data import get_data_factory

        df = get_data_factory().get_market_data(symbol)
        cs = closes(df)
        if len(cs) < period + 1:
            return None
        ma = sum(cs[-period:]) / period
        ok = bool(cs[-1] > ma)
    except Exception:
        return None
    with _REGIME_LOCK:
        _REGIME_CACHE[symbol] = (today, ok)
    return ok


def spy_trend_ok(period: int = 50) -> bool | None:
    """SPY's regime read. See `index_trend_ok`."""
    return index_trend_ok("SPY", period)


def venue_trend_ok(ticker: str, period: int = 50) -> bool | None:
    """The regime read for the market `ticker` trades in.

    A KRX name is gated on its own board, not on SPY: gating it on a US index
    measures the wrong market, and dropping the gate entirely restores exactly
    the ungated configuration the bear-period backtests found negative-edge.
    A bare 6-digit code carries no board, so it reads KOSPI.
    """
    if is_krx_ticker(ticker):
        board = _KOSDAQ_INDEX if ticker.strip().upper().endswith(".KQ") else _KOSPI_INDEX
        return index_trend_ok(board, period)
    return index_trend_ok("SPY", period)


def week_ending(weekly: pd.DataFrame) -> str | None:
    """ISO date of the last completed weekly bar, for dedup keying.

    A weekly signal must be unique per DATA week, not per run day: the EOD
    weekly pass runs Mon-Fri, and on KRX Friday's run already sees its own
    completed week while Mon-Thu still see the previous one. Keying on the run
    date therefore both duplicates a week and collides two different weeks.
    """
    try:
        return weekly.index[-1].date().isoformat()
    except (IndexError, AttributeError):
        return None


def is_krx_ticker(ticker: str) -> bool:
    """6-digit code, bare or with a Yahoo .KS/.KQ suffix."""
    t = (ticker or "").strip()
    if t.isdigit() and len(t) == 6:
        return True
    core, _, suffix = t.partition(".")
    # Suffix compared case-insensitively so this agrees with DataFactory's
    # `is_krx_venue`, which uppercases before comparing.
    return suffix.upper() in ("KS", "KQ") and core.isdigit() and len(core) == 6


def weekly_bars(ohlc: pd.DataFrame, ticker: str = "") -> pd.DataFrame:
    """W-FRI bars with a genuinely partial trailing week dropped.

    A week that has not reached its Friday sums only the elapsed days, so its
    volume understates and its close is not a weekly close. Keeping it makes a
    weekly signal depend on which weekday the scan runs.

    Completeness is judged against the SESSION calendar, not the Friday label. A
    holiday Friday looked partial on every run — KRX 2025-10-03, with the next
    week closed for Chuseok — and because the following observed bar belongs to a
    later week, that week never became the last bar and its signals were lost
    outright. Without a calendar answer, fall back to the date comparison.
    """
    weekly = resample(ohlc, "W-FRI")
    try:
        last_daily = _ensure_dt_index(ohlc).index[-1].date()
        if not len(weekly):
            return weekly
        # Compare calendar dates: tz-safe if the market-data index ever becomes
        # tz-aware, where a naive/aware comparison would raise and skip the drop.
        label = weekly.index[-1].date()
        if label > last_daily:
            from TerraFin.data.providers.market.sessions import last_session_on_or_before

            final_session = last_session_on_or_before(label, ticker)
            if final_session is None or last_daily < final_session:
                weekly = weekly.iloc[:-1]
    except (IndexError, AttributeError, KeyError, ImportError):
        pass
    return weekly


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
