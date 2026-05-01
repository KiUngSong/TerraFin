import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Iterator, Literal, Mapping
from uuid import uuid4

from .conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    deserialize_message_blocks,
    ensure_message_blocks,
    is_internal_only_message,
    serialize_message_blocks,
)
from .conversation_state import RUNTIME_MODEL_METADATA_KEY


TRANSCRIPT_STORE_VERSION = 3
TranscriptEventType = Literal[
    "session_header",
    "message",
    "runtime_model",
    "custom_title",
    "compact_boundary",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _message_preview(content: str, *, limit: int = 96) -> str:
    compact = " ".join(str(content).split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


@dataclass(frozen=True, slots=True)
class HostedTranscriptEvent:
    event_id: str
    session_id: str
    event_type: TranscriptEventType
    created_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HostedSessionIndexEntry:
    session_id: str
    agent_name: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    title: str | None = None
    last_message_preview: str | None = None
    message_count: int = 0
    runtime_model: dict[str, Any] | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HostedTranscriptSummary:
    session_id: str
    title: str | None
    last_message_preview: str | None
    last_message_at: datetime | None
    message_count: int
    runtime_model: dict[str, Any] | None


class HostedTranscriptLock:
    def __init__(self) -> None:
        self._global_lock = Lock()
        self._session_locks: dict[str, RLock] = {}
        self._index_lock = RLock()

    def _session_lock(self, session_id: str) -> RLock:
        with self._global_lock:
            return self._session_locks.setdefault(session_id, RLock())

    @contextmanager
    def session(self, session_id: str) -> Iterator[None]:
        lock = self._session_lock(session_id)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def index(self) -> Iterator[None]:
        self._index_lock.acquire()
        try:
            yield
        finally:
            self._index_lock.release()


class HostedTranscriptReader:
    def __init__(self, store: "HostedTranscriptStore") -> None:
        self.store = store

    def load_conversation(
        self,
        session_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> TerraFinHostedConversation:
        entry = self.store.get_session_index(session_id)
        events = self.store.load_events(session_id)
        created_at = entry.created_at
        agent_name = entry.agent_name
        conversation = TerraFinHostedConversation(
            session_id=session_id,
            agent_name=agent_name,
            created_at=created_at,
            metadata=dict(metadata or {}),
        )
        if entry.runtime_model is not None:
            conversation.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(entry.runtime_model)
        for event in events:
            if event.event_type == "runtime_model":
                conversation.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(event.payload)
                continue
            if event.event_type != "message":
                continue
            conversation.messages.append(
                ensure_message_blocks(
                    TerraFinConversationMessage(
                        role=str(event.payload.get("role")),
                        content=str(event.payload.get("content") or ""),
                        created_at=event.created_at,
                        name=event.payload.get("name"),
                        tool_call_id=event.payload.get("toolCallId"),
                        metadata=dict(event.payload.get("metadata", {})),
                        blocks=deserialize_message_blocks(event.payload.get("blocks")),
                    )
                )
            )
        return conversation

    def build_summary(self, session_id: str) -> HostedTranscriptSummary:
        entry = self.store.get_session_index(session_id)
        return HostedTranscriptSummary(
            session_id=entry.session_id,
            title=entry.title,
            last_message_preview=entry.last_message_preview,
            last_message_at=entry.last_message_at,
            message_count=entry.message_count,
            runtime_model=None if entry.runtime_model is None else dict(entry.runtime_model),
        )


class HostedTranscriptStore:
    def __init__(self, *, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.root_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.sessions_dir / "sessions.json"
        self.lock = HostedTranscriptLock()
        self.reader = HostedTranscriptReader(self)
        self._initialize_index()

    def _initialize_index(self) -> None:
        with self.lock.index():
            if not self.index_path.exists():
                self._save_index_unlocked({})
                return
            try:
                payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                self._reset_index_unlocked()
                return
            if not isinstance(payload, dict) or int(payload.get("version", 0)) != TRANSCRIPT_STORE_VERSION:
                self._reset_index_unlocked()

    def _reset_index_unlocked(self) -> None:
        if self.index_path.exists():
            archived = self.index_path.with_name(
                f"{self.index_path.stem}.legacy.{_utc_now().strftime('%Y%m%d%H%M%S')}{self.index_path.suffix}"
            )
            self.index_path.replace(archived)
        self._save_index_unlocked({})

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def _archive_path(self, session_id: str, deleted_at: datetime) -> Path:
        suffix = deleted_at.strftime("%Y%m%d%H%M%S")
        return self.sessions_dir / f"{session_id}.deleted.{suffix}.jsonl"

    def _load_index_unlocked(self) -> dict[str, HostedSessionIndexEntry]:
        if not self.index_path.exists():
            return {}
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        sessions = payload.get("sessions", {})
        if not isinstance(sessions, dict):
            return {}
        entries: dict[str, HostedSessionIndexEntry] = {}
        for session_id, raw in sessions.items():
            if not isinstance(raw, dict):
                continue
            entries[str(session_id)] = HostedSessionIndexEntry(
                session_id=str(raw["sessionId"]),
                agent_name=str(raw["agentName"]),
                created_at=_parse_datetime(raw.get("createdAt")) or _utc_now(),
                updated_at=_parse_datetime(raw.get("updatedAt")) or _utc_now(),
                last_message_at=_parse_datetime(raw.get("lastMessageAt")),
                title=raw.get("title"),
                last_message_preview=raw.get("lastMessagePreview"),
                message_count=int(raw.get("messageCount", 0)),
                runtime_model=None if raw.get("runtimeModel") is None else dict(raw.get("runtimeModel", {})),
                deleted_at=_parse_datetime(raw.get("deletedAt")),
            )
        return entries

    def _save_index_unlocked(self, entries: Mapping[str, HostedSessionIndexEntry]) -> None:
        payload = {
            "version": TRANSCRIPT_STORE_VERSION,
            "sessions": {
                session_id: {
                    "sessionId": entry.session_id,
                    "agentName": entry.agent_name,
                    "createdAt": entry.created_at.isoformat(),
                    "updatedAt": entry.updated_at.isoformat(),
                    "lastMessageAt": _isoformat(entry.last_message_at),
                    "title": entry.title,
                    "lastMessagePreview": entry.last_message_preview,
                    "messageCount": entry.message_count,
                    "runtimeModel": None if entry.runtime_model is None else dict(entry.runtime_model),
                    "deletedAt": _isoformat(entry.deleted_at),
                }
                for session_id, entry in entries.items()
            },
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        temp_path = self.index_path.with_suffix(".tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(self.index_path)

    def _append_event_unlocked(self, session_id: str, event: HostedTranscriptEvent) -> None:
        path = self._session_path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "eventId": event.event_id,
                        "sessionId": event.session_id,
                        "type": event.event_type,
                        "createdAt": event.created_at.isoformat(),
                        "payload": event.payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")

    def _read_events_unlocked(self, session_id: str) -> tuple[HostedTranscriptEvent, ...]:
        path = self._session_path(session_id)
        if not path.exists():
            raise KeyError(session_id)
        events: list[HostedTranscriptEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                events.append(
                    HostedTranscriptEvent(
                        event_id=str(payload.get("eventId") or f"event:{uuid4().hex}"),
                        session_id=str(payload.get("sessionId") or session_id),
                        event_type=str(payload.get("type") or "message"),
                        created_at=_parse_datetime(payload.get("createdAt")) or _utc_now(),
                        payload=dict(payload.get("payload", {})),
                    )
                )
        return tuple(events)

    def session_exists(self, session_id: str) -> bool:
        try:
            entry = self.get_session_index(session_id)
        except KeyError:
            return False
        return entry.deleted_at is None

    def create_session(
        self,
        *,
        session_id: str,
        agent_name: str,
        created_at: datetime,
        runtime_model: dict[str, Any] | None = None,
        system_message: TerraFinConversationMessage | None = None,
    ) -> HostedSessionIndexEntry:
        with self.lock.session(session_id):
            with self.lock.index():
                index = self._load_index_unlocked()
                if session_id in index and index[session_id].deleted_at is None:
                    raise ValueError(f"Transcript session already exists: {session_id}")
                events = [
                    HostedTranscriptEvent(
                        event_id=f"event:{uuid4().hex}",
                        session_id=session_id,
                        event_type="session_header",
                        created_at=created_at,
                        payload={"agentName": agent_name},
                    )
                ]
                if runtime_model is not None:
                    events.append(
                        HostedTranscriptEvent(
                            event_id=f"event:{uuid4().hex}",
                            session_id=session_id,
                            event_type="runtime_model",
                            created_at=created_at,
                            payload=dict(runtime_model),
                        )
                    )
                if system_message is not None:
                    events.append(
                        HostedTranscriptEvent(
                            event_id=f"event:{uuid4().hex}",
                            session_id=session_id,
                            event_type="message",
                            created_at=system_message.created_at,
                            payload={
                                "role": system_message.role,
                                "content": system_message.content,
                                "name": system_message.name,
                                "toolCallId": system_message.tool_call_id,
                                "metadata": dict(system_message.metadata),
                                "blocks": serialize_message_blocks(system_message.blocks),
                            },
                        )
                    )
                path = self._session_path(session_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
                for event in events:
                    self._append_event_unlocked(session_id, event)
                entry = HostedSessionIndexEntry(
                    session_id=session_id,
                    agent_name=agent_name,
                    created_at=created_at,
                    updated_at=system_message.created_at if system_message is not None else created_at,
                    runtime_model=None if runtime_model is None else dict(runtime_model),
                )
                index[session_id] = entry
                self._save_index_unlocked(index)
                return entry

    def append_message(
        self,
        session_id: str,
        message: TerraFinConversationMessage,
    ) -> HostedTranscriptEvent:
        message = ensure_message_blocks(message)
        with self.lock.session(session_id):
            event = HostedTranscriptEvent(
                event_id=f"event:{uuid4().hex}",
                session_id=session_id,
                event_type="message",
                created_at=message.created_at,
                payload={
                    "role": message.role,
                    "content": message.content,
                    "name": message.name,
                    "toolCallId": message.tool_call_id,
                    "metadata": dict(message.metadata),
                    "blocks": serialize_message_blocks(message.blocks),
                },
            )
            self._append_event_unlocked(session_id, event)
            with self.lock.index():
                index = self._load_index_unlocked()
                entry = index[session_id]
                updated = replace(
                    entry,
                    updated_at=message.created_at,
                )
                if message.role in {"user", "assistant"} and not is_internal_only_message(message):
                    updated = replace(
                        updated,
                        last_message_at=message.created_at,
                        last_message_preview=_message_preview(message.content),
                        message_count=entry.message_count + 1,
                    )
                    if message.role == "user" and not entry.title:
                        updated = replace(
                            updated,
                            title=_message_preview(message.content, limit=72),
                        )
                index[session_id] = updated
                self._save_index_unlocked(index)
            return event

    def append_runtime_model(
        self,
        session_id: str,
        runtime_model: Mapping[str, Any],
        *,
        created_at: datetime | None = None,
    ) -> HostedSessionIndexEntry:
        normalized = dict(runtime_model)
        timestamp = created_at or _utc_now()
        with self.lock.session(session_id):
            with self.lock.index():
                index = self._load_index_unlocked()
                entry = index[session_id]
                if entry.runtime_model == normalized:
                    return entry
                event = HostedTranscriptEvent(
                    event_id=f"event:{uuid4().hex}",
                    session_id=session_id,
                    event_type="runtime_model",
                    created_at=timestamp,
                    payload=normalized,
                )
                self._append_event_unlocked(session_id, event)
                updated = replace(entry, updated_at=timestamp, runtime_model=normalized)
                index[session_id] = updated
                self._save_index_unlocked(index)
                return updated

    def append_custom_title(
        self,
        session_id: str,
        title: str,
        *,
        created_at: datetime | None = None,
    ) -> HostedSessionIndexEntry:
        normalized_title = str(title or "").strip()
        timestamp = created_at or _utc_now()
        with self.lock.session(session_id):
            with self.lock.index():
                index = self._load_index_unlocked()
                entry = index[session_id]
                event = HostedTranscriptEvent(
                    event_id=f"event:{uuid4().hex}",
                    session_id=session_id,
                    event_type="custom_title",
                    created_at=timestamp,
                    payload={"title": normalized_title},
                )
                self._append_event_unlocked(session_id, event)
                updated = replace(entry, updated_at=timestamp, title=normalized_title or None)
                index[session_id] = updated
                self._save_index_unlocked(index)
                return updated

    def load_events(self, session_id: str) -> tuple[HostedTranscriptEvent, ...]:
        with self.lock.session(session_id):
            return self._read_events_unlocked(session_id)

    def get_session_index(self, session_id: str) -> HostedSessionIndexEntry:
        with self.lock.index():
            index = self._load_index_unlocked()
            if session_id not in index:
                raise KeyError(session_id)
            return index[session_id]

    def list_sessions(self, *, include_deleted: bool = False) -> tuple[HostedSessionIndexEntry, ...]:
        with self.lock.index():
            index = self._load_index_unlocked()
            items = [entry for entry in index.values() if include_deleted or entry.deleted_at is None]
            items.sort(key=lambda item: item.updated_at, reverse=True)
            return tuple(items)

    def load_conversation(
        self,
        session_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> TerraFinHostedConversation:
        return self.reader.load_conversation(session_id, metadata=metadata)

    def build_summary(self, session_id: str) -> HostedTranscriptSummary:
        return self.reader.build_summary(session_id)

    def archive_session(self, session_id: str, *, deleted_at: datetime | None = None) -> HostedSessionIndexEntry:
        timestamp = deleted_at or _utc_now()
        with self.lock.session(session_id):
            with self.lock.index():
                index = self._load_index_unlocked()
                entry = index[session_id]
                session_path = self._session_path(session_id)
                if session_path.exists():
                    session_path.replace(self._archive_path(session_id, timestamp))
                updated = replace(entry, updated_at=timestamp, deleted_at=timestamp)
                index[session_id] = updated
                self._save_index_unlocked(index)
                return updated

    def rewrite_session_messages(
        self,
        session_id: str,
        *,
        replacements: Mapping[str, dict[str, Any]],
    ) -> bool:
        if not replacements:
            return False
        with self.lock.session(session_id):
            events = list(self._read_events_unlocked(session_id))
            changed = False
            for index, event in enumerate(events):
                replacement = replacements.get(event.event_id)
                if replacement is None or event.event_type != "message":
                    continue
                events[index] = replace(event, payload=dict(replacement))
                changed = True
            if not changed:
                return False
            temp_path = self._session_path(session_id).with_suffix(".rewrite.tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(
                        json.dumps(
                            {
                                "eventId": event.event_id,
                                "sessionId": event.session_id,
                                "type": event.event_type,
                                "createdAt": event.created_at.isoformat(),
                                "payload": event.payload,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    handle.write("\n")
            temp_path.replace(self._session_path(session_id))
            return True
