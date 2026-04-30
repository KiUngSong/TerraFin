"""Cached yfinance Ticker info and earnings dates.

Provides in-memory + file cache for yf.Ticker().info and .earnings_dates,
which are slow network calls (~1-3s each). Follows the same pattern as
YFINANCE_CACHE in yfinance.py.
"""

import math

import yfinance as yf

from TerraFin.data.cache.policy import ttl_for


_NS_INFO = "market.ticker_info"
_NS_EARNINGS = "market.earnings"
_SOURCE_INFO_PREFIX = "market.ticker_info"
_SOURCE_EARNINGS_PREFIX = "market.earnings"


def _manager():
    """Lazy import to avoid circular dependency."""
    from TerraFin.data.cache.registry import get_cache_manager

    return get_cache_manager()


def _ensure_info_source(ticker: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec

    source = f"{_SOURCE_INFO_PREFIX}.{ticker}"
    manager = _manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_NS_INFO,
                key=ticker,
                ttl_seconds=ttl_for("market.ticker_info"),
                fetch_fn=lambda t=ticker: _fetch_info(t),
                # See _fetch_earnings: serve {} on transient block so the
                # dashboard renders, but don't cache the failure.
                fallback_fn=lambda: {},
            )
        )
    return source


def _ensure_earnings_source(ticker: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec

    source = f"{_SOURCE_EARNINGS_PREFIX}.{ticker}"
    manager = _manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_NS_EARNINGS,
                key=ticker,
                ttl_seconds=ttl_for("market.earnings"),
                fetch_fn=lambda t=ticker: _fetch_earnings(t),
                # When fetch raises (transient upstream block), serve [] so
                # the dashboard still renders. The fallback path is NOT
                # cached, so the next request retries the real fetch.
                fallback_fn=lambda: [],
            )
        )
    return source


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


def _search_quote_metadata(ticker: str) -> dict:
    """Yahoo Search fallback for fields missing from yf.Ticker.info.

    Yahoo's quoteSummary endpoint (which `.info` hits) returns 401/429 on
    many shared cloud IPs (HuggingFace Spaces, AWS, Cloudflare workers, etc.).
    The public `/v1/finance/search` endpoint is on a different rate budget
    and reliably returns `quoteType`, `shortname`, `longname`, `exchange`
    even when `.info` is empty. Used to recover ETF detection in particular.
    """
    try:
        import requests
    except ImportError:
        return {}
    try:
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": ticker, "quotesCount": 5, "newsCount": 0, "lang": "en-US"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=4,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}
    target = ticker.upper()
    for q_item in data.get("quotes", []) or []:
        sym = (q_item.get("symbol") or "").upper()
        if sym != target:
            continue
        out: dict = {}
        if q_item.get("quoteType"):
            out["quoteType"] = q_item["quoteType"]
        if q_item.get("shortname") or q_item.get("longname"):
            out["shortName"] = q_item.get("shortname") or q_item.get("longname")
        if q_item.get("exchange"):
            out["exchange"] = q_item["exchange"]
        return out
    return {}


def _fetch_info(ticker: str) -> dict:
    """Fetch yfinance .info with cloud-IP fallbacks.

    `.info` hits Yahoo's quoteSummary endpoint — frequently 401/429 on
    shared cloud IPs (HF Spaces, AWS). When that happens, `fast_info` +
    history give us price/range, and the search endpoint gives quoteType
    + identity. If even those fallbacks can't recover price-and-identity,
    raise so the cache layer doesn't pin a near-empty dict for the full
    24h TTL — the next request retries.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
    except Exception as exc:
        raise RuntimeError(f"yfinance Ticker init failed for {ticker}: {exc}") from exc

    info: dict = {}
    info_call_failed = False
    try:
        raw = ticker_obj.info
    except Exception:
        info_call_failed = True
        raw = None
    if raw is None:
        info_call_failed = info_call_failed or True
        info = {}
    elif isinstance(raw, dict):
        info = dict(raw)
    else:
        info = _mapping_from_object(raw)

    info = _merge_missing(info, _fast_info_fallback(ticker_obj))

    # Cloud-IP fallback: graft quoteType/shortName/exchange from Yahoo Search
    # when the heavier quoteSummary endpoint returned nothing useful for them.
    if not info.get("quoteType") or not info.get("shortName"):
        info = _merge_missing(info, _search_quote_metadata(ticker))

    # If .info itself failed AND fallbacks didn't recover the minimum
    # signals (price + identity), this is a suspected upstream block.
    # Raise so the cache layer falls through to the fallback_fn instead
    # of pinning the degraded payload for 24h.
    if info_call_failed:
        has_price = info.get("currentPrice") is not None or info.get("regularMarketPrice") is not None
        has_identity = bool(info.get("quoteType")) or bool(info.get("shortName"))
        if not (has_price and has_identity):
            raise RuntimeError(
                f"yfinance .info blocked for {ticker} and fallbacks insufficient"
            )

    return info


def get_ticker_info(ticker: str) -> dict:
    """Return yf.Ticker().info for a ticker, cached via CacheManager."""
    ticker = ticker.upper()
    source = _ensure_info_source(ticker)
    result = _manager().get_payload(source)
    payload = result.payload if isinstance(result.payload, dict) else {}
    return dict(payload)


def get_ticker_earnings(ticker: str) -> list[dict]:
    """Return earnings history for a ticker, cached via CacheManager.

    Each entry: {"date", "epsEstimate", "epsReported", "surprise", "surprisePercent"}.
    """
    ticker = ticker.upper()
    source = _ensure_earnings_source(ticker)
    result = _manager().get_payload(source)
    payload = result.payload if isinstance(result.payload, list) else []
    return list(payload)


def _fetch_earnings(ticker: str) -> list[dict]:
    """Fetch and normalize earnings_dates from yfinance.

    Raises on suspected upstream failure so the cache layer falls back to
    stale data instead of writing an empty list for the full TTL window.
    yfinance silently returns None when Yahoo rate-limits a shared cloud
    IP (HF Spaces, AWS) — distinguishing that from a legitimately empty
    history requires treating None as a signal for re-fetch.
    """
    try:
        t = yf.Ticker(ticker)
    except Exception as exc:
        raise RuntimeError(f"yfinance Ticker init failed for {ticker}: {exc}") from exc
    try:
        df = t.earnings_dates
    except Exception as exc:
        # Covers YFRateLimitError plus assorted upstream HTTP errors.
        raise RuntimeError(f"earnings_dates fetch failed for {ticker}: {exc}") from exc
    if df is None:
        # Suspected upstream block — re-raise so the cache layer keeps any
        # prior good payload instead of pinning an empty list.
        raise RuntimeError(
            f"earnings_dates returned None for {ticker} (suspected upstream block)"
        )
    if df.empty:
        return []  # Legitimately no earnings on file

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
    """Clear all per-ticker info / earnings payloads via CacheManager."""
    from TerraFin.data.cache.manager import CacheManager

    manager = _manager()
    for source in list(manager._payload_specs.keys()):
        if source.startswith(_SOURCE_INFO_PREFIX + ".") or source.startswith(_SOURCE_EARNINGS_PREFIX + "."):
            manager.clear_payload(source)
    CacheManager.file_cache_clear(_NS_INFO)
    CacheManager.file_cache_clear(_NS_EARNINGS)
