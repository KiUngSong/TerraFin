import pandas as pd

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


def _serialize_zones(df: TimeSeriesDataFrame) -> list[dict] | None:
    raw_zones = None
    chart_meta = getattr(df, "chart_meta", None)
    if isinstance(chart_meta, dict):
        raw_zones = chart_meta.get("zones")
    if raw_zones is None:
        raw_zones = df.attrs.get("zones")
    if not isinstance(raw_zones, list):
        return None
    zones: list[dict] = []
    for zone in raw_zones:
        if not isinstance(zone, dict):
            continue
        color = zone.get("color")
        if not isinstance(color, str) or not color:
            continue
        try:
            lower = float(zone["from"])
            upper = float(zone["to"])
        except (KeyError, TypeError, ValueError):
            continue
        zones.append({"from": lower, "to": upper, "color": color})
    return zones or None


def _is_line_only(name: str) -> bool:
    """Indicators and non-stock instruments should render as line, not candlestick."""
    from TerraFin.data.providers.economic import indicator_registry
    from TerraFin.data.providers.market import MARKET_INDICATOR_REGISTRY

    if name in MARKET_INDICATOR_REGISTRY:
        return True
    if name in indicator_registry._indicators:
        return True
    return False


def _payload_length(series: list[dict]) -> int:
    return sum(len(item.get("data", [])) for item in series)


def format_series_item(df: TimeSeriesDataFrame | None, default_id: str = "Primary") -> dict | None:
    if df is None or df.empty:
        return None
    if "time" not in df.columns or "close" not in df.columns:
        return None

    frame = df
    times = pd.to_datetime(frame["time"], errors="coerce").dt.strftime("%Y-%m-%d").tolist()
    has_ohlc = all(col in frame.columns for col in ("open", "high", "low", "close")) and not _is_line_only(
        str(getattr(df, "name", ""))
    )

    if has_ohlc:
        rows = zip(
            times,
            frame["open"].astype(float).tolist(),
            frame["high"].astype(float).tolist(),
            frame["low"].astype(float).tolist(),
            frame["close"].astype(float).tolist(),
        )
        data = [
            {"time": time_str, "open": open_, "high": high, "low": low, "close": close}
            for time_str, open_, high, low, close in rows
        ]
        series_type = "candlestick"
    else:
        rows = zip(times, frame["close"].astype(float).tolist())
        data = [{"time": time_str, "value": value} for time_str, value in rows]
        series_type = "line"

    item = {
        "id": str(getattr(df, "name", "") or df.attrs.get("label", default_id)),
        "seriesType": series_type,
        "data": data,
    }
    zones = _serialize_zones(df)
    if zones:
        item["zones"] = zones
    return item


def format_dataframe(df: TimeSeriesDataFrame | None) -> dict:
    item = format_series_item(df)
    if item is None:
        return {"mode": "multi", "series": [], "dataLength": 0}
    series = [item]
    return {"mode": "multi", "series": series, "dataLength": _payload_length(series)}


def build_source_payload_from_items(source_items: list[dict]) -> dict:
    """Build an untransformed multi-series source payload."""
    items: list[dict] = []
    for source_item in source_items:
        if not isinstance(source_item, dict):
            continue
        items.append(dict(source_item))
    return {
        "mode": "multi",
        "series": items,
        "dataLength": _payload_length(items),
    }


def build_multi_payload_from_items(source_items: list[dict]) -> dict:
    """Build a multi-series chart payload from preformatted series items."""
    items: list[dict] = []
    n_candlestick = 0
    n_line = 0

    for source_item in source_items:
        item = dict(source_item)
        st = item.get("seriesType")
        if st == "candlestick":
            n_candlestick += 1
        elif st == "line":
            n_line += 1
        items.append(item)

    if n_candlestick >= 3:
        for item in items:
            if item.get("seriesType") == "candlestick":
                item["returnSeries"] = True
                item["seriesType"] = "line"
                item["data"] = [
                    {"time": point["time"], "value": float(point["close"])}
                    for point in item.get("data", [])
                    if isinstance(point, dict) and "time" in point and "close" in point
                ]

    force_percentage = n_candlestick >= 3

    overlay_idx = 0
    candle_idx = 0
    primary_assigned = False
    for item in items:
        st = item.get("seriesType")
        if force_percentage:
            if item.get("returnSeries"):
                item["priceScaleId"] = "right"
            else:
                item["priceScaleId"] = f"overlay-{overlay_idx}"
                overlay_idx += 1
        elif n_candlestick == 2:
            if st == "candlestick":
                item["returnSeries"] = True
                item["priceScaleId"] = "left" if candle_idx == 0 else "right"
                candle_idx += 1
            else:
                item["priceScaleId"] = f"overlay-{overlay_idx}"
                overlay_idx += 1
        elif n_candlestick == 1 and n_line >= 1:
            if st == "candlestick":
                item["priceScaleId"] = "right"
            elif not primary_assigned:
                item["priceScaleId"] = "left"
                primary_assigned = True
            else:
                item["priceScaleId"] = f"overlay-{overlay_idx}"
                overlay_idx += 1
        elif n_candlestick == 1 and n_line == 0:
            item["priceScaleId"] = "right"
        elif n_candlestick == 0 and n_line == 1:
            item["priceScaleId"] = "right"
        elif n_candlestick == 0 and n_line >= 2:
            if not primary_assigned:
                item["priceScaleId"] = "left"
                primary_assigned = True
            elif overlay_idx == 0:
                item["priceScaleId"] = "right"
                overlay_idx += 1
            else:
                item["priceScaleId"] = f"overlay-{overlay_idx - 1}"
                overlay_idx += 1

    return {
        "mode": "multi",
        "series": items,
        "dataLength": sum(len(item.get("data", [])) for item in items),
        "forcePercentage": force_percentage,
    }


def build_multi_payload(frames: list[TimeSeriesDataFrame]) -> dict:
    """Build a multi-series chart payload from a list of DataFrames."""
    items: list[dict] = []
    for idx, df in enumerate(frames):
        item = format_series_item(df, default_id=f"Series {idx + 1}")
        if item is not None:
            items.append(item)
    return build_multi_payload_from_items(items)


def build_source_payload(frames: list[TimeSeriesDataFrame]) -> dict:
    """Build an untransformed multi-series source payload from DataFrames."""
    items: list[dict] = []
    for idx, df in enumerate(frames):
        item = format_series_item(df, default_id=f"Series {idx + 1}")
        if item is not None:
            items.append(item)
    return build_source_payload_from_items(items)
