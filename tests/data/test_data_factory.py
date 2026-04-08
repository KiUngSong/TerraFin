import inspect

import pandas as pd

import TerraFin.data.factory as factory_module
import TerraFin.data.providers.market.market_indicator as market_indicator_module
from TerraFin.data import DataFactory
from TerraFin.data.contracts import HistoryChunk
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


def _assert_timeseries_contract(df: TimeSeriesDataFrame) -> None:
    assert isinstance(df, TimeSeriesDataFrame)

    if df.empty:
        # Empty is an accepted fallback contract.
        return

    assert "time" in df.columns
    assert "close" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["time"])
    assert df["time"].is_monotonic_increasing
    assert not df["time"].duplicated().any()


def test_timeseries_dataframe_normalizes_index_based_data() -> None:
    raw = pd.DataFrame(
        {"Close": [1.0, 1.1, 1.2]},
        index=["2024-01-03", "2024-01-01", "2024-01-01"],  # duplicate time included intentionally
    )
    df = TimeSeriesDataFrame(raw)

    _assert_timeseries_contract(df)
    assert list(df.columns) == ["time", "close"]
    assert len(df) == 2


def test_chart_output_methods_are_marked() -> None:
    chart_methods = {
        name
        for name, method in inspect.getmembers(DataFactory, predicate=inspect.isfunction)
        if getattr(method, "__chart_output__", False)
    }
    assert chart_methods == {"get", "get_fred_data", "get_economic_data", "get_market_data"}


def test_get_market_data_contract_stubbed(monkeypatch) -> None:
    def _stub_market_data(_name: str) -> pd.DataFrame:
        return pd.DataFrame({"Close": [100.0, 101.5, 103.0]}, index=["2026-01-01", "2026-01-02", "2026-01-03"])

    monkeypatch.setattr(factory_module, "get_market_data", _stub_market_data)
    factory = DataFactory()
    df = factory.get_market_data("S&P 500")
    _assert_timeseries_contract(df)


def test_get_fred_data_contract_stubbed(monkeypatch) -> None:
    def _stub_fred_data(_name: str) -> pd.DataFrame:
        return pd.DataFrame({"Close": [2.5, 2.6, 2.7]}, index=["2026-01-01", "2026-01-02", "2026-01-03"])

    monkeypatch.setattr(factory_module, "get_fred_data", _stub_fred_data)
    factory = DataFactory()
    df = factory.get_fred_data("T10Y2Y")
    _assert_timeseries_contract(df)


def test_get_economic_data_contract_stubbed(monkeypatch) -> None:
    def _stub_economic_data(_name: str) -> pd.DataFrame:
        return pd.DataFrame({"Close": [1.0, 0.9, 0.8]}, index=["2026-01-01", "2026-01-02", "2026-01-03"])

    monkeypatch.setattr(factory_module, "get_economic_indicator", _stub_economic_data)
    factory = DataFactory()
    df = factory.get_economic_data("Term Spread")
    _assert_timeseries_contract(df)


def test_get_recent_history_contract_stubbed(monkeypatch) -> None:
    def _stub_recent(_ticker: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": ["2024-01-01", "2025-01-01", "2026-01-01"],
                    "close": [100.0, 120.0, 140.0],
                }
            )
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2026-01-01",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="test",
        )

    monkeypatch.setattr(factory_module, "get_yf_recent_history", _stub_recent)

    chunk = DataFactory().get_recent_history("AAPL", period="3y")

    _assert_timeseries_contract(chunk.frame)
    assert chunk.loaded_start == "2024-01-01"
    assert chunk.loaded_end == "2026-01-01"
    assert chunk.has_older is True
    assert chunk.requested_period == "3y"


