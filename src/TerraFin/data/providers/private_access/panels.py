"""Private-source panel payloads (non-time-series).

Each panel maps to a backend resource under the private endpoint, registers a
CachePayloadSpec on the shared CacheManager, and exposes a typed accessor.
The DataFactory consumes these panels via `get_panel_data` / `get_calendar_events`.
"""

from datetime import datetime
from typing import Any

from TerraFin.data.cache.manager import CacheManager, CachePayloadSpec
from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.providers.economic.macro_calendar import get_macro_events_all
from TerraFin.data.providers.economic.macro_values import enrich_macro_events_all
from TerraFin.data.providers.private_access.client import PrivateAccessClient
from TerraFin.data.providers.private_access.config import load_private_access_config
from TerraFin.data.providers.private_access.fallbacks import get_calendar_fallback, get_market_breadth_fallback
from TerraFin.data.providers.private_access.models import (
    CalendarEvent,
    CalendarResponse,
    MarketBreadthResponse,
    TopCompaniesResponse,
    TrailingForwardPeSpreadResponse,
)
from TerraFin.data.providers.private_access.series import (
    PrivateSeriesSpec,
    get_private_series_current,
)
from TerraFin.data.providers.private_access.series_registry import PRIVATE_SERIES


SRC_BREADTH = "private.market_breadth"
SRC_PE_SPREAD = "private.trailing_forward_pe"
SRC_CAPE = "private.cape"
SRC_CALENDAR = "private.calendar"
SRC_MACRO = "private.macro"
SRC_FEAR_GREED = "private.fear_greed"
SRC_TOP_COMPANIES = "private.top_companies"


PANEL_SOURCES: tuple[str, ...] = (
    SRC_BREADTH,
    SRC_PE_SPREAD,
    SRC_CAPE,
    SRC_CALENDAR,
    SRC_MACRO,
    SRC_FEAR_GREED,
    SRC_TOP_COMPANIES,
)


def _client() -> PrivateAccessClient:
    return PrivateAccessClient(load_private_access_config())


def _load_market_breadth_panel() -> list[dict]:
    payload = _client().fetch_panel("market-breadth")
    response = MarketBreadthResponse.model_validate(payload)
    return [metric.model_dump() for metric in response.metrics]


def _fetch_trailing_forward_pe() -> dict:
    payload = _client().fetch_panel("trailing-forward-pe-spread")
    return TrailingForwardPeSpreadResponse.model_validate(payload).model_dump()


def _load_calendar_panel() -> list[dict]:
    payload = _client().fetch_panel("calendar-events")
    response = CalendarResponse.model_validate(payload)
    return [event.model_dump() for event in response.events]


def _load_top_companies_panel() -> list[dict]:
    payload = _client().fetch_panel("top-companies?top_k=50")
    response = TopCompaniesResponse.model_validate(payload)
    return [company.model_dump(exclude_none=True) for company in response.companies]


def _fetch_cape() -> dict:
    snapshot = get_private_series_current(PRIVATE_SERIES["cape"], force_refresh=True)
    md = dict(snapshot.metadata) if snapshot.metadata else {}
    return {"date": md.get("date"), "cape": md.get("cape")}


def _fear_greed_rating(score: float | int | None) -> str:
    if score is None:
        return "Unavailable"
    s = float(score)
    if s <= 24:
        return "Extreme Fear"
    if s <= 44:
        return "Fear"
    if s <= 54:
        return "Neutral"
    if s <= 74:
        return "Greed"
    return "Extreme Greed"


def _fetch_fear_greed() -> dict:
    snapshot = get_private_series_current(PRIVATE_SERIES["fear_greed"], force_refresh=True)
    md = dict(snapshot.metadata) if snapshot.metadata else {}
    score = md.get("score")
    previous_close = md.get("previous_close")
    effective_score = score if score is not None else previous_close
    raw_rating = md.get("rating")
    rating = raw_rating if raw_rating and raw_rating != "Unavailable" else _fear_greed_rating(effective_score)
    return {
        "score": effective_score,
        "rating": rating,
        "timestamp": str(md.get("timestamp") or ""),
        "previous_close": previous_close,
        "previous_1_week": md.get("previous_1_week"),
        "previous_1_month": md.get("previous_1_month"),
    }


def _fetch_macro_events() -> list[dict]:
    enriched = enrich_macro_events_all(get_macro_events_all())
    return [
        {
            "id": event.id,
            "title": event.title,
            "start": event.start.isoformat().replace("+00:00", ""),
            "category": event.category,
            "importance": event.importance,
            "description": event.description,
            "source": event.source,
        }
        for event in enriched
    ]


