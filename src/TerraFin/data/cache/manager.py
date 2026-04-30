import copy
import dataclasses
import json
import logging
import shutil
import sys
import typing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import sleep
from typing import Any, Callable, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)


RefreshFn = Callable[[], object]
CachePayload = Any
FetchPayloadFn = Callable[[], CachePayload]
FallbackPayloadFn = Callable[[], CachePayload]


@runtime_checkable
class CacheSerializer(Protocol):
    name: str

    def write(self, path: Path, payload: Any) -> None: ...

    def read(self, path: Path) -> Any: ...


class JsonContractSerializer:
    """Serializer for dataclass-based contracts.

    Encodes via dataclasses.asdict (datetime -> ISO string), and rebuilds the
    dataclass on read using type hints. Lists of dataclasses and nested
    dataclass fields are handled recursively.
    """

    name = "json_contract"

    def __init__(self, contract_cls: type) -> None:
        self.contract_cls = contract_cls

    def write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "_cached_at": datetime.now(UTC).isoformat(),
            "_serializer": self.name,
            "_contract": self.contract_cls.__name__,
            "_payload": _encode_dataclass(payload),
        }
        path.write_text(json.dumps(data, indent=2, default=str))

    def read(self, path: Path) -> Any:
        data = json.loads(path.read_text())
        raw = data.get("_payload")
        return _decode_dataclass(raw, self.contract_cls)


