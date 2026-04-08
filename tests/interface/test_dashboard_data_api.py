import pandas as pd
from fastapi.testclient import TestClient

import TerraFin.data.cache.manager as cache_manager_module
import TerraFin.data.providers.private_access.cape as cape_module
import TerraFin.data.providers.private_access.fear_greed as fear_greed_module
import TerraFin.interface.watchlist_service as watchlist_service_module
from TerraFin.data.cache.registry import reset_cache_manager
from TerraFin.data.providers.private_access.client import PrivateAccessClient
from TerraFin.data.providers.private_access.models import MarketBreadthResponse
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app
from TerraFin.interface.watchlist_service import reset_watchlist_service


def _assert_watchlist_item_shape(item: dict) -> None:
    assert set(item) == {"symbol", "name", "move"}
    assert isinstance(item["symbol"], str)
    assert isinstance(item["name"], str)
    assert isinstance(item["move"], str)


def _assert_breadth_metric_shape(metric: dict) -> None:
    assert set(metric) == {"label", "value", "tone"}
    assert isinstance(metric["label"], str)
    assert isinstance(metric["value"], str)
    assert isinstance(metric["tone"], str)


def _fake_history_frame() -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0, 102.0]})


def _reset_services() -> None:
    reset_cache_manager()
    reset_watchlist_service()
    reset_private_data_service()


def test_dashboard_data_uses_fallback_when_private_source_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    monkeypatch.delenv("TERRAFIN_MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    _reset_services()
    client = TestClient(create_app())

    watchlist_response = client.get("/dashboard/api/watchlist")
    assert watchlist_response.status_code == 200
    watchlist_payload = watchlist_response.json()
    assert isinstance(watchlist_payload["items"], list)
    assert watchlist_payload["backendConfigured"] is False
    assert watchlist_payload["mode"] == "fallback"
    assert len(watchlist_payload["items"]) >= 7
    _assert_watchlist_item_shape(watchlist_payload["items"][0])

    breadth_response = client.get("/dashboard/api/market-breadth")
    assert breadth_response.status_code == 200
    breadth_payload = breadth_response.json()
    assert isinstance(breadth_payload["metrics"], list)
    assert len(breadth_payload["metrics"]) >= 1
    _assert_breadth_metric_shape(breadth_payload["metrics"][0])


def test_dashboard_market_breadth_uses_private_source_when_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)

    def _mock_breadth(self):
        _ = self
        return MarketBreadthResponse(metrics=[{"label": "Advancers", "value": "500", "tone": "#047857"}])

    monkeypatch.setattr(PrivateAccessClient, "fetch_market_breadth", _mock_breadth)
    _reset_services()

    client = TestClient(create_app())
    breadth_payload = client.get("/dashboard/api/market-breadth").json()

    _assert_breadth_metric_shape(breadth_payload["metrics"][0])
    assert breadth_payload["metrics"][0]["value"] == "500"


