import pandas as pd
from fastapi.testclient import TestClient

import TerraFin.agent.service as agent_service
import TerraFin.interface.stock.data_routes as stock_routes
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import SecEdgarConfigurationError
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app
from TerraFin.interface.watchlist_service import reset_watchlist_service


def _make_fake_tsdf(ticker: str = "TEST", n: int = 120) -> TimeSeriesDataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base = 100.0
    data = {
        "time": dates,
        "open": [base + idx * 0.1 for idx in range(n)],
        "high": [base + idx * 0.1 + 1 for idx in range(n)],
        "low": [base + idx * 0.1 - 1 for idx in range(n)],
        "close": [base + idx * 0.2 for idx in range(n)],
        "volume": [1000 + idx for idx in range(n)],
    }
    df = TimeSeriesDataFrame(pd.DataFrame(data))
    df.name = ticker
    return df


class _FakeDataFactory:
    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs

    def get(self, name):
        return _make_fake_tsdf(name, 180)

    def get_recent_history(self, name, period="3y"):
        _ = period
        df = _make_fake_tsdf(name, 90)
        return HistoryChunk(
            frame=df,
            loaded_start="2025-01-01",
            loaded_end="2025-05-06",
            requested_period="3y",
            is_complete=False,
            has_older=True,
            source_version="recent-cache",
        )

    def get_full_history_backfill(self, name, loaded_start=None):
        _ = loaded_start
        df = _make_fake_tsdf(name, 180)
        return HistoryChunk(
            frame=df,
            loaded_start="2024-07-03",
            loaded_end="2025-05-06",
            requested_period=None,
            is_complete=True,
            has_older=False,
            source_version="full-cache",
        )

    def get_fred_data(self, name):
        df = _make_fake_tsdf(name, 12)[["time", "close"]]
        df = TimeSeriesDataFrame(df)
        df.name = name
        return df

    def get_corporate_data(self, ticker, statement_type="income", period="annual"):
        _ = ticker, statement_type, period
        return pd.DataFrame(
            {
                "date": ["2025-12-31", "2024-12-31"],
                "Revenue": [1000.0, 950.0],
                "Net Income": [210.0, 200.0],
            }
        )


class _FakePrivateDataService:
    def get_market_breadth(self):
        return [{"label": "Advancers", "value": "300", "tone": "#047857"}]

    def get_calendar_events(self, *, year, month, categories=None, limit=None):
        _ = categories, limit
        return [
            {
                "id": f"{year}-{month}-1",
                "title": "CPI",
                "start": f"{year}-{month:02d}-12",
                "category": "macro",
                "importance": "high",
                "displayTime": "08:30",
                "description": "Inflation",
                "source": "FRED",
            }
        ]


class _FakeWatchlistService:
    def get_watchlist_snapshot(self):
        return [{"symbol": "AAPL", "name": "Apple", "move": "+1.1%"}]


class _FakePortfolioOutput:
    def __init__(self) -> None:
        self.info = {"Period": "Q1 2026", "Source": "fixture"}
        self.df = pd.DataFrame(
            [
                {"Stock": "AAA", "% of Portfolio": 10.5, "Recent Activity": "Add 2.00%", "Updated": 2.0},
                {"Stock": "BBB", "% of Portfolio": 8.0, "Recent Activity": "Reduce 1.50%", "Updated": -1.5},
            ]
        )


def _configure_agent_fakes(monkeypatch) -> None:
    monkeypatch.setattr(agent_service, "DataFactory", _FakeDataFactory)
    monkeypatch.setattr(stock_routes, "DataFactory", _FakeDataFactory)
    monkeypatch.setattr(agent_service, "get_private_data_service", lambda: _FakePrivateDataService())
    monkeypatch.setattr(agent_service, "get_watchlist_service", lambda: _FakeWatchlistService())
    monkeypatch.setattr(
        stock_routes,
        "get_ticker_info",
        lambda ticker: {
            "shortName": f"{ticker} Inc.",
            "sector": "Technology",
            "industry": "Software",
            "currentPrice": 150.0,
            "previousClose": 147.0,
            "exchange": "NASDAQ",
        },
    )
    monkeypatch.setattr(
        stock_routes,
        "get_ticker_earnings",
        lambda ticker: [
            {
                "date": "2025-12-31",
                "epsEstimate": "2.10",
                "epsReported": "2.25",
                "surprise": "0.15",
                "surprisePercent": "7.14",
            }
        ],
    )
    monkeypatch.setattr(agent_service, "get_portfolio_data", lambda guru: _FakePortfolioOutput())


def _client(monkeypatch) -> TestClient:
    _configure_agent_fakes(monkeypatch)
    reset_watchlist_service()
    reset_private_data_service()
    return TestClient(create_app())


