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
        return _StubResponse(error=requests.HTTPError("500 server error"))

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint="https://example.test", access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(requests.HTTPError):
        client.fetch_market_breadth()


def test_private_access_client_propagates_request_exceptions(monkeypatch) -> None:
    def _mock_get(*args, **kwargs):
        _ = args, kwargs
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests, "get", _mock_get)
    client = PrivateAccessClient(
        PrivateAccessConfig(endpoint="https://example.test", access_key=None, access_value=None, timeout_seconds=1.0)
    )
    with pytest.raises(requests.Timeout):
        client.fetch_calendar_events()


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
