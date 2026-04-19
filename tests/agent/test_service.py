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

    def get_economic_data(self, name: str):
        frame = _make_frame(name, periods=12)[["time", "close"]]
        frame = TimeSeriesDataFrame(frame)
        frame.name = name
        return frame


class _FakePrivateDataService:
    def get_market_breadth(self):
        return [{"label": "Advancers", "value": "320", "tone": "#047857"}]

    def get_fear_greed_current(self):
        return {
            "score": 42,
            "rating": "Fear",
            "previousClose": 45,
            "oneWeekAgo": 50,
            "oneMonthAgo": 38,
        }

    def get_top_companies(self):
        return [
            {"symbol": "AAPL", "name": "Apple", "marketCap": 3_200_000_000_000},
            {"symbol": "MSFT", "name": "Microsoft", "marketCap": 3_100_000_000_000},
        ]

    def get_trailing_forward_pe(self):
        return {
            "date": "2026-04-15",
            "summary": {"trailing_forward_pe_spread": 2.1},
            "coverage": {"usable": 480, "requested": 500},
            "history": [
                {"date": "2026-04-14", "spread": 2.0},
                {"date": "2026-04-15", "spread": 2.1},
            ],
        }

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
    # market_breadth and watchlist are now standalone capabilities —
    # `market_snapshot` is per-ticker only (was mixing whole-market state
    # with per-ticker view, audit: DA Med-7).
    assert "market_breadth" not in snapshot
    assert "watchlist" not in snapshot
    breadth = service.market_breadth()
    watchlist = service.watchlist()
    assert breadth["metrics"][0]["label"] == "Advancers"
    assert watchlist["items"][0]["symbol"] == "AAPL"
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


