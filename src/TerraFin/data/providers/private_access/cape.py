import pandas as pd

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from .client import PrivateAccessClient
from .series import (
    PrivateSeriesSpec,
    clear_private_series_cache,
    get_private_series_current,
    get_private_series_frame,
    get_private_series_full_history_backfill,
    get_private_series_history,
    get_private_series_recent_history,
    refresh_private_series_cache,
)


def _fetch_history(client: PrivateAccessClient):
    if hasattr(client, "fetch_series_history"):
        try:
            return client.fetch_series_history("cape")
        except Exception:
            pass
    return client.fetch_cape_history()


def _fetch_current(client: PrivateAccessClient):
    return client.fetch_cape_current()


def _normalize_history(records: list[dict]) -> list[dict]:
    if not records:
        return []
    normalized_records = [record.model_dump() if hasattr(record, "model_dump") else dict(record) for record in records]
    df = pd.DataFrame(normalized_records)
    if "time" not in df.columns and "date" in df.columns:
        df["time"] = df["date"].astype(str).map(_normalize_month_string)
    if "close" not in df.columns and "cape" in df.columns:
        df = df.rename(columns={"cape": "close"})
    if "time" not in df.columns or "close" not in df.columns:
        return []
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates(subset=["time"], keep="last")
    return [
        {
            "time": pd.Timestamp(row["time"]).strftime("%Y-%m-%d"),
            "close": float(row["close"]),
        }
        for _, row in df.iterrows()
    ]


def _normalize_month_string(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 7:
        return f"{text}-01"
    return text


def _build_frame(records: list[dict]) -> TimeSeriesDataFrame:
    frame = TimeSeriesDataFrame(pd.DataFrame(records), name="CAPE")
    frame.name = "CAPE"
    return frame


def _normalize_current(payload: dict) -> dict:
    value = payload.get("cape")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "date": payload.get("date") or None,
        "cape": value,
    }


def _derive_current(history: list[dict]) -> dict:
    records = _normalize_history(history)
    if not records:
        raise ValueError("CAPE history is unavailable.")
    latest = records[-1]
    return {
        "date": pd.Timestamp(latest["time"]).strftime("%Y-%m"),
        "cape": float(latest["close"]),
    }


CAPE_SERIES_SPEC = PrivateSeriesSpec(
    key="cape",
    display_name="CAPE",
    history_cache_namespace="private_cape_history",
    history_fetcher=_fetch_history,
    history_normalizer=_normalize_history,
    frame_builder=_build_frame,
    current_cache_namespace="private_cape_series_current",
    current_fetcher=_fetch_current,
    current_normalizer=_normalize_current,
    current_deriver=_derive_current,
)


def get_cape_history(*, force_refresh: bool = False, client: PrivateAccessClient | None = None) -> list[dict]:
    history = get_private_series_history(CAPE_SERIES_SPEC, force_refresh=force_refresh, client=client)
    return [{"date": pd.Timestamp(item["time"]).strftime("%Y-%m"), "cape": item["close"]} for item in history]


def get_cape_frame() -> TimeSeriesDataFrame:
    return get_private_series_frame(CAPE_SERIES_SPEC)


def get_cape_recent_history(*, period: str = "3y"):
    return get_private_series_recent_history(CAPE_SERIES_SPEC, period=period)


def get_cape_full_history_backfill(*, loaded_start: str | None = None):
    return get_private_series_full_history_backfill(CAPE_SERIES_SPEC, loaded_start=loaded_start)


def get_cape_current(*, force_refresh: bool = False, client: PrivateAccessClient | None = None) -> dict:
    return get_private_series_current(CAPE_SERIES_SPEC, force_refresh=force_refresh, client=client)


def refresh_cape_cache() -> None:
    refresh_private_series_cache(CAPE_SERIES_SPEC)


def clear_cape_cache() -> None:
    clear_private_series_cache(CAPE_SERIES_SPEC)
