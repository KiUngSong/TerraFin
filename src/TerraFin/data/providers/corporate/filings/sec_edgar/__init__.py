# SEC EDGAR Data Module for TerraFin
# This module provides access to SEC EDGAR filing data

from .filing import (
    SEC_FILINGS_CACHE_NAMESPACE,
    clear_sec_filings_cache,
    download_filing,
    get_company_filings,
    get_ticker_to_cik_dict_cached,
    ticker_to_cik_dict,
)
from .parser import build_toc, parse_sec_filing


# Agent-friendly defaults: parsed markdown persists 30 days so repeat agent
# queries against the same filing skip both the SEC download and the sec_parser
# semantic walk.
_PARSED_CACHE_TTL = 30 * 86_400


def _parsed_cache_key(cik: int, accession_number: str, file_name: str, include_images: bool) -> str:
    return f"parsed_{cik}_{accession_number}_{file_name}_i{int(include_images)}"


def get_sec_data(
    ticker: str,
    filing_type: str = "10-Q",
    filing_index: int = 0,
    parse: bool = True,
    *,
    include_images: bool = False,
):
    """
    Main interface for getting SEC filing data.

    When ``parse=True``, the parsed markdown is cached for 30 days under the
    shared ``sec_filings`` namespace, keyed by ``(cik, accession, file_name,
    include_images)``. Repeat calls skip both the download and the parse.

    Args:
        ticker (str): Stock ticker symbol
        filing_type (str): Type of filing to retrieve ("10-K", "10-Q", "8-K")
        filing_index (int): Index of filing to retrieve (0 = latest)
        parse (bool): Whether to parse the filing content to markdown
        include_images (bool): When parsing, emit markdown tags for inline
            images. Off by default — see `parse_sec_filing` for rationale.

    Returns:
        str: Raw HTML when ``parse=False``, parsed markdown otherwise.
    """
    cik = get_ticker_to_cik_dict_cached().get(ticker.upper())

    if cik is None:
        raise ValueError(f"CIK not found for ticker: {ticker}")

    # Get filings based on type
    include_8k = filing_type == "8-K"
    filings_df = get_company_filings(cik, include_8k=include_8k)

    if filings_df is None or len(filings_df) == 0:
        raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    # Filter by filing type if specified
    if filing_type != "all":
        filings_df = filings_df[filings_df.form == filing_type]
        if len(filings_df) == 0:
            raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    if filing_index >= len(filings_df):
        raise ValueError(f"Filing index {filing_index} out of range. Available: 0-{len(filings_df) - 1}")

    # Get filing details
    accession_number = filings_df.accessionNumber.iloc[filing_index].replace("-", "")
    file_name = filings_df.primaryDocument.iloc[filing_index]
    filing_form = filings_df.primaryDocDescription.iloc[filing_index]

    if not parse:
        return download_filing(cik, accession_number, file_name)

    from TerraFin.data.cache.manager import CacheManager

    cache_key = _parsed_cache_key(cik, accession_number, file_name, include_images)
    cached = CacheManager.file_cache_read(SEC_FILINGS_CACHE_NAMESPACE, cache_key, _PARSED_CACHE_TTL)
    if isinstance(cached, dict) and "content" in cached:
        return cached["content"]

    html_content = download_filing(cik, accession_number, file_name)
    parsed = parse_sec_filing(html_content, filing_form, include_images=include_images)
    CacheManager.file_cache_write(SEC_FILINGS_CACHE_NAMESPACE, cache_key, {"content": parsed})
    return parsed


def get_sec_toc(
    ticker: str,
    filing_type: str = "10-Q",
    filing_index: int = 0,
    *,
    include_images: bool = False,
    max_level: int | None = 2,
) -> list[dict]:
    """
    Return the table of contents (section headings) for a filing.

    Reuses the parsed-markdown file cache, so this call is free when the same
    filing has been parsed recently. Useful for agents that want to see which
    sections exist before fetching the full filing body.

    Returns a flat list of ``{"level", "text", "line_index", "slug",
    "char_count"}`` entries. ``max_level`` defaults to ``2`` (top-level only)
    to keep the TOC context-cheap; pass ``None`` for the full hierarchy.
    """
    markdown = get_sec_data(
        ticker,
        filing_type=filing_type,
        filing_index=filing_index,
        parse=True,
        include_images=include_images,
    )
    return build_toc(markdown, max_level=max_level)


__all__ = [
    "build_toc",
    "clear_sec_filings_cache",
    "download_filing",
    "get_company_filings",
    "get_sec_data",
    "get_sec_toc",
    "get_ticker_to_cik_dict_cached",
    "parse_sec_filing",
    "ticker_to_cik_dict",
]
