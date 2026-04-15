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
            TerraFinCapability(
                name="open_chart",
                description="Create or update a TerraFin chart session and return a chart artifact.",
                handler=resolved_chart_opener,
                focus_extractor=_chart_focus,
                artifact_builder=_chart_artifact,
                side_effecting=True,
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
