"""Inbound webhook helpers: HMAC verification + signal deduplication + rate limiting.

Single-worker only: in-memory dedup and rate-limit state are per-process. If you
run uvicorn with --workers > 1, deploy a shared store before relying on these.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import OrderedDict, deque
from threading import Lock

from TerraFin.data.contracts.alert_provider import InboundSignal
from TerraFin.signals.env import signals_env

log = logging.getLogger(__name__)

_DEDUP_MAX = 10_000
_seen_signal_ids: "OrderedDict[str, None]" = OrderedDict()
_dedup_lock = Lock()

_RATE_WINDOW_S = 60
_RATE_MAX = 60  # max requests per IP per window
_RATE_MAX_KEYS = 10_000  # cap total tracked clients to bound memory
_rate_buckets: "OrderedDict[str, deque[float]]" = OrderedDict()
_rate_lock = Lock()


class WebhookSecretMissing(RuntimeError):
    """Raised when no shared secret is configured — refuse all inbound signals."""


def get_webhook_secret() -> str:
    return signals_env("TERRAFIN_SIGNALS_WEBHOOK_SECRET", "TERRAFIN_ALERT_WEBHOOK_SECRET")


def verify_signature(body: bytes, header_sig: str) -> bool:
    """Return True iff X-Signature matches HMAC-SHA256(secret, body).

    Raises WebhookSecretMissing if no secret is configured. The endpoint must
    map this to a 503 — never silently accept.
    """
    secret = get_webhook_secret()
    if not secret:
        raise WebhookSecretMissing(
            "TERRAFIN_SIGNALS_WEBHOOK_SECRET is not set. Inbound signal endpoint disabled."
        )
    if not header_sig:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)


def is_duplicate(signal: InboundSignal) -> bool:
    """Return True if signal_id was already processed. LRU-bounded."""
    if not signal.signal_id:
        return False
    with _dedup_lock:
        if signal.signal_id in _seen_signal_ids:
            _seen_signal_ids.move_to_end(signal.signal_id)
            return True
        _seen_signal_ids[signal.signal_id] = None
        if len(_seen_signal_ids) > _DEDUP_MAX:
            _seen_signal_ids.popitem(last=False)
    return False


def check_rate_limit(client_id: str) -> bool:
    """Return True if request is within rate budget. Sliding window per client_id.

    `_rate_buckets` is an LRU-bounded OrderedDict: at most _RATE_MAX_KEYS
    distinct clients tracked at once. Oldest entries evicted under attack.
    """
    if not client_id:
        client_id = "unknown"
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW_S
    with _rate_lock:
        bucket = _rate_buckets.get(client_id)
        if bucket is None:
            bucket = deque()
            _rate_buckets[client_id] = bucket
            if len(_rate_buckets) > _RATE_MAX_KEYS:
                _rate_buckets.popitem(last=False)
        else:
            _rate_buckets.move_to_end(client_id)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RATE_MAX:
            return False
        bucket.append(now)
    return True


def forward_to_telegram(signal: InboundSignal) -> None:
    from TerraFin.signals.channels.telegram import TelegramChannel

    try:
        ch = TelegramChannel.from_config()
    except (FileNotFoundError, RuntimeError) as exc:
        log.warning("Telegram not configured, dropping signal %s: %s", signal.ticker, exc)
        return

    sev = f"[{signal.severity.upper()}] " if signal.severity else ""
    text = f"{sev}{signal.ticker}: {signal.signal}"
    ch.send(
        title="TerraFin Alert",
        body_md=text,
        payload={"signals": [signal.model_dump(mode="json")]},
    )
