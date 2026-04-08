import copy
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import sleep
from typing import Callable
from zoneinfo import ZoneInfo


RefreshFn = Callable[[], object]
CachePayload = dict | list
FetchPayloadFn = Callable[[], CachePayload]
FallbackPayloadFn = Callable[[], CachePayload]

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
    def __init__(self, poll_seconds: int = 30, timezone_name: str = "UTC") -> None:
        self._poll_seconds = max(1, poll_seconds)
        self._timezone_name = timezone_name
        self._timezone = ZoneInfo(timezone_name)
        self._sources: dict[str, CacheSourceState] = {}
        self._payload_specs: dict[str, CachePayloadSpec] = {}
        self._memory_payloads: dict[str, tuple[CachePayload, datetime]] = {}
        self._lock = Lock()
        self._runner: Thread | None = None
        self._stop_event = Event()
        self._persisted_state = self._load_persisted_state()

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

        if not force_refresh:
            memory = self._read_memory_payload(source, spec.ttl_seconds)
            if memory is not None:
                return CachePayloadResult(payload=memory, freshness="fresh")

            cached = self.file_cache_read(spec.namespace, spec.key, spec.ttl_seconds)
            if isinstance(cached, (dict, list)):
                self._write_memory_payload(source, cached)
                return CachePayloadResult(payload=_copy_payload(cached), freshness="fresh")

        now = datetime.now(UTC)
        try:
            payload = spec.fetch_fn()
            self.file_cache_write(spec.namespace, spec.key, payload)
            self._write_memory_payload(source, payload)
            self._record_source_state(
                source,
                now=now,
                success=True,
                error=None,
                result_kind="fresh",
            )
            return CachePayloadResult(payload=_copy_payload(payload), freshness="fresh")
        except Exception as exc:
            error = str(exc)
            if allow_stale:
                stale = self.file_cache_read_stale(spec.namespace, spec.key)
                if isinstance(stale, (dict, list)):
                    self._write_memory_payload(source, stale, cached_at=now)
                    self._record_source_state(
                        source,
                        now=now,
                        success=False,
                        error=error,
                        result_kind="stale",
                    )
                    return CachePayloadResult(payload=_copy_payload(stale), freshness="stale", error=error)

            if allow_fallback and spec.fallback_fn is not None:
                payload = spec.fallback_fn()
                self._record_source_state(
                    source,
                    now=now,
                    success=False,
                    error=error,
                    result_kind="fallback",
                )
                return CachePayloadResult(payload=_copy_payload(payload), freshness="fallback", error=error)

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
        self.file_cache_clear(spec.namespace, spec.key)

    def set_payload(self, source: str, payload: CachePayload) -> None:
        spec = self._payload_specs.get(source)
        if spec is None:
            raise KeyError(f"Unknown cache payload source: {source}")
        self.file_cache_write(spec.namespace, spec.key, payload)
        self._write_memory_payload(source, payload)

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
    def file_cache_read(namespace: str, key: str, max_age_seconds: int) -> dict | list | None:
        """Read a JSON cache file if it exists and is fresh enough.

        Args:
            namespace: Subdirectory under ~/.terrafin/cache/ (e.g., "guru_holdings")
            key: Cache key (used as filename, sanitized)
            max_age_seconds: Maximum age in seconds before stale

        Returns:
            Parsed JSON payload, or None if missing/stale.
        """
        path = CacheManager.cache_path(namespace, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            cached_at = data.get("_cached_at", "")
            if cached_at:
                age = (datetime.now(UTC) - datetime.fromisoformat(cached_at)).total_seconds()
                if age <= max_age_seconds:
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
    def file_cache_write(namespace: str, key: str, payload: dict | list) -> None:
        """Write data to a JSON cache file with timestamp.

        Args:
            namespace: Subdirectory under ~/.terrafin/cache/
            key: Cache key
            payload: Data to cache
        """
        try:
            cache_dir = _FILE_CACHE_DIR / namespace
            cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "_cached_at": datetime.now(UTC).isoformat(),
                "_payload": payload,
            }
            (cache_dir / f"{_safe_key(key)}.json").write_text(json.dumps(data, indent=2, default=str))
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
        memory = self._memory_payloads.get(source)
        if memory is None:
            return None
        payload, cached_at = memory
        age = (datetime.now(UTC) - cached_at).total_seconds()
        if age > ttl_seconds:
            self._memory_payloads.pop(source, None)
            return None
        return _copy_payload(payload)

    def _write_memory_payload(
        self,
        source: str,
        payload: CachePayload,
        *,
        cached_at: datetime | None = None,
    ) -> None:
        self._memory_payloads[source] = (_copy_payload(payload), cached_at or datetime.now(UTC))

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


def _copy_payload(payload: CachePayload) -> CachePayload:
    return copy.deepcopy(payload)
