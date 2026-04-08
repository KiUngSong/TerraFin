from typing import Any, Literal

from pydantic import BaseModel, Field


DepthMode = Literal["auto", "recent", "full"]
ResolvedDepth = Literal["recent", "full"]
ChartView = Literal["daily", "weekly", "monthly", "yearly"]
SeriesType = Literal["line", "candlestick"]


class ProcessingMetadata(BaseModel):
    requestedDepth: DepthMode
    resolvedDepth: ResolvedDepth
    loadedStart: str | None = None
    loadedEnd: str | None = None
    isComplete: bool
    hasOlder: bool
    sourceVersion: str | None = None
    view: ChartView | None = None


class MarketDataPoint(BaseModel):
    time: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    value: float | None = None
    volume: float | None = None


class IndicatorResult(BaseModel):
    name: str
    offset: int
    values: dict[str, Any]


class IndicatorSummary(BaseModel):
    rsi: float | None = None
    macd_signal: str | None = None
    bb_position: str | None = None


class PriceAction(BaseModel):
    current: float | None = None
    change_1d: float | None = None
    change_5d: float | None = None


class ResolveResponse(BaseModel):
    type: str
    name: str
    path: str
    processing: ProcessingMetadata


class MarketDataResponse(BaseModel):
    ticker: str
    seriesType: SeriesType
    count: int
    data: list[MarketDataPoint]
    processing: ProcessingMetadata


class IndicatorsResponse(BaseModel):
    ticker: str
    indicators: dict[str, IndicatorResult]
    unknown: list[str]
    processing: ProcessingMetadata


class MarketSnapshotResponse(BaseModel):
    ticker: str
    price_action: PriceAction
    indicators: IndicatorSummary
    market_breadth: list[dict]
    watchlist: list[dict]
    processing: ProcessingMetadata


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
    processing: ProcessingMetadata


class EarningsRecord(BaseModel):
    date: str
    epsEstimate: str
    epsReported: str
    surprise: str
    surprisePercent: str


class EarningsResponse(BaseModel):
    ticker: str
    earnings: list[EarningsRecord]
    processing: ProcessingMetadata


class FinancialRow(BaseModel):
    label: str
    values: dict[str, str | float | None]


class FinancialStatementResponse(BaseModel):
    ticker: str
    statement: str
    period: str
    columns: list[str]
    rows: list[FinancialRow]
    processing: ProcessingMetadata


class PortfolioResponse(BaseModel):
    guru: str
    info: dict[str, str]
    holdings: list[dict]
    count: int
    processing: ProcessingMetadata


class EconomicIndicatorResult(BaseModel):
    name: str
    latest_value: float | None = None
    latest_time: str | None = None
    series: list[dict]


class EconomicResponse(BaseModel):
    indicators: dict[str, EconomicIndicatorResult]
    processing: ProcessingMetadata


class MacroInstrumentInfoResponse(BaseModel):
    name: str
    type: str
    description: str
    currentValue: float | None
    change: float | None
    changePercent: float | None


class MacroFocusResponse(BaseModel):
    name: str
    info: MacroInstrumentInfoResponse
    seriesType: SeriesType
    count: int
    data: list[MarketDataPoint]
    processing: ProcessingMetadata


class CalendarEventResponse(BaseModel):
    id: str
    title: str
    start: str
    category: Literal["earning", "macro", "event"] = "event"
    importance: str | None = None
    displayTime: str | None = None
    description: str | None = None
    source: str | None = None


class CalendarResponse(BaseModel):
    events: list[CalendarEventResponse]
    count: int
    month: int
    year: int
    processing: ProcessingMetadata


class LPPLFitDetail(BaseModel):
    tc: float
    m: float
    omega: float
    b: float
    c_over_b: float
    residual: float


class LPPLAnalysisResponse(BaseModel):
    name: str
    confidence: float
    interpretation: str
    market_state: str
    qualifying_count: int
    total_windows: int
    qualifying_fits: list[LPPLFitDetail]
    processing: ProcessingMetadata


class ChartOpenResponse(BaseModel):
    ok: bool
    sessionId: str
    chartUrl: str
    processing: ProcessingMetadata = Field(
        default_factory=lambda: ProcessingMetadata(
            requestedDepth="full",
            resolvedDepth="full",
            loadedStart=None,
            loadedEnd=None,
            isComplete=True,
            hasOlder=False,
            sourceVersion="chart-session",
            view=None,
        )
    )
