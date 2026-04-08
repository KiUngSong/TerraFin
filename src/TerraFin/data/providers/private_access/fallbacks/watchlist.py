from TerraFin.data.providers.private_access.fallbacks._loader import load_fallback_section
from TerraFin.data.providers.private_access.models import WatchlistSnapshotResponse


def get_watchlist_fallback() -> WatchlistSnapshotResponse:
    return WatchlistSnapshotResponse.model_validate(load_fallback_section("watchlist"))
