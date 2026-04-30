from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from TerraFin.data import get_data_factory
from TerraFin.data.cache.registry import get_cache_manager, refresh_all_due
from TerraFin.interface.watchlist_service import (
    WatchlistConfigurationError,
    WatchlistConflictError,
    WatchlistNotFoundError,
    WatchlistValidationError,
    get_watchlist_service,
)

from typing import Literal


DASHBOARD_API_PREFIX = "/dashboard/api"


class WatchlistItemResponse(BaseModel):
    symbol: str
    name: str
    move: str
    tags: list[str] = []


class WatchlistSnapshotResponse(BaseModel):
    items: list[WatchlistItemResponse]
    backendConfigured: bool
    mode: str


class WatchlistGroupResponse(BaseModel):
    tag: str
    count: int


class WatchlistGroupsResponse(BaseModel):
    groups: list[WatchlistGroupResponse]


class WatchlistCreateRequest(BaseModel):
    symbol: str
    tags: list[str] = []


class WatchlistSymbolEntry(BaseModel):
    symbol: str
    tags: list[str] = []


class WatchlistReplaceRequest(BaseModel):
    symbols: list[str | WatchlistSymbolEntry]


class WatchlistTagsRequest(BaseModel):
    tags: list[str]
    mode: Literal["set", "add", "remove"] = "set"


class WatchlistRenameGroupRequest(BaseModel):
    old: str
    new: str


class BreadthMetricResponse(BaseModel):
    label: str
    value: str
    tone: str


class MarketBreadthResponse(BaseModel):
    metrics: list[BreadthMetricResponse]


class TrailingForwardPeHistoryPointResponse(BaseModel):
    date: str
    value: float


class TrailingForwardPeSpreadResponse(BaseModel):
    date: str
    description: str
    latestValue: float | None = None
    usableCount: int | None = None
    requestedCount: int | None = None
    history: list[TrailingForwardPeHistoryPointResponse]


class CapeResponse(BaseModel):
    date: str | None = None
    cape: float | None = None


class FearGreedResponse(BaseModel):
    score: int | None = None
    rating: str
    timestamp: str
    previous_close: int | None = None
    previous_1_week: int | None = None
    previous_1_month: int | None = None


class CacheRefreshResponse(BaseModel):
    ok: bool
    force: bool
    sources: list[dict]


class CacheStatusResponse(BaseModel):
    sources: list[dict]


