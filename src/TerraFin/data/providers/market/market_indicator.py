from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame

from .yfinance import get_yf_data, get_yf_full_history_backfill, get_yf_recent_history


VOL_REGIME_ZONES = [
    {"from": 0.0, "to": 20.0, "color": "rgba(76,175,80,0.15)"},
    {"from": 80.0, "to": 100.0, "color": "rgba(244,67,54,0.15)"},
]


@dataclass
class MarketIndicator:
    """Market indicator"""

    description: str = ""  # description of the indicator
    key: str = ""  # required key value to get data. e.g. id for fred
    get_data: Callable = get_yf_data  # function to get data
    get_recent_history: Callable | None = None
    get_full_history_backfill: Callable | None = None


def _frame_bounds(frame: TimeSeriesDataFrame) -> tuple[str | None, str | None]:
    if frame.empty or "time" not in frame.columns:
        return None, None
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return None, None
    return times.iloc[0].strftime("%Y-%m-%d"), times.iloc[-1].strftime("%Y-%m-%d")


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


def _slice_recent_timeseries(frame: TimeSeriesDataFrame, period: str) -> TimeSeriesDataFrame:
    if frame.empty or "time" not in frame.columns:
        return TimeSeriesDataFrame.make_empty()
    times = pd.to_datetime(frame["time"], errors="coerce").dropna()
    if times.empty:
        return TimeSeriesDataFrame.make_empty()
    cutoff = (times.iloc[-1] - _period_offset(period)).normalize()
    recent = frame[pd.to_datetime(frame["time"], errors="coerce") >= cutoff].reset_index(drop=True)
    if recent.empty:
        recent = frame.tail(1).reset_index(drop=True)
    out = TimeSeriesDataFrame(recent, name=frame.name, chart_meta=frame.chart_meta)
    return out


def _copy_history_chunk(
    chunk: HistoryChunk,
    *,
    frame: TimeSeriesDataFrame,
    loaded_start: str | None,
    loaded_end: str | None,
    requested_period: str | None,
    is_complete: bool,
    has_older: bool,
    source_version: str,
) -> HistoryChunk:
    return HistoryChunk(
        frame=frame,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        requested_period=requested_period,
        is_complete=is_complete,
        has_older=has_older,
        source_version=source_version,
    )


def _with_chart_meta(frame: TimeSeriesDataFrame, *, zones: list[dict] | None = None) -> TimeSeriesDataFrame:
    chart_meta = frame.chart_meta
    if zones:
        chart_meta["zones"] = [dict(zone) for zone in zones]
    frame.chart_meta = chart_meta
    return frame


def _timeseries_from_market_frame(data: pd.DataFrame | TimeSeriesDataFrame, *, name: str) -> TimeSeriesDataFrame:
    frame = data if isinstance(data, TimeSeriesDataFrame) else TimeSeriesDataFrame(data)
    frame.name = name
    return frame


def _compute_vol_regime_frame(data: pd.DataFrame | TimeSeriesDataFrame) -> TimeSeriesDataFrame:
    from TerraFin.analytics.analysis.technical import percentile_rank

    vix_df = _timeseries_from_market_frame(data, name="Vol Regime")
    if len(vix_df) < 127:
        empty = TimeSeriesDataFrame.make_empty()
        empty.name = "Vol Regime"
        return _with_chart_meta(empty, zones=VOL_REGIME_ZONES)
    offset, ranks = percentile_rank(vix_df["close"].tolist(), window=126)
    dates = pd.to_datetime(vix_df["time"], errors="coerce").iloc[offset:]
    df = pd.DataFrame({"time": dates.iloc[: len(ranks)], "close": ranks})
    out = TimeSeriesDataFrame(df, name="Vol Regime", chart_meta={"zones": VOL_REGIME_ZONES})
    return out


def _compute_vvix_vix_ratio_frame(
    vvix_data: pd.DataFrame | TimeSeriesDataFrame,
    vix_data: pd.DataFrame | TimeSeriesDataFrame,
) -> TimeSeriesDataFrame:
    vvix_df = _timeseries_from_market_frame(vvix_data, name="VVIX/VIX Ratio")
    vix_df = _timeseries_from_market_frame(vix_data, name="VVIX/VIX Ratio")

    vvix = vvix_df[["time", "close"]].rename(columns={"close": "vvix"})
    vix = vix_df[["time", "close"]].rename(columns={"close": "vix"})
    merged = vvix.merge(vix, on="time", how="inner")
    if merged.empty:
        empty = TimeSeriesDataFrame.make_empty()
        empty.name = "VVIX/VIX Ratio"
        return empty

    ratio = merged["vvix"] / merged["vix"].replace(0, np.nan)
    out = TimeSeriesDataFrame(pd.DataFrame({"time": merged["time"], "close": ratio.dropna()}), name="VVIX/VIX Ratio")
    return out


