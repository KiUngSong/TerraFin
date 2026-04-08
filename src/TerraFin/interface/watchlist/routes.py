from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


WATCHLIST_PATH = "/watchlist"


def create_watchlist_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(WATCHLIST_PATH)
    @router.get(f"{WATCHLIST_PATH}/")
    def watchlist_index():
        return FileResponse(build_dir / "index.html")

    return router
