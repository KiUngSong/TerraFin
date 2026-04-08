import logging

import pandas as pd

from TerraFin.env import apply_api_keys

from .contracts import HistoryChunk, chart_output
from .contracts.dataframes import TimeSeriesDataFrame
from .providers.corporate.fundamentals import get_corporate_data
from .providers.corporate.investor_positioning import PortfolioOutput, get_portfolio_data
from .providers.economic import get_economic_indicator, get_fred_data
from .providers.market import INDEX_MAP, MARKET_INDICATOR_REGISTRY, get_market_data
from .providers.market.yfinance import get_yf_data, get_yf_full_history_backfill, get_yf_recent_history


logger = logging.getLogger(__name__)


class DataFactory:
    """Pure data acquisition and processing factory."""

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        apply_api_keys(api_keys)

    def _to_timeseries(
        self,
        data: pd.DataFrame | TimeSeriesDataFrame,
        *,
        source_name: str,
    ) -> TimeSeriesDataFrame:
        """Normalize source outputs into a consistent chart-ready frame."""
        try:
            if isinstance(data, TimeSeriesDataFrame):
                if not data.name:
                    data.name = source_name.split(":", 1)[-1]
                return data
            out = TimeSeriesDataFrame(data)
            out.name = source_name.split(":", 1)[-1]
            return out
        except Exception as exc:
            logger.warning("Failed to normalize data from %s. Returning empty frame. error=%s", source_name, exc)
            out = TimeSeriesDataFrame.make_empty()
            out.name = source_name.split(":", 1)[-1]
            return out

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
    ) -> pd.DataFrame | None:
        """Get corporate data from the data layer."""
        return get_corporate_data(ticker, statement_type, period=period)

    def get_portfolio_data(self, guru_name: str) -> PortfolioOutput:
        """Get portfolio data from the data layer."""
        return get_portfolio_data(guru_name)
