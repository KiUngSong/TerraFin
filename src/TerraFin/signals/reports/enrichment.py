"""Optional agent enrichment for the weekly report.

The deterministic skeleton is canonical — agent enrichment is *additive
context only*, never overrides numbers. Each section is wrapped with
provenance (URL when available, else `(via tool_name)`) so the reader
knows which parts are tool-derived facts vs. LLM commentary.

Sections (each independently optional — a failure in one never blocks the
others, and a total enrichment failure leaves the deterministic report
intact):

1. Index context — one LLM paragraph placing the watchlist groups against
   ^GSPC / ^SOX / ^RUT WoW. Uses the agent runtime so the LLM does the
   tool selection + comparison wording.
2. SEC drill — for each ``intra_week_events`` entry where the caller flags
   ``unattributed=True``, look up an 8-K within ±2 days via the direct
   ``/agent/api/sec-filings`` route. Deterministic, no LLM. Cites the
   EDGAR ``documentUrl`` so the reader can verify.
3. Macro context — pulls ``calendar_events`` for the current month (and
   prior month if the report's ±5d window straddles a boundary) via the
   direct ``/agent/api/calendar`` route, filters to FOMC / CPI / payrolls
   inside the window. Deterministic, no LLM.

Disabled silently when the agent runtime is unavailable (no API key, etc.)
so the basic report still ships.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

_BASE = "http://0.0.0.0:8001"
_AGENT_NAME = "terrafin-assistant"
_INDEX_CALL_TIMEOUT = 180  # seconds for the single LLM paragraph
_HTTP_TIMEOUT = 15  # seconds for direct data routes (sec-filings, calendar)

# Macro events we surface in the optional macro section. Matched against
# the lower-cased calendar event title — broad enough to catch the common
# title variants ("FOMC Meeting", "FOMC Rate Decision", "CPI (YoY)", ...).
_MACRO_KEYWORDS = ("fomc", "cpi", "ppi", "payroll", "nonfarm", "unemployment")


# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------


def is_agent_available() -> bool:
    """Quick probe: is the hosted agent runtime configured?"""
    try:
        with urllib.request.urlopen(
            f"{_BASE}/agent/api/runtime/agents", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return False
    for a in data.get("agents", []):
        if a.get("name") == _AGENT_NAME and a.get("runtimeConfigured"):
            return True
    return False


def _post(path: str, body: dict, timeout: int) -> dict | None:
    try:
        req = urllib.request.Request(
            f"{_BASE}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("agent post %s failed: %s", path, exc)
        return None


def _get(path: str, params: dict | None = None, timeout: int = _HTTP_TIMEOUT) -> dict | None:
    url = f"{_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("agent get %s failed: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Section 1 — Index context (LLM paragraph)
# ---------------------------------------------------------------------------


def _index_context(per_ticker_summary: list[dict], as_of: date) -> str | None:
    sess = _post("/agent/api/runtime/sessions", {"agentName": _AGENT_NAME}, timeout=10)
    if not sess or not sess.get("sessionId"):
        return None
    sid = sess["sessionId"]

    # Strip events to keep the prompt tight — the LLM only needs WoW + tags
    # to write the comparison paragraph.
    trimmed = [
        {"symbol": t["symbol"], "tags": t.get("tags") or [], "wow_pct": t.get("wow_pct")}
        for t in per_ticker_summary
    ]
    summary_json = json.dumps(trimmed, ensure_ascii=False)
    prompt = (
        f"Today is {as_of.isoformat()}. Run the following automatically — do NOT ask "
        f"for confirmation, do NOT request permission. The market_data tool is read-only.\n\n"
        f"Tool selection rule: use the `market_data` tool with `ticker=^GSPC|^SOX|^RUT` "
        f"and `period='1mo'`. Do NOT use the `indicators` tool — it does not carry these "
        f"index symbols and will error.\n\n"
        f"Step 1: call market_data with ticker='^GSPC' and period='1mo'.\n"
        f"Step 2: call market_data with ticker='^SOX' and period='1mo'.\n"
        f"Step 3: call market_data with ticker='^RUT' and period='1mo'.\n"
        f"Step 4: for each, compute the 5-trading-day close-to-close % return.\n"
        f"Step 5: write exactly one paragraph (2-3 sentences) placing the watchlist groups "
        f"against those indices. Tag each index like '(^GSPC +X.XX% via market_data)'. "
        f"If a market_data call errors, omit that index silently. "
        f"Do NOT restate the per-ticker data. Do NOT ask questions. "
        f"Output only the paragraph.\n\n"
        f"WATCHLIST (already has WoW per ticker):\n{summary_json}"
    )
    result = _post(
        f"/agent/api/runtime/sessions/{sid}/messages",
        {"content": prompt},
        timeout=_INDEX_CALL_TIMEOUT,
    )
    if not result:
        return None
    fm = result.get("finalMessage") or {}
    content = fm.get("content") if isinstance(fm, dict) else None
    if not content or not isinstance(content, str):
        return None
    return content.strip()


# ---------------------------------------------------------------------------
# Section 2 — SEC drill on unattributed events
# ---------------------------------------------------------------------------


def _sec_drill(per_ticker_summary: list[dict], window_days: int = 2) -> list[str]:
    """For each unattributed intra-week event, look up an 8-K within ±window_days.

    Returns one markdown bullet per resolved event, citing the EDGAR
    ``documentUrl``. Tickers without an unattributed event are skipped.
    Failures per ticker are swallowed so one bad lookup never sinks the
    section.
    """
    lines: list[str] = []
    seen_tickers: set[str] = set()
    cache: dict[str, list[dict]] = {}
    for t in per_ticker_summary:
        sym = t.get("symbol")
        if not sym:
            continue
        unresolved = [
            ev
            for ev in (t.get("intra_week_events") or [])
            if ev.get("unattributed")
        ]
        if not unresolved:
            continue
        if sym not in cache:
            payload = _get("/agent/api/sec-filings", {"ticker": sym})
            cache[sym] = (payload or {}).get("filings") or []
        filings = cache[sym]
        if not filings:
            continue
        eight_ks = [f for f in filings if (f.get("form") or "").startswith("8-K")]
        if not eight_ks:
            continue
        for ev in unresolved:
            ev_date_str = ev.get("date")
            try:
                ev_date = datetime.strptime(ev_date_str, "%Y-%m-%d").date()
            except Exception:
                continue
            best: dict | None = None
            best_gap = None
            for f in eight_ks:
                try:
                    fd = datetime.strptime(f.get("filingDate") or "", "%Y-%m-%d").date()
                except Exception:
                    continue
                gap = abs((fd - ev_date).days)
                if gap > window_days:
                    continue
                if best_gap is None or gap < best_gap:
                    best, best_gap = f, gap
            if not best:
                continue
            move = ev.get("move_pct")
            sign = "+" if (move or 0) > 0 else ""
            url = best.get("documentUrl") or best.get("indexUrl")
            desc = best.get("primaryDocDescription") or "8-K"
            link = f"[8-K {best['filingDate']}]({url})" if url else f"8-K {best['filingDate']}"
            lines.append(
                f"- **{sym}** {ev_date_str} ({sign}{move}%) → {link} — {desc}"
            )
            seen_tickers.add(sym)
    return lines


# ---------------------------------------------------------------------------
# Section 3 — Macro context (FOMC / CPI / payrolls inside ±5d)
# ---------------------------------------------------------------------------


def _macro_context(as_of: date, window_days: int = 5) -> list[str]:
    """Pull FOMC/CPI/payrolls events within ±window_days of as_of.

    Hits ``/agent/api/calendar`` directly (deterministic, no LLM). Queries
    the current month plus the prior or next month if the window straddles
    a boundary.
    """
    months_to_query: list[tuple[int, int]] = [(as_of.year, as_of.month)]
    early_edge = as_of - timedelta(days=window_days)
    late_edge = as_of + timedelta(days=window_days)
    if early_edge.month != as_of.month:
        months_to_query.append((early_edge.year, early_edge.month))
    if late_edge.month != as_of.month:
        months_to_query.append((late_edge.year, late_edge.month))

    events: list[dict] = []
    for yr, mo in months_to_query:
        payload = _get("/agent/api/calendar", {"year": yr, "month": mo})
        if not payload:
            continue
        for e in payload.get("events") or []:
            events.append(e)

    lo, hi = as_of - timedelta(days=window_days), as_of + timedelta(days=window_days)
    out: list[str] = []
    seen: set[str] = set()
    for e in events:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        tlow = title.lower()
        if not any(k in tlow for k in _MACRO_KEYWORDS):
            continue
        start = (e.get("start") or "")[:10]
        try:
            d = datetime.strptime(start, "%Y-%m-%d").date()
        except Exception:
            continue
        if d < lo or d > hi:
            continue
        key = f"{start}|{tlow}"
        if key in seen:
            continue
        seen.add(key)
        rel = (d - as_of).days
        when = "today" if rel == 0 else (f"in {rel}d" if rel > 0 else f"{-rel}d ago")
        out.append(f"- {start} ({when}): **{title}** *(via calendar_events)*")
    return out


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def render_enrichment_section(per_ticker_summary: list[dict], as_of: date) -> str:
    """Build the optional agent-enrichment markdown block, or empty string.

    Each subsection is independent — partial failures are tolerated. Total
    failure (or runtime unavailable) returns ``""`` so the caller appends
    nothing.
    """
    if not is_agent_available():
        return ""

    body_parts: list[str] = []

    # Section 1 — index context (LLM paragraph)
    try:
        idx_text = _index_context(per_ticker_summary, as_of)
    except Exception:
        log.exception("index-context enrichment failed")
        idx_text = None
    if idx_text:
        body_parts.append("### Index Context\n\n" + idx_text)

    # Section 2 — SEC drill
    try:
        sec_lines = _sec_drill(per_ticker_summary)
    except Exception:
        log.exception("sec-drill enrichment failed")
        sec_lines = []
    if sec_lines:
        body_parts.append(
            "### Unattributed Move Drill (8-K ±2d)\n\n" + "\n".join(sec_lines)
        )

    # Section 3 — macro context
    try:
        macro_lines = _macro_context(as_of)
    except Exception:
        log.exception("macro-context enrichment failed")
        macro_lines = []
    if macro_lines:
        body_parts.append(
            "### Macro Calendar (±5d)\n\n" + "\n".join(macro_lines)
        )

    if not body_parts:
        return ""

    header = (
        "\n## 🤖 Agent Enrichment\n"
        "*Sections below are generated from agent tool calls. Numbers above "
        "are deterministic; numbers below carry the cited source.*\n\n"
    )
    return header + "\n\n".join(body_parts) + "\n"