def create_dashboard_data_router() -> APIRouter:
    router = APIRouter()
    data_factory = get_data_factory()
    watchlist_service = get_watchlist_service()
    cache_manager = get_cache_manager()

    def _watchlist_response(items: list[dict]) -> WatchlistSnapshotResponse:
        backend_configured = watchlist_service.is_backend_configured()
        return WatchlistSnapshotResponse(
            items=[WatchlistItemResponse.model_validate(item) for item in items],
            backendConfigured=backend_configured,
            mode="mongo" if backend_configured else "fallback",
        )

    @router.get(f"{DASHBOARD_API_PREFIX}/watchlist", response_model=WatchlistSnapshotResponse)
    def api_get_watchlist_snapshot(group: str | None = Query(default=None)):
        return _watchlist_response(watchlist_service.get_watchlist_snapshot(group=group))

    @router.get(f"{DASHBOARD_API_PREFIX}/watchlist/groups", response_model=WatchlistGroupsResponse)
    def api_get_watchlist_groups():
        return WatchlistGroupsResponse(
            groups=[WatchlistGroupResponse(**g) for g in watchlist_service.list_groups()]
        )

    @router.post(f"{DASHBOARD_API_PREFIX}/watchlist/groups/rename", response_model=WatchlistSnapshotResponse)
    def api_rename_watchlist_group(body: WatchlistRenameGroupRequest = Body(...)):
        try:
            return _watchlist_response(watchlist_service.rename_group(body.old, body.new))
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.patch(f"{DASHBOARD_API_PREFIX}/watchlist/{{symbol}}/tags", response_model=WatchlistSnapshotResponse)
    def api_patch_watchlist_tags(symbol: str, body: WatchlistTagsRequest = Body(...)):
        try:
            if body.mode == "set":
                items = watchlist_service.set_tags(symbol, body.tags)
            elif body.mode == "add":
                items = watchlist_service.add_tags(symbol, body.tags)
            else:
                items = watchlist_service.remove_tags(symbol, body.tags)
            return _watchlist_response(items)
        except WatchlistNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(f"{DASHBOARD_API_PREFIX}/watchlist", response_model=WatchlistSnapshotResponse)
    def api_add_watchlist_symbol(body: WatchlistCreateRequest = Body(...)):
        try:
            return _watchlist_response(watchlist_service.add_symbol(body.symbol, tags=body.tags))
        except WatchlistConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put(f"{DASHBOARD_API_PREFIX}/watchlist", response_model=WatchlistSnapshotResponse)
    def api_replace_watchlist(body: WatchlistReplaceRequest = Body(...)):
        try:
            normalized = [
                s if isinstance(s, str) else s.model_dump()
                for s in body.symbols
            ]
            return _watchlist_response(watchlist_service.replace_symbols(normalized))
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete(f"{DASHBOARD_API_PREFIX}/watchlist/{{symbol}}", response_model=WatchlistSnapshotResponse)
    def api_remove_watchlist_symbol(symbol: str):
        try:
            return _watchlist_response(watchlist_service.remove_symbol(symbol))
        except WatchlistNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(f"{DASHBOARD_API_PREFIX}/market-breadth", response_model=MarketBreadthResponse)
    def api_get_market_breadth():
        metrics = data_factory.get_panel_data("market_breadth")
        return MarketBreadthResponse(metrics=[BreadthMetricResponse.model_validate(metric) for metric in metrics])

    @router.get(f"{DASHBOARD_API_PREFIX}/trailing-forward-pe-spread", response_model=TrailingForwardPeSpreadResponse)
    def api_get_trailing_forward_pe_spread():
        payload = data_factory.get_panel_data("trailing_forward_pe")
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        coverage = payload.get("coverage", {}) if isinstance(payload, dict) else {}
        history = payload.get("history", []) if isinstance(payload, dict) else []
        description = (
            "Trailing P/E minus forward P/E, used as a rough proxy for how much "
            "future earnings expectations diverge from trailing earnings."
        )
        return TrailingForwardPeSpreadResponse(
            date=str(payload.get("date", "")) if isinstance(payload, dict) else "",
            description=description,
            latestValue=summary.get("trailing_forward_pe_spread"),
            usableCount=coverage.get("usable"),
            requestedCount=coverage.get("requested"),
            history=[TrailingForwardPeHistoryPointResponse.model_validate(point) for point in history],
        )

    @router.get(f"{DASHBOARD_API_PREFIX}/cape", response_model=CapeResponse)
    def api_get_cape():
        data = data_factory.get_panel_data("cape")
        return CapeResponse(date=data.get("date"), cape=data.get("cape"))

    @router.get(f"{DASHBOARD_API_PREFIX}/fear-greed", response_model=FearGreedResponse)
    def api_get_fear_greed():
        return FearGreedResponse.model_validate(data_factory.get_panel_data("fear_greed"))

    @router.get(f"{DASHBOARD_API_PREFIX}/cache-status", response_model=CacheStatusResponse)
    def api_get_cache_status():
        return {"sources": cache_manager.get_status()}

    @router.post(f"{DASHBOARD_API_PREFIX}/cache-refresh", response_model=CacheRefreshResponse)
    def api_post_cache_refresh(force: bool = Query(default=False)):
        refresh_all_due(force=force)
        return CacheRefreshResponse(ok=True, force=force, sources=cache_manager.get_status())

    return router
