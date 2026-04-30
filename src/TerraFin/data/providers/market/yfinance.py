import pandas as pd
import yfinance as yf

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame


_V2_NAMESPACE = "yfinance_v2"
_RECENT_TOLERANCE_DAYS = 14


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    normalized = pd.to_datetime(index, errors="coerce", utc=True)
    if isinstance(normalized, pd.Series):
        normalized = pd.DatetimeIndex(normalized)
    return pd.DatetimeIndex(normalized)


def _normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    normalized = frame.copy()
    normalized.index = _normalize_index(normalized.index)
    normalized = normalized[~normalized.index.isna()]
    if normalized.empty:
        return pd.DataFrame()
    normalized = normalized.sort_index()
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    normalized.index = normalized.index.tz_convert(None)
    normalized.index.name = frame.index.name or "Date"

    keep_columns = [column for column in ("Open", "High", "Low", "Close", "Volume") if column in normalized.columns]
    if "Close" not in keep_columns:
        return pd.DataFrame()
    return normalized[keep_columns]


def _frame_bounds(frame: pd.DataFrame) -> tuple[str | None, str | None]:
    if frame.empty:
        return None, None
    index = _normalize_index(frame.index)
    if len(index) == 0:
        return None, None
    return index[0].strftime("%Y-%m-%d"), index[-1].strftime("%Y-%m-%d")


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


