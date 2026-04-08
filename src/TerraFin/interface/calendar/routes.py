from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from TerraFin.interface.calendar.state import (
    get_calendar_selection,
    set_calendar_selection,
)
from TerraFin.interface.private_data_service import get_private_data_service


CALENDAR_PATH = "/calendar"
CALENDAR_API_PATH = f"{CALENDAR_PATH}/api"


def _session_id(request: Request) -> str:
    return request.headers.get("X-Session-ID", "default")


class CalendarEvent(BaseModel):
    id: str
    title: str
    start: str
    category: Literal["earning", "macro", "event"] = "event"
    importance: str | None = None
    displayTime: str | None = None
    description: str | None = None
    source: str | None = None


class CalendarSelection(BaseModel):
    eventId: str | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=1970, le=2200)


class CalendarEventsResponse(BaseModel):
    events: list[CalendarEvent]
    count: int
    month: int
    year: int


class UpsertEventsRequest(BaseModel):
    events: list[CalendarEvent]


class UpsertEventsResponse(BaseModel):
    ok: bool
    count: int


class OkResponse(BaseModel):
    ok: bool


def create_calendar_router(build_dir: Path) -> APIRouter:
    router = APIRouter()
    private_data_service = get_private_data_service()

    @router.get(f"{CALENDAR_API_PATH}/events", response_model=CalendarEventsResponse)
    def api_get_calendar_events(
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=1970, le=2200),
        categories: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ):
        category_filter = None
        if categories:
            category_filter = {item.strip() for item in categories.split(",") if item.strip()}
        filtered = private_data_service.get_calendar_events(
            year=year,
            month=month,
            categories=category_filter,
            limit=limit,
        )
        model_events = [CalendarEvent.model_validate(event) for event in filtered]
        return CalendarEventsResponse(events=model_events, count=len(model_events), month=month, year=year)

    @router.post(f"{CALENDAR_API_PATH}/events", response_model=UpsertEventsResponse)
    def api_post_calendar_events(body: UpsertEventsRequest):
        private_data_service.set_calendar_events([event.model_dump() for event in body.events])
        return {"ok": True, "count": len(body.events)}

    @router.get(f"{CALENDAR_API_PATH}/selection", response_model=CalendarSelection | None)
    def api_get_calendar_selection(request: Request):
        return get_calendar_selection(_session_id(request))

    @router.post(f"{CALENDAR_API_PATH}/selection", response_model=OkResponse)
    def api_post_calendar_selection(request: Request, body: CalendarSelection):
        payload = body.model_dump(exclude_none=False)
        set_calendar_selection(payload, _session_id(request))
        return {"ok": True}

    @router.get(CALENDAR_PATH)
    @router.get(f"{CALENDAR_PATH}/")
    def calendar_index():
        return FileResponse(build_dir / "index.html")

    return router
