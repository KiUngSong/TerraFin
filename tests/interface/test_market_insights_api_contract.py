import pandas as pd
from fastapi.testclient import TestClient

import TerraFin.data as data_module
import TerraFin.interface.market_insights.data_routes as market_routes
import TerraFin.interface.market_insights.payloads as market_payloads
from TerraFin.data.contracts import HistoryChunk
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import SecEdgarConfigurationError
from TerraFin.interface.server import create_app


class _FakePortfolioOutput:
    def __init__(self) -> None:
        self.info = {"Period": "Q1 2026", "Source": "fixture"}
        self.df = pd.DataFrame(
            [
                {
                    "Stock": "AAA - Example",
                    "% of Portfolio": 10.5,
                    "Recent Activity": "Add 2.00%",
                    "Updated": 2.0,
                },
                {
                    "Stock": "BBB - Example",
                    "% of Portfolio": 8.0,
                    "Recent Activity": "Reduce 1.50%",
                    "Updated": -1.5,
                },
            ]
        )


def test_market_insights_regime_contract() -> None:
    client = TestClient(create_app())
    response = client.get("/market-insights/api/regime")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"summary", "confidence", "signals"}
    assert isinstance(payload["summary"], str)
    assert isinstance(payload["confidence"], str)
    assert isinstance(payload["signals"], list)
    assert all(isinstance(item, str) for item in payload["signals"])


def test_market_insights_gurus_contract() -> None:
    client = TestClient(create_app())
    response = client.get("/market-insights/api/investor-positioning/gurus")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"gurus", "count", "enabled", "message"}
    assert isinstance(payload["gurus"], list)
    assert isinstance(payload["count"], int)
    assert isinstance(payload["enabled"], bool)
    assert payload["message"] is None or isinstance(payload["message"], str)
    assert payload["count"] == len(payload["gurus"])


