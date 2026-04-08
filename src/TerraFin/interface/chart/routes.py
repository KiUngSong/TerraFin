import hashlib
import uuid
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.interface.chart.chart_view import apply_view
from TerraFin.interface.chart.formatters import (
    build_multi_payload_from_items,
    build_source_payload,
    build_source_payload_from_items,
    format_series_item,
)
from TerraFin.interface.chart.indicators import (
    compute_bollinger_bands,
    compute_macd,
    compute_mandelbrot_fractal_dimension,
    compute_moving_averages,
    compute_range_volatility,
    compute_realized_volatility,
    compute_rsi,
    compute_trend_signal,
)
from TerraFin.interface.chart.state import (
    add_named_series,
    clear_named_series,
    clear_pinned_names,
    clear_series_history,
    get_chart_payload,
    get_chart_selection,
    get_chart_source,
    get_chart_view,
    get_indicator_overlays,
    get_named_series,
    get_named_series_items,
    get_pinned_names,
    get_series_history_by_name,
    get_series_history_status,
    get_series_names,
    remove_named_series,
    remove_series_history_status,
    set_chart_payload,
    set_chart_selection,
    set_chart_source,
    set_chart_view,
    set_indicator_overlays,
    set_pinned_names,
    set_series_history_status,
)


MAX_CHART_SERIES = 5


CHART_PATH = "/chart"
CHART_API_PATH = f"{CHART_PATH}/api"


def _session_id(request: Request) -> str:
    return request.headers.get("X-Session-ID", "default")


class ChartDataResponse(BaseModel):
    mode: str = "multi"
    series: list[dict] = Field(default_factory=list)
    dataLength: int
    forcePercentage: bool = False
    entries: list[dict] = Field(default_factory=list)
    historyBySeries: dict[str, dict] = Field(default_factory=dict)


class OkResponse(BaseModel):
    ok: bool


class ChartDataWriteResponse(BaseModel):
    ok: bool
    dataLength: int
    mode: str = "multi"
    series: list[dict] = Field(default_factory=list)
    forcePercentage: bool = False
    entries: list[dict] = Field(default_factory=list)
    historyBySeries: dict[str, dict] = Field(default_factory=dict)


class ChartViewWriteResponse(BaseModel):
    ok: bool
    view: str
    dataLength: int
    mode: str = "multi"
    series: list[dict] = Field(default_factory=list)
    forcePercentage: bool = False
    entries: list[dict] = Field(default_factory=list)
    historyBySeries: dict[str, dict] = Field(default_factory=dict)


class LinePoint(BaseModel):
    time: str
    value: float


class CandlestickPoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float


class ChartSeries(BaseModel):
    id: str
    seriesType: Literal["line", "candlestick", "histogram"]
    color: str | None = None
    data: list[LinePoint | CandlestickPoint] = Field(default_factory=list)
    priceScaleId: str | None = None
    returnSeries: bool = False
    indicator: bool = False
    indicatorGroup: str | None = None
    lineStyle: str | None = None
    priceLevels: list[dict] | None = None
    zones: list[dict] | None = None


class MultiChartPayload(BaseModel):
    mode: Literal["multi"]
    series: list[ChartSeries] = Field(default_factory=list)
    dataLength: int | None = None
    forcePercentage: bool = False
    pinned: bool = False


