"""Tests for signal route helpers — proxy header handling, status codes."""
from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from TerraFin.interface.signals import webhook as wh
from TerraFin.interface.signals.routes import _client_id, create_alerting_router


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    wh._seen_signal_ids.clear()
    wh._rate_buckets.clear()
    monkeypatch.delenv("TERRAFIN_ALERT_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TERRAFIN_TRUST_PROXY_HEADERS", raising=False)


def _mk_request(host: str = "1.1.1.1", xff: str = "") -> MagicMock:
    req = MagicMock()
    req.client.host = host
    req.headers = {"x-forwarded-for": xff} if xff else {}
    # MagicMock .get fallback: emulate dict.get
    req.headers = type("H", (dict,), {})(req.headers) if isinstance(req.headers, dict) else req.headers
    return req


def test_client_id_uses_socket_when_proxy_trust_off():
    req = _mk_request(host="1.1.1.1", xff="9.9.9.9")
    assert _client_id(req) == "1.1.1.1"


def test_client_id_honors_xff_when_trusted(monkeypatch):
    monkeypatch.setenv("TERRAFIN_TRUST_PROXY_HEADERS", "1")
    req = _mk_request(host="10.0.0.1", xff="9.9.9.9, 10.0.0.1")
    assert _client_id(req) == "9.9.9.9"


def test_client_id_falls_back_to_socket_when_xff_empty(monkeypatch):
    monkeypatch.setenv("TERRAFIN_TRUST_PROXY_HEADERS", "1")
    req = _mk_request(host="1.2.3.4", xff="")
    assert _client_id(req) == "1.2.3.4"


def test_client_id_falls_back_when_xff_first_entry_blank(monkeypatch):
    monkeypatch.setenv("TERRAFIN_TRUST_PROXY_HEADERS", "1")
    # Leading comma → first entry empty after split → must fall back to socket
    req = _mk_request(host="1.2.3.4", xff=", 9.9.9.9")
    assert _client_id(req) == "1.2.3.4"
    req = _mk_request(host="5.5.5.5", xff="   ")
    assert _client_id(req) == "5.5.5.5"


def _client_with_router() -> TestClient:
    app = FastAPI()
    app.include_router(create_alerting_router())
    return TestClient(app)


def test_endpoint_503_when_secret_unset():
    client = _client_with_router()
    resp = client.post(
        "/signals/api/signal",
        json={"ticker": "AAPL", "signal": "x"},
        headers={"x-signature": "deadbeef"},
    )
    assert resp.status_code == 503


def test_endpoint_401_on_bad_signature(monkeypatch):
    monkeypatch.setenv("TERRAFIN_ALERT_WEBHOOK_SECRET", "s3cret")
    client = _client_with_router()
    resp = client.post(
        "/signals/api/signal",
        json={"ticker": "AAPL", "signal": "x"},
        headers={"x-signature": "deadbeef"},
    )
    assert resp.status_code == 401


def test_oversized_body_rejected_413(monkeypatch):
    monkeypatch.setenv("TERRAFIN_ALERT_WEBHOOK_SECRET", "s3cret")
    client = _client_with_router()
    huge = b'{"ticker":"AAPL","signal":"' + b"x" * (70 * 1024) + b'"}'
    resp = client.post(
        "/signals/api/signal",
        content=huge,
        headers={"x-signature": "deadbeef", "content-type": "application/json"},
    )
    assert resp.status_code == 413


def test_unauth_requests_do_not_pollute_rate_bucket(monkeypatch):
    monkeypatch.setenv("TERRAFIN_ALERT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(wh, "_RATE_MAX", 3)
    client = _client_with_router()
    # 10 unsigned requests → all 401, none should consume the rate budget
    for _ in range(10):
        resp = client.post(
            "/signals/api/signal",
            json={"ticker": "AAPL", "signal": "x"},
            headers={"x-signature": "deadbeef"},
        )
        assert resp.status_code == 401
    # Round-3 invariant: unauth requests must not allocate any rate bucket
    assert not wh._rate_buckets


def test_legacy_alerting_path_still_routes(monkeypatch):
    monkeypatch.setenv("TERRAFIN_ALERT_WEBHOOK_SECRET", "s3cret")
    sent: list = []
    monkeypatch.setattr(
        "TerraFin.interface.signals.routes.forward_to_telegram",
        lambda s: sent.append(s),
    )
    client = _client_with_router()
    body = b'{"ticker":"AAPL","signal":"x"}'
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/alerting/api/signal",
        content=body,
        headers={"x-signature": sig, "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(sent) == 1
