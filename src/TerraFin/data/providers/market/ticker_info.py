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


def get_ticker_info(ticker: str) -> dict:
    """Return yf.Ticker().info for a ticker, cached in memory + file."""
    ticker = ticker.upper()

    if ticker in _INFO_CACHE:
        return dict(_INFO_CACHE[ticker])

    cached = _file_cache().file_cache_read(_NS_INFO, ticker, _FILE_TTL)
    if cached is not None:
        _INFO_CACHE[ticker] = cached
        return dict(cached)

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

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