def _indicator_cache_key(payload: dict) -> str:
    parts = [payload.get("mode", "multi"), "pct" if payload.get("forcePercentage", False) else "abs"]
    for series in payload.get("series", []):
        if not isinstance(series, dict):
            continue
        data = series.get("data", [])
        first = data[0] if data else {}
        middle = data[len(data) // 2] if data else {}
        last = data[-1] if data else {}
        parts.extend(
            [
                str(series.get("id", "")),
                str(series.get("seriesType", "")),
                str(series.get("priceScaleId", "")),
                "1" if series.get("returnSeries") else "0",
                str(len(data)),
                str(first.get("time", "")),
                str(middle.get("time", "")),
                str(last.get("time", "")),
                str(first.get("close", first.get("value", ""))),
                str(middle.get("close", middle.get("value", ""))),
                str(last.get("close", last.get("value", ""))),
            ]
        )
    encoded = "|".join(parts)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _add_indicators(payload: dict) -> dict:
    """Add indicator overlays if the payload has a single candlestick."""
    series = payload.get("series", [])
    n_candle = sum(1 for s in series if isinstance(s, dict) and s.get("seriesType") == "candlestick")
    if n_candle != 1:
        return payload
    cache_key = _indicator_cache_key(payload)
    indicators = get_indicator_overlays(cache_key)
    if indicators is None:
        candle = next(s for s in series if s.get("seriesType") == "candlestick")
        data = candle.get("data", [])
        indicators = []
        indicators.extend(compute_moving_averages(data))
        indicators.extend(compute_bollinger_bands(data))
        indicators.extend(compute_rsi(data))
        indicators.extend(compute_macd(data))
        indicators.extend(compute_realized_volatility(data))
        indicators.extend(compute_range_volatility(data))
        indicators.extend(compute_trend_signal(data))
        indicators.extend(compute_mandelbrot_fractal_dimension(data))
        set_indicator_overlays(cache_key, indicators)
    result = dict(payload)
    result["series"] = list(series) + indicators
    return result


def _payload_length(payload: dict) -> int:
    series = payload.get("series", [])
    if not isinstance(series, list):
        return 0
    return sum(len(item.get("data", [])) for item in series if isinstance(item, dict))


def _series_entries(payload: dict, pinned: set[str]) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("series", []):
        if not isinstance(item, dict) or item.get("indicator") or not item.get("id"):
            continue
        name = item["id"]
        if name in seen:
            continue
        seen.add(name)
        entries.append({"name": name, "pinned": name in pinned})
    return entries


def _chart_response(payload: dict, sid: str) -> dict:
    return {
        "mode": payload.get("mode", "multi"),
        "series": payload.get("series", []),
        "dataLength": _payload_length(payload),
        "forcePercentage": payload.get("forcePercentage", False),
        "entries": _series_entries(payload, get_pinned_names(sid)),
        "historyBySeries": _history_by_series_response(sid),
    }


def _history_by_series_response(sid: str) -> dict[str, dict]:
    history = get_series_history_by_name(sid)
    return {name: dict(status) for name, status in history.items()}


def _series_history_payload(
    *,
    loaded_start: str | None,
    loaded_end: str | None,
    is_complete: bool,
    has_older: bool,
    seed_period: str | None,
    request_token: str,
    backfill_in_flight: bool,
) -> dict:
    return {
        "loadedStart": loaded_start,
        "loadedEnd": loaded_end,
        "isComplete": is_complete,
        "hasOlder": has_older,
        "seedPeriod": seed_period,
        "backfillInFlight": backfill_in_flight,
        "requestToken": request_token,
    }


def _set_history_from_chunk(
    name: str,
    sid: str,
    *,
    loaded_start: str | None,
    loaded_end: str | None,
    is_complete: bool,
    has_older: bool,
    seed_period: str | None,
    request_token: str | None = None,
    backfill_in_flight: bool | None = None,
) -> str:
    display_name = _display_name(name)
    token = request_token or uuid.uuid4().hex
    set_series_history_status(
        display_name,
        _series_history_payload(
            loaded_start=loaded_start,
            loaded_end=loaded_end,
            is_complete=is_complete,
            has_older=has_older,
            seed_period=seed_period,
            request_token=token,
            backfill_in_flight=has_older if backfill_in_flight is None else backfill_in_flight,
        ),
        sid,
    )
    return token


def _series_time_bounds(item: dict) -> tuple[str | None, str | None]:
    data = item.get("data", [])
    times = [point.get("time") for point in data if isinstance(point, dict) and isinstance(point.get("time"), str)]
    if not times:
        return None, None
    return times[0], times[-1]


def _frame_from_series_item(item: dict) -> TimeSeriesDataFrame | None:
    if not isinstance(item, dict) or item.get("indicator") or not item.get("id"):
        return None
    data = item.get("data", [])
    if not isinstance(data, list):
        return None
    series_type = item.get("seriesType")
    frame_data: list[dict] = []
    if series_type == "candlestick":
        frame_data = [
            {
                "time": point.get("time"),
                "open": point.get("open"),
                "high": point.get("high"),
                "low": point.get("low"),
                "close": point.get("close"),
            }
            for point in data
            if isinstance(point, dict)
        ]
    elif series_type in {"line", "histogram"}:
        frame_data = [
            {
                "time": point.get("time"),
                "close": point.get("value"),
            }
            for point in data
            if isinstance(point, dict)
        ]
    else:
        return None
    frame = TimeSeriesDataFrame(pd.DataFrame(frame_data))
    frame.name = _display_name(str(item.get("id")))
    return frame


def _initialize_complete_history_from_source(source: dict, sid: str) -> None:
    clear_named_series(sid)
    clear_series_history(sid)
    for item in source.get("series", []):
        if not isinstance(item, dict) or item.get("indicator") or not item.get("id"):
            continue
        display_name = _display_name(str(item["id"]))
        frame = _frame_from_series_item(item)
        if frame is not None:
            add_named_series(display_name, frame, sid, formatted_item=dict(item))
        loaded_start, loaded_end = _series_time_bounds(item)
        set_series_history_status(
            display_name,
            _series_history_payload(
                loaded_start=loaded_start,
                loaded_end=loaded_end,
                is_complete=True,
                has_older=False,
                seed_period=None,
                request_token=uuid.uuid4().hex,
                backfill_in_flight=False,
            ),
            sid,
        )


def _render_source_payload(source: dict, sid: str) -> dict:
    set_chart_source(source, sid)
    view = get_chart_view(sid)
    transformed = apply_view(source, view)
    if _payload_needs_layout(transformed):
        transformed = build_multi_payload_from_items(transformed.get("series", []))
    display = _add_indicators(transformed)
    set_chart_payload(display, sid)
    return display


def _display_name(name: str) -> str:
    return name.upper() if name == name.lower() else name


def _payload_needs_layout(payload: dict) -> bool:
    series = payload.get("series", [])
    if not isinstance(series, list) or not series:
        return False
    for item in series:
        if not isinstance(item, dict):
            return False
        if item.get("indicator"):
            return False
        if item.get("priceScaleId") is not None:
            return False
        if item.get("returnSeries"):
            return False
    return True


def _series_data_signature(item: dict) -> tuple:
    data = item.get("data", [])
    first = data[0] if data else {}
    middle = data[len(data) // 2] if data else {}
    last = data[-1] if data else {}
    return (
        len(data),
        first.get("time"),
        middle.get("time"),
        last.get("time"),
        first.get("open", first.get("value")),
        middle.get("close", middle.get("value")),
        last.get("close", last.get("value")),
    )


def _series_signature(item: dict) -> tuple:
    return (
        item.get("id"),
        item.get("seriesType"),
        item.get("color"),
        item.get("priceScaleId"),
        item.get("returnSeries", False),
        item.get("indicator", False),
        item.get("indicatorGroup"),
        item.get("lineStyle"),
        tuple(
            (
                level.get("price"),
                level.get("color"),
                level.get("title"),
            )
            for level in item.get("priceLevels", []) or []
            if isinstance(level, dict)
        ),
        tuple(
            (
                zone.get("from"),
                zone.get("to"),
                zone.get("color"),
            )
            for zone in item.get("zones", []) or []
            if isinstance(zone, dict)
        ),
        _series_data_signature(item),
    )


def _mutation_response(before_payload: dict, after_payload: dict, sid: str) -> dict:
    before_map = {
        item["id"]: item for item in before_payload.get("series", []) if isinstance(item, dict) and item.get("id")
    }
    after_map = {
        item["id"]: item for item in after_payload.get("series", []) if isinstance(item, dict) and item.get("id")
    }
    series_order = [
        item["id"] for item in after_payload.get("series", []) if isinstance(item, dict) and item.get("id")
    ]
    upsert_ids = [
        series_id
        for series_id in series_order
        if series_id in before_map
        if _series_signature(after_map[series_id]) != _series_signature(before_map[series_id])
    ]
    upsert_ids.extend(series_id for series_id in series_order if series_id not in before_map)
    removed_ids = [series_id for series_id in before_map if series_id not in after_map]
    return {
        "mode": after_payload.get("mode", "multi"),
        "upsertSeries": [after_map[series_id] for series_id in series_order if series_id in set(upsert_ids)],
        "removedSeriesIds": removed_ids,
        "seriesOrder": series_order,
        "dataLength": _payload_length(after_payload),
        "forcePercentage": after_payload.get("forcePercentage", False),
        "entries": _series_entries(after_payload, get_pinned_names(sid)),
    }


def _rebuild_from_named_series(sid: str) -> dict:
    """Rebuild source + payload from all named series."""
    named = get_named_series(sid)
    if not named:
        source = {"mode": "multi", "series": [], "dataLength": 0}
        set_chart_source(source, sid)
        set_chart_payload(source, sid)
        return source
    named_items = get_named_series_items(sid)
    ordered_names = get_series_names(sid)
    if len(named_items) == len(named):
        source = build_source_payload_from_items([named_items[name] for name in ordered_names if name in named_items])
    else:
        frames = [named[name] for name in ordered_names]
        source = build_source_payload(frames)
    return _render_source_payload(source, sid)


def seed_single_series_chart(name: str, df: TimeSeriesDataFrame, sid: str, *, pinned: bool = False) -> dict:
    clear_named_series(sid)
    clear_pinned_names(sid)
    clear_series_history(sid)
    display_name = _display_name(name)
    df.name = display_name
    formatted_item = format_series_item(df, default_id=display_name)
    add_named_series(display_name, df, sid, formatted_item=formatted_item)
    display = _rebuild_from_named_series(sid)
    if pinned:
        set_pinned_names({display_name}, sid)
    return _chart_response(display, sid)


def add_single_series_chart(
    name: str, df: TimeSeriesDataFrame, sid: str, *, pinned: bool = False
) -> tuple[dict, bool]:
    display_name = _display_name(name)
    names = get_series_names(sid)
    if display_name in names:
        return _chart_response(get_chart_payload(sid), sid), False
    if len(names) >= MAX_CHART_SERIES:
        raise ValueError(f"Maximum {MAX_CHART_SERIES} charts")
    df.name = display_name
    formatted_item = format_series_item(df, default_id=display_name)
    add_named_series(display_name, df, sid, formatted_item=formatted_item)
    display = _rebuild_from_named_series(sid)
    if pinned:
        set_pinned_names(get_pinned_names(sid) | {display_name}, sid)
    return _chart_response(display, sid), True


def remove_single_series_chart(name: str, sid: str) -> dict:
    display_name = _display_name(name)

    # If named series is empty but payload has data (from update_chart),
    # adopt current source series into named series so we can rebuild without the removed one.
    if not get_series_names(sid):
        source = get_chart_source(sid)
        for s in source.get("series", []):
            if isinstance(s, dict) and not s.get("indicator") and s.get("id"):
                series_id = s["id"]
                try:
                    from TerraFin.data import DataFactory

                    df = DataFactory().get(series_id)
                    df.name = series_id
                    formatted_item = format_series_item(df, default_id=series_id)
                    add_named_series(series_id, df, sid, formatted_item=formatted_item)
                except Exception:
                    pass

    remove_named_series(display_name, sid)
    remove_series_history_status(display_name, sid)
    set_pinned_names({pinned_name for pinned_name in get_pinned_names(sid) if pinned_name != display_name}, sid)
    display = _rebuild_from_named_series(sid)
    return _chart_response(display, sid)


def _combine_series_history(
    current_df: TimeSeriesDataFrame, older_df: TimeSeriesDataFrame, display_name: str
) -> TimeSeriesDataFrame:
    if older_df.empty:
        current_df.name = display_name
        return current_df
    chart_meta = current_df.chart_meta or older_df.chart_meta
    combined = TimeSeriesDataFrame(
        pd.concat([pd.DataFrame(older_df), pd.DataFrame(current_df)], ignore_index=True),
        name=display_name,
        chart_meta=chart_meta,
    )
    combined.name = display_name
    return combined


def seed_single_series_chart_progressive(
    name: str,
    df: TimeSeriesDataFrame,
    sid: str,
    *,
    pinned: bool = False,
    seed_period: str = "3y",
    loaded_start: str | None = None,
    loaded_end: str | None = None,
    is_complete: bool = False,
    has_older: bool = True,
) -> tuple[dict, str]:
    snapshot = seed_single_series_chart(name, df, sid, pinned=pinned)
    token = _set_history_from_chunk(
        name,
        sid,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        is_complete=is_complete,
        has_older=has_older,
        seed_period=seed_period,
    )
    return snapshot, token


def add_single_series_chart_progressive(
    name: str,
    df: TimeSeriesDataFrame,
    sid: str,
    *,
    pinned: bool = False,
    seed_period: str = "3y",
    loaded_start: str | None = None,
    loaded_end: str | None = None,
    is_complete: bool = False,
    has_older: bool = True,
) -> tuple[dict, bool, str | None]:
    snapshot, added = add_single_series_chart(name, df, sid, pinned=pinned)
    if not added:
        return snapshot, False, None
    token = _set_history_from_chunk(
        name,
        sid,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        is_complete=is_complete,
        has_older=has_older,
        seed_period=seed_period,
    )
    return snapshot, True, token


def create_chart_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(f"{CHART_API_PATH}/chart-data", response_model=ChartDataResponse)
    def api_get_chart_data(request: Request):
        sid = _session_id(request)
        payload = get_chart_payload(sid)
        return _chart_response(payload, sid)

    @router.post(f"{CHART_API_PATH}/chart-data", response_model=ChartDataWriteResponse)
    def api_post_chart_data(request: Request, body: MultiChartPayload = Body(...)):
        sid = _session_id(request)
        is_pinned = body.pinned
        payload_dict = body.model_dump()
        source = build_source_payload_from_items(payload_dict.get("series", []))
        _initialize_complete_history_from_source(source, sid)
        set_chart_view("daily", sid)
        display = _render_source_payload(source, sid)
        # Set pinned names if requested
        if is_pinned:
            pinned = {s["id"] for s in source.get("series", []) if isinstance(s, dict) and s.get("id")}
            set_pinned_names(pinned, sid)
        else:
            clear_pinned_names(sid)
        return {"ok": True, **_chart_response(display, sid)}

    @router.post(f"{CHART_API_PATH}/chart-view", response_model=ChartViewWriteResponse)
    def api_post_chart_view(request: Request, body: dict = Body(...)):
        sid = _session_id(request)
        view = (body.get("view") or "daily").lower()
        set_chart_view(view, sid)
        transformed = apply_view(get_chart_source(sid), view)
        display = _add_indicators(transformed)
        set_chart_payload(display, sid)
        return {"ok": True, "view": view, **_chart_response(display, sid)}

    @router.get(f"{CHART_API_PATH}/chart-selection", response_model=dict | None)
    def api_get_chart_selection(request: Request):
        return get_chart_selection(_session_id(request))

    @router.post(f"{CHART_API_PATH}/chart-selection", response_model=OkResponse)
    def api_post_chart_selection(request: Request, body: dict = Body(...)):
        set_chart_selection(body, _session_id(request))
        return {"ok": True}

    # ── Interactive series management ────────────────────────────────────

    @router.post(f"{CHART_API_PATH}/chart-series/add")
    def api_add_series(request: Request, body: dict = Body(...)):
        sid = _session_id(request)
        name = (body.get("name") or "").strip()
        pinned = body.get("pinned", False)
        if not name:
            return {
                "ok": False,
                "error": "Name is required",
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        names = get_series_names(sid)
        display_name = _display_name(name)
        if display_name in names:
            return {
                "ok": False,
                "error": "Already added",
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        if len(names) >= MAX_CHART_SERIES:
            return {
                "ok": False,
                "error": f"Maximum {MAX_CHART_SERIES} charts",
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        before_payload = get_chart_payload(sid)
        try:
            from TerraFin.data import DataFactory

            history_chunk = DataFactory().get_recent_history(name, period="3y")
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        try:
            _, added, request_token = add_single_series_chart_progressive(
                name,
                history_chunk.frame,
                sid,
                pinned=pinned,
                seed_period="3y",
                loaded_start=history_chunk.loaded_start,
                loaded_end=history_chunk.loaded_end,
                is_complete=history_chunk.is_complete,
                has_older=history_chunk.has_older,
            )
        except ValueError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        if not added:
            return {
                "ok": False,
                "error": "Already added",
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        after_payload = get_chart_payload(sid)
        return {
            "ok": True,
            "names": get_series_names(sid),
            "requestToken": request_token,
            "historyBySeries": _history_by_series_response(sid),
            "mutation": _mutation_response(before_payload, after_payload, sid),
        }

    @router.post(f"{CHART_API_PATH}/chart-series/set")
    def api_set_series(request: Request, body: dict = Body(...)):
        """Clear all series, load a single ticker, and pin it."""
        sid = _session_id(request)
        name = (body.get("name") or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "Name is required",
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        pinned = body.get("pinned", False)
        clear_named_series(sid)
        clear_pinned_names(sid)
        clear_series_history(sid)
        set_chart_view("daily", sid)
        try:
            from TerraFin.data import DataFactory

            history_chunk = DataFactory().get_recent_history(name, period="3y")
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "historyBySeries": _history_by_series_response(sid),
                **_chart_response(get_chart_payload(sid), sid),
            }
        snapshot, request_token = seed_single_series_chart_progressive(
            name,
            history_chunk.frame,
            sid,
            pinned=pinned,
            seed_period="3y",
            loaded_start=history_chunk.loaded_start,
            loaded_end=history_chunk.loaded_end,
            is_complete=history_chunk.is_complete,
            has_older=history_chunk.has_older,
        )
        return {
            "ok": True,
            "names": get_series_names(sid),
            "requestToken": request_token,
            **snapshot,
            "historyBySeries": _history_by_series_response(sid),
        }

    @router.post(f"{CHART_API_PATH}/chart-series/progressive/set")
    def api_set_series_progressive(request: Request, body: dict = Body(...)):
        sid = _session_id(request)
        name = (body.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Name is required", **_chart_response(get_chart_payload(sid), sid)}
        pinned = body.get("pinned", False)
        seed_period = (body.get("seedPeriod") or "3y").strip().lower()
        clear_named_series(sid)
        clear_pinned_names(sid)
        clear_series_history(sid)
        set_chart_view("daily", sid)
        try:
            from TerraFin.data import DataFactory

            history_chunk = DataFactory().get_recent_history(name, period=seed_period)
        except Exception as exc:
            return {"ok": False, "error": str(exc), **_chart_response(get_chart_payload(sid), sid)}

        snapshot, request_token = seed_single_series_chart_progressive(
            name,
            history_chunk.frame,
            sid,
            pinned=pinned,
            seed_period=seed_period,
            loaded_start=history_chunk.loaded_start,
            loaded_end=history_chunk.loaded_end,
            is_complete=history_chunk.is_complete,
            has_older=history_chunk.has_older,
        )
        return {
            "ok": True,
            "names": get_series_names(sid),
            "requestToken": request_token,
            **snapshot,
            "historyBySeries": _history_by_series_response(sid),
        }

    @router.post(f"{CHART_API_PATH}/chart-series/progressive/backfill")
    def api_backfill_series_progressive(request: Request, body: dict = Body(...)):
        sid = _session_id(request)
        name = (body.get("name") or "").strip()
        request_token = (body.get("requestToken") or "").strip()
        if not name:
            return {"ok": False, "error": "Name is required"}
        display_name = _display_name(name)
        status = get_series_history_status(display_name, sid)
        if status is None:
            return {"ok": False, "error": "Progressive history not initialized"}
        if request_token != status.get("requestToken"):
            return {"ok": False, "stale": True, "historyBySeries": _history_by_series_response(sid)}
        if status.get("isComplete") or not status.get("hasOlder"):
            next_status = dict(status)
            next_status["backfillInFlight"] = False
            set_series_history_status(display_name, next_status, sid)
            return {
                "ok": True,
                "mutation": None,
                "requestToken": request_token,
                "historyBySeries": _history_by_series_response(sid),
            }

        current_named = get_named_series(sid).get(display_name)
        if current_named is None:
            return {"ok": False, "error": "Series state was lost"}

        before_payload = get_chart_payload(sid)
        try:
            from TerraFin.data import DataFactory

            history_chunk = DataFactory().get_full_history_backfill(name, loaded_start=status.get("loadedStart"))
        except Exception as exc:
            return {"ok": False, "error": str(exc), "requestToken": request_token}

        combined = _combine_series_history(current_named, history_chunk.frame, display_name)
        formatted_item = format_series_item(combined, default_id=display_name)
        add_named_series(display_name, combined, sid, formatted_item=formatted_item)
        set_series_history_status(
            display_name,
            _series_history_payload(
                loaded_start=history_chunk.loaded_start,
                loaded_end=history_chunk.loaded_end,
                is_complete=history_chunk.is_complete,
                has_older=history_chunk.has_older,
                seed_period=status.get("seedPeriod"),
                request_token=request_token,
                backfill_in_flight=False,
            ),
            sid,
        )
        after_payload = _rebuild_from_named_series(sid)
        return {
            "ok": True,
            "mutation": _mutation_response(before_payload, after_payload, sid),
            "requestToken": request_token,
            "historyBySeries": _history_by_series_response(sid),
        }

    @router.post(f"{CHART_API_PATH}/chart-series/remove")
    def api_remove_series(request: Request, body: dict = Body(...)):
        sid = _session_id(request)
        name = (body.get("name") or "").strip()
        before_payload = get_chart_payload(sid)
        remove_single_series_chart(name, sid)
        after_payload = get_chart_payload(sid)
        return {
            "ok": True,
            "mutation": _mutation_response(before_payload, after_payload, sid),
            "historyBySeries": _history_by_series_response(sid),
        }

    @router.get(f"{CHART_API_PATH}/chart-series/names")
    def api_get_series_names(request: Request):
        sid = _session_id(request)
        payload = get_chart_payload(sid)
        return {"entries": _series_entries(payload, get_pinned_names(sid))}

    @router.get(f"{CHART_API_PATH}/chart-series/search")
    def api_search_series(request: Request, q: str = ""):
        q = q.strip().lower()
        if not q:
            return {"suggestions": []}
        from TerraFin.data.providers.economic import indicator_registry
        from TerraFin.data.providers.market import INDEX_MAP, MARKET_INDICATOR_REGISTRY

        all_names: list[str] = []
        all_names.extend(MARKET_INDICATOR_REGISTRY.keys())
        all_names.extend(INDEX_MAP.keys())
        all_names.extend(indicator_registry._indicators.keys())
        matches = [n for n in all_names if q in n.lower()]
        return {"suggestions": matches[:10]}

    @router.get(CHART_PATH)
    @router.get(f"{CHART_PATH}/")
    def chart_index():
        html = (build_dir / "index.html").read_text()
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    return router