def _min_date(*values: str | None) -> str | None:
    dates = [pd.Timestamp(value) for value in values if value]
    if not dates:
        return None
    return min(dates).strftime("%Y-%m-%d")


def _vol_regime_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    # The percentile-rank calculation needs lookback before the visible 3Y seed.
    base_period = "5y" if period == "3y" else period
    base_chunk = get_yf_recent_history("^VIX", period=base_period)
    full_frame = _compute_vol_regime_frame(base_chunk.frame)
    recent_frame = _slice_recent_timeseries(full_frame, period)
    loaded_start, loaded_end = _frame_bounds(recent_frame)
    has_older = base_chunk.has_older or len(recent_frame) < len(full_frame)
    return _copy_history_chunk(
        base_chunk,
        frame=recent_frame,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        requested_period=period,
        is_complete=not has_older,
        has_older=has_older,
        source_version=f"{base_chunk.source_version}:vol-regime",
    )


def _vol_regime_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    base_chunk = get_yf_full_history_backfill("^VIX", loaded_start=loaded_start)
    older_frame = _compute_vol_regime_frame(base_chunk.frame)
    derived_start, _ = _frame_bounds(older_frame)
    return _copy_history_chunk(
        base_chunk,
        frame=older_frame,
        loaded_start=derived_start,
        loaded_end=base_chunk.loaded_end,
        requested_period=None,
        is_complete=True,
        has_older=False,
        source_version=f"{base_chunk.source_version}:vol-regime",
    )


def _vvix_vix_ratio_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    vvix_chunk = get_yf_recent_history("^VVIX", period=period)
    vix_chunk = get_yf_recent_history("^VIX", period=period)
    frame = _compute_vvix_vix_ratio_frame(vvix_chunk.frame, vix_chunk.frame)
    loaded_start, loaded_end = _frame_bounds(frame)
    has_older = vvix_chunk.has_older or vix_chunk.has_older
    return HistoryChunk(
        frame=frame,
        loaded_start=loaded_start,
        loaded_end=loaded_end,
        requested_period=period,
        is_complete=not has_older,
        has_older=has_older,
        source_version=f"{vvix_chunk.source_version}:{vix_chunk.source_version}:vvix-vix-ratio",
    )


def _vvix_vix_ratio_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    vvix_chunk = get_yf_full_history_backfill("^VVIX", loaded_start=loaded_start)
    vix_chunk = get_yf_full_history_backfill("^VIX", loaded_start=loaded_start)
    frame = _compute_vvix_vix_ratio_frame(vvix_chunk.frame, vix_chunk.frame)
    derived_start, _ = _frame_bounds(frame)
    return HistoryChunk(
        frame=frame,
        loaded_start=derived_start,
        loaded_end=_min_date(vvix_chunk.loaded_end, vix_chunk.loaded_end),
        requested_period=None,
        is_complete=True,
        has_older=False,
        source_version=f"{vvix_chunk.source_version}:{vix_chunk.source_version}:vvix-vix-ratio",
    )


def _fetch_vol_regime(_key: str):
    """VIX 6-month percentile rank (0-100)."""
    return _compute_vol_regime_frame(get_yf_data("^VIX"))


def _fetch_vvix_vix_ratio(_key: str):
    """Compute VVIX/VIX ratio from yfinance data."""
    return _compute_vvix_vix_ratio_frame(get_yf_data("^VVIX"), get_yf_data("^VIX"))


def _fetch_fear_greed(_key: str):
    """Fetch Fear & Greed data via private access endpoint."""
    from TerraFin.data.providers.private_access.fear_greed import get_fear_greed_frame

    return get_fear_greed_frame()


def _fetch_net_breadth(_key: str):
    """Fetch Net Breadth history via private access endpoint."""
    from TerraFin.data.providers.private_access.net_breadth import get_net_breadth_frame

    return get_net_breadth_frame()


def _fetch_cape(_key: str):
    """Fetch CAPE series via private access endpoint."""
    from TerraFin.data.providers.private_access.cape import get_cape_frame

    return get_cape_frame()


def _fetch_trailing_forward_pe(_key: str):
    """Fetch trailing-forward P/E spread series via private access endpoint."""
    from TerraFin.data.providers.private_access.trailing_forward_pe import get_trailing_forward_pe_frame

    return get_trailing_forward_pe_frame()


