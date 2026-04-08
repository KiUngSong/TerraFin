"""Stock Analysis API endpoints."""

from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from TerraFin.analytics.analysis.fundamental import build_stock_dcf_payload, build_stock_reverse_dcf_payload
from TerraFin.analytics.analysis.fundamental.dcf.models import StockDCFOverrides
from TerraFin.analytics.analysis.risk import estimate_beta_5y_monthly, estimate_beta_5y_monthly_adjusted
from TerraFin.data import DataFactory
from TerraFin.data.providers.economic import indicator_registry
from TerraFin.data.providers.market import INDEX_MAP, MARKET_INDICATOR_REGISTRY
from TerraFin.data.providers.market.ticker_info import get_ticker_earnings, get_ticker_info
from TerraFin.interface.valuation_models import (
    DCFValuationResponse,
    ReverseDCFResponse,
    StockDCFRequest,
    StockReverseDCFRequest,
)


STOCK_API_PREFIX = "/stock/api"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CompanyInfoResponse(BaseModel):
    ticker: str
    shortName: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    website: str | None = None
    marketCap: float | None = None
    trailingPE: float | None = None
    forwardPE: float | None = None
    trailingEps: float | None = None
    forwardEps: float | None = None
    dividendYield: float | None = None
    fiftyTwoWeekHigh: float | None = None
    fiftyTwoWeekLow: float | None = None
    currentPrice: float | None = None
    previousClose: float | None = None
    changePercent: float | None = None
    exchange: str | None = None
    beta: float | None = None


class EarningsRecord(BaseModel):
    date: str
    epsEstimate: str
    epsReported: str
    surprise: str
    surprisePercent: str


class EarningsHistoryResponse(BaseModel):
    ticker: str
    earnings: list[EarningsRecord]


class FinancialRow(BaseModel):
    label: str
    values: dict[str, str | float | None]


class FinancialStatementResponse(BaseModel):
    ticker: str
    statement: str
    period: str
    columns: list[str]
    rows: list[FinancialRow]


class ResolveTickerResponse(BaseModel):
    type: str  # "stock" or "macro"
    name: str
    path: str


class BetaEstimateResponse(BaseModel):
    status: str
    symbol: str
    benchmarkSymbol: str | None = None
    benchmarkLabel: str | None = None
    methodId: str
    adjustedMethodId: str
    lookbackYears: int
    frequency: str
    beta: float | None = None
    adjustedBeta: float | None = None
    observations: int
    rSquared: float | None = None
    warnings: list[str]


def _case_insensitive_match(name: str, candidates: Iterable[str]) -> str | None:
    normalized = name.strip().casefold()
    if not normalized:
        return None
    for candidate in candidates:
        if candidate.casefold() == normalized:
            return candidate
    return None


def _resolve_macro_name(name: str) -> str | None:
    match = _case_insensitive_match(name, INDEX_MAP.keys())
    if match:
        return match
    match = _case_insensitive_match(name, MARKET_INDICATOR_REGISTRY.keys())
    if match:
        return match
    try:
        return _case_insensitive_match(name, indicator_registry._indicators.keys())
    except Exception:
        return None


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
        "earnings": [EarningsRecord(**record).model_dump() for record in records],
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
            rows.append(FinancialRow(label=column, values=values).model_dump())
        return {
            "ticker": normalized,
            "statement": statement,
            "period": period,
            "columns": [str(date) for date in dates],
            "rows": rows,
        }

    columns = [str(column) for column in df.columns]
    rows = [
        FinancialRow(label=str(idx), values={str(column): df.at[idx, column] for column in df.columns}).model_dump()
        for idx in df.index
    ]
    return {
        "ticker": normalized,
        "statement": statement,
        "period": period,
        "columns": columns,
        "rows": rows,
    }


def resolve_ticker_query(query: str) -> dict[str, str]:
    name = query.strip()
    macro_name = _resolve_macro_name(name)
    if macro_name:
        return {"type": "macro", "name": macro_name, "path": f"/market-insights?ticker={macro_name}"}

    upper = name.upper()
    return {"type": "stock", "name": upper, "path": f"/stock/{upper}"}


