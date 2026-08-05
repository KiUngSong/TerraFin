import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from TerraFin.analytics.analysis.patterns import Signal, evaluate
from TerraFin.data.watchlist_service import get_watchlist_service


log = logging.getLogger(__name__)

_SCAN_WORKERS = 8

# The alerting CLI has always scanned a 1-year window. Patterns that need more
# history (52W_NEW_HIGH/LOW need 303 bars, MINERVINI_TEMPLATE 263, the weekly MA
# crosses ~121 weeks) simply never fire at that width, so callers that want the
# full catalogue pass a wider period — `pattern_scan` uses 3y to match the
# single-ticker `patterns` capability.
_DEFAULT_PERIOD = "1y"


def _fetch_ohlc(ticker: str, period: str = _DEFAULT_PERIOD) -> pd.DataFrame:
    from TerraFin.data.providers.market.yfinance import get_yf_recent_history

    chunk = get_yf_recent_history(ticker, period=period)
    if chunk.frame.empty:
        raise ValueError(f"no data returned for {ticker}")
    return chunk.frame.copy()


def _scan_one(item: dict, period: str = _DEFAULT_PERIOD) -> tuple[str, list[Signal], bool]:
    """Return (ticker, signals, ok). `ok=False` means the symbol was not scanned."""
    ticker = item["symbol"]
    try:
        ohlc = _fetch_ohlc(ticker, period=period)
        return ticker, evaluate(ticker, ohlc), True
    except Exception:
        log.warning("scan: skipping %s — fetch/evaluate failed", ticker, exc_info=True)
        return ticker, [], False


def scan_detailed(
    group: str | None = None,
    tickers: Sequence[str] | None = None,
    *,
    period: str = _DEFAULT_PERIOD,
) -> tuple[list[Signal], list[str]]:
    """Evaluate every pattern across a symbol set, reporting what was skipped.

    Returns ``(signals, failed_symbols)``. A symbol lands in ``failed_symbols``
    when its history could not be fetched or evaluated, so callers can report
    real coverage instead of assuming every requested symbol was scanned.

    Defaults to the user's watchlist (optionally one ``group``). Pass ``tickers``
    to scan an arbitrary list instead.
    """
    if tickers is not None:
        items = [{"symbol": t.strip().upper()} for t in tickers if t and t.strip()]
    else:
        svc = get_watchlist_service()
        items = svc.get_watchlist_snapshot(group=group)
    if not items:
        return [], []

    results: list[Signal] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
        for ticker, signals, ok in pool.map(lambda item: _scan_one(item, period=period), items):
            if ok:
                results.extend(signals)
            else:
                failed.append(ticker)
    return results, failed


def scan(group: str | None = None, tickers: Sequence[str] | None = None) -> list[Signal]:
    """Signals only, for the alerting CLI. See `scan_detailed` for coverage."""
    signals, _ = scan_detailed(group=group, tickers=tickers)
    return signals
