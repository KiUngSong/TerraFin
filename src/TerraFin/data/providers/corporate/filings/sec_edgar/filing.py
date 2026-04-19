import logging
from typing import Any

import pandas as pd

from TerraFin.configuration import load_terrafin_config

from .client import SECClient


log = logging.getLogger(__name__)

# All SEC-filings cache entries live under this single namespace so
# `clear_sec_filings_cache()` wipes everything in one call and the CacheManager
# lifecycle (see `data/cache/policy.py`) covers the whole layer.
SEC_FILINGS_CACHE_NAMESPACE = "sec_filings"

# TTLs reflect how often each dataset actually changes upstream.
_CIK_MAPPING_TTL = 7 * 86_400  # SEC publishes this list; cadence ~monthly.
_SUBMISSIONS_TTL = 86_400  # Recent filings grow daily.
_SUBMISSIONS_HISTORY_TTL = 30 * 86_400  # Paginated history chunks rarely change.

CIK_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_EDGAR_SETUP_EXAMPLE = "Set TERRAFIN_SEC_USER_AGENT='Your Org Name sec-contact@example.com'."

# Process-local ticker→CIK memo. Backed by the file cache via
# `_try_cik_request`, but held in memory to avoid repeated ~1MB JSON reads
# and DataFrame construction on the hot path. `clear_sec_filings_cache()`
# nulls this out so disk + memory stay coherent.
_TICKER2CIK_DICT: dict[Any, Any] | None = None


class SecEdgarError(RuntimeError):
    """Base error for SEC EDGAR access."""


class SecEdgarConfigurationError(SecEdgarError):
    """Raised when SEC EDGAR access is not configured."""


class SecEdgarUnavailableError(SecEdgarError):
    """Raised when SEC EDGAR cannot be reached."""


def sec_edgar_status_message() -> str:
    return (
        "SEC EDGAR access is unavailable until `TERRAFIN_SEC_USER_AGENT` is configured. "
        + SEC_EDGAR_SETUP_EXAMPLE
    )


def sec_edgar_is_configured() -> bool:
    try:
        _sec_user_agent()
        return True
    except SecEdgarConfigurationError:
        return False


def ensure_sec_edgar_configured() -> None:
    _ = _sec_user_agent()


def _sec_user_agent() -> str:
    """Read the required SEC EDGAR user agent from a single env var."""
    explicit = load_terrafin_config().sec_edgar.user_agent
    if explicit:
        return explicit
    raise SecEdgarConfigurationError(sec_edgar_status_message())


def create_sec_client(host_url: str = "data.sec.gov") -> SECClient:
    """Create a SEC client with an env-configurable user agent."""
    return SECClient(_sec_user_agent(), host_url)


def _fetch_json(url: str, *, host_url: str = "data.sec.gov") -> dict[str, Any]:
    log.debug("SEC GET (json) %s", url)
    try:
        client = create_sec_client(host_url=host_url)
        response = client.get(url)
        response.raise_for_status()
        return response.json()
    except SecEdgarError:
        raise
    except Exception as exc:
        log.warning("SEC EDGAR JSON fetch failed for %s: %s", url, exc)
        raise SecEdgarUnavailableError(
            "SEC EDGAR request failed. "
            "Confirm `TERRAFIN_SEC_USER_AGENT` is configured and retry later."
        ) from exc


def _fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
    log.debug("SEC GET (text) %s", url)
    try:
        client = create_sec_client(host_url=host_url)
        response = client.get(url)
        response.raise_for_status()
        return response.content.decode("utf-8")
    except SecEdgarError:
        raise
    except Exception as exc:
        log.warning("SEC EDGAR text fetch failed for %s: %s", url, exc)
        raise SecEdgarUnavailableError(
            "SEC EDGAR filing download failed. "
            "Confirm `TERRAFIN_SEC_USER_AGENT` is configured and retry later."
        ) from exc


# ── File-cache adapters (lazy CacheManager import breaks the circular dep) ──


def _read_cached_dict(key: str, ttl_seconds: int) -> dict | None:
    from TerraFin.data.cache.manager import CacheManager

    payload = CacheManager.file_cache_read(SEC_FILINGS_CACHE_NAMESPACE, key, ttl_seconds)
    return payload if isinstance(payload, dict) else None


def _write_cached_dict(key: str, payload: dict) -> None:
    from TerraFin.data.cache.manager import CacheManager

    CacheManager.file_cache_write(SEC_FILINGS_CACHE_NAMESPACE, key, payload)