def test_dashboard_fear_greed_falls_back_to_cached_history_when_current_misses(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    fear_greed_module.clear_fear_greed_cache()

    def _mock_history(self):
        _ = self
        return [
            {"date": "2026-01-01", "score": 25},
            {"date": "2026-01-10", "score": 40},
            {"date": "2026-01-28", "score": 62},
            {"date": "2026-02-01", "score": 70},
        ]

    def _mock_current(self):
        _ = self
        raise RuntimeError("current unavailable")

    monkeypatch.setattr(PrivateAccessClient, "fetch_fear_greed", _mock_history)
    monkeypatch.setattr(PrivateAccessClient, "fetch_fear_greed_current", _mock_current)
    client = TestClient(create_app())
    payload = client.get("/dashboard/api/fear-greed").json()

    assert payload["score"] == 70
    assert payload["rating"] == "Greed"
    assert payload["previous_close"] == 62
    assert payload["previous_1_week"] == 40
    assert payload["previous_1_month"] == 25


def test_dashboard_cape_falls_back_to_series_history_when_current_misses(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    cape_module.clear_cape_cache()

    def _mock_history(self):
        _ = self
        return [
            {"date": "2025-12", "cape": 29.4},
            {"date": "2026-01", "cape": 31.1},
        ]

    def _mock_current(self):
        _ = self
        raise RuntimeError("current unavailable")

    monkeypatch.setattr(PrivateAccessClient, "fetch_cape_history", _mock_history)
    monkeypatch.setattr(PrivateAccessClient, "fetch_cape_current", _mock_current)
    client = TestClient(create_app())
    payload = client.get("/dashboard/api/cape").json()

    assert payload["date"] == "2026-01"
    assert payload["cape"] == 31.1


def test_dashboard_watchlist_crud(monkeypatch, tmp_path) -> None:
    storage: dict[str, dict] = {}

    class _FakeCollection:
        def find_one(self, query):
            return storage.get(query["_id"])

        def update_one(self, query, update, upsert=False):
            _ = upsert
            storage[query["_id"]] = {"_id": query["_id"], **update["$set"]}

    class _FakeDatabase:
        def __getitem__(self, name):
            _ = name
            return _FakeCollection()

    class _FakeMongoClient:
        def __init__(self, uri, serverSelectionTimeoutMS=2000):
            self.uri = uri
            _ = serverSelectionTimeoutMS

        def __getitem__(self, name):
            _ = name
            return _FakeDatabase()

    monkeypatch.setenv("TERRAFIN_MONGODB_URI", "mongodb://example.test")
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(watchlist_service_module, "get_yf_data", lambda symbol: _fake_history_frame())
    monkeypatch.setattr(watchlist_service_module, "_resolve_company_name", lambda symbol: f"{symbol} Holdings")
    monkeypatch.setattr(watchlist_service_module, "MongoClient", _FakeMongoClient)

    _reset_services()
    client = TestClient(create_app())

    initial = client.get("/dashboard/api/watchlist")
    assert initial.status_code == 200
    assert initial.json()["items"] == []
    assert initial.json()["backendConfigured"] is True
    assert initial.json()["mode"] == "mongo"
    assert storage["terrafin_watchlist"] == {
        "_id": "terrafin_watchlist",
        "Company List": [],
        "items": [],
    }

    created = client.post("/dashboard/api/watchlist", json={"symbol": "meta"})
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["backendConfigured"] is True
    assert created_payload["mode"] == "mongo"
    assert created_payload["items"] == [{"symbol": "META", "name": "META Holdings", "move": "+2.00%"}]

    duplicate = client.post("/dashboard/api/watchlist", json={"symbol": "META"})
    assert duplicate.status_code == 409

    removed = client.delete("/dashboard/api/watchlist/META")
    assert removed.status_code == 200
    assert removed.json()["items"] == []


def test_dashboard_watchlist_falls_back_when_mongo_backend_is_unreachable(monkeypatch, tmp_path) -> None:
    class _UnavailableCollection:
        def find_one(self, query):
            _ = query
            raise RuntimeError("mongo unavailable")

        def update_one(self, query, update, upsert=False):
            _ = query, update, upsert
            raise RuntimeError("mongo unavailable")

    class _UnavailableDatabase:
        def __getitem__(self, name):
            _ = name
            return _UnavailableCollection()

    class _UnavailableMongoClient:
        def __init__(self, uri, serverSelectionTimeoutMS=2000):
            _ = uri, serverSelectionTimeoutMS

        def __getitem__(self, name):
            _ = name
            return _UnavailableDatabase()

    monkeypatch.setenv("TERRAFIN_MONGODB_URI", "mongodb://unavailable.test")
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    monkeypatch.setattr(watchlist_service_module, "MongoClient", _UnavailableMongoClient)

    _reset_services()
    client = TestClient(create_app())

    response = client.get("/dashboard/api/watchlist")
    assert response.status_code == 200
    payload = response.json()
    assert payload["backendConfigured"] is False
    assert payload["mode"] == "fallback"
    assert len(payload["items"]) >= 1


def test_dashboard_cache_status_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    client = TestClient(create_app())
    response = client.get("/dashboard/api/cache-status")
    assert response.status_code == 200
    body = response.json()
    assert "sources" in body
    assert isinstance(body["sources"], list)
    assert len(body["sources"]) >= 3
    first = body["sources"][0]
    assert {
        "source",
        "mode",
        "intervalSeconds",
        "enabled",
        "lastRunAt",
        "lastSuccessAt",
        "lastError",
    }.issubset(first.keys())
    assert any(item["source"] == "portfolio.cache" for item in body["sources"])


def test_watchlist_page_route_serves_frontend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    client = TestClient(create_app())
    response = client.get("/watchlist")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_dashboard_cache_refresh_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    client = TestClient(create_app())
    response = client.post("/dashboard/api/cache-refresh?force=true")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["force"] is True
    assert isinstance(body["sources"], list)
    assert len(body["sources"]) >= 3
