from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from TerraFin.data.cache.manager import CacheManager, CachePayloadSpec
from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.contracts import HistoryChunk
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from .client import PrivateAccessClient
from .config import load_private_access_config


HistoryNormalizer = Callable[[Any], list[dict]]
CurrentNormalizer = Callable[[dict], dict]
HistoryDeriver = Callable[[list[dict]], dict]
FrameBuilder = Callable[[list[dict]], TimeSeriesDataFrame]
HistoryFetcher = Callable[[PrivateAccessClient], Any]
CurrentFetcher = Callable[[PrivateAccessClient], dict]


@dataclass(frozen=True)
class PrivateSeriesSpec:
    key: str
    display_name: str
    history_cache_namespace: str
    history_fetcher: HistoryFetcher
    history_normalizer: HistoryNormalizer
    frame_builder: FrameBuilder
    current_cache_namespace: str | None = None
    current_fetcher: CurrentFetcher | None = None
    current_normalizer: CurrentNormalizer | None = None
    current_deriver: HistoryDeriver | None = None
    history_cache_key: str = "history"
    current_cache_key: str = "current"
    history_ttl: int = 86_400
    current_ttl: int = 3_600

def get_private_series_history(
    spec: PrivateSeriesSpec,
    *,
    force_refresh: bool = False,
    client: PrivateAccessClient | None = None,
) -> list[dict]:
    if client is not None:
        return _fetch_series_history_direct(spec, force_refresh=force_refresh, client=client)

    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    result = manager.get_payload(_history_source_name(spec), force_refresh=force_refresh, allow_stale=True)
    payload = result.payload
    return [dict(item) for item in payload] if isinstance(payload, list) else []


def get_private_series_current(
    spec: PrivateSeriesSpec,
    *,
    force_refresh: bool = False,
    client: PrivateAccessClient | None = None,
) -> dict:
    if spec.current_cache_namespace is None or spec.current_deriver is None:
        raise RuntimeError(f"{spec.display_name} does not define a current snapshot contract.")

    if client is not None:
        return _fetch_series_current_direct(spec, force_refresh=force_refresh, client=client)

    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    result = manager.get_payload(_current_source_name(spec), force_refresh=force_refresh, allow_stale=True)
    payload = result.payload
    return dict(payload) if isinstance(payload, dict) else {}


def get_private_series_frame(spec: PrivateSeriesSpec) -> TimeSeriesDataFrame:
    frame = spec.frame_builder(get_private_series_history(spec))
    frame.name = spec.display_name
    return frame


def get_private_series_recent_history(spec: PrivateSeriesSpec, *, period: str = "3y") -> HistoryChunk:
    full_frame = get_private_series_frame(spec)
    recent_frame = _slice_recent_timeseries(full_frame, period)
    loaded_start, loaded_end = _frame_bounds(recent_frame)
    has_older = len(recent_frame) < len(full_frame)
    return HistoryChunk(
        frame=recent_frame,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        requested_period=period,
        is_complete=not has_older,
        has_older=has_older,
        source_version=f"private-series:{spec.key}:recent",
    )


def get_private_series_full_history_backfill(
    spec: PrivateSeriesSpec,
    *,
    loaded_start: str | None = None,
) -> HistoryChunk:
    full_frame = get_private_series_frame(spec)
    if loaded_start:
        cutoff = pd.Timestamp(loaded_start)
        older = full_frame[pd.to_datetime(full_frame["time"], errors="coerce") < cutoff].reset_index(drop=True)
        older_frame = TimeSeriesDataFrame(older, name=full_frame.name, chart_meta=full_frame.chart_meta)
    else:
        older_frame = full_frame
    derived_start, derived_end = _frame_bounds(older_frame)
    return HistoryChunk(
        frame=older_frame,
        loaded_start=derived_start,
        loaded_end=derived_end,
        requested_period=None,
        is_complete=True,
        has_older=False,
        source_version=f"private-series:{spec.key}:full",
    )


def refresh_private_series_cache(spec: PrivateSeriesSpec) -> None:
    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    manager.refresh_payload(_history_source_name(spec), allow_stale=True)
    if spec.current_cache_namespace is not None and spec.current_deriver is not None:
        manager.refresh_payload(_current_source_name(spec), allow_stale=True)


def clear_private_series_cache(spec: PrivateSeriesSpec) -> None:
    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    manager.clear_payload(_history_source_name(spec))
    if spec.current_cache_namespace is not None:
        manager.clear_payload(_current_source_name(spec))


def _normalize_current(spec: PrivateSeriesSpec, payload: dict) -> dict:
    if spec.current_normalizer is not None:
        return spec.current_normalizer(payload)
    return dict(payload)


def _fetch_series_history_direct(
    spec: PrivateSeriesSpec,
    *,
    force_refresh: bool,
    client: PrivateAccessClient,
) -> list[dict]:
    if not force_refresh:
        cached = CacheManager.file_cache_read(spec.history_cache_namespace, spec.history_cache_key, spec.history_ttl)
        if isinstance(cached, list):
            return [dict(item) for item in spec.history_normalizer(cached)]

    try:
        normalized = spec.history_normalizer(spec.history_fetcher(client))
        if not normalized:
            raise ValueError(f"No {spec.display_name} history returned from private source.")
        CacheManager.file_cache_write(spec.history_cache_namespace, spec.history_cache_key, normalized)
        return [dict(item) for item in normalized]
    except Exception:
        stale = CacheManager.file_cache_read_stale(spec.history_cache_namespace, spec.history_cache_key)
        if isinstance(stale, list):
            return [dict(item) for item in spec.history_normalizer(stale)]
        raise


