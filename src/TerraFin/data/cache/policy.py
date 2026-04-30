from dataclasses import dataclass

from TerraFin.configuration import load_terrafin_config


# Single source of truth for cache TTLs. Keyed by source-name namespace
# (per-instance suffixes like `.<TICKER>` are stripped via longest-prefix match
# in `ttl_for`). To audit a TTL, edit here.
CACHE_TTL_REGISTRY: dict[str, int] = {
    # Market — yfinance
    "yfinance.full": 86_400,
    "market.ticker_info": 86_400,
    "market.earnings": 86_400,
    # Economic — FRED
    "fred": 7 * 86_400,
    # Corporate fundamentals
    "fundamentals.yfinance": 86_400,
    # SEC EDGAR
    "sec.cik": 7 * 86_400,
    "sec.submissions": 86_400,
    "sec.submissions.history": 30 * 86_400,
    "sec.parsed": 86_400,
    # 13F guru holdings
    "portfolio": 7 * 86_400,
    # Private-source panels
    "private.market_breadth": 21_600,
    "private.trailing_forward_pe": 86_400,
    "private.cape": 7 * 86_400,
    "private.calendar": 7 * 86_400,
    "private.macro": 7 * 86_400,
    "private.fear_greed": 86_400,
    "private.top_companies": 7 * 86_400,
    # Private-source per-series
    "private.series.history": 86_400,
    "private.series.current": 3_600,
}


def ttl_for(source: str, default: int = 86_400) -> int:
    """Look up TTL by source name (longest-prefix match)."""
    if source in CACHE_TTL_REGISTRY:
        return CACHE_TTL_REGISTRY[source]
    parts = source.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in CACHE_TTL_REGISTRY:
            return CACHE_TTL_REGISTRY[candidate]
    return default


@dataclass(frozen=True)
class CachePolicy:
    source: str
    mode: str
    interval_seconds: int
    schedule: str = "interval"
    slots_per_day: int = 1
    enabled: bool = True


def get_default_cache_policies() -> list[CachePolicy]:
    cache_config = load_terrafin_config().cache
    return [
        CachePolicy(
            source="private.market_breadth",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("market_breadth"),
            schedule="boundary",
            slots_per_day=2,
        ),
        CachePolicy(
            source="private.trailing_forward_pe",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("trailing_forward_pe"),
            schedule="boundary",
            slots_per_day=2,
        ),
        CachePolicy(
            source="private.cape",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("cape"),
            schedule="boundary",
        ),
        CachePolicy(
            source="private.calendar",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("calendar"),
            schedule="boundary",
        ),
        CachePolicy(
            source="private.macro",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("macro"),
            schedule="boundary",
        ),
        CachePolicy(
            source="private.fear_greed",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("fear_greed"),
            schedule="boundary",
            slots_per_day=2,
        ),
        CachePolicy(
            source="private.top_companies",
            mode="refresh",
            interval_seconds=cache_config.interval_seconds_for("top_companies"),
            schedule="boundary",
        ),
        CachePolicy(
            source="fred.cache",
            mode="clear_only",
            interval_seconds=cache_config.interval_seconds_for("fred"),
        ),
        CachePolicy(
            source="portfolio.cache",
            mode="clear_only",
            interval_seconds=cache_config.interval_seconds_for("portfolio"),
        ),
        CachePolicy(
            source="ticker_info.cache",
            mode="clear_only",
            interval_seconds=cache_config.interval_seconds_for("ticker_info"),
        ),
        CachePolicy(
            source="sec_filings.cache",
            mode="clear_only",
            interval_seconds=cache_config.interval_seconds_for("sec_filings"),
        ),
    ]
