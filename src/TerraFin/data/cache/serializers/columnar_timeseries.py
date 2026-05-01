"""Columnar serializer for OHLCV time-series frames.

Generalizes the yfinance v2 artifact format. The on-disk layout is:

    <path>/
      time_i64.npy
      open_f64.npy
      high_f64.npy
      low_f64.npy
      close_f64.npy
      volume_f64.npy
      meta.json

Layout matches existing ``~/.terrafin/cache/yfinance_v2/<TICKER>/<variant>/``
artifacts so both the legacy yfinance code path and the managed-cache code path
read/write the same bytes.
"""

import json
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame

_logger = logging.getLogger(__name__)


_CANONICAL_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
_COLUMN_FILE_MAP = {
    "Open": "open_f64.npy",
    "High": "high_f64.npy",
    "Low": "low_f64.npy",
    "Close": "close_f64.npy",
    "Volume": "volume_f64.npy",
}
_VERSION = 2


def _frame_to_capitalized(frame: pd.DataFrame) -> pd.DataFrame:
    """Project arbitrary OHLCV frame to capitalized columns + DatetimeIndex.

    Accepts both the lowercase ``time/open/high/low/close/volume`` layout used by
    ``TimeSeriesDataFrame`` and the capitalized layout used by raw yfinance
    output. Returns a plain ``pd.DataFrame`` with capitalized columns and a
    naive UTC ``DatetimeIndex``.
    """
    if frame is None or len(frame) == 0:
        return pd.DataFrame()

    if isinstance(frame, pd.DataFrame):
        df = pd.DataFrame(
            {col: frame[col].to_numpy() for col in frame.columns},
            index=pd.Index(frame.index),
        )
    else:
        df = pd.DataFrame(frame).copy()

    if "time" in df.columns:
        df = df.set_index("time")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce", utc=True)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True)
    df = df[~df.index.isna()]
    if df.empty:
        return pd.DataFrame()
    df.index = pd.DatetimeIndex(df.index).tz_convert(None)
    df.index.name = "Date"
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    rename = {}
    for col in df.columns:
        lower = str(col).lower()
        for canonical in _CANONICAL_COLUMNS:
            if lower == canonical.lower():
                rename[col] = canonical
                break
    if rename:
        df = df.rename(columns=rename)

    keep = [c for c in _CANONICAL_COLUMNS if c in df.columns]
    if "Close" not in keep:
        return pd.DataFrame()
    return df[keep]


def _schema_for(frame: pd.DataFrame) -> tuple[str, list[str]]:
    columns = [c for c in _CANONICAL_COLUMNS if c in frame.columns]
    if columns[:4] == ["Open", "High", "Low", "Close"]:
        return "ohlcv", columns
    return "close_only", ["Close"]


def _read_meta(path: Path, *, max_age_seconds: int | None = None) -> dict | None:
    meta_path = path / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return None
    if max_age_seconds is not None:
        cached_at = meta.get("cached_at")
        if not cached_at:
            return None
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(cached_at)).total_seconds()
        except Exception:
            return None
        if age > max_age_seconds:
            return None
    return meta


def _frame_from_columnar(
    path: Path,
    meta: dict,
    *,
    start_idx: int = 0,
    stop_idx: int | None = None,
    mmap: bool = False,
) -> pd.DataFrame:
    mode = "r" if mmap else None
    time_values = np.load(path / "time_i64.npy", mmap_mode=mode)
    end_idx = len(time_values) if stop_idx is None else max(start_idx, min(int(stop_idx), len(time_values)))
    begin_idx = max(0, min(int(start_idx), end_idx))
    if end_idx <= begin_idx:
        return pd.DataFrame()
    index_values = np.asarray(time_values[begin_idx:end_idx], dtype=np.int64)
    index = pd.to_datetime(index_values, unit="s", utc=True).tz_convert(None)
    columns = [c for c in meta.get("columns", []) if c in _COLUMN_FILE_MAP] or ["Close"]
    data: dict[str, np.ndarray] = {}
    for column in columns:
        values = np.load(path / _COLUMN_FILE_MAP[column], mmap_mode=mode)
        data[column] = np.asarray(values[begin_idx:end_idx], dtype=np.float64)
    frame = pd.DataFrame(data, index=index)
    frame.index.name = meta.get("index_name", "Date")
    return frame


