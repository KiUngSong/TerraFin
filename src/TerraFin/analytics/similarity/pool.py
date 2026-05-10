"""SimilarityPool — build and fetch a universe of price series for pattern matching.

Price cache: per-symbol parquet files keyed on ``{symbol}_eoy{year}`` where year is
             last calendar year (e.g. ``AAPL_eoy2025.parquet``).  Data ends on
             {year}-12-31, so the file is immutable — it is never re-downloaded.
             Download progress is printed to stdout on first fetch.
Pool cache:  process-level in-memory dict keyed on ``universe`` with a configurable
             TTL (default 6 h). Shared across concurrent ``similarity_search`` calls
             so ~713 symbols are only fetched once per server lifetime (modulo TTL
             expiry). Concurrent cold-start races are serialized per-universe via
             an in-flight Event so only one download runs at a time.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".terrafin" / "cache" / "prices"

# Process-level pool cache: universe → (pool, fetched_at)
_pool_cache: dict[str, tuple["SimilarityPool", datetime]] = {}
_pool_cache_lock = threading.Lock()
# Per-universe in-flight events: while a download is running, other threads wait.
_pool_in_flight: dict[str, threading.Event] = {}
_POOL_TTL_SECONDS: int = 6 * 3600  # 6 h


@dataclass
class SimilarityPool:
    symbols: list[str]
    universe_name: str = ""
    _meta: dict = field(default_factory=dict, repr=False)
    # Populated by fetch_prices(); None until first fetch.
    _prices: "dict[str, pd.Series] | None" = field(default=None, repr=False)
    _prices_period: str | None = field(default=None, repr=False)
    _prices_fetched_at: datetime | None = field(default=None, repr=False)

    @classmethod
    def from_watchlist(cls, service, groups: list[str] | None = None) -> "SimilarityPool":
        """Build pool from watchlist, optionally filtered to specific groups."""
        items = service.get_watchlist_snapshot()
        if groups:
            g_set = set(groups)
            items = [i for i in items if any(g in g_set for g in (i.get("tags") or []))]
        symbols = [i["symbol"] for i in items]
        meta = {
            i["symbol"]: {"name": i.get("name", ""), "tags": i.get("tags") or []}
            for i in items
        }
        return cls(symbols=symbols, universe_name="watchlist", _meta=meta)

    @classmethod
    def from_universe(cls, name: str) -> "SimilarityPool":
        """Build pool from a bundled universe CSV.

        Supported names: ``"sp500"``, ``"nasdaq100"``, ``"kospi200"``,
        ``"sp500+kospi200"``, ``"sp500+nasdaq100+kospi200"``, or any ``+``-joined
        combination of the above.
        """
        import csv
        from TerraFin.data.reference import UNIVERSES_DIR as universes_dir
        parts = [p.strip() for p in name.split("+")]
        symbols: list[str] = []
        meta: dict = {}
        for part in parts:
            csv_path = universes_dir / f"{part}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"Universe '{part}' not found at {csv_path}")
            with open(csv_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = row["symbol"]
                    if sym not in meta:
                        symbols.append(sym)
                        meta[sym] = {"name": row.get("name", ""), "tags": [part]}
        return cls(symbols=symbols, universe_name=name, _meta=meta)

    @classmethod
    def from_symbols(cls, symbols: list[str]) -> "SimilarityPool":
        return cls(symbols=list(symbols), universe_name="custom")

    def fetch_prices(self) -> "dict[str, pd.Series]":
        """Fetch full close-price history for all symbols and store on self.

        Returns the full EOY history per symbol (no period slice) so the
        scorer can slide the target template across the entire series.
        Prints download progress when a parquet is not yet cached.
        Skips symbols with fewer than 20 trading days.
        """
        year = date.today().year - 1
        total = len(self.symbols)
        result: dict[str, "pd.Series"] = {}
        failed: list[str] = []
        for i, sym in enumerate(self.symbols, 1):
            from_cache = (_CACHE_DIR / f"{sym}_eoy{year}.parquet").exists()
            if not from_cache:
                print(f"[pool] Downloading {sym} ({i}/{total})...", flush=True)
            s = _fetch_eoy(sym, year)
            if s is not None:
                s = s.ffill().dropna()
            if s is not None and len(s) >= 20:
                result[sym] = s
            else:
                failed.append(sym)
        if failed:
            log.debug("pool: skipped %d symbols (no data): %s", len(failed), failed)
        log.info("pool: loaded %d/%d symbols (eoy%d)", len(result), total, year)
        self._prices = result
        self._prices_period = None
        self._prices_fetched_at = datetime.utcnow()
        return result

    def prices(self) -> "dict[str, pd.Series]":
        """Return full cached price history, fetching if not yet loaded."""
        if self._prices is None:
            return self.fetch_prices()
        return self._prices

    def names(self) -> dict[str, str]:
        """Return {symbol: display_name} for pool members that have metadata."""
        return {sym: self._meta[sym]["name"] for sym in self.symbols if sym in self._meta}

    def info(self) -> dict:
        """Snapshot of pool state for inclusion in API responses."""
        return {
            "universe": self.universe_name,
            "symbolCount": len(self.symbols),
            "loadedCount": len(self._prices) if self._prices is not None else None,
            "period": self._prices_period,
            "fetchedAt": self._prices_fetched_at.isoformat() if self._prices_fetched_at else None,
        }


def get_pool(universe: str) -> SimilarityPool:
    """Return a pool with full price history loaded, using the process-level TTL cache.

    Watchlist pools are never cached (they change per-request).
    Concurrent cold-start requests for the same universe serialize via a per-universe
    Event so only one download runs; the rest wait and share the result.
    """
    if universe == "watchlist":
        from TerraFin.interface.watchlist_service import get_watchlist_service
        pool = SimilarityPool.from_watchlist(get_watchlist_service())
        pool.fetch_prices()
        return pool

    while True:
        with _pool_cache_lock:
            # Cache hit?
            if universe in _pool_cache:
                cached_pool, fetched_at = _pool_cache[universe]
                age = (datetime.utcnow() - fetched_at).total_seconds()
                if age < _POOL_TTL_SECONDS:
                    log.debug("pool cache hit: %s (age %.0fs)", universe, age)
                    return cached_pool

            # Another thread already building this universe?
            if universe in _pool_in_flight:
                event = _pool_in_flight[universe]
            else:
                # We are the builder — register our in-flight event.
                event = threading.Event()
                _pool_in_flight[universe] = event
                event = None  # sentinel: we own the build

        if event is not None:
            # Wait for the builder thread to finish, then re-check cache.
            event.wait()
            continue

        # We own the build — run outside the lock.
        try:
            pool = SimilarityPool.from_universe(universe)
            pool.fetch_prices()
            with _pool_cache_lock:
                _pool_cache[universe] = (pool, datetime.utcnow())
            return pool
        finally:
            with _pool_cache_lock:
                done_event = _pool_in_flight.pop(universe, None)
            if done_event is not None:
                done_event.set()


def _fetch_eoy(symbol: str, year: int) -> "pd.Series | None":
    """Fetch full close-price history through ``{year}-12-31``, cached permanently.

    The parquet file is considered immutable once written: year-end historical
    data never changes, so no TTL check is applied.
    """
    import pandas as pd

    cache_path = _CACHE_DIR / f"{symbol}_eoy{year}.parquet"
    if cache_path.exists():
        try:
            s = pd.read_parquet(cache_path)["close"]
            if s.index.tz is not None:
                s.index = pd.to_datetime(s.index.date)
            return s
        except Exception:
            pass

    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed — cannot fetch prices")
        return None

    end = date(year, 12, 31).isoformat()

    try:
        df = yf.Ticker(symbol).history(
            period="max",
            auto_adjust=True,
        )
        if not df.empty:
            df = df[df.index <= end]
    except Exception as exc:
        log.debug("yfinance fail for %s: %s", symbol, exc)
        return None

    if df.empty:
        return None

    series = df["Close"].rename(symbol)
    # Strip exchange timezone: keep wall-clock date, produce tz-naive index.
    series.index = pd.to_datetime(series.index.date)

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        series.to_frame("close").to_parquet(cache_path)
    except Exception as exc:
        log.debug("cache write fail for %s: %s", symbol, exc)

    return series