def _fear_greed_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    from TerraFin.data.providers.private_access.fear_greed import get_fear_greed_recent_history

    return get_fear_greed_recent_history(period=period)


def _fear_greed_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    from TerraFin.data.providers.private_access.fear_greed import get_fear_greed_full_history_backfill

    return get_fear_greed_full_history_backfill(loaded_start=loaded_start)


def _net_breadth_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    from TerraFin.data.providers.private_access.net_breadth import get_net_breadth_recent_history

    return get_net_breadth_recent_history(period=period)


def _net_breadth_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    from TerraFin.data.providers.private_access.net_breadth import get_net_breadth_full_history_backfill

    return get_net_breadth_full_history_backfill(loaded_start=loaded_start)


def _cape_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    from TerraFin.data.providers.private_access.cape import get_cape_recent_history

    return get_cape_recent_history(period=period)


def _cape_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    from TerraFin.data.providers.private_access.cape import get_cape_full_history_backfill

    return get_cape_full_history_backfill(loaded_start=loaded_start)


def _trailing_forward_pe_recent_history(_key: str, *, period: str = "3y") -> HistoryChunk:
    from TerraFin.data.providers.private_access.trailing_forward_pe import get_trailing_forward_pe_recent_history

    return get_trailing_forward_pe_recent_history(period=period)


def _trailing_forward_pe_full_history_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
    from TerraFin.data.providers.private_access.trailing_forward_pe import (
        get_trailing_forward_pe_full_history_backfill,
    )

    return get_trailing_forward_pe_full_history_backfill(loaded_start=loaded_start)


MARKET_INDICATOR_REGISTRY = {
    "VIX": MarketIndicator(description="VIX: CBOE Volatility Index", key="^VIX"),
    "VVIX": MarketIndicator(description="VVIX: CBOE VIX Volatility", key="^VVIX"),
    "SKEW": MarketIndicator(description="SKEW: Measures tail risk", key="^SKEW"),
    "Treasury-13W": MarketIndicator(description="Treasury-13W", key="^IRX"),
    "Treasury-2Y": MarketIndicator(description="Treasury-2Y", key="2YY=F"),
    "Treasury-5Y": MarketIndicator(description="Treasury-5Y", key="^FVX"),
    "Treasury-10Y": MarketIndicator(description="Treasury-10Y", key="^TNX"),
    "Treasury-30Y": MarketIndicator(description="Treasury-30Y", key="^TYX"),
    "MOVE": MarketIndicator(description="MOVE: ICE BofA MOVE Index (bond market implied volatility)", key="^MOVE"),
    "Vol Regime": MarketIndicator(
        description="VIX 6-month percentile rank (0-100). Calm below 20 and elevated above 80.",
        key="vol-regime",
        get_data=_fetch_vol_regime,
        get_recent_history=_vol_regime_recent_history,
        get_full_history_backfill=_vol_regime_full_history_backfill,
    ),
    "VVIX/VIX Ratio": MarketIndicator(
        description="VVIX/VIX Ratio: vol-of-vol relative to vol. High values (>6) indicate asymmetric VIX upside potential.",
        key="vvix-vix-ratio",
        get_data=_fetch_vvix_vix_ratio,
        get_recent_history=_vvix_vix_ratio_recent_history,
        get_full_history_backfill=_vvix_vix_ratio_full_history_backfill,
    ),
    "Fear & Greed": MarketIndicator(
        description="CNN Fear & Greed Index (0-100)",
        key="fear-greed",
        get_data=_fetch_fear_greed,
        get_recent_history=_fear_greed_recent_history,
        get_full_history_backfill=_fear_greed_full_history_backfill,
    ),
    "Net Breadth": MarketIndicator(
        description="Daily S&P 500 net breadth: advancers minus decliners as a share of the basket.",
        key="net-breadth",
        get_data=_fetch_net_breadth,
        get_recent_history=_net_breadth_recent_history,
        get_full_history_backfill=_net_breadth_full_history_backfill,
    ),
    "CAPE": MarketIndicator(
        description="CAPE (Shiller PE10): cyclically adjusted price-to-earnings ratio.",
        key="cape",
        get_data=_fetch_cape,
        get_recent_history=_cape_recent_history,
        get_full_history_backfill=_cape_full_history_backfill,
    ),
    "Trailing-Forward P/E Spread": MarketIndicator(
        description="Trailing-forward P/E spread snapshot history for top market-cap companies.",
        key="trailing-forward-pe-spread",
        get_data=_fetch_trailing_forward_pe,
        get_recent_history=_trailing_forward_pe_recent_history,
        get_full_history_backfill=_trailing_forward_pe_full_history_backfill,
    ),
}
