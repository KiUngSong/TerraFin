"""FRED-based macro event calendar.

Uses the FRED release/dates API to get upcoming dates for major US
economic releases. Free, reliable, covers full year ahead.
"""

from datetime import datetime, timezone

import requests

from TerraFin.configuration import load_terrafin_config
from TerraFin.data.contracts import CalendarEvent, EventList


_FRED_RELEASES_URL = "https://api.stlouisfed.org/fred/release/dates"

# Major US macro releases: FRED release_id → display name
MACRO_RELEASES: dict[int, dict] = {
    50: {"name": "Employment Situation (NFP)", "importance": "high"},
    53: {"name": "GDP", "importance": "high"},
    10: {"name": "CPI", "importance": "high"},
    46: {"name": "PPI", "importance": "high"},
    21: {"name": "FOMC Rate Decision", "importance": "high"},
    54: {"name": "Personal Income & Outlays (PCE)", "importance": "high"},
    9: {"name": "Retail Sales", "importance": "high"},
    180: {"name": "Jobless Claims", "importance": "medium"},
    352: {"name": "ADP Employment", "importance": "medium"},
    82: {"name": "ISM Manufacturing PMI", "importance": "medium"},
    323: {"name": "Michigan Consumer Sentiment", "importance": "medium"},
    86: {"name": "Durable Goods Orders", "importance": "medium"},
    475: {"name": "JOLTs (Job Openings)", "importance": "medium"},
    22: {"name": "Existing Home Sales", "importance": "low"},
    304: {"name": "New Home Sales", "importance": "low"},
    57: {"name": "Trade Balance", "importance": "low"},
    13: {"name": "Industrial Production", "importance": "low"},
    97: {"name": "Beige Book", "importance": "low"},
}


def get_macro_events(year: int, month: int) -> EventList:
    """Get macro calendar events for a given month."""
    all_events = get_macro_events_all()
    return EventList(events=[
        e for e in all_events
        if e.start.year == year and e.start.month == month
    ])


def get_macro_events_all() -> EventList:
    """Fetch all available macro calendar events (no month filter)."""
    api_key = load_terrafin_config().fred.api_key or ""
    if not api_key:
        return EventList.make_empty()

    events: list[CalendarEvent] = []
    day_counter: dict[str, int] = {}

    for release_id, info in MACRO_RELEASES.items():
        try:
            dates = _fetch_release_dates(release_id, api_key)
        except Exception:
            continue

        for date_str in dates:
            try:
                parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            day_counter[date_str] = day_counter.get(date_str, 0) + 1
            event_id = f"macro-{release_id}-{date_str}-{day_counter[date_str]}"

            events.append(CalendarEvent(
                id=event_id,
                title=info["name"],
                start=parsed,
                category="macro",
                importance=info["importance"],
                display_time="",
                source="FRED",
            ))

    events.sort(key=lambda e: e.start)
    return EventList(events=events)


def _fetch_release_dates(release_id: int, api_key: str) -> list[str]:
    """Fetch upcoming release dates from FRED API."""
    resp = requests.get(
        _FRED_RELEASES_URL,
        params={
            "release_id": release_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "include_release_dates_with_no_data": "true",
            "limit": 20,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return [d["date"] for d in data.get("release_dates", [])]
