from datetime import timedelta

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
            return client.fetch_series_history("fear-greed")
        except Exception:
            pass
    return client.fetch_fear_greed()


def _fetch_current(client: PrivateAccessClient):
    return client.fetch_fear_greed_current()


def _normalize_history(records: list[dict]) -> list[dict]:
    if not records:
        return []
    df = pd.DataFrame(records)
    if "time" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "time"})
    if "close" not in df.columns and "score" in df.columns:
        df = df.rename(columns={"score": "close"})
    if "time" not in df.columns or "close" not in df.columns:
        return []
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates(subset=["time"], keep="last")
    return [
        {
            "time": pd.Timestamp(row["time"]).strftime("%Y-%m-%d"),
            "close": int(round(float(row["close"]))),
        }
        for _, row in df.iterrows()
    ]


def _build_frame(records: list[dict]) -> TimeSeriesDataFrame:
    frame = TimeSeriesDataFrame(pd.DataFrame(records), name="Fear & Greed")
    frame.name = "Fear & Greed"
    return frame


def _normalize_current(payload: dict) -> dict:
    score = payload.get("score")
    try:
        score = int(round(float(score))) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "score": score,
        "rating": _normalize_rating(payload.get("rating")) or _rating_from_score(score),
        "timestamp": str(payload.get("timestamp", "") or ""),
        "previous_close": _normalize_optional_int(payload.get("previous_close")),
        "previous_1_week": _normalize_optional_int(payload.get("previous_1_week")),
        "previous_1_month": _normalize_optional_int(payload.get("previous_1_month")),
    }


def _normalize_optional_int(value) -> int | None:
    try:
        return int(round(float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_rating(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = " ".join(text.split())
    mapping = {
        "extreme fear": "Extreme Fear",
        "fear": "Fear",
        "neutral": "Neutral",
        "greed": "Greed",
        "extreme greed": "Extreme Greed",
    }
    return mapping.get(text, text.title())


def _derive_current(history: list[dict]) -> dict:
    records = _normalize_history(history)
    if not records:
        raise ValueError("Fear & Greed history is unavailable.")

    latest = records[-1]
    latest_date = pd.Timestamp(latest["time"])
    previous_close = records[-2]["close"] if len(records) >= 2 else latest["close"]
    previous_1_week = _value_on_or_before(records, latest_date - timedelta(days=7))
    previous_1_month = _value_on_or_before(records, latest_date - timedelta(days=30))
    score = latest["close"]
    return {
        "score": score,
        "rating": _rating_from_score(score),
        "timestamp": latest_date.strftime("%Y-%m-%d"),
        "previous_close": previous_close,
        "previous_1_week": previous_1_week,
        "previous_1_month": previous_1_month,
    }


def _value_on_or_before(records: list[dict], target: pd.Timestamp) -> int | None:
    for record in reversed(records):
        if pd.Timestamp(record["time"]) <= target:
            return int(record["close"])
    return int(records[0]["close"]) if records else None


def _rating_from_score(score: int | None) -> str:
    if score is None:
        return "Unavailable"
    if score <= 25:
        return "Extreme Fear"
    if score <= 44:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 74:
        return "Greed"
    return "Extreme Greed"


FEAR_GREED_SERIES_SPEC = PrivateSeriesSpec(
    key="fear-greed",
    display_name="Fear & Greed",
    history_cache_namespace="private_fear_greed_history",
    history_fetcher=_fetch_history,
    history_normalizer=_normalize_history,
    frame_builder=_build_frame,
    current_cache_namespace="private_fear_greed_current",
    current_fetcher=_fetch_current,
    current_normalizer=_normalize_current,
    current_deriver=_derive_current,
)


def get_fear_greed_history(*, force_refresh: bool = False, client: PrivateAccessClient | None = None) -> list[dict]:
    history = get_private_series_history(FEAR_GREED_SERIES_SPEC, force_refresh=force_refresh, client=client)
    return [{"date": item["time"], "score": item["close"]} for item in history]


def get_fear_greed_frame() -> TimeSeriesDataFrame:
    return get_private_series_frame(FEAR_GREED_SERIES_SPEC)


def get_fear_greed_recent_history(*, period: str = "3y"):
    return get_private_series_recent_history(FEAR_GREED_SERIES_SPEC, period=period)


def get_fear_greed_full_history_backfill(*, loaded_start: str | None = None):
    return get_private_series_full_history_backfill(FEAR_GREED_SERIES_SPEC, loaded_start=loaded_start)


def get_fear_greed_current(*, force_refresh: bool = False, client: PrivateAccessClient | None = None) -> dict:
    return get_private_series_current(FEAR_GREED_SERIES_SPEC, force_refresh=force_refresh, client=client)


def refresh_fear_greed_cache() -> None:
    refresh_private_series_cache(FEAR_GREED_SERIES_SPEC)


def clear_fear_greed_cache() -> None:
    clear_private_series_cache(FEAR_GREED_SERIES_SPEC)