def test_get_full_history_backfill_contract_stubbed(monkeypatch) -> None:
    def _stub_backfill(_ticker: str, *, loaded_start: str | None = None) -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": ["2021-01-01", "2022-01-01", "2023-01-01"],
                    "close": [80.0, 90.0, 95.0],
                }
            )
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2021-01-01",
            loaded_end="2026-01-01",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="test",
        )

    monkeypatch.setattr(factory_module, "get_yf_full_history_backfill", _stub_backfill)

    chunk = DataFactory().get_full_history_backfill("AAPL", loaded_start="2024-01-01")

    _assert_timeseries_contract(chunk.frame)
    assert chunk.loaded_start == "2021-01-01"
    assert chunk.loaded_end == "2026-01-01"
    assert chunk.is_complete is True


def test_get_recent_history_uses_custom_market_indicator_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["Vol Regime"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_recent(_key: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.date_range("2023-01-01", periods=5, freq="D"),
                    "close": [10.0, 15.0, 25.0, 45.0, 85.0],
                }
            ),
            name="Vol Regime",
            chart_meta={"zones": market_indicator_module.VOL_REGIME_ZONES},
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2023-01-01",
            loaded_end="2023-01-05",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="custom-recent",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_recent_history", _stub_recent)

    chunk = DataFactory().get_recent_history("Vol Regime", period="3y")

    assert chunk.source_version == "custom-recent"
    assert chunk.frame.name == "Vol Regime"
    assert chunk.frame.chart_meta["zones"] == market_indicator_module.VOL_REGIME_ZONES
    assert chunk.has_older is True


def test_get_full_history_backfill_uses_custom_market_indicator_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["VVIX/VIX Ratio"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.date_range("2021-01-01", periods=3, freq="D"),
                    "close": [4.9, 5.1, 5.3],
                }
            ),
            name="VVIX/VIX Ratio",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2021-01-01",
            loaded_end="2026-01-01",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="custom-full",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_full_history_backfill", _stub_backfill)

    chunk = DataFactory().get_full_history_backfill("VVIX/VIX Ratio", loaded_start="2024-01-01")

    assert chunk.source_version == "custom-full"
    assert chunk.frame.name == "VVIX/VIX Ratio"
    assert chunk.loaded_start == "2021-01-01"
    assert chunk.is_complete is True


def test_get_recent_history_uses_fear_greed_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["Fear & Greed"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_recent(_key: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.date_range("2024-01-01", periods=3, freq="D"),
                    "close": [25.0, 45.0, 65.0],
                }
            ),
            name="Fear & Greed",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2024-01-03",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="fear-greed-recent",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_recent_history", _stub_recent)

    chunk = DataFactory().get_recent_history("Fear & Greed", period="3y")

    assert chunk.source_version == "fear-greed-recent"
    assert chunk.frame.name == "Fear & Greed"
    assert chunk.has_older is True


def test_get_recent_history_uses_cape_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["CAPE"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_recent(_key: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.to_datetime(["2024-01-01", "2025-01-01", "2026-01-01"]),
                    "close": [28.5, 31.2, 33.1],
                }
            ),
            name="CAPE",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2026-01-01",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="cape-recent",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_recent_history", _stub_recent)

    chunk = DataFactory().get_recent_history("CAPE", period="3y")

    assert chunk.source_version == "cape-recent"
    assert chunk.frame.name == "CAPE"
    assert chunk.has_older is True


def test_get_recent_history_uses_net_breadth_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["Net Breadth"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_recent(_key: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                    "close": [-12.0, 4.5, 16.2],
                }
            ),
            name="Net Breadth",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2024-01-03",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="net-breadth-recent",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_recent_history", _stub_recent)

    chunk = DataFactory().get_recent_history("Net Breadth", period="3y")

    assert chunk.source_version == "net-breadth-recent"
    assert chunk.frame.name == "Net Breadth"
    assert chunk.has_older is True


