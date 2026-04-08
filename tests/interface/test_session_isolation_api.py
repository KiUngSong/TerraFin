from datetime import datetime

from fastapi.testclient import TestClient

from TerraFin.data import DataFactory
from TerraFin.data.contracts import HistoryChunk
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.interface.private_data_service import reset_private_data_service
from TerraFin.interface.server import create_app


def test_chart_same_session_read_after_write() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-a"}
    payload = {
        "mode": "multi",
        "series": [
            {
                "id": "S1",
                "seriesType": "line",
                "data": [{"time": "2026-01-01", "value": 10}, {"time": "2026-01-02", "value": 20}],
            }
        ],
    }

    post_response = client.post("/chart/api/chart-data", json=payload, headers=headers)
    assert post_response.status_code == 200
    assert post_response.json()["ok"] is True

    get_response = client.get("/chart/api/chart-data", headers=headers)
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["mode"] == "multi"
    assert body["series"][0]["data"] == payload["series"][0]["data"]
    assert body["dataLength"] == 2
    assert body["historyBySeries"]["S1"]["isComplete"] is True
    assert body["historyBySeries"]["S1"]["hasOlder"] is False


def test_chart_cross_session_isolation_for_data_and_selection() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers_a = {"X-Session-ID": "A"}
    headers_b = {"X-Session-ID": "B"}

    payload_a = {
        "mode": "multi",
        "series": [{"id": "A", "seriesType": "line", "data": [{"time": "2026-01-01", "value": 1}]}],
    }
    payload_b = {
        "mode": "multi",
        "series": [
            {"id": "B", "seriesType": "line", "data": [{"time": "2026-01-01", "value": 9}]},
            {"id": "B2", "seriesType": "line", "data": [{"time": "2026-01-02", "value": 10}]},
        ],
    }

    client.post("/chart/api/chart-data", json=payload_a, headers=headers_a)
    client.post("/chart/api/chart-data", json=payload_b, headers=headers_b)

    data_a = client.get("/chart/api/chart-data", headers=headers_a).json()
    data_b = client.get("/chart/api/chart-data", headers=headers_b).json()
    assert data_a["series"][0]["id"] == "A"
    assert data_b["series"][0]["id"] == "B"
    assert len(data_a["series"][0]["data"]) == 1
    assert len(data_b["series"]) == 2
    assert data_a["dataLength"] != data_b["dataLength"]
    assert set(data_a["historyBySeries"]) == {"A"}
    assert set(data_b["historyBySeries"]) == {"B", "B2"}

    selection_a = {"from": 1, "to": 2}
    selection_b = {"from": 3, "to": 4}
    client.post("/chart/api/chart-selection", json=selection_a, headers=headers_a)
    client.post("/chart/api/chart-selection", json=selection_b, headers=headers_b)

    assert client.get("/chart/api/chart-selection", headers=headers_a).json() == selection_a
    assert client.get("/chart/api/chart-selection", headers=headers_b).json() == selection_b


def test_calendar_same_session_read_after_write() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers = {"X-Session-ID": "cal-a"}
    payload = {"eventId": "2026-02-25-0", "month": 2, "year": 2026}

    post_response = client.post("/calendar/api/selection", json=payload, headers=headers)
    assert post_response.status_code == 200
    assert post_response.json()["ok"] is True

    get_response = client.get("/calendar/api/selection", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json() == payload


def test_calendar_cross_session_selection_isolation() -> None:
    reset_private_data_service()
    client = TestClient(create_app())
    headers_a = {"X-Session-ID": "A"}
    headers_b = {"X-Session-ID": "B"}

    payload_a = {"eventId": "2026-01-05-0", "month": 1, "year": 2026}
    payload_b = {"eventId": "2026-01-12-0", "month": 1, "year": 2026}

    client.post("/calendar/api/selection", json=payload_a, headers=headers_a)
    client.post("/calendar/api/selection", json=payload_b, headers=headers_b)

    assert client.get("/calendar/api/selection", headers=headers_a).json() == payload_a
    assert client.get("/calendar/api/selection", headers=headers_b).json() == payload_b


def test_default_session_behavior_without_header_is_stable() -> None:
    reset_private_data_service()
    client = TestClient(create_app())

    chart_payload = {
        "mode": "multi",
        "series": [{"id": "Default", "seriesType": "line", "data": [{"time": "2026-03-01", "value": 200}]}],
    }
    calendar_payload = {"eventId": "2026-03-05-0", "month": 3, "year": 2026}
    now = datetime.utcnow()

    chart_post = client.post("/chart/api/chart-data", json=chart_payload)
    calendar_post = client.post("/calendar/api/selection", json=calendar_payload)
    events_get = client.get(f"/calendar/api/events?month={now.month}&year={now.year}")

    assert chart_post.status_code == 200
    assert calendar_post.status_code == 200
    assert events_get.status_code == 200
    chart_get = client.get("/chart/api/chart-data").json()
    assert chart_get["series"][0]["id"] == "Default"
    assert chart_get["series"][0]["data"][0]["value"] == 200.0
    assert client.get("/calendar/api/selection").json() == calendar_payload


def test_progressive_chart_history_is_isolated_by_session(monkeypatch) -> None:
    def _recent_history(self, name: str, *, period: str = "3y") -> HistoryChunk:
        frame = TimeSeriesDataFrame(
            {
                "time": ["2024-01-01", "2025-01-01", "2026-01-01"],
                "close": [100.0, 110.0, 120.0] if name == "AAPL" else [200.0, 210.0, 220.0],
            }
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

    monkeypatch.setattr(DataFactory, "get_recent_history", _recent_history)

    reset_private_data_service()
    client = TestClient(create_app())

    response_a = client.post(
        "/chart/api/chart-series/progressive/set",
        json={"name": "AAPL", "seedPeriod": "3y", "pinned": True},
        headers={"X-Session-ID": "session-a"},
    )
    response_b = client.post(
        "/chart/api/chart-series/progressive/set",
        json={"name": "MSFT", "seedPeriod": "3y", "pinned": True},
        headers={"X-Session-ID": "session-b"},
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["entries"] == [{"name": "AAPL", "pinned": True}]
    assert response_b.json()["entries"] == [{"name": "MSFT", "pinned": True}]
