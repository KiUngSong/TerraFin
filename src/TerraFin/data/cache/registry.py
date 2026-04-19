from TerraFin.data.cache.manager import CacheManager, CacheSourceSpec
from TerraFin.data.cache.policy import get_default_cache_policies


_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        from TerraFin.interface.config import load_runtime_config

        _cache_manager = CacheManager(timezone_name=load_runtime_config().cache_timezone)
        _register_default_sources(_cache_manager)
    return _cache_manager


def _register_default_sources(manager: CacheManager) -> None:
    from TerraFin.data.providers.corporate.filings.sec_edgar.filing import clear_sec_filings_cache
    from TerraFin.data.providers.corporate.filings.sec_edgar.holdings import clear_guru_holdings_cache
    from TerraFin.data.providers.economic.fred_data import clear_fred_cache
    from TerraFin.data.providers.market.ticker_info import clear_ticker_info_cache
    from TerraFin.data.providers.market.yfinance import clear_yfinance_cache

    clear_only_callbacks = {
        "fred.cache": clear_fred_cache,
        "yfinance.cache": clear_yfinance_cache,
        "portfolio.cache": clear_guru_holdings_cache,
        "ticker_info.cache": clear_ticker_info_cache,
        "sec_filings.cache": clear_sec_filings_cache,
    }

    for policy in get_default_cache_policies():
        clear_fn = clear_only_callbacks.get(policy.source)
        manager.register(
            CacheSourceSpec(
                source=policy.source,
                mode=policy.mode,
                interval_seconds=policy.interval_seconds,
                schedule=policy.schedule,
                slots_per_day=policy.slots_per_day,
                enabled=policy.enabled,
                clear_fn=clear_fn,
            )
        )


def clear_all_cache() -> None:
    get_cache_manager().clear_all()


def refresh_all_due(force: bool = False) -> None:
    get_cache_manager().refresh_due_sources(force=force)


def reset_cache_manager() -> None:
    global _cache_manager
    if _cache_manager is not None:
        _cache_manager.stop()
    _cache_manager = None