def clear_sec_filings_cache() -> None:
    """Clear the unified SEC filings file cache: CIK mapping, submissions, parsed markdown.

    Also resets the in-memory ticker→CIK memo so repeat lookups go back through
    the (now empty) file cache rather than silently serving the stale dict.
    """
    from TerraFin.data.cache.manager import CacheManager

    global _TICKER2CIK_DICT
    _TICKER2CIK_DICT = None
    CacheManager.file_cache_clear(SEC_FILINGS_CACHE_NAMESPACE)


# ── Public API ──────────────────────────────────────────────────────────────


def _try_cik_request() -> dict[str, Any]:
    """Fetch the SEC ticker→CIK mapping, persisted via the shared file cache."""
    cached = _read_cached_dict("cik_mapping", _CIK_MAPPING_TTL)
    if cached is not None:
        return cached

    data = _fetch_json(CIK_URL, host_url="www.sec.gov")
    _write_cached_dict("cik_mapping", data)
    return data


def get_cik_mapping():
    """
    Get mapping of ticker symbols to CIK numbers from SEC.

    Returns:
        pd.DataFrame: DataFrame with company ticker and CIK information
    """
    cik_list = _try_cik_request()
    return pd.DataFrame(cik_list["data"], columns=cik_list["fields"])


def ticker_to_cik_dict() -> dict[Any, Any] | Any:
    """Get a dictionary mapping ticker symbols to CIK numbers (uncached)."""
    cik_df = get_cik_mapping()
    return cik_df.set_index("ticker")["cik"].to_dict()


def get_ticker_to_cik_dict_cached() -> dict[Any, Any]:
    """Memoized ticker→CIK lookup. Reset by `clear_sec_filings_cache()`."""
    global _TICKER2CIK_DICT
    if _TICKER2CIK_DICT is None:
        _TICKER2CIK_DICT = ticker_to_cik_dict()
    return _TICKER2CIK_DICT


def _block_to_df(block: dict, target_filing_form: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(block)
    if df.empty or "form" not in df.columns:
        return df
    return df[df.form.isin(target_filing_form)]


def _submissions_cache_key(cik: int, history_name: str | None = None) -> str:
    if history_name:
        return f"submissions_history_{history_name}"
    return f"submissions_{cik}"


def get_company_filings(
    cik: int | None,
    include_8k: bool = False,
    include_history: bool = False,
) -> pd.DataFrame | None:
    """
    Get SEC filings (8-K, 10-K, 10-Q) for a company by CIK.

    Args:
        cik: Company CIK number
        include_8k: Whether to include 8-K filings (default: False)
        include_history: If True, paginate through `filings.files` to include
            older filings beyond the 1000-entry `recent` block. Each extra file
            adds one HTTP call (or cache hit), so keep this off unless deep
            history is needed.

    Returns:
        pd.DataFrame: DataFrame with filing information, ordered newest-first.

    Filing types:
        8-K: Report of unscheduled material events or corporate event
        10-K: Annual report
        10-Q: Quarterly report
    """
    if cik is None:
        return None

    target_filing_form = ["10-K", "10-Q"]
    if include_8k:
        target_filing_form.append("8-K")

    recent_key = _submissions_cache_key(cik)
    cik_metadata = _read_cached_dict(recent_key, _SUBMISSIONS_TTL)
    if cik_metadata is None:
        url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
        cik_metadata = _fetch_json(url)
        _write_cached_dict(recent_key, cik_metadata)

    filings_meta = cik_metadata.get("filings") or {}
    frames = [_block_to_df(filings_meta.get("recent") or {}, target_filing_form)]

    if include_history:
        for file_info in filings_meta.get("files") or []:
            name = file_info.get("name")
            if not name:
                continue
            hist_key = _submissions_cache_key(cik, name)
            history = _read_cached_dict(hist_key, _SUBMISSIONS_HISTORY_TTL)
            if history is None:
                try:
                    history = _fetch_json(f"https://data.sec.gov/submissions/{name}")
                except SecEdgarError as exc:
                    log.warning("Skipping historical submissions file %s: %s", name, exc)
                    continue
                _write_cached_dict(hist_key, history)
            frames.append(_block_to_df(history, target_filing_form))

    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame()
    return pd.concat(non_empty, ignore_index=True)


def download_filing(cik: int, accession_number: str, file_name: str) -> str:
    """
    Download SEC filing content.

    Raw HTML is not file-cached (filings can exceed 20 MB each). Callers that
    need durable caching should go through `get_sec_data` which caches the
    post-parse markdown via the shared `sec_filings` namespace.
    """
    url = f"https://www.sec.gov/Archives/edgar/data/{str(cik).zfill(10)}/{accession_number}/{file_name}"
    return _fetch_text(url)
