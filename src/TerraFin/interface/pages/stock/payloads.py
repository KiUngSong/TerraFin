import functools
import math
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from TerraFin.analytics.analysis.fundamental.dcf.inputs import (
    _annual_fcf_series,
    _latest_annual_fcf,
    _latest_stock_fcf,
    _quarterly_ttm_fcf,
    _safe_float,
    _select_stock_fcf_base,
    _three_year_avg_fcf,
)
from TerraFin.data import (
    SecEdgarError,
    build_toc,
    fetch_and_parse_filing,
    get_company_filings,
    get_data_factory,
    get_ticker_earnings,
    get_ticker_info,
    get_ticker_to_cik_dict_cached,
)
from TerraFin.interface.pages.market_insights.payloads import canonical_macro_name, resolve_macro_type


def _resolve_macro_name(name: str) -> str | None:
    resolved_name = canonical_macro_name(name)
    return resolved_name if resolve_macro_type(resolved_name) is not None else None


def build_company_info_payload(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    info = get_ticker_info(normalized)
    if not info or (
        not info.get("shortName")
        and not info.get("currentPrice")
        and not info.get("regularMarketPrice")
        and not info.get("marketCap")
    ):
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
        "quoteType": info.get("quoteType"),
    }


def build_earnings_payload(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    records = get_ticker_earnings(normalized)
    if not records:
        raise HTTPException(status_code=404, detail=f"No data found for ticker '{ticker}'.")
    return {
        "ticker": normalized,
        "earnings": [dict(record) for record in records],
    }


def build_fcf_history_payload(ticker: str, *, years: int = 10) -> dict[str, Any]:
    """Annual FCF + FCF/share series and TTM FCF/share.

    Per-year shares are not reliably available from yfinance cashflow data, so
    every year is divided by current sharesOutstanding. Acceptable for
    visualization (helps users gauge what a "realistic" FCF/share looks like
    for the company), not for precise per-year ownership accounting. The
    response carries a `sharesNote` so the client can disclose this caveat.
    """
    normalized = ticker.upper()
    info = get_ticker_info(normalized) or {}
    shares_outstanding = _safe_float(info.get("sharesOutstanding"))

    factory = get_data_factory()
    cashflow_quarter = factory.get_corporate_data(normalized, "cashflow", period="quarter")
    cashflow_annual = factory.get_corporate_data(normalized, "cashflow", period="annual")
    annual_series = _annual_fcf_series(cashflow_annual)
    ttm_fcf, ttm_source = _latest_stock_fcf(cashflow_quarter, cashflow_annual)

    import math

    def _finite_or_none(value: Any) -> float | None:
        try:
            parsed = float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
        if parsed is None or not math.isfinite(parsed):
            return None
        return parsed

    history: list[dict[str, Any]] = []
    if annual_series is not None and cashflow_annual is not None and len(cashflow_annual.columns) > 0:
        dates = [str(c) for c in cashflow_annual.columns]
        for date_value, fcf_value in zip(dates[:years], annual_series.head(years).tolist()):
            fcf_float = _finite_or_none(fcf_value)
            year_label = str(date_value)[:4] if date_value else None
            fcf_per_share = (
                fcf_float / shares_outstanding
                if fcf_float is not None and shares_outstanding and shares_outstanding > 0
                else None
            )
            history.append(
                {
                    "year": year_label,
                    "fcf": fcf_float,
                    "fcfPerShare": fcf_per_share,
                }
            )

    def _per_share(total: float | None) -> float | None:
        if total is None or not shares_outstanding or shares_outstanding <= 0:
            return None
        return total / shares_outstanding

    ttm_fcf_per_share = _finite_or_none(_per_share(ttm_fcf))
    three_year_avg = _finite_or_none(_per_share(_three_year_avg_fcf(cashflow_annual)))
    latest_annual = _finite_or_none(_per_share(_latest_annual_fcf(cashflow_annual)))
    ttm_per_share_candidate = _finite_or_none(_per_share(_quarterly_ttm_fcf(cashflow_quarter)))

    # Rolling TTM series — each point is a "trailing 12 months of FCF" ending
    # at a specific date. We assemble two sources:
    #   (a) Annual year-end values: by definition the annual FCF for fiscal
    #       year Y equals the TTM at that year's end date. Gives us 4-5 points
    #       spread across years.
    #   (b) Quarterly windows from yfinance's last 5-6 quarters: 1-3 additional
    #       interim points (e.g., 25Q3) that fill in between year-ends.
    # Combined, we get 6-7 points spanning multiple years.
    rolling_ttm: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    # (a) Annual year-ends. Walk oldest → newest so the resulting list is
    # chronological once we extend with quarterly points and sort.
    if annual_series is not None and cashflow_annual is not None and len(cashflow_annual.columns) > 0:
        annual_dates = [str(c) for c in cashflow_annual.columns]
        for date_value, fcf_value in zip(
            reversed(annual_dates[:years]),
            reversed(annual_series.head(years).tolist()),
        ):
            fcf_float = _finite_or_none(fcf_value)
            if fcf_float is None or not date_value:
                continue
            iso = str(date_value)[:10]
            per_share = _finite_or_none(_per_share(fcf_float))
            if per_share is None:
                continue
            rolling_ttm.append({"asOf": iso, "fcfPerShare": per_share})
            seen_dates.add(iso)

    # (b) Quarterly rolling windows.
    if cashflow_quarter is not None:
        quarter_series = _annual_fcf_series(cashflow_quarter)
        if quarter_series is not None and len(cashflow_quarter.columns) > 0:
            quarter_dates = [str(c) for c in cashflow_quarter.columns]
            n = len(quarter_series)
            for end_idx in range(n - 4, -1, -1):
                window = quarter_series.iloc[end_idx : end_idx + 4]
                if window.dropna().shape[0] < 4:
                    continue
                date_value = quarter_dates[end_idx] if end_idx < len(quarter_dates) else None
                if not date_value:
                    continue
                iso = str(date_value)[:10]
                if iso in seen_dates:
                    continue  # already covered by an annual year-end
                window_sum = float(window.sum())
                per_share = _finite_or_none(_per_share(window_sum))
                if per_share is None:
                    continue
                rolling_ttm.append({"asOf": iso, "fcfPerShare": per_share})
                seen_dates.add(iso)

    rolling_ttm.sort(key=lambda p: p["asOf"])

    # Which source would "auto" resolve to given current data? Used by the UI to show
    # "Auto → 3yr Avg" so the user knows what Auto is actually picking.
    _, auto_selected_source = _select_stock_fcf_base(cashflow_quarter, cashflow_annual, source="auto")

    return {
        "ticker": normalized,
        "sharesOutstanding": shares_outstanding,
        "ttmFcfPerShare": ttm_fcf_per_share,
        "ttmSource": ttm_source,
        "rollingTtm": rolling_ttm,
        "candidates": {
            "threeYearAvg": three_year_avg,
            "latestAnnual": latest_annual,
            "ttm": ttm_per_share_candidate,
        },
        "autoSelectedSource": auto_selected_source,
        "sharesNote": (
            "Per-year FCF/share is computed using current sharesOutstanding; "
            "historical share counts are not used and so dilution/buybacks "
            "are not reflected year-over-year."
        ),
        "history": list(reversed(history)),  # oldest first for left-to-right plotting
    }


def build_financial_statement_payload(
    ticker: str,
    statement: str = "income",
    period: str = "annual",
) -> dict[str, Any]:
    normalized = ticker.upper()
    try:
        df = get_data_factory().get_corporate_data(normalized, statement, period)
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

    import math

    def _clean(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    return {
        "ticker": normalized,
        "statement": statement,
        "period": period,
        "columns": [str(column) for column in df.columns],
        "rows": [
            {
                "label": str(idx),
                "values": {str(column): _clean(df.at[idx, column]) for column in df.columns},
            }
            for idx in df.index
        ],
    }


def resolve_ticker_query(query: str) -> dict[str, str]:
    name = query.strip()
    macro_name = _resolve_macro_name(name)
    if macro_name:
        # Percent-encode: macro names like "S&P 500" contain `&`/spaces that
        # otherwise split the URL (browser reads `?ticker=S` and drops the rest).
        return {"type": "macro", "name": macro_name, "path": f"/market-insights?ticker={quote(macro_name, safe='')}"}

    upper = name.upper()
    return {"type": "stock", "name": upper, "path": f"/stock/{quote(upper, safe='')}"}


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


@functools.lru_cache(maxsize=32)
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
        # 8-K branch appends EX-99.x exhibit bodies (earnings PR / CFO commentary)
        # so the dashboard shows the substantive content, not just the cover sheet.
        markdown = fetch_and_parse_filing(
            cik, acc_clean, primary_document, form, include_images,
        )
    except SecEdgarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        # Unsupported form (e.g., a DEF 14A passed through) — raw fallback.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # `max_level=2` keeps the sidebar compact (Part/Item scaffold only).
    # 8-K exhibit bodies (earnings PR / CFO commentary) emit their own
    # section structure at level 3 (e.g. `### Q1 FY27 Summary`,
    # `### CFO Commentary`); bump to level 3 so those entries land in
    # the sidebar TOC. Other forms keep the compact level-2 view.
    toc_max_level = 3 if (form or "").upper().startswith("8-K") else 2
    # Normalize keys to camelCase for frontend consistency with the rest of the API.
    toc = [
        {
            "level": entry["level"],
            "text": entry["text"],
            "lineIndex": entry["line_index"],
            "slug": entry["slug"],
            "charCount": entry["char_count"],
        }
        for entry in build_toc(markdown, max_level=toc_max_level)
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


# ---------------------------------------------------------------------------
# Income statement Sankey
# ---------------------------------------------------------------------------

# yfinance label → canonical key. Order within a tuple = preference, so we can
# fall back to alternative labels if yfinance changes its mind (it has, twice).
_INCOME_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue", "TotalRevenue"),
    "costOfRevenue": ("Cost Of Revenue", "Reconciled Cost Of Revenue", "CostOfRevenue"),
    "grossProfit": ("Gross Profit", "GrossProfit"),
    "operatingExpense": ("Operating Expense", "OperatingExpense", "Total Operating Expenses"),
    "researchAndDevelopment": ("Research And Development", "ResearchAndDevelopment"),
    "sellingGeneralAdmin": ("Selling General And Administration", "SellingGeneralAndAdministration"),
    "operatingIncome": ("Operating Income", "Total Operating Income As Reported", "OperatingIncome"),
    "pretaxIncome": ("Pretax Income", "PretaxIncome"),
    "taxProvision": ("Tax Provision", "TaxProvision", "Income Tax Expense Benefit"),
    "netIncome": ("Net Income", "Net Income Common Stockholders", "NetIncome"),
}


def _pick_income_value(row_map: dict[str, float], canonical: str) -> float | None:
    """Return the first non-null value among the aliases for ``canonical``."""
    for label in _INCOME_FIELD_ALIASES.get(canonical, ()):
        value = row_map.get(label)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return None


def _yoy_pct(current: float | None, prior: float | None) -> float | None:
    """Year-over-year percent change. ``None`` when either side is missing or
    when prior == 0 (division-by-zero would be infinity, not informative)."""
    if current is None or prior is None:
        return None
    try:
        if prior == 0:
            return None
        return ((current - prior) / abs(prior)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _income_frame_to_period_map(frame) -> tuple[list[str], dict[str, dict[str, float]]]:
    """Reshape the corporate-data frame into ``(dates_newest_first, {date: {label: value}})``.

    The corporate-data ``FinancialStatementFrame`` is indexed by line item
    label with one column per report date. We index by date so we can compare
    the same period this year vs last year without DataFrame gymnastics.
    """
    if frame is None or frame.empty:
        return [], {}
    dates = [str(c) for c in frame.columns]
    by_date: dict[str, dict[str, float]] = {}
    for date in dates:
        col = frame[date]
        by_date[date] = {str(label): value for label, value in col.items()}
    # Newest-first: column 0 of FinancialStatementFrame is the most recent.
    return dates, by_date


def _sankey_metric(
    current: float | None,
    prior: float | None,
) -> dict[str, Any]:
    return {
        "value": current,
        "yoyPct": _yoy_pct(current, prior),
    }


def build_income_sankey_payload(ticker: str, *, period: str = "quarter") -> dict[str, Any]:
    """Build the income-statement Sankey payload for a single ticker.

    Returns ``nodes`` and ``links`` ready to feed @nivo/sankey, plus a flat
    ``metrics`` map keyed by canonical line item so the UI can render the
    summary KPI row without re-deriving values from the diagram. Each metric
    carries the absolute value and Y/Y delta (vs the same-quarter-prior-year
    when ``period == "quarter"``, vs the prior fiscal year for ``"annual"``).

    Raises HTTPException(404) when no statement rows are available — typically
    a non-equity ticker (ETF, index) or a name yfinance does not cover.
    """
    if period not in ("quarter", "annual"):
        raise HTTPException(status_code=400, detail="period must be 'quarter' or 'annual'")
    normalized = ticker.upper()

    factory = get_data_factory()
    frame = factory.get_corporate_data(normalized, "income", period=period)
    dates, by_date = _income_frame_to_period_map(frame)
    if not dates:
        raise HTTPException(status_code=404, detail=f"No income statement data for '{ticker}'.")

    current_date = dates[0]
    current_row = by_date[current_date]
    # Pick the prior period by DATE, not by index. Index-based lookup silently
    # picks the wrong quarter for newly-listed names, after restated periods,
    # or across 53-week fiscal years. Target = current_date − 1 year; accept
    # the nearest available column within ±45 days, else leave priors empty
    # so Y/Y deltas surface as null instead of misleading numbers.
    try:
        current_dt = datetime.fromisoformat(current_date)
    except ValueError:
        current_dt = None
    prior_date: str | None = None
    prior_row: dict[str, float] = {}
    if current_dt is not None:
        target_dt = current_dt.replace(year=current_dt.year - 1) if current_dt.month != 2 or current_dt.day != 29 else current_dt.replace(year=current_dt.year - 1, day=28)
        best: tuple[int, str] | None = None  # (abs_days_off, date_str)
        for candidate in dates[1:]:
            try:
                cand_dt = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            diff = abs((cand_dt - target_dt).days)
            if diff > 45:
                continue
            if best is None or diff < best[0]:
                best = (diff, candidate)
        if best is not None:
            prior_date = best[1]
            prior_row = by_date[prior_date]

    def _val(key: str, row: dict[str, float]) -> float | None:
        return _pick_income_value(row, key)

    revenue = _val("revenue", current_row)
    cost_of_revenue = _val("costOfRevenue", current_row)
    gross_profit = _val("grossProfit", current_row)
    op_expense = _val("operatingExpense", current_row)
    rd = _val("researchAndDevelopment", current_row)
    sga = _val("sellingGeneralAdmin", current_row)
    op_income = _val("operatingIncome", current_row)
    pretax = _val("pretaxIncome", current_row)
    tax = _val("taxProvision", current_row)
    net_income = _val("netIncome", current_row)

    # Derived fallbacks — yfinance occasionally omits one or two intermediate
    # lines. Compute from the others rather than presenting a hole in the
    # diagram (Sankey balance breaks if any one is missing).
    if gross_profit is None and revenue is not None and cost_of_revenue is not None:
        gross_profit = revenue - cost_of_revenue
    if cost_of_revenue is None and revenue is not None and gross_profit is not None:
        cost_of_revenue = revenue - gross_profit
    if op_expense is None and rd is not None and sga is not None:
        op_expense = rd + sga
    if op_income is None and gross_profit is not None and op_expense is not None:
        op_income = gross_profit - op_expense
    # Tax is derived from Pretax − NI when yfinance omits the explicit line.
    if tax is None and pretax is not None and net_income is not None:
        tax = pretax - net_income
    # Other income/expense net = Pretax − OpIncome. Usually small for industrials,
    # large + negative for highly-leveraged names (interest expense). Carried as
    # its own node when material so the diagram stays balanced.
    other_net = None
    if pretax is not None and op_income is not None:
        other_net = pretax - op_income

    if revenue is None or gross_profit is None or cost_of_revenue is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Income statement for '{ticker}' is missing required fields "
                "(revenue/gross profit/cost of revenue) — cannot build the Sankey."
            ),
        )

    # ---- nodes ---------------------------------------------------------
    # `kind` drives the frontend color palette: positive flow (revenue intake,
    # margin retention, earnings) renders green; cost/leakage renders red;
    # neutral (raw revenue, "other") renders grey.
    def _node(node_id: str, label: str, value: float | None, prior: float | None, kind: str) -> dict[str, Any]:
        return {
            "id": node_id,
            "label": label,
            "value": value,
            "yoyPct": _yoy_pct(value, prior),
            "kind": kind,
        }

    nodes: list[dict[str, Any]] = [
        _node("revenue", "Total revenue", revenue, _val("revenue", prior_row), "neutral"),
        _node("grossProfit", "Gross profit", gross_profit, _val("grossProfit", prior_row), "good"),
        _node("costOfRevenue", "Cost of sales", cost_of_revenue, _val("costOfRevenue", prior_row), "bad"),
    ]
    if op_income is not None:
        nodes.append(_node("operatingIncome", "Operating income", op_income, _val("operatingIncome", prior_row), "good"))
    if op_expense is not None:
        nodes.append(_node("operatingExpense", "Operating expenses", op_expense, _val("operatingExpense", prior_row), "bad"))
    if rd is not None:
        nodes.append(_node("rd", "R&D", rd, _val("researchAndDevelopment", prior_row), "bad"))
    if sga is not None:
        nodes.append(_node("sga", "SG&A", sga, _val("sellingGeneralAdmin", prior_row), "bad"))
    if net_income is not None:
        nodes.append(_node("netIncome", "Net income", net_income, _val("netIncome", prior_row), "good"))
    if tax is not None:
        nodes.append(_node("tax", "Taxes", tax, _val("taxProvision", prior_row), "bad"))
    # Only surface "Other" when the net is materially non-zero (>1% of revenue).
    # Otherwise it adds clutter for no signal.
    other_threshold = (revenue or 0) * 0.01
    if other_net is not None and abs(other_net) > other_threshold:
        kind = "good" if other_net > 0 else "bad"
        nodes.append(_node("other", "Other income / expense", other_net, None, kind))

    # ---- links ---------------------------------------------------------
    # Sankey requires non-negative link values; for "Other income" we feed the
    # signed magnitude into the diagram but flip the source so a negative
    # entry (typical: net interest expense) flows OUT of operating income, and
    # a positive entry flows IN to net income.
    links: list[dict[str, Any]] = [
        {"source": "revenue", "target": "grossProfit", "value": gross_profit},
        {"source": "revenue", "target": "costOfRevenue", "value": cost_of_revenue},
    ]

    have_opincome = op_income is not None
    have_opexpense = op_expense is not None

    if have_opincome and have_opexpense:
        links.append({"source": "grossProfit", "target": "operatingIncome", "value": op_income})
        links.append({"source": "grossProfit", "target": "operatingExpense", "value": op_expense})

    if op_expense is not None:
        if rd is not None:
            links.append({"source": "operatingExpense", "target": "rd", "value": rd})
        if sga is not None:
            links.append({"source": "operatingExpense", "target": "sga", "value": sga})
        # Residual "other opex" — anything in operating expense not captured by
        # R&D + SG&A. Apple has ~0 here; many industrials carry depreciation,
        # restructuring, etc. Surface only when material (>5% of opex).
        residual_opex = op_expense - ((rd or 0) + (sga or 0))
        if residual_opex > op_expense * 0.05:
            nodes.append(_node("otherOpex", "Other opex", residual_opex, None, "bad"))
            links.append({"source": "operatingExpense", "target": "otherOpex", "value": residual_opex})

    if have_opincome and net_income is not None:
        # Split Operating income into Net income + Taxes (+ Other when material).
        # When Other is present it routes either through OpIncome (negative net,
        # e.g. interest expense reduces OpIncome → Pretax) or into NetIncome
        # (positive net, e.g. interest income).
        if other_net is not None and abs(other_net) > other_threshold:
            if other_net < 0:
                # Treat as a cost out of OpIncome.
                links.append({"source": "operatingIncome", "target": "other", "value": abs(other_net)})
            else:
                # Treat as an inflow to Net income (rendered as a separate strand).
                links.append({"source": "other", "target": "netIncome", "value": other_net})
        if tax is not None:
            links.append({"source": "operatingIncome", "target": "tax", "value": max(tax, 0.0)})
        # Net income link value = whatever's left of OpIncome after taxes (+ any
        # negative Other). Compute explicitly to keep the diagram balanced even
        # when yfinance's NI doesn't match the arithmetic.
        net_link = op_income - max(tax or 0, 0.0) - (abs(other_net) if (other_net or 0) < 0 else 0.0)
        if net_link > 0:
            links.append({"source": "operatingIncome", "target": "netIncome", "value": net_link})

    # Flat metrics map for the summary KPI row above the diagram. Carries the
    # same Y/Y deltas as the nodes for code-path consistency.
    metrics = {
        "revenue": _sankey_metric(revenue, _val("revenue", prior_row)),
        "grossProfit": _sankey_metric(gross_profit, _val("grossProfit", prior_row)),
        "costOfRevenue": _sankey_metric(cost_of_revenue, _val("costOfRevenue", prior_row)),
        "operatingIncome": _sankey_metric(op_income, _val("operatingIncome", prior_row)),
        "operatingExpense": _sankey_metric(op_expense, _val("operatingExpense", prior_row)),
        "researchAndDevelopment": _sankey_metric(rd, _val("researchAndDevelopment", prior_row)),
        "sellingGeneralAdmin": _sankey_metric(sga, _val("sellingGeneralAdmin", prior_row)),
        "netIncome": _sankey_metric(net_income, _val("netIncome", prior_row)),
        "taxProvision": _sankey_metric(tax, _val("taxProvision", prior_row)),
    }

    return {
        "ticker": normalized,
        "period": period,
        "asOf": current_date,
        "priorAsOf": prior_date,
        "metrics": metrics,
        "nodes": nodes,
        "links": links,
    }