def test_get_recent_history_uses_economic_indicator_for_rrp(monkeypatch) -> None:
    def _forbid_recent_history(_ticker: str, *, period: str = "3y") -> HistoryChunk:
        _ = period
        raise AssertionError("yfinance recent-history loader should not run for economic indicators")

    def _stub_economic_indicator(name: str) -> pd.DataFrame:
        assert name == "RRP"
        return pd.DataFrame(
            {
                "Close": [2.0, 4.0, 6.0, 8.0],
            },
            index=["2020-01-01", "2022-01-01", "2024-01-01", "2026-01-01"],
        )

    monkeypatch.setattr(factory_module, "get_yf_recent_history", _forbid_recent_history)
    monkeypatch.setattr(factory_module, "get_economic_indicator", _stub_economic_indicator)

    chunk = DataFactory().get_recent_history("RRP", period="3y")

    assert chunk.frame.name == "RRP"
    assert chunk.loaded_start == "2024-01-01"
    assert chunk.loaded_end == "2026-01-01"
    assert chunk.has_older is True
    assert chunk.requested_period == "3y"
    assert chunk.frame["close"].tolist() == [6.0, 8.0]


def test_get_full_history_backfill_uses_trailing_forward_pe_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["Trailing-Forward P/E Spread"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.to_datetime(["2022-01-01", "2023-01-01", "2024-01-01"]),
                    "close": [1.1, 0.8, 0.5],
                }
            ),
            name="Trailing-Forward P/E Spread",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2022-01-01",
            loaded_end="2024-01-01",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="pe-spread-full",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_full_history_backfill", _stub_backfill)

    chunk = DataFactory().get_full_history_backfill("Trailing-Forward P/E Spread", loaded_start="2025-01-01")

    assert chunk.source_version == "pe-spread-full"
    assert chunk.frame.name == "Trailing-Forward P/E Spread"
    assert chunk.is_complete is True


def test_get_full_history_backfill_uses_economic_indicator_for_rrp(monkeypatch) -> None:
    def _forbid_full_history(_ticker: str, *, loaded_start: str | None = None) -> HistoryChunk:
        _ = loaded_start
        raise AssertionError("yfinance full-history loader should not run for economic indicators")

    def _stub_economic_indicator(name: str) -> pd.DataFrame:
        assert name == "RRP"
        return pd.DataFrame(
            {
                "Close": [2.0, 4.0, 6.0, 8.0],
            },
            index=["2020-01-01", "2022-01-01", "2024-01-01", "2026-01-01"],
        )

    monkeypatch.setattr(factory_module, "get_yf_full_history_backfill", _forbid_full_history)
    monkeypatch.setattr(factory_module, "get_economic_indicator", _stub_economic_indicator)

    chunk = DataFactory().get_full_history_backfill("RRP", loaded_start="2024-01-01")

    assert chunk.frame.name == "RRP"
    assert chunk.loaded_start == "2020-01-01"
    assert chunk.loaded_end == "2026-01-01"
    assert chunk.is_complete is True
    assert chunk.frame["close"].tolist() == [2.0, 4.0]


def test_get_full_history_backfill_uses_net_breadth_progressive_hook(monkeypatch) -> None:
    indicator = factory_module.MARKET_INDICATOR_REGISTRY["Net Breadth"]

    def _forbid_fallback(_key: str):
        raise AssertionError("fallback market-data loader should not run")

    def _stub_backfill(_key: str, *, loaded_start: str | None = None) -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03"]),
                    "close": [-18.0, -6.0, 9.0],
                }
            ),
            name="Net Breadth",
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2023-01-01",
            loaded_end="2023-01-03",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="net-breadth-full",
        )

    monkeypatch.setattr(indicator, "get_data", _forbid_fallback)
    monkeypatch.setattr(indicator, "get_full_history_backfill", _stub_backfill)

    chunk = DataFactory().get_full_history_backfill("Net Breadth", loaded_start="2025-01-01")

    assert chunk.source_version == "net-breadth-full"
    assert chunk.frame.name == "Net Breadth"
    assert chunk.is_complete is True
