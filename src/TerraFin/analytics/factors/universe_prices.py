"""Fresh close-price loading for cross-sectional factor computations.

`analytics.similarity.pool` owns universe membership, but its price cache is
frozen at last year's Dec 31 — deliberately, because shape matching does not
need today's bar. A live factor signal does, so this module fetches recent
history per symbol through the data layer's cached yfinance path instead.

Kept separate from `relative_strength` so that module stays pure computation and
remains usable with caller-supplied prices (live or historical).
"""

import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor


log = logging.getLogger(__name__)

# Matches the watchlist scanner: enough parallelism to be useful without
# hammering upstream.
_FETCH_WORKERS = 8

# Closes are only needed to rank a universe; the underlying yfinance artifact
# has a 24h TTL, so a short in-process memo just avoids re-reading and
# re-parsing hundreds of artifacts within one session. Deliberately short:
# `CacheManager` cannot see or invalidate this tier (see `clear_memo`).
_MEMO_TTL_SECONDS = 300

# One sp500-sized entry is roughly 500 symbols x ~500 closes, so cap the number
# of distinct symbol-set keys kept: without a bound, every leaderboard and
# single-ticker variation would add another retained copy.
_MEMO_MAX_ENTRIES = 4

_memo: dict[tuple[str, ...], tuple[float, dict[str, list[float]]]] = {}
_memo_lock = threading.Lock()


def universe_symbols(universe: str) -> list[str]:
    """Resolve a universe name to its symbol list.

    Accepts the same names as `SimilarityPool`: ``"sp500"``, ``"nasdaq100"``,
    ``"kospi200"``, any ``+``-joined combination, or ``"watchlist"``.
    """
    from TerraFin.analytics.similarity.pool import SimilarityPool

    if universe == "watchlist":
        from TerraFin.data.watchlist_service import get_watchlist_service

        return list(SimilarityPool.from_watchlist(get_watchlist_service()).symbols)
    return list(SimilarityPool.from_universe(universe).symbols)


def _fetch_closes_one(ticker: str) -> tuple[str, list[float], bool]:
    """Return (ticker, closes, is_stale).

    `read_recent` slices relative to the artifact's last bar rather than today,
    so a halted or delisted name can return a full-looking series that ends
    months ago. The staleness flag lets callers avoid ranking a stale series
    against live ones without noticing.
    """
    from TerraFin.data.providers.market.yfinance import get_yf_recent_history

    chunk = get_yf_recent_history(ticker, period="2y")
    frame = chunk.frame
    if frame.empty or "close" not in frame:
        raise ValueError(f"no close series for {ticker}")
    closes = [float(v) for v in frame["close"].dropna().tolist()]
    is_stale = "stale" in (getattr(chunk, "source_version", "") or "")
    return ticker, closes, is_stale


def fetch_closes(symbols: Sequence[str], *, use_memo: bool = True) -> dict[str, list[float]]:
    """Closes only. See `fetch_closes_detailed` when staleness matters."""
    closes, _ = fetch_closes_detailed(symbols, use_memo=use_memo)
    return closes


def fetch_closes_detailed(
    symbols: Sequence[str], *, use_memo: bool = True
) -> tuple[dict[str, list[float]], list[str]]:
    """Fetch recent daily closes (oldest→newest), plus the stale-served symbols.

    Symbols whose history cannot be fetched are omitted rather than raising, so
    one delisted or renamed member does not void a whole universe ranking.
    Two years is requested because the IBD relative-strength blend needs more
    than 252 trading days.
    """
    wanted = [s.strip().upper() for s in symbols if s and s.strip()]
    if not wanted:
        return {}, []

    key = tuple(sorted(set(wanted)))
    if use_memo:
        with _memo_lock:
            cached = _memo.get(key)
            if cached is not None and (time.monotonic() - cached[0]) < _MEMO_TTL_SECONDS:
                # Staleness was reported when the entry was first fetched.
                return dict(cached[1]), []

    closes: dict[str, list[float]] = {}
    stale: list[str] = []
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        for result in pool.map(_safe_fetch, key):
            if result is not None:
                ticker, series, is_stale = result
                closes[ticker] = series
                if is_stale:
                    stale.append(ticker)
    if stale:
        log.warning(
            "universe_prices: %d symbol(s) served from a stale artifact: %s",
            len(stale),
            ", ".join(stale[:10]),
        )

    if use_memo:
        with _memo_lock:
            _memo[key] = (time.monotonic(), dict(closes))
            while len(_memo) > _MEMO_MAX_ENTRIES:
                _memo.pop(next(iter(_memo)))
    return closes, stale


def clear_memo() -> None:
    """Drop memoised closes.

    The memo is process-local and invisible to `CacheManager`, so clearing the
    shared cache does not reach it. Call this alongside a cache clear when a
    caller must see freshly fetched prices.
    """
    with _memo_lock:
        _memo.clear()


def _safe_fetch(ticker: str) -> tuple[str, list[float], bool] | None:
    try:
        return _fetch_closes_one(ticker)
    except Exception:
        log.warning("universe_prices: skipping %s — fetch failed", ticker, exc_info=True)
        return None
