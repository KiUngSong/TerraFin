"""CUSIP -> ticker resolution via OpenFIGI mapping.

Used to enrich SEC 13F holdings rows (which carry CUSIP + nameOfIssuer but no
ticker) with canonical ticker symbols so the agent can hand them to
ticker-input tools (`company_info`, `earnings`, `financials`, ...) without
guessing.

Free OpenFIGI tier: 25 req/s, no auth required. With an API key the limit
rises, but we don't depend on one. Resolution failures (unmapped CUSIP, ETF
unit trusts without an exchange ticker, network error) return `None` and the
caller is expected to leave `Ticker` null on the row.

Results cache on disk via `CacheManager.file_cache_*`. CUSIP -> ticker is
stable enough that we cache for 90 days; on the rare ticker-change event the
worst case is one quarter of stale data, which is acceptable for a 13F flow
that itself only updates quarterly.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests


log = logging.getLogger(__name__)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_CACHE_NAMESPACE = "cusip_ticker"
_CACHE_MAX_SECONDS = 90 * 86400  # 90 days
_REQUEST_TIMEOUT = 8.0
_CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")

# Common-share class codes preferred when OpenFIGI returns multiple matches.
# Picks the primary US listing over ADRs/preferred/foreign trackers.
_PREFERRED_EXCHANGE_CODES = ("US", "UV", "UN", "UQ", "UA", "UR")


def _is_valid_cusip(cusip: str) -> bool:
    return bool(_CUSIP_RE.match(cusip))


def _select_ticker(entries: list[dict[str, Any]]) -> str | None:
    """Pick the best ticker from an OpenFIGI `data` array.

    Prefers entries with a US composite exchange code; falls back to the first
    entry that has a non-empty ticker.
    """
    for code in _PREFERRED_EXCHANGE_CODES:
        for entry in entries:
            if str(entry.get("exchCode", "")).upper() == code:
                ticker = str(entry.get("ticker", "")).strip()
                if ticker:
                    return ticker.upper()
    for entry in entries:
        ticker = str(entry.get("ticker", "")).strip()
        if ticker:
            return ticker.upper()
    return None


def resolve_cusip_to_ticker(cusip: str) -> str | None:
    """Resolve a 9-character CUSIP to a US ticker symbol, or None if unknown.

    Caches both hits and misses (miss stored as empty string sentinel).
    Network/parse errors are logged and treated as misses without poisoning
    the cache.
    """
    cusip = (cusip or "").strip().upper()
    if not _is_valid_cusip(cusip):
        return None

    from TerraFin.data.cache.manager import CacheManager

    cached = CacheManager.file_cache_read(_CACHE_NAMESPACE, cusip, _CACHE_MAX_SECONDS)
    if cached is not None:
        ticker = cached.get("ticker") if isinstance(cached, dict) else None
        return ticker or None

    body = [{"idType": "ID_CUSIP", "idValue": cusip}]
    try:
        response = requests.post(_OPENFIGI_URL, json=body, timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("OpenFIGI mapping request failed for CUSIP %s: %s", cusip, exc)
        return None

    if response.status_code != 200:
        log.warning("OpenFIGI mapping non-200 for CUSIP %s: %s", cusip, response.status_code)
        return None

    try:
        results = response.json()
    except ValueError:
        log.warning("OpenFIGI mapping returned non-JSON for CUSIP %s", cusip)
        return None

    ticker: str | None = None
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            data = first.get("data")
            if isinstance(data, list) and data:
                ticker = _select_ticker([d for d in data if isinstance(d, dict)])

    CacheManager.file_cache_write(_CACHE_NAMESPACE, cusip, {"ticker": ticker or ""})
    return ticker


def clear_cusip_resolver_cache() -> None:
    """Clear the CUSIP->ticker resolution cache."""
    from TerraFin.data.cache.manager import CacheManager

    CacheManager.file_cache_clear(_CACHE_NAMESPACE)
