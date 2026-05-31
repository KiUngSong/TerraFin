from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


TERMINAL_PATH = "/terminal"


def create_terminal_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(TERMINAL_PATH)
    @router.get(f"{TERMINAL_PATH}/")
    def terminal_index():
        return FileResponse(
            build_dir / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    return router
