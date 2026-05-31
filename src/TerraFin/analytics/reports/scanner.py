import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from TerraFin.analytics.analysis.patterns import Signal, evaluate
from TerraFin.data.watchlist_service import get_watchlist_service


log = logging.getLogger(__name__)

_SCAN_WORKERS = 8


def _fetch_ohlc(ticker: str) -> pd.DataFrame:
    from TerraFin.data.providers.market.yfinance import get_yf_recent_history

    chunk = get_yf_recent_history(ticker, period="1y")
    if chunk.frame.empty:
        raise ValueError(f"no data returned for {ticker}")
    return chunk.frame.copy()


def _scan_one(item: dict) -> list[Signal]:
    ticker = item["symbol"]
    try:
        ohlc = _fetch_ohlc(ticker)
        return evaluate(ticker, ohlc)
    except Exception:
        log.warning("scan: skipping %s — fetch/evaluate failed", ticker, exc_info=True)
        return []


def scan(group: str | None = None) -> list[Signal]:
    svc = get_watchlist_service()
    items = svc.get_watchlist_snapshot(group=group)
    if not items:
        return []
    results: list[Signal] = []
    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
        for signals in pool.map(_scan_one, items):
            results.extend(signals)
    return results
