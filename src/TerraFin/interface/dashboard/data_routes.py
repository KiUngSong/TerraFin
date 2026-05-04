from typing import Literal

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
    # True iff TERRAFIN_SIGNALS_PROVIDER_URL is set — frontend hides the
    # per-row monitor toggle when no provider is configured.
    monitorEnabled: bool = False


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


class WatchlistCreateGroupRequest(BaseModel):
    name: str


class WatchlistReorderGroupsRequest(BaseModel):
    groups: list[str]


class WatchlistReorderItemsRequest(BaseModel):
    symbols: list[str]


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


class SpxGexHistoryPointResponse(BaseModel):
    date: str
    gex_b: float
    dix: float | None = None
    price: float | None = None


class SpxGexHistoryResponse(BaseModel):
    points: list[SpxGexHistoryPointResponse]
    source: str


def create_dashboard_data_router() -> APIRouter:
    router = APIRouter()
    data_factory = get_data_factory()
    watchlist_service = get_watchlist_service()
    cache_manager = get_cache_manager()

    def _watchlist_response(items: list[dict]) -> WatchlistSnapshotResponse:
        from TerraFin.interface.monitor.http_provider import is_signal_provider_configured

        backend_configured = watchlist_service.is_backend_configured()
        return WatchlistSnapshotResponse(
            items=[WatchlistItemResponse.model_validate(item) for item in items],
            backendConfigured=backend_configured,
            mode="mongo" if backend_configured else "fallback",
            monitorEnabled=is_signal_provider_configured(),
        )

    def _is_monitored(item: dict | None) -> bool:
        if not item:
            return False
        return any(str(t).strip().lower() == "monitor" for t in (item.get("tags") or []))

    def _find_item(items: list[dict], symbol: str) -> dict | None:
        target = (symbol or "").strip().upper()
        for entry in items:
            if str(entry.get("symbol") or "").upper() == target:
                return entry
        return None

    async def _push_monitor_change(symbol: str, is_now_monitored: bool) -> None:
        """Push immediate register/unregister to the signal provider, then send
        a Telegram confirmation (or failure notice) so the user always learns
        the round-trip result and silent fails are surfaced.

        Pre-checks ``/health`` first so we can fail loud with an actionable
        "monitor daemon is down — start it" message instead of swallowing a
        connection-refused as a vague heartbeat-retry warning.
        """
        from TerraFin.interface.monitor.http_provider import get_signal_provider_from_env

        provider = get_signal_provider_from_env()
        if provider is None:
            return

        action = "registered to monitor list" if is_now_monitored else "removed from monitor list"
        if (await provider.health()) is None:
            await _notify_monitor_change(
                symbol,
                ok=False,
                action=action,
                error=(
                    "Monitor daemon unreachable on the configured URL. "
                    "Start it with DataFactory's `scripts/start_monitor.sh` "
                    "(or check that the host/port and bearer key match)."
                ),
            )
            return
        try:
            if is_now_monitored:
                await provider.register([symbol])
            else:
                await provider.unregister([symbol])
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Immediate monitor push failed for %s (heartbeat will retry)",
                symbol,
                exc_info=True,
            )
            await _notify_monitor_change(symbol, ok=False, action=action, error=str(exc))
            return
        await _notify_monitor_change(symbol, ok=True, action=action, error=None)

    async def _notify_monitor_change(symbol: str, *, ok: bool, action: str, error: str | None) -> None:
        """Best-effort Telegram confirmation for the monitor toggle round-trip."""
        import asyncio
        import logging

        try:
            from TerraFin.interface.channels.telegram import TelegramChannel

            ch = TelegramChannel.from_config()
        except Exception:
            return  # Telegram not configured — silently skip
        if ok:
            emoji = "✅"
            msg = f"{emoji} <b>{symbol}</b> {action}"
        else:
            emoji = "⚠️"
            msg = (
                f"{emoji} <b>{symbol}</b> {action} — <b>FAILED</b>\n"
                f"<i>{error or 'unknown error'}</i>\n"
                f"Heartbeat will retry within 60s."
            )
        try:
            await asyncio.get_running_loop().run_in_executor(None, ch.send_text, msg)
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to send monitor-toggle Telegram notice for %s", symbol, exc_info=True
            )

    @router.get(f"{DASHBOARD_API_PREFIX}/watchlist", response_model=WatchlistSnapshotResponse)
    def api_get_watchlist_snapshot(group: str | None = Query(default=None)):
        return _watchlist_response(watchlist_service.get_watchlist_snapshot(group=group))

    @router.get(f"{DASHBOARD_API_PREFIX}/watchlist/groups", response_model=WatchlistGroupsResponse)
    def api_get_watchlist_groups():
        return WatchlistGroupsResponse(groups=[WatchlistGroupResponse(**g) for g in watchlist_service.list_groups()])

    @router.post(f"{DASHBOARD_API_PREFIX}/watchlist/groups", response_model=WatchlistGroupsResponse)
    def api_create_watchlist_group(body: WatchlistCreateGroupRequest = Body(...)):
        try:
            watchlist_service.create_group(body.name)
            return WatchlistGroupsResponse(groups=[WatchlistGroupResponse(**g) for g in watchlist_service.list_groups()])
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.delete(f"{DASHBOARD_API_PREFIX}/watchlist/groups/{{name}}", response_model=WatchlistSnapshotResponse)
    def api_delete_watchlist_group(name: str):
        try:
            return _watchlist_response(watchlist_service.delete_group(name))
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.put(f"{DASHBOARD_API_PREFIX}/watchlist/groups/order", response_model=WatchlistGroupsResponse)
    def api_reorder_watchlist_groups(body: WatchlistReorderGroupsRequest = Body(...)):
        try:
            watchlist_service.reorder_groups(body.groups)
            return WatchlistGroupsResponse(groups=[WatchlistGroupResponse(**g) for g in watchlist_service.list_groups()])
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.put(f"{DASHBOARD_API_PREFIX}/watchlist/groups/{{group}}/item-order", response_model=WatchlistSnapshotResponse)
    def api_reorder_watchlist_items(group: str, body: WatchlistReorderItemsRequest = Body(...)):
        try:
            return _watchlist_response(watchlist_service.reorder_items(group, body.symbols))
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(f"{DASHBOARD_API_PREFIX}/watchlist/groups/rename", response_model=WatchlistSnapshotResponse)
    def api_rename_watchlist_group(body: WatchlistRenameGroupRequest = Body(...)):
        try:
            return _watchlist_response(watchlist_service.rename_group(body.old, body.new))
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.patch(f"{DASHBOARD_API_PREFIX}/watchlist/{{symbol}}/tags", response_model=WatchlistSnapshotResponse)
    async def api_patch_watchlist_tags(symbol: str, body: WatchlistTagsRequest = Body(...)):
        try:
            pre = _is_monitored(_find_item(watchlist_service.get_watchlist_snapshot(), symbol))
            if body.mode == "set":
                items = watchlist_service.set_tags(symbol, body.tags)
            elif body.mode == "add":
                items = watchlist_service.add_tags(symbol, body.tags)
            else:
                items = watchlist_service.remove_tags(symbol, body.tags)
            post = _is_monitored(_find_item(items, symbol))
            # Don't wait the next heartbeat (60s) — push monitor flag changes
            # to the provider immediately. Provider failure is non-fatal: the
            # toggle is already persisted and the heartbeat will reconcile.
            if pre != post:
                await _push_monitor_change(symbol, post)
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
        except WatchlistConflictError:
            # Ticker already exists — add it to the requested group instead of rejecting.
            if body.tags:
                try:
                    return _watchlist_response(watchlist_service.add_tags(body.symbol, body.tags))
                except WatchlistConfigurationError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                except WatchlistValidationError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise HTTPException(status_code=409, detail=f"{body.symbol.strip().upper()} is already in the watchlist.")
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put(f"{DASHBOARD_API_PREFIX}/watchlist", response_model=WatchlistSnapshotResponse)
    def api_replace_watchlist(body: WatchlistReplaceRequest = Body(...)):
        try:
            normalized = [s if isinstance(s, str) else s.model_dump() for s in body.symbols]
            return _watchlist_response(watchlist_service.replace_symbols(normalized))
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete(f"{DASHBOARD_API_PREFIX}/watchlist/{{symbol}}", response_model=WatchlistSnapshotResponse)
    async def api_remove_watchlist_symbol(symbol: str, group: str | None = Query(default=None)):
        try:
            if group:
                # Group-scoped: remove only that tag; item is preserved in other groups.
                items = watchlist_service.remove_tags(symbol, [group])
                return _watchlist_response(items)
            was_monitored = _is_monitored(_find_item(watchlist_service.get_watchlist_snapshot(), symbol))
            items = watchlist_service.remove_symbol(symbol)
            if was_monitored:
                await _push_monitor_change(symbol, is_now_monitored=False)
            return _watchlist_response(items)
        except WatchlistNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WatchlistConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except WatchlistValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(f"{DASHBOARD_API_PREFIX}/reports/weekly")
    def api_list_weekly_reports():
        from TerraFin.analytics.reports import list_reports

        reports = list_reports(limit=12)
        return {"reports": [r.summary() for r in reports]}

    @router.get(f"{DASHBOARD_API_PREFIX}/reports/weekly/{{as_of}}")
    def api_get_weekly_report(as_of: str):
        from TerraFin.analytics.reports import load_report

        rec = load_report(as_of)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"No report for {as_of}")
        return {**rec.summary(), "markdown": rec.markdown}

    @router.post(f"{DASHBOARD_API_PREFIX}/reports/weekly/run")
    def api_run_weekly_report():
        from TerraFin.analytics.reports import list_reports
        from TerraFin.analytics.reports.weekly import build_weekly_report

        build_weekly_report()
        latest = list_reports(limit=1)
        return {"reports": [r.summary() for r in latest]}

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

    @router.get(f"{DASHBOARD_API_PREFIX}/spx-gex-history", response_model=SpxGexHistoryResponse)
    def api_get_spx_gex_history(force: bool = Query(default=False)):
        from TerraFin.analytics.data.spx_gex_history import get_spx_gex_history

        points = get_spx_gex_history(force_refresh=force)
        return SpxGexHistoryResponse(
            points=[SpxGexHistoryPointResponse(**p) for p in points],
            source="squeezemetrics",
        )

    return router
