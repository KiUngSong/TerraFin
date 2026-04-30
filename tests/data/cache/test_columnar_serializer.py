"""Round-trip tests for the columnar time-series serializer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from TerraFin.data.cache.serializers import (
    ColumnarTimeSeriesSerializer,
    HistoryChunkSerializer,
)
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame


def _make_ohlcv_frame(rows: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2023-01-02", periods=rows, freq="B")
    rng = np.arange(rows, dtype=float) + 100.0
    return pd.DataFrame(
        {
            "Open": rng,
            "High": rng + 1,
            "Low": rng - 1,
            "Close": rng + 0.5,
            "Volume": (rng * 1000).astype(float),
        },
        index=idx,
    )


def test_columnar_round_trip(tmp_path: Path) -> None:
    serializer = ColumnarTimeSeriesSerializer()
    raw = _make_ohlcv_frame(20)
    payload = TimeSeriesDataFrame(raw)

    artifact_dir = tmp_path / "frame"
    serializer.write(artifact_dir, payload)

    loaded = serializer.read(artifact_dir)

    assert isinstance(loaded, TimeSeriesDataFrame)
    assert len(loaded) == len(payload)
    pd.testing.assert_series_equal(
        loaded["close"].reset_index(drop=True),
        payload["close"].reset_index(drop=True),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        loaded["volume"].reset_index(drop=True),
        payload["volume"].reset_index(drop=True),
        check_names=False,
    )


def test_columnar_partial_read_recent_and_backfill(tmp_path: Path) -> None:
    serializer = ColumnarTimeSeriesSerializer()
    rows = pd.date_range("2020-01-01", periods=400, freq="B")
    rng = np.arange(len(rows), dtype=float) + 50.0
    raw = pd.DataFrame(
        {"Open": rng, "High": rng + 1, "Low": rng - 1, "Close": rng + 0.25, "Volume": rng * 100},
        index=rows,
    )
    artifact_dir = tmp_path / "AAPL" / "full"
    serializer.write(artifact_dir, raw)

    recent, has_older = serializer.read_recent(artifact_dir, "6m", mmap=True)
    assert has_older is True
    assert not recent.empty
    assert len(recent) < len(raw)

    backfill, start, end = serializer.read_backfill(artifact_dir, recent["time"].iloc[0].strftime("%Y-%m-%d"))
    assert start is not None and end is not None
    assert not backfill.empty
    assert len(backfill) + len(recent) <= len(raw) + 5


def test_columnar_reads_existing_yfinance_v2_layout(tmp_path: Path) -> None:
    """Manually lay down the legacy on-disk format and ensure the serializer reads it."""
    artifact_dir = tmp_path / "yfinance_v2" / "aapl" / "full"
    artifact_dir.mkdir(parents=True)
    rows = 5
    idx = pd.date_range("2024-01-02", periods=rows, freq="B")
    times = (pd.DatetimeIndex(idx).view("int64") // 10**9).astype(np.int64)
    np.save(artifact_dir / "time_i64.npy", times)
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    np.save(artifact_dir / "open_f64.npy", closes - 0.5)
    np.save(artifact_dir / "high_f64.npy", closes + 1)
    np.save(artifact_dir / "low_f64.npy", closes - 1)
    np.save(artifact_dir / "close_f64.npy", closes)
    np.save(artifact_dir / "volume_f64.npy", closes * 1000)
    meta = {
        "version": 2,
        "schema": "ohlcv",
        "columns": ["Open", "High", "Low", "Close", "Volume"],
        "row_count": rows,
        "start_time": idx[0].strftime("%Y-%m-%d"),
        "end_time": idx[-1].strftime("%Y-%m-%d"),
        "cached_at": datetime.now(UTC).isoformat(),
        "is_complete": True,
        "has_older": False,
        "source": "yfinance",
        "index_name": "Date",
    }
    (artifact_dir / "meta.json").write_text(json.dumps(meta))

    serializer = ColumnarTimeSeriesSerializer()
    loaded = serializer.read(artifact_dir)
    assert isinstance(loaded, TimeSeriesDataFrame)
    assert len(loaded) == rows
    assert list(loaded["close"]) == pytest.approx(list(closes))


def test_columnar_preserves_name_and_chart_meta(tmp_path: Path) -> None:
    serializer = ColumnarTimeSeriesSerializer()
    raw = _make_ohlcv_frame(10)
    payload = TimeSeriesDataFrame(raw, name="AAPL", chart_meta={"unit": "USD", "kind": "ohlcv"})

    artifact_dir = tmp_path / "frame"
    serializer.write(artifact_dir, payload)
    loaded = serializer.read(artifact_dir)

    assert loaded.name == "AAPL"
    assert loaded.chart_meta == {"unit": "USD", "kind": "ohlcv"}


def test_columnar_drops_non_serializable_chart_meta(tmp_path: Path) -> None:
    serializer = ColumnarTimeSeriesSerializer()
    raw = _make_ohlcv_frame(5)

    class Weird:
        pass

    payload = TimeSeriesDataFrame(raw, name="TSLA", chart_meta={"obj": Weird()})
    artifact_dir = tmp_path / "frame"
    serializer.write(artifact_dir, payload)
    loaded = serializer.read(artifact_dir)
    # name still preserved
    assert loaded.name == "TSLA"
    # chart_meta either populated (via default=str) or empty dict; never crash
    assert isinstance(loaded.chart_meta, dict)


def test_history_chunk_serializer_round_trip(tmp_path: Path) -> None:
    serializer = HistoryChunkSerializer()
    frame = TimeSeriesDataFrame(_make_ohlcv_frame(8))
    chunk = HistoryChunk(
        frame=frame,
        loaded_start="2023-01-02",
        loaded_end="2023-01-11",
        requested_period="3y",
        is_complete=False,
        has_older=True,
        source_version="test",
    )
    artifact_dir = tmp_path / "chunk"
    serializer.write(artifact_dir, chunk)
    loaded = serializer.read(artifact_dir)

    assert loaded.loaded_start == "2023-01-02"
    assert loaded.loaded_end == "2023-01-11"
    assert loaded.requested_period == "3y"
    assert loaded.is_complete is False
    assert loaded.has_older is True
    assert loaded.source_version == "test"
    assert isinstance(loaded.frame, TimeSeriesDataFrame)
    assert len(loaded.frame) == len(frame)