def _slice_recent_frame(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    normalized = _normalize_market_frame(frame)
    if normalized.empty:
        return normalized
    end = pd.Timestamp(normalized.index[-1])
    start = (end - _period_offset(period)).normalize()
    recent = normalized[normalized.index >= start]
    if recent.empty:
        return normalized.iloc[[-1]].copy()
    return recent.copy()


def _infer_has_older(frame: pd.DataFrame, period: str) -> bool:
    normalized = _normalize_market_frame(frame)
    if normalized.empty:
        return False
    end = pd.Timestamp(normalized.index[-1])
    cutoff = (end - _period_offset(period)).normalize()
    tolerance = pd.Timedelta(days=_RECENT_TOLERANCE_DAYS)
    first = pd.Timestamp(normalized.index[0])
    return first <= cutoff + tolerance


def _empty_history_chunk(*, period: str | None, source_version: str | None, is_complete: bool) -> HistoryChunk:
    frame = TimeSeriesDataFrame.make_empty()
    return HistoryChunk(
        frame=frame,
        loaded_start=None,
        loaded_end=None,
        requested_period=period,
        is_complete=is_complete,
        has_older=False,
        source_version=source_version,
    )


def _history_chunk_from_frame(
    frame: pd.DataFrame,
    *,
    period: str | None,
    has_older: bool,
    is_complete: bool,
    source_version: str,
    loaded_start: str | None = None,
    loaded_end: str | None = None,
) -> HistoryChunk:
    normalized = _normalize_market_frame(frame)
    series = TimeSeriesDataFrame(normalized)
    start, end = _frame_bounds(normalized)
    return HistoryChunk(
        frame=series,
        loaded_start=loaded_start if loaded_start is not None else start,
        loaded_end=loaded_end if loaded_end is not None else end,
        requested_period=period,
        is_complete=is_complete,
        has_older=has_older,
        source_version=source_version,
    )


def _download_frame(ticker: str, *, period: str) -> pd.DataFrame:
    frame = yf.download(ticker, period=period, auto_adjust=True, multi_level_index=False)
    normalized = _normalize_market_frame(frame)
    if normalized.empty and not valid_ticker(ticker):
        raise ValueError(f"Invalid ticker: {ticker}")
    return normalized


def _managed_cache_manager():
    from TerraFin.data.cache import get_cache_manager

    return get_cache_manager()


def _ensure_full_payload_registered(ticker: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec

    source = f"yfinance.full.{ticker}"
    manager = _managed_cache_manager()
    if source in manager._payload_specs:
        return source
    manager.register_payload(
        CachePayloadSpec(
            source=source,
            namespace=_V2_NAMESPACE,
            key=f"{ticker}/full",
            ttl_seconds=ttl_for("yfinance.full"),
            fetch_fn=lambda t=ticker: _download_frame(t, period="max"),
            expected_type=TimeSeriesDataFrame,
        )
    )
    return source


def _ts_to_market_frame(payload) -> pd.DataFrame:
    if payload is None or len(payload) == 0:
        return pd.DataFrame()
    columns = list(payload.columns)
    data = {col: payload[col].to_numpy() for col in columns}
    df = pd.DataFrame(data)
    if "time" in df.columns:
        new_index = pd.DatetimeIndex(pd.to_datetime(df["time"], errors="coerce"))
        new_index.name = "Date"
        df.index = new_index
        df = df.drop(columns=["time"])
    elif isinstance(payload.index, pd.DatetimeIndex):
        df.index = pd.DatetimeIndex(payload.index)
    else:
        df.index = pd.DatetimeIndex(pd.to_datetime(payload.index, errors="coerce"))
    rename = {}
    for c in df.columns:
        for canonical in ("Open", "High", "Low", "Close", "Volume"):
            if str(c).lower() == canonical.lower():
                rename[c] = canonical
                break
    if rename:
        df = df.rename(columns=rename)
    return _normalize_market_frame(df)


def _get_yf_full(ticker: str) -> pd.DataFrame:
    source = _ensure_full_payload_registered(ticker)
    result = _managed_cache_manager().get_payload(source)
    return _ts_to_market_frame(result.payload)


def get_yf_data(ticker: str) -> pd.DataFrame:
    """
    Get the data from yfinance by its name
    :param ticker: str, ticker or index name
    :return: DataFrame, indicator data
    """
    return _get_yf_full(ticker.upper()).copy()


def get_yf_recent_history(ticker: str, *, period: str = "3y") -> HistoryChunk:
    ticker = ticker.upper()
    from TerraFin.data.cache.serializers import ColumnarTimeSeriesSerializer

    serializer = ColumnarTimeSeriesSerializer()
    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    if artifact_dir.exists():
        recent_frame, has_older = serializer.read_recent(artifact_dir, period)
        if not recent_frame.empty:
            normalized = _ts_to_market_frame(recent_frame)
            return _history_chunk_from_frame(
                normalized,
                period=period,
                has_older=has_older,
                is_complete=not has_older,
                source_version="managed-artifact-tail",
            )

    full_df = _get_yf_full(ticker)
    if full_df.empty:
        return _empty_history_chunk(period=period, source_version="managed-download", is_complete=True)
    recent = _slice_recent_frame(full_df, period)
    has_older = len(recent) < len(full_df)
    return _history_chunk_from_frame(
        recent,
        period=period,
        has_older=has_older,
        is_complete=not has_older,
        source_version="managed-download",
    )


def get_yf_full_history_backfill(ticker: str, *, loaded_start: str | None = None) -> HistoryChunk:
    ticker = ticker.upper()
    from TerraFin.data.cache.serializers import ColumnarTimeSeriesSerializer

    serializer = ColumnarTimeSeriesSerializer()
    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    if artifact_dir.exists():
        older_frame, full_start, full_end = serializer.read_backfill(artifact_dir, loaded_start)
        normalized_older = _ts_to_market_frame(older_frame)
        return _history_chunk_from_frame(
            normalized_older,
            period=None,
            has_older=False,
            is_complete=True,
            source_version="managed-artifact-full",
            loaded_start=full_start,
            loaded_end=full_end,
        )

    full_df = _get_yf_full(ticker)
    if full_df.empty:
        return _empty_history_chunk(period=None, source_version="managed-download-full", is_complete=True)
    cutoff = pd.Timestamp(loaded_start) if loaded_start else None
    older = full_df[full_df.index < cutoff].copy() if cutoff is not None else full_df
    full_start, full_end = _frame_bounds(full_df)
    return _history_chunk_from_frame(
        older,
        period=None,
        has_older=False,
        is_complete=True,
        source_version="managed-download-full",
        loaded_start=full_start,
        loaded_end=full_end,
    )


def valid_ticker(ticker: str) -> bool:
    """
    Check if the ticker is valid
    :param ticker: str, ticker
    :return: bool, True if the ticker is valid, False otherwise
    """
    ticker_name = ticker.upper()
    ticker_data = yf.Ticker(ticker_name)
    hist = ticker_data.history(period="1d")
    return not hist.empty
