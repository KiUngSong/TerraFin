import json
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame
from TerraFin.data.providers.market.session_calendar import (
    is_cache_stale_by_session,
    latest_expected_close,
    resolve_exchange,
)


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


def _last_bar_utc(frame: pd.DataFrame) -> datetime | None:
    """Naive-UTC datetime of the last bar in a normalized OHLCV frame."""
    if frame is None or frame.empty:
        return None
    try:
        ts = pd.Timestamp(frame.index[-1])
    except (IndexError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tz is None:
        ts = ts.tz_localize(UTC)
    else:
        ts = ts.tz_convert(UTC)
    return ts.to_pydatetime()


def _get_yf_full(ticker: str, *, force_refresh: bool = False) -> pd.DataFrame:
    source = _ensure_full_payload_registered(ticker)
    manager = _managed_cache_manager()
    now_utc = datetime.now(UTC)

    # Session-aware staleness gate. ``get_payload`` only consults the
    # wall-clock TTL — on a fresh-by-TTL but session-stale artifact it
    # would return the prior frame, leaving callers (charts, indicators)
    # one session behind. Peek at the cached artifact's rightmost bar
    # first; if it predates the most-recent expected session close,
    # promote to force_refresh so the upstream is consulted.
    #
    # Only the LAST bar matters for staleness. A 5y historical tail is
    # otherwise indistinguishable from a 1y tail by this check: we look
    # solely at the artifact's right edge.
    #
    # Holiday short-circuit: if a prior auto-stale fetch found no new
    # bar (last_bar unchanged), the serializer's meta records a
    # ``last_session_check_at`` sentinel. As long as that check timestamp
    # is at-or-after the current expected close AND the wall-clock TTL
    # is fresh, skip the re-fetch — we already verified upstream has
    # nothing newer than the cached bar.
    session_stale = False
    # Always peek so we can detect the holiday case after an externally
    # forced re-fetch (e.g. ``get_yf_recent_history`` triggered it).
    pre_last_bar, last_check_at = _peek_artifact_state(ticker)
    if not force_refresh and pre_last_bar is not None and is_cache_stale_by_session(
        pre_last_bar, ticker, now_utc=now_utc
    ):
        schedule = resolve_exchange(ticker)
        expected = latest_expected_close(schedule, now_utc=now_utc)
        ttl_fresh = _artifact_within_ttl(ticker)
        if (
            last_check_at is not None
            and expected is not None
            and last_check_at >= expected
            and ttl_fresh
        ):
            # Sentinel says we already verified after the latest expected
            # close — serve cache without re-fetching.
            session_stale = False
        else:
            session_stale = True

    fetch_force = force_refresh or session_stale
    result = manager.get_payload(source, force_refresh=fetch_force)
    frame = _ts_to_market_frame(result.payload)

    # If an auto-stale (or upstream-forced) fetch returned the same last
    # bar as before — and the bar is still session-stale by calendar —
    # drop a sentinel into the artifact meta so subsequent calls within
    # the TTL window skip the re-fetch (holiday short-circuit).
    if fetch_force and pre_last_bar is not None:
        new_last_bar = _last_bar_utc(frame)
        if (
            new_last_bar is not None
            and new_last_bar.date() == pre_last_bar.date()
            and is_cache_stale_by_session(new_last_bar, ticker, now_utc=now_utc)
        ):
            _write_session_check_sentinel(ticker, checked_at=now_utc)

    return frame


def _peek_artifact_state(ticker: str) -> tuple[datetime | None, datetime | None]:
    """Read just the rightmost bar timestamp + sentinel from the artifact.

    Returns ``(last_bar_utc, last_session_check_at)``. Either may be None.
    Used by the session-staleness gate — we only need the last bar +
    sentinel, never the body of the frame, so this avoids a full
    deserialization on every read.
    """
    import numpy as np

    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    time_path = artifact_dir / "time_i64.npy"
    if not time_path.exists():
        return None, None
    last_bar: datetime | None = None
    try:
        time_values = np.load(time_path, mmap_mode="r")
        if len(time_values) > 0:
            last_bar = datetime.fromtimestamp(int(time_values[-1]), tz=UTC)
    except Exception:
        last_bar = None

    last_check_at: datetime | None = None
    meta_path = artifact_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            raw = meta.get("last_session_check_at")
            if raw:
                last_check_at = datetime.fromisoformat(raw)
                if last_check_at.tzinfo is None:
                    last_check_at = last_check_at.replace(tzinfo=UTC)
        except Exception:
            last_check_at = None

    return last_bar, last_check_at


def _peek_artifact_last_bar(ticker: str) -> datetime | None:
    """Back-compat shim — returns just the last bar without the sentinel."""
    last_bar, _ = _peek_artifact_state(ticker)
    return last_bar


def _artifact_within_ttl(ticker: str) -> bool:
    """True iff the artifact's ``cached_at`` is within the yfinance.full TTL."""
    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    meta_path = artifact_dir / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
        cached_at = meta.get("cached_at")
        if not cached_at:
            return False
        cached_dt = datetime.fromisoformat(cached_at)
        if cached_dt.tzinfo is None:
            cached_dt = cached_dt.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - cached_dt).total_seconds()
        return age <= ttl_for("yfinance.full")
    except Exception:
        return False


