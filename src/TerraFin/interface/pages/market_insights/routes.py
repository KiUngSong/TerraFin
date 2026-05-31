from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


MARKET_INSIGHTS_PATH = "/market-insights"


def create_market_insights_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get(MARKET_INSIGHTS_PATH)
    @router.get(f"{MARKET_INSIGHTS_PATH}/")
    def market_insights_index():
        return FileResponse(build_dir / "index.html")

    return router
