import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame


YFINANCE_CACHE: dict[str, pd.DataFrame] = {}
YFINANCE_RECENT_CACHE: dict[tuple[str, str], pd.DataFrame] = {}

_V2_NAMESPACE = "yfinance_v2"
_FILE_TTL = 86_400  # 24h
_RECENT_TOLERANCE_DAYS = 14
_V2_VERSION = 2

_COLUMN_FILE_MAP = {
    "Open": "open_f64.npy",
    "High": "high_f64.npy",
    "Low": "low_f64.npy",
    "Close": "close_f64.npy",
    "Volume": "volume_f64.npy",
}


def _file_cache():
    """Lazy import to avoid circular dependency (registry → yfinance → CacheManager → registry)."""
    from TerraFin.data.cache.manager import CacheManager

    return CacheManager


def _cache_root() -> Path:
    manager = _file_cache()
    cache_root = getattr(manager, "cache_root", None)
    if callable(cache_root):
        return cache_root()
    return Path.home() / ".terrafin" / "cache"


def _safe_key(key: str) -> str:
    manager = _file_cache()
    safe_key = getattr(manager, "safe_key", None)
    if callable(safe_key):
        return safe_key(key)
    return key.lower().replace(" ", "_").replace("/", "_")


def _artifact_dir(ticker: str, variant: str) -> Path:
    return _cache_root() / _V2_NAMESPACE / _safe_key(ticker) / variant


def _meta_path(ticker: str, variant: str) -> Path:
    return _artifact_dir(ticker, variant) / "meta.json"


def _read_meta(ticker: str, variant: str, *, max_age_seconds: int = _FILE_TTL) -> dict | None:
    path = _meta_path(ticker, variant)
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text())
        cached_at = meta.get("cached_at")
        if not cached_at:
            return None
        age = (datetime.now(UTC) - datetime.fromisoformat(cached_at)).total_seconds()
        if age > max_age_seconds:
            return None
        return meta
    except Exception:
        return None


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    normalized = pd.to_datetime(index, errors="coerce", utc=True)
    if isinstance(normalized, pd.Series):
        normalized = pd.DatetimeIndex(normalized)
    return pd.DatetimeIndex(normalized)


def _normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = _normalize_index(normalized.index)
    else:
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


def _schema_for_frame(frame: pd.DataFrame) -> tuple[str, list[str]]:
    columns = [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]
    if columns[:4] == ["Open", "High", "Low", "Close"]:
        return "ohlcv", columns
    return "close_only", ["Close"]


