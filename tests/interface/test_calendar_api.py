from datetime import datetime

from fastapi.testclient import TestClient

import TerraFin.data.cache.manager as cache_manager_module
from TerraFin.data.cache.registry import reset_cache_manager
from TerraFin.data.providers.private_access.client import PrivateAccessClient
from TerraFin.data.providers.private_access.models import CalendarResponse
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app


def _reset_services() -> None:
    reset_cache_manager()
    reset_private_data_service()


def test_calendar_events_endpoint_returns_contract(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    now = datetime.utcnow()
    _reset_services()
    client = TestClient(create_app())

    response = client.get(f"/calendar/api/events?month={now.month}&year={now.year}")

    assert response.status_code == 200
    body = response.json()
    assert body["month"] == now.month
    assert body["year"] == now.year
    assert body["count"] >= 1
    assert isinstance(body["events"], list)
    assert {"id", "title", "start", "category"}.issubset(body["events"][0].keys())


def test_calendar_events_are_filtered_by_category(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    now = datetime.utcnow()

    def _mock_calendar(self):
        _ = self
        return CalendarResponse(
            events=[
                {
                    "id": f"{now.year}-{now.month:02d}-10-0",
                    "title": "Mock Macro",
                    "start": f"{now.year}-{now.month:02d}-10T08:30:00",
                    "category": "macro",
                },
                {
                    "id": f"{now.year}-{now.month:02d}-20-0",
                    "title": "Mock Earnings",
                    "start": f"{now.year}-{now.month:02d}-20T16:00:00",
                    "category": "earning",
                },
            ]
        )

    monkeypatch.setattr(PrivateAccessClient, "fetch_calendar_events", _mock_calendar)
    _reset_services()
    client = TestClient(create_app())

    get_response = client.get(f"/calendar/api/events?month={now.month}&year={now.year}&categories=earning")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["count"] == 1
    assert body["events"][0]["category"] == "earning"
    assert body["events"][0]["title"] == "Mock Earnings"


def test_calendar_selection_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    _reset_services()
    client = TestClient(create_app())
    payload = {"eventId": "2026-02-25-0", "month": 2, "year": 2026}

    post_response = client.post("/calendar/api/selection", json=payload)
    assert post_response.status_code == 200
    assert post_response.json()["ok"] is True

    get_response = client.get("/calendar/api/selection")
    assert get_response.status_code == 200
    assert get_response.json() == payload


def test_calendar_events_use_private_source_when_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    now = datetime.utcnow()

    def _mock_calendar(self):
        _ = self
        return CalendarResponse(
            events=[
                {
                    "id": f"{now.year}-{now.month:02d}-03-0",
                    "title": "Private Macro",
                    "start": f"{now.year}-{now.month:02d}-03T08:30:00",
                    "category": "macro",
                },
                {
                    "id": f"{now.year}-{now.month:02d}-04-0",
                    "title": "Private Earnings",
                    "start": f"{now.year}-{now.month:02d}-04T16:00:00",
                    "category": "earning",
                },
            ]
        )

    monkeypatch.setattr(PrivateAccessClient, "fetch_calendar_events", _mock_calendar)
    _reset_services()
    client = TestClient(create_app())

    response = client.get(f"/calendar/api/events?month={now.month}&year={now.year}&categories=earning")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["title"] == "Private Earnings"
