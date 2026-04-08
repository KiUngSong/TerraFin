from typing import Literal

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    id: str
    title: str
    start: str
    category: Literal["earning", "macro", "event"] = "event"
    importance: str | None = None
    displayTime: str | None = None
    description: str | None = None
    source: str | None = None


class CalendarResponse(BaseModel):
    events: list[CalendarEvent]
