"""CUSIP -> ticker resolution via OpenFIGI mapping.

Used to enrich SEC 13F holdings rows (which carry CUSIP + nameOfIssuer but no
ticker) with canonical ticker symbols so the agent can hand them to
ticker-input tools (`company_info`, `earnings`, `financials`, ...) without
guessing.

Free OpenFIGI tier: 25 requests per MINUTE without an API key — not per
second. A 13F row set is resolved through `resolve_cusips_to_tickers`, which
batches up to `_MAX_JOBS_PER_REQUEST` CUSIPs per POST, so an 89-position
portfolio costs 9 requests rather than 89. Resolution failures (unmapped
CUSIP, ETF unit trusts without an exchange ticker, network error) return
`None` and the caller is expected to leave `Ticker` null on the row.

Results cache on disk via `CacheManager.file_cache_*`. CUSIP -> ticker is
stable enough that we cache for 90 days; on the rare ticker-change event the
worst case is one quarter of stale data, which is acceptable for a 13F flow
that itself only updates quarterly.

Transport failures (429, 5xx, timeout, non-JSON) cache separately and briefly
in `_FAILURE_NAMESPACE`. Without that, a rate-limited CUSIP is re-requested on
every page render: one guru with 6 throttled CUSIPs cost 4.0s per click, every
click, because nothing recorded that the call had just failed.
"""

import logging
import re
from collections.abc import Iterable
from typing import Any

import requests


log = logging.getLogger(__name__)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_CACHE_NAMESPACE = "cusip_ticker"
_CACHE_MAX_SECONDS = 90 * 86400  # 90 days
_REQUEST_TIMEOUT = 8.0
_CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")

# Transport failures are retried, but not on every render. OpenFIGI's
# unauthenticated window is a minute, so two minutes outlasts it while still
# recovering inside the same browsing session.
_FAILURE_NAMESPACE = "cusip_ticker_failed"
_FAILURE_TTL_SECONDS = 120

# OpenFIGI accepts 10 jobs per unauthenticated /v3/mapping POST.
_MAX_JOBS_PER_REQUEST = 10

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


def _read_cached_ticker(cusip: str) -> tuple[bool, str | None]:
    """Return (was_cached, ticker). A cached miss reads back as (True, None)."""
    from TerraFin.data.cache.manager import CacheManager

    cached = CacheManager.file_cache_read(_CACHE_NAMESPACE, cusip, _CACHE_MAX_SECONDS)
    if cached is None:
        return False, None
    ticker = cached.get("ticker") if isinstance(cached, dict) else None
    return True, (ticker or None)


def _failed_recently(cusip: str) -> bool:
    """True when the last attempt failed in transport inside the retry window."""
    from TerraFin.data.cache.manager import CacheManager

    return CacheManager.file_cache_read(_FAILURE_NAMESPACE, cusip, _FAILURE_TTL_SECONDS) is not None


def _record_failures(cusips: list[str], reason: str) -> None:
    from TerraFin.data.cache.manager import CacheManager

    for cusip in cusips:
        CacheManager.file_cache_write(_FAILURE_NAMESPACE, cusip, {"reason": reason})


def _tickers_from_results(results: Any, batch: list[str]) -> dict[str, str | None]:
    """Map an OpenFIGI response back onto the CUSIPs that produced it.

    OpenFIGI answers positionally: `results[i]` belongs to `jobs[i]`.
    """
    mapped: dict[str, str | None] = {}
    if not isinstance(results, list):
        return mapped
    for cusip, result in zip(batch, results, strict=True):
        ticker: str | None = None
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, list) and data:
                ticker = _select_ticker([d for d in data if isinstance(d, dict)])
        mapped[cusip] = ticker
    return mapped


def resolve_cusips_to_tickers(cusips: Iterable[str]) -> dict[str, str | None]:
    """Resolve many CUSIPs, batching the OpenFIGI POSTs.

    Keyed by normalised CUSIP. Cache hits (including cached misses) cost no
    request, and a CUSIP whose last attempt failed within
    `_FAILURE_TTL_SECONDS` is skipped and reported as None rather than retried.
    """
    from TerraFin.data.cache.manager import CacheManager

    resolved: dict[str, str | None] = {}
    pending: list[str] = []

    for raw in cusips:
        cusip = (raw or "").strip().upper()
        if not _is_valid_cusip(cusip) or cusip in resolved or cusip in pending:
            continue
        was_cached, ticker = _read_cached_ticker(cusip)
        if was_cached:
            resolved[cusip] = ticker
        elif _failed_recently(cusip):
            resolved[cusip] = None
        else:
            pending.append(cusip)

    for start in range(0, len(pending), _MAX_JOBS_PER_REQUEST):
        batch = pending[start : start + _MAX_JOBS_PER_REQUEST]
        body = [{"idType": "ID_CUSIP", "idValue": cusip} for cusip in batch]
        try:
            response = requests.post(_OPENFIGI_URL, json=body, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("OpenFIGI mapping request failed for %d CUSIP(s): %s", len(batch), exc)
            _record_failures(batch, "request-error")
            resolved.update(dict.fromkeys(batch))
            continue

        if response.status_code != 200:
            log.warning(
                "OpenFIGI mapping non-200 for %d CUSIP(s): %s", len(batch), response.status_code
            )
            _record_failures(batch, f"http-{response.status_code}")
            resolved.update(dict.fromkeys(batch))
            continue

        try:
            results = response.json()
        except ValueError:
            log.warning("OpenFIGI mapping returned non-JSON for %d CUSIP(s)", len(batch))
            _record_failures(batch, "non-json")
            resolved.update(dict.fromkeys(batch))
            continue

        # OpenFIGI answers positionally and length-preservingly: an unmappable
        # job returns an `error` object at its own index. A short array means we
        # cannot tell which job each result belongs to, so nothing may be
        # written to the 90-day namespace — a wrong "" there would outlive the
        # incident by three months.
        if not isinstance(results, list) or len(results) != len(batch):
            log.warning(
                "OpenFIGI returned %s result(s) for %d job(s); treating the batch as failed",
                len(results) if isinstance(results, list) else "non-list",
                len(batch),
            )
            _record_failures(batch, "length-mismatch")
            resolved.update(dict.fromkeys(batch))
            continue

        mapped = _tickers_from_results(results, batch)
        for cusip in batch:
            ticker = mapped.get(cusip)
            CacheManager.file_cache_write(_CACHE_NAMESPACE, cusip, {"ticker": ticker or ""})
            resolved[cusip] = ticker

    return resolved


def resolve_cusip_to_ticker(cusip: str) -> str | None:
    """Resolve a 9-character CUSIP to a US ticker symbol, or None if unknown.

    Caches both hits and misses (miss stored as an empty-string sentinel).
    Transport failures cache briefly in `_FAILURE_NAMESPACE` so a rate-limited
    CUSIP is not re-requested on every render.
    """
    normalised = (cusip or "").strip().upper()
    if not _is_valid_cusip(normalised):
        return None
    return resolve_cusips_to_tickers([normalised]).get(normalised)


def clear_cusip_resolver_cache() -> None:
    """Clear the CUSIP->ticker resolution cache, successes and failures both."""
    from TerraFin.data.cache.manager import CacheManager

    CacheManager.file_cache_clear(_CACHE_NAMESPACE)
    CacheManager.file_cache_clear(_FAILURE_NAMESPACE)
