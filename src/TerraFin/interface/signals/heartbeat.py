"""Periodic re-registration of watchlist tickers with the external alert provider."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def registration_heartbeat(provider, interval: int = 60) -> None:
    """Re-register current watchlist tickers every `interval` seconds."""
    from TerraFin.interface.watchlist_service import get_watchlist_service

    while True:
        await asyncio.sleep(interval)
        try:
            items = get_watchlist_service().get_watchlist_snapshot()
            tickers = [item["symbol"] for item in items]
            if tickers:
                await provider.register(tickers)
                log.debug("Re-registered %d tickers with alert provider", len(tickers))
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Failed to re-register tickers (will retry in %ds)", interval)
