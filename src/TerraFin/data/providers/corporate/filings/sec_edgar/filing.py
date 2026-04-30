import logging
from typing import Any

import pandas as pd

from TerraFin.configuration import load_terrafin_config
from TerraFin.data.cache.policy import ttl_for

from .client import SECClient


log = logging.getLogger(__name__)

# Parsed-markdown cache (step 5, not migrated) still lives under this namespace.
SEC_FILINGS_CACHE_NAMESPACE = "sec_filings"

# Managed-cache namespaces for the index/CIK paths (step 4 migration).
SEC_CIK_NAMESPACE = "sec.cik"
SEC_SUBMISSIONS_NAMESPACE = "sec.submissions"

_CIK_MAPPING_SOURCE = "sec.cik.mapping"
_CIK_MAPPING_KEY = "mapping"
_TICKER_TO_CIK_SOURCE = "sec.cik.ticker_to_cik"
_TICKER_TO_CIK_KEY = "ticker_to_cik"

CIK_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_EDGAR_SETUP_EXAMPLE = "Set TERRAFIN_SEC_USER_AGENT='Your Org Name sec-contact@example.com'."


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


# ── Managed-cache wiring ────────────────────────────────────────────────────


def _ensure_cik_mapping_registered() -> None:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    manager = get_cache_manager()
    manager.register_payload(
        CachePayloadSpec(
            source=_CIK_MAPPING_SOURCE,
            namespace=SEC_CIK_NAMESPACE,
            key=_CIK_MAPPING_KEY,
            ttl_seconds=ttl_for("sec.cik"),
            fetch_fn=lambda: _fetch_json(CIK_URL, host_url="www.sec.gov"),
        )
    )
    manager.register_payload(
        CachePayloadSpec(
            source=_TICKER_TO_CIK_SOURCE,
            namespace=SEC_CIK_NAMESPACE,
            key=_TICKER_TO_CIK_KEY,
            ttl_seconds=ttl_for("sec.cik"),
            fetch_fn=_build_ticker_to_cik_dict,
        )
    )


def _build_ticker_to_cik_dict() -> dict[str, Any]:
    cik_list = _try_cik_request()
    df = pd.DataFrame(cik_list["data"], columns=cik_list["fields"])
    return df.set_index("ticker")["cik"].to_dict()


def _submissions_source(cik: int) -> str:
    return f"sec.submissions.{cik}"


def _submissions_history_source(name: str) -> str:
    return f"sec.submissions.history.{name}"


def _ensure_submissions_registered(cik: int) -> None:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    get_cache_manager().register_payload(
        CachePayloadSpec(
            source=_submissions_source(cik),
            namespace=SEC_SUBMISSIONS_NAMESPACE,
            key=str(cik),
            ttl_seconds=ttl_for("sec.submissions"),
            fetch_fn=lambda url=url: _fetch_json(url),
        )
    )


def _ensure_submissions_history_registered(name: str) -> None:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    url = f"https://data.sec.gov/submissions/{name}"
    get_cache_manager().register_payload(
        CachePayloadSpec(
            source=_submissions_history_source(name),
            namespace=SEC_SUBMISSIONS_NAMESPACE,
            key=f"history_{name}",
            ttl_seconds=ttl_for("sec.submissions.history"),
            fetch_fn=lambda url=url: _fetch_json(url),
        )
    )


def clear_sec_index_cache() -> None:
    """Clear all managed CIK + submissions payload sources and their on-disk dirs."""
    from TerraFin.data.cache.manager import CacheManager
    from TerraFin.data.cache.registry import get_cache_manager

    manager = get_cache_manager()
    for source in list(manager._payload_specs):
        if source.startswith("sec.cik.") or source.startswith("sec.submissions."):
            manager.clear_payload(source)
    CacheManager.file_cache_clear(SEC_CIK_NAMESPACE)
    CacheManager.file_cache_clear(SEC_SUBMISSIONS_NAMESPACE)


def clear_sec_filings_cache() -> None:
    """Clear every SEC-filings cache: CIK map, submissions, parsed markdown."""
    from TerraFin.data.cache.manager import CacheManager
    from TerraFin.data.cache.registry import get_cache_manager

    clear_sec_index_cache()
    manager = get_cache_manager()
    for source in list(manager._payload_specs):
        if source.startswith("sec.parsed."):
            manager.clear_payload(source)
    CacheManager.file_cache_clear(SEC_FILINGS_CACHE_NAMESPACE)


# ── Public API ──────────────────────────────────────────────────────────────


def _try_cik_request() -> dict[str, Any]:
    """Fetch the SEC ticker→CIK mapping, persisted via the managed cache."""
    from TerraFin.data.cache.registry import get_cache_manager

    _ensure_cik_mapping_registered()
    result = get_cache_manager().get_payload(_CIK_MAPPING_SOURCE)
    return result.payload  # type: ignore[return-value]


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
    """Ticker→CIK lookup served from the managed cache."""
    from TerraFin.data.cache.registry import get_cache_manager

    _ensure_cik_mapping_registered()
    return get_cache_manager().get_payload(_TICKER_TO_CIK_SOURCE).payload  # type: ignore[return-value]


def _block_to_df(block: dict, target_filing_form: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(block)
    if df.empty or "form" not in df.columns:
        return df
    return df[df.form.isin(target_filing_form)]


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

    from TerraFin.data.cache.registry import get_cache_manager

    target_filing_form = ["10-K", "10-Q"]
    if include_8k:
        target_filing_form.append("8-K")

    _ensure_submissions_registered(cik)
    cik_metadata = get_cache_manager().get_payload(_submissions_source(cik)).payload
    if not isinstance(cik_metadata, dict):
        cik_metadata = {}

    filings_meta = cik_metadata.get("filings") or {}
    frames = [_block_to_df(filings_meta.get("recent") or {}, target_filing_form)]

    if include_history:
        for file_info in filings_meta.get("files") or []:
            name = file_info.get("name")
            if not name:
                continue
            _ensure_submissions_history_registered(name)
            try:
                history = get_cache_manager().get_payload(_submissions_history_source(name)).payload
            except SecEdgarError as exc:
                log.warning("Skipping historical submissions file %s: %s", name, exc)
                continue
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
