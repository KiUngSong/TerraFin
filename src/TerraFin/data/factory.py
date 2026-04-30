import logging

import pandas as pd

from TerraFin.env import apply_api_keys

from .contracts import (
    EventList,
    FilingDocument,
    HistoryChunk,
    IndicatorSnapshot,
    TOCEntry,
    chart_output,
)
from .contracts.dataframes import TimeSeriesDataFrame
from .providers.corporate.filings.sec_edgar import get_sec_data, get_sec_toc
from .providers.corporate.fundamentals import get_corporate_data
from .providers.corporate.investor_positioning import PortfolioOutput, get_portfolio_data
from .providers.economic import get_economic_indicator, get_fred_data
from .providers.economic.macro_calendar import get_macro_events_all
from .providers.market import INDEX_MAP, MARKET_INDICATOR_REGISTRY, get_market_data
from .providers.market.yfinance import get_yf_data, get_yf_full_history_backfill, get_yf_recent_history
from .cache.registry import get_cache_manager
from .providers.private_access import PRIVATE_SERIES, get_private_series_current
from .providers.private_access.panels import (
    PANEL_SOURCES,
    SRC_BREADTH,
    SRC_CALENDAR,
    SRC_CAPE,
    SRC_FEAR_GREED,
    SRC_PE_SPREAD,
    SRC_TOP_COMPANIES,
    clear_panel_caches,
    get_calendar_events_merged,
    get_panel_payload,
)
from .providers.private_access.panels import set_calendar_events as _panels_set_calendar_events


logger = logging.getLogger(__name__)


