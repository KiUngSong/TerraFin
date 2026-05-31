from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


STOCK_PATH = "/stock"


def create_stock_router(build_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/stock/")
    @router.get("/stock")
    def stock_index():
        return FileResponse(build_dir / "index.html")

    @router.get("/stock/{ticker}")
    def stock_detail(ticker: str):
        return FileResponse(build_dir / "index.html")

    return router
