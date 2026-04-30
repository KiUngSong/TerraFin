"""Coverage for CUSIP -> ticker resolution + caching.

We don't hit the real OpenFIGI API in tests; the network call is monkeypatched
and only the response shape, parsing, ticker selection, and cache behavior
are verified.
"""

import json

import pytest
import requests

from TerraFin.data.providers.corporate import cusip_resolver


class _StubResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is _MalformedJsonSentinel:
            raise ValueError("not json")
        return self._payload


_MalformedJsonSentinel = object()


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch, tmp_path):
    """Redirect file cache to a temp dir so each test starts clean."""
    from TerraFin.data.cache import manager as cache_module

    monkeypatch.setattr(cache_module, "_FILE_CACHE_DIR", tmp_path)
    yield


def test_resolve_cusip_returns_ticker_from_us_listing(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json
        return _StubResponse(
            [
                {
                    "data": [
                        {"ticker": "AAPL", "exchCode": "US"},
                        {"ticker": "AAPL.MX", "exchCode": "MM"},
                    ]
                }
            ]
        )

    monkeypatch.setattr(cusip_resolver.requests, "post", fake_post)

    assert cusip_resolver.resolve_cusip_to_ticker("037833100") == "AAPL"
    assert captured["body"] == [{"idType": "ID_CUSIP", "idValue": "037833100"}]


def test_resolve_cusip_caches_misses(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _StubResponse([{"warning": "No identifier found."}])

    monkeypatch.setattr(cusip_resolver.requests, "post", fake_post)

    assert cusip_resolver.resolve_cusip_to_ticker("999999999") is None
    # Second call hits the on-disk cache, not OpenFIGI.
    assert cusip_resolver.resolve_cusip_to_ticker("999999999") is None
    assert calls["n"] == 1


def test_resolve_cusip_rejects_malformed_input(monkeypatch) -> None:
    monkeypatch.setattr(
        cusip_resolver.requests,
        "post",
        lambda *a, **k: pytest.fail("network must not be called for invalid CUSIP"),
    )

    assert cusip_resolver.resolve_cusip_to_ticker("not-a-cusip") is None
    assert cusip_resolver.resolve_cusip_to_ticker("") is None


def test_resolve_cusip_swallows_request_exceptions(monkeypatch) -> None:
    def boom(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(cusip_resolver.requests, "post", boom)

    assert cusip_resolver.resolve_cusip_to_ticker("037833100") is None