def _encode_dataclass(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode_dataclass(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, list):
        return [_encode_dataclass(item) for item in value]
    if isinstance(value, tuple):
        return [_encode_dataclass(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode_dataclass(val) for key, val in value.items()}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    return value


def _decode_dataclass(raw: Any, target_type: Any) -> Any:
    if raw is None:
        return None
    origin = typing.get_origin(target_type)
    if isinstance(raw, dict) and "__datetime__" in raw and len(raw) == 1:
        return datetime.fromisoformat(raw["__datetime__"])
    if dataclasses.is_dataclass(target_type) and isinstance(raw, dict):
        hints = typing.get_type_hints(target_type)
        kwargs = {}
        for f in dataclasses.fields(target_type):
            if f.name not in raw:
                continue
            kwargs[f.name] = _decode_dataclass(raw[f.name], hints.get(f.name, Any))
        return target_type(**kwargs)
    if origin is list and isinstance(raw, list):
        (inner,) = typing.get_args(target_type) or (Any,)
        return [_decode_dataclass(item, inner) for item in raw]
    if origin is dict and isinstance(raw, dict):
        args = typing.get_args(target_type)
        val_type = args[1] if len(args) == 2 else Any
        return {key: _decode_dataclass(val, val_type) for key, val in raw.items()}
    return raw

_FILE_CACHE_DIR = Path.home() / ".terrafin" / "cache"
_STATE_FILE_NAME = ".cache_manager_state.json"


@dataclass
class CacheSourceSpec:
    source: str
    mode: str  # "refresh", "clear_only", "file"
    interval_seconds: int
    schedule: str = "interval"  # "interval" | "boundary"
    slots_per_day: int = 1
    refresh_fn: RefreshFn | None = None
    clear_fn: RefreshFn | None = None
    enabled: bool = True


@dataclass(frozen=True)
class CachePayloadSpec:
    source: str
    namespace: str
    key: str
    ttl_seconds: int
    fetch_fn: FetchPayloadFn
    fallback_fn: FallbackPayloadFn | None = None
    frozen_payload: bool = False
    expected_type: type | None = None
    size_estimator: Callable[[Any], int] | None = None


MEMORY_LRU_FROZEN_MAX_BYTES = 200 * 1024 * 1024


@dataclass
class _MemoryEntry:
    payload: CachePayload
    cached_at: datetime
    last_accessed: datetime
    frozen: bool
    size: int


@dataclass(frozen=True)
class CachePayloadResult:
    payload: CachePayload
    freshness: str  # "fresh" | "stale" | "fallback"
    error: str | None = None


@dataclass
class CacheSourceState:
    spec: CacheSourceSpec
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_anchor_at: datetime | None = None
    last_result_kind: str | None = None
    last_schedule_key: str | None = None


class CacheManager:
    _serializers: dict[type, CacheSerializer] = {}

    def __init__(self, poll_seconds: int = 30, timezone_name: str = "UTC") -> None:
        self._poll_seconds = max(1, poll_seconds)
        self._timezone_name = timezone_name
        self._timezone = ZoneInfo(timezone_name)
        self._sources: dict[str, CacheSourceState] = {}
        self._payload_specs: dict[str, CachePayloadSpec] = {}
        self._memory_payloads: dict[str, _MemoryEntry] = {}
        self._lock = Lock()
        self._fetch_locks: dict[str, Lock] = {}
        self._fetch_locks_mutex = Lock()
        self._runner: Thread | None = None
        self._stop_event = Event()
        self._persisted_state = self._load_persisted_state()

    def _get_fetch_lock(self, source: str) -> Lock:
        with self._fetch_locks_mutex:
            lock = self._fetch_locks.get(source)
            if lock is None:
                lock = Lock()
                self._fetch_locks[source] = lock
            return lock

    def register(self, spec: CacheSourceSpec) -> None:
        with self._lock:
            existing = self._sources.get(spec.source)
            if existing is not None:
                merged_spec = CacheSourceSpec(
                    source=spec.source,
                    mode=spec.mode,
                    interval_seconds=spec.interval_seconds,
                    schedule=spec.schedule,
                    slots_per_day=max(1, spec.slots_per_day),
                    refresh_fn=spec.refresh_fn or existing.spec.refresh_fn,
                    clear_fn=spec.clear_fn or existing.spec.clear_fn,
                    enabled=spec.enabled,
                )
                self._sources[spec.source] = CacheSourceState(
                    spec=merged_spec,
                    last_run_at=existing.last_run_at,
                    last_success_at=existing.last_success_at,
                    last_error=existing.last_error,
                    last_anchor_at=existing.last_anchor_at,
                    last_result_kind=existing.last_result_kind,
                    last_schedule_key=existing.last_schedule_key,
                )
                self._persist_state_locked()
                return

            persisted = self._persisted_state.get(spec.source, {})
            anchor_at = self._parse_datetime(persisted.get("last_anchor_at"))
            if spec.mode == "clear_only" and anchor_at is None:
                anchor_at = datetime.now(UTC)

            self._sources[spec.source] = CacheSourceState(
                spec=spec,
                last_run_at=self._parse_datetime(persisted.get("last_run_at")),
                last_success_at=self._parse_datetime(persisted.get("last_success_at")),
                last_error=persisted.get("last_error"),
                last_anchor_at=anchor_at,
                last_result_kind=persisted.get("last_result_kind"),
                last_schedule_key=persisted.get("last_schedule_key"),
            )
            self._persist_state_locked()

    def register_payload(self, spec: CachePayloadSpec) -> None:
        with self._lock:
            self._payload_specs[spec.source] = spec
            existing = self._sources.get(spec.source)

        self.register(
            CacheSourceSpec(
                source=spec.source,
                mode="refresh",
                interval_seconds=existing.spec.interval_seconds if existing is not None else spec.ttl_seconds,
                schedule=existing.spec.schedule if existing is not None else "interval",
                slots_per_day=existing.spec.slots_per_day if existing is not None else 1,
                refresh_fn=lambda source=spec.source: self.refresh_payload(source),
                clear_fn=lambda source=spec.source: self.clear_payload(source),
                enabled=existing.spec.enabled if existing is not None else True,
            )
        )

    def get_payload(
        self,
        source: str,
        *,
        force_refresh: bool = False,
        allow_stale: bool = True,
        allow_fallback: bool = True,
    ) -> CachePayloadResult:
        spec = self._payload_specs.get(source)
        if spec is None:
            raise KeyError(f"Unknown cache payload source: {source}")

        frozen = spec.frozen_payload

        custom_serializer = self._serializer_for_cls(spec.expected_type) if spec.expected_type else None

        def _try_cached() -> CachePayloadResult | None:
            memory = self._read_memory_payload(source, spec.ttl_seconds)
            if memory is not None:
                return CachePayloadResult(payload=memory, freshness="fresh")
            if not frozen:
                if custom_serializer is not None:
                    artifact = self._read_artifact(spec, custom_serializer)
                    if artifact is not None:
                        self._write_memory_payload(source, artifact, spec=spec, frozen=frozen)
                        return CachePayloadResult(payload=_copy_payload(artifact, frozen=frozen), freshness="fresh")
                else:
                    cached = self.file_cache_read(spec.namespace, spec.key, spec.ttl_seconds)
                    if isinstance(cached, (dict, list)):
                        self._write_memory_payload(source, cached, spec=spec, frozen=frozen)
                        return CachePayloadResult(payload=_copy_payload(cached, frozen=frozen), freshness="fresh")
            return None

        if not force_refresh:
            hit = _try_cached()
            if hit is not None:
                return hit

        # Single-flight: serialize concurrent misses on the same source so
        # only one thread runs fetch_fn. Other waiters re-check cache after
        # the holder populates it.
        fetch_lock = self._get_fetch_lock(source)
        with fetch_lock:
            if not force_refresh:
                hit = _try_cached()
                if hit is not None:
                    return hit

            now = datetime.now(UTC)
            try:
                payload = spec.fetch_fn()
                if not frozen:
                    if custom_serializer is not None:
                        self._write_artifact(spec, custom_serializer, payload)
                    else:
                        self.file_cache_write(spec.namespace, spec.key, payload)
                self._write_memory_payload(source, payload, spec=spec, frozen=frozen)
                self._record_source_state(
                    source,
                    now=now,
                    success=True,
                    error=None,
                    result_kind="fresh",
                )
                return CachePayloadResult(payload=_copy_payload(payload, frozen=frozen), freshness="fresh")
            except Exception as exc:
                error = str(exc)
                if allow_stale and not frozen:
                    stale = self.file_cache_read_stale(spec.namespace, spec.key)
                    if isinstance(stale, (dict, list)):
                        self._write_memory_payload(source, stale, cached_at=now, spec=spec, frozen=frozen)
                        self._record_source_state(
                            source,
                            now=now,
                            success=False,
                            error=error,
                            result_kind="stale",
                        )
                        return CachePayloadResult(payload=_copy_payload(stale, frozen=frozen), freshness="stale", error=error)

                if allow_fallback and spec.fallback_fn is not None:
                    payload = spec.fallback_fn()
                    self._record_source_state(
                        source,
                        now=now,
                        success=False,
                        error=error,
                        result_kind="fallback",
                    )
                    return CachePayloadResult(payload=_copy_payload(payload, frozen=frozen), freshness="fallback", error=error)

                self._record_source_state(
                    source,
                    now=now,
                    success=False,
                    error=error,
                    result_kind="error",
                )
                raise

    def refresh_payload(
        self,
        source: str,
        *,
        allow_stale: bool = True,
        allow_fallback: bool = True,
    ) -> CachePayloadResult:
        return self.get_payload(
            source,
            force_refresh=True,
            allow_stale=allow_stale,
            allow_fallback=allow_fallback,
        )

    def clear_payload(self, source: str) -> None:
        spec = self._payload_specs.get(source)
        if spec is None:
            return
        self._memory_payloads.pop(source, None)
        if not spec.frozen_payload:
            if spec.expected_type is not None and self._serializer_for_cls(spec.expected_type) is not None:
                target = self.artifact_path(spec.namespace, spec.key)
                if target.exists():
                    try:
                        shutil.rmtree(target)
                    except OSError:
                        pass
            else:
                self.file_cache_clear(spec.namespace, spec.key)

    def _read_artifact(self, spec: "CachePayloadSpec", serializer: CacheSerializer) -> Any:
        path = self.artifact_path(spec.namespace, spec.key)
        if not path.exists():
            return None
        meta_path = path / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                cached_at = meta.get("cached_at")
                if cached_at:
                    age = (datetime.now(UTC) - datetime.fromisoformat(cached_at)).total_seconds()
                    if age > spec.ttl_seconds:
                        return None
            except Exception:
                return None
        try:
            return serializer.read(path)
        except Exception:
            return None

    def _write_artifact(self, spec: "CachePayloadSpec", serializer: CacheSerializer, payload: Any) -> None:
        path = self.artifact_path(spec.namespace, spec.key)
        try:
            serializer.write(path, payload)
        except Exception:
            pass

    def set_payload(self, source: str, payload: CachePayload) -> None:
        spec = self._payload_specs.get(source)
        if spec is None:
            raise KeyError(f"Unknown cache payload source: {source}")
        if not spec.frozen_payload:
            self.file_cache_write(spec.namespace, spec.key, payload)
        self._write_memory_payload(source, payload, spec=spec, frozen=spec.frozen_payload)

    @classmethod
    def register_serializer(cls, contract_cls: type, serializer: CacheSerializer) -> None:
        cls._serializers[contract_cls] = serializer

    def serializer_for(self, payload_or_cls: Any) -> CacheSerializer | None:
        cls = payload_or_cls if isinstance(payload_or_cls, type) else type(payload_or_cls)
        serializer = type(self)._serializers.get(cls)
        if serializer is not None:
            return serializer
        for registered_cls, registered_serializer in type(self)._serializers.items():
            if isinstance(payload_or_cls, registered_cls):
                return registered_serializer
        return None

    @classmethod
    def _serializer_for_cls(cls, target_cls: type | None) -> CacheSerializer | None:
        if target_cls is None:
            return None
        return cls._serializers.get(target_cls)

    def refresh_due_sources(self, force: bool = False, force_modes: set[str] | None = None) -> None:
        with self._lock:
            states = list(self._sources.values())
        now = datetime.now(UTC)
        for state in states:
            if not state.spec.enabled:
                continue
            should_force = force and (force_modes is None or state.spec.mode in force_modes)
            if not should_force and not self._is_due(state, now):
                continue
            self._run_source(state, now)

    def _run_source(self, state: CacheSourceState, now: datetime) -> None:
        fn: RefreshFn | None = state.spec.refresh_fn if state.spec.mode == "refresh" else state.spec.clear_fn
        if fn is None:
            return
        try:
            result = fn()
            if isinstance(result, CachePayloadResult):
                if result.freshness == "fresh":
                    state.last_success_at = now
                    state.last_error = None
                else:
                    state.last_error = result.error
                state.last_result_kind = result.freshness
            else:
                state.last_success_at = now
                state.last_error = None
                state.last_result_kind = "fresh"
        except Exception as exc:  # pragma: no cover - runtime safeguard
            state.last_error = str(exc)
            state.last_result_kind = "error"
            print(f"Cache manager: source '{state.spec.source}' failed: {exc}")
        finally:
            state.last_run_at = now
            state.last_anchor_at = now
            state.last_schedule_key = self._schedule_key_for_state(state.spec, now)
            with self._lock:
                self._persist_state_locked()

    def _is_due(self, state: CacheSourceState, now: datetime) -> bool:
        if state.spec.schedule == "boundary":
            schedule_key = self._schedule_key_for_state(state.spec, now)
            return schedule_key is not None and schedule_key != state.last_schedule_key
        reference = state.last_run_at or state.last_anchor_at
        if reference is None:
            return True
        elapsed = (now - reference).total_seconds()
        return elapsed >= state.spec.interval_seconds

    def start(self) -> None:
        if self._runner is not None and self._runner.is_alive():
            return
        self._stop_event.clear()
        self._runner = Thread(target=self._loop, name="cache-manager", daemon=True)
        self._runner.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._runner is not None:
            self._runner.join(timeout=2.0)

    def _loop(self) -> None:
        self.refresh_due_sources(force=False)
        while not self._stop_event.is_set():
            self.refresh_due_sources(force=False)
            sleep(self._poll_seconds)

    def clear_all(self) -> None:
        with self._lock:
            states = list(self._sources.values())
        now = datetime.now(UTC)
        for state in states:
            if state.spec.clear_fn is None:
                continue
            try:
                state.spec.clear_fn()
                state.last_success_at = now
                state.last_error = None
                state.last_result_kind = "fresh"
            except Exception as exc:  # pragma: no cover
                state.last_error = str(exc)
                state.last_result_kind = "error"
                print(f"Cache manager: clear failed for '{state.spec.source}': {exc}")
            finally:
                state.last_run_at = now
                state.last_anchor_at = now
                state.last_schedule_key = self._schedule_key_for_state(state.spec, now)
        with self._lock:
            self._persist_state_locked()

    # ── File-based cache ────────────────────────────────────────────────

    @staticmethod
    def cache_root() -> Path:
        return _FILE_CACHE_DIR

    @staticmethod
    def namespace_dir(namespace: str) -> Path:
        return _FILE_CACHE_DIR / namespace

    @staticmethod
    def safe_key(key: str) -> str:
        return _safe_key(key)

    @staticmethod
    def cache_path(namespace: str, key: str) -> Path:
        return _FILE_CACHE_DIR / namespace / f"{_safe_key(key)}.json"

    @staticmethod
    def artifact_path(namespace: str, key: str) -> Path:
        """Directory path for serializer-managed artifacts.

        Slashes in ``key`` are preserved as path separators (each segment is
        independently sanitized) so callers can address legacy on-disk layouts
        like ``yfinance_v2/<TICKER>/<variant>/``.
        """
        segments = [_safe_key(seg) for seg in key.split("/") if seg]
        return _FILE_CACHE_DIR.joinpath(namespace, *segments)

    @staticmethod
    def file_cache_read(
        namespace: str,
        key: str,
        max_age_seconds: int,
        *,
        expected_type: type | None = None,
    ) -> Any:
        """Read a cache file if it exists and is fresh enough.

        If a serializer is registered for ``expected_type``, dispatch to it;
        otherwise fall back to the JSON envelope format.
        """
        serializer = CacheManager._serializer_for_cls(expected_type)
        path = CacheManager.cache_path(namespace, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            cached_at = data.get("_cached_at", "")
            if cached_at:
                age = (datetime.now(UTC) - datetime.fromisoformat(cached_at)).total_seconds()
                if age > max_age_seconds:
                    return None
            if serializer is not None and data.get("_serializer") == getattr(serializer, "name", None):
                return serializer.read(path)
            return data.get("_payload")
        except Exception:
            pass
        return None

    @staticmethod
    def file_cache_read_stale(namespace: str, key: str) -> dict | list | None:
        """Read a JSON cache file regardless of freshness.

        Returns the cached payload if the file exists and is parseable.
        """
        path = CacheManager.cache_path(namespace, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            payload = data.get("_payload")
        except Exception:
            return None
        return payload if isinstance(payload, (dict, list)) else None

    @staticmethod
    def file_cache_write(namespace: str, key: str, payload: Any) -> None:
        """Write data to a cache file with timestamp.

        If a serializer is registered for ``type(payload)``, dispatch to it;
        otherwise fall back to the JSON envelope format.
        """
        serializer = CacheManager._serializer_for_cls(type(payload))
        path = _FILE_CACHE_DIR / namespace / f"{_safe_key(key)}.json"
        try:
            if serializer is not None:
                serializer.write(path, payload)
                return
            cache_dir = _FILE_CACHE_DIR / namespace
            cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "_cached_at": datetime.now(UTC).isoformat(),
                "_payload": payload,
            }
            path.write_text(json.dumps(data, indent=2, default=str))
        except OSError:
            pass

    @staticmethod
    def file_cache_clear(namespace: str, key: str | None = None) -> None:
        """Clear file cache. If key is None, clear entire namespace."""
        cache_dir = _FILE_CACHE_DIR / namespace
        if not cache_dir.exists():
            return
        if key:
            path = cache_dir / f"{_safe_key(key)}.json"
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        else:
            for f in cache_dir.glob("*.json"):
                try:
                    f.unlink()
                except OSError:
                    pass

    @staticmethod
    def file_cache_remove_tree(namespace: str, key: str | None = None) -> None:
        """Remove a namespace or namespace/key directory tree."""
        target = CacheManager.namespace_dir(namespace)
        if key is not None:
            target = target / _safe_key(key)
        if not target.exists():
            return
        try:
            shutil.rmtree(target)
        except OSError:
            pass

    def get_status(self) -> list[dict]:
        with self._lock:
            states = list(self._sources.values())
        result: list[dict] = []
        for state in states:
            result.append(
                {
                    "source": state.spec.source,
                    "mode": state.spec.mode,
                    "intervalSeconds": state.spec.interval_seconds,
                    "enabled": state.spec.enabled,
                    "lastRunAt": state.last_run_at.isoformat() if state.last_run_at else None,
                    "lastSuccessAt": state.last_success_at.isoformat() if state.last_success_at else None,
                    "lastError": state.last_error,
                    "lastResultKind": state.last_result_kind,
                    "schedule": state.spec.schedule,
                    "slotsPerDay": state.spec.slots_per_day,
                }
            )
        return result

    @staticmethod
    def _state_path() -> Path:
        return _FILE_CACHE_DIR / _STATE_FILE_NAME

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _load_persisted_state(self) -> dict[str, dict]:
        path = self._state_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except Exception:
            return {}
        sources = data.get("sources")
        if not isinstance(sources, dict):
            return {}
        return {str(source): value for source, value in sources.items() if isinstance(value, dict)}

    def _persist_state_locked(self) -> None:
        try:
            _FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "sources": {
                    source: {
                        "last_run_at": state.last_run_at.isoformat() if state.last_run_at else None,
                        "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
                        "last_error": state.last_error,
                        "last_anchor_at": state.last_anchor_at.isoformat() if state.last_anchor_at else None,
                        "last_result_kind": state.last_result_kind,
                        "last_schedule_key": state.last_schedule_key,
                    }
                    for source, state in self._sources.items()
                },
            }
            self._state_path().write_text(json.dumps(payload, indent=2))
            self._persisted_state = payload["sources"]
        except OSError:
            pass

    def _read_memory_payload(self, source: str, ttl_seconds: int) -> CachePayload | None:
        entry = self._memory_payloads.get(source)
        if entry is None:
            return None
        now = datetime.now(UTC)
        age = (now - entry.cached_at).total_seconds()
        if age > ttl_seconds:
            self._memory_payloads.pop(source, None)
            return None
        entry.last_accessed = now
        return _copy_payload(entry.payload, frozen=entry.frozen)

    def _write_memory_payload(
        self,
        source: str,
        payload: CachePayload,
        *,
        cached_at: datetime | None = None,
        frozen: bool = False,
        spec: "CachePayloadSpec | None" = None,
    ) -> None:
        now = cached_at or datetime.now(UTC)
        stored = payload if frozen else _copy_payload(payload, frozen=False)
        size = _estimate_size(stored, spec) if frozen else 0
        self._memory_payloads[source] = _MemoryEntry(
            payload=stored,
            cached_at=now,
            last_accessed=now,
            frozen=frozen,
            size=size,
        )
        if frozen:
            self._evict_frozen_lru()

    def _evict_frozen_lru(self) -> None:
        total = sum(e.size for e in self._memory_payloads.values() if e.frozen)
        if total <= MEMORY_LRU_FROZEN_MAX_BYTES:
            return
        frozen_items = [
            (src, entry) for src, entry in self._memory_payloads.items() if entry.frozen
        ]
        frozen_items.sort(key=lambda kv: kv[1].last_accessed)
        for src, entry in frozen_items:
            if total <= MEMORY_LRU_FROZEN_MAX_BYTES:
                break
            self._memory_payloads.pop(src, None)
            total -= entry.size

    def _record_source_state(
        self,
        source: str,
        *,
        now: datetime,
        success: bool,
        error: str | None,
        result_kind: str,
    ) -> None:
        with self._lock:
            state = self._sources.get(source)
            if state is None:
                return
            state.last_run_at = now
            state.last_anchor_at = now
            state.last_error = error
            state.last_result_kind = result_kind
            state.last_schedule_key = self._schedule_key_for_state(state.spec, now)
            if success:
                state.last_success_at = now
            self._persist_state_locked()

    def _schedule_key_for_state(self, spec: CacheSourceSpec, now: datetime) -> str | None:
        if spec.schedule != "boundary":
            return None
        slots = max(1, spec.slots_per_day)
        local_now = now.astimezone(self._timezone)
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_since_midnight = int((local_now - midnight).total_seconds())
        slot_length = (24 * 60 * 60) / slots
        slot_index = min(slots - 1, int(seconds_since_midnight // slot_length))
        return f"{local_now.date().isoformat()}:{slot_index}"


def _safe_key(key: str) -> str:
    """Sanitize a cache key for use as a filename."""
    return key.lower().replace(" ", "_").replace("/", "_")


def _copy_payload(payload: CachePayload, *, frozen: bool = False) -> CachePayload:
    if frozen:
        return payload
    return copy.deepcopy(payload)


def _estimate_size(payload: Any, spec: "CachePayloadSpec | None" = None) -> int:
    """Approximate in-memory size of a frozen payload, in bytes.

    Estimates are approximate; complex object graphs are undercounted.
    """
    if spec is not None and spec.size_estimator is not None:
        try:
            return int(spec.size_estimator(payload))
        except Exception:
            pass
    return _default_size_estimator(payload)


def _default_size_estimator(payload: Any) -> int:
    if payload is None:
        return 0
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    if isinstance(payload, bytes):
        return len(payload)
    try:
        import pandas as pd

        if isinstance(payload, pd.DataFrame):
            return int(payload.memory_usage(deep=True).sum())
        if isinstance(payload, pd.Series):
            return int(payload.memory_usage(deep=True))
    except Exception:
        pass
    if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
        total = 0
        for f in dataclasses.fields(payload):
            total += _default_size_estimator(getattr(payload, f.name, None))
        return total
    if isinstance(payload, (list, tuple)):
        return sum(_default_size_estimator(item) for item in payload)
    if isinstance(payload, dict):
        return sum(_default_size_estimator(k) + _default_size_estimator(v) for k, v in payload.items())
    return sys.getsizeof(payload)
