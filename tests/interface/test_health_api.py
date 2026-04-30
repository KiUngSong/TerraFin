import pytest
from fastapi.testclient import TestClient

import TerraFin.interface.server as server_module


def test_health_endpoint_returns_stable_contract() -> None:
    client = TestClient(server_module.create_app())

    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["alive"] is True
    assert payload["service"] == "terrafin-interface"
    assert "version" in payload


def test_ready_returns_200_when_dependencies_are_available() -> None:
    client = TestClient(server_module.create_app())

    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["ready"] is True
    assert payload["checks"]["cache_manager"]["ok"] is True
    assert payload["checks"]["data_factory"]["ok"] is True


def test_ready_returns_503_when_dependency_check_fails(monkeypatch) -> None:
    def _raise_data_factory_error():
        raise RuntimeError("data factory unavailable")

    app = server_module.create_app()
    monkeypatch.setattr(server_module, "get_data_factory", _raise_data_factory_error)
    client = TestClient(app)

    response = client.get("/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "service_not_ready"
    assert payload["error"]["message"] == "Service is not ready."
    assert payload["error"]["details"]["checks"]["data_factory"]["ok"] is False


def test_probe_endpoints_remain_root_when_base_path_enabled() -> None:
    client = TestClient(server_module.create_app(base_path="/terrafin"))

    health_root = client.get("/health")
    ready_root = client.get("/ready")
    health_prefixed = client.get("/terrafin/health")
    ready_prefixed = client.get("/terrafin/ready")

    assert health_root.status_code == 200
    assert ready_root.status_code == 200
    assert health_prefixed.status_code == 404
    assert ready_prefixed.status_code == 404


def test_feature_routes_use_base_path_prefix_when_enabled() -> None:
    client = TestClient(server_module.create_app(base_path="/terrafin"))

    prefixed = client.get("/terrafin/dashboard/api/watchlist")
    unprefixed = client.get("/dashboard/api/watchlist")

    assert prefixed.status_code == 200
    assert unprefixed.status_code == 404


def test_root_redirects_to_dashboard() -> None:
    client = TestClient(server_module.create_app())

    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/dashboard"


def test_root_redirect_respects_base_path() -> None:
    client = TestClient(server_module.create_app(base_path="/terrafin"))

    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/terrafin/dashboard"


def test_create_app_raises_clear_error_when_frontend_build_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "BUILD_DIR", tmp_path / "missing-build")

    with pytest.raises(server_module.AppRuntimeError, match="Frontend build assets are missing or incomplete"):
        server_module.create_app()
