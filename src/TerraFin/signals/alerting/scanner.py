"""Scan all watchlist tickers for technical signals."""
from __future__ import annotations

import logging
from typing import Sequence

from TerraFin.signals.alerting.conditions import Signal, evaluate
from TerraFin.interface.watchlist_service import get_watchlist_service

log = logging.getLogger(__name__)


def scan(group: str | None = None) -> list[Signal]:
    """Evaluate all watchlist tickers and return triggered signals.

    Args:
        group: Optional tag/group to restrict scan to. Omit for full watchlist.
    """
    svc = get_watchlist_service()
    items = svc.get_watchlist_snapshot(group=group)
    if not items:
        log.info("Watchlist empty — nothing to scan.")
        return []

    all_signals: list[Signal] = []
    for item in items:
        ticker = item["symbol"]
        try:
            ohlc = _fetch_ohlc(ticker)
            signals = evaluate(ticker, ohlc)
            all_signals.extend(signals)
        except Exception:
            log.exception("Failed to evaluate signals for %s", ticker)

    return all_signals


def _fetch_ohlc(ticker: str):
    """Fetch OHLC data via the shared data pipeline (not bypassing it)."""
    from TerraFin.data import get_data_factory
    return get_data_factory().get_market_data(ticker)
