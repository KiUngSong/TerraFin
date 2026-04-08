from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


DASHBOARD_PATH = "/dashboard"


def create_dashboard_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(DASHBOARD_PATH)
    @router.get(f"{DASHBOARD_PATH}/")
    def dashboard_index():
        return FileResponse(build_dir / "index.html")

    return router