def _write_session_check_sentinel(ticker: str, *, checked_at: datetime) -> None:
    """Stamp ``last_session_check_at`` into the artifact's meta.json.

    Best-effort: meta-write failures are swallowed so a cosmetic update
    never breaks the data path. The sentinel is optional — readers that
    don't see it fall back to the existing staleness check.
    """
    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    meta_path = artifact_dir / "meta.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text())
        meta["last_session_check_at"] = checked_at.astimezone(UTC).isoformat()
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception:
        pass


def get_yf_data(ticker: str, *, force_refresh: bool = False) -> pd.DataFrame:
    """
    Get the data from yfinance by its name
    :param ticker: str, ticker or index name
    :param force_refresh: when True, bypass the 24h yfinance.full cache READ
        and re-fetch from upstream. The on-disk artifact is preserved on
        fetch failure so subsequent non-force callers still see the prior
        value.
    :return: DataFrame, indicator data
    """
    return _get_yf_full(ticker.upper(), force_refresh=force_refresh).copy()


def get_yf_recent_history(ticker: str, *, period: str = "3y", force_refresh: bool = False) -> HistoryChunk:
    ticker = ticker.upper()
    from TerraFin.data.cache.serializers import ColumnarTimeSeriesSerializer

    serializer = ColumnarTimeSeriesSerializer()
    artifact_dir = _managed_cache_manager().artifact_path(_V2_NAMESPACE, f"{ticker}/full")
    # Skip the artifact short-circuit when force_refresh is set so we always
    # go through manager.get_payload(force_refresh=True). The artifact is
    # NOT deleted — get_payload simply re-fetches and overwrites atomically.
    cached_chunk: HistoryChunk | None = None
    session_stale = False
    if not force_refresh and artifact_dir.exists():
        recent_frame, has_older = serializer.read_recent(artifact_dir, period, max_age_seconds=ttl_for("yfinance.full"))
        if not recent_frame.empty:
            normalized = _ts_to_market_frame(recent_frame)
            cached_chunk = _history_chunk_from_frame(
                normalized,
                period=period,
                has_older=has_older,
                is_complete=not has_older,
                source_version="managed-artifact-tail",
            )
            # Session-aware staleness: the artifact's last bar predates
            # the most-recent expected session close for this exchange,
            # so a newer bar should exist upstream — fall through to a
            # forced re-fetch (which will overwrite the artifact). If
            # the re-fetch fails we serve the cached chunk anyway, since
            # a stale-but-readable answer beats no answer.
            now_utc = datetime.now(UTC)
            session_stale = is_cache_stale_by_session(
                _last_bar_utc(normalized), ticker, now_utc=now_utc
            )
            if session_stale:
                # Holiday short-circuit: a prior auto-stale fetch may have
                # already verified upstream has no new bar. The serializer
                # writes ``last_session_check_at`` into meta.json in that
                # case; serve cache without re-fetching as long as the
                # sentinel covers the current expected close.
                _, last_check_at = _peek_artifact_state(ticker)
                if last_check_at is not None:
                    schedule = resolve_exchange(ticker)
                    expected = latest_expected_close(schedule, now_utc=now_utc)
                    if expected is not None and last_check_at >= expected:
                        session_stale = False
            if not session_stale:
                return cached_chunk

    fetch_force = force_refresh or session_stale
    try:
        full_df = _get_yf_full(ticker, force_refresh=fetch_force)
    except Exception:
        if session_stale and cached_chunk is not None and not force_refresh:
            # Caller didn't explicitly opt into freshness verification —
            # serve the cached chunk despite the failed re-fetch. Mark
            # the source_version so callers can distinguish a clean cache
            # hit from a stale-on-fetch-failure fallback.
            cached_chunk.source_version = "managed-artifact-tail-stale"
            return cached_chunk
        raise
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
