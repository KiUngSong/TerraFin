"""Stock Analysis API endpoints."""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from TerraFin.analytics.analysis.fundamental import build_stock_dcf_payload, build_stock_reverse_dcf_payload
from TerraFin.analytics.analysis.fundamental.dcf.models import StockDCFOverrides
from TerraFin.analytics.analysis.risk import estimate_beta_5y_monthly, estimate_beta_5y_monthly_adjusted
from TerraFin.interface.stock.payloads import (
    build_company_info_payload,
    build_earnings_payload,
    build_fcf_history_payload,
    build_filing_document_payload,
    build_filings_list_payload,
    build_financial_statement_payload,
    resolve_ticker_query,
)
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


class FcfHistoryRow(BaseModel):
    year: str | None = None
    fcf: float | None = None
    fcfPerShare: float | None = None


class FcfCandidates(BaseModel):
    threeYearAvg: float | None = None
    latestAnnual: float | None = None
    ttm: float | None = None


class FcfRollingTtmPoint(BaseModel):
    asOf: str | None = None
    fcfPerShare: float | None = None


class FcfHistoryResponse(BaseModel):
    ticker: str
    sharesOutstanding: float | None = None
    ttmFcfPerShare: float | None = None
    ttmSource: str | None = None
    candidates: FcfCandidates = FcfCandidates()
    autoSelectedSource: str | None = None
    rollingTtm: list[FcfRollingTtmPoint] = []
    sharesNote: str | None = None
    history: list[FcfHistoryRow]


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


class FilingRowResponse(BaseModel):
    accession: str
    form: str
    filingDate: str
    reportDate: str | None = None
    primaryDocument: str
    primaryDocDescription: str | None = None
    indexUrl: str
    documentUrl: str


class FilingLatestByFormEntry(BaseModel):
    accession: str
    primaryDocument: str
    filingDate: str
    reportDate: str | None = None
    documentUrl: str


class FilingsListResponse(BaseModel):
    ticker: str
    cik: int
    forms: list[str]
    filings: list[FilingRowResponse]
    # Shortcut: `latestByForm["10-K"].accession` gives direct access to the
    # newest filing of a given form without scanning the chronological list.
    latestByForm: dict[str, FilingLatestByFormEntry] = {}


class TocEntry(BaseModel):
    level: int
    text: str
    lineIndex: int
    slug: str
    charCount: int


class FilingDocumentResponse(BaseModel):
    ticker: str
    accession: str
    primaryDocument: str
    markdown: str
    toc: list[TocEntry]
    charCount: int
    indexUrl: str
    documentUrl: str


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

    @router.get(f"{STOCK_API_PREFIX}/fcf-history", response_model=FcfHistoryResponse)
    def api_fcf_history(
        ticker: str = Query(..., min_length=1),
        years: int = Query(default=10, ge=1, le=20),
    ):
        return FcfHistoryResponse(**build_fcf_history_payload(ticker, years=years))

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
    def api_dcf(
        ticker: str = Query(..., min_length=1),
        projectionYears: int | None = Query(default=None),
    ):
        return DCFValuationResponse.model_validate(
            build_stock_dcf_payload(ticker, projection_years=projectionYears)
        )

    @router.post(f"{STOCK_API_PREFIX}/dcf", response_model=DCFValuationResponse)
    def api_post_dcf(ticker: str = Query(..., min_length=1), request: StockDCFRequest | None = None):
        overrides = StockDCFOverrides(
            base_cash_flow_per_share=request.baseCashFlowPerShare if request else None,
            base_growth_pct=request.baseGrowthPct if request else None,
            terminal_growth_pct=request.terminalGrowthPct if request else None,
            beta=request.beta if request else None,
            equity_risk_premium_pct=request.equityRiskPremiumPct if request else None,
            current_price=request.currentPrice if request else None,
            fcf_base_source=request.fcfBaseSource if request else None,  # type: ignore[arg-type]
            breakeven_year=request.breakevenYear if request else None,
            breakeven_cash_flow_per_share=request.breakevenCashFlowPerShare if request else None,
            post_breakeven_growth_pct=request.postBreakevenGrowthPct if request else None,
        )
        return DCFValuationResponse.model_validate(
            build_stock_dcf_payload(
                ticker,
                overrides=overrides,
                projection_years=request.projectionYears if request else None,
            )
        )

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

    @router.get(f"{STOCK_API_PREFIX}/filings", response_model=FilingsListResponse)
    def api_filings(
        ticker: str = Query(..., min_length=1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return FilingsListResponse(**build_filings_list_payload(ticker, limit=limit))

    @router.get(f"{STOCK_API_PREFIX}/filing-document", response_model=FilingDocumentResponse)
    def api_filing_document(
        ticker: str = Query(..., min_length=1),
        accession: str = Query(..., min_length=1),
        primaryDocument: str = Query(..., min_length=1),
        form: str = Query(default="10-Q", min_length=1),
        includeImages: bool = Query(default=False),
    ):
        return FilingDocumentResponse(
            **build_filing_document_payload(
                ticker,
                accession,
                primaryDocument,
                form=form,
                include_images=includeImages,
            )
        )

    return router