def _fetch_series_current_direct(
    spec: PrivateSeriesSpec,
    *,
    force_refresh: bool,
    client: PrivateAccessClient,
) -> dict:
    if not force_refresh:
        cached = CacheManager.file_cache_read(spec.current_cache_namespace, spec.current_cache_key, spec.current_ttl)
        if isinstance(cached, dict):
            return dict(_normalize_current(spec, cached))

    try:
        if spec.current_fetcher is None or spec.current_normalizer is None:
            raise RuntimeError(f"{spec.display_name} has no direct current fetcher.")
        current = spec.current_normalizer(spec.current_fetcher(client))
        history = _fetch_series_history_direct(spec, force_refresh=False, client=client)
        if history:
            current = _merge_history_context(spec, current, history)
        CacheManager.file_cache_write(spec.current_cache_namespace, spec.current_cache_key, current)
        return dict(current)
    except Exception:
        try:
            history = _fetch_series_history_direct(spec, force_refresh=force_refresh, client=client)
        except Exception:
            history = None
        if history:
            current = spec.current_deriver(history)
            CacheManager.file_cache_write(spec.current_cache_namespace, spec.current_cache_key, current)
            return dict(current)
        stale = CacheManager.file_cache_read_stale(spec.current_cache_namespace, spec.current_cache_key)
        if isinstance(stale, dict):
            return dict(_normalize_current(spec, stale))
        raise


def _history_source_name(spec: PrivateSeriesSpec) -> str:
    return f"private.series.{spec.key}.history"


def _current_source_name(spec: PrivateSeriesSpec) -> str:
    return f"private.series.{spec.key}.current"


def _ensure_series_sources_registered(manager: CacheManager, spec: PrivateSeriesSpec) -> None:
    manager.register_payload(
        CachePayloadSpec(
            source=_history_source_name(spec),
            namespace=spec.history_cache_namespace,
            key=spec.history_cache_key,
            ttl_seconds=spec.history_ttl,
            fetch_fn=lambda spec=spec: _fetch_series_history_runtime(spec),
        )
    )
    if spec.current_cache_namespace is not None and spec.current_deriver is not None:
        manager.register_payload(
            CachePayloadSpec(
                source=_current_source_name(spec),
                namespace=spec.current_cache_namespace,
                key=spec.current_cache_key,
                ttl_seconds=spec.current_ttl,
                fetch_fn=lambda spec=spec: _fetch_series_current_runtime(spec),
                fallback_fn=lambda spec=spec: dict(spec.current_deriver(get_private_series_history(spec))),
            )
        )


def _fetch_series_history_runtime(spec: PrivateSeriesSpec) -> list[dict]:
    active_client = PrivateAccessClient(load_private_access_config())
    normalized = spec.history_normalizer(spec.history_fetcher(active_client))
    if not normalized:
        raise ValueError(f"No {spec.display_name} history returned from private source.")
    return normalized


def _fetch_series_current_runtime(spec: PrivateSeriesSpec) -> dict:
    if spec.current_fetcher is None or spec.current_normalizer is None:
        raise RuntimeError(f"{spec.display_name} has no direct current fetcher.")
    active_client = PrivateAccessClient(load_private_access_config())
    current = spec.current_normalizer(spec.current_fetcher(active_client))
    history_result = get_cache_manager().get_payload(_history_source_name(spec), allow_stale=True)
    history = history_result.payload if isinstance(history_result.payload, list) else []
    if history:
        current = _merge_history_context(spec, current, history)
    return current


def _merge_history_context(spec: PrivateSeriesSpec, current: dict, history: list[dict]) -> dict:
    if spec.current_deriver is None:
        return dict(current)
    merged = dict(current)
    derived = spec.current_deriver(history)
    for field in ("previous_close", "previous_1_week", "previous_1_month"):
        if merged.get(field) is None and field in derived:
            merged[field] = derived.get(field)
    if not merged.get("timestamp"):
        merged["timestamp"] = derived.get("timestamp", "")
    if not merged.get("rating"):
        merged["rating"] = derived.get("rating", "Unavailable")
    return merged


def _frame_bounds(frame: TimeSeriesDataFrame) -> tuple[str | None, str | None]:
    if frame.empty or "time" not in frame.columns:
        return None, None
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return None, None
    return times.iloc[0].strftime("%Y-%m-%d"), times.iloc[-1].strftime("%Y-%m-%d")


def _period_offset(period: str) -> pd.DateOffset:
    text = period.strip().lower()
    if not text:
        raise ValueError("Period is required")
    unit = text[-1]
    amount = int(text[:-1] or "0")
    if amount <= 0:
        raise ValueError(f"Invalid period: {period}")
    if unit == "y":
        return pd.DateOffset(years=amount)
    if unit == "m":
        return pd.DateOffset(months=amount)
    if unit == "d":
        return pd.DateOffset(days=amount)
    raise ValueError(f"Unsupported period: {period}")


def _slice_recent_timeseries(frame: TimeSeriesDataFrame, period: str) -> TimeSeriesDataFrame:
    if frame.empty or "time" not in frame.columns:
        return TimeSeriesDataFrame.make_empty()
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return TimeSeriesDataFrame.make_empty()
    cutoff = (times.iloc[-1] - _period_offset(period)).normalize()
    recent = frame[pd.to_datetime(frame["time"], errors="coerce") >= cutoff].reset_index(drop=True)
    if recent.empty:
        recent = frame.tail(1).reset_index(drop=True)
    out = TimeSeriesDataFrame(recent, name=frame.name, chart_meta=frame.chart_meta)
    out.name = frame.name
    return out
