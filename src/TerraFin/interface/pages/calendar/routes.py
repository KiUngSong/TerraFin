from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


CALENDAR_PATH = "/calendar"


def create_calendar_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(CALENDAR_PATH)
    @router.get(f"{CALENDAR_PATH}/")
    def calendar_index():
        return FileResponse(
            build_dir / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    return router
