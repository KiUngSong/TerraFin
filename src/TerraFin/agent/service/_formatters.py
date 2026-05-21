"""Private helpers that bridge analytics/interface payloads into the
agent-facing service responses. Split out of ``service.py`` to keep the
``TerraFinAgentService`` body focused on capability methods. These helpers
are not part of the public API — they should only be imported by
``service.service``.
"""

from typing import Any

import pandas as pd

from TerraFin.analytics.analysis.technical import DEFAULT_MFD_WINDOWS
from TerraFin.data.contracts import TimeSeriesDataFrame
from TerraFin.interface.chart.chart_view import apply_view
from TerraFin.interface.chart.formatters import build_multi_payload
from TerraFin.interface.chart.indicators.adapter import (
    compute_bollinger_bands,
    compute_macd,
    compute_mandelbrot_fractal_dimension,
    compute_moving_averages,
    compute_range_volatility,
    compute_realized_volatility,
    compute_rsi,
    compute_trend_signal,
)

from ..contracts.schemas import ChartView, DepthMode, ProcessingMetadata


DEFAULT_RECENT_PERIOD = "3y"
VALID_DEPTHS = {"auto", "recent", "full"}
VALID_VIEWS = {"daily", "weekly", "monthly", "yearly"}


def _normalize_depth(depth: str | None) -> DepthMode:
    text = (depth or "auto").strip().lower()
    if text not in VALID_DEPTHS:
        raise ValueError(f"Unsupported depth: {depth}")
    return text  # type: ignore[return-value]


def _normalize_view(view: str | None) -> ChartView:
    text = (view or "daily").strip().lower()
    if text not in VALID_VIEWS:
        raise ValueError(f"Unsupported view: {view}")
    return text  # type: ignore[return-value]


def _frame_bounds(frame: TimeSeriesDataFrame) -> tuple[str | None, str | None]:
    if frame.empty or "time" not in frame.columns:
        return None, None
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return None, None
    return times.iloc[0].strftime("%Y-%m-%d"), times.iloc[-1].strftime("%Y-%m-%d")


def _full_processing(
    *,
    requested_depth: DepthMode,
    source_version: str,
    view: ChartView | None,
    frame: TimeSeriesDataFrame | None = None,
) -> dict[str, Any]:
    loaded_start, loaded_end = (None, None) if frame is None else _frame_bounds(frame)
    return ProcessingMetadata(
        requestedDepth=requested_depth,
        resolvedDepth="full",
        loadedStart=loaded_start,
        loadedEnd=loaded_end,
        isComplete=True,
        hasOlder=False,
        sourceVersion=source_version,
        view=view,
    ).model_dump()


def _chunk_processing(*, requested_depth: DepthMode, view: ChartView, history_chunk) -> dict[str, Any]:
    resolved_depth = "full" if history_chunk.is_complete else "recent"
    return ProcessingMetadata(
        requestedDepth=requested_depth,
        resolvedDepth=resolved_depth,
        loadedStart=history_chunk.loaded_start,
        loadedEnd=history_chunk.loaded_end,
        isComplete=history_chunk.is_complete,
        hasOlder=history_chunk.has_older,
        sourceVersion=history_chunk.source_version,
        view=view,
    ).model_dump()


def _primary_series(frame: TimeSeriesDataFrame, *, view: ChartView) -> dict[str, Any]:
    payload = build_multi_payload([frame])
    transformed = apply_view(payload, view)
    series = transformed.get("series", [])
    if not series:
        raise LookupError(f"No chartable data found for '{frame.name or 'series'}'.")
    return dict(series[0])


def _series_points(series: dict[str, Any]) -> list[dict[str, Any]]:
    points = series.get("data", [])
    return [dict(point) for point in points if isinstance(point, dict)]