def test_economic_normalizes_human_friendly_indicator_aliases(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    payload = service.economic(["Fed Funds Rate", "US Federal Reserve Balance Sheet"])

    assert "Federal Funds Effective Rate" in payload["indicators"]
    assert "SOMA" in payload["indicators"]


# ---------------------------------------------------------------------------
# DA-audit mismatch fixes — the agent must see the same payload shape the
# frontend widgets/routes render, so questions like "what's the Fear & Greed
# score?" or "what's the S&P 500 implied growth?" answer the same way whether
# the user looks at the widget or asks the agent. Before these fixes, agent
# had either no tool (widgets invisible to agent) or a cherry-picked subset
# (divergent between UI and agent).
# ---------------------------------------------------------------------------


def test_fear_greed_returns_full_widget_payload(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    service = agent_service.TerraFinAgentService()

    payload = service.fear_greed()

    assert payload["score"] == 42
    assert payload["rating"] == "Fear"
    assert payload["previousClose"] == 45
    assert payload["oneWeekAgo"] == 50
    assert payload["oneMonthAgo"] == 38
    assert payload["processing"]["resolvedDepth"] == "full"


def test_top_companies_returns_full_list(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    service = agent_service.TerraFinAgentService()

    payload = service.top_companies()

    assert payload["count"] == 2
    assert payload["companies"][0]["symbol"] == "AAPL"


def test_market_regime_mirrors_route_placeholder() -> None:
    """Route returns a placeholder; agent mirrors it verbatim so the two
    views never diverge (even for placeholder content)."""
    service = agent_service.TerraFinAgentService()

    payload = service.market_regime()

    assert "selective risk-taking" in payload["summary"]
    assert payload["confidence"] == "low"
    assert len(payload["signals"]) == 3


def test_trailing_forward_pe_returns_dashboard_shape(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    service = agent_service.TerraFinAgentService()

    payload = service.trailing_forward_pe()

    assert payload["date"] == "2026-04-15"
    assert payload["latestValue"] == 2.1
    assert payload["usableCount"] == 480
    assert payload["requestedCount"] == 500
    assert len(payload["history"]) == 2


def test_market_breadth_standalone_returns_metrics_list(monkeypatch) -> None:
    """Was bundled inside market_snapshot; now a standalone tool so agent
    and the MarketBreadthCard widget query the same data (DA Med-7)."""
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    service = agent_service.TerraFinAgentService()

    payload = service.market_breadth()

    assert payload["metrics"][0]["label"] == "Advancers"


def test_watchlist_standalone_returns_items_list(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "get_watchlist_service", lambda: _FakeWatchlistService())
    service = agent_service.TerraFinAgentService()

    payload = service.watchlist()

    assert payload["count"] == 1
    assert payload["items"][0]["symbol"] == "AAPL"


def test_market_snapshot_no_longer_bundles_whole_market_widgets(monkeypatch) -> None:
    """Regression guard for DA Med-7 fix: market_snapshot is per-ticker
    only. The temptation to re-bundle market-wide widgets for
    "convenience" is what caused the original UI↔agent divergence —
    widgets refresh on their own cadence while market_snapshot bundled a
    point-in-time copy, so the agent's number could lag the UI's."""
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    service = agent_service.TerraFinAgentService()

    snapshot = service.market_snapshot("TEST")

    assert "market_breadth" not in snapshot
    assert "watchlist" not in snapshot


def test_portfolio_exposes_top_holdings_matching_route_sort(monkeypatch) -> None:
    """Route pre-computes `topHoldings` (top 8 by % of Portfolio). Agent
    must return the same list so the UI treemap and the agent agree on
    which positions are the "top" ones (DA Med-9)."""
    import pandas as _pd

    class _FakePortfolio:
        def __init__(self) -> None:
            self.df = _pd.DataFrame(
                [
                    {"Stock": "AAPL", "% of Portfolio": 25.0, "Recent Activity": "Hold", "Updated": "2026-03-31"},
                    {"Stock": "MSFT", "% of Portfolio": 15.0, "Recent Activity": "Buy", "Updated": "2026-03-31"},
                    {"Stock": "NVDA", "% of Portfolio": 10.0, "Recent Activity": "Buy", "Updated": "2026-03-31"},
                ]
            )
            self.info = {"guru": "buffett"}

    monkeypatch.setattr(agent_service, "get_portfolio_data", lambda _g: _FakePortfolio())
    service = agent_service.TerraFinAgentService()

    payload = service.portfolio("buffett")

    assert payload["count"] == 3
    assert len(payload["topHoldings"]) == 3
    # Sorted by % of Portfolio descending.
    assert payload["topHoldings"][0]["Stock"] == "AAPL"
    assert payload["topHoldings"][1]["Stock"] == "MSFT"


def test_valuation_passes_through_full_dcf_and_reverse_dcf_payloads(monkeypatch) -> None:
    """Regression for DA High-1 / High-2: agent must see the same
    DCFValuationResponse shape the user sees in DcfValuationPanel —
    scenarios, sensitivity, methods, rateCurve, dataQuality, not just
    a cherry-picked 4-field subset."""
    dcf_full = {
        "status": "ready",
        "currentIntrinsicValue": 120.0,
        "upsidePct": 8.0,
        "assumptions": {"discountRate": 0.1},
        "scenarios": {"base": {}, "bull": {}, "bear": {}},
        "sensitivity": [[1.1, 1.2], [0.9, 1.0]],
        "methods": ["dcf", "pe"],
        "rateCurve": [{"year": 2025, "rate": 0.05}],
        "dataQuality": {"grade": "A"},
        "warnings": [],
    }
    reverse_full = {
        "status": "ready",
        "impliedGrowthPct": 10.5,
        "modelPrice": 115.0,
        "projectedCashFlows": [10, 11, 12],
        "growthProfile": {"terminalGrowth": 0.025},
        "priceToCashFlowMultiple": 12.0,
        "terminalValue": 1000.0,
        "terminalGrowthPct": 2.5,
        "discountSpreadPct": 3.0,
        "rateCurve": [{"year": 2025, "rate": 0.05}],
        "dataQuality": {"grade": "A"},
        "warnings": [],
    }
    monkeypatch.setattr(agent_service, "build_stock_dcf_payload", lambda _t: dcf_full)
    monkeypatch.setattr(agent_service, "build_stock_reverse_dcf_payload", lambda _t: reverse_full)
    monkeypatch.setattr(
        agent_service,
        "build_company_info_payload",
        lambda _t: {"currentPrice": 110.0, "trailingPE": 22.0, "forwardPE": 20.0, "trailingEps": 5.0},
    )

    class _FakeDF:
        def __init__(self) -> None:
            self._data = {"TotalStockholdersEquity": [2_000_000_000], "SharesOutstanding": [20_000_000]}
            self.columns = list(self._data.keys())
            self.empty = False

        def __getitem__(self, col):
            return type("_S", (), {"iloc": type("_I", (), {"__getitem__": lambda _, idx: self._data[col][idx]})()})()

    class _FactoryStub:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def get_corporate_data(self, *args, **kwargs):
            _ = args, kwargs
            return _FakeDF()

    monkeypatch.setattr(agent_service, "DataFactory", _FactoryStub)
    service = agent_service.TerraFinAgentService()

    payload = service.valuation("AAPL")

    # Full DCF payload preserved, not cherry-picked.
    assert payload["dcf"]["scenarios"]["base"] == {}
    assert payload["dcf"]["sensitivity"] == [[1.1, 1.2], [0.9, 1.0]]
    assert payload["dcf"]["dataQuality"]["grade"] == "A"
    # Full reverse DCF payload preserved.
    assert payload["reverseDcf"]["projectedCashFlows"] == [10, 11, 12]
    assert payload["reverseDcf"]["terminalGrowthPct"] == 2.5
    assert payload["reverseDcf"]["priceToCashFlowMultiple"] == 12.0
