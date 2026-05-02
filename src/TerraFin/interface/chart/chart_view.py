"""Chart view transformations for multi-series chart payloads.

Pure-Python implementation — no pandas dependency.
"""


def _period_key(date_str: str, view: str) -> str:
    """Map a YYYY-MM-DD string to a period bucket key."""
    y, m, d = date_str[:4], date_str[5:7], date_str[8:10]
    if view == "weekly":
        # ISO week: group by year-week
        from datetime import date as _date
        dt = _date(int(y), int(m), int(d))
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if view == "monthly":
        return f"{y}-{m}"
    if view == "yearly":
        return y
    return date_str  # daily — no grouping


def _resample_candlestick(data: list[dict], view: str) -> list[dict]:
    """Resample OHLC data: first open, max high, min low, last close per period."""
    if not data or view == "daily":
        return data

    buckets: dict[str, dict] = {}
    order: list[str] = []
    for p in data:
        t = p.get("time", "")
        key = _period_key(t, view)
        vol = p.get("volume")
        if key not in buckets:
            buckets[key] = {
                "time": t,
                "open": float(p["open"]),
                "high": float(p["high"]),
                "low": float(p["low"]),
                "close": float(p["close"]),
            }
            if vol is not None:
                buckets[key]["volume"] = float(vol)
            order.append(key)
        else:
            b = buckets[key]
            b["time"] = t  # keep last date in period
            h = float(p["high"])
            lo = float(p["low"])
            if h > b["high"]:
                b["high"] = h
            if lo < b["low"]:
                b["low"] = lo
            b["close"] = float(p["close"])
            if vol is not None:
                b["volume"] = b.get("volume", 0.0) + float(vol)
    return [buckets[k] for k in order]


def _resample_line(data: list[dict], view: str) -> list[dict]:
    """Resample line data: last value per period."""
    if not data or view == "daily":
        return data

    buckets: dict[str, dict] = {}
    order: list[str] = []
    for p in data:
        t = p.get("time", "")
        key = _period_key(t, view)
        if key not in buckets:
            buckets[key] = {"time": t, "value": float(p["value"])}
            order.append(key)
        else:
            buckets[key] = {"time": t, "value": float(p["value"])}
    return [buckets[k] for k in order]


def _payload_length(series: list[dict]) -> int:
    return sum(len(item.get("data", [])) for item in series)


def apply_view(source_payload: dict, view: str) -> dict:
    """Apply timeframe transform to each series in a multi-series payload.

    view: daily | weekly | monthly | yearly
    """
    if source_payload.get("mode") != "multi":
        return {"mode": "multi", "series": [], "dataLength": 0}

    source_series = source_payload.get("series")
    if not isinstance(source_series, list):
        return {"mode": "multi", "series": [], "dataLength": 0}

    view = (view or "daily").lower()
    transformed_series: list[dict] = []
    for item in source_series:
        if not isinstance(item, dict):
            continue
        series_type = item.get("seriesType")
        if series_type == "candlestick":
            transformed_data = _resample_candlestick(item.get("data", []), view)
        elif series_type == "line":
            transformed_data = _resample_line(item.get("data", []), view)
        else:
            continue
        out: dict = {
            "id": str(item.get("id", "Series")),
            "seriesType": series_type,
            "color": item.get("color"),
            "data": transformed_data,
        }
        if item.get("priceScaleId") is not None:
            out["priceScaleId"] = item["priceScaleId"]
        if item.get("returnSeries"):
            out["returnSeries"] = True
        if item.get("indicator"):
            out["indicator"] = True
        if item.get("indicatorGroup") is not None:
            out["indicatorGroup"] = item["indicatorGroup"]
        if item.get("lineStyle") is not None:
            out["lineStyle"] = item["lineStyle"]
        if item.get("priceLevels"):
            out["priceLevels"] = item["priceLevels"]
        if item.get("zones"):
            out["zones"] = item["zones"]
        transformed_series.append(out)

    result: dict = {"mode": "multi", "series": transformed_series, "dataLength": _payload_length(transformed_series)}
    if source_payload.get("forcePercentage"):
        result["forcePercentage"] = True
    return result
