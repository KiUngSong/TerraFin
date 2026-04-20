from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


# ---------------------------------------------------------------------------
# Permissive stubs for capabilities whose response shape is currently
# `dict[str, Any]`. Defined here so `tool_contracts.CAPABILITY_SCHEMAS` (which
# references them by string name) can resolve, FastAPI can advertise them in
# `/openapi.json`, and the upcoming generator can import them by name to
# emit accurate SKILL.md / docs entries. `extra="allow"` keeps the contract
# loose until each shape is tightened in a separate pass.
# ---------------------------------------------------------------------------


class _PermissiveResponse(BaseModel):
    """Base class for stub responses that mirror raw `dict[str, Any]` payloads."""

    model_config = ConfigDict(extra="allow")


class FundamentalScreenResponse(_PermissiveResponse):
    ticker: str | None = None


class RiskProfileResponse(_PermissiveResponse):
    name: str | None = None


class ValuationResponse(_PermissiveResponse):
    ticker: str | None = None


class SecFilingsListResponse(_PermissiveResponse):
    ticker: str | None = None


class SecFilingDocumentResponse(_PermissiveResponse):
    ticker: str | None = None
    accession: str | None = None
    primaryDocument: str | None = None


class SecFilingSectionResponse(_PermissiveResponse):
    ticker: str | None = None
    accession: str | None = None
    sectionSlug: str | None = None


class MarketBreadthResponse(_PermissiveResponse):
    pass


class WatchlistResponse(_PermissiveResponse):
    pass


class HostedToolDefinitionResponse(BaseModel):
    name: str
    capabilityName: str
    description: str
    executionMode: Literal["invoke", "task"]
    sideEffecting: bool
    inputSchema: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedRuntimeModelResponse(BaseModel):
    modelRef: str
    providerId: str
    providerLabel: str
    modelId: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedAgentDefinitionResponse(BaseModel):
    name: str
    description: str
    allowedCapabilities: list[str]
    defaultDepth: DepthMode
    defaultView: ChartView
    chartAccess: bool
    allowBackgroundTasks: bool
    runtimeModel: HostedRuntimeModelResponse | None = None
    runtimeConfigured: bool = True
    runtimeSetupMessage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tools: list[HostedToolDefinitionResponse] = Field(default_factory=list)


class HostedAgentCatalogResponse(BaseModel):
    agents: list[HostedAgentDefinitionResponse]


class HostedConversationMessageResponse(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    createdAt: str
    name: str | None = None
    toolCallId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedAgentSessionSummaryResponse(BaseModel):
    sessionId: str
    agentName: str
    createdAt: str
    updatedAt: str
    lastAccessedAt: str
    runtimeModel: HostedRuntimeModelResponse | None = None
    title: str | None = None
    lastMessagePreview: str | None = None
    lastMessageAt: str | None = None
    messageCount: int = 0
    pendingTaskCount: int = 0


class HostedAgentSessionListResponse(BaseModel):
    sessions: list[HostedAgentSessionSummaryResponse] = Field(default_factory=list)


class HostedAgentSessionDeleteResponse(BaseModel):
    sessionId: str
    deletedAt: str


class HostedTaskSummaryResponse(BaseModel):
    taskId: str
    status: str
    description: str


class HostedSessionPolicyResponse(BaseModel):
    defaultDepth: DepthMode
    defaultView: ChartView
    chartAccess: bool
    allowBackgroundTasks: bool
    requireHumanApprovalForSideEffects: bool = False
    requireHumanApprovalForBackgroundTasks: bool = False


class HostedArtifactResponse(BaseModel):
    artifactId: str
    kind: str
    title: str
    capabilityName: str
    createdAt: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HostedCapabilityCallResponse(BaseModel):
    capabilityName: str
    calledAt: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputKeys: list[str] = Field(default_factory=list)
    focusItems: list[str] = Field(default_factory=list)
    artifactIds: list[str] = Field(default_factory=list)


class HostedPermissionAuditResponse(BaseModel):
    eventId: str
    createdAt: str
    action: Literal["invoke", "task", "cancel_task", "approve", "deny"]
    capabilityName: str | None = None
    toolName: str | None = None
    sideEffecting: bool
    outcome: Literal["allowed", "denied", "pending"]
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedApprovalResponse(BaseModel):
    approvalId: str
    createdAt: str
    updatedAt: str
    resolvedAt: str | None = None
    sessionId: str
    agentName: str
    action: Literal["invoke", "task"]
    capabilityName: str
    toolName: str | None = None
    sideEffecting: bool
    status: Literal["pending", "approved", "denied", "consumed"]
    reason: str
    inputPayload: dict[str, Any] = Field(default_factory=dict)
    decisionNote: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedTaskResponse(BaseModel):
    taskId: str
    capabilityName: str
    status: str
    description: str
    sessionId: str | None = None
    createdAt: str
    startedAt: str | None = None
    completedAt: str | None = None
    inputPayload: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None


class HostedTaskListResponse(BaseModel):
    sessionId: str
    tasks: list[HostedTaskResponse] = Field(default_factory=list)


class HostedApprovalListResponse(BaseModel):
    sessionId: str
    approvals: list[HostedApprovalResponse] = Field(default_factory=list)


class HostedToolInvocationResponse(BaseModel):
    toolName: str
    capabilityName: str
    executionMode: Literal["invoke", "task"]
    payload: dict[str, Any]
    task: HostedTaskSummaryResponse | None = None


class HostedAgentSessionCreateRequest(BaseModel):
    agentName: str = Field(min_length=1)
    sessionId: str | None = None
    systemPrompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedAgentMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    # Browser's current view-context id. The hosted session records the
    # viewContextId it was created with, but a long-lived session outlives a
    # single sessionStorage (new tab, cleared storage, etc.), so the browser
    # sends its live id on every message and the server refreshes the link.
    viewContextId: str | None = None


class HostedApprovalDecisionRequest(BaseModel):
    note: str | None = None


class HostedViewContextUpdateRequest(BaseModel):
    route: str = Field(min_length=1)
    pageType: str = Field(min_length=1)
    title: str | None = None
    summary: str | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedViewContextResponse(BaseModel):
    contextId: str
    createdAt: str
    updatedAt: str
    route: str
    pageType: str
    title: str | None = None
    summary: str | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostedAgentSessionResponse(BaseModel):
    sessionId: str
    agentName: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    runtimeModel: HostedRuntimeModelResponse | None = None
    policy: HostedSessionPolicyResponse | None = None
    focusItems: list[str] = Field(default_factory=list)
    artifacts: list[HostedArtifactResponse] = Field(default_factory=list)
    capabilityCalls: list[HostedCapabilityCallResponse] = Field(default_factory=list)
    tasks: list[HostedTaskResponse] = Field(default_factory=list)
    approvals: list[HostedApprovalResponse] = Field(default_factory=list)
    auditTrail: list[HostedPermissionAuditResponse] = Field(default_factory=list)
    tools: list[HostedToolDefinitionResponse] = Field(default_factory=list)
    messages: list[HostedConversationMessageResponse] = Field(default_factory=list)


class HostedAgentRunResponse(BaseModel):
    sessionId: str
    agentName: str
    steps: int
    finalMessage: HostedConversationMessageResponse | None = None
    messagesAdded: list[HostedConversationMessageResponse] = Field(default_factory=list)
    toolResults: list[HostedToolInvocationResponse] = Field(default_factory=list)
    session: HostedAgentSessionResponse
