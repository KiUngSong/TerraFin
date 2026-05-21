# SEC EDGAR Data Module for TerraFin
# This module provides access to SEC EDGAR filing data

import logging

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts import FilingDocument, TOCEntry

from .filing import (
    SecEdgarError,
    clear_sec_filings_cache,
    download_exhibit,
    download_filing,
    filter_ex99_html_exhibits,
    get_company_filings,
    get_ticker_to_cik_dict_cached,
    list_filing_files,
    ticker_to_cik_dict,
)
from .parser import build_toc, parse_sec_filing


log = logging.getLogger(__name__)

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
            fetch_fn=lambda: fetch_and_parse_filing(
                cik, accession_number, file_name, filing_form, include_images
            ),
        )
    )
    return source


def fetch_and_parse_filing(
    cik: int,
    accession_number: str,
    file_name: str,
    filing_form: str,
    include_images: bool,
) -> str:
    """Fetch+parse the primary doc; for 8-K, append EX-99.x exhibit bodies."""
    body = parse_sec_filing(
        download_filing(cik, accession_number, file_name),
        filing_form,
        include_images=include_images,
    )
    if "8-K" not in (filing_form or "").upper():
        return body
    return body + _fetch_and_render_8k_exhibits(cik, accession_number, include_images)


def _fetch_and_render_8k_exhibits(
    cik: int,
    accession_number: str,
    include_images: bool,
) -> str:
    """Best-effort fetch of every EX-99.x HTML exhibit on an 8-K accession.

    A listing failure (network, 404) yields an empty string — the primary
    8-K body is still useful on its own. Per-exhibit failures emit a marker
    heading so the caller knows the exhibit existed but wasn't reachable.
    """
    try:
        files = list_filing_files(cik, accession_number)
    except SecEdgarError as exc:
        log.warning(
            "Skipping 8-K exhibits: accession index unavailable (cik=%s, accession=%s): %s",
            cik,
            accession_number,
            exc,
        )
        return ""

    exhibits = filter_ex99_html_exhibits(files)
    if not exhibits:
        return ""

    parts: list[str] = []
    for row in exhibits:
        type_ = row.get("type") or "EX-99"
        document = row.get("document") or ""
        raw_description = (row.get("description") or "").strip()
        # Many issuers (NVDA, AAPL) just repeat the type in the Description
        # column ("EX-99.1") rather than naming it ("Press Release"). When
        # that happens, swap in a readable default so the rendered heading
        # is `## Exhibit 99.1 — Press Release`, not `## Exhibit 99.1 — EX-99.1`.
        if not raw_description or raw_description.upper() == type_.upper():
            description = _default_exhibit_description(type_)
        else:
            description = raw_description
        # Convert "EX-99.1" → "Exhibit 99.1" for a readable heading; build_toc
        # will slugify to "exhibit-99-1-press-release" (or similar).
        heading_label = _type_to_heading_label(type_)
        try:
            html = download_exhibit(cik, accession_number, document)
        except SecEdgarError as exc:
            log.warning(
                "Skipping 8-K exhibit %s (%s): %s", type_, document, exc
            )
            parts.append(f"\n## {heading_label} — {description} (fetch failed)\n")
            continue
        try:
            exhibit_md = parse_sec_filing(html, "8-K", include_images=include_images)
        except Exception as exc:
            log.warning(
                "Skipping 8-K exhibit %s (%s): parse failed: %s",
                type_,
                document,
                exc,
            )
            parts.append(f"\n## {heading_label} — {description} (parse failed)\n")
            continue
        parts.append(f"\n## {heading_label} — {description}\n\n{exhibit_md}")
    return "".join(parts)


def _type_to_heading_label(type_: str) -> str:
    """`EX-99.1` -> `Exhibit 99.1`, `EX-99` -> `Exhibit 99`."""
    cleaned = type_.strip().upper()
    if cleaned.startswith("EX-"):
        return "Exhibit " + cleaned[3:]
    return cleaned


def _default_exhibit_description(type_: str) -> str:
    """When EDGAR omits a description, fall back to a generic label.

    Only EX-99.1 is the canonical press-release slot; EX-99.2 is the
    well-known supplemental commentary slot. EX-99.3 and above can be
    investor decks, additional press materials, or other ad-hoc
    exhibits — labeling those all "Press Release" was cosmetically
    wrong, so fall back to a neutral "Additional Material" label.
    """
    cleaned = type_.strip().upper()
    if cleaned == "EX-99.1":
        return "Press Release"
    if cleaned == "EX-99.2":
        return "Supplemental Material"
    if cleaned.startswith("EX-99"):
        return "Additional Material"
    return "Exhibit"


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
    "download_exhibit",
    "download_filing",
    "filter_ex99_html_exhibits",
    "get_company_filings",
    "get_sec_data",
    "get_sec_toc",
    "get_ticker_to_cik_dict_cached",
    "list_filing_files",
    "parse_sec_filing",
    "ticker_to_cik_dict",
]
