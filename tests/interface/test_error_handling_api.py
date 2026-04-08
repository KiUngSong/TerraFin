from fastapi.testclient import TestClient

import TerraFin.interface.server as server_module
from TerraFin.interface.private_data_service import reset_private_data_service


def test_validation_error_payload_is_standardized() -> None:
    reset_private_data_service()
    client = TestClient(server_module.create_app())

    response = client.get("/calendar/api/events?month=13&year=2026", headers={"X-Request-ID": "req-422"})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["message"] == "Request validation failed."
    assert payload["error"]["request_id"] == "req-422"
    assert isinstance(payload["error"]["details"], list)
    assert len(payload["error"]["details"]) >= 1


def test_uncaught_exception_payload_is_standardized(monkeypatch) -> None:
    def _raise_unexpected():
        raise Exception("unexpected failure")

    monkeypatch.setattr(server_module, "_service_version", _raise_unexpected)
    reset_private_data_service()
    client = TestClient(server_module.create_app(), raise_server_exceptions=False)

    response = client.get("/health", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    payload = response.json()
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "Internal server error."
    assert payload["error"]["request_id"] == "req-500"
    assert "details" not in payload["error"]


def test_known_runtime_error_payload_is_standardized(monkeypatch) -> None:
    def _raise_private_data_error():
        raise RuntimeError("private data unavailable")

    reset_private_data_service()
    app = server_module.create_app()
    monkeypatch.setattr(server_module, "get_private_data_service", _raise_private_data_error)
    client = TestClient(app)

    response = client.get("/ready", headers={"X-Request-ID": "req-503"})
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "service_not_ready"
    assert payload["error"]["message"] == "Service is not ready."
    assert payload["error"]["request_id"] == "req-503"
    assert payload["error"]["details"]["checks"]["private_data_service"]["ok"] is False
