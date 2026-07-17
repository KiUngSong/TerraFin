"""Market Voices — dumb read-if-present renderer over the private endpoint.

The raw view docs (contract: ``data/contracts/voices.py``) are fetched once
over the private HTTP endpoint (same channel as Fear & Greed — no Mongo on
this read path) and shaped in one pass: gate out non-conforming docs, keep the
latest view per voice, tally the consensus. A voice exists iff it has one
conforming doc; there is no roster.

Rendering rules the shape encodes:
- card = latest doc by ``(as_of, ingested_at)``; the card always shows ``as_of``
- the consensus tally counts only views younger than STALE_AFTER_DAYS; older
  views still render with their visible date (never a UI "stale" tier)
- history is capped at HISTORY_MAX per voice, oldest -> newest
"""

import logging
from datetime import date, datetime, timezone

from pydantic import BaseModel

from TerraFin.data.contracts.voices import NAME_MAX_CHARS, STANCES, THESIS_MAX_CHARS


log = logging.getLogger(__name__)

SRC_MARKET_VOICES = "private.market_voices"
# Consensus tally window: an older view still shows (with its date) but is not
# a live vote. One global constant — never a per-voice or per-doc knob.
STALE_AFTER_DAYS = 60
# Most past views served per voice on the /history route.
HISTORY_MAX = 8


class MarketVoiceEntry(BaseModel):
    slug: str
    name: str
    as_of: str
    age_days: int
    stance: str
    thesis: str
    source_url: str = ""


class MarketVoicesSummary(BaseModel):
    bull: int
    bear: int
    neutral: int
    stale: int  # rendered but older than the tally window
    reporting: int  # voices with a conforming view


class MarketVoicesResponse(BaseModel):
    views: list[MarketVoiceEntry]
    summary: MarketVoicesSummary


def _conforms(doc: object, today: date) -> dict | None:
    """Contract gate: return the normalized renderable view, or None.

    Any doc in the collection is a candidate (read-if-present), so junk/debug
    docs must never become a public card. Normalizes slug/stance casing and
    drops a non-http(s) source_url (bad provenance doesn't erase an opinion).
    """
    if not isinstance(doc, dict):
        return None
    slug = str(doc.get("slug") or "").strip().lower()
    name = str(doc.get("name") or "").strip()
    thesis = str(doc.get("thesis") or "").strip()
    stance = str(doc.get("stance") or "").strip().lower()
    if not slug or not name or not thesis or stance not in STANCES:
        return None
    if len(name) > NAME_MAX_CHARS or len(thesis) > THESIS_MAX_CHARS:
        return None
    as_of = str(doc.get("as_of") or "").strip()[:10]
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError:
        return None
    if (parsed - today).days > 1:  # future-dated docs must not pin "latest"
        return None
    url = str(doc.get("source_url") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = ""
    return {
        "slug": slug,
        "name": name,
        "as_of": as_of,
        "age_days": max((today - parsed).days, 0),
        "stance": stance,
        "thesis": thesis,
        "source_url": url,
        # ordering only, stripped from responses
        "_ingested_at": str(doc.get("ingested_at") or ""),
    }


def _recency_key(view: dict) -> tuple[str, str]:
    return (view["as_of"], view["_ingested_at"])


def shape_market_voices(raw: object) -> dict:
    """One pass over the raw doc list -> {views, summary, history}.

    ``views`` = latest conforming view per voice, newest first. ``history`` =
    per-slug conforming views oldest->newest, capped at HISTORY_MAX (kept in
    the cached payload so /history needs no second fetch).
    """
    today = datetime.now(timezone.utc).date()
    by_slug: dict[str, list[dict]] = {}
    skipped = 0
    for doc in raw if isinstance(raw, list) else []:
        view = _conforms(doc, today)
        if view is None:
            skipped += 1
            continue
        by_slug.setdefault(view["slug"], []).append(view)
    if skipped:
        log.debug("market-voices: skipped %d non-conforming doc(s)", skipped)

    def public(view: dict) -> dict:
        return {k: v for k, v in view.items() if not k.startswith("_")}

    views: list[dict] = []
    history: dict[str, list[dict]] = {}
    bull = bear = neutral = stale = 0
    for slug, slug_views in by_slug.items():
        ordered = sorted(slug_views, key=_recency_key)
        latest = ordered[-1]
        views.append(public(latest))
        history[slug] = [public(v) for v in ordered[-HISTORY_MAX:]]
        if latest["age_days"] > STALE_AFTER_DAYS:
            stale += 1
        elif latest["stance"] == "bullish":
            bull += 1
        elif latest["stance"] == "bearish":
            bear += 1
        else:
            neutral += 1
    views.sort(key=lambda v: (v["as_of"], v["slug"]), reverse=True)
    return {
        "views": views,
        "summary": {
            "bull": bull,
            "bear": bear,
            "neutral": neutral,
            "stale": stale,
            "reporting": len(views),
        },
        "history": history,
    }


def _cached_payload() -> dict:
    from TerraFin.data.cache.registry import get_cache_manager
    from TerraFin.data.providers.private_access.panels import get_panel_payload

    payload = get_panel_payload(get_cache_manager(), SRC_MARKET_VOICES)
    return payload if isinstance(payload, dict) else {"views": [], "summary": None, "history": {}}


def get_market_voices() -> dict:
    """{views, summary} for the panel; empty views when nothing conforms."""
    payload = _cached_payload()
    summary = payload.get("summary") or {"bull": 0, "bear": 0, "neutral": 0, "stale": 0, "reporting": 0}
    return {"views": payload.get("views") or [], "summary": summary}


def get_market_voices_history(slug: str) -> list[dict]:
    """A voice's conforming views oldest->newest, capped at HISTORY_MAX.
    Unknown slug -> [] (read-if-present: no allowlist, no 404)."""
    history = _cached_payload().get("history") or {}
    return list(history.get(str(slug or "").strip().lower(), []))
