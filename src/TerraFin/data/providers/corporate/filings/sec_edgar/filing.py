from typing import Any

import pandas as pd
from cachetools import TTLCache

from TerraFin.configuration import load_terrafin_config

from .client import SECClient


# Create a cache with a time-to-live (TTL) of 60 seconds
cache = TTLCache(maxsize=1024, ttl=60)

# Define the URL, headers, and session.
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
    try:
        client = create_sec_client(host_url=host_url)
        response = client.get(url)
        response.raise_for_status()
        return response.json()
    except SecEdgarError:
        raise
    except Exception as exc:
        raise SecEdgarUnavailableError(
            "SEC EDGAR request failed. "
            "Confirm `TERRAFIN_SEC_USER_AGENT` is configured and retry later."
        ) from exc


def _fetch_text(url: str, *, host_url: str = "www.sec.gov") -> str:
    try:
        client = create_sec_client(host_url=host_url)
        response = client.get(url)
        response.raise_for_status()
        return response.content.decode("utf-8")
    except SecEdgarError:
        raise
    except Exception as exc:
        raise SecEdgarUnavailableError(
            "SEC EDGAR filing download failed. "
            "Confirm `TERRAFIN_SEC_USER_AGENT` is configured and retry later."
        ) from exc


def _try_cik_request():
    """Try to request CIK data with optional proxy."""
    # Check if the response is cached
    cached_response = cache.get(CIK_URL)
    if cached_response:
        return cached_response.json()

    # Make the request
    client = create_sec_client(host_url="www.sec.gov")
    res = client.get(CIK_URL)
    res.raise_for_status()
    del client

    # Cache the response
    cache[CIK_URL] = res

    return res.json()


def get_cik_mapping():
    """
    Get mapping of ticker symbols to CIK numbers from SEC.

    Returns:
        pd.DataFrame: DataFrame with company ticker and CIK information
    """
    cik_list = _try_cik_request()

    # Convert the data to a DataFrame
    cik_df = pd.DataFrame(cik_list["data"], columns=cik_list["fields"])
    return cik_df


def ticker_to_cik_dict() -> dict[Any, Any] | Any:
    """Get a dictionary mapping ticker symbols to CIK numbers."""
    cik_df = get_cik_mapping()
    return cik_df.set_index("ticker")["cik"].to_dict()


def get_company_filings(cik: int | None, include_8k: bool = False) -> pd.DataFrame | None:
    """
    Get SEC filings (8-K, 10-K, 10-Q) for a company by CIK.

    Args:
        cik: Company CIK number
        include_8k: Whether to include 8-K filings (default: False)

    Returns:
        pd.DataFrame: DataFrame with filing information

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

    # CIK is a 10-digit number, pad with zeros if necessary
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"

    def metadata_to_df(cik_metadata):
        filings_df = pd.DataFrame(cik_metadata["filings"]["recent"])
        filings_df = filings_df[filings_df.form.isin(target_filing_form)]
        return filings_df

    # Check if the response is cached
    cached_response = cache.get(url)
    if cached_response:
        return metadata_to_df(cached_response)

    cik_metadata = _fetch_json(url)

    # Cache the response
    cache[url] = cik_metadata

    return metadata_to_df(cik_metadata)


def download_filing(cik: int, accession_number: str, file_name: str) -> str:
    """
    Download SEC filing content.

    Args:
        cik: Company CIK number
        accession_number: SEC accession number
        file_name: Name of the filing file

    Returns:
        str: Filing content as text
    """
    # CIK is a 10-digit number, pad with zeros if necessary
    url = f"https://www.sec.gov/Archives/edgar/data/{str(cik).zfill(10)}/{accession_number}/{file_name}"

    # Check if the response is cached
    cached_response = cache.get(url)
    if cached_response:
        return cached_response

    content = _fetch_text(url)

    # Cache the response
    cache[url] = content

    return content


def get_filing_url(cik: int, accession_number: str, file_name: str) -> str:
    """
    Get the URL for viewing a SEC filing online.

    Args:
        cik: Company CIK number
        accession_number: SEC accession number
        file_name: Name of the filing file

    Returns:
        str: URL for viewing the filing
    """
    # CIK is a 10-digit number, pad with zeros if necessary
    url = f"https://www.sec.gov/Archives/edgar/data/{str(cik).zfill(10)}/{accession_number}/{file_name}"
    return url
