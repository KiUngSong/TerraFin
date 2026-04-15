from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from TerraFin.data import DataFactory
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