def test_market_insights_holdings_contract(monkeypatch) -> None:
    class _FakeFactory:
        def get_portfolio_data(self, guru: str, filing_date: str | None = None):
            assert guru == "Test Guru"
            return _FakePortfolioOutput()

    monkeypatch.setattr(market_routes, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/investor-positioning/holdings?guru=Test Guru")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"guru", "info", "rows", "topHoldings"}
    assert payload["guru"] == "Test Guru"
    assert isinstance(payload["info"], dict)
    assert isinstance(payload["rows"], list)
    assert isinstance(payload["topHoldings"], list)
    assert len(payload["rows"]) == 2
    assert payload["topHoldings"][0]["Stock"] == "AAA - Example"


def test_market_insights_holdings_requires_guru_query() -> None:
    client = TestClient(create_app())
    response = client.get(
        "/market-insights/api/investor-positioning/holdings", headers={"X-Request-ID": "req-missing-guru"}
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"] == "req-missing-guru"
    assert isinstance(payload["error"]["details"], list)


def test_market_insights_holdings_returns_503_when_sec_edgar_is_not_configured(monkeypatch) -> None:
    class _FakeFactory:
        def get_portfolio_data(self, guru: str, filing_date: str | None = None):
            _ = guru
            raise SecEdgarConfigurationError(
                "SEC EDGAR access is unavailable until `TERRAFIN_SEC_USER_AGENT` is configured."
            )

    monkeypatch.setattr(market_routes, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/investor-positioning/holdings?guru=Warren%20Buffett")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "sec_edgar_not_configured"
    assert payload["error"]["details"]["feature"] == "investor_positioning"
    assert payload["error"]["details"]["guru"] == "Warren Buffett"


def test_market_insights_top_companies_contract_uses_private_data_service(monkeypatch) -> None:
    class _FakeDataFactory:
        def get_panel_data(self, name: str):
            assert name == "top_companies"
            return [
                {
                    "rank": 1,
                    "ticker": "005930.KS",
                    "name": "Samsung Electronics",
                    "marketCap": "$360.00 B",
                    "country": "South Korea",
                }
            ]

    monkeypatch.setattr(market_routes, "get_data_factory", lambda: _FakeDataFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/top-companies")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "companies": [
            {
                "rank": 1,
                "ticker": "005930.KS",
                "name": "Samsung Electronics",
                "marketCap": "$360.00 B",
                "country": "South Korea",
            }
        ],
        "count": 1,
    }


def test_market_insights_macro_info_contract_uses_single_lookup(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeFactory:
        def get(self, name: str) -> TimeSeriesDataFrame:
            calls.append(name)
            return TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02", "2026-01-03"],
                        "open": [100.0, 101.0, 102.0],
                        "high": [101.0, 102.0, 103.0],
                        "low": [99.5, 100.5, 101.5],
                        "close": [100.5, 101.5, 102.5],
                    }
                )
            )

    monkeypatch.setattr(market_payloads, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/macro-info?name=S%26P%20500")
    assert response.status_code == 200

    payload = response.json()
    assert set(payload) == {"name", "type", "description", "currentValue", "change", "changePercent"}
    assert payload["name"] == "S&P 500"
    assert payload["type"] == "index"
    assert payload["description"] == "Benchmark U.S. large-cap equity index."
    assert payload["currentValue"] == 102.5
    assert payload["change"] == 1.0
    assert payload["changePercent"] == 0.99
    assert calls == ["S&P 500"]


def test_market_insights_macro_info_supports_shanghai_composite(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeFactory:
        def get(self, name: str) -> TimeSeriesDataFrame:
            calls.append(name)
            return TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02", "2026-01-03"],
                        "open": [3200.0, 3210.0, 3220.0],
                        "high": [3215.0, 3225.0, 3235.0],
                        "low": [3190.0, 3200.0, 3210.0],
                        "close": [3205.0, 3215.0, 3225.0],
                    }
                )
            )

    monkeypatch.setattr(market_payloads, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/macro-info?name=Shanghai%20Composite")
    assert response.status_code == 200

    payload = response.json()
    assert payload["name"] == "Shanghai Composite"
    assert payload["type"] == "index"
    assert payload["description"] == (
        "Broad mainland China equity benchmark tracking the Shanghai market."
    )
    assert calls == ["Shanghai Composite"]


def test_market_insights_macro_info_accepts_case_insensitive_name(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeFactory:
        def get(self, name: str) -> TimeSeriesDataFrame:
            calls.append(name)
            return TimeSeriesDataFrame(
                pd.DataFrame(
                    {
                        "time": ["2026-01-01", "2026-01-02"],
                        "close": [2500.0, 2510.0],
                    }
                )
            )

    monkeypatch.setattr(market_payloads, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())

    response = client.get("/market-insights/api/macro-info?name=kospi")
    assert response.status_code == 200

    payload = response.json()
    assert payload["name"] == "Kospi"
    assert calls == ["Kospi"]


def test_market_insights_macro_info_prefers_session_series(monkeypatch) -> None:
    recent_calls: list[str] = []
    get_calls: list[str] = []

    class _FakeFactory:
        def get_recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
            recent_calls.append(name)
            assert period == "3y"
            return HistoryChunk(
                frame=TimeSeriesDataFrame(
                    pd.DataFrame(
                        {
                            "time": ["2026-01-01", "2026-01-02", "2026-01-03"],
                            "open": [100.0, 101.0, 102.0],
                            "high": [101.0, 102.0, 103.0],
                            "low": [99.5, 100.5, 101.5],
                            "close": [100.5, 101.5, 102.5],
                        }
                    )
                ),
                loaded_start="2026-01-01",
                loaded_end="2026-01-03",
                requested_period=period,
                is_complete=False,
                has_older=True,
                source_version="test",
            )

        def get(self, name: str) -> TimeSeriesDataFrame:
            get_calls.append(name)
            raise AssertionError("macro-info should reuse session data instead of calling get()")

    monkeypatch.setattr(data_module, "get_data_factory", lambda: _FakeFactory())
    monkeypatch.setattr(market_payloads, "get_data_factory", lambda: _FakeFactory())
    client = TestClient(create_app())
    headers = {"X-Session-ID": "macro-info-session"}

    seed = client.post(
        "/chart/api/chart-series/progressive/set",
        json={"name": "S&P 500", "pinned": False, "seedPeriod": "3y"},
        headers=headers,
    )
    assert seed.status_code == 200
    assert recent_calls == ["S&P 500"]
    assert get_calls == []

    response = client.get("/market-insights/api/macro-info?name=S%26P%20500", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["name"] == "S&P 500"
    assert payload["currentValue"] == 102.5
    assert recent_calls == ["S&P 500"]
    assert get_calls == []


def test_market_insights_legacy_macro_chart_routes_are_removed() -> None:
    client = TestClient(create_app())

    assert client.get("/market-insights/api/macro-chart?name=S%26P%20500").status_code == 404
    assert client.get("/market-insights/api/macro-focus?name=S%26P%20500").status_code == 404
    assert client.get("/market-insights/api/macro-session-info?name=S%26P%20500").status_code == 404
    assert client.post("/market-insights/api/macro-focus", json={"name": "Nasdaq"}).status_code == 404
    assert client.post(
        "/market-insights/api/macro-focus/remove",
        json={"name": "S&P 500", "focusName": "Nasdaq"},
    ).status_code == 404