def _write_v2_artifact(ticker: str, variant: str, frame: pd.DataFrame, *, is_complete: bool, has_older: bool) -> None:
    normalized = _normalize_market_frame(frame)
    if normalized.empty:
        return

    artifact_dir = _artifact_dir(ticker, variant)
    temp_dir = artifact_dir.with_name(f"{artifact_dir.name}.tmp-{os.getpid()}-{time.time_ns()}")
    schema, columns = _schema_for_frame(normalized)
    normalized_index = _normalize_index(normalized.index)
    time_values = (normalized_index.view("int64") // 10**9).astype(np.int64)

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        np.save(temp_dir / "time_i64.npy", time_values)
        for column in columns:
            np.save(temp_dir / _COLUMN_FILE_MAP[column], normalized[column].astype(float).to_numpy(dtype=np.float64))

        meta = {
            "version": _V2_VERSION,
            "schema": schema,
            "columns": columns,
            "row_count": int(len(normalized)),
            "start_time": normalized_index[0].strftime("%Y-%m-%d"),
            "end_time": normalized_index[-1].strftime("%Y-%m-%d"),
            "cached_at": datetime.now(UTC).isoformat(),
            "is_complete": is_complete,
            "has_older": has_older,
            "source": "yfinance",
            "index_name": normalized.index.name or "Date",
        }
        (temp_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        artifact_dir.parent.mkdir(parents=True, exist_ok=True)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
        os.replace(temp_dir, artifact_dir)
    except Exception:
        for child in temp_dir.glob("*"):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass


def _artifact_frame(
    ticker: str,
    variant: str,
    *,
    start_idx: int = 0,
    stop_idx: int | None = None,
    mmap: bool,
) -> pd.DataFrame | None:
    meta = _read_meta(ticker, variant)
    if meta is None:
        return None

    artifact_dir = _artifact_dir(ticker, variant)
    try:
        time_values = np.load(artifact_dir / "time_i64.npy", mmap_mode="r" if mmap else None)
        end_idx = len(time_values) if stop_idx is None else max(start_idx, min(int(stop_idx), len(time_values)))
        begin_idx = max(0, min(int(start_idx), end_idx))
        if end_idx <= begin_idx:
            return pd.DataFrame()
        index_values = np.asarray(time_values[begin_idx:end_idx], dtype=np.int64)
        index = pd.to_datetime(index_values, unit="s", utc=True).tz_convert(None)
        data: dict[str, np.ndarray] = {}
        columns = [column for column in meta.get("columns", []) if column in _COLUMN_FILE_MAP]
        if not columns:
            columns = ["Close"]
        for column in columns:
            values = np.load(artifact_dir / _COLUMN_FILE_MAP[column], mmap_mode="r" if mmap else None)
            data[column] = np.asarray(values[begin_idx:end_idx], dtype=np.float64)
        frame = pd.DataFrame(data, index=index)
        frame.index.name = meta.get("index_name", "Date")
        return frame
    except Exception:
        return None


def _full_artifact_frame(ticker: str, *, mmap: bool = False) -> pd.DataFrame | None:
    return _artifact_frame(ticker, "full", mmap=mmap)


def _seed_artifact_frame(ticker: str, period: str) -> pd.DataFrame | None:
    if period != "3y":
        return None
    return _artifact_frame(ticker, "seed_3y", mmap=False)


def _derive_recent_from_full_artifact(ticker: str, period: str) -> tuple[pd.DataFrame | None, bool]:
    meta = _read_meta(ticker, "full")
    if meta is None:
        return None, False
    artifact_dir = _artifact_dir(ticker, "full")
    try:
        time_values = np.load(artifact_dir / "time_i64.npy", mmap_mode="r")
        if len(time_values) == 0:
            return pd.DataFrame(), False
        last_dt = pd.to_datetime(int(time_values[-1]), unit="s", utc=True)
        cutoff = (last_dt - _period_offset(period)).normalize()
        cutoff_seconds = int(cutoff.timestamp())
        start_idx = int(np.searchsorted(time_values, cutoff_seconds, side="left"))
        has_older = start_idx > 0
        frame = _artifact_frame(ticker, "full", start_idx=start_idx, mmap=True)
        return frame, has_older
    except Exception:
        return None, False


def _older_from_full_artifact(ticker: str, loaded_start: str | None) -> tuple[pd.DataFrame | None, str | None, str | None]:
    meta = _read_meta(ticker, "full")
    if meta is None:
        return None, None, None
    artifact_dir = _artifact_dir(ticker, "full")
    start_time = meta.get("start_time")
    end_time = meta.get("end_time")
    if not loaded_start:
        frame = _artifact_frame(ticker, "full", mmap=True)
        return frame, start_time, end_time
    try:
        time_values = np.load(artifact_dir / "time_i64.npy", mmap_mode="r")
        cutoff_dt = pd.to_datetime(loaded_start, utc=True, errors="coerce")
        if pd.isna(cutoff_dt):
            return None, None, None
        cutoff_seconds = int(cutoff_dt.timestamp())
        stop_idx = int(np.searchsorted(time_values, cutoff_seconds, side="left"))
        frame = _artifact_frame(ticker, "full", stop_idx=stop_idx, mmap=True)
        return frame, start_time, end_time
    except Exception:
        return None, None, None


def _persist_v2_caches(ticker: str, full_frame: pd.DataFrame, *, recent_period: str = "3y") -> None:
    normalized = _normalize_market_frame(full_frame)
    if normalized.empty:
        return
    recent = _slice_recent_frame(normalized, recent_period)
    has_older = len(recent) < len(normalized)
    _write_v2_artifact(ticker, "full", normalized, is_complete=True, has_older=False)
    if recent_period == "3y":
        _write_v2_artifact(ticker, "seed_3y", recent, is_complete=not has_older, has_older=has_older)


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


def get_yf_recent_history(ticker: str, *, period: str = "3y") -> HistoryChunk:
    ticker = ticker.upper()
    memory_key = (ticker, period)

    recent_cached = YFINANCE_RECENT_CACHE.get(memory_key)
    if recent_cached is not None:
        full_cached = YFINANCE_CACHE.get(ticker)
        has_older = len(recent_cached) < len(full_cached) if full_cached is not None else _infer_has_older(recent_cached, period)
        return _history_chunk_from_frame(
            recent_cached,
            period=period,
            has_older=has_older,
            is_complete=not has_older,
            source_version="memory-seed",
        )

    full_cached = YFINANCE_CACHE.get(ticker)
    if full_cached is not None:
        recent = _slice_recent_frame(full_cached, period)
        YFINANCE_RECENT_CACHE[memory_key] = recent
        has_older = len(recent) < len(full_cached)
        return _history_chunk_from_frame(
            recent,
            period=period,
            has_older=has_older,
            is_complete=not has_older,
            source_version="memory-full",
        )

    full_from_v2, has_older_from_v2 = _derive_recent_from_full_artifact(ticker, period)
    if full_from_v2 is not None:
        recent = _normalize_market_frame(full_from_v2)
        if not recent.empty:
            YFINANCE_RECENT_CACHE[memory_key] = recent
            return _history_chunk_from_frame(
                recent,
                period=period,
                has_older=has_older_from_v2,
                is_complete=not has_older_from_v2,
                source_version="v2-full-tail",
            )

    seed_frame = _seed_artifact_frame(ticker, period)
    if seed_frame is not None:
        meta = _read_meta(ticker, "seed_3y")
        seed = _normalize_market_frame(seed_frame)
        if not seed.empty:
            YFINANCE_RECENT_CACHE[memory_key] = seed
            has_older = bool(meta and meta.get("has_older", False))
            return _history_chunk_from_frame(
                seed,
                period=period,
                has_older=has_older,
                is_complete=bool(meta.get("is_complete", not has_older)) if meta else not has_older,
                source_version="v2-seed",
            )

    recent_download = _download_frame(ticker, period=period)
    if recent_download.empty:
        return _empty_history_chunk(period=period, source_version="download-seed", is_complete=True)

    has_older = _infer_has_older(recent_download, period)
    YFINANCE_RECENT_CACHE[memory_key] = recent_download
    _write_v2_artifact(ticker, "seed_3y", recent_download, is_complete=not has_older, has_older=has_older)
    return _history_chunk_from_frame(
        recent_download,
        period=period,
        has_older=has_older,
        is_complete=not has_older,
        source_version="download-seed",
    )


def get_yf_full_history_backfill(ticker: str, *, loaded_start: str | None = None) -> HistoryChunk:
    ticker = ticker.upper()
    full_cached = YFINANCE_CACHE.get(ticker)
    if full_cached is not None:
        normalized = _normalize_market_frame(full_cached)
        if loaded_start:
            cutoff = pd.Timestamp(loaded_start)
            older = normalized[normalized.index < cutoff].copy()
        else:
            older = normalized
        return _history_chunk_from_frame(
            older,
            period=None,
            has_older=False,
            is_complete=True,
            source_version="memory-full",
            loaded_start=_frame_bounds(normalized)[0],
            loaded_end=_frame_bounds(normalized)[1],
        )

    older_from_v2, full_start, full_end = _older_from_full_artifact(ticker, loaded_start)
    if older_from_v2 is not None:
        return _history_chunk_from_frame(
            older_from_v2,
            period=None,
            has_older=False,
            is_complete=True,
            source_version="v2-full",
            loaded_start=full_start,
            loaded_end=full_end,
        )

    full_download = _download_frame(ticker, period="max")
    if full_download.empty:
        return _empty_history_chunk(period=None, source_version="download-full", is_complete=True)

    YFINANCE_CACHE[ticker] = full_download
    _persist_v2_caches(ticker, full_download)
    cutoff = pd.Timestamp(loaded_start) if loaded_start else None
    older = full_download[full_download.index < cutoff].copy() if cutoff is not None else full_download
    full_start, full_end = _frame_bounds(full_download)
    return _history_chunk_from_frame(
        older,
        period=None,
        has_older=False,
        is_complete=True,
        source_version="download-full",
        loaded_start=full_start,
        loaded_end=full_end,
    )


def get_yf_data(ticker: str) -> pd.DataFrame:
    """
    Get the data from yfinance by its name
    :param ticker: str, ticker or index name
    :return: DataFrame, indicator data
    """

    ticker = ticker.upper()
    if ticker in YFINANCE_CACHE:
        return YFINANCE_CACHE[ticker].copy()

    full_frame = _full_artifact_frame(ticker)
    if full_frame is not None:
        normalized = _normalize_market_frame(full_frame)
        YFINANCE_CACHE[ticker] = normalized
        return normalized.copy()

    downloaded = _download_frame(ticker, period="max")
    YFINANCE_CACHE[ticker] = downloaded
    if not downloaded.empty:
        _persist_v2_caches(ticker, downloaded)
    return downloaded.copy()


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


def clear_yfinance_cache() -> None:
    YFINANCE_CACHE.clear()
    YFINANCE_RECENT_CACHE.clear()
    remove_tree = getattr(_file_cache(), "file_cache_remove_tree", None)
    if callable(remove_tree):
        remove_tree(_V2_NAMESPACE)
