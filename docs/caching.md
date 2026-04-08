---
title: Cache System
summary: How TerraFin combines in-memory cache, file cache, and a background manager to keep data fresh.
read_when:
  - Understanding how TerraFin keeps data fresh
  - Tuning cache intervals or policies
  - Registering a new cache source
  - Debugging stale data issues
---

# Cache System

TerraFin uses two cache layers:

- in-memory cache for fast reuse inside the current process
- on-disk cache under `~/.terrafin/cache/` for reuse across restarts

On top of that, TerraFin runs a background `CacheManager` for sources that need
scheduled refresh or scheduled invalidation.

## Architecture overview

```
register sources ─> start() on app startup ─> daemon thread polls every N seconds
                                                 │
                                   ┌─────────────┴─────────────┐
                                   │                           │
                              refresh_fn()               clear_fn()
                           (active fetch)          (invalidate; lazy refill)
                                   │                           │
                              stop() on app shutdown ──────────┘
```

### Key modules

| Module | Path | Responsibility |
|--------|------|----------------|
| `CacheManager` | `src/TerraFin/data/cache/manager.py` | Runs the poll loop, tracks source state |
| `CachePolicy` | `src/TerraFin/data/cache/policy.py` | Declares default intervals and env-var overrides |
| Cache registry | `src/TerraFin/data/cache/registry.py` | Wires callbacks, exposes singleton manager |

The manager persists scheduling state in:

```text
~/.terrafin/cache/.cache_manager_state.json
```

That persisted state keeps `clear_only` schedules stable across restarts.

## What the manager controls

The background manager only controls registered sources. Today that means:

| Source | Mode | Default interval | Purpose |
|--------|------|------------------|---------|
| `private.market_breadth` | `refresh` | 12 h | Boundary schedule, runs at local midnight/noon |
| `private.trailing_forward_pe` | `refresh` | 12 h | Boundary schedule, runs at local midnight/noon |
| `private.cape` | `refresh` | 1 d | Boundary schedule, runs after local day change |
| `private.calendar` | `refresh` | 1 d | Boundary schedule, runs after local day change |
| `private.macro` | `refresh` | 1 d | Boundary schedule, runs after local day change |
| `private.fear_greed` | `refresh` | 12 h | Boundary schedule, runs at local midnight/noon |
| `private.top_companies` | `refresh` | 1 d | Boundary schedule, runs after local day change |
| `fred.cache` | `clear_only` | 3 d | Invalidate FRED cache and refetch lazily |
| `yfinance.cache` | `clear_only` | 12 h | Invalidate yfinance cache and refetch lazily |
| `portfolio.cache` | `clear_only` | 3 d | Invalidate guru portfolio file cache and refetch lazily |

## Cache modes

### `refresh`

Call `refresh_fn` on a schedule. Use this for data that should stay warm even if
no request is currently hitting it.

Refresh sources can run in two scheduling styles:

- `interval`: due after `interval_seconds` have elapsed
- `boundary`: due once per local schedule slot in `TERRAFIN_CACHE_TIMEZONE`

TerraFin uses boundary scheduling for private dashboard payloads, so daily
sources refresh once after the local day changes and 12-hour sources refresh at
the local midnight/noon boundaries.

### `clear_only`

Call `clear_fn` on a schedule. The next caller repopulates the cache on demand.
Use this for public providers where background fetching is unnecessary.

At startup, TerraFin only runs sources that are already due. `clear_only`
sources therefore keep their persisted anchors, and boundary-scheduled refresh
sources only catch up if the configured local slot changed while the server was
down.

## File cache

TerraFin has two on-disk cache styles:

- generic JSON namespace/key files managed by `CacheManager.file_cache_*`
- specialized provider-owned artifacts such as `yfinance_v2`

### Generic JSON file cache

Generic file cache uses a namespace/key layout:

```text
~/.terrafin/cache/<namespace>/<key>.json
```

Each JSON file stores:

```json
{"_cached_at": "<ISO timestamp>", "_payload": ...}
```

Reads check freshness against a TTL supplied by the caller. File I/O is handled
by these static helpers on `CacheManager`:

- `file_cache_read(namespace, key, max_age_seconds)`
- `file_cache_write(namespace, key, payload)`
- `file_cache_clear(namespace, key=None)`

### Specialized yfinance artifacts

yfinance-backed market history uses its own typed artifact layout:

