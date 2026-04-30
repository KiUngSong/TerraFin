# SEC EDGAR Data Module for TerraFin
# This module provides access to SEC EDGAR filing data

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts import FilingDocument, TOCEntry

from .filing import (
    clear_sec_filings_cache,
    download_filing,
    get_company_filings,
    get_ticker_to_cik_dict_cached,
    ticker_to_cik_dict,
)
from .parser import build_toc, parse_sec_filing


SEC_PARSED_NAMESPACE = "sec.parsed"


def _parsed_source(cik: int, accession_number: str, file_name: str, include_images: bool) -> str:
    return f"sec.parsed.{cik}.{accession_number}.{file_name}.i{int(include_images)}"


def _ensure_parsed_registered(
    cik: int,
    accession_number: str,
    file_name: str,
    include_images: bool,
    filing_form: str,
) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    source = _parsed_source(cik, accession_number, file_name, include_images)
    get_cache_manager().register_payload(
        CachePayloadSpec(
            source=source,
            namespace=SEC_PARSED_NAMESPACE,
            key=source,
            ttl_seconds=ttl_for("sec.parsed"),
            frozen_payload=True,
            fetch_fn=lambda: parse_sec_filing(
                download_filing(cik, accession_number, file_name),
                filing_form,
                include_images=include_images,
            ),
        )
    )
    return source


def get_sec_data(
    ticker: str,
    filing_type: str = "10-Q",
    filing_index: int = 0,
    *,
    include_images: bool = False,
) -> FilingDocument:
    """Return parsed SEC filing as a canonical FilingDocument contract."""
    cik = get_ticker_to_cik_dict_cached().get(ticker.upper())
    if cik is None:
        raise ValueError(f"CIK not found for ticker: {ticker}")

    include_8k = filing_type == "8-K"
    filings_df = get_company_filings(cik, include_8k=include_8k)
    if filings_df is None or len(filings_df) == 0:
        raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    if filing_type != "all":
        filings_df = filings_df[filings_df.form == filing_type]
        if len(filings_df) == 0:
            raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    if filing_index >= len(filings_df):
        raise ValueError(f"Filing index {filing_index} out of range. Available: 0-{len(filings_df) - 1}")

    accession_number = filings_df.accessionNumber.iloc[filing_index].replace("-", "")
    file_name = filings_df.primaryDocument.iloc[filing_index]
    filing_form = filings_df.primaryDocDescription.iloc[filing_index]
    filing_date = str(filings_df.filingDate.iloc[filing_index]) if "filingDate" in filings_df.columns else ""

    from TerraFin.data.cache.registry import get_cache_manager

    source = _ensure_parsed_registered(cik, accession_number, file_name, include_images, filing_form)
    markdown = get_cache_manager().get_payload(source).payload

    toc_entries = [
        TOCEntry(
            id=entry["slug"],
            title=entry["text"],
            level=entry["level"],
            anchor=entry["slug"],
        )
        for entry in build_toc(markdown, max_level=None)
    ]

    return FilingDocument(
        ticker=ticker.upper(),
        filing_type=filing_type if filing_type in ("10-K", "10-Q", "8-K", "13F", "S-1", "DEF 14A") else "10-Q",
        accession=accession_number,
        filing_date=filing_date,
        markdown=markdown,
        toc=toc_entries,
        metadata={"primary_document": file_name, "cik": cik, "form": filing_form},
    )


def get_sec_toc(
    ticker: str,
    filing_type: str = "10-Q",
    filing_index: int = 0,
    *,
    include_images: bool = False,
    max_level: int | None = 2,
) -> list[TOCEntry]:
    """Return the table of contents (TOCEntry list) for a filing."""
    document = get_sec_data(
        ticker,
        filing_type=filing_type,
        filing_index=filing_index,
        include_images=include_images,
    )
    if max_level is None:
        return list(document.toc)
    return [entry for entry in document.toc if entry.level <= max_level]


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
