"""Macro calendar: data releases from FRED, FOMC dates from the Fed's calendar."""

import html
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from TerraFin.configuration import load_terrafin_config
from TerraFin.data.contracts import CalendarEvent, EventList

log = logging.getLogger(__name__)

_FRED_RELEASES_URL = "https://api.stlouisfed.org/fred/release/dates"
_FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# FRED release_id → name. IDs verified against the FRED /release endpoint; the
# prior table had ~half of them mislabeled, which emitted phantom dates.
MACRO_RELEASES: dict[int, dict] = {
    50: {"name": "Employment Situation (NFP)", "importance": "high"},
    53: {"name": "GDP", "importance": "high"},
    10: {"name": "CPI", "importance": "high"},
    46: {"name": "PPI", "importance": "high"},
    54: {"name": "Personal Income & Outlays (PCE)", "importance": "high"},
    9: {"name": "Retail Sales", "importance": "high"},
    180: {"name": "Jobless Claims", "importance": "medium"},
    194: {"name": "ADP Employment", "importance": "medium"},
    91: {"name": "Michigan Consumer Sentiment", "importance": "medium"},
    192: {"name": "JOLTs (Job Openings)", "importance": "medium"},
    97: {"name": "New Home Sales", "importance": "low"},
    51: {"name": "Trade Balance", "importance": "low"},
    13: {"name": "Industrial Production", "importance": "low"},
}
# Omitted (no reliable FRED schedule): ISM PMI, Durable Goods, Existing Home
# Sales, Beige Book.

_MONTH_NUM = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_MON = "(" + "|".join(_MONTH_NUM) + ")[a-z]*"
# Fed renders meetings as "June 16-17", "January 31-February 1", or "Apr/May 30-1".
# Groups: 1=month, 2=slashed 2nd month, 3=day1, 4=explicit 2nd month, 5=day2.
_MEETING = re.compile(
    _MON + r"(?:/" + _MON + r")?\s+(\d{1,2})\s*[-–]\s*(?:" + _MON + r"\s+)?(\d{1,2})\b")

_fomc_cache: tuple[str, ...] | None = None


def _fomc_decision_dates() -> tuple[str, ...]:
    """FOMC decision days from the Fed's own calendar (no economic feed carries
    FOMC). Empty if unreachable; cached only on success so failures retry."""
    global _fomc_cache
    if _fomc_cache is not None:
        return _fomc_cache
    try:
        resp = requests.get(_FED_FOMC_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        text = html.unescape(re.sub(r"<[^>]+>", " ", resp.text))
        years = list(re.finditer(r"(20\d\d)\s+FOMC Meetings", text))
        dates: set[str] = set()
        for i, ym in enumerate(years):
            year = ym.group(1)
            seg = text[ym.end(): (years[i + 1].start() if i + 1 < len(years) else len(text))]
            seg = seg.split("Note:", 1)[0]  # drop trailing "...scheduled for Jan X, <next yr>" note
            for m in _MEETING.finditer(seg):
                mon2 = m.group(2) or m.group(4)  # cross-month 2nd month, if any
                d1, d2 = int(m.group(3)), int(m.group(5))
                if mon2:                       # cross-month meeting ends on the 1st
                    if d2 == 1 and d1 >= 28:
                        dates.add(f"{year}-{_MONTH_NUM[mon2]:02d}-01")
                elif d2 == d1 + 1:             # same-month 2-day meeting
                    dates.add(f"{year}-{_MONTH_NUM[m.group(1)]:02d}-{d2:02d}")
        if dates:
            _fomc_cache = tuple(sorted(dates))
            return _fomc_cache
        log.warning("FOMC calendar parse found no dates")
    except Exception as exc:
        log.warning("FOMC calendar fetch failed: %s", exc)
    return ()


def get_macro_events(year: int, month: int) -> EventList:
    """Macro events for a given month."""
    return EventList(events=[
        e for e in get_macro_events_all()
        if e.start.year == year and e.start.month == month
    ])


def get_macro_events_all() -> EventList:
    """All macro events: FRED data releases + FOMC decisions."""
    api_key = load_terrafin_config().fred.api_key or ""
    if not api_key:
        return EventList.make_empty()

    events: list[CalendarEvent] = []
    day_counter: dict[str, int] = {}

    dropped: list[str] = []
    for release_id, info in MACRO_RELEASES.items():
        try:
            dates = _fetch_release_dates(release_id, api_key)
        except Exception as exc:
            log.warning("FRED release %s (%s) failed: %s", release_id, info["name"], exc)
            dropped.append(f"{info['name']}({info['importance']})")
            continue
        for date_str in dates:
            try:
                parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            day_counter[date_str] = day_counter.get(date_str, 0) + 1
            events.append(CalendarEvent(
                id=f"macro-{release_id}-{date_str}-{day_counter[date_str]}",
                title=info["name"],
                start=parsed,
                category="macro",
                importance=info["importance"],
                display_time="",
                source="FRED",
            ))

    for date_str in _fomc_decision_dates():
        try:
            parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        events.append(CalendarEvent(
            id=f"macro-fomc-{date_str}",
            title="FOMC Rate Decision",
            start=parsed,
            category="macro",
            importance="high",
            display_time="",
            source="Fed schedule",
        ))

    # A dropped release leaves a hole a consumer cannot tell apart from "nothing
    # scheduled" — the calendar still returns 200 with a plausible-looking list.
    # High-importance holes are the ones that mislead (CPI, PPI, NFP, PCE), so they
    # get an ERROR that names what is missing rather than one warning line per
    # release buried among the rest.
    if any("(high)" in d for d in dropped):
        log.error("MACRO CALENDAR INCOMPLETE — high-importance releases missing: %s. "
                  "Downstream will render this as 'nothing scheduled'.", ", ".join(dropped))

    events.sort(key=lambda e: e.start)
    return EventList(events=events)


def _fetch_release_dates(release_id: int, api_key: str) -> list[str]:
    """Scheduled release dates for a FRED release_id, from today forward.

    Asks for an explicit forward window. The previous query took the 20 newest
    dates with no range, which silently truncated the NEAR term for anything
    frequent: weekly Jobless Claims filled all 20 slots with dates months out and
    the next print vanished from the calendar.

    Retries: a single 10s timeout against FRED produced 124 swallowed failures in
    one server log, and every one of them deleted a release from the calendar for
    the rest of that process's life.
    """
    # Window starts BEHIND today: `_session_today()` on the consumer side honours a
    # backfill pin, so a re-render of an older session needs dates already past.
    today = date.today()
    params = {
        "release_id": release_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "include_release_dates_with_no_data": "true",
        "realtime_start": (today - timedelta(days=45)).isoformat(),
        "realtime_end": (today + timedelta(days=400)).isoformat(),
        "limit": 200,
    }
    last: Exception | None = None
    # Two attempts, not three: the caller reaches this over HTTP with a 15s client
    # timeout, so a long retry ladder across 13 releases just moves the failure from
    # "one release missing" to "the whole calendar request times out".
    for attempt, timeout in enumerate((12, 20), start=1):
        try:
            resp = requests.get(_FRED_RELEASES_URL, params=params, timeout=timeout)
            # A 4xx is a bad key or a bad release_id — retrying cannot fix it and
            # would turn a fast, legible config error into a slow one.
            resp.raise_for_status()
            return [d["date"] for d in resp.json().get("release_dates", [])]
        except requests.HTTPError as exc:
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                raise
            last = exc
        except Exception as exc:  # timeout, connection reset, malformed JSON
            last = exc
        if attempt < 2:
            time.sleep(2)
    raise last if last else RuntimeError("FRED release dates unavailable")
