from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from .service import TerraFinAgentService


ArtifactKind = Literal[
    "chart",
    "table",
    "report",
    "calendar_slice",
    "valuation_result",
    "portfolio_snapshot",
    "data_payload",
]
TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

CapabilityHandler = Callable[..., dict[str, Any]]
FocusExtractor = Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[str, ...]]
ArtifactBuilder = Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], "TerraFinArtifact | None"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_terminal_task_status(status: TaskStatus) -> bool:
    return status in {"completed", "failed", "cancelled"}


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in items:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _focus_from_input_keys(*keys: str) -> FocusExtractor:
    def _extract(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
        values: list[str] = []
        for key in keys:
            value = inputs.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                values.append(value)
                continue
            if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
                values.extend(str(item) for item in value)
                continue
            values.append(str(value))
        return tuple(_dedupe(values))

    return _extract


def _resolve_focus(_: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str, ...]:
    name = payload.get("name")
    if name is None:
        return ()
    return tuple(_dedupe([str(name)]))


def _economic_focus(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
    indicators = inputs.get("indicators")
    if indicators is None:
        return ()
    if isinstance(indicators, str):
        return tuple(_dedupe(part for part in indicators.split(",")))
    if isinstance(indicators, Iterable) and not isinstance(indicators, (bytes, bytearray, dict)):
        return tuple(_dedupe(str(item) for item in indicators))
    return tuple(_dedupe([str(indicators)]))


def _chart_focus(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
    value = inputs.get("data_or_names")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        names = [str(item) for item in value if isinstance(item, str)]
        return tuple(_dedupe(names))
    return ()


def _chart_artifact(
    session_id: str,
    capability_name: str,
    inputs: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> TerraFinArtifact | None:
    if not payload.get("ok"):
        return None
    chart_url = payload.get("chartUrl")
    chart_session_id = payload.get("sessionId")
    if chart_url is None or chart_session_id is None:
        return None

    focused = _chart_focus(inputs, payload)
    if focused:
        title = f"Chart: {', '.join(focused)}"
    else:
        title = "Chart Session"

    return TerraFinArtifact(
        artifact_id=str(chart_session_id),
        kind="chart",
        title=title,
        session_id=session_id,
        capability_name=capability_name,
        created_at=_utc_now(),
        payload={
            "chartUrl": str(chart_url),
            "sessionId": str(chart_session_id),
        },
    )


@dataclass(frozen=True, slots=True)
class TerraFinArtifact:
    artifact_id: str
    kind: ArtifactKind
    title: str
    session_id: str
    capability_name: str
    created_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinCapabilityCall:
    capability_name: str
    called_at: datetime
    inputs: dict[str, Any]
    output_keys: tuple[str, ...]
    focus_items: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TerraFinTaskRecord:
    task_id: str
    capability_name: str
    status: TaskStatus
    description: str
    session_id: str | None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_payload: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = 0


@dataclass(frozen=True, slots=True)
class TerraFinAgentSessionSnapshot:
    session_id: str
    focus_items: tuple[str, ...]
    artifacts: tuple[TerraFinArtifact, ...]
    capability_calls: tuple[TerraFinCapabilityCall, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TerraFinCapability:
    name: str
    description: str
    handler: CapabilityHandler
    focus_extractor: FocusExtractor | None = None
    artifact_builder: ArtifactBuilder | None = None
    side_effecting: bool = False
    backgroundable: bool = False

    def extract_focus(self, inputs: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str, ...]:
        if self.focus_extractor is None:
            return ()
        return tuple(_dedupe(self.focus_extractor(inputs, payload)))

    def build_artifact(
        self,
        session_id: str,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> TerraFinArtifact | None:
        if self.artifact_builder is None:
            return None
        return self.artifact_builder(session_id, self.name, inputs, payload)


class TerraFinCapabilityRegistry:
    def __init__(self, capabilities: Iterable[TerraFinCapability] | None = None) -> None:
        self._capabilities: dict[str, TerraFinCapability] = {}
        if capabilities is not None:
            for capability in capabilities:
                self.register(capability)

    def register(self, capability: TerraFinCapability) -> TerraFinCapability:
        if capability.name in self._capabilities:
            raise ValueError(f"Capability already registered: {capability.name}")
        self._capabilities[capability.name] = capability
        return capability

    def get(self, name: str) -> TerraFinCapability:
        try:
            return self._capabilities[name]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise KeyError(f"Unknown TerraFin capability: {name}") from exc

    def list(self) -> tuple[TerraFinCapability, ...]:
        return tuple(self._capabilities.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def invoke(
        self,
        capability_name: str,
        *,
        context: TerraFinAgentContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        capability = self.get(capability_name)
        payload = capability.handler(**kwargs)
        if not isinstance(payload, dict):
            raise TypeError(f"Capability '{capability_name}' must return a dict payload.")
        if context is not None:
            context._record_capability_result(capability, inputs=kwargs, payload=payload)
        return payload


@dataclass
class TerraFinAgentSession:
    session_id: str = field(default_factory=lambda: f"terrafin-session:{uuid4().hex}")
    focus_items: list[str] = field(default_factory=list)
    artifacts: list[TerraFinArtifact] = field(default_factory=list)
    capability_calls: list[TerraFinCapabilityCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_focus(self, *items: str) -> tuple[str, ...]:
        added: list[str] = []
        existing = set(self.focus_items)
        for item in _dedupe(items):
            if item in existing:
                continue
            existing.add(item)
            self.focus_items.append(item)
            added.append(item)
        return tuple(added)

    def record_artifact(self, artifact: TerraFinArtifact) -> TerraFinArtifact:
        self.artifacts.append(artifact)
        return artifact

    def record_capability_call(
        self,
        capability_name: str,
        *,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
        focus_items: Iterable[str] = (),
        artifacts: Iterable[TerraFinArtifact] = (),
    ) -> TerraFinCapabilityCall:
        record = TerraFinCapabilityCall(
            capability_name=capability_name,
            called_at=_utc_now(),
            inputs=dict(inputs),
            output_keys=tuple(sorted(payload.keys())),
            focus_items=tuple(_dedupe(focus_items)),
            artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
        )
        self.capability_calls.append(record)
        return record

    def snapshot(self) -> TerraFinAgentSessionSnapshot:
        return TerraFinAgentSessionSnapshot(
            session_id=self.session_id,
            focus_items=tuple(self.focus_items),
            artifacts=tuple(self.artifacts),
            capability_calls=tuple(self.capability_calls),
            metadata=dict(self.metadata),
        )


class TerraFinTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, TerraFinTaskRecord] = {}
        self._lock = RLock()

    def create(
        self,
        capability_name: str,
        *,
        description: str,
        session_id: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
    ) -> TerraFinTaskRecord:
        with self._lock:
            now = _utc_now()
            record = TerraFinTaskRecord(
                task_id=f"task:{uuid4().hex}",
                capability_name=capability_name,
                status="pending",
                description=description,
                session_id=session_id,
                created_at=now,
                input_payload=dict(input_payload or {}),
            )
            self._tasks[record.task_id] = record
            return record

    def claim(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_expires_at: datetime,
        progress: Mapping[str, Any] | None = None,
    ) -> TerraFinTaskRecord:
        with self._lock:
            previous = self._tasks[task_id]
            record = replace(
                previous,
                status="running",
                started_at=previous.started_at or _utc_now(),
                progress=dict(progress or previous.progress),
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
                attempt_count=previous.attempt_count + 1,
            )
            self._tasks[task_id] = record
            return record

    def get(self, task_id: str) -> TerraFinTaskRecord:
        with self._lock:
            return self._tasks[task_id]

    def list(self) -> tuple[TerraFinTaskRecord, ...]:
        with self._lock:
            return tuple(self._tasks.values())

    def list_for_session(self, session_id: str) -> tuple[TerraFinTaskRecord, ...]:
        with self._lock:
            return tuple(task for task in self._tasks.values() if task.session_id == session_id)

    def has_active_tasks(self) -> bool:
        with self._lock:
            return any(not _is_terminal_task_status(task.status) for task in self._tasks.values())

    def mark_running(self, task_id: str, *, progress: Mapping[str, Any] | None = None) -> TerraFinTaskRecord:
        with self._lock:
            previous = self._tasks[task_id]
            if _is_terminal_task_status(previous.status):
                return previous
            record = replace(
                previous,
                status="running",
                started_at=_utc_now(),
                progress=dict(progress or previous.progress),
                lease_expires_at=previous.lease_expires_at,
                worker_id=previous.worker_id,
            )
            self._tasks[task_id] = record
            return record

    def complete(
        self,
        task_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        progress: Mapping[str, Any] | None = None,
    ) -> TerraFinTaskRecord:
        with self._lock:
            previous = self._tasks[task_id]
            if _is_terminal_task_status(previous.status):
                return previous
            record = replace(
                previous,
                status="completed",
                completed_at=_utc_now(),
                result=dict(result) if result is not None else None,
                progress=dict(progress or previous.progress),
                error=None,
                worker_id=None,
                lease_expires_at=None,
            )
            self._tasks[task_id] = record
            return record

    def fail(self, task_id: str, *, error: str, progress: Mapping[str, Any] | None = None) -> TerraFinTaskRecord:
        with self._lock:
            previous = self._tasks[task_id]
            if _is_terminal_task_status(previous.status):
                return previous
            record = replace(
                previous,
                status="failed",
                completed_at=_utc_now(),
                progress=dict(progress or previous.progress),
                error=error,
                worker_id=None,
                lease_expires_at=None,
            )
            self._tasks[task_id] = record
            return record

    def cancel(self, task_id: str, *, reason: str | None = None) -> TerraFinTaskRecord:
        with self._lock:
            previous = self._tasks[task_id]
            if _is_terminal_task_status(previous.status):
                return previous
            record = replace(
                previous,
                status="cancelled",
                completed_at=_utc_now(),
                error=reason,
                worker_id=None,
                lease_expires_at=None,
            )
            self._tasks[task_id] = record
            return record

    def prune_terminal(self, *, completed_before: datetime) -> tuple[TerraFinTaskRecord, ...]:
        removed: list[TerraFinTaskRecord] = []
        with self._lock:
            for task_id, record in list(self._tasks.items()):
                if not _is_terminal_task_status(record.status):
                    continue
                if record.completed_at is None or record.completed_at >= completed_before:
                    continue
                removed.append(record)
                del self._tasks[task_id]
        return tuple(removed)


@dataclass
class TerraFinAgentContext:
    registry: TerraFinCapabilityRegistry
    session: TerraFinAgentSession = field(default_factory=TerraFinAgentSession)
    task_registry: TerraFinTaskRegistry = field(default_factory=TerraFinTaskRegistry)
    service: TerraFinAgentService | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def call(self, capability_name: str, /, **kwargs: Any) -> dict[str, Any]:
        return self.registry.invoke(capability_name, context=self, **kwargs)

    def run_task(
        self,
        capability_name: str,
        /,
        *,
        description: str | None = None,
        **kwargs: Any,
    ) -> tuple[TerraFinTaskRecord, dict[str, Any]]:
        task = self.task_registry.create(
            capability_name,
            description=description or capability_name.replace("_", " "),
            session_id=self.session.session_id,
            input_payload=kwargs,
        )
        self.task_registry.mark_running(task.task_id)
        try:
            result = self.call(capability_name, **kwargs)
        except Exception as exc:
            self.task_registry.fail(task.task_id, error=str(exc))
            raise
        completed = self.task_registry.complete(task.task_id, result=result)
        return completed, result

    def _record_capability_result(
        self,
        capability: TerraFinCapability,
        *,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> TerraFinCapabilityCall:
        focus_items = capability.extract_focus(inputs, payload)
        if focus_items:
            self.session.record_focus(*focus_items)

        artifacts: list[TerraFinArtifact] = []
        artifact = capability.build_artifact(self.session.session_id, inputs, payload)
        if artifact is not None:
            self.session.record_artifact(artifact)
            artifacts.append(artifact)

        return self.session.record_capability_call(
            capability.name,
            inputs=inputs,
            payload=payload,
            focus_items=focus_items,
            artifacts=artifacts,
        )


def build_default_capability_registry(
    service: TerraFinAgentService | None = None,
    *,
    chart_opener: Callable[..., dict[str, Any]] | None = None,
) -> TerraFinCapabilityRegistry:
    if chart_opener is None:
        from .tasks import open_chart as default_open_chart

    resolved_service = service or TerraFinAgentService()
    resolved_chart_opener = chart_opener or default_open_chart

    registry = TerraFinCapabilityRegistry(
        [
            TerraFinCapability(
                name="resolve",
                description="Resolve a free-form market or macro query into TerraFin routing.",
                handler=resolved_service.resolve,
                focus_extractor=_resolve_focus,
            ),
            TerraFinCapability(
                name="market_data",
                description="Fetch chart-ready market data for a single asset.",
                handler=resolved_service.market_data,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="indicators",
                description="Compute chart-matching technical indicators for a single asset.",
                handler=resolved_service.indicators,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="market_snapshot",
                description="Fetch a compact market snapshot for a single asset.",
                handler=resolved_service.market_snapshot,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="lppl_analysis",
                description="Run LPPL bubble analysis for a single asset.",
                handler=resolved_service.lppl_analysis,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="company_info",
                description="Fetch company profile and valuation fields for a ticker.",
                handler=resolved_service.company_info,
                focus_extractor=_focus_from_input_keys("ticker"),
            ),
            TerraFinCapability(
                name="earnings",
                description="Fetch earnings history for a ticker.",
                handler=resolved_service.earnings,
                focus_extractor=_focus_from_input_keys("ticker"),
            ),
            TerraFinCapability(
                name="financials",
                description="Fetch a financial statement table for a ticker.",
                handler=resolved_service.financials,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="portfolio",
                description="Fetch guru portfolio holdings and summary metadata.",
                handler=resolved_service.portfolio,
                focus_extractor=_focus_from_input_keys("guru"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="economic",
                description="Fetch economic indicator series.",
                handler=resolved_service.economic,
                focus_extractor=_economic_focus,
                backgroundable=True,
            ),
            TerraFinCapability(
                name="macro_focus",
                description="Fetch macro summary plus chart-ready series for an instrument.",
                handler=resolved_service.macro_focus,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="calendar_events",
                description="Fetch TerraFin calendar events for a month.",
                handler=resolved_service.calendar_events,
                backgroundable=True,
            ),
            # ----- Dashboard widget-parity capabilities -----
            # Each of these mirrors a standalone widget the user sees on the
            # dashboard / market-insights / stock-analysis pages. Without them
            # the user would be surprised the agent can't comment on something
            # they're staring at. Payloads pass through verbatim from the
            # `build_*_payload` / `get_*` route helpers so the two views never
            # diverge (DA audit: High-3/4/5, Med-6).
            TerraFinCapability(
                name="fear_greed",
                description=(
                    "Fetch the CNN Fear & Greed index — same data as the "
                    "`/dashboard/api/fear-greed` widget. Returns score, rating, "
                    "previous close, and 1W/1M history."
                ),
                handler=resolved_service.fear_greed,
            ),
            TerraFinCapability(
                name="sp500_dcf",
                description=(
                    "Fetch the full S&P 500 DCF valuation — same shape as "
                    "`/market-insights/api/dcf/sp500`. Includes scenarios, "
                    "sensitivity matrix, methods, rateCurve, dataQuality."
                ),
                handler=resolved_service.sp500_dcf,
                backgroundable=True,
            ),
            TerraFinCapability(
                name="beta_estimate",
                description=(
                    "Fetch a 5-year monthly beta estimate with adjusted beta, "
                    "R², and benchmark — same shape as `/stock/api/beta-estimate`. "
                    "Use this when you need the statistical quality of the beta; "
                    "`company_info` only surfaces a bare beta string."
                ),
                handler=resolved_service.beta_estimate,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="top_companies",
                description=(
                    "Fetch the market-insights top-companies list — same data as "
                    "`/market-insights/api/top-companies`."
                ),
                handler=resolved_service.top_companies,
            ),
            TerraFinCapability(
                name="market_regime",
                description=(
                    "Fetch the market regime summary — same data as "
                    "`/market-insights/api/regime`. Returns a short summary, "
                    "confidence, and bulleted signals."
                ),
                handler=resolved_service.market_regime,
            ),
            TerraFinCapability(
                name="trailing_forward_pe",
                description=(
                    "Fetch the trailing vs. forward P/E spread — same data as "
                    "`/dashboard/api/trailing-forward-pe-spread`."
                ),
                handler=resolved_service.trailing_forward_pe,
                backgroundable=True,
            ),
            TerraFinCapability(
                name="market_breadth",
                description=(
                    "Fetch standalone market-breadth metrics — same data as the "
                    "MarketBreadthCard widget. Was previously bundled inside "
                    "`market_snapshot`; use this capability when the question is "
                    "about whole-market state rather than a single ticker."
                ),
                handler=resolved_service.market_breadth,
            ),
            TerraFinCapability(
                name="watchlist",
                description=(
                    "Fetch the user's current watchlist — same data as the "
                    "WatchlistSection widget. Standalone now; was previously "
                    "bundled inside `market_snapshot`."
                ),
                handler=resolved_service.watchlist,
            ),
            TerraFinCapability(
                name="open_chart",
                description="Create or update a TerraFin chart session and return a chart artifact.",
                handler=resolved_chart_opener,
                focus_extractor=_chart_focus,
                artifact_builder=_chart_artifact,
                side_effecting=True,
            ),
            TerraFinCapability(
                name="fundamental_screen",
                description="Run fundamental quality and moat screening for a ticker (ROE, margins, earnings quality, balance sheet, pricing power).",
                handler=resolved_service.fundamental_screen,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="risk_profile",
                description="Compute statistical risk profile for an asset (tail risk, convexity, volatility regime, drawdown).",
                handler=resolved_service.risk_profile,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="valuation",
                description="Run DCF, reverse DCF, relative valuation, and Graham Number for a ticker.",
                handler=resolved_service.valuation,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="sec_filings",
                description=(
                    "List recent 10-K / 10-Q / 8-K filings for a ticker with SEC EDGAR links. "
                    "Call this ONCE when you need to pivot to a filing not currently in view. The "
                    "response's `latestByForm` dict is the direct lookup: "
                    "`latestByForm['10-K'].accession` / `.primaryDocument` give you everything "
                    "`sec_filing_section` needs. Do NOT scan the flat `filings` array — it's "
                    "chronological, so 8-Ks cluster at the top and the 10-K/10-Q you want may be in "
                    "position 5+.\n"
                    "If a filing is already shown in the user's view context, DON'T call this tool at "
                    "all — the accession and primaryDocument live in `current_view_context.selection`.\n"
                    "OUTPUT FORMAT — pick by question type:\n"
                    "• Quantitative filing analysis ('analyze the 10-Q', 'what do the numbers say'): "
                    "(1) lead with a '## TL;DR' of 3-5 bullets where each bullet is a punchline number "
                    "or concrete insight — no filler adjectives; "
                    "(2) follow with a compact '## Key numbers' table (≤6 rows) comparing current vs "
                    "prior-year period, showing only metrics that move the thesis; tables MUST include "
                    "the `| --- |` header-separator row after the header row; "
                    "(3) narrate with named subsections ('### The X story', '### The Y anomaly') of "
                    "≤3 sentences each, **bolding** one driver number per sentence maximum; "
                    "(4) close with '## Not disclosed in this filing' as a short bulleted list.\n"
                    "• Qualitative/descriptive question ('what is their business', 'how do they make "
                    "money', 'what are the risks'): 2-4 short paragraphs grounded in the full section "
                    "body (you MUST have called sec_filing_section first — don't answer off the 4 KB "
                    "excerpt). Lead with the single most important sentence, then add specifics: "
                    "products/segments, go-to-market, differentiation, any concrete numbers the "
                    "filing discloses. Skip the TL;DR bullets and Key-numbers table — they're for "
                    "quantitative questions, not descriptive ones.\n"
                    "EDITORIAL DISCIPLINE (strict — reviewers will reject otherwise): "
                    "(a) no adjectives not grounded in the filing text — avoid 'notable', 'heavy lifting', "
                    "'nearly wiped', 'pristine'; if you flip management's spin, cite the arithmetic that "
                    "supports the flip (and report the net number management disclosed); "
                    "(b) numbers in the TL;DR MUST match the Key-numbers table exactly — no '+12%' in one "
                    "and '+11.6%' in the other for the same metric; "
                    "(c) when the fixture provides both QoQ and YoY deltas (or both Q and YTD), report "
                    "both — a QoQ drop can hide YoY expansion and vice versa; "
                    "(d) scan every statement for line items moving >50% YoY and surface them — a "
                    "13x jump in a small bucket or a credits line halving is exactly what skimmers want; "
                    "(e) if MD&A rounding or direction contradicts what you compute from the statements, "
                    "report BOTH and prefer the statement-derived number, flagging the discrepancy."
                ),
                handler=resolved_service.sec_filings,
                focus_extractor=_focus_from_input_keys("ticker"),
            ),
            TerraFinCapability(
                name="sec_filing_document",
                description=(
                    "Fetch the table of contents (section titles, slugs, and sizes) for a specific "
                    "10-K, 10-Q, or other SEC filing. Returns structure only — use `sec_filing_section` "
                    "to pull the actual prose. Requires the accession and primaryDocument fields from "
                    "`sec_filings` or the current view context.\n"
                    "Analyst discovery protocol — do NOT assume fixed item numbers across different "
                    "forms. Instead, scan the TOC for titles containing these keywords:\n"
                    "• Financial Data: 'Financial Statements', 'Notes', 'Consolidated Statements'.\n"
                    "• Strategy & Operations: 'Business', 'Management's Discussion', 'MD&A'.\n"
                    "• Risk & Legal: 'Risk Factors', 'Legal Proceedings', 'Controls'.\n"
                    "Plan to fetch the specific sections that contain the evidence needed for your "
                    "answer rather than guessing from summaries."
                ),
                handler=resolved_service.sec_filing_document,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
            TerraFinCapability(
                name="sec_filing_section",
                description=(
                    "Fetch the verbatim markdown body of a single filing section by slug. "
                    "The slug MUST come verbatim from a prior `sec_filing_document` call's TOC — "
                    "NEVER guess slug names from SEC filing conventions (the parser does not always "
                    "match convention; trust the actual TOC, not your prior knowledge).\n"
                    "\n"
                    "REQUIRED WORKFLOW (follow in order):\n"
                    "1. Call `sec_filing_document(ticker, accession, primaryDocument, form)` first to "
                    "obtain the TOC. Every entry has `{slug, text, charCount}`.\n"
                    "2. Pick the slug whose `text` matches what the user is asking about. If no text "
                    "matches cleanly (e.g. user asked about 'earnings' but there is no Item labelled "
                    "'Financial Statements'), use `charCount` as a size signal — the LARGEST section "
                    "in the relevant Part usually contains the content. 10-K MD&A and Financial "
                    "Statements often appear as a single very large section when the parser misses the "
                    "Item 7 / Item 8 split; a 200 KB section body in Part II is almost certainly "
                    "financial reporting regardless of what its heading says.\n"
                    "3. Pass that exact slug string to this tool. Do not reformat it, translate it, or "
                    "guess a canonical form.\n"
                    "\n"
                    "IF THIS TOOL RETURNS 'section not found': do NOT tell the user the section "
                    "doesn't exist. The error response includes the full list of available slugs with "
                    "their sizes. Pick one from that list (prefer the largest one in the relevant Part "
                    "if no name matches), and retry this tool immediately. Only after a second real "
                    "failure should you report inability to find the content.\n"
                    "\n"
                    "OUTPUT PROPERTIES:\n"
                    "- Returns raw, un-truncated markdown including tables. Use the tables to "
                    "recompute margins, growth rates, and capital allocation signals directly from "
                    "source data — do not fall back to the `financials` summary tool.\n"
                    "- If the user is viewing a filing, the `sectionExcerpt` in their view-context is "
                    "only ~4 KB. Substantive questions (strategy, full financials, segment detail) "
                    "REQUIRE this tool to fetch the full section body (often 100 KB+).\n"
                    "\n"
                    "VERBATIM CITATION RULE:\n"
                    "When you quote risk factors, MD&A language, forward-looking statements, or "
                    "legal commitments from the returned body, copy the exact wording inside "
                    "quotation marks and name the section. Do NOT paraphrase — users need to be "
                    "able to verify what the filing actually says, not what you think it says. "
                    "Paraphrasing into friendlier English in safety-sensitive sections is a bug."
                ),
                handler=resolved_service.sec_filing_section,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
            ),
        ]
    )
    return registry


def create_agent_context(
    *,
    service: TerraFinAgentService | None = None,
    registry: TerraFinCapabilityRegistry | None = None,
    session: TerraFinAgentSession | None = None,
    task_registry: TerraFinTaskRegistry | None = None,
    chart_opener: Callable[..., dict[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TerraFinAgentContext:
    resolved_service = service or TerraFinAgentService()
    resolved_registry = registry or build_default_capability_registry(
        resolved_service,
        chart_opener=chart_opener,
    )
    return TerraFinAgentContext(
        registry=resolved_registry,
        session=session or TerraFinAgentSession(),
        task_registry=task_registry or TerraFinTaskRegistry(),
        service=resolved_service,
        metadata=dict(metadata or {}),
    )
