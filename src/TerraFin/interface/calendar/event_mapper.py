from datetime import datetime
from typing import Iterable, Mapping


def _get_optional_text(row: Mapping[str, object], field_name: str) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def transform_rows_to_calendar_events(
    rows: Iterable[Mapping[str, object]],
    category: str = "event",
) -> list[dict]:
    events: list[dict] = []
    date_event_count: dict[str, int] = {}

    for row in rows:
        date_str = str(row.get("Date", "")).strip()
        if not date_str:
            continue
        event_title = str(row.get("Event", "")).strip()
        if not event_title:
            continue
        try:
            start = datetime.strptime(date_str, "%Y/%m/%d").isoformat()
        except ValueError:
            # Skip malformed rows to keep API payload safe.
            continue

        count = date_event_count.get(date_str, 0)
        date_event_count[date_str] = count + 1

        events.append(
            {
                "title": event_title,
                "start": start,
                "id": f"{date_str.replace('/', '-')}-{count}",
                "category": category,
                "importance": _get_optional_text(row, "Importance"),
                "displayTime": _get_optional_text(row, "Time"),
                "description": _get_optional_text(row, "Description"),
                "source": _get_optional_text(row, "Source"),
            }
        )
    return events


def merge_calendar_event_rows(
    macro_rows: Iterable[Mapping[str, object]],
    earning_rows: Iterable[Mapping[str, object]],
) -> list[dict]:
    return transform_rows_to_calendar_events(macro_rows, category="macro") + transform_rows_to_calendar_events(
        earning_rows, category="earning"
    )
