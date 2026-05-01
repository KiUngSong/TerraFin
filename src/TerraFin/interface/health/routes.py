"""TerraFin ``/health`` — multi-component live status page.

Active probes, run on each request (no background polling). 30-second
in-process cache keeps refresh-spam from hammering Telegram / the signals
provider. Each probe has a 2-second timeout so one slow target doesn't hang
the whole page.

Components covered:

- **Agent** — checks whether at least one model provider has its
  ``auth_env_vars`` set. Static check; no remote call.
- **Telegram** — reads ``~/.terrafin/telegram.json`` and calls ``getMe``.
- **Signals provider** — reads ``TERRAFIN_SIGNALS_PROVIDER_URL`` and
  proxies the upstream monitor's ``/health`` JSON (DataFactory monitor
  reports per-broker WS state + last tick age).

Renders a small self-contained HTML page (no JS, no external CSS). Visit
``/health`` in a browser; ``GET /health.json`` returns the same data as
JSON for scripting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, JSONResponse

from TerraFin.signals.env import signals_env

log = logging.getLogger(__name__)

_TELEGRAM_CONFIG_PATH = Path.home() / ".terrafin" / "telegram.json"
_PROBE_TIMEOUT = 2.0
_CACHE_TTL_SEC = 30.0

_cache: dict[str, Any] = {"snapshot": None, "expires_at": 0.0}
_cache_lock = asyncio.Lock()


# --- Probes ----------------------------------------------------------------

def _probe_agent() -> dict[str, Any]:
    """Static: at least one provider has its auth env var set."""
    try:
        from TerraFin.agent.model_management import _CATALOGS  # type: ignore
    except Exception:
        # Fallback: hard-code the well-known env vars.
        env_groups = [
            ("OpenAI",        ("OPENAI_API_KEY",)),
            ("Anthropic",     ("ANTHROPIC_API_KEY",)),
            ("Gemini",        ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
            ("GitHub Copilot",("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")),
        ]
    else:
        env_groups = [(c.label if hasattr(c, "label") else c.id, c.auth_env_vars) for c in _CATALOGS]
    found: list[str] = []
    for label, env_vars in env_groups:
        if any(os.environ.get(v) for v in env_vars):
            found.append(label)
    if not found:
        return {"status": "down", "detail": "no provider env vars set"}
    return {"status": "ok", "detail": f"providers: {', '.join(found)}"}


async def _probe_telegram() -> dict[str, Any]:
    if not _TELEGRAM_CONFIG_PATH.exists():
        return {"status": "down", "detail": f"config missing: {_TELEGRAM_CONFIG_PATH}"}
    try:
        cfg = json.loads(_TELEGRAM_CONFIG_PATH.read_text())
        token = cfg.get("token")
        chat_id = cfg.get("chat_id")
    except Exception as exc:
        return {"status": "down", "detail": f"config unreadable: {exc}"}
    if not token:
        return {"status": "down", "detail": "config missing token"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        if r.status_code != 200:
            return {"status": "down", "detail": f"getMe HTTP {r.status_code}"}
        body = r.json()
        if not body.get("ok"):
            return {"status": "down", "detail": str(body.get("description", "getMe not ok"))}
        username = body.get("result", {}).get("username", "?")
        return {"status": "ok", "detail": f"@{username} (chat_id={chat_id or '?'})"}
    except asyncio.TimeoutError:
        return {"status": "down", "detail": f"getMe timeout >{_PROBE_TIMEOUT}s"}
    except Exception as exc:
        return {"status": "down", "detail": f"getMe error: {exc}"}


async def _probe_signals_provider() -> dict[str, Any]:
    url = signals_env("TERRAFIN_SIGNALS_PROVIDER_URL", "TERRAFIN_ALERT_PROVIDER_URL")
    if not url:
        return {"status": "down", "detail": "TERRAFIN_SIGNALS_PROVIDER_URL not set"}
    key = signals_env("TERRAFIN_SIGNALS_PROVIDER_KEY", "TERRAFIN_ALERT_PROVIDER_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            r = await client.get(url.rstrip("/") + "/health", headers=headers)
        if r.status_code != 200:
            return {"status": "down", "detail": f"upstream HTTP {r.status_code}"}
        upstream = r.json()
    except asyncio.TimeoutError:
        return {"status": "down", "detail": f"upstream timeout >{_PROBE_TIMEOUT}s"}
    except Exception as exc:
        return {"status": "down", "detail": f"upstream error: {exc}"}
    return {
        "status": upstream.get("status", "ok"),
        "detail": f"{upstream.get('subscribed_total', 0)} subs",
        "upstream": upstream,
    }


# --- Aggregation + caching -------------------------------------------------

async def _gather_snapshot() -> dict[str, Any]:
    agent = _probe_agent()
    telegram, signals = await asyncio.gather(
        _probe_telegram(), _probe_signals_provider()
    )
    rank = {"ok": 0, "starting": 0, "degraded": 1, "down": 2}
    overall = max(
        rank.get(agent["status"], 2),
        rank.get(telegram["status"], 2),
        rank.get(signals["status"], 2),
    )
    overall_label = {0: "ok", 1: "degraded", 2: "down"}[overall]
    return {
        "status": overall_label,
        "checked_at": time.time(),
        "components": {
            "agent": agent,
            "telegram": telegram,
            "signals": signals,
        },
    }


async def _get_snapshot(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not force and _cache["snapshot"] is not None and now < _cache["expires_at"]:
        return _cache["snapshot"]
    async with _cache_lock:
        if not force and _cache["snapshot"] is not None and time.monotonic() < _cache["expires_at"]:
            return _cache["snapshot"]
        snap = await _gather_snapshot()
        _cache["snapshot"] = snap
        _cache["expires_at"] = time.monotonic() + _CACHE_TTL_SEC
        return snap


# --- HTML rendering --------------------------------------------------------

_STATUS_COLORS = {
    "ok":       ("#047857", "#d1fae5"),  # text, bg
    "degraded": ("#b45309", "#fef3c7"),
    "down":     ("#b91c1c", "#fee2e2"),
    "starting": ("#1d4ed8", "#dbeafe"),
}


def _badge(status: str) -> str:
    fg, bg = _STATUS_COLORS.get(status, ("#334155", "#e2e8f0"))
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-weight:600;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:.5px;">{escape(status)}</span>'
    )


def _component_card(name: str, comp: dict[str, Any]) -> str:
    extra = ""
    upstream = comp.get("upstream")
    if upstream:
        brokers = upstream.get("brokers") or {}
        rows = []
        for bname, b in brokers.items():
            rows.append(
                f'<tr>'
                f'<td style="padding:4px 10px;color:#475569;">{escape(bname)}</td>'
                f'<td style="padding:4px 10px;">{_badge(str(b.get("status","?")))}</td>'
                f'<td style="padding:4px 10px;color:#475569;">{escape(str(b.get("detail","")))}</td>'
                f'<td style="padding:4px 10px;color:#475569;text-align:right;">'
                f'subs={b.get("subs",0)} '
                f'last_tick={b.get("last_tick_age_sec") if b.get("last_tick_age_sec") is not None else "—"}s'
                f'</td>'
                f'</tr>'
            )
        if rows:
            extra = (
                '<table style="width:100%;border-collapse:collapse;margin-top:10px;'
                'font-size:13px;background:#f8fafc;border-radius:8px;overflow:hidden;">'
                + "".join(rows) + "</table>"
            )
    return (
        '<div style="border:1px solid #e2e8f0;border-radius:12px;padding:16px 20px;'
        'background:#fff;box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">'
        f'<div style="font-weight:600;font-size:15px;color:#0f172a;">{escape(name)}</div>'
        f'{_badge(str(comp.get("status","?")))}'
        '</div>'
        f'<div style="margin-top:6px;color:#475569;font-size:13px;">{escape(str(comp.get("detail","")))}</div>'
        f'{extra}'
        '</div>'
    )


def _render_html(snap: dict[str, Any]) -> str:
    comps = snap["components"]
    cards = "".join(
        _component_card(name, comps[key])
        for name, key in (("Agent", "agent"), ("Telegram", "telegram"), ("Signals Provider", "signals"))
    )
    checked = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(snap["checked_at"]))
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TerraFin Health</title>
</head>
<body style="margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#0f172a;">
<div style="max-width:760px;margin:32px auto;padding:0 16px;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
    <h1 style="margin:0;font-size:22px;">TerraFin Health</h1>
    <div>{_badge(str(snap["status"]))}</div>
  </div>
  <div style="display:flex;flex-direction:column;gap:12px;">{cards}</div>
  <div style="margin-top:20px;color:#64748b;font-size:12px;">
    Checked {escape(checked)} · cache {int(_CACHE_TTL_SEC)}s · refresh: reload page
  </div>
</div>
</body></html>"""


def create_health_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_class=HTMLResponse)
    async def health_html(refresh: int = 0) -> Response:
        snap = await _get_snapshot(force=bool(refresh))
        return HTMLResponse(_render_html(snap))

    @router.get("/health.json")
    async def health_json(refresh: int = 0) -> JSONResponse:
        snap = await _get_snapshot(force=bool(refresh))
        return JSONResponse(snap)

    return router