```text
~/.terrafin/cache/yfinance_v2/<safe_key>/
  seed_3y/
    meta.json
    time_i64.npy
    close_f64.npy
    open_f64.npy
    high_f64.npy
    low_f64.npy
    volume_f64.npy
  full/
    meta.json
    time_i64.npy
    close_f64.npy
    open_f64.npy
    high_f64.npy
    low_f64.npy
    volume_f64.npy
```

Important details:

- `seed_3y` stores the recent bootstrap window used by progressive chart loads
- `full` stores the complete history artifact
- `meta.json` carries `cached_at`, bounds, schema, and completeness flags
- NumPy arrays let TerraFin slice from the tail of a full artifact without
  rebuilding the whole dataset eagerly
- full-history tail reads use memory-mapped NumPy loads when possible

### yfinance read order

For recent-history chart seeds, TerraFin checks:

```text
recent memory cache
  -> full memory cache
  -> tail slice from yfinance_v2/full
  -> yfinance_v2/seed_3y
  -> upstream 3Y download
```

For older-history backfill, TerraFin checks:

```text
full memory cache
  -> yfinance_v2/full
  -> upstream full-history download
```

### Recovery chain

When TerraFin tries to satisfy a request, the recovery order is:

```text
in-memory  ->  on-disk cache  ->  upstream fetch  ->  fallback fixture
```

Not every source has a fixture fallback, but the on-disk cache acts as the
bridge between process restarts and fresh upstream data.

### Generic JSON namespaces

| Source | Namespace | Key | Typical TTL |
|--------|-----------|-----|-------------|
| Watchlist | `private_watchlist` | `snapshot` | 24 h |
| Market breadth | `private_breadth` | `metrics` | 24 h |
| P/E spread | `private_pe_spread` | `spread` | 24 h |
| CAPE | `private_cape` | `current` | 7 d |
| Calendar | `private_calendar` | `events` | 7 d |
| Macro events | `private_macro` | `events` | 7 d |
| FRED | `fred` | `{series_name}` | 7 d |
| Guru holdings | `guru_holdings` | `{guru_name}` | 7 d |

### Specialized namespaces

| Source | Namespace | Layout |
|--------|-----------|--------|
| yfinance | `yfinance_v2` | `<safe_key>/seed_3y/` and `<safe_key>/full/` typed artifacts |

## Configuration precedence

Cache intervals resolve in this order:

1. matching environment variable
2. hardcoded default in `get_default_cache_policies()`

Supported configuration keys:

| Source | Config key | Env var |
|--------|------------|---------|
| `private.market_breadth` | `market_breadth` | `TERRAFIN_CACHE_MARKET_BREADTH` |
| `private.trailing_forward_pe` | `trailing_forward_pe` | `TERRAFIN_CACHE_TRAILING_FORWARD_PE` |
| `private.cape` | `cape` | `TERRAFIN_CACHE_CAPE` |
| `private.calendar` | `calendar` | `TERRAFIN_CACHE_CALENDAR` |
| `private.macro` | `macro` | `TERRAFIN_CACHE_MACRO` |
| `private.fear_greed` | `fear_greed` | `TERRAFIN_CACHE_FEAR_GREED` |
| `private.top_companies` | `top_companies` | `TERRAFIN_CACHE_TOP_COMPANIES` |
| `fred.cache` | `fred` | `TERRAFIN_CACHE_FRED` |
| `yfinance.cache` | `yfinance` | `TERRAFIN_CACHE_YFINANCE` |
| `portfolio.cache` | `portfolio` | `TERRAFIN_CACHE_PORTFOLIO` |

For new private refresh sources, the default convention is daily refresh unless
there is a specific reason to keep the payload warmer.

Boundary schedules use `TERRAFIN_CACHE_TIMEZONE` from the runtime config. If
that variable is unset, TerraFin uses `UTC`.

## CacheManager API

```python
from TerraFin.data.cache.manager import CacheManager, CacheSourceSpec
```

### Types

```python
RefreshFn = Callable[[], object]
```

#### CacheSourceSpec (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Unique source identifier |
| `mode` | `str` | In practice, `"refresh"` or `"clear_only"` |
| `interval_seconds` | `int` | Seconds between runs |
| `schedule` | `str` | `"interval"` or `"boundary"` |
| `slots_per_day` | `int` | Number of local boundary slots per day |
| `refresh_fn` | `RefreshFn \| None` | Called in refresh mode (default `None`) |
| `clear_fn` | `RefreshFn \| None` | Called in clear_only mode (default `None`) |
| `enabled` | `bool` | Whether the source is active (default `True`) |

