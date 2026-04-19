from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from TerraFin.data import DataFactory
from TerraFin.data.providers.corporate.filings.sec_edgar import (
    build_toc,
    download_filing,
    get_company_filings,
    get_ticker_to_cik_dict_cached,
    parse_sec_filing,
)
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import SecEdgarError
from TerraFin.data.providers.market.ticker_info import get_ticker_earnings, get_ticker_info
from TerraFin.interface.market_insights.payloads import canonical_macro_name, resolve_macro_type


def _resolve_macro_name(name: str) -> str | None:
    resolved_name = canonical_macro_name(name)
    return resolved_name if resolve_macro_type(resolved_name) is not None else None


def build_company_info_payload(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    info = get_ticker_info(normalized)
    if not info:
        raise HTTPException(status_code=404, detail=f"No data found for ticker '{ticker}'.")

    current = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    change_pct = None
    if current and prev_close and prev_close != 0:
        change_pct = round(((current / prev_close) - 1.0) * 100.0, 2)

    return {
        "ticker": normalized,
        "shortName": info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "website": info.get("website"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "trailingEps": info.get("trailingEps"),
        "forwardEps": info.get("forwardEps"),
        "dividendYield": info.get("dividendYield"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "currentPrice": current,
        "previousClose": prev_close,
        "changePercent": change_pct,
        "exchange": info.get("exchange"),
        "beta": info.get("beta"),
    }


def build_earnings_payload(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    records = get_ticker_earnings(normalized)
    return {
        "ticker": normalized,
        "earnings": [dict(record) for record in records],
    }


def build_financial_statement_payload(
    ticker: str,
    statement: str = "income",
    period: str = "annual",
) -> dict[str, Any]:
    normalized = ticker.upper()
    try:
        df = DataFactory().get_corporate_data(normalized, statement, period)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch financials: {exc}") from exc

    if df is None or df.empty:
        return {
            "ticker": normalized,
            "statement": statement,
            "period": period,
            "columns": [],
            "rows": [],
        }

    if "date" in df.columns:
        dates = df["date"].tolist()
        data_cols = [column for column in df.columns if column != "date"]
        rows = []
        for column in data_cols:
            values = {}
            for idx, date in enumerate(dates):
                value = df[column].iloc[idx]
                values[str(date)] = value if value is not None else None
            rows.append({"label": column, "values": values})
        return {
            "ticker": normalized,
            "statement": statement,
            "period": period,
            "columns": [str(date) for date in dates],
            "rows": rows,
        }

    return {
        "ticker": normalized,
        "statement": statement,
        "period": period,
        "columns": [str(column) for column in df.columns],
        "rows": [
            {
                "label": str(idx),
                "values": {str(column): df.at[idx, column] for column in df.columns},
            }
            for idx in df.index
        ],
    }


def resolve_ticker_query(query: str) -> dict[str, str]:
    name = query.strip()
    macro_name = _resolve_macro_name(name)
    if macro_name:
        return {"type": "macro", "name": macro_name, "path": f"/market-insights?ticker={macro_name}"}

    upper = name.upper()
    return {"type": "stock", "name": upper, "path": f"/stock/{upper}"}


# ---------------------------------------------------------------------------
# SEC filings
# ---------------------------------------------------------------------------


def _edgar_urls(cik: int, accession_number: str, primary_doc: str) -> dict[str, str]:
    acc_clean = accession_number.replace("-", "")
    cik_padded = str(cik).zfill(10)
    archive_base = f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{acc_clean}"
    # Human-facing link: SEC's inline-XBRL viewer (`/ix?doc=/Archives/...`).
    # This is the URL you get when you click a filing on EDGAR — it wraps the
    # primary document in SEC's viewer UI with proper styling and navigation,
    # working for both iXBRL-tagged and plain HTML filings.
    # `indexUrl` still points at the raw directory listing for debugging and
    # file-level access.
    if primary_doc:
        document_url = f"https://www.sec.gov/ix?doc=/Archives/edgar/data/{cik_padded}/{acc_clean}/{primary_doc}"
    else:
        document_url = f"{archive_base}/"
    return {
        "indexUrl": f"{archive_base}/",
        "documentUrl": document_url,
    }


def _resolve_cik(ticker: str) -> int:
    cik = get_ticker_to_cik_dict_cached().get(ticker.upper())
    if cik is None:
        raise HTTPException(status_code=404, detail=f"CIK not found for ticker '{ticker}'.")
    return int(cik)


def build_filings_list_payload(ticker: str, *, limit: int = 20) -> dict[str, Any]:
    """List recent 10-K / 10-Q / 8-K filings with EDGAR links."""
    normalized = ticker.upper()
    cik = _resolve_cik(normalized)
    try:
        df = get_company_filings(cik, include_8k=True)
    except SecEdgarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if df is None or df.empty:
        return {"ticker": normalized, "cik": cik, "forms": [], "filings": []}

    df = df.sort_values("filingDate", ascending=False).head(limit)

    filings: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        accession = str(row.get("accessionNumber", ""))
        primary_doc = str(row.get("primaryDocument", ""))
        urls = _edgar_urls(cik, accession, primary_doc)
        filings.append(
            {
                "accession": accession,
                "form": str(row.get("form", "")),
                "filingDate": str(row.get("filingDate", "")),
                "reportDate": str(row.get("reportDate", "")) or None,
                "primaryDocument": primary_doc,
                "primaryDocDescription": str(row.get("primaryDocDescription", "")) or None,
                "indexUrl": urls["indexUrl"],
                "documentUrl": urls["documentUrl"],
            }
        )

    # Forms present in this result, in canonical order (10-K first, then 10-Q, 8-K,
    # then anything else). Lets the frontend build a form dropdown without
    # guessing what exists for this ticker (e.g. 20-F for foreign filers).
    seen: list[str] = []
    for f in filings:
        form = f["form"]
        if form and form not in seen:
            seen.append(form)
    priority = {"10-K": 0, "10-K/A": 1, "10-Q": 2, "10-Q/A": 3, "8-K": 4, "8-K/A": 5}
    seen.sort(key=lambda f: priority.get(f, 100))

    # Per-form shortcut so an agent can do `latestByForm["10-K"]` directly
    # instead of scanning a chronological list that mixes 8-Ks in front of
    # quarterly/annual filings. Each entry carries enough to call
    # `sec_filing_section` / `sec_filing_document` with no follow-up.
    latest_by_form: dict[str, dict[str, Any]] = {}
    for f in filings:
        form = f["form"]
        if form and form not in latest_by_form:
            latest_by_form[form] = {
                "accession": f["accession"],
                "primaryDocument": f["primaryDocument"],
                "filingDate": f["filingDate"],
                "reportDate": f["reportDate"],
                "documentUrl": f["documentUrl"],
            }

    return {
        "ticker": normalized,
        "cik": cik,
        "forms": seen,
        "filings": filings,
        "latestByForm": latest_by_form,
    }


def build_filing_document_payload(
    ticker: str,
    accession: str,
    primary_document: str,
    *,
    form: str = "10-Q",
    include_images: bool = False,
) -> dict[str, Any]:
    """Fetch + parse a specific filing, returning the markdown body plus a TOC."""
    normalized = ticker.upper()
    cik = _resolve_cik(normalized)

    acc_clean = accession.replace("-", "")
    if not primary_document:
        raise HTTPException(status_code=400, detail="primaryDocument is required.")

    try:
        html = download_filing(cik, acc_clean, primary_document)
    except SecEdgarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        markdown = parse_sec_filing(html, form, include_images=include_images)
    except ValueError as exc:
        # Unsupported form (e.g., a DEF 14A passed through) — raw fallback.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # `max_level=2` keeps the sidebar compact (Part/Item scaffold only).
    # Normalize keys to camelCase for frontend consistency with the rest of the API.
    toc = [
        {
            "level": entry["level"],
            "text": entry["text"],
            "lineIndex": entry["line_index"],
            "slug": entry["slug"],
            "charCount": entry["char_count"],
        }
        for entry in build_toc(markdown, max_level=2)
    ]

    urls = _edgar_urls(cik, acc_clean, primary_document)
    return {
        "ticker": normalized,
        "accession": acc_clean,
        "primaryDocument": primary_document,
        "markdown": markdown,
        "toc": toc,
        "charCount": len(markdown),
        "indexUrl": urls["indexUrl"],
        "documentUrl": urls["documentUrl"],
    }
