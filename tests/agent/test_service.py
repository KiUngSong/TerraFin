import pandas as pd

import TerraFin.agent.service as agent_service
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame


def _make_frame(name: str = "TEST", periods: int = 120) -> TimeSeriesDataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    base = 100.0
    frame = TimeSeriesDataFrame(
        pd.DataFrame(
            {
                "time": dates,
                "open": [base + idx * 0.2 for idx in range(periods)],
                "high": [base + idx * 0.2 + 1 for idx in range(periods)],
                "low": [base + idx * 0.2 - 1 for idx in range(periods)],
                "close": [base + idx * 0.25 for idx in range(periods)],
                "volume": [1000 + idx for idx in range(periods)],
            }
        )
    )
    frame.name = name
    return frame


class _FakeDataFactory:
    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs

    def get(self, name: str):
        return _make_frame(name, periods=180)

    def get_recent_history(self, name: str, period: str = "3y"):
        _ = period
        frame = _make_frame(name, periods=90)
        return HistoryChunk(
            frame=frame,
            loaded_start="2024-01-01",
            loaded_end="2024-05-03",
            requested_period="3y",
            is_complete=False,
            has_older=True,
            source_version="recent-cache",
        )

    def get_full_history_backfill(self, name: str, loaded_start: str | None = None):
        _ = loaded_start
        frame = _make_frame(name, periods=180)
        return HistoryChunk(
            frame=frame,
            loaded_start="2023-07-03",
            loaded_end="2024-05-03",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="full-cache",
        )

    def get_fred_data(self, name: str):
        frame = _make_frame(name, periods=12)[["time", "close"]]
        frame = TimeSeriesDataFrame(frame)
        frame.name = name
        return frame


class _FakePrivateDataService:
    def get_market_breadth(self):
        return [{"label": "Advancers", "value": "320", "tone": "#047857"}]

    def get_calendar_events(self, *, year: int, month: int, categories=None, limit=None):
        _ = categories, limit
        return [
            {
                "id": f"{year}-{month}-macro",
                "title": "CPI",
                "start": f"{year}-{month:02d}-12",
                "category": "macro",
                "importance": "high",
                "displayTime": "08:30",
                "description": "Inflation release",
                "source": "FRED",
            }
        ]


class _FakeWatchlistService:
    def get_watchlist_snapshot(self):
        return [{"symbol": "AAPL", "name": "Apple", "move": "+1.2%"}]


def test_market_data_uses_recent_pipeline_and_processing(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    payload = service.market_data("TEST", depth="auto", view="monthly")

    assert payload["ticker"] == "TEST"
    assert payload["processing"]["requestedDepth"] == "auto"
    assert payload["processing"]["resolvedDepth"] == "recent"
    assert payload["processing"]["isComplete"] is False
    assert payload["processing"]["hasOlder"] is True
    assert payload["processing"]["view"] == "monthly"
    assert payload["count"] < 90


def test_market_data_can_force_full_history(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    payload = service.market_data("TEST", depth="full", view="daily")

    assert payload["processing"]["requestedDepth"] == "full"
    assert payload["processing"]["resolvedDepth"] == "full"
    assert payload["processing"]["isComplete"] is True
    assert payload["processing"]["hasOlder"] is False
    assert payload["count"] == 180


def test_indicators_use_shared_processing_contract(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    payload = service.indicators(
        "TEST",
        "rsi,macd,bb,sma_20,realized_vol,range_vol,mfd_65,mfd",
        depth="auto",
        view="daily",
    )

    assert payload["processing"]["resolvedDepth"] == "recent"
    assert set(payload["indicators"]) == {"rsi", "macd", "bb", "sma_20", "realized_vol", "range_vol", "mfd_65", "mfd"}
    assert payload["indicators"]["mfd_65"]["values"]["value"] is not None
    assert payload["indicators"]["mfd"]["values"]["latest"]["65"] is not None
    assert payload["unknown"] == []


def test_market_snapshot_and_calendar_include_processing(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    monkeypatch.setattr(agent_service, "get_watchlist_service", lambda: _FakeWatchlistService())
    service = agent_service.TerraFinAgentService()

    snapshot = service.market_snapshot("TEST")
    calendar = service.calendar_events(year=2026, month=4, categories="macro")

    assert snapshot["processing"]["resolvedDepth"] == "recent"
    assert snapshot["market_breadth"][0]["label"] == "Advancers"
    assert snapshot["watchlist"][0]["symbol"] == "AAPL"
    assert calendar["processing"]["resolvedDepth"] == "full"
    assert calendar["count"] == 1


def test_macro_focus_uses_shared_market_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    payload = service.macro_focus("S&P 500", depth="auto", view="weekly")

    assert payload["name"] == "S&P 500"
    assert payload["info"]["type"] == "index"
    assert payload["processing"]["resolvedDepth"] == "recent"
    assert payload["processing"]["view"] == "weekly"
