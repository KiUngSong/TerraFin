"""Inbound alert webhook endpoint.

Primary path: POST /signals/api/signal
Legacy alias: POST /alerting/api/signal  (kept so existing senders keep working)
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request

from TerraFin.data.contracts.alert_provider import InboundSignal
from TerraFin.interface.signals.webhook import (
    WebhookSecretMissing,
    check_rate_limit,
    forward_to_telegram,
    is_duplicate,
    verify_signature,
)

log = logging.getLogger(__name__)

SIGNALS_API_PREFIX = "/signals/api"
ALERTING_API_PREFIX = "/alerting/api"  # legacy

# Inbound signal payloads are tiny (a few hundred bytes). Cap at 64KB to bound
# the HMAC + JSON-parse cost an unauthenticated caller can force.
_MAX_BODY_BYTES = 64 * 1024


def _client_id(request: Request) -> str:
    """Identify the caller for rate-limit bucketing.

    Behind a reverse proxy, request.client.host is the proxy IP, so every
    inbound request shares one bucket and the limit becomes useless. Set
    TERRAFIN_TRUST_PROXY_HEADERS=1 only when running behind a trusted proxy
    that strips/rewrites X-Forwarded-For; otherwise clients can spoof the
    header and bypass the limit.

    Falls back to socket IP when the header is missing or its leftmost entry
    is empty/whitespace (which would otherwise collapse all malformed-header
    callers onto one shared bucket).
    """
    socket_ip = request.client.host if request.client else "unknown"
    if os.environ.get("TERRAFIN_TRUST_PROXY_HEADERS") == "1":
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    return socket_ip


async def _handle_signal(request: Request, x_signature: str):
    # Cap body size BEFORE buying any auth/parse cost. Reject via
    # Content-Length when present; otherwise enforce after read.
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    # Auth first: reject before touching the rate-limit bucket so unsigned
    # probes (or XFF-spoofing attackers) cannot pollute legitimate senders'
    # buckets and DOS them via 429.
    try:
        ok = verify_signature(body, x_signature)
    except WebhookSecretMissing:
        log.error("Inbound signal rejected: webhook secret not configured")
        raise HTTPException(
            status_code=503,
            detail="Inbound signal endpoint disabled: TERRAFIN_SIGNALS_WEBHOOK_SECRET not set",
        )
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid signature")

    if not check_rate_limit(_client_id(request)):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Parse only after auth + rate-limit pass.
    try:
        payload = InboundSignal.model_validate_json(body)
    except Exception as exc:
        log.warning("Invalid InboundSignal payload after valid signature: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid payload")

    if is_duplicate(payload):
        log.debug("Duplicate signal ignored: %s", payload.signal_id)
        return {"status": "duplicate"}

    log.info("Signal received: %s — %s", payload.ticker, payload.signal)
    forward_to_telegram(payload)
    return {"status": "ok"}


def create_alerting_router() -> APIRouter:
    router = APIRouter()

    @router.post(f"{SIGNALS_API_PREFIX}/signal", status_code=200)
    async def inbound_signal(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await _handle_signal(request, x_signature)

    @router.post(f"{ALERTING_API_PREFIX}/signal", status_code=200, include_in_schema=False)
    async def inbound_signal_legacy(
        request: Request,
        x_signature: str = Header(default=""),
    ):
        return await _handle_signal(request, x_signature)

    return router
