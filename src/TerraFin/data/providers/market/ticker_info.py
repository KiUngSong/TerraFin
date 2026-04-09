"""Cached yfinance Ticker info and earnings dates.

Provides in-memory + file cache for yf.Ticker().info and .earnings_dates,
which are slow network calls (~1-3s each). Follows the same pattern as
YFINANCE_CACHE in yfinance.py.
"""

import math

import yfinance as yf


_INFO_CACHE: dict[str, dict] = {}
_EARNINGS_CACHE: dict[str, list[dict]] = {}

_NS_INFO = "ticker_info"
_NS_EARNINGS = "ticker_earnings"
_FILE_TTL = 86_400  # 24h


def _file_cache():
    """Lazy import to avoid circular dependency."""
    from TerraFin.data.cache.manager import CacheManager

    return CacheManager


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _mapping_from_object(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    keys = getattr(value, "keys", None)
    if callable(keys):
        try:
            return {str(key): value[key] for key in keys()}
        except Exception:
            return {}
    try:
        return dict(value)
    except Exception:
        return {}


def _first_available(mapping: dict, *keys: str):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _history_column(frame, *names: str):
    if frame is None or getattr(frame, "empty", True):
        return None
    lowered = {str(column).lower(): column for column in frame.columns}
    for name in names:
        column = lowered.get(name.lower())
        if column is not None:
            return frame[column]
    return None


def _merge_missing(base: dict, fallback: dict) -> dict:
    if not fallback:
        return dict(base)
    merged = dict(base)
    for key, value in fallback.items():
        if merged.get(key) is None:
            merged[key] = value
    return merged


def _fast_info_fallback(ticker_obj) -> dict:
    fallback: dict = {}

    try:
        fast_info = _mapping_from_object(getattr(ticker_obj, "fast_info", None))
    except Exception:
        fast_info = {}

    current_price = _safe_float(_first_available(fast_info, "lastPrice", "last_price", "regularMarketPrice"))
    previous_close = _safe_float(
        _first_available(fast_info, "previousClose", "previous_close", "regularMarketPreviousClose")
    )
    market_cap = _safe_float(_first_available(fast_info, "marketCap", "market_cap"))
    year_high = _safe_float(_first_available(fast_info, "yearHigh", "year_high"))
    year_low = _safe_float(_first_available(fast_info, "yearLow", "year_low"))
    exchange = _first_available(fast_info, "exchange")

    history = None
    try:
        history = ticker_obj.history(period="1y", auto_adjust=True)
    except Exception:
        history = None

    if history is not None and not history.empty:
        close_series = _history_column(history, "close")
        high_series = _history_column(history, "high", "close")
        low_series = _history_column(history, "low", "close")

        if close_series is not None and not close_series.empty:
            if current_price is None:
                current_price = _safe_float(close_series.iloc[-1])
            if previous_close is None:
                baseline = close_series.iloc[-2] if len(close_series) > 1 else close_series.iloc[-1]
                previous_close = _safe_float(baseline)
        if high_series is not None and not high_series.empty and year_high is None:
            year_high = _safe_float(high_series.max())
        if low_series is not None and not low_series.empty and year_low is None:
            year_low = _safe_float(low_series.min())

    if current_price is not None:
        fallback["currentPrice"] = current_price
        fallback["regularMarketPrice"] = current_price
    if previous_close is not None:
        fallback["previousClose"] = previous_close
        fallback["regularMarketPreviousClose"] = previous_close
    if market_cap is not None:
        fallback["marketCap"] = market_cap
    if year_high is not None:
        fallback["fiftyTwoWeekHigh"] = year_high
    if year_low is not None:
        fallback["fiftyTwoWeekLow"] = year_low
    if exchange is not None:
        fallback["exchange"] = exchange

    return fallback


def get_ticker_info(ticker: str) -> dict:
    """Return yf.Ticker().info for a ticker, cached in memory + file."""
    ticker = ticker.upper()

    if ticker in _INFO_CACHE:
        return dict(_INFO_CACHE[ticker])

    cached = _file_cache().file_cache_read(_NS_INFO, ticker, _FILE_TTL)
    if cached is not None:
        _INFO_CACHE[ticker] = cached
        return dict(cached)

    info: dict = {}
    ticker_obj = None
    try:
        ticker_obj = yf.Ticker(ticker)
    except Exception:
        ticker_obj = None

    if ticker_obj is not None:
        try:
            info = ticker_obj.info or {}
        except Exception:
            info = {}
        if not isinstance(info, dict):
            info = _mapping_from_object(info)
        info = _merge_missing(info, _fast_info_fallback(ticker_obj))

    _INFO_CACHE[ticker] = info

    try:
        _file_cache().file_cache_write(_NS_INFO, ticker, info)
    except Exception:
        pass

    return dict(info)


def get_ticker_earnings(ticker: str) -> list[dict]:
    """Return earnings history for a ticker, cached in memory + file.

    Each entry: {"date", "epsEstimate", "epsReported", "surprise", "surprisePercent"}.
    """
    ticker = ticker.upper()

    if ticker in _EARNINGS_CACHE:
        return list(_EARNINGS_CACHE[ticker])

    cached = _file_cache().file_cache_read(_NS_EARNINGS, ticker, _FILE_TTL)
    if cached is not None:
        _EARNINGS_CACHE[ticker] = cached
        return list(cached)

    earnings = _fetch_earnings(ticker)
    _EARNINGS_CACHE[ticker] = earnings

    try:
        _file_cache().file_cache_write(_NS_EARNINGS, ticker, earnings)
    except Exception:
        pass

    return list(earnings)


def _fetch_earnings(ticker: str) -> list[dict]:
    """Fetch and normalize earnings_dates from yfinance."""
    try:
        t = yf.Ticker(ticker)
        df = t.earnings_dates
        if df is None or df.empty:
            return []
    except Exception:
        return []

    records: list[dict] = []
    for idx, row in df.iterrows():
        date_str = str(idx)[:10] if idx is not None else ""
        estimate = _safe_float(row.get("EPS Estimate"))
        reported = _safe_float(row.get("Reported EPS"))
        surprise = _safe_float(row.get("Surprise(%)"))

        records.append(
            {
                "date": date_str,
                "epsEstimate": _fmt(estimate),
                "epsReported": _fmt(reported),
                "surprise": _fmt(reported - estimate) if estimate is not None and reported is not None else "-",
                "surprisePercent": _fmt(surprise, suffix="%") if surprise is not None else "-",
            }
        )

    return records


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _fmt(val: float | None, suffix: str = "") -> str:
    if val is None:
        return "-"
    return f"{val:.2f}{suffix}"


def clear_ticker_info_cache() -> None:
    """Clear both memory and file caches."""
    _INFO_CACHE.clear()
    _EARNINGS_CACHE.clear()
    _file_cache().file_cache_clear(_NS_INFO)
    _file_cache().file_cache_clear(_NS_EARNINGS)
