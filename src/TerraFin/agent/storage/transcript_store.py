import fcntl
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Iterator, Literal, Mapping
from uuid import uuid4

from ..contracts.conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    deserialize_message_blocks,
    ensure_message_blocks,
    is_internal_only_message,
    serialize_message_blocks,
)
from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY


_logger = logging.getLogger(__name__)

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
    def __init__(self, *, index_lock_path: Path | None = None) -> None:
        self._global_lock = Lock()
        self._session_locks: dict[str, RLock] = {}
        self._index_lock = RLock()
        # The index is a whole-file read-modify-write and an RLock covers one
        # process. Two writers is this store's normal deployment, and a lost
        # update there silently reverts the other's `updated_at`.
        self._index_lock_path = index_lock_path
        self._index_depth = 0
        self._warned_unlocked = False

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

    def _acquire_index_file(self) -> int | None:
        """Blocking LOCK_EX on the index, or None if locking is unavailable.

        Fails open, as `agent/runtime/inflight.py` does: a read-only mount must not
        take the store down. Writers only — serialising readers measured 2.2x worse
        than no cross-process lock at all, and they do not need it, since
        `replace()` is atomic.
        """
        if self._index_lock_path is None:
            # Same symptom as a failed flock, and previously the only silent one:
            # no lock means every write nulls the snapshot, and a lock-free reader
            # then pays a full re-parse.
            self._warn_unlocked(OSError("no index lock path configured"))
            return None
        try:
            handle = os.open(self._index_lock_path, os.O_RDONLY | os.O_CREAT, 0o644)
        except OSError as exc:
            self._warn_unlocked(exc)
            return None
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError as exc:
            os.close(handle)
            self._warn_unlocked(exc)
            return None
        return handle

    def _warn_unlocked(self, exc: OSError) -> None:
        """Say so once. The fail-open is deliberate; its cost is not obvious.

        Without the lock every write discards the index cache, and since readers are
        lock-free that cache is all that stands between a GET and a full re-parse.
        """
        if self._warned_unlocked:
            return
        self._warned_unlocked = True
        _logger.warning(
            "transcript index lock unavailable at %s (%s); index writes will run "
            "unserialised across processes and will not cache",
            self._index_lock_path,
            exc,
        )

    @contextmanager
    def index(self) -> Iterator[bool]:
        """Serialise a read-modify-write of the index, across processes.

        Yields whether the lock was actually acquired. Yielded rather than stored:
        as ambient state it could be read outside any frame and answer plausibly and
        wrongly. Re-entrant, because `flock` is per open file description and a
        nested acquire would deadlock against the frame above.
        """
        self._index_lock.acquire()
        handle = None
        # An inner frame reuses the outer's lock: acquiring again would open a
        # second descriptor and block against this thread's own hold. It yields
        # False for `locked` — it did not take the lock, so it must not be the
        # frame that decides to trust a stat. The depth moves with the frame, not
        # with the handle, since the acquire fails open.
        outermost = self._index_depth == 0
        try:
            if outermost:
                handle = self._acquire_index_file()
            self._index_depth += 1
            try:
                yield handle is not None
            finally:
                self._index_depth -= 1
        finally:
            if handle is not None:
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                finally:
                    os.close(handle)
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
        self.lock = HostedTranscriptLock(index_lock_path=self.sessions_dir / "sessions.lock")
        # One temp name per store instance. A single shared `sessions.tmp` let
        # two processes interleave into one file; a fresh name per write leaked
        # the whole file on SIGKILL and needed a reaper that could delete a temp
        # another process was mid-write. Per instance is unique without either.
        self._index_temp_path = self.index_path.with_name(
            f"{self.index_path.stem}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        # Key and entries as one attribute, so a lock-free reader cannot pair a
        # new key with old entries. One assignment, one read, atomic under the
        # GIL.
        self._index_snapshot: tuple[tuple[int, int, int], dict[str, HostedSessionIndexEntry]] | None = None
        self.reader = HostedTranscriptReader(self)
        self._initialize_index()

    def _initialize_index(self) -> None:
        with self.lock.index() as locked:
            if not self.index_path.exists():
                self._save_index_unlocked({}, locked=locked)
                return
            try:
                payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                self._reset_index_unlocked(locked=locked)
                return
            if not isinstance(payload, dict) or int(payload.get("version", 0)) != TRANSCRIPT_STORE_VERSION:
                self._reset_index_unlocked(locked=locked)

    def _reset_index_unlocked(self, *, locked: bool) -> None:
        if self.index_path.exists():
            archived = self.index_path.with_name(
                f"{self.index_path.stem}.legacy.{_utc_now().strftime('%Y%m%d%H%M%S')}{self.index_path.suffix}"
            )
            self.index_path.replace(archived)
        self._save_index_unlocked({}, locked=locked)

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def _archive_path(self, session_id: str, deleted_at: datetime) -> Path:
        suffix = deleted_at.strftime("%Y%m%d%H%M%S")
        return self.sessions_dir / f"{session_id}.deleted.{suffix}.jsonl"

    def _index_stat_key(self) -> tuple[int, int, int] | None:
        """A key that changes on every publish, whatever the clock resolution.

        `st_ino` is load-bearing: HFS+ stores whole-second mtimes and an
        `updated_at` bump rewrites a fixed-width string, so mtime and size can both
        be identical across a real change. `replace()` always moves a new inode.
        """
        try:
            info = self.index_path.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size, info.st_ino)

    def _load_index_unlocked(self) -> dict[str, HostedSessionIndexEntry]:
        # Keyed on the file's identity, so another process's write invalidates
        # this too. Safe to call with no lock held: see the note above the read
        # methods.
        stat_key = self._index_stat_key()
        snapshot = self._index_snapshot  # one read: never a torn key/entries pair
        if stat_key is not None and snapshot is not None and snapshot[0] == stat_key:
            return dict(snapshot[1])  # callers mutate what they get back
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
        if stat_key is not None:
            # The stat above precedes the read, so these entries are always at
            # least as new as this key. The harmful pairing — old entries under
            # a new key — is unreachable; a stale key merely costs one reparse.
            self._index_snapshot = (stat_key, dict(entries))
        return entries

    def _save_index_unlocked(
        self, entries: Mapping[str, HostedSessionIndexEntry], *, locked: bool
    ) -> None:
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
        # No `indent`: measured 57.6 ms of the 88.9 ms save on a 6201-entry
        # index, and that save is what every writer holds the lock across. The
        # file has no human reader.
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temp_path = self._index_temp_path
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(self.index_path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        stat_key = self._index_stat_key() if locked else None
        if stat_key is not None:
            self._index_snapshot = (stat_key, dict(entries))
        else:
            # Unlocked write: another process may have published between the
            # `replace()` above and the `stat()` we would take, which would
            # cache our entries under their key and never self-heal. A read
            # stats *before* parsing, so its version of this race corrects
            # itself on the next call; this one does not.
            self._index_snapshot = None

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
            with self.lock.index() as locked:
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
                self._save_index_unlocked(index, locked=locked)
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
            with self.lock.index() as locked:
                index = self._load_index_unlocked()
                entry = index[session_id]
                updated = replace(
                    entry,
                    # A *message* clock, not a write clock. Two appends carrying
                    # the same `created_at` leave this still, and the cross-process
                    # staleness detection in interface/agent/data_routes.py keys on
                    # it — so an explicit `created_at` on an append (a replay, a
                    # migration, a deferred report stamped with its finish time)
                    # would blind that detection with a green suite.
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
                self._save_index_unlocked(index, locked=locked)
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
        # This runs on every session GET and is almost always a no-op, so check
        # before taking the writer's frame. An absent session falls through, so
        # the KeyError still comes from the authoritative read. A publish inside
        # the stat-to-compare window can make it skip an event; harmless, because
        # a reload replays the event stream and this sync re-runs every GET.
        snapshot = self._load_index_unlocked().get(session_id)
        if snapshot is not None and snapshot.runtime_model == normalized:
            return snapshot
        with self.lock.session(session_id):
            with self.lock.index() as locked:
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
                self._save_index_unlocked(index, locked=locked)
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
            with self.lock.index() as locked:
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
                self._save_index_unlocked(index, locked=locked)
                return updated

    def load_events(self, session_id: str) -> tuple[HostedTranscriptEvent, ...]:
        with self.lock.session(session_id):
            return self._read_events_unlocked(session_id)

    # Readers take neither lock. A writer holds the RLock across the whole
    # serialise-and-rename, and every agent route is `def`, so a GET and the
    # running turn's append are concurrent threads in one process.
    #
    # Safe: `replace()` swaps a directory entry and an open fd pins the old
    # inode, and the snapshot is one attribute, so it cannot be read torn.

    def get_session_index(self, session_id: str) -> HostedSessionIndexEntry:
        index = self._load_index_unlocked()
        if session_id not in index:
            raise KeyError(session_id)
        return index[session_id]

    def list_sessions(self, *, include_deleted: bool = False) -> tuple[HostedSessionIndexEntry, ...]:
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
            with self.lock.index() as locked:
                index = self._load_index_unlocked()
                entry = index[session_id]
                session_path = self._session_path(session_id)
                if session_path.exists():
                    session_path.replace(self._archive_path(session_id, timestamp))
                updated = replace(entry, updated_at=timestamp, deleted_at=timestamp)
                index[session_id] = updated
                self._save_index_unlocked(index, locked=locked)
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
