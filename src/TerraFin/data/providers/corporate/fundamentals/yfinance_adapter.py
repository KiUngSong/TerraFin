from typing import Any

import pandas as pd
import yfinance as yf

from TerraFin.data.cache.manager import CacheManager
from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts import FinancialStatementFrame


_CACHE_NAMESPACE = "yfinance_fundamentals"

_STATEMENT_ATTRS: dict[str, dict[str, list[str]]] = {
    "income": {
        "annual": ["income_stmt", "financials"],
        "quarter": ["quarterly_income_stmt", "quarterly_financials"],
    },
    "balance": {
        "annual": ["balance_sheet"],
        "quarter": ["quarterly_balance_sheet"],
    },
    "cashflow": {
        "annual": ["cash_flow", "cashflow"],
        "quarter": ["quarterly_cash_flow", "quarterly_cashflow"],
    },
}


def _cache_key(ticker: str, statement_type: str, period: str) -> str:
    return f"{ticker.upper()}-{statement_type}-{period}"


def _coerce_statement_frame(raw: Any) -> pd.DataFrame | None:
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return None

    frame = raw.copy()
    date_columns = sum(int(pd.notna(pd.to_datetime(column, errors="coerce"))) for column in frame.columns)
    date_index = sum(int(pd.notna(pd.to_datetime(index, errors="coerce"))) for index in frame.index)

    # yfinance usually returns line items as rows and report dates as columns.
    if date_columns >= max(1, date_index):
        frame = frame.transpose()

    if "date" not in frame.columns:
        frame = frame.reset_index().rename(columns={"index": "date"})

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"])
    if frame.empty:
        return None

    frame = frame.sort_values("date", ascending=False).reset_index(drop=True)
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame


def _cached_statement(ticker: str, statement_type: str, period: str) -> pd.DataFrame | None:
    cached = CacheManager.file_cache_read(_CACHE_NAMESPACE, _cache_key(ticker, statement_type, period), ttl_for("fundamentals.yfinance"))
    if cached is None:
        return None
    frame = pd.DataFrame(cached)
    return frame if not frame.empty else None


def _write_cached_statement(ticker: str, statement_type: str, period: str, frame: pd.DataFrame | None) -> None:
    payload = [] if frame is None else frame.to_dict(orient="records")
    CacheManager.file_cache_write(_CACHE_NAMESPACE, _cache_key(ticker, statement_type, period), payload)


def _fetch_statement_frame(ticker: str, statement_type: str, period: str) -> pd.DataFrame | None:
    ticker_obj = yf.Ticker(ticker.upper())
    for attr_name in _STATEMENT_ATTRS.get(statement_type, {}).get(period, []):
        candidate = getattr(ticker_obj, attr_name, None)
        if candidate is None:
            continue
        if callable(candidate):
            try:
                candidate = candidate()
            except TypeError:
                continue
        frame = _coerce_statement_frame(candidate)
        if frame is not None:
            return frame
    return None


def _to_canonical(
    frame: pd.DataFrame | None,
    *,
    statement_type: str,
    period: str,
    ticker: str,
) -> FinancialStatementFrame:
    """Build canonical FinancialStatementFrame: columns are date strings, rows are line items.

    Source frame layout (legacy yfinance adapter): rows = periods with a `date` column,
    columns = line items. Transpose so columns become reporting dates.
    """
    contract_period = "quarterly" if period == "quarter" else period
    if frame is None or frame.empty or "date" not in frame.columns:
        return FinancialStatementFrame.make_empty(statement_type, contract_period, ticker.upper())
    pivoted = frame.set_index("date").transpose()
    pivoted.columns = [str(col) for col in pivoted.columns]
    return FinancialStatementFrame(
        pivoted,
        statement_type=statement_type,
        period=contract_period,
        ticker=ticker.upper(),
    )


def get_corporate_data(
    ticker: str,
    statement_type: str = "income",
    period: str = "annual",
) -> FinancialStatementFrame:
    if statement_type not in _STATEMENT_ATTRS:
        raise ValueError(f"Unsupported statement_type: {statement_type}")
    if period not in ("annual", "quarter"):
        raise ValueError(f"Unsupported period: {period}")

    cached = _cached_statement(ticker, statement_type, period)
    if cached is not None:
        return _to_canonical(cached, statement_type=statement_type, period=period, ticker=ticker)

    frame = _fetch_statement_frame(ticker, statement_type, period)
    _write_cached_statement(ticker, statement_type, period, frame)
    return _to_canonical(frame, statement_type=statement_type, period=period, ticker=ticker)


def clear_corporate_data_cache() -> None:
    CacheManager.file_cache_clear(_CACHE_NAMESPACE)
