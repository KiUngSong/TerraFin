"""Periodic synchronization of monitor-flagged watchlist tickers with the
external alert provider.

Tickers are flagged for monitoring by carrying the ``"monitor"`` tag in
the watchlist (case-insensitive). The watchlist's monitored set is the
**single source of truth**: every heartbeat reconciles the provider's
actual subscribed set against it.

- Tickers in the watchlist monitor set but NOT subscribed → ``register``.
- Tickers subscribed on the provider but NOT in the watchlist monitor
  set → ``unregister`` (orphan eviction). Catches drift from out-of-band
  registers, provider restarts that lost in-memory state, etc.

Providers should treat both calls as idempotent.
"""
import asyncio
import logging

log = logging.getLogger(__name__)

_MONITOR_TAG = "monitor"


def _monitored_symbols(items: list[dict]) -> list[str]:
    out: list[str] = []
    for item in items:
        tags = [str(t).strip().lower() for t in item.get("tags") or []]
        if _MONITOR_TAG in tags:
            out.append(item["symbol"])
    return out


async def registration_heartbeat(provider, interval: int = 60) -> None:
    """Reconcile the provider's subscribed set against the watchlist."""
    from TerraFin.interface.watchlist_service import get_watchlist_service

    while True:
        try:
            items = get_watchlist_service().get_watchlist_snapshot()
            desired = set(_monitored_symbols(items))

            try:
                actual = set(await provider.list_subscribed())
            except AttributeError:
                # Provider doesn't expose introspection — fall back to
                # idempotent re-register only (no orphan eviction).
                actual = set()
            except Exception:
                log.exception("Failed to read provider's subscribed set; "
                              "will re-register desired only")
                actual = set()

            to_register = sorted(desired - actual)
            to_unregister = sorted(actual - desired)

            if to_unregister:
                await provider.unregister(to_unregister)
                log.info("Evicted %d orphan ticker(s) from alert provider: %s",
                         len(to_unregister), to_unregister)
            if to_register:
                await provider.register(to_register)
                log.info("Registered %d ticker(s) with alert provider: %s",
                         len(to_register), to_register)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Failed to sync monitor flags (will retry in %ds)", interval)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
