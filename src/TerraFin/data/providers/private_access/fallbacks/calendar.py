from datetime import datetime

from TerraFin.data.providers.private_access.fallbacks._loader import load_fallback_section
from TerraFin.data.providers.private_access.models import CalendarResponse


def get_calendar_fallback(now: datetime | None = None) -> CalendarResponse:
    base = now or datetime.utcnow()
    substitutions = {"year": f"{base.year}", "month": f"{base.month:02d}"}
    payload = load_fallback_section("calendar")
    templated_events: list[dict] = []
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        templated_events.append(
            {key: value.format(**substitutions) if isinstance(value, str) else value for key, value in event.items()}
        )
    return CalendarResponse.model_validate({"events": templated_events})
