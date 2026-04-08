import pandas as pd

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from .client import PrivateAccessClient
from .series import (
    PrivateSeriesSpec,
    clear_private_series_cache,
    get_private_series_frame,
    get_private_series_full_history_backfill,
    get_private_series_history,
    get_private_series_recent_history,
    refresh_private_series_cache,
)


def _fetch_history(client: PrivateAccessClient):
    if hasattr(client, "fetch_series_history"):
        try:
            return client.fetch_series_history("trailing-forward-pe-spread")
        except Exception:
            pass
    payload = client.fetch_trailing_forward_pe_spread()
    return payload.history


def _normalize_history(records: list[dict]) -> list[dict]:
    if not records:
        return []
    normalized_records = [record.model_dump() if hasattr(record, "model_dump") else dict(record) for record in records]
    df = pd.DataFrame(normalized_records)
    if "time" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "time"})
    if "close" not in df.columns and "value" in df.columns:
        df = df.rename(columns={"value": "close"})
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


def _build_frame(records: list[dict]) -> TimeSeriesDataFrame:
    frame = TimeSeriesDataFrame(pd.DataFrame(records), name="Trailing-Forward P/E Spread")
    frame.name = "Trailing-Forward P/E Spread"
    return frame


TRAILING_FORWARD_PE_SERIES_SPEC = PrivateSeriesSpec(
    key="trailing-forward-pe-spread",
    display_name="Trailing-Forward P/E Spread",
    history_cache_namespace="private_trailing_forward_pe_history",
    history_fetcher=_fetch_history,
    history_normalizer=_normalize_history,
    frame_builder=_build_frame,
)


def get_trailing_forward_pe_history(
    *,
    force_refresh: bool = False,
    client: PrivateAccessClient | None = None,
) -> list[dict]:
    history = get_private_series_history(TRAILING_FORWARD_PE_SERIES_SPEC, force_refresh=force_refresh, client=client)
    return [{"date": item["time"], "value": item["close"]} for item in history]


def get_trailing_forward_pe_frame() -> TimeSeriesDataFrame:
    return get_private_series_frame(TRAILING_FORWARD_PE_SERIES_SPEC)


def get_trailing_forward_pe_recent_history(*, period: str = "3y"):
    return get_private_series_recent_history(TRAILING_FORWARD_PE_SERIES_SPEC, period=period)


def get_trailing_forward_pe_full_history_backfill(*, loaded_start: str | None = None):
    return get_private_series_full_history_backfill(TRAILING_FORWARD_PE_SERIES_SPEC, loaded_start=loaded_start)


def refresh_trailing_forward_pe_cache() -> None:
    refresh_private_series_cache(TRAILING_FORWARD_PE_SERIES_SPEC)


def clear_trailing_forward_pe_cache() -> None:
    clear_private_series_cache(TRAILING_FORWARD_PE_SERIES_SPEC)
