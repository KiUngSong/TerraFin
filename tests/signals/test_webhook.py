"""Tests for the inbound signal webhook: secret enforcement, dedup, rate limit."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from TerraFin.data.contracts.alert_provider import InboundSignal
from TerraFin.interface.signals import webhook as wh


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    wh._seen_signal_ids.clear()
    wh._rate_buckets.clear()
    monkeypatch.delenv("TERRAFIN_SIGNALS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TERRAFIN_ALERT_WEBHOOK_SECRET", raising=False)


def test_verify_signature_raises_when_secret_unset():
    with pytest.raises(wh.WebhookSecretMissing):
        wh.verify_signature(b"{}", "anything")


def test_verify_signature_rejects_empty_header(monkeypatch):
    monkeypatch.setenv("TERRAFIN_SIGNALS_WEBHOOK_SECRET", "s3cret")
    assert wh.verify_signature(b"{}", "") is False


def test_verify_signature_accepts_valid_hmac(monkeypatch):
    monkeypatch.setenv("TERRAFIN_SIGNALS_WEBHOOK_SECRET", "s3cret")
    body = b'{"ticker":"AAPL","signal":"x"}'
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert wh.verify_signature(body, sig) is True


def test_verify_signature_rejects_wrong_hmac(monkeypatch):
    monkeypatch.setenv("TERRAFIN_SIGNALS_WEBHOOK_SECRET", "s3cret")
    assert wh.verify_signature(b"x", "deadbeef") is False


def test_is_duplicate_returns_false_for_no_id():
    sig = InboundSignal(ticker="AAPL", signal="x")
    assert wh.is_duplicate(sig) is False


def test_is_duplicate_dedups_same_id():
    s = InboundSignal(ticker="AAPL", signal="x", signal_id="abc")
    assert wh.is_duplicate(s) is False
    assert wh.is_duplicate(s) is True


def test_dedup_is_lru_bounded(monkeypatch):
    monkeypatch.setattr(wh, "_DEDUP_MAX", 5)
    for i in range(10):
        wh.is_duplicate(InboundSignal(ticker="X", signal="y", signal_id=f"id{i}"))
    assert len(wh._seen_signal_ids) == 5
    # Oldest evicted
    assert "id0" not in wh._seen_signal_ids
    assert "id9" in wh._seen_signal_ids


def test_rate_limit_allows_within_budget(monkeypatch):
    monkeypatch.setattr(wh, "_RATE_MAX", 3)
    for _ in range(3):
        assert wh.check_rate_limit("1.2.3.4") is True


def test_rate_limit_blocks_over_budget(monkeypatch):
    monkeypatch.setattr(wh, "_RATE_MAX", 3)
    for _ in range(3):
        wh.check_rate_limit("1.2.3.4")
    assert wh.check_rate_limit("1.2.3.4") is False
    # Other client unaffected
    assert wh.check_rate_limit("9.9.9.9") is True


def test_rate_limit_keys_are_lru_bounded(monkeypatch):
    monkeypatch.setattr(wh, "_RATE_MAX_KEYS", 5)
    for i in range(10):
        wh.check_rate_limit(f"client_{i}")
    assert len(wh._rate_buckets) == 5
    # Oldest evicted, newest retained
    assert "client_0" not in wh._rate_buckets
    assert "client_9" in wh._rate_buckets


def test_rate_limit_window_rolls_over(monkeypatch):
    monkeypatch.setattr(wh, "_RATE_MAX", 2)
    monkeypatch.setattr(wh, "_RATE_WINDOW_S", 60)
    fake_now = [1000.0]
    monkeypatch.setattr(wh.time, "monotonic", lambda: fake_now[0])
    assert wh.check_rate_limit("c") is True
    assert wh.check_rate_limit("c") is True
    assert wh.check_rate_limit("c") is False
    fake_now[0] += 61  # advance past window
    assert wh.check_rate_limit("c") is True


def test_rate_limit_empty_client_id_buckets_under_unknown():
    assert wh.check_rate_limit("") is True
    assert "unknown" in wh._rate_buckets
