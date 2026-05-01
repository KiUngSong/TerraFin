import hashlib
import json
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from inspect import signature
from threading import Event, RLock, Thread
from typing import Any, Mapping
from uuid import uuid4

from .conversation_state import RUNTIME_MODEL_METADATA_KEY
from .definitions import (
    TerraFinAgentDefinition,
    TerraFinAgentDefinitionRegistry,
    build_default_agent_definition_registry,
    is_internal_agent_definition,
)
from .model_runtime import TerraFinRuntimeModel
from .runtime import (
    TerraFinAgentContext,
    TerraFinAgentSession,
    TerraFinCapability,
    TerraFinCapabilityRegistry,
    TerraFinTaskRecord,
    build_default_capability_registry,
    create_agent_context,
)
from .service import TerraFinAgentService
from .session_store import (
    HostedSessionStore,
    InMemoryHostedSessionStore,
    TerraFinHostedApprovalRequest,
    TerraFinHostedSessionRecord,
    TerraFinHostedViewContextRecord,
)
from .transcript_store import HostedTranscriptStore


class TerraFinAgentPolicyError(RuntimeError):
    """Raised when an agent definition attempts to exceed its allowed scope."""


class TerraFinAgentApprovalRequiredError(RuntimeError):
    """Raised when a hosted agent action requires a human approval checkpoint."""

    def __init__(self, approval: TerraFinHostedApprovalRequest) -> None:
        self.approval = approval
        super().__init__(approval.reason)


