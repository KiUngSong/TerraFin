import logging
from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from TerraFin.analytics.analysis.fundamental import build_sp500_dcf_payload
from TerraFin.analytics.analysis.fundamental.dcf.models import SP500DCFOverrides, SP500YearAssumption
from TerraFin.data import DataFactory
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import (
    SecEdgarConfigurationError,
    SecEdgarUnavailableError,
)
from TerraFin.data.providers.corporate.investor_positioning import (
    ALL_GURUS,
    get_investor_positioning_capability,
    get_portfolio_data,
)
from TerraFin.data.providers.economic import indicator_registry
from TerraFin.data.providers.market import INDEX_DESCRIPTIONS, INDEX_MAP, MARKET_INDICATOR_REGISTRY
from TerraFin.interface.chart.state import get_named_series
from TerraFin.interface.errors import AppRuntimeError
from TerraFin.interface.private_data_service import get_private_data_service
from TerraFin.interface.valuation_models import DCFValuationResponse, SP500DCFRequest


_logger = logging.getLogger(__name__)


MARKET_INSIGHTS_API_PREFIX = "/market-insights/api"


class MarketRegimeResponse(BaseModel):
    summary: str
    confidence: str
    signals: list[str]


class MacroInstrumentInfoResponse(BaseModel):
    name: str
    type: str
    description: str
    currentValue: float | None
    change: float | None
    changePercent: float | None


class GuruListResponse(BaseModel):
    gurus: list[str]
    count: int
    enabled: bool
    message: str | None = None


class InvestorPositioningResponse(BaseModel):
    guru: str
    info: dict[str, str]
    rows: list[dict]
    topHoldings: list[dict]


def create_market_insights_data_router() -> APIRouter:
    router = APIRouter()

    @router.get(f"{MARKET_INSIGHTS_API_PREFIX}/regime", response_model=MarketRegimeResponse)
    def api_get_market_regime():
        # Initial placeholder to stabilize page contract; can be replaced by real regime model.
        return MarketRegimeResponse(
            summary="Mixed regime with selective risk-taking and elevated event sensitivity.",
            confidence="low",
            signals=[
                "Breadth is improving in pockets but still uneven.",
                "Macro event concentration this week can raise short-term volatility.",
                "Leadership remains concentrated in a handful of large-cap names.",
            ],
        )

    @router.get(f"{MARKET_INSIGHTS_API_PREFIX}/investor-positioning/gurus", response_model=GuruListResponse)
    def api_get_investor_positioning_gurus():
        capability = get_investor_positioning_capability()
        return GuruListResponse(
            gurus=ALL_GURUS,
            count=len(ALL_GURUS),
            enabled=capability.enabled,
            message=capability.message,
        )

    @router.get(
        f"{MARKET_INSIGHTS_API_PREFIX}/investor-positioning/holdings",
        response_model=InvestorPositioningResponse,
    )
    def api_get_investor_positioning_holdings(guru: str = Query(..., min_length=1)):
        try:
            output = get_portfolio_data(guru)
        except Exception as exc:
            _raise_investor_positioning_error(exc, guru=guru)
        rows = output.df.to_dict(orient="records")
        top_holdings = (
            output.df[["Stock", "% of Portfolio", "Recent Activity", "Updated"]]
            .sort_values(by="% of Portfolio", ascending=False)
            .head(8)
            .to_dict(orient="records")
        )
        return InvestorPositioningResponse(
            guru=guru,
            info=dict(output.info),
            rows=rows,
            topHoldings=top_holdings,
        )

    @router.get(f"{MARKET_INSIGHTS_API_PREFIX}/top-companies")
    def api_get_top_companies():
        try:
            companies = get_private_data_service().get_top_companies()
            return {"companies": companies, "count": len(companies)}
        except Exception as e:
            _logger.warning("Failed to fetch top companies: %s", e)
            return {"companies": [], "count": 0}

    @router.get(f"{MARKET_INSIGHTS_API_PREFIX}/dcf/sp500", response_model=DCFValuationResponse)
    def api_get_sp500_dcf():
        return DCFValuationResponse.model_validate(build_sp500_dcf_payload())

    @router.post(f"{MARKET_INSIGHTS_API_PREFIX}/dcf/sp500", response_model=DCFValuationResponse)
    def api_post_sp500_dcf(request: SP500DCFRequest):
        overrides = SP500DCFOverrides(
            base_year_eps=request.baseYearEps,
            terminal_growth_pct=request.terminalGrowthPct,
            terminal_equity_risk_premium_pct=request.terminalEquityRiskPremiumPct,
            terminal_roe_pct=request.terminalRoePct,
            yearly_assumptions=tuple(
                SP500YearAssumption(
                    year_offset=row.yearOffset,
                    growth_pct=row.growthPct,
                    payout_ratio_pct=row.payoutRatioPct,
                    buyback_ratio_pct=row.buybackRatioPct,
                    equity_risk_premium_pct=row.equityRiskPremiumPct,
                )
                for row in (request.yearlyAssumptions or [])
            )
            or None,
        )
        return DCFValuationResponse.model_validate(build_sp500_dcf_payload(overrides=overrides))

    # -------------------------------------------------------------------
    # Macro instrument endpoints
    # -------------------------------------------------------------------

    @router.get(f"{MARKET_INSIGHTS_API_PREFIX}/macro-info", response_model=MacroInstrumentInfoResponse)
    def api_macro_info(request: Request, name: str = Query(..., min_length=1)):
        """Return metadata + current value for a macro instrument."""
        resolved_name = _canonical_macro_name(name)
        indicator_type, description, df = _load_macro_dataframe(
            resolved_name,
            session_id=request.headers.get("X-Session-ID"),
        )
        return _build_macro_info_response(resolved_name, description, df, indicator_type=indicator_type)

    return router