def _series_closes(series: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for point in _series_points(series):
        if point.get("close") is not None:
            values.append(float(point["close"]))
        elif point.get("value") is not None:
            values.append(float(point["value"]))
    return values


def _indicator_input(series: dict[str, Any]) -> list[dict[str, Any]]:
    points = _series_points(series)
    if series.get("seriesType") == "candlestick":
        return points
    converted: list[dict[str, Any]] = []
    for point in points:
        value = point.get("value")
        if value is None:
            continue
        converted.append({"time": point.get("time"), "close": float(value)})
    return converted


def _offset_for(base_points: list[dict[str, Any]], values: list[dict[str, Any]]) -> int:
    return max(len(base_points) - len(values), 0)


def _line_values(series: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for point in series.get("data", []):
        if isinstance(point, dict) and point.get("value") is not None:
            values.append(float(point["value"]))
    return values


def _compute_indicator_results(
    series: dict[str, Any], requested: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    input_points = _indicator_input(series)
    base_points = _series_points(series)
    results: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []

    ma_map = {}
    for overlay in compute_moving_averages(input_points):
        indicator_id = str(overlay.get("id", ""))
        if indicator_id.startswith("MA "):
            ma_map[f"sma_{indicator_id.split(' ', 1)[1]}"] = overlay

    cache: dict[str, list[dict[str, Any]]] = {
        "rsi": compute_rsi(input_points),
        "bb": compute_bollinger_bands(input_points),
        "macd": compute_macd(input_points),
        "realized_vol": compute_realized_volatility(input_points),
        "range_vol": compute_range_volatility(input_points),
        "trend_signal": compute_trend_signal(input_points),
        "mfd": compute_mandelbrot_fractal_dimension(input_points, windows=DEFAULT_MFD_WINDOWS),
    }
    mfd_map = {}
    for overlay in cache["mfd"]:
        indicator_id = str(overlay.get("id", ""))
        if indicator_id.startswith("MFD "):
            mfd_map[f"mfd_{indicator_id.split(' ', 1)[1]}"] = overlay

    for name in requested:
        if name in ma_map:
            overlay = ma_map[name]
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {
                    "value": values[-1] if values else None,
                    "series": values,
                },
            }
            continue

        if name == "rsi":
            overlays = cache["rsi"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "bb":
            overlays = cache["bb"]
            upper = overlays[0] if len(overlays) > 0 else {"data": []}
            lower = overlays[1] if len(overlays) > 1 else {"data": []}
            upper_values = _line_values(upper)
            lower_values = _line_values(lower)
            latest_close = _series_closes(series)
            position = None
            if latest_close and upper_values and lower_values:
                midpoint = (upper_values[-1] + lower_values[-1]) / 2
                if latest_close[-1] > midpoint:
                    position = "upper"
                elif latest_close[-1] < midpoint:
                    position = "lower"
                else:
                    position = "middle"
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, upper.get("data", [])),
                "values": {
                    "position": position,
                    "upper": upper_values,
                    "lower": lower_values,
                },
            }
            continue

        if name == "macd":
            overlays = cache["macd"]
            histogram = next(
                (overlay for overlay in overlays if overlay.get("seriesType") == "histogram"), {"data": []}
            )
            macd_line = next((overlay for overlay in overlays if overlay.get("id") == "MACD"), {"data": []})
            signal_line = next((overlay for overlay in overlays if overlay.get("id") == "Signal"), {"data": []})
            hist_values = _line_values(histogram)
            last_hist = hist_values[-1] if hist_values else 0.0
            signal_label = "bullish" if last_hist > 0 else "bearish" if last_hist < 0 else "neutral"
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, macd_line.get("data", [])),
                "values": {
                    "signal": signal_label if hist_values else None,
                    "histogram_value": last_hist if hist_values else None,
                    "series": {
                        "macd": _line_values(macd_line),
                        "signal": _line_values(signal_line),
                        "histogram": hist_values,
                    },
                },
            }
            continue

        if name == "realized_vol":
            overlays = cache["realized_vol"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "range_vol":
            overlays = cache["range_vol"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name == "trend_signal":
            overlays = cache["trend_signal"]
            overlay = overlays[0] if overlays else {"data": []}
            values = _line_values(overlay)
            results[name] = {
                "name": name,
                "offset": _offset_for(base_points, overlay.get("data", [])),
                "values": {"value": values[-1] if values else None, "series": values},
            }
            continue

        if name in {"mfd", "mfd_65", "mfd_130", "mfd_260"}:
            if name == "mfd":
                latest: dict[str, float | None] = {}
                series_map: dict[str, list[float]] = {}
                offsets: dict[str, int] = {}
                for key in ("mfd_65", "mfd_130", "mfd_260"):
                    overlay = mfd_map.get(key, {"data": []})
                    values = _line_values(overlay)
                    window = key.split("_", 1)[1]
                    latest[window] = values[-1] if values else None
                    series_map[window] = values
                    offsets[window] = (
                        _offset_for(base_points, overlay.get("data", [])) if overlay.get("data") else int(window)
                    )
                results[name] = {
                    "name": name,
                    "offset": min(offsets.values()),
                    "values": {
                        "latest": latest,
                        "series": series_map,
                        "offsets": offsets,
                    },
                }
            else:
                overlay = mfd_map.get(name, {"data": []})
                values = _line_values(overlay)
                window = int(name.split("_", 1)[1])
                results[name] = {
                    "name": name,
                    "offset": _offset_for(base_points, overlay.get("data", [])) if overlay.get("data") else window,
                    "values": {"value": values[-1] if values else None, "series": values},
                }
            continue

        unknown.append(name)

    return results, unknown


def _price_action(series: dict[str, Any]) -> dict[str, float | None]:
    closes = _series_closes(series)
    current = closes[-1] if closes else None
    change_1d = round(((closes[-1] / closes[-2]) - 1) * 100, 2) if len(closes) >= 2 else None
    change_5d = round(((closes[-1] / closes[-6]) - 1) * 100, 2) if len(closes) >= 6 else None
    return {"current": current, "change_1d": change_1d, "change_5d": change_5d}


def _calendar_processing() -> dict[str, Any]:
    return _full_processing(requested_depth="full", source_version="calendar", view=None, frame=None)