class TerraFinAgentSessionConflictError(RuntimeError):
    """Raised when a hosted session lifecycle action conflicts with active runtime state."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _AsyncTaskHandle:
    def __init__(self, session_id: str, task_id: str) -> None:
        self.session_id = session_id
        self.task_id = task_id
        self.cancel_event = Event()
        self.future: Future[None] | None = None


class TerraFinHostedAgentRuntime:
    def __init__(
        self,
        *,
        service: TerraFinAgentService | None = None,
        capability_registry: TerraFinCapabilityRegistry | None = None,
        agent_registry: TerraFinAgentDefinitionRegistry | None = None,
        chart_opener: Callable[..., dict[str, Any]] | None = None,
        session_store: HostedSessionStore | None = None,
        transcript_store: HostedTranscriptStore | None = None,
        session_ttl_seconds: int = 6 * 60 * 60,
        task_retention_seconds: int = 30 * 60,
        task_max_workers: int = 4,
        task_dispatch_poll_seconds: float = 0.25,
        task_lease_seconds: int = 30,
        default_require_human_approval_for_side_effects: bool = False,
        default_require_human_approval_for_background_tasks: bool = False,
        default_runtime_model: TerraFinRuntimeModel | None = None,
    ) -> None:
        self.service = service or TerraFinAgentService()
        self.capability_registry = capability_registry or build_default_capability_registry(
            self.service,
            chart_opener=chart_opener,
        )
        self.agent_registry = agent_registry or build_default_agent_definition_registry()
        self.session_store = session_store or InMemoryHostedSessionStore()
        self.transcript_store = transcript_store
        self.session_ttl_seconds = session_ttl_seconds
        self.task_retention_seconds = task_retention_seconds
        self.default_require_human_approval_for_side_effects = default_require_human_approval_for_side_effects
        self.default_require_human_approval_for_background_tasks = default_require_human_approval_for_background_tasks
        self.default_runtime_model = default_runtime_model
        self.task_dispatch_poll_seconds = max(task_dispatch_poll_seconds, 0.05)
        self.task_lease_seconds = max(task_lease_seconds, 1)
        self._worker_id = f"worker:{uuid4().hex}"
        self._task_executor = ThreadPoolExecutor(
            max_workers=max(task_max_workers, 1),
            thread_name_prefix="terrafin-agent-task",
        )
        self._task_max_workers = max(task_max_workers, 1)
        self._task_handles: dict[str, _AsyncTaskHandle] = {}
        self._task_index: dict[str, str] = {}
        self._task_lock = RLock()
        self._dispatcher_stop = Event()
        self._dispatcher_thread = Thread(
            target=self._dispatch_loop,
            name="terrafin-agent-dispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()

    def shutdown(self) -> None:
        self._dispatcher_stop.set()
        if self._dispatcher_thread.is_alive():
            self._dispatcher_thread.join(timeout=1.0)
        self._task_executor.shutdown(wait=False, cancel_futures=True)

    def list_agents(self) -> tuple[TerraFinAgentDefinition, ...]:
        self._cleanup_expired_state()
        return self.agent_registry.list()

    def list_sessions(self) -> tuple[TerraFinHostedSessionRecord, ...]:
        self._cleanup_expired_state()
        if self.transcript_store is None:
            return tuple(
                record for record in self.session_store.list() if not self._is_hidden_internal_session(record)
            )
        records: list[TerraFinHostedSessionRecord] = []
        for entry in self.transcript_store.list_sessions():
            try:
                record = self.session_store.get(entry.session_id)
            except KeyError:
                continue
            self._ensure_runtime_model_bound(record)
            self._sync_transcript_runtime_model(record)
            self._reconcile_orphaned_tasks(record)
            self._prune_terminal_tasks(record)
            if self._is_hidden_internal_session(record):
                continue
            records.append(record)
        return tuple(records)

    def get_agent_definition(self, agent_name: str) -> TerraFinAgentDefinition:
        return self.agent_registry.get(agent_name)

    def create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        allow_internal: bool = False,
    ) -> TerraFinAgentContext:
        self._cleanup_expired_state()
        definition = self.get_agent_definition(agent_name)
        if is_internal_agent_definition(definition) and not allow_internal:
            raise TerraFinAgentPolicyError(
                f"Agent definition '{agent_name}' is internal-only and cannot be created through the public runtime surface."
            )
        requested_metadata = dict(metadata or {})
        require_human_approval_for_side_effects = bool(
            requested_metadata.pop(
                "requireHumanApprovalForSideEffects",
                self.default_require_human_approval_for_side_effects,
            )
        )
        require_human_approval_for_background_tasks = bool(
            requested_metadata.pop(
                "requireHumanApprovalForBackgroundTasks",
                self.default_require_human_approval_for_background_tasks,
            )
        )
        if self.default_runtime_model is not None:
            requested_metadata.setdefault(
                RUNTIME_MODEL_METADATA_KEY,
                self.default_runtime_model.to_payload(),
            )
        session = TerraFinAgentSession(
            session_id=session_id or f"terrafin-session:{uuid4().hex}",
            metadata={
                **requested_metadata,
                "agentDefinition": definition.name,
                "agentPolicy": {
                    "defaultDepth": definition.default_depth,
                    "defaultView": definition.default_view,
                    "chartAccess": definition.chart_access,
                    "allowBackgroundTasks": definition.allow_background_tasks,
                    "requireHumanApprovalForSideEffects": require_human_approval_for_side_effects,
                    "requireHumanApprovalForBackgroundTasks": require_human_approval_for_background_tasks,
                },
            },
        )
        context = create_agent_context(
            service=self.service,
            registry=self.capability_registry,
            session=session,
            metadata=dict(session.metadata),
        )
        record = TerraFinHostedSessionRecord(
            session_id=session.session_id,
            agent_name=definition.name,
            context=context,
            metadata=dict(session.metadata),
        )
        self.session_store.create(record)
        if self.transcript_store is not None and not self.transcript_store.session_exists(session.session_id):
            self.transcript_store.create_session(
                session_id=session.session_id,
                agent_name=definition.name,
                created_at=record.created_at,
                runtime_model=session.metadata.get(RUNTIME_MODEL_METADATA_KEY),
            )
        return context

    def create_internal_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TerraFinAgentContext:
        resolved_metadata = {"hiddenInternal": True, **dict(metadata or {})}
        return self.create_session(
            agent_name,
            session_id=session_id,
            metadata=resolved_metadata,
            allow_internal=True,
        )

    def attach_conversation(self, session_id: str, conversation: Any) -> TerraFinHostedSessionRecord:
        return self.session_store.attach_conversation(session_id, conversation)

    def persist_session(self, session_id: str) -> TerraFinHostedSessionRecord:
        return self.session_store.persist(self.session_store.get(session_id))

    def get_session_record(self, session_id: str) -> TerraFinHostedSessionRecord:
        self._cleanup_expired_state()
        if self.transcript_store is not None and not self.transcript_store.session_exists(session_id):
            raise KeyError(session_id)
        record = self.session_store.touch(session_id)
        self._ensure_runtime_model_bound(record)
        self._sync_transcript_runtime_model(record)
        self._reconcile_orphaned_tasks(record)
        self._prune_terminal_tasks(record)
        self._hydrate_transient_conversation(record)
        return record

    def get_session(self, session_id: str) -> TerraFinAgentContext:
        return self.get_session_record(session_id).context

    def get_public_session_record(self, session_id: str) -> TerraFinHostedSessionRecord:
        record = self.get_session_record(session_id)
        if self._is_hidden_internal_session(record):
            raise KeyError(session_id)
        return record

    def get_session_definition(self, session_id: str) -> TerraFinAgentDefinition:
        record = self.get_session_record(session_id)
        return self.agent_registry.get(record.agent_name)

    def delete_session(self, session_id: str) -> TerraFinHostedSessionRecord:
        record = self.get_session_record(session_id)
        deleted_at = _utc_now()
        self._delete_hidden_child_sessions(parent_session_id=session_id, deleted_at=deleted_at)
        active_tasks = [
            task
            for task in record.context.task_registry.list_for_session(session_id)
            if task.status not in {"completed", "failed", "cancelled"}
        ]
        if active_tasks:
            raise TerraFinAgentSessionConflictError(
                f"Session '{session_id}' still has active background tasks. Cancel them before deleting the session."
            )
        self._drop_task_handles_for_session(session_id)
        if self.transcript_store is not None and self.transcript_store.session_exists(session_id):
            self.transcript_store.archive_session(session_id, deleted_at=deleted_at)
        removed = self.session_store.delete(session_id)
        removed.updated_at = deleted_at
        removed.last_accessed_at = deleted_at
        return removed

    def list_public_session_tasks(self, session_id: str) -> tuple[TerraFinTaskRecord, ...]:
        self.get_public_session_record(session_id)
        return self.list_session_tasks(session_id)

    def get_public_task(self, task_id: str) -> TerraFinTaskRecord:
        task = self.get_task(task_id)
        session_id = str(task.session_id or "").strip()
        if not session_id:
            raise KeyError(task_id)
        self.get_public_session_record(session_id)
        return task

    def cancel_public_task(self, task_id: str) -> TerraFinTaskRecord:
        task = self.get_public_task(task_id)
        return self.cancel_task(task.task_id)

    def list_public_session_approvals(self, session_id: str) -> tuple[TerraFinHostedApprovalRequest, ...]:
        self.get_public_session_record(session_id)
        return self.list_session_approvals(session_id)

    def get_public_approval(self, approval_id: str) -> TerraFinHostedApprovalRequest:
        approval = self.get_approval(approval_id)
        self.get_public_session_record(approval.session_id)
        return approval

    def approve_public_approval(
        self,
        approval_id: str,
        *,
        note: str | None = None,
    ) -> TerraFinHostedApprovalRequest:
        approval = self.get_public_approval(approval_id)
        return self.approve_approval(approval.approval_id, note=note)

    def deny_public_approval(
        self,
        approval_id: str,
        *,
        note: str | None = None,
    ) -> TerraFinHostedApprovalRequest:
        approval = self.get_public_approval(approval_id)
        return self.deny_approval(approval.approval_id, note=note)

    def _is_hidden_internal_session(self, record: TerraFinHostedSessionRecord) -> bool:
        return bool(record.context.session.metadata.get("hiddenInternal") or record.metadata.get("hiddenInternal"))

    def _delete_hidden_child_sessions(
        self,
        *,
        parent_session_id: str,
        deleted_at: datetime,
    ) -> None:
        child_session_ids = [
            record.session_id
            for record in self.session_store.list()
            if str(record.metadata.get("parentSessionId") or "").strip() == parent_session_id
        ]
        for child_session_id in child_session_ids:
            child_record = self.get_session_record(child_session_id)
            active_tasks = [
                task
                for task in child_record.context.task_registry.list_for_session(child_session_id)
                if task.status not in {"completed", "failed", "cancelled"}
            ]
            if active_tasks:
                raise TerraFinAgentSessionConflictError(
                    f"Hidden child session '{child_session_id}' still has active background tasks."
                )
            self._drop_task_handles_for_session(child_session_id)
            if self.transcript_store is not None and self.transcript_store.session_exists(child_session_id):
                self.transcript_store.archive_session(child_session_id, deleted_at=deleted_at)
            removed = self.session_store.delete(child_session_id)
            removed.updated_at = deleted_at
            removed.last_accessed_at = deleted_at

    def _ensure_runtime_model_bound(self, record: TerraFinHostedSessionRecord) -> None:
        if self.default_runtime_model is None:
            return
        runtime_model_payload = self.default_runtime_model.to_payload()
        changed = False

        if record.context.session.metadata.get(RUNTIME_MODEL_METADATA_KEY) != runtime_model_payload:
            record.context.session.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(runtime_model_payload)
            changed = True

        if record.metadata.get(RUNTIME_MODEL_METADATA_KEY) != runtime_model_payload:
            record.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(runtime_model_payload)
            changed = True

        if (
            record.conversation is not None
            and record.conversation.metadata.get(RUNTIME_MODEL_METADATA_KEY) != runtime_model_payload
        ):
            record.conversation.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(runtime_model_payload)
            changed = True

        if changed:
            self.session_store.persist(record)

    def _sync_transcript_runtime_model(self, record: TerraFinHostedSessionRecord) -> None:
        if self.transcript_store is None:
            return
        if not self.transcript_store.session_exists(record.session_id):
            return
        runtime_model_payload = record.context.session.metadata.get(RUNTIME_MODEL_METADATA_KEY)
        if not isinstance(runtime_model_payload, dict):
            return
        self.transcript_store.append_runtime_model(record.session_id, runtime_model_payload)

    def _hydrate_transient_conversation(self, record: TerraFinHostedSessionRecord) -> None:
        if self.transcript_store is None:
            return
        if record.conversation is not None:
            return
        if not self.transcript_store.session_exists(record.session_id):
            return
        payload = record.metadata.get("conversationState", {})
        metadata = dict(payload) if isinstance(payload, dict) else {}
        record.conversation = self.transcript_store.load_conversation(
            record.session_id,
            metadata=metadata,
        )

    def invoke(self, session_id: str, capability_name: str, /, **kwargs: Any) -> dict[str, Any]:
        record = self.get_session_record(session_id)
        definition = self.agent_registry.get(record.agent_name)
        capability = self.capability_registry.get(capability_name)
        resolved_kwargs = self._apply_defaults(
            definition,
            capability,
            kwargs,
            runtime_session_id=record.context.session.session_id,
        )
        self._enforce_policy(
            record=record,
            definition=definition,
            capability=capability,
            action="invoke",
            tool_name=capability.name,
            as_task=False,
            input_payload=resolved_kwargs,
        )
        payload = record.context.call(capability_name, **resolved_kwargs)
        self.session_store.persist(record)
        return payload

    def run_task(
        self,
        session_id: str,
        capability_name: str,
        /,
        *,
        description: str | None = None,
        **kwargs: Any,
    ) -> tuple[TerraFinTaskRecord, dict[str, Any]]:
        record = self.get_session_record(session_id)
        definition = self.agent_registry.get(record.agent_name)
        capability = self.capability_registry.get(capability_name)
        resolved_kwargs = self._apply_defaults(
            definition,
            capability,
            kwargs,
            runtime_session_id=record.context.session.session_id,
        )
        self._enforce_policy(
            record=record,
            definition=definition,
            capability=capability,
            action="task",
            tool_name=f"start_{capability.name}_task",
            as_task=True,
            input_payload=resolved_kwargs,
        )
        try:
            task, result = record.context.run_task(
                capability_name,
                description=description,
                **resolved_kwargs,
            )
        except Exception:
            self.session_store.persist(record)
            raise
        self._index_task(task.task_id, session_id)
        self.session_store.persist(record)
        return task, result

    def start_task(
        self,
        session_id: str,
        capability_name: str,
        /,
        *,
        description: str | None = None,
        **kwargs: Any,
    ) -> TerraFinTaskRecord:
        record = self.get_session_record(session_id)
        definition = self.agent_registry.get(record.agent_name)
        capability = self.capability_registry.get(capability_name)
        resolved_kwargs = self._apply_defaults(
            definition,
            capability,
            kwargs,
            runtime_session_id=record.context.session.session_id,
        )
        self._enforce_policy(
            record=record,
            definition=definition,
            capability=capability,
            action="task",
            tool_name=f"start_{capability.name}_task",
            as_task=True,
            input_payload=resolved_kwargs,
        )
        task = record.context.task_registry.create(
            capability_name,
            description=description or capability_name.replace("_", " "),
            session_id=session_id,
            input_payload=resolved_kwargs,
        )
        self._index_task(task.task_id, session_id)
        self.session_store.persist(record)
        return record.context.task_registry.get(task.task_id)

    def list_session_tasks(self, session_id: str) -> tuple[TerraFinTaskRecord, ...]:
        record = self.get_session_record(session_id)
        return record.context.task_registry.list_for_session(session_id)

    def get_task(self, task_id: str) -> TerraFinTaskRecord:
        session_id = self._session_id_for_task(task_id)
        return self.get_session_record(session_id).context.task_registry.get(task_id)

    def cancel_task(self, task_id: str) -> TerraFinTaskRecord:
        session_id = self._session_id_for_task(task_id)
        record = self.get_session_record(session_id)
        definition = self.agent_registry.get(record.agent_name)
        task = record.context.task_registry.get(task_id)
        capability = self.capability_registry.get(task.capability_name)
        self._record_policy_event(
            session_id=session_id,
            definition=definition,
            capability=capability,
            action="cancel_task",
            tool_name=None,
            outcome="allowed",
            reason="Task cancellation requested.",
        )
        if task.status in {"completed", "failed", "cancelled"}:
            return task

        with self._task_lock:
            handle = self._task_handles.get(task_id)

        if handle is None:
            cancelled_task = record.context.task_registry.cancel(task_id, reason="Task cancelled.")
            self.session_store.persist(record)
            return cancelled_task

        handle.cancel_event.set()
        cancelled = False
        if handle.future is not None:
            cancelled = handle.future.cancel()
        reason = "Task cancelled before execution." if cancelled else "Cancellation requested."
        cancelled_task = record.context.task_registry.cancel(task_id, reason=reason)
        self.session_store.persist(record)
        return cancelled_task

    def list_session_approvals(self, session_id: str) -> tuple[TerraFinHostedApprovalRequest, ...]:
        record = self.get_session_record(session_id)
        return tuple(record.approval_requests)

    def get_approval(self, approval_id: str) -> TerraFinHostedApprovalRequest:
        _, approval = self.session_store.find_approval(approval_id)
        return approval

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
        return self.session_store.upsert_view_context(
            context_id,
            route=route,
            page_type=page_type,
            title=title,
            summary=summary,
            selection=selection,
            entities=entities,
            metadata=metadata,
        )

    def get_view_context(self, context_id: str) -> TerraFinHostedViewContextRecord:
        return self.session_store.get_view_context(context_id)

    def relink_session_view_context(self, session_id: str, view_context_id: str) -> None:
        """Update the session's linked viewContextId.

        A hosted session records the viewContextId it was created with, but a
        long-lived session can outlive a single browser sessionStorage (new
        tab, cleared storage, …). Callers — chiefly the message-submit path —
        refresh the link on every request so `current_view_context` always
        reads what the user is looking at *now*, not the snapshot from
        session-creation time.

        The mutation MUST be persisted through the session store — in-memory
        mutation alone is invisible to SQLite-backed stores across workers /
        processes that share only the DB, not the cache. `session_store.persist`
        serializes the updated record back to disk.
        """
        if not view_context_id:
            return
        record = self.get_session_record(session_id)
        previous = record.context.session.metadata.get("viewContextId")
        if previous == view_context_id:
            return
        record.context.session.metadata["viewContextId"] = view_context_id
        record.metadata["viewContextId"] = view_context_id
        self.session_store.persist(record)

    def read_linked_view_context(
        self,
        session_id: str,
        *,
        view_context_id: str | None = None,
    ) -> dict[str, Any]:
        record = self.get_session_record(session_id)
        linked_context_id = view_context_id or record.context.session.metadata.get("viewContextId")
        if not linked_context_id:
            return {
                "available": False,
                "linked": False,
                "reason": "No current view context is linked to this hosted session.",
            }
        try:
            context = self.get_view_context(str(linked_context_id))
        except KeyError:
            return {
                "available": False,
                "linked": view_context_id is None,
                "contextId": str(linked_context_id),
                "reason": "The linked current view context is unavailable or has not been published yet.",
            }
        return {
            "available": True,
            "linked": view_context_id is None,
            "contextId": context.context_id,
            "createdAt": context.created_at.isoformat(),
            "updatedAt": context.updated_at.isoformat(),
            "route": context.route,
            "pageType": context.page_type,
            "title": context.title,
            "summary": context.summary,
            "selection": dict(context.selection),
            "entities": [dict(entity) for entity in context.entities],
            "metadata": dict(context.metadata),
        }

    def approve_approval(
        self,
        approval_id: str,
        *,
        note: str | None = None,
    ) -> TerraFinHostedApprovalRequest:
        record, approval = self.session_store.find_approval(approval_id)
        updated = self.session_store.update_approval(approval_id, status="approved", decision_note=note)
        definition = self.agent_registry.get(record.agent_name)
        capability = self.capability_registry.get(approval.capability_name)
        self._record_policy_event(
            session_id=record.session_id,
            definition=definition,
            capability=capability,
            action="approve",
            tool_name=approval.tool_name,
            outcome="allowed",
            reason=note or "Human approval granted.",
            metadata={"approvalId": approval_id},
        )
        return updated

    def deny_approval(
        self,
        approval_id: str,
        *,
        note: str | None = None,
    ) -> TerraFinHostedApprovalRequest:
        record, approval = self.session_store.find_approval(approval_id)
        updated = self.session_store.update_approval(approval_id, status="denied", decision_note=note)
        definition = self.agent_registry.get(record.agent_name)
        capability = self.capability_registry.get(approval.capability_name)
        self._record_policy_event(
            session_id=record.session_id,
            definition=definition,
            capability=capability,
            action="deny",
            tool_name=approval.tool_name,
            outcome="denied",
            reason=note or "Human approval denied.",
            metadata={"approvalId": approval_id},
        )
        return updated

    def _execute_async_task(
        self,
        session_id: str,
        task_id: str,
        capability_name: str,
        cancel_event: Event,
    ) -> None:
        try:
            record = self.get_session_record(session_id)
        except KeyError:
            self._drop_task_handle(task_id)
            return

        if cancel_event.is_set():
            record.context.task_registry.cancel(task_id, reason="Task cancelled before execution.")
            self.session_store.persist(record)
            self._drop_task_handle(task_id)
            return

        task = record.context.task_registry.get(task_id)
        kwargs = dict(task.input_payload)
        try:
            result = record.context.call(capability_name, **kwargs)
        except Exception as exc:
            if cancel_event.is_set():
                record.context.task_registry.cancel(task_id, reason="Cancellation requested.")
            else:
                record.context.task_registry.fail(task_id, error=str(exc))
            self.session_store.persist(record)
            self._drop_task_handle(task_id)
            return

        if cancel_event.is_set():
            record.context.task_registry.cancel(task_id, reason="Cancellation requested.")
            self.session_store.persist(record)
            self._drop_task_handle(task_id)
            return
        latest_task = self.session_store.get(session_id).context.task_registry.get(task_id)
        if latest_task.status == "cancelled":
            record.context.task_registry.cancel(task_id, reason=latest_task.error or "Cancellation requested.")
            self.session_store.persist(record)
            self._drop_task_handle(task_id)
            return
        record.context.task_registry.complete(task_id, result=result, progress={"state": "completed"})
        self.session_store.persist(record)
        self._drop_task_handle(task_id)

    def _enforce_policy(
        self,
        *,
        record: TerraFinHostedSessionRecord,
        definition: TerraFinAgentDefinition,
        capability: TerraFinCapability,
        action: str,
        tool_name: str | None,
        as_task: bool,
        input_payload: Mapping[str, Any],
    ) -> None:
        if not definition.allows(capability.name):
            reason = f"Agent '{definition.name}' cannot use capability '{capability.name}'."
            self._record_policy_event(
                session_id=record.session_id,
                definition=definition,
                capability=capability,
                action=action,
                tool_name=tool_name,
                outcome="denied",
                reason=reason,
            )
            raise TerraFinAgentPolicyError(reason)
        if capability.name == "open_chart" and not definition.chart_access:
            reason = f"Agent '{definition.name}' does not allow chart session access."
            self._record_policy_event(
                session_id=record.session_id,
                definition=definition,
                capability=capability,
                action=action,
                tool_name=tool_name,
                outcome="denied",
                reason=reason,
            )
            raise TerraFinAgentPolicyError(reason)
        if as_task and not definition.allow_background_tasks:
            reason = f"Agent '{definition.name}' does not allow background task execution."
            self._record_policy_event(
                session_id=record.session_id,
                definition=definition,
                capability=capability,
                action=action,
                tool_name=tool_name,
                outcome="denied",
                reason=reason,
            )
            raise TerraFinAgentPolicyError(reason)
        if as_task and not capability.backgroundable:
            reason = f"Capability '{capability.name}' is not marked as backgroundable."
            self._record_policy_event(
                session_id=record.session_id,
                definition=definition,
                capability=capability,
                action=action,
                tool_name=tool_name,
                outcome="denied",
                reason=reason,
            )
            raise TerraFinAgentPolicyError(reason)

        pending_approval, allowed_reason, approval_metadata = self._resolve_human_approval(
            record=record,
            definition=definition,
            capability=capability,
            action=action,
            tool_name=tool_name,
            as_task=as_task,
            input_payload=input_payload,
        )
        if pending_approval is not None:
            self._record_policy_event(
                session_id=record.session_id,
                definition=definition,
                capability=capability,
                action=action,
                tool_name=tool_name,
                outcome="pending",
                reason=pending_approval.reason,
                metadata=approval_metadata,
            )
            raise TerraFinAgentApprovalRequiredError(pending_approval)

        self._record_policy_event(
            session_id=record.session_id,
            definition=definition,
            capability=capability,
            action=action,
            tool_name=tool_name,
            outcome="allowed",
            reason=allowed_reason or "Allowed by hosted agent policy.",
            metadata=approval_metadata,
        )

    def _resolve_human_approval(
        self,
        *,
        record: TerraFinHostedSessionRecord,
        definition: TerraFinAgentDefinition,
        capability: TerraFinCapability,
        action: str,
        tool_name: str | None,
        as_task: bool,
        input_payload: Mapping[str, Any],
    ) -> tuple[TerraFinHostedApprovalRequest | None, str | None, dict[str, Any]]:
        policy = dict(record.context.session.metadata.get("agentPolicy", {}))
        requires_approval = False
        if capability.side_effecting and bool(policy.get("requireHumanApprovalForSideEffects", False)):
            requires_approval = True
        if as_task and bool(policy.get("requireHumanApprovalForBackgroundTasks", False)):
            requires_approval = True
        if not requires_approval:
            return None, None, {}

        fingerprint = self._approval_fingerprint(
            action=action,
            capability_name=capability.name,
            tool_name=tool_name,
            input_payload=input_payload,
        )
        matching = [
            approval
            for approval in record.approval_requests
            if approval.action == action
            and approval.capability_name == capability.name
            and approval.tool_name == tool_name
            and approval.fingerprint == fingerprint
        ]
        for approval in reversed(matching):
            if approval.status == "approved":
                consumed = self.session_store.update_approval(
                    approval.approval_id,
                    status="consumed",
                    metadata={"consumedAt": _utc_now().isoformat()},
                )
                return (
                    None,
                    f"Allowed by approval request '{consumed.approval_id}'.",
                    {"approvalId": consumed.approval_id},
                )
            if approval.status == "pending":
                return approval, None, {"approvalId": approval.approval_id}

        reason = (
            f"Human approval is required before '{tool_name or capability.name}' can run for "
            f"hosted session '{record.session_id}'."
        )
        approval = self.session_store.create_approval(
            record.session_id,
            agent_name=definition.name,
            action="task" if as_task else "invoke",
            capability_name=capability.name,
            tool_name=tool_name,
            side_effecting=capability.side_effecting or as_task,
            reason=reason,
            fingerprint=fingerprint,
            input_payload=dict(input_payload),
        )
        return approval, None, {"approvalId": approval.approval_id}

    def _record_policy_event(
        self,
        *,
        session_id: str,
        definition: TerraFinAgentDefinition,
        capability: TerraFinCapability | None,
        action: str,
        tool_name: str | None,
        outcome: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.session_store.append_audit(
            session_id,
            agent_name=definition.name,
            action=action,  # type: ignore[arg-type]
            capability_name=None if capability is None else capability.name,
            tool_name=tool_name,
            side_effecting=False if capability is None else capability.side_effecting,
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
            metadata=metadata,
        )

    def _apply_defaults(
        self,
        definition: TerraFinAgentDefinition,
        capability: TerraFinCapability,
        provided: Mapping[str, Any],
        *,
        runtime_session_id: str,
    ) -> dict[str, Any]:
        resolved = dict(provided)
        parameters = signature(capability.handler).parameters

        if "depth" in parameters and resolved.get("depth") is None:
            resolved["depth"] = definition.default_depth
        if "view" in parameters and resolved.get("view") is None:
            resolved["view"] = definition.default_view
        # Auto-inject the runtime's session_id when the handler accepts one.
        # `open_chart` binds its chart session to the assistant session;
        # `macro_focus` uses it to pick up session-local named series so the
        # agent reads the same macro frame the user loaded on the chart.
        if "session_id" in parameters and resolved.get("session_id") is None:
            resolved["session_id"] = runtime_session_id
        return resolved

    def _approval_fingerprint(
        self,
        *,
        action: str,
        capability_name: str,
        tool_name: str | None,
        input_payload: Mapping[str, Any],
    ) -> str:
        serialized = json.dumps(
            {
                "action": action,
                "capabilityName": capability_name,
                "toolName": tool_name,
                "inputPayload": dict(input_payload),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _session_id_for_task(self, task_id: str) -> str:
        with self._task_lock:
            session_id = self._task_index.get(task_id)
        if session_id is not None:
            return session_id
        for record in self.session_store.list():
            for task in record.context.task_registry.list_for_session(record.session_id):
                self._index_task(task.task_id, record.session_id)
            with self._task_lock:
                session_id = self._task_index.get(task_id)
            if session_id is not None:
                return session_id
        raise KeyError(f"Unknown TerraFin hosted task: {task_id}")

    def _index_task(self, task_id: str, session_id: str) -> None:
        with self._task_lock:
            self._task_index[task_id] = session_id

    def _drop_task_handle(self, task_id: str) -> None:
        with self._task_lock:
            self._task_handles.pop(task_id, None)
            self._task_index.pop(task_id, None)

    def _drop_task_handles_for_session(self, session_id: str) -> None:
        with self._task_lock:
            task_ids = [
                task_id for task_id, indexed_session_id in self._task_index.items() if indexed_session_id == session_id
            ]
            for task_id in task_ids:
                self._task_handles.pop(task_id, None)
                self._task_index.pop(task_id, None)

    def _active_task_count(self) -> int:
        with self._task_lock:
            return sum(
                1 for handle in self._task_handles.values() if handle.future is not None and not handle.future.done()
            )

    def _launch_claimed_task(self, session_id: str, task: TerraFinTaskRecord) -> None:
        handle = _AsyncTaskHandle(session_id=session_id, task_id=task.task_id)
        with self._task_lock:
            existing = self._task_handles.get(task.task_id)
            if existing is not None and existing.future is not None and not existing.future.done():
                return
            self._task_handles[task.task_id] = handle
        future = self._task_executor.submit(
            self._execute_async_task,
            session_id,
            task.task_id,
            task.capability_name,
            handle.cancel_event,
        )
        handle.future = future

    def _dispatch_loop(self) -> None:
        while not self._dispatcher_stop.is_set():
            try:
                self._cleanup_expired_state()
                if self._active_task_count() >= self._task_max_workers:
                    self._dispatcher_stop.wait(self.task_dispatch_poll_seconds)
                    continue
                claimed = self.session_store.claim_pending_task(
                    worker_id=self._worker_id,
                    lease_seconds=self.task_lease_seconds,
                )
                if claimed is None:
                    self._dispatcher_stop.wait(self.task_dispatch_poll_seconds)
                    continue
                record, task = claimed
                self._index_task(task.task_id, record.session_id)
                self._launch_claimed_task(record.session_id, task)
            except Exception:
                self._dispatcher_stop.wait(min(self.task_dispatch_poll_seconds * 2, 1.0))

    def _reconcile_orphaned_tasks(self, record: TerraFinHostedSessionRecord) -> None:
        for task in record.context.task_registry.list_for_session(record.session_id):
            self._index_task(task.task_id, record.session_id)

    def _prune_terminal_tasks(self, record: TerraFinHostedSessionRecord) -> None:
        if self.task_retention_seconds <= 0:
            return
        cutoff = _utc_now() - timedelta(seconds=self.task_retention_seconds)
        removed = record.context.task_registry.prune_terminal(completed_before=cutoff)
        if not removed:
            return
        for task in removed:
            self._drop_task_handle(task.task_id)
        self.session_store.persist(record)

    def _cleanup_expired_state(self) -> None:
        removed_sessions = self.session_store.cleanup_expired(session_ttl_seconds=self.session_ttl_seconds)
        for record in removed_sessions:
            self._drop_task_handles_for_session(record.session_id)
