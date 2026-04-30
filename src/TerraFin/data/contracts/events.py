"""Calendar event contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Literal


EventCategory = Literal["macro", "earning", "fed", "dividend", "ipo"]
EventImportance = Literal["low", "medium", "high"]

_CATEGORIES = {"macro", "earning", "fed", "dividend", "ipo"}
_IMPORTANCES = {"low", "medium", "high"}


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: datetime
    category: EventCategory
    importance: EventImportance
    display_time: str
    description: str | None = None
    source: str | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError(
                f"CalendarEvent.start must be timezone-aware, got naive datetime {self.start!r}"
            )
        if self.category not in _CATEGORIES:
            raise ValueError(
                f"CalendarEvent.category must be one of {sorted(_CATEGORIES)}, got {self.category!r}"
            )
        if self.importance not in _IMPORTANCES:
            raise ValueError(
                f"CalendarEvent.importance must be one of {sorted(_IMPORTANCES)}, got {self.importance!r}"
            )


@dataclass
class EventList:
    events: list[CalendarEvent]

    def __post_init__(self) -> None:
        if not isinstance(self.events, list):
            raise ValueError(
                f"EventList.events must be a list, got {type(self.events).__name__}"
            )

    @classmethod
    def make_empty(cls) -> "EventList":
        return cls(events=[])

    def __iter__(self) -> Iterator[CalendarEvent]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, index):
        return self.events[index]
