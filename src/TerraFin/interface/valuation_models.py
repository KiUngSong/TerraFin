from typing import Any

from pydantic import BaseModel, Field


class DCFValuationResponse(BaseModel):
    status: str
    entityType: str
    symbol: str
    asOf: str
    currentPrice: float | None = None
    currentIntrinsicValue: float | None = None
    upsidePct: float | None = None
    scenarios: dict[str, Any]
    assumptions: dict[str, Any]
    sensitivity: dict[str, Any]
    rateCurve: dict[str, Any]
    dataQuality: dict[str, Any]
    warnings: list[str]
    methods: list[dict[str, Any]] | None = None


class SP500YearAssumptionRequest(BaseModel):
    yearOffset: int = Field(..., ge=1, le=5)
    growthPct: float
    payoutRatioPct: float
    buybackRatioPct: float
    equityRiskPremiumPct: float


class SP500DCFRequest(BaseModel):
    baseYearEps: float | None = None
    terminalGrowthPct: float | None = None
    terminalEquityRiskPremiumPct: float | None = None
    terminalRoePct: float | None = None
    yearlyAssumptions: list[SP500YearAssumptionRequest] | None = None


class StockDCFRequest(BaseModel):
    baseCashFlowPerShare: float | None = None
    baseGrowthPct: float | None = None
    terminalGrowthPct: float | None = None
    beta: float | None = None
    equityRiskPremiumPct: float | None = None
    currentPrice: float | None = None
    projectionYears: int | None = Field(default=None)
    fcfBaseSource: str | None = Field(
        default=None,
        pattern="^(auto|3yr_avg|ttm|latest_annual)$",
    )
    breakevenYear: int | None = Field(default=None, ge=1, le=15)
    breakevenCashFlowPerShare: float | None = None
    postBreakevenGrowthPct: float | None = None


class ReverseDCFResponse(BaseModel):
    status: str
    entityType: str
    symbol: str
    asOf: str
    currentPrice: float | None = None
    baseCashFlowPerShare: float | None = None
    impliedGrowthPct: float | None = None
    modelPrice: float | None = None
    projectionYears: int
    growthProfile: dict[str, Any]
    priceToCashFlowMultiple: float | None = None
    terminalGrowthPct: float | None = None
    terminalDiscountRatePct: float | None = None
    terminalValue: float | None = None
    terminalPresentValueWeightPct: float | None = None
    discountSpreadPct: float | None = None
    assumptions: dict[str, Any]
    projectedCashFlows: list[dict[str, Any]]
    rateCurve: dict[str, Any]
    dataQuality: dict[str, Any]
    warnings: list[str]


class StockReverseDCFRequest(BaseModel):
    currentPrice: float | None = None
    baseCashFlowPerShare: float | None = None
    terminalGrowthPct: float | None = None
    beta: float | None = None
    equityRiskPremiumPct: float | None = None
    projectionYears: int | None = Field(default=5, ge=1, le=20)
    growthProfile: str | None = Field(
        default="early_maturity",
        pattern="^(high_growth|early_maturity|fully_mature)$",
    )
