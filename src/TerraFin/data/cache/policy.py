from dataclasses import dataclass

from TerraFin.configuration import load_terrafin_config


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
            source="yfinance.cache",
            mode="clear_only",
            interval_seconds=cache_config.interval_seconds_for("yfinance"),
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
