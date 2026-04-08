import pytest
import requests

from TerraFin.data.providers.private_access.client import PrivateAccessClient
from TerraFin.data.providers.private_access.config import PrivateAccessConfig


class _StubResponse:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


def test_private_access_client_raises_when_endpoint_unconfigured() -> None:
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint=None, access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(RuntimeError, match="not configured"):
        client.fetch_watchlist_snapshot()


def test_private_access_client_propagates_http_errors(monkeypatch) -> None:
    def _mock_get(*args, **kwargs):
        _ = args, kwargs
        error = requests.HTTPError("500 server error")
        error.response = _StubResponse()
        error.response.status_code = 500
        return _StubResponse(error=error)

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint="https://example.test", access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(RuntimeError, match="Private source request failed for resource 'market-breadth' with HTTP 500."):
        client.fetch_market_breadth()


def test_private_access_client_propagates_request_exceptions(monkeypatch) -> None:
    def _mock_get(*args, **kwargs):
        _ = args, kwargs
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint="https://example.test", access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(RuntimeError, match="Private source request timed out for resource 'calendar-events'."):
        client.fetch_calendar_events()


def test_private_access_client_redacts_endpoint_for_auth_failures(monkeypatch) -> None:
    def _mock_get(*args, **kwargs):
        _ = args, kwargs
        error = requests.HTTPError("401 Client Error: Unauthorized for url: https://example.test/private/fear-greed")
        error.response = _StubResponse()
        error.response.status_code = 401
        return _StubResponse(error=error)

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(
            endpoint="https://example.test/private",
            access_key="X-API-Key",
            access_value="wrong",
            timeout_seconds=1.0,
        )
    )

    with pytest.raises(RuntimeError) as excinfo:
        client.fetch_fear_greed()

    message = str(excinfo.value)
    assert "TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE" in message
    assert "https://example.test/private/fear-greed" not in message


def test_private_access_client_rejects_non_dict_payload(monkeypatch) -> None:
    def _mock_get(*args, **kwargs):
        _ = args, kwargs
        return _StubResponse(payload=["not-a-dict"])

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint="https://example.test", access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(ValueError, match="Invalid payload"):
        client.fetch_watchlist_snapshot()


def test_private_access_client_fetches_normalized_private_series(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _mock_get(url, **kwargs):
        captured["url"] = url
        captured["api_key"] = kwargs.get("headers", {}).get("X-API-Key", "")
        return _StubResponse(
            payload={
                "key": "fear-greed",
                "name": "Fear & Greed",
                "data": [{"time": "2026-01-01", "close": 42}],
                "count": 1,
            }
        )

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(
            endpoint="https://example.test/private/",
            access_key="X-API-Key",
            access_value="secret",
            timeout_seconds=1.0,
        )
    )

    payload = client.fetch_series_history("fear-greed")

    assert captured["url"] == "https://example.test/private/series/fear-greed"
    assert captured["api_key"] == "secret"
    assert payload == [{"time": "2026-01-01", "close": 42}]


def test_private_access_client_fetches_top_companies(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _mock_get(url, **kwargs):
        captured["url"] = url
        captured["api_key"] = kwargs.get("headers", {}).get("X-API-Key", "")
        return _StubResponse(
            payload={
                "companies": [
                    {
                        "rank": 1,
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "marketCap": "$3.00 T",
                        "country": "United States",
                    }
                ],
                "count": 1,
            }
        )

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(
            endpoint="https://example.test/private/",
            access_key="X-API-Key",
            access_value="secret",
            timeout_seconds=1.0,
        )
    )

    payload = client.fetch_top_companies()

    assert captured["url"] == "https://example.test/private/top-companies?top_k=50"
    assert captured["api_key"] == "secret"
    assert payload.count == 1
    assert payload.companies[0].ticker == "AAPL"