def _attach_meta(frame: TimeSeriesDataFrame, meta: dict) -> TimeSeriesDataFrame:
    frame_name = meta.get("frame_name")
    if frame_name is not None:
        frame.name = frame_name
    chart_meta = meta.get("chart_meta")
    if isinstance(chart_meta, dict):
        frame.chart_meta = chart_meta
    return frame


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


class ColumnarTimeSeriesSerializer:
    """Reads/writes OHLCV frames as a directory of ``.npy`` columns."""

    name = "columnar_timeseries_v2"

    def write(self, path: Path, payload: Any) -> None:
        normalized = _frame_to_capitalized(payload)
        if normalized.empty:
            return
        schema, columns = _schema_for(normalized)
        time_values = (pd.DatetimeIndex(normalized.index).view("int64") // 10**9).astype(np.int64)

        frame_name = getattr(payload, "name", None)
        raw_chart_meta = getattr(payload, "chart_meta", None)
        chart_meta_json: Any = None
        if isinstance(raw_chart_meta, dict) and raw_chart_meta:
            try:
                chart_meta_json = json.loads(json.dumps(raw_chart_meta, default=str))
            except (TypeError, ValueError) as exc:
                _logger.warning("ColumnarTimeSeriesSerializer: chart_meta not JSON-serializable; dropping. error=%s", exc)
                chart_meta_json = None

        path = Path(path)
        temp_dir = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            np.save(temp_dir / "time_i64.npy", time_values)
            for column in columns:
                np.save(
                    temp_dir / _COLUMN_FILE_MAP[column],
                    normalized[column].astype(float).to_numpy(dtype=np.float64),
                )
            meta = {
                "version": _VERSION,
                "schema": schema,
                "columns": columns,
                "row_count": int(len(normalized)),
                "start_time": pd.Timestamp(normalized.index[0]).strftime("%Y-%m-%d"),
                "end_time": pd.Timestamp(normalized.index[-1]).strftime("%Y-%m-%d"),
                "cached_at": datetime.now(UTC).isoformat(),
                "is_complete": True,
                "has_older": False,
                "source": "columnar_timeseries_v2",
                "index_name": normalized.index.name or "Date",
                "frame_name": frame_name,
                "chart_meta": chart_meta_json,
            }
            (temp_dir / "meta.json").write_text(json.dumps(meta, indent=2))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            os.replace(temp_dir, path)
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
            raise

    def read(self, path: Path) -> TimeSeriesDataFrame:
        path = Path(path)
        meta = _read_meta(path)
        if meta is None:
            return TimeSeriesDataFrame.make_empty()
        try:
            frame = _frame_from_columnar(path, meta, mmap=False)
        except Exception:
            return TimeSeriesDataFrame.make_empty()
        result = TimeSeriesDataFrame(frame)
        frame_name = meta.get("frame_name")
        if frame_name is not None:
            result.name = frame_name
        chart_meta = meta.get("chart_meta")
        if isinstance(chart_meta, dict):
            result.chart_meta = chart_meta
        return result

    def read_recent(self, path: Path, period: str, *, mmap: bool = True) -> tuple[TimeSeriesDataFrame, bool]:
        """Return the trailing slice of the artifact covering ``period``.

        Returns ``(frame, has_older)`` where ``has_older`` indicates whether
        the artifact contains rows before the slice (i.e. backfill exists).
        """
        path = Path(path)
        meta = _read_meta(path)
        if meta is None:
            return TimeSeriesDataFrame.make_empty(), False
        try:
            time_values = np.load(path / "time_i64.npy", mmap_mode="r" if mmap else None)
            if len(time_values) == 0:
                return TimeSeriesDataFrame.make_empty(), False
            last_dt = pd.to_datetime(int(time_values[-1]), unit="s", utc=True)
            cutoff = (last_dt - _period_offset(period)).normalize()
            cutoff_seconds = int(cutoff.timestamp())
            start_idx = int(np.searchsorted(time_values, cutoff_seconds, side="left"))
            has_older = start_idx > 0
            frame = _frame_from_columnar(path, meta, start_idx=start_idx, mmap=mmap)
        except Exception:
            return TimeSeriesDataFrame.make_empty(), False
        return _attach_meta(TimeSeriesDataFrame(frame), meta), has_older

    def read_backfill(
        self,
        path: Path,
        loaded_start: str | None,
        *,
        mmap: bool = True,
    ) -> tuple[TimeSeriesDataFrame, str | None, str | None]:
        """Return rows older than ``loaded_start`` plus full bounds.

        If ``loaded_start`` is ``None``, returns the entire artifact.
        """
        path = Path(path)
        meta = _read_meta(path)
        if meta is None:
            return TimeSeriesDataFrame.make_empty(), None, None
        start_time = meta.get("start_time")
        end_time = meta.get("end_time")
        try:
            if not loaded_start:
                frame = _frame_from_columnar(path, meta, mmap=mmap)
                return _attach_meta(TimeSeriesDataFrame(frame), meta), start_time, end_time
            time_values = np.load(path / "time_i64.npy", mmap_mode="r" if mmap else None)
            cutoff_dt = pd.to_datetime(loaded_start, utc=True, errors="coerce")
            if pd.isna(cutoff_dt):
                return TimeSeriesDataFrame.make_empty(), None, None
            cutoff_seconds = int(cutoff_dt.timestamp())
            stop_idx = int(np.searchsorted(time_values, cutoff_seconds, side="left"))
            frame = _frame_from_columnar(path, meta, stop_idx=stop_idx, mmap=mmap)
        except Exception:
            return TimeSeriesDataFrame.make_empty(), None, None
        return _attach_meta(TimeSeriesDataFrame(frame), meta), start_time, end_time


class HistoryChunkSerializer:
    """Splits a ``HistoryChunk`` into a JSON metadata file + columnar frame.

    Layout::

        <path>/
          metadata.json   # loaded_start/end, requested_period, flags, source_version
          frame/          # columnar TimeSeriesDataFrame artifact
    """

    name = "history_chunk_v1"

    def __init__(self) -> None:
        self._frame_serializer = ColumnarTimeSeriesSerializer()

    def write(self, path: Path, payload: Any) -> None:
        if not isinstance(payload, HistoryChunk):
            raise TypeError(f"HistoryChunkSerializer expects HistoryChunk, got {type(payload).__name__}")
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        metadata = {
            "loaded_start": payload.loaded_start,
            "loaded_end": payload.loaded_end,
            "requested_period": payload.requested_period,
            "is_complete": payload.is_complete,
            "has_older": payload.has_older,
            "source_version": payload.source_version,
            "cached_at": datetime.now(UTC).isoformat(),
        }
        (path / "metadata.json").write_text(json.dumps(metadata, indent=2))
        self._frame_serializer.write(path / "frame", payload.frame)

    def read(self, path: Path) -> HistoryChunk:
        path = Path(path)
        metadata_path = path / "metadata.json"
        if not metadata_path.exists():
            return HistoryChunk(
                frame=TimeSeriesDataFrame.make_empty(),
                loaded_start=None,
                loaded_end=None,
                requested_period=None,
                is_complete=True,
                has_older=False,
                source_version=None,
            )
        metadata = json.loads(metadata_path.read_text())
        frame = self._frame_serializer.read(path / "frame")
        return HistoryChunk(
            frame=frame,
            loaded_start=metadata.get("loaded_start"),
            loaded_end=metadata.get("loaded_end"),
            requested_period=metadata.get("requested_period"),
            is_complete=bool(metadata.get("is_complete", True)),
            has_older=bool(metadata.get("has_older", False)),
            source_version=metadata.get("source_version"),
        )
