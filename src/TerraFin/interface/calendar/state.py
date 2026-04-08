from copy import deepcopy
from datetime import datetime


DEFAULT_SESSION_ID = "default"

_calendar_events_by_session: dict[str, list[dict]] = {}
_calendar_selection_by_session: dict[str, dict | None] = {}


def _sample_events(now: datetime | None = None) -> list[dict]:
    base = now or datetime.utcnow()
    month = base.month
    year = base.year
    return [
        {
            "id": f"{year}-{month:02d}-05-0",
            "title": "US Nonfarm Payrolls",
            "start": f"{year}-{month:02d}-05T08:30:00",
            "category": "macro",
            "importance": "high",
            "displayTime": "08:30 ET",
            "description": "Monthly U.S. payroll growth and unemployment release.",
            "source": "BLS",
        },
        {
            "id": f"{year}-{month:02d}-12-0",
            "title": "CPI Inflation",
            "start": f"{year}-{month:02d}-12T08:30:00",
            "category": "macro",
            "importance": "high",
            "displayTime": "08:30 ET",
            "description": "Consumer Price Index report.",
            "source": "BLS",
        },
        {
            "id": f"{year}-{month:02d}-25-0",
            "title": "NVDA Earnings",
            "start": f"{year}-{month:02d}-25T16:05:00",
            "category": "earning",
            "importance": "high",
            "displayTime": "After market",
            "description": "Quarterly earnings call and guidance.",
            "source": "Company IR",
        },
    ]


def sample_calendar_events(now: datetime | None = None) -> list[dict]:
    return _sample_events(now=now)


def _ensure_session(session_id: str) -> None:
    if session_id not in _calendar_events_by_session:
        _calendar_events_by_session[session_id] = _sample_events()
    if session_id not in _calendar_selection_by_session:
        _calendar_selection_by_session[session_id] = None


def reset_calendar_state(initial_events: list[dict] | None = None) -> None:
    _calendar_events_by_session.clear()
    _calendar_selection_by_session.clear()

    _calendar_events_by_session[DEFAULT_SESSION_ID] = (
        deepcopy(initial_events) if initial_events is not None else _sample_events()
    )
    _calendar_selection_by_session[DEFAULT_SESSION_ID] = None


def get_calendar_events(session_id: str = DEFAULT_SESSION_ID) -> list[dict]:
    _ensure_session(session_id)
    return deepcopy(_calendar_events_by_session[session_id])


def set_calendar_events(events: list[dict], session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _calendar_events_by_session[session_id] = deepcopy(events)


def get_calendar_selection(session_id: str = DEFAULT_SESSION_ID) -> dict | None:
    _ensure_session(session_id)
    return deepcopy(_calendar_selection_by_session[session_id])


def set_calendar_selection(selection: dict | None, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _calendar_selection_by_session[session_id] = deepcopy(selection)