def _display_name(name: str) -> str:
    return name.upper() if name == name.lower() else name


def _case_insensitive_match(name: str, candidates: Iterable[str]) -> str | None:
    normalized = name.strip().casefold()
    if not normalized:
        return None
    for candidate in candidates:
        if candidate.casefold() == normalized:
            return candidate
    return None


def _canonical_macro_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return stripped
    match = _case_insensitive_match(stripped, INDEX_MAP.keys())
    if match:
        return match
    match = _case_insensitive_match(stripped, MARKET_INDICATOR_REGISTRY.keys())
    if match:
        return match
    try:
        match = _case_insensitive_match(stripped, indicator_registry._indicators.keys())
        if match:
            return match
    except Exception:
        pass
    return _display_name(stripped)


def _load_macro_dataframe(name: str, *, session_id: str | None = None) -> tuple[str, str, TimeSeriesDataFrame]:
    name = _canonical_macro_name(name)
    indicator_type = _resolve_macro_type(name)
    if indicator_type is None:
        raise HTTPException(status_code=404, detail=f"Unknown macro instrument: '{name}'")

    description = _get_macro_description(name)

    if session_id:
        session_df = get_named_series(session_id).get(name)
        if session_df is not None:
            session_df.name = name
            return indicator_type, description, session_df

    try:
        factory = DataFactory()
        if hasattr(factory, "get_recent_history"):
            history_chunk = factory.get_recent_history(name, period="3y")
            df = history_chunk.frame
        else:
            df = factory.get(name)
    except Exception:
        try:
            df = DataFactory().get(name)
        except Exception as fallback_exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch data: {fallback_exc}") from fallback_exc

    df.name = name
    return indicator_type, description, df

def _build_macro_info_response(
    name: str,
    description: str,
    df: TimeSeriesDataFrame,
    *,
    indicator_type: str,
) -> MacroInstrumentInfoResponse:
    closes = df["close"].dropna()
    current = float(closes.iloc[-1]) if len(closes) > 0 else None
    previous = float(closes.iloc[-2]) if len(closes) > 1 else None
    change = round(current - previous, 4) if current is not None and previous is not None else None
    change_pct = round((change / previous) * 100, 2) if change is not None and previous else None

    return MacroInstrumentInfoResponse(
        name=name,
        type=indicator_type,
        description=description,
        currentValue=current,
        change=change,
        changePercent=change_pct,
    )

def _get_macro_description(name: str) -> str:
    if name in INDEX_DESCRIPTIONS:
        return INDEX_DESCRIPTIONS[name]
    if name in MARKET_INDICATOR_REGISTRY:
        return MARKET_INDICATOR_REGISTRY[name].description
    if name in indicator_registry._indicators:
        return indicator_registry._indicators[name].description
    return ""


def _resolve_macro_type(name: str) -> str | None:
    """Return the macro type for a name, or None if not a known macro instrument."""
    if name in INDEX_MAP:
        return "index"
    if name in MARKET_INDICATOR_REGISTRY:
        if "Treasury" in name:
            return "treasury"
        if name in ("VIX", "VVIX", "SKEW"):
            return "volatility"
        return "indicator"
    try:
        if name in indicator_registry._indicators:
            return "economic"
    except Exception:
        pass
    return None


def _raise_investor_positioning_error(exc: Exception, *, guru: str) -> None:
    if isinstance(exc, SecEdgarConfigurationError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_not_configured",
            status_code=503,
            details={"feature": "investor_positioning", "guru": guru},
        ) from exc
    if isinstance(exc, SecEdgarUnavailableError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_unavailable",
            status_code=503,
            details={"feature": "investor_positioning", "guru": guru},
        ) from exc
    raise exc
