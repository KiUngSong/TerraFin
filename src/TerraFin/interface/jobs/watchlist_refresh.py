"""Watchlist move% refresh job.

Fires ``WatchlistService.refresh_all_moves()`` once at each region's
market-close + buffer boundary (KRX 16:30 KST +1h, NYSE 16:00 ET +1h).
On boot, catches up immediately if the stored move data predates the most
recently passed slot.

Disable with ``TERRAFIN_WATCHLIST_REFRESH_ENABLED=0``.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_REGIONS = [
    {"label": "KRX", "tz": "Asia/Seoul",       "close_hour": 15, "close_minute": 30, "buffer_minutes": 60},
    {"label": "NYSE", "tz": "America/New_York", "close_hour": 16, "close_minute":  0, "buffer_minutes": 60},
]


def _next_fire_at_utc(now_utc: datetime) -> tuple[datetime, str]:
    candidates: list[tuple[datetime, str]] = []
    for r in _REGIONS:
        tz = ZoneInfo(r["tz"])
        local = now_utc.astimezone(tz)
        target = local.replace(hour=r["close_hour"], minute=r["close_minute"], second=0, microsecond=0)
        target += timedelta(minutes=r["buffer_minutes"])
        if target <= local:
            target += timedelta(days=1)
        candidates.append((target.astimezone(timezone.utc), r["label"]))
    return min(candidates, key=lambda c: c[0])


def _previous_fire_at_utc(now_utc: datetime) -> datetime:
    passed: list[datetime] = []
    for r in _REGIONS:
        tz = ZoneInfo(r["tz"])
        local = now_utc.astimezone(tz)
        target = local.replace(hour=r["close_hour"], minute=r["close_minute"], second=0, microsecond=0)
        target += timedelta(minutes=r["buffer_minutes"])
        if target > local:
            target -= timedelta(days=1)
        passed.append(target.astimezone(timezone.utc))
    return max(passed)


async def run() -> None:
    if os.environ.get("TERRAFIN_WATCHLIST_REFRESH_ENABLED", "1") in ("0", "false", "False"):
        log.info("watchlist-refresh: disabled via env, exiting")
        return

    loop = asyncio.get_running_loop()

    from TerraFin.interface.watchlist_service import get_watchlist_service
    svc = get_watchlist_service()

    if not svc.is_backend_configured():
        log.info("watchlist-refresh: MongoDB not configured, exiting")
        return

    # Boot catch-up: fire immediately if stored data predates the last boundary.
    try:
        latest = svc.latest_refresh_at_utc()
        now = datetime.now(timezone.utc)
        prev_slot = _previous_fire_at_utc(now)
        if latest is None or latest < prev_slot:
            log.info("watchlist-refresh: boot catch-up (latest=%s, slot=%s)", latest, prev_slot)
            await loop.run_in_executor(None, svc.refresh_all_moves)
    except Exception:
        log.exception("watchlist-refresh: boot catch-up failed")

    # Steady-state: sleep until next boundary, fire, repeat.
    while True:
        try:
            now = datetime.now(timezone.utc)
            fire_at, label = _next_fire_at_utc(now)
            wait = max((fire_at - now).total_seconds(), 1.0)
            log.info("watchlist-refresh: next fire %s (%s, in %.0fs)", fire_at.isoformat(), label, wait)
            await asyncio.sleep(wait)
            svc = get_watchlist_service()
            await loop.run_in_executor(None, svc.refresh_all_moves)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("watchlist-refresh: iteration failed, retrying in 60s")
            await asyncio.sleep(60)