class DataFactory:
    """Pure data acquisition and processing factory."""

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        apply_api_keys(api_keys)

    def _to_timeseries(
        self,
        data: TimeSeriesDataFrame,
        *,
        source_name: str,
    ) -> TimeSeriesDataFrame:
        """Validate that providers return TimeSeriesDataFrame; assign default name if missing."""
        if not isinstance(data, TimeSeriesDataFrame):
            raise TypeError(
                f"Provider {source_name} returned {type(data).__name__}, expected TimeSeriesDataFrame"
            )
        if not data.name:
            data.name = source_name.split(":", 1)[-1]
        return data

    @staticmethod
    def _frame_bounds(frame: TimeSeriesDataFrame) -> tuple[str | None, str | None]:
        if frame.empty or "time" not in frame.columns:
            return None, None
        times = pd.to_datetime(frame["time"], errors="coerce")
        times = times.dropna()
        if times.empty:
            return None, None
        return times.iloc[0].strftime("%Y-%m-%d"), times.iloc[-1].strftime("%Y-%m-%d")

    @staticmethod
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

    def _slice_recent_timeseries(self, frame: TimeSeriesDataFrame, period: str) -> TimeSeriesDataFrame:
        if frame.empty or "time" not in frame.columns:
            return TimeSeriesDataFrame.make_empty()
        end = pd.to_datetime(frame["time"], errors="coerce").dropna()
        if end.empty:
            return TimeSeriesDataFrame.make_empty()
        cutoff = (end.iloc[-1] - self._period_offset(period)).normalize()
        recent = frame[pd.to_datetime(frame["time"], errors="coerce") >= cutoff].reset_index(drop=True)
        if recent.empty:
            recent = frame.tail(1).reset_index(drop=True)
        out = TimeSeriesDataFrame(recent, name=frame.name, chart_meta=frame.chart_meta)
        out.name = frame.name
        return out

    def _fallback_recent_history(self, name: str, period: str, *, source_name: str) -> HistoryChunk:
        frame = self._to_timeseries(self.get(name), source_name=source_name)
        recent = self._slice_recent_timeseries(frame, period)
        has_older = not frame.empty and len(recent) < len(frame)
        loaded_start, loaded_end = self._frame_bounds(recent)
        return HistoryChunk(
            frame=recent,
            loaded_start=loaded_start,
            loaded_end=loaded_end,
            requested_period=period,
            is_complete=not has_older,
            has_older=has_older,
            source_version="factory-fallback",
        )

    def _fallback_backfill_history(self, name: str, loaded_start: str | None, *, source_name: str) -> HistoryChunk:
        frame = self._to_timeseries(self.get(name), source_name=source_name)
        if frame.empty or "time" not in frame.columns:
            return HistoryChunk(
                frame=TimeSeriesDataFrame.make_empty(),
                loaded_start=None,
                loaded_end=None,
                requested_period=None,
                is_complete=True,
                has_older=False,
                source_version="factory-fallback",
            )
        if loaded_start:
            cutoff = pd.to_datetime(loaded_start, errors="coerce")
            if pd.isna(cutoff):
                older = TimeSeriesDataFrame.make_empty()
            else:
                older = TimeSeriesDataFrame(
                    frame[pd.to_datetime(frame["time"], errors="coerce") < cutoff].reset_index(drop=True),
                    name=frame.name,
                    chart_meta=frame.chart_meta,
                )
        else:
            older = TimeSeriesDataFrame(frame.reset_index(drop=True), name=frame.name, chart_meta=frame.chart_meta)
        older.name = frame.name
        full_start, full_end = self._frame_bounds(frame)
        return HistoryChunk(
            frame=older,
            loaded_start=full_start,
            loaded_end=full_end,
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="factory-fallback",
        )

    @staticmethod
    def _resolve_market_ticker(name: str) -> str | None:
        if name in MARKET_INDICATOR_REGISTRY:
            indicator = MARKET_INDICATOR_REGISTRY[name]
            if indicator.get_data is get_yf_data:
                return indicator.key
            return None
        if name in INDEX_MAP:
            return INDEX_MAP.get(name, name)
        if " " not in name or name.upper() == name or any(char in name for char in (".", "-", "^", "=")):
            return name
        return None

    @staticmethod
    def _is_economic_indicator(name: str) -> bool:
        from .providers.economic import indicator_registry

        return name in indicator_registry._indicators

    @chart_output(source_name="auto", query_arg="name")
    def get(self, name: str) -> TimeSeriesDataFrame:
        """Unified data access — resolves name across all registries.

        Lookup order:
        1. Market indicator registry (VIX, Fear & Greed, etc.)
        2. Economic indicator registry (Unemployment Rate, M2, etc.)
        3. Index map (S&P 500, Kospi, etc.)
        4. Raw yfinance ticker (AAPL, MSFT, etc.)
        """
        # 1. Market indicators
        if name in MARKET_INDICATOR_REGISTRY:
            return get_market_data(name)

        # 2. Economic indicators
        try:
            return get_economic_indicator(name)
        except ValueError:
            pass

        # 3. Index map + yfinance fallback
        return get_market_data(name)

    @chart_output(source_name="fred", query_arg="indicator_name")
    def get_fred_data(self, indicator_name: str) -> TimeSeriesDataFrame:
        """Get data from the FRED database directly."""
        return get_fred_data(indicator_name)

    @chart_output(source_name="economic", query_arg="indicator_name")
    def get_economic_data(self, indicator_name: str) -> TimeSeriesDataFrame:
        """Get economic data from the data layer."""
        return get_economic_indicator(indicator_name)

    @chart_output(source_name="market", query_arg="ticker_or_index_name_or_indicator_name")
    def get_market_data(self, ticker_or_index_name_or_indicator_name: str) -> TimeSeriesDataFrame:
        """Get market data from the data layer."""
        return get_market_data(ticker_or_index_name_or_indicator_name)

    def get_recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
        """Return a recent history seed window for progressive chart loading."""
        if name in MARKET_INDICATOR_REGISTRY:
            indicator = MARKET_INDICATOR_REGISTRY[name]
            if indicator.get_recent_history is not None:
                chunk = indicator.get_recent_history(indicator.key, period=period)
                chunk.frame.name = name.split(":", 1)[-1]
                return chunk
        if self._is_economic_indicator(name):
            return self._fallback_recent_history(name, period, source_name=f"economic:{name}")
        ticker = self._resolve_market_ticker(name)
        if ticker is not None:
            try:
                chunk = get_yf_recent_history(ticker, period=period)
                chunk.frame.name = name.split(":", 1)[-1]
                return chunk
            except ValueError:
                raise
            except Exception:
                logger.exception("Falling back to full recent-history slice for %s", name)
        return self._fallback_recent_history(name, period, source_name=f"auto:{name}")

    def get_full_history_backfill(self, name: str, *, loaded_start: str | None = None) -> HistoryChunk:
        """Return older history to prepend onto an already-seeded chart."""
        if name in MARKET_INDICATOR_REGISTRY:
            indicator = MARKET_INDICATOR_REGISTRY[name]
            if indicator.get_full_history_backfill is not None:
                chunk = indicator.get_full_history_backfill(indicator.key, loaded_start=loaded_start)
                chunk.frame.name = name.split(":", 1)[-1]
                return chunk
        if self._is_economic_indicator(name):
            return self._fallback_backfill_history(name, loaded_start, source_name=f"economic:{name}")
        ticker = self._resolve_market_ticker(name)
        if ticker is not None:
            try:
                chunk = get_yf_full_history_backfill(ticker, loaded_start=loaded_start)
                chunk.frame.name = name.split(":", 1)[-1]
                return chunk
            except ValueError:
                raise
            except Exception:
                logger.exception("Falling back to full history slice for %s", name)
        return self._fallback_backfill_history(name, loaded_start, source_name=f"auto:{name}")

    def get_corporate_data(
        self, ticker: str, statement_type: str = "income", period: str = "annual"
    ):
        """Get corporate data — returns a FinancialStatementFrame."""
        return get_corporate_data(ticker, statement_type, period=period)

    def get_portfolio_data(self, guru_name: str, filing_date: str | None = None) -> PortfolioOutput:
        """Get portfolio data from the data layer."""
        return get_portfolio_data(guru_name, filing_date=filing_date)

    def get_filing(self, ticker: str, filing_type: str = "10-K") -> FilingDocument:
        """Return a parsed SEC filing as a FilingDocument."""
        return get_sec_data(ticker, filing_type=filing_type)

    def get_filing_toc(self, ticker: str, filing_type: str = "10-K") -> list[TOCEntry]:
        """Return the table of contents for a SEC filing."""
        return get_sec_toc(ticker, filing_type=filing_type)

    def get_macro_events(self, start: str | None = None, end: str | None = None) -> EventList:
        """Return macro calendar events, optionally filtered by ISO date bounds."""
        events = get_macro_events_all()
        if start is None and end is None:
            return events
        start_ts = pd.to_datetime(start, utc=True, errors="coerce") if start else None
        end_ts = pd.to_datetime(end, utc=True, errors="coerce") if end else None
        filtered = [
            event
            for event in events
            if (start_ts is None or pd.Timestamp(event.start) >= start_ts)
            and (end_ts is None or pd.Timestamp(event.start) <= end_ts)
        ]
        return EventList(events=filtered)

    def get_indicator_snapshot(self, name: str) -> IndicatorSnapshot:
        """Return a current scalar snapshot for a private-series indicator."""
        spec = PRIVATE_SERIES.get(name)
        if spec is None:
            raise ValueError(f"Unknown indicator snapshot: {name}")
        return get_private_series_current(spec)

    # -----------------------------------------------------------------
    # Private-source panel payloads (non-time-series). Exposed via
    # `get_panel_data` plus calendar-specific helpers since calendar
    # merges two cached sources.
    # -----------------------------------------------------------------

    _PANEL_NAME_TO_SOURCE: dict[str, str] = {
        "market_breadth": SRC_BREADTH,
        "trailing_forward_pe": SRC_PE_SPREAD,
        "cape": SRC_CAPE,
        "fear_greed": SRC_FEAR_GREED,
        "top_companies": SRC_TOP_COMPANIES,
    }

    def get_panel_data(self, name: str):
        """Return the cached panel payload (dict or list[dict]) for a non-time-series widget."""
        source = self._PANEL_NAME_TO_SOURCE.get(name)
        if source is None:
            raise ValueError(f"Unknown panel: {name}")
        payload = get_panel_payload(get_cache_manager(), source)
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        if isinstance(payload, dict):
            return dict(payload)
        return payload

    def get_calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: set[str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return merged calendar events (private source + enriched macro)."""
        return get_calendar_events_merged(
            get_cache_manager(),
            year=year,
            month=month,
            categories=categories,
            limit=limit,
        )

    def set_calendar_events(self, events: list[dict]) -> None:
        _panels_set_calendar_events(get_cache_manager(), events)

    def refresh_panel(self, name: str) -> None:
        source = self._PANEL_NAME_TO_SOURCE.get(name) or (name if name in PANEL_SOURCES else None)
        if source is None:
            raise ValueError(f"Unknown panel: {name}")
        get_cache_manager().refresh_payload(source)

    def clear_panel_caches(self) -> None:
        clear_panel_caches(get_cache_manager())


_DEFAULT_FACTORY: DataFactory | None = None


def get_data_factory() -> DataFactory:
    """Return the process-wide DataFactory singleton, lazy-initialized."""
    global _DEFAULT_FACTORY
    if _DEFAULT_FACTORY is None:
        _DEFAULT_FACTORY = DataFactory()
    return _DEFAULT_FACTORY
