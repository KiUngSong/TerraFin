import TerraFin.interface.watchlist as watchlist_module


def test_watchlist_public_api_exports_router_factory() -> None:
    assert watchlist_module.WATCHLIST_PATH == "/watchlist"
    assert callable(watchlist_module.create_watchlist_router)