def build_beta_estimate_payload(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    raw = estimate_beta_5y_monthly(normalized)
    adjusted = estimate_beta_5y_monthly_adjusted(normalized)
    warnings = list(dict.fromkeys([*raw.warnings, *adjusted.warnings]))
    return {
        "status": raw.status,
        "symbol": normalized,
        "benchmarkSymbol": raw.benchmark_symbol,
        "benchmarkLabel": raw.benchmark_label,
        "methodId": raw.method_id,
        "adjustedMethodId": adjusted.method_id,
        "lookbackYears": raw.lookback_years,
        "frequency": raw.frequency,
        "beta": raw.beta,
        "adjustedBeta": adjusted.beta,
        "observations": raw.observations,
        "rSquared": raw.r_squared,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def create_stock_data_router() -> APIRouter:
    router = APIRouter()

    @router.get(f"{STOCK_API_PREFIX}/company-info", response_model=CompanyInfoResponse)
    def api_company_info(ticker: str = Query(..., min_length=1)):
        return CompanyInfoResponse(**build_company_info_payload(ticker))

    @router.get(f"{STOCK_API_PREFIX}/earnings", response_model=EarningsHistoryResponse)
    def api_earnings(ticker: str = Query(..., min_length=1)):
        return EarningsHistoryResponse(**build_earnings_payload(ticker))

    @router.get(f"{STOCK_API_PREFIX}/beta-estimate", response_model=BetaEstimateResponse)
    def api_beta_estimate(ticker: str = Query(..., min_length=1)):
        return BetaEstimateResponse(**build_beta_estimate_payload(ticker))

    @router.get(f"{STOCK_API_PREFIX}/financials", response_model=FinancialStatementResponse)
    def api_financials(
        ticker: str = Query(..., min_length=1),
        statement: str = Query(default="income", pattern="^(income|balance|cashflow)$"),
        period: str = Query(default="annual", pattern="^(annual|quarter)$"),
    ):
        return FinancialStatementResponse(
            **build_financial_statement_payload(ticker, statement=statement, period=period)
        )

    @router.get(f"{STOCK_API_PREFIX}/dcf", response_model=DCFValuationResponse)
    def api_dcf(ticker: str = Query(..., min_length=1)):
        return DCFValuationResponse.model_validate(build_stock_dcf_payload(ticker))

    @router.post(f"{STOCK_API_PREFIX}/dcf", response_model=DCFValuationResponse)
    def api_post_dcf(ticker: str = Query(..., min_length=1), request: StockDCFRequest | None = None):
        overrides = StockDCFOverrides(
            base_cash_flow_per_share=request.baseCashFlowPerShare if request else None,
            base_growth_pct=request.baseGrowthPct if request else None,
            terminal_growth_pct=request.terminalGrowthPct if request else None,
            beta=request.beta if request else None,
            equity_risk_premium_pct=request.equityRiskPremiumPct if request else None,
            current_price=request.currentPrice if request else None,
        )
        return DCFValuationResponse.model_validate(build_stock_dcf_payload(ticker, overrides=overrides))

    @router.get(f"{STOCK_API_PREFIX}/reverse-dcf", response_model=ReverseDCFResponse)
    def api_reverse_dcf(
        ticker: str = Query(..., min_length=1),
        projectionYears: int = Query(default=5, ge=1, le=20),
        growthProfile: str = Query(default="early_maturity", pattern="^(high_growth|early_maturity|fully_mature)$"),
    ):
        return ReverseDCFResponse.model_validate(
            build_stock_reverse_dcf_payload(
                ticker,
                projection_years=projectionYears,
                growth_profile=growthProfile,
            )
        )

    @router.post(f"{STOCK_API_PREFIX}/reverse-dcf", response_model=ReverseDCFResponse)
    def api_post_reverse_dcf(
        ticker: str = Query(..., min_length=1),
        request: StockReverseDCFRequest | None = None,
    ):
        overrides = StockDCFOverrides(
            base_cash_flow_per_share=request.baseCashFlowPerShare if request else None,
            terminal_growth_pct=request.terminalGrowthPct if request else None,
            beta=request.beta if request else None,
            equity_risk_premium_pct=request.equityRiskPremiumPct if request else None,
            current_price=request.currentPrice if request else None,
        )
        return ReverseDCFResponse.model_validate(
            build_stock_reverse_dcf_payload(
                ticker,
                overrides=overrides,
                projection_years=request.projectionYears if request and request.projectionYears else 5,
                growth_profile=request.growthProfile if request and request.growthProfile else "early_maturity",
            )
        )

    @router.get("/resolve-ticker", response_model=ResolveTickerResponse)
    def api_resolve_ticker(q: str = Query(..., min_length=1)):
        return ResolveTickerResponse(**resolve_ticker_query(q))

    return router