_PANEL_SPECS: tuple[CachePayloadSpec, ...] = (
    CachePayloadSpec(
        source=SRC_BREADTH,
        namespace="private_breadth",
        key="metrics",
        ttl_seconds=ttl_for(SRC_BREADTH),
        fetch_fn=_load_market_breadth_panel,
        fallback_fn=lambda: [metric.model_dump() for metric in get_market_breadth_fallback().metrics],
    ),
    CachePayloadSpec(
        source=SRC_PE_SPREAD,
        namespace="private_pe_spread",
        key="spread",
        ttl_seconds=ttl_for(SRC_PE_SPREAD),
        fetch_fn=_fetch_trailing_forward_pe,
        fallback_fn=lambda: {"date": "", "summary": {}, "coverage": {}, "history": []},
    ),
    CachePayloadSpec(
        source=SRC_CAPE,
        namespace="private_cape",
        key="current",
        ttl_seconds=ttl_for(SRC_CAPE),
        fetch_fn=_fetch_cape,
        fallback_fn=lambda: {"date": None, "cape": None},
    ),
    CachePayloadSpec(
        source=SRC_CALENDAR,
        namespace="private_calendar",
        key="events",
        ttl_seconds=ttl_for(SRC_CALENDAR),
        fetch_fn=_load_calendar_panel,
        fallback_fn=lambda: [event.model_dump() for event in get_calendar_fallback().events],
    ),
    CachePayloadSpec(
        source=SRC_MACRO,
        namespace="private_macro",
        key="events",
        ttl_seconds=ttl_for(SRC_MACRO),
        fetch_fn=_fetch_macro_events,
        fallback_fn=lambda: [],
    ),
    CachePayloadSpec(
        source=SRC_FEAR_GREED,
        namespace="private_fear_greed_current",
        key="current",
        ttl_seconds=ttl_for(SRC_FEAR_GREED),
        fetch_fn=_fetch_fear_greed,
        fallback_fn=lambda: {
            "score": None,
            "rating": "Unavailable",
            "timestamp": "",
            "previous_close": None,
            "previous_1_week": None,
            "previous_1_month": None,
        },
    ),
    CachePayloadSpec(
        source=SRC_TOP_COMPANIES,
        namespace="private_top_companies",
        key="companies",
        ttl_seconds=ttl_for(SRC_TOP_COMPANIES),
        fetch_fn=_load_top_companies_panel,
        fallback_fn=lambda: [],
    ),
)


def register_panel_sources(manager: CacheManager) -> None:
    for spec in _PANEL_SPECS:
        manager.register_payload(spec)


def get_panel_payload(manager: CacheManager, source: str) -> Any:
    """Return the raw cached payload (dict or list[dict]) for a registered panel."""
    return manager.get_payload(source).payload


def _parse_event_start(start: str) -> datetime | None:
    text = (start or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(text, "%Y/%m/%d")
        except ValueError:
            return None


def _filter_calendar_events(
    events: list[CalendarEvent],
    *,
    year: int,
    month: int,
    categories: set[str] | None,
) -> list[CalendarEvent]:
    filtered: list[CalendarEvent] = []
    for event in events:
        parsed = _parse_event_start(event.start)
        if parsed is None:
            continue
        if parsed.year != year or parsed.month != month:
            continue
        if categories and event.category not in categories:
            continue
        filtered.append(event)
    filtered.sort(key=lambda item: item.start)
    return filtered


def get_calendar_events_merged(
    manager: CacheManager,
    *,
    year: int,
    month: int,
    categories: set[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Calendar events merged from the private source plus enriched macro events."""
    raw = get_panel_payload(manager, SRC_CALENDAR)
    source_events = [CalendarEvent.model_validate(event) for event in raw]
    filtered = _filter_calendar_events(source_events, year=year, month=month, categories=categories)
    result = [event.model_dump() for event in filtered]

    if categories is None or "macro" in categories:
        for event in get_panel_payload(manager, SRC_MACRO):
            try:
                dt_str = event.get("start", "")[:10]
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            except (ValueError, IndexError):
                continue
            if dt.year == year and dt.month == month:
                if categories and event.get("category") not in categories:
                    continue
                result.append(event)

    result.sort(key=lambda e: e.get("start", ""))
    if limit is not None:
        result = result[:limit]
    return result


def set_calendar_events(manager: CacheManager, events: list[dict]) -> None:
    manager.set_payload(SRC_CALENDAR, list(events))


def clear_panel_caches(manager: CacheManager) -> None:
    for source in PANEL_SOURCES:
        manager.clear_payload(source)


# Re-export PrivateSeriesSpec at module level for typing if needed
__all__ = [
    "PANEL_SOURCES",
    "SRC_BREADTH",
    "SRC_PE_SPREAD",
    "SRC_CAPE",
    "SRC_CALENDAR",
    "SRC_MACRO",
    "SRC_FEAR_GREED",
    "SRC_TOP_COMPANIES",
    "register_panel_sources",
    "get_panel_payload",
    "get_calendar_events_merged",
    "set_calendar_events",
    "clear_panel_caches",
    "PrivateSeriesSpec",
]