#### CacheSourceState (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `spec` | `CacheSourceSpec` | The source specification |
| `last_run_at` | `datetime \| None` | Timestamp of last execution |
| `last_success_at` | `datetime \| None` | Timestamp of last successful execution |
| `last_error` | `str \| None` | Error message from last failure |
| `last_anchor_at` | `datetime \| None` | Persisted interval anchor, mainly used by `clear_only` sources |
| `last_result_kind` | `str \| None` | Last outcome kind: `fresh`, `stale`, `fallback`, or `error` |
| `last_schedule_key` | `str \| None` | Last completed local boundary slot for boundary-scheduled sources |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(poll_seconds: int = 30, timezone_name: str = "UTC")` | Create a manager that polls every `poll_seconds` using the given cache timezone |
| `register` | `(spec: CacheSourceSpec) -> None` | Register a cache source |
| `register_payload` | `(spec: CachePayloadSpec) -> None` | Register a manager-owned JSON payload source |
| `get_payload` | `(source: str, *, force_refresh: bool = False, allow_stale: bool = True, allow_fallback: bool = True) -> CachePayloadResult` | Read-through access for registered payload sources |
| `refresh_payload` | `(source: str, *, allow_stale: bool = True, allow_fallback: bool = True) -> CachePayloadResult` | Force-refresh a payload source |
| `clear_payload` | `(source: str) -> None` | Clear one payload source from memory and file cache |
| `set_payload` | `(source: str, payload: dict \| list) -> None` | Seed or overwrite a payload source |
| `refresh_due_sources` | `(force: bool = False) -> None` | Refresh sources that are due; pass `force=True` to refresh all |
| `start` | `() -> None` | Start the background daemon thread |
| `stop` | `() -> None` | Stop the background thread |
| `clear_all` | `() -> None` | Clear every registered source |
| `get_status` | `() -> list[dict]` | Return status dicts with `source`, `mode`, `intervalSeconds`, `schedule`, `slotsPerDay`, `enabled`, `lastRunAt`, `lastSuccessAt`, `lastError`, `lastResultKind` |

Internal methods (`_run_source`, `_is_due`, `_loop`) are not part of the public
API. Do not call them directly.

## Cache registry

The registry module provides the singleton `CacheManager` and registers the
default scheduled sources. Payload-backed private data is not refreshed through
service callbacks anymore; those sources self-register as `CachePayloadSpec`
entries and the manager owns their refresh, stale fallback, and file-cache
lifecycles directly.

```python
from TerraFin.data.cache.registry import (
    get_cache_manager,
    reset_cache_manager,
    clear_all_cache,
    refresh_all_due,
)
```

### Functions

| Function | Description |
|----------|-------------|
| `get_cache_manager()` | Return the singleton `CacheManager`; initializes it with `TERRAFIN_CACHE_TIMEZONE` and registers defaults on first call |
| `reset_cache_manager()` | Reset the singleton manager; mainly for tests |
| `clear_all_cache()` | Clear all registered cache sources |
| `refresh_all_due(force: bool = False)` | Refresh due sources (or all when `force=True`) |

The internal `_register_default_sources(manager)` now does two things:

- register scheduled policy entries such as `private.market_breadth`,
  `private.top_companies`, `private.fear_greed`, and the other `private.*`
  payload sources
- attach clear functions only for the `clear_only` provider caches such as
  `yfinance.cache`, `fred.cache`, `portfolio.cache`, and `ticker_info.cache`

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard/api/cache-status` | Return status of all registered sources |
| `POST` | `/dashboard/api/cache-refresh?force=true` | Trigger refresh of due sources (or all if `force=true`) |

## Extending the cache system

To register a new cache source:

```python
from TerraFin.data.cache.manager import CacheSourceSpec
from TerraFin.data.cache.registry import get_cache_manager

spec = CacheSourceSpec(
    source="my_provider.cache",
    mode="clear_only",           # or "refresh"
    interval_seconds=3600,
    clear_fn=my_clear_function,  # for clear_only mode
    # refresh_fn=my_refresh_fn,  # for refresh mode
    enabled=True,
)

manager = get_cache_manager()
manager.register(spec)
```

### Checklist

1. Choose `refresh` only when the source truly needs proactive warming.
2. Prefer `clear_only` for public providers that can fetch on demand.
3. Keep the callback idempotent and safe to run from a background thread.
4. Add an env var only if you want the interval to be operator-configurable.

## See also

- [data-layer.md](./data-layer.md) for how providers use these caches
- [interface.md](./interface.md) for the dashboard endpoints that expose cache status
