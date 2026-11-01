"""Task record + thread-safe registry for backgroundable capabilities.

Note: this module is `agent.runtime.tasks` and is distinct from
`agent.tasks` (which holds high-level helpers like `open_chart`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from .artifacts import _utc_now


if TYPE_CHECKING:
    from ..storage.session_store import HostedSessionStore


TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

# A task whose lease has expired this many times is failed instead of re-claimed.
TASK_MAX_ATTEMPTS = 3


def _is_terminal_task_status(status: TaskStatus) -> bool:
    return status in {"completed", "failed", "cancelled"}


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
    origin_tool_call_id: str | None = None


def task_lease_expired(task: TerraFinTaskRecord, *, now: datetime) -> bool:
    return task.status == "running" and task.lease_expires_at is not None and task.lease_expires_at <= now


def task_restart_limit_reached(task: TerraFinTaskRecord, *, now: datetime) -> bool:
    return task_lease_expired(task, now=now) and task.attempt_count >= TASK_MAX_ATTEMPTS


class TerraFinTaskContext:
    """A background handler's view of its own task, injected as `task`."""

    def __init__(
        self,
        *,
        task_id: str,
        session_id: str,
        heartbeat: Callable[[str | None], None],
        cancel_event: Event,
        store: "HostedSessionStore",
        call: Callable[..., dict[str, Any]],
        turn_runner: Callable[[], Callable[..., Any] | None],
    ) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self._heartbeat = heartbeat
        self._cancel_event = cancel_event
        self._store = store
        self._call = call
        self._turn_runner = turn_runner

    @property
    def model_turn(self) -> Callable[..., Any] | None:
        """The hosted loop's `complete_model_turn`, or None while no loop is bound."""
        return self._turn_runner()

    def heartbeat(self, stage: str | None = None) -> None:
        """Renews the lease, and sets `progress.stage` when `stage` is given."""
        self._heartbeat(stage)

    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def load_checkpoint(self) -> dict[str, Any] | None:
        return self._store.load_task_checkpoint(self.session_id, self.task_id)

    def save_checkpoint(self, payload: Mapping[str, Any]) -> None:
        self._store.save_task_checkpoint(self.session_id, self.task_id, payload=dict(payload))

    def call(self, capability_name: str, /, **kwargs: Any) -> dict[str, Any]:
        return self._call(capability_name, **kwargs)


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
        origin_tool_call_id: str | None = None,
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
                origin_tool_call_id=origin_tool_call_id,
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

    def record_progress(
        self,
        task_id: str,
        *,
        progress: Mapping[str, Any] | None = None,
        lease_expires_at: datetime | None = None,
    ) -> TerraFinTaskRecord:
        """Heartbeat a running task mid-execution.

        Unlike `mark_running`, this keeps `started_at`, so elapsed time is not
        reset on every tick, and renews the lease when `lease_expires_at` is
        given, so another worker does not re-claim a task still making progress.
        """
        with self._lock:
            previous = self._tasks[task_id]
            if _is_terminal_task_status(previous.status):
                return previous
            record = replace(
                previous,
                status="running",
                started_at=previous.started_at or _utc_now(),
                progress=dict(progress or previous.progress),
                worker_id=previous.worker_id,
                lease_expires_at=lease_expires_at if lease_expires_at is not None else previous.lease_expires_at,
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
