from dataclasses import dataclass

import pandas as pd

from TerraFin.data.cache.manager import CacheManager, CachePayloadSpec
from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.contracts import HistoryChunk, IndicatorSnapshot
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from .client import PrivateAccessClient
from .config import load_private_access_config


@dataclass(frozen=True)
class PrivateSeriesSpec:
    key: str
    display_name: str
    history_cache_namespace: str
    current_cache_namespace: str | None = None
    history_cache_key: str = "history"
    current_cache_key: str = "current"


def _build_frame(records: list[dict], display_name: str) -> TimeSeriesDataFrame:
    if records:
        df = pd.DataFrame(records)
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates(subset=["time"], keep="last")
        df["time"] = df["time"].dt.strftime("%Y-%m-%d")
        frame = TimeSeriesDataFrame(df.reset_index(drop=True), name=display_name)
    else:
        frame = TimeSeriesDataFrame(pd.DataFrame(columns=["time", "close"]), name=display_name)
    frame.name = display_name
    return frame


def _snapshot_from_payload(payload: dict, spec: PrivateSeriesSpec) -> IndicatorSnapshot:
    value = payload.get("value")
    return IndicatorSnapshot(
        name=payload.get("name") or spec.display_name,
        value=value if value is not None else "",
        as_of=str(payload.get("as_of") or ""),
        unit=payload.get("unit"),
        change=payload.get("change"),
        change_pct=payload.get("change_pct"),
        rating=payload.get("rating"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _history_records(spec: PrivateSeriesSpec, *, force_refresh: bool = False) -> list[dict]:
    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    result = manager.get_payload(_history_source_name(spec), force_refresh=force_refresh, allow_stale=True)
    payload = result.payload
    return [dict(item) for item in payload] if isinstance(payload, list) else []


def _current_payload(spec: PrivateSeriesSpec, *, force_refresh: bool = False) -> dict:
    if spec.current_cache_namespace is None:
        raise RuntimeError(f"{spec.display_name} does not define a current snapshot contract.")

    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    result = manager.get_payload(_current_source_name(spec), force_refresh=force_refresh, allow_stale=True)
    payload = result.payload
    return dict(payload) if isinstance(payload, dict) else {}


def get_private_series_history(spec: PrivateSeriesSpec, *, force_refresh: bool = False) -> TimeSeriesDataFrame:
    records = _history_records(spec, force_refresh=force_refresh)
    return _build_frame(records, spec.display_name)


def get_private_series_current(spec: PrivateSeriesSpec, *, force_refresh: bool = False) -> IndicatorSnapshot:
    payload = _current_payload(spec, force_refresh=force_refresh)
    return _snapshot_from_payload(payload, spec)


def get_private_series_frame(spec: PrivateSeriesSpec) -> TimeSeriesDataFrame:
    return get_private_series_history(spec)


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
    if spec.current_cache_namespace is not None:
        manager.refresh_payload(_current_source_name(spec), allow_stale=True)


def clear_private_series_cache(spec: PrivateSeriesSpec) -> None:
    manager = get_cache_manager()
    _ensure_series_sources_registered(manager, spec)
    manager.clear_payload(_history_source_name(spec))
    if spec.current_cache_namespace is not None:
        manager.clear_payload(_current_source_name(spec))


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
            ttl_seconds=ttl_for("private.series.history"),
            fetch_fn=lambda spec=spec: _fetch_series_history_runtime(spec),
        )
    )
    if spec.current_cache_namespace is not None:
        manager.register_payload(
            CachePayloadSpec(
                source=_current_source_name(spec),
                namespace=spec.current_cache_namespace,
                key=spec.current_cache_key,
                ttl_seconds=ttl_for("private.series.current"),
                fetch_fn=lambda spec=spec: _fetch_series_current_runtime(spec),
            )
        )


def _fetch_series_history_runtime(spec: PrivateSeriesSpec) -> list[dict]:
    active_client = PrivateAccessClient(load_private_access_config())
    records = list(active_client.fetch_series_history(spec.key))
    if not records:
        raise ValueError(f"No {spec.display_name} history returned from private source.")
    return records


def _fetch_series_current_runtime(spec: PrivateSeriesSpec) -> dict:
    active_client = PrivateAccessClient(load_private_access_config())
    return dict(active_client.fetch_series_current(spec.key))


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
