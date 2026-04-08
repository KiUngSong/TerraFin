from fastapi import APIRouter, HTTPException, Query

from TerraFin.agent.models import (
    CalendarResponse,
    CompanyInfoResponse,
    EarningsResponse,
    EconomicResponse,
    FinancialStatementResponse,
    IndicatorsResponse,
    LPPLAnalysisResponse,
    MacroFocusResponse,
    MarketDataResponse,
    MarketSnapshotResponse,
    PortfolioResponse,
    ResolveResponse,
)
from TerraFin.agent.service import TerraFinAgentService
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import (
    SecEdgarConfigurationError,
    SecEdgarUnavailableError,
)
from TerraFin.interface.errors import AppRuntimeError


AGENT_API_PREFIX = "/agent/api"


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, SecEdgarConfigurationError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_not_configured",
            status_code=503,
            details={"feature": "agent_portfolio"},
        ) from exc
    if isinstance(exc, SecEdgarUnavailableError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_unavailable",
            status_code=503,
            details={"feature": "agent_portfolio"},
        ) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def create_agent_data_router() -> APIRouter:
    router = APIRouter()
    service = TerraFinAgentService()

    @router.get(f"{AGENT_API_PREFIX}/resolve", response_model=ResolveResponse)
    def api_agent_resolve(q: str = Query(..., min_length=1)):
        try:
            return ResolveResponse(**service.resolve(q))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-data", response_model=MarketDataResponse)
    def api_agent_market_data(
        ticker: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MarketDataResponse(**service.market_data(ticker, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/indicators", response_model=IndicatorsResponse)
    def api_agent_indicators(
        ticker: str = Query(..., min_length=1),
        indicators: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return IndicatorsResponse(**service.indicators(ticker, indicators, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-snapshot", response_model=MarketSnapshotResponse)
    def api_agent_market_snapshot(
        ticker: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MarketSnapshotResponse(**service.market_snapshot(ticker, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/company", response_model=CompanyInfoResponse)
    def api_agent_company(ticker: str = Query(..., min_length=1)):
        try:
            return CompanyInfoResponse(**service.company_info(ticker))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/earnings", response_model=EarningsResponse)
    def api_agent_earnings(ticker: str = Query(..., min_length=1)):
        try:
            return EarningsResponse(**service.earnings(ticker))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/financials", response_model=FinancialStatementResponse)
    def api_agent_financials(
        ticker: str = Query(..., min_length=1),
        statement: str = Query(default="income", pattern="^(income|balance|cashflow)$"),
        period: str = Query(default="annual", pattern="^(annual|quarter)$"),
    ):
        try:
            return FinancialStatementResponse(**service.financials(ticker, statement=statement, period=period))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/portfolio", response_model=PortfolioResponse)
    def api_agent_portfolio(guru: str = Query(..., min_length=1)):
        try:
            return PortfolioResponse(**service.portfolio(guru))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/economic", response_model=EconomicResponse)
    def api_agent_economic(indicators: str = Query(..., min_length=1)):
        try:
            return EconomicResponse(**service.economic(indicators))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/macro-focus", response_model=MacroFocusResponse)
    def api_agent_macro_focus(
        name: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MacroFocusResponse(**service.macro_focus(name, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/lppl", response_model=LPPLAnalysisResponse)
    def api_agent_lppl(
        name: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return LPPLAnalysisResponse(**service.lppl_analysis(name, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/calendar", response_model=CalendarResponse)
    def api_agent_calendar(
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=1970, le=2200),
        categories: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ):
        try:
            return CalendarResponse(
                **service.calendar_events(year=year, month=month, categories=categories, limit=limit)
            )
        except Exception as exc:
            _raise_http_error(exc)

    return router