def test_agent_market_data_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/market-data?ticker=TEST&depth=auto&view=monthly")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "seriesType", "count", "data", "processing"}
    assert payload["ticker"] == "TEST"
    assert payload["processing"]["requestedDepth"] == "auto"
    assert payload["processing"]["resolvedDepth"] == "recent"
    assert payload["processing"]["view"] == "monthly"


def test_agent_indicators_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/indicators?ticker=TEST&indicators=rsi,macd,bb,sma_20,realized_vol,range_vol")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "indicators", "unknown", "processing"}
    assert set(payload["indicators"]) == {"rsi", "macd", "bb", "sma_20", "realized_vol", "range_vol"}
    assert payload["unknown"] == []
    assert payload["processing"]["resolvedDepth"] == "recent"


def test_agent_market_snapshot_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/agent/api/market-snapshot?ticker=TEST&depth=full")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"ticker", "price_action", "indicators", "market_breadth", "watchlist", "processing"}
    assert payload["processing"]["resolvedDepth"] == "full"
    assert payload["watchlist"][0]["symbol"] == "AAPL"


def test_agent_resolve_company_earnings_and_financials(monkeypatch) -> None:
    client = _client(monkeypatch)

    resolve_resp = client.get("/agent/api/resolve?q=AAPL")
    company_resp = client.get("/agent/api/company?ticker=AAPL")
    earnings_resp = client.get("/agent/api/earnings?ticker=AAPL")
    financials_resp = client.get("/agent/api/financials?ticker=AAPL&statement=income&period=annual")

    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["path"] == "/stock/AAPL"

    assert company_resp.status_code == 200
    assert company_resp.json()["ticker"] == "AAPL"
    assert "processing" in company_resp.json()

    assert earnings_resp.status_code == 200
    assert earnings_resp.json()["earnings"][0]["epsReported"] == "2.25"

    assert financials_resp.status_code == 200
    assert financials_resp.json()["statement"] == "income"
    assert len(financials_resp.json()["rows"]) == 2


def test_agent_portfolio_economic_macro_and_calendar(monkeypatch) -> None:
    client = _client(monkeypatch)

    portfolio_resp = client.get("/agent/api/portfolio?guru=Test%20Guru")
    economic_resp = client.get("/agent/api/economic?indicators=UNRATE")
    macro_resp = client.get("/agent/api/macro-focus?name=S%26P%20500&view=weekly")
    china_macro_resp = client.get("/agent/api/macro-focus?name=Shanghai%20Composite&view=weekly")
    calendar_resp = client.get("/agent/api/calendar?year=2026&month=4&categories=macro")

    assert portfolio_resp.status_code == 200
    assert portfolio_resp.json()["count"] == 2

    assert economic_resp.status_code == 200
    assert "UNRATE" in economic_resp.json()["indicators"]
    assert "processing" in economic_resp.json()

    assert macro_resp.status_code == 200
    assert macro_resp.json()["info"]["type"] == "index"
    assert macro_resp.json()["info"]["description"] == "Benchmark U.S. large-cap equity index."
    assert macro_resp.json()["processing"]["view"] == "weekly"

    assert china_macro_resp.status_code == 200
    assert china_macro_resp.json()["name"] == "Shanghai Composite"
    assert china_macro_resp.json()["info"]["type"] == "index"
    assert china_macro_resp.json()["info"]["description"] == (
        "Broad mainland China equity benchmark tracking the Shanghai market."
    )

    assert calendar_resp.status_code == 200
    assert calendar_resp.json()["count"] == 1
    assert calendar_resp.json()["processing"]["resolvedDepth"] == "full"


def test_agent_openapi_includes_new_routes(monkeypatch) -> None:
    client = _client(monkeypatch)

    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/agent/api/resolve" in paths
    assert "/agent/api/company" in paths
    assert "/agent/api/earnings" in paths
    assert "/agent/api/financials" in paths
    assert "/agent/api/macro-focus" in paths
    assert "/agent/api/calendar" in paths


def test_agent_portfolio_returns_503_when_sec_edgar_is_not_configured(monkeypatch) -> None:
    _configure_agent_fakes(monkeypatch)
    monkeypatch.setattr(
        agent_service,
        "get_portfolio_data",
        lambda guru: (_ for _ in ()).throw(
            SecEdgarConfigurationError(
                "SEC EDGAR access is unavailable until `TERRAFIN_SEC_USER_AGENT` is configured."
            )
        ),
    )
    reset_watchlist_service()
    reset_private_data_service()
    client = TestClient(create_app())

    response = client.get("/agent/api/portfolio?guru=Warren%20Buffett")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "sec_edgar_not_configured"
    assert payload["error"]["details"]["feature"] == "agent_portfolio"
