import logging

import pandas as pd
import yfinance as yf

from TerraFin.analytics.analysis.patterns import Signal, evaluate
from TerraFin.interface.watchlist_service import get_watchlist_service

log = logging.getLogger(__name__)


def _fetch_ohlc(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
    df.columns = [c.lower() for c in df.columns]
    if df.empty:
        raise ValueError(f"no data returned for {ticker}")
    return df


def scan(group: str | None = None) -> list[Signal]:
    svc = get_watchlist_service()
    items = svc.get_watchlist_snapshot(group=group)
    results: list[Signal] = []
    for item in items:
        ticker = item["symbol"]
        try:
            ohlc = _fetch_ohlc(ticker)
            results.extend(evaluate(ticker, ohlc))
        except Exception:
            log.warning("scan: skipping %s — fetch/evaluate failed", ticker, exc_info=True)
            continue
    return results
