from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from .runtime import (
    TerraFinAgentContext,
    TerraFinAgentSession,
    TerraFinArtifact,
    TerraFinCapabilityCall,
    TerraFinTaskRecord,
    TerraFinTaskRegistry,
    create_agent_context,
)


if TYPE_CHECKING:
    from .loop import TerraFinHostedConversation
    from .runtime import TerraFinCapabilityRegistry
    from .service import TerraFinAgentService


PermissionAction = Literal["invoke", "task", "cancel_task", "approve", "deny"]
PermissionOutcome = Literal["allowed", "denied", "pending"]
ApprovalStatus = Literal["pending", "approved", "denied", "consumed"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class TerraFinHostedPermissionEvent:
    event_id: str
    created_at: datetime
    session_id: str
    agent_name: str
    action: PermissionAction
    capability_name: str | None
    tool_name: str | None
    side_effecting: bool
    outcome: PermissionOutcome
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinHostedApprovalRequest:
    approval_id: str
    created_at: datetime
    updated_at: datetime
    session_id: str
    agent_name: str
    action: Literal["invoke", "task"]
    capability_name: str
    tool_name: str | None
    side_effecting: bool
    status: ApprovalStatus
    reason: str
    fingerprint: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    decision_note: str | None = None
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinHostedViewContextRecord:
    context_id: str
    created_at: datetime
    updated_at: datetime
    route: str
    page_type: str
    title: str | None = None
    summary: str | None = None
    selection: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TerraFinHostedSessionRecord:
    session_id: str
    agent_name: str
    context: TerraFinAgentContext
    metadata: dict[str, Any]
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_accessed_at: datetime = field(default_factory=_utc_now)
    conversation: TerraFinHostedConversation | None = None
    audit_log: list[TerraFinHostedPermissionEvent] = field(default_factory=list)
    approval_requests: list[TerraFinHostedApprovalRequest] = field(default_factory=list)

    def touch(self) -> "TerraFinHostedSessionRecord":
        now = _utc_now()
        self.updated_at = now
        self.last_accessed_at = now
        return self


class HostedSessionStore:
    def create(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def get(self, session_id: str) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def list(self) -> tuple[TerraFinHostedSessionRecord, ...]:
        raise NotImplementedError

    def attach_conversation(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
    ) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def touch(self, session_id: str) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def append_audit(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: PermissionAction,
        capability_name: str | None,
        tool_name: str | None,
        side_effecting: bool,
        outcome: PermissionOutcome,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedPermissionEvent:
        raise NotImplementedError

    def create_approval(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: Literal["invoke", "task"],
        capability_name: str,
        tool_name: str | None,
        side_effecting: bool,
        reason: str,
        fingerprint: str,
        input_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        raise NotImplementedError

    def update_approval(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decision_note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        raise NotImplementedError

    def find_approval(
        self,
        approval_id: str,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinHostedApprovalRequest]:
        raise NotImplementedError

    def upsert_view_context(
        self,
        context_id: str,
        *,
        route: str,
        page_type: str,
        title: str | None = None,
        summary: str | None = None,
        selection: dict[str, Any] | None = None,
        entities: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedViewContextRecord:
        raise NotImplementedError

    def get_view_context(self, context_id: str) -> TerraFinHostedViewContextRecord:
        raise NotImplementedError

    def claim_pending_task(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinTaskRecord] | None:
        raise NotImplementedError

    def persist(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def delete(self, session_id: str) -> TerraFinHostedSessionRecord:
        raise NotImplementedError

    def cleanup_expired(self, *, session_ttl_seconds: int) -> tuple[TerraFinHostedSessionRecord, ...]:
        raise NotImplementedError


def _serialize_artifact(artifact: TerraFinArtifact) -> dict[str, Any]:
    return {
        "artifactId": artifact.artifact_id,
        "kind": artifact.kind,
        "title": artifact.title,
        "sessionId": artifact.session_id,
        "capabilityName": artifact.capability_name,
        "createdAt": artifact.created_at.isoformat(),
        "payload": dict(artifact.payload),
    }


def _deserialize_artifact(payload: dict[str, Any]) -> TerraFinArtifact:
    return TerraFinArtifact(
        artifact_id=str(payload["artifactId"]),
        kind=str(payload["kind"]),
        title=str(payload["title"]),
        session_id=str(payload["sessionId"]),
        capability_name=str(payload["capabilityName"]),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        payload=dict(payload.get("payload", {})),
    )


def _serialize_capability_call(call: TerraFinCapabilityCall) -> dict[str, Any]:
    return {
        "capabilityName": call.capability_name,
        "calledAt": call.called_at.isoformat(),
        "inputs": dict(call.inputs),
        "outputKeys": list(call.output_keys),
        "focusItems": list(call.focus_items),
        "artifactIds": list(call.artifact_ids),
    }


def _deserialize_capability_call(payload: dict[str, Any]) -> TerraFinCapabilityCall:
    return TerraFinCapabilityCall(
        capability_name=str(payload["capabilityName"]),
        called_at=_parse_datetime(str(payload["calledAt"])) or _utc_now(),
        inputs=dict(payload.get("inputs", {})),
        output_keys=tuple(str(item) for item in payload.get("outputKeys", [])),
        focus_items=tuple(str(item) for item in payload.get("focusItems", [])),
        artifact_ids=tuple(str(item) for item in payload.get("artifactIds", [])),
    )


def _serialize_task(task: TerraFinTaskRecord) -> dict[str, Any]:
    return {
        "taskId": task.task_id,
        "capabilityName": task.capability_name,
        "status": task.status,
        "description": task.description,
        "sessionId": task.session_id,
        "createdAt": task.created_at.isoformat(),
        "startedAt": _isoformat(task.started_at),
        "completedAt": _isoformat(task.completed_at),
        "inputPayload": dict(task.input_payload),
        "progress": dict(task.progress),
        "result": None if task.result is None else dict(task.result),
        "error": task.error,
        "workerId": task.worker_id,
        "leaseExpiresAt": _isoformat(task.lease_expires_at),
        "attemptCount": task.attempt_count,
    }


def _deserialize_task(payload: dict[str, Any]) -> TerraFinTaskRecord:
    return TerraFinTaskRecord(
        task_id=str(payload["taskId"]),
        capability_name=str(payload["capabilityName"]),
        status=str(payload["status"]),
        description=str(payload["description"]),
        session_id=payload.get("sessionId"),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        started_at=_parse_datetime(payload.get("startedAt")),
        completed_at=_parse_datetime(payload.get("completedAt")),
        input_payload=dict(payload.get("inputPayload", {})),
        progress=dict(payload.get("progress", {})),
        result=None if payload.get("result") is None else dict(payload["result"]),
        error=payload.get("error"),
        worker_id=payload.get("workerId"),
        lease_expires_at=_parse_datetime(payload.get("leaseExpiresAt")),
        attempt_count=int(payload.get("attemptCount", 0)),
    )


def _task_is_claimable(task: TerraFinTaskRecord, *, now: datetime) -> bool:
    if task.status == "pending":
        return True
    if task.status != "running":
        return False
    return task.lease_expires_at is not None and task.lease_expires_at <= now


def _serialize_audit(event: TerraFinHostedPermissionEvent) -> dict[str, Any]:
    return {
        "eventId": event.event_id,
        "createdAt": event.created_at.isoformat(),
        "sessionId": event.session_id,
        "agentName": event.agent_name,
        "action": event.action,
        "capabilityName": event.capability_name,
        "toolName": event.tool_name,
        "sideEffecting": event.side_effecting,
        "outcome": event.outcome,
        "reason": event.reason,
        "metadata": dict(event.metadata),
    }


def _deserialize_audit(payload: dict[str, Any]) -> TerraFinHostedPermissionEvent:
    return TerraFinHostedPermissionEvent(
        event_id=str(payload["eventId"]),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        session_id=str(payload["sessionId"]),
        agent_name=str(payload["agentName"]),
        action=str(payload["action"]),
        capability_name=payload.get("capabilityName"),
        tool_name=payload.get("toolName"),
        side_effecting=bool(payload.get("sideEffecting", False)),
        outcome=str(payload["outcome"]),
        reason=str(payload["reason"]),
        metadata=dict(payload.get("metadata", {})),
    )


def _serialize_approval(approval: TerraFinHostedApprovalRequest) -> dict[str, Any]:
    return {
        "approvalId": approval.approval_id,
        "createdAt": approval.created_at.isoformat(),
        "updatedAt": approval.updated_at.isoformat(),
        "resolvedAt": _isoformat(approval.resolved_at),
        "sessionId": approval.session_id,
        "agentName": approval.agent_name,
        "action": approval.action,
        "capabilityName": approval.capability_name,
        "toolName": approval.tool_name,
        "sideEffecting": approval.side_effecting,
        "status": approval.status,
        "reason": approval.reason,
        "fingerprint": approval.fingerprint,
        "inputPayload": dict(approval.input_payload),
        "decisionNote": approval.decision_note,
        "metadata": dict(approval.metadata),
    }


def _deserialize_approval(payload: dict[str, Any]) -> TerraFinHostedApprovalRequest:
    return TerraFinHostedApprovalRequest(
        approval_id=str(payload["approvalId"]),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        updated_at=_parse_datetime(str(payload["updatedAt"])) or _utc_now(),
        resolved_at=_parse_datetime(payload.get("resolvedAt")),
        session_id=str(payload["sessionId"]),
        agent_name=str(payload["agentName"]),
        action=str(payload["action"]),
        capability_name=str(payload["capabilityName"]),
        tool_name=payload.get("toolName"),
        side_effecting=bool(payload.get("sideEffecting", False)),
        status=str(payload["status"]),
        reason=str(payload["reason"]),
        fingerprint=str(payload["fingerprint"]),
        input_payload=dict(payload.get("inputPayload", {})),
        decision_note=payload.get("decisionNote"),
        metadata=dict(payload.get("metadata", {})),
    )


def _serialize_view_context(record: TerraFinHostedViewContextRecord) -> dict[str, Any]:
    return {
        "contextId": record.context_id,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "route": record.route,
        "pageType": record.page_type,
        "title": record.title,
        "summary": record.summary,
        "selection": dict(record.selection),
        "entities": [dict(entity) for entity in record.entities],
        "metadata": dict(record.metadata),
    }


def _deserialize_view_context(payload: dict[str, Any]) -> TerraFinHostedViewContextRecord:
    return TerraFinHostedViewContextRecord(
        context_id=str(payload["contextId"]),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        updated_at=_parse_datetime(str(payload["updatedAt"])) or _utc_now(),
        route=str(payload["route"]),
        page_type=str(payload["pageType"]),
        title=payload.get("title"),
        summary=payload.get("summary"),
        selection=dict(payload.get("selection", {})),
        entities=[dict(entity) for entity in payload.get("entities", [])],
        metadata=dict(payload.get("metadata", {})),
    )


def _serialize_record(record: TerraFinHostedSessionRecord) -> dict[str, Any]:
    session = record.context.session
    return {
        "sessionId": record.session_id,
        "agentName": record.agent_name,
        "metadata": dict(record.metadata),
        "contextMetadata": dict(record.context.metadata),
        "sessionMetadata": dict(session.metadata),
        "focusItems": list(session.focus_items),
        "artifacts": [_serialize_artifact(artifact) for artifact in session.artifacts],
        "capabilityCalls": [_serialize_capability_call(call) for call in session.capability_calls],
        "tasks": [_serialize_task(task) for task in record.context.task_registry.list()],
        "auditLog": [_serialize_audit(event) for event in record.audit_log],
        "approvals": [_serialize_approval(approval) for approval in record.approval_requests],
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "lastAccessedAt": record.last_accessed_at.isoformat(),
    }


def _deserialize_record(
    payload: dict[str, Any],
    *,
    service: TerraFinAgentService,
    registry: TerraFinCapabilityRegistry,
) -> TerraFinHostedSessionRecord:
    session = TerraFinAgentSession(
        session_id=str(payload["sessionId"]),
        focus_items=[str(item) for item in payload.get("focusItems", [])],
        artifacts=[_deserialize_artifact(item) for item in payload.get("artifacts", [])],
        capability_calls=[_deserialize_capability_call(item) for item in payload.get("capabilityCalls", [])],
        metadata=dict(payload.get("sessionMetadata", payload.get("metadata", {}))),
    )
    task_registry = TerraFinTaskRegistry()
    for task_payload in payload.get("tasks", []):
        task = _deserialize_task(task_payload)
        task_registry._tasks[task.task_id] = task
    context = create_agent_context(
        service=service,
        registry=registry,
        session=session,
        task_registry=task_registry,
        metadata=dict(payload.get("contextMetadata", payload.get("metadata", {}))),
    )
    return TerraFinHostedSessionRecord(
        session_id=str(payload["sessionId"]),
        agent_name=str(payload["agentName"]),
        context=context,
        metadata=dict(payload.get("metadata", {})),
        created_at=_parse_datetime(str(payload["createdAt"])) or _utc_now(),
        updated_at=_parse_datetime(str(payload["updatedAt"])) or _utc_now(),
        last_accessed_at=_parse_datetime(str(payload["lastAccessedAt"])) or _utc_now(),
        audit_log=[_deserialize_audit(item) for item in payload.get("auditLog", [])],
        approval_requests=[_deserialize_approval(item) for item in payload.get("approvals", [])],
    )


class InMemoryHostedSessionStore(HostedSessionStore):
    def __init__(self) -> None:
        self._records: dict[str, TerraFinHostedSessionRecord] = {}
        self._view_contexts: dict[str, TerraFinHostedViewContextRecord] = {}
        self._lock = RLock()

    def create(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        with self._lock:
            if record.session_id in self._records:
                raise ValueError(f"Hosted runtime session already exists: {record.session_id}")
            self._records[record.session_id] = record
            return record

    def get(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            return self._records[session_id]

    def list(self) -> tuple[TerraFinHostedSessionRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def attach_conversation(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
    ) -> TerraFinHostedSessionRecord:
        with self._lock:
            record = self._records[session_id]
            record.conversation = conversation
            return record

    def touch(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            record = self._records[session_id]
            record.touch()
            return record

    def append_audit(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: PermissionAction,
        capability_name: str | None,
        tool_name: str | None,
        side_effecting: bool,
        outcome: PermissionOutcome,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedPermissionEvent:
        with self._lock:
            record = self._records[session_id]
            event = TerraFinHostedPermissionEvent(
                event_id=f"audit:{uuid4().hex}",
                created_at=_utc_now(),
                session_id=session_id,
                agent_name=agent_name,
                action=action,
                capability_name=capability_name,
                tool_name=tool_name,
                side_effecting=side_effecting,
                outcome=outcome,
                reason=reason,
                metadata=dict(metadata or {}),
            )
            record.audit_log.append(event)
            record.touch()
            return event

    def create_approval(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: Literal["invoke", "task"],
        capability_name: str,
        tool_name: str | None,
        side_effecting: bool,
        reason: str,
        fingerprint: str,
        input_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        with self._lock:
            record = self._records[session_id]
            approval = TerraFinHostedApprovalRequest(
                approval_id=f"approval:{uuid4().hex}",
                created_at=_utc_now(),
                updated_at=_utc_now(),
                session_id=session_id,
                agent_name=agent_name,
                action=action,
                capability_name=capability_name,
                tool_name=tool_name,
                side_effecting=side_effecting,
                status="pending",
                reason=reason,
                fingerprint=fingerprint,
                input_payload=dict(input_payload or {}),
                metadata=dict(metadata or {}),
            )
            record.approval_requests.append(approval)
            record.touch()
            return approval

    def update_approval(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decision_note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        with self._lock:
            record, approval = self.find_approval(approval_id)
            updated = replace(
                approval,
                status=status,
                updated_at=_utc_now(),
                decision_note=decision_note,
                resolved_at=_utc_now() if status in {"approved", "denied", "consumed"} else None,
                metadata={**dict(approval.metadata), **dict(metadata or {})},
            )
            record.approval_requests = [
                updated if item.approval_id == approval_id else item for item in record.approval_requests
            ]
            record.touch()
            return updated

    def find_approval(
        self,
        approval_id: str,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinHostedApprovalRequest]:
        with self._lock:
            for record in self._records.values():
                for approval in record.approval_requests:
                    if approval.approval_id == approval_id:
                        return record, approval
        raise KeyError(f"Unknown TerraFin hosted approval request: {approval_id}")

    def upsert_view_context(
        self,
        context_id: str,
        *,
        route: str,
        page_type: str,
        title: str | None = None,
        summary: str | None = None,
        selection: dict[str, Any] | None = None,
        entities: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedViewContextRecord:
        with self._lock:
            existing = self._view_contexts.get(context_id)
            now = _utc_now()
            record = TerraFinHostedViewContextRecord(
                context_id=context_id,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
                route=route,
                page_type=page_type,
                title=title,
                summary=summary,
                selection=dict(selection or {}),
                entities=[dict(entity) for entity in (entities or [])],
                metadata=dict(metadata or {}),
            )
            self._view_contexts[context_id] = record
            return record

    def get_view_context(self, context_id: str) -> TerraFinHostedViewContextRecord:
        with self._lock:
            return self._view_contexts[context_id]

    def claim_pending_task(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinTaskRecord] | None:
        with self._lock:
            now = _utc_now()
            lease_expires_at = now + timedelta(seconds=max(lease_seconds, 1))
            for record in self._records.values():
                for task in record.context.task_registry.list_for_session(record.session_id):
                    if not _task_is_claimable(task, now=now):
                        continue
                    claimed = record.context.task_registry.claim(
                        task.task_id,
                        worker_id=worker_id,
                        lease_expires_at=lease_expires_at,
                        progress={**dict(task.progress), "state": "running"},
                    )
                    record.touch()
                    return record, claimed
        return None

    def persist(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        with self._lock:
            self._records[record.session_id] = record
            record.touch()
            return record

    def delete(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            return self._records.pop(session_id)

    def cleanup_expired(self, *, session_ttl_seconds: int) -> tuple[TerraFinHostedSessionRecord, ...]:
        if session_ttl_seconds <= 0:
            return ()
        cutoff = _utc_now() - timedelta(seconds=session_ttl_seconds)
        removed: list[TerraFinHostedSessionRecord] = []
        with self._lock:
            for session_id, record in list(self._records.items()):
                if record.last_accessed_at >= cutoff:
                    continue
                if record.context.task_registry.has_active_tasks():
                    continue
                removed.append(record)
                del self._records[session_id]
        return tuple(removed)


class SQLiteHostedSessionStore(HostedSessionStore):
    def __init__(
        self,
        *,
        db_path: str | Path,
        service: TerraFinAgentService,
        registry: TerraFinCapabilityRegistry,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._service = service
        self._registry = registry
        self._lock = RLock()
        self._cache: dict[str, TerraFinHostedSessionRecord] = {}
        self._view_context_cache: dict[str, TerraFinHostedViewContextRecord] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=30.0)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hosted_sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hosted_sessions_last_accessed
                ON hosted_sessions(last_accessed_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hosted_view_contexts (
                    context_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hosted_view_contexts_updated
                ON hosted_view_contexts(updated_at)
                """
            )

    def _save_record(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        payload = json.dumps(_serialize_record(record), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO hosted_sessions(session_id, agent_name, payload, updated_at, last_accessed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_name=excluded.agent_name,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at,
                    last_accessed_at=excluded.last_accessed_at
                """,
                (
                    record.session_id,
                    record.agent_name,
                    payload,
                    record.updated_at.isoformat(),
                    record.last_accessed_at.isoformat(),
                ),
            )
        self._cache[record.session_id] = record
        return record

    def _load_record(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM hosted_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        payload = json.loads(str(row[0]))
        record = _deserialize_record(payload, service=self._service, registry=self._registry)
        self._cache[record.session_id] = record
        return record

    def _save_view_context(
        self,
        record: TerraFinHostedViewContextRecord,
    ) -> TerraFinHostedViewContextRecord:
        payload = json.dumps(_serialize_view_context(record), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO hosted_view_contexts(context_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(context_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    record.context_id,
                    payload,
                    record.updated_at.isoformat(),
                ),
            )
        self._view_context_cache[record.context_id] = record
        return record

    def _load_view_context(self, context_id: str) -> TerraFinHostedViewContextRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM hosted_view_contexts WHERE context_id = ?",
                (context_id,),
            ).fetchone()
        if row is None:
            raise KeyError(context_id)
        record = _deserialize_view_context(json.loads(str(row[0])))
        self._view_context_cache[record.context_id] = record
        return record

    def create(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        with self._lock:
            try:
                self.get(record.session_id)
            except KeyError:
                pass
            else:
                raise ValueError(f"Hosted runtime session already exists: {record.session_id}")
            return self._save_record(record)

    def get(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            if session_id in self._cache:
                return self._cache[session_id]
            return self._load_record(session_id)

    def list(self) -> tuple[TerraFinHostedSessionRecord, ...]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute("SELECT payload FROM hosted_sessions ORDER BY updated_at DESC").fetchall()
            records = [
                _deserialize_record(json.loads(str(row[0])), service=self._service, registry=self._registry)
                for row in rows
            ]
            self._cache = {record.session_id: record for record in records}
            return tuple(records)

    def attach_conversation(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
    ) -> TerraFinHostedSessionRecord:
        with self._lock:
            record = self.get(session_id)
            record.conversation = conversation
            self._cache[record.session_id] = record
            return record

    def touch(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            record = self.get(session_id)
            record.touch()
            return self._save_record(record)

    def append_audit(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: PermissionAction,
        capability_name: str | None,
        tool_name: str | None,
        side_effecting: bool,
        outcome: PermissionOutcome,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedPermissionEvent:
        with self._lock:
            record = self.get(session_id)
            event = TerraFinHostedPermissionEvent(
                event_id=f"audit:{uuid4().hex}",
                created_at=_utc_now(),
                session_id=session_id,
                agent_name=agent_name,
                action=action,
                capability_name=capability_name,
                tool_name=tool_name,
                side_effecting=side_effecting,
                outcome=outcome,
                reason=reason,
                metadata=dict(metadata or {}),
            )
            record.audit_log.append(event)
            record.touch()
            self._save_record(record)
            return event

    def create_approval(
        self,
        session_id: str,
        *,
        agent_name: str,
        action: Literal["invoke", "task"],
        capability_name: str,
        tool_name: str | None,
        side_effecting: bool,
        reason: str,
        fingerprint: str,
        input_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        with self._lock:
            record = self.get(session_id)
            approval = TerraFinHostedApprovalRequest(
                approval_id=f"approval:{uuid4().hex}",
                created_at=_utc_now(),
                updated_at=_utc_now(),
                session_id=session_id,
                agent_name=agent_name,
                action=action,
                capability_name=capability_name,
                tool_name=tool_name,
                side_effecting=side_effecting,
                status="pending",
                reason=reason,
                fingerprint=fingerprint,
                input_payload=dict(input_payload or {}),
                metadata=dict(metadata or {}),
            )
            record.approval_requests.append(approval)
            record.touch()
            self._save_record(record)
            return approval

    def update_approval(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decision_note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedApprovalRequest:
        with self._lock:
            record, approval = self.find_approval(approval_id)
            updated = replace(
                approval,
                status=status,
                updated_at=_utc_now(),
                decision_note=decision_note,
                resolved_at=_utc_now() if status in {"approved", "denied", "consumed"} else None,
                metadata={**dict(approval.metadata), **dict(metadata or {})},
            )
            record.approval_requests = [
                updated if item.approval_id == approval_id else item for item in record.approval_requests
            ]
            record.touch()
            self._save_record(record)
            return updated

    def find_approval(
        self,
        approval_id: str,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinHostedApprovalRequest]:
        with self._lock:
            for record in self._cache.values():
                for approval in record.approval_requests:
                    if approval.approval_id == approval_id:
                        return record, approval
            for record in self.list():
                for approval in record.approval_requests:
                    if approval.approval_id == approval_id:
                        return record, approval
        raise KeyError(f"Unknown TerraFin hosted approval request: {approval_id}")

    def upsert_view_context(
        self,
        context_id: str,
        *,
        route: str,
        page_type: str,
        title: str | None = None,
        summary: str | None = None,
        selection: dict[str, Any] | None = None,
        entities: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerraFinHostedViewContextRecord:
        with self._lock:
            try:
                existing = self.get_view_context(context_id)
            except KeyError:
                existing = None
            now = _utc_now()
            record = TerraFinHostedViewContextRecord(
                context_id=context_id,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
                route=route,
                page_type=page_type,
                title=title,
                summary=summary,
                selection=dict(selection or {}),
                entities=[dict(entity) for entity in (entities or [])],
                metadata=dict(metadata or {}),
            )
            return self._save_view_context(record)

    def get_view_context(self, context_id: str) -> TerraFinHostedViewContextRecord:
        with self._lock:
            return self._load_view_context(context_id)

    def claim_pending_task(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> tuple[TerraFinHostedSessionRecord, TerraFinTaskRecord] | None:
        with self._lock:
            now = _utc_now()
            lease_expires_at = now + timedelta(seconds=max(lease_seconds, 1))
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT session_id, payload FROM hosted_sessions ORDER BY updated_at ASC"
                ).fetchall()
                for session_id, payload_json in rows:
                    payload = json.loads(str(payload_json))
                    tasks = list(payload.get("tasks", []))
                    for index, task_payload in enumerate(tasks):
                        task = _deserialize_task(task_payload)
                        if not _task_is_claimable(task, now=now):
                            continue
                        updated_task = replace(
                            task,
                            status="running",
                            started_at=task.started_at or now,
                            progress={**dict(task.progress), "state": "running"},
                            worker_id=worker_id,
                            lease_expires_at=lease_expires_at,
                            attempt_count=task.attempt_count + 1,
                        )
                        tasks[index] = _serialize_task(updated_task)
                        payload["tasks"] = tasks
                        payload["updatedAt"] = now.isoformat()
                        payload["lastAccessedAt"] = payload.get("lastAccessedAt") or now.isoformat()
                        connection.execute(
                            """
                            UPDATE hosted_sessions
                            SET payload = ?, updated_at = ?, last_accessed_at = ?
                            WHERE session_id = ?
                            """,
                            (
                                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                payload["updatedAt"],
                                payload["lastAccessedAt"],
                                str(session_id),
                            ),
                        )
                        record = _deserialize_record(payload, service=self._service, registry=self._registry)
                        self._cache[record.session_id] = record
                        return record, record.context.task_registry.get(updated_task.task_id)
        return None

    def persist(self, record: TerraFinHostedSessionRecord) -> TerraFinHostedSessionRecord:
        with self._lock:
            record.touch()
            return self._save_record(record)

    def delete(self, session_id: str) -> TerraFinHostedSessionRecord:
        with self._lock:
            record = self.get(session_id)
            with self._connect() as connection:
                connection.execute("DELETE FROM hosted_sessions WHERE session_id = ?", (session_id,))
            self._cache.pop(session_id, None)
            return record

    def cleanup_expired(self, *, session_ttl_seconds: int) -> tuple[TerraFinHostedSessionRecord, ...]:
        if session_ttl_seconds <= 0:
            return ()
        cutoff = _utc_now() - timedelta(seconds=session_ttl_seconds)
        removed: list[TerraFinHostedSessionRecord] = []
        with self._lock:
            for record in list(self.list()):
                if record.last_accessed_at >= cutoff:
                    continue
                if record.context.task_registry.has_active_tasks():
                    continue
                removed.append(self.delete(record.session_id))
        return tuple(removed)
