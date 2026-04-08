from TerraFin.data.providers.private_access.fallbacks._loader import load_fallback_section
from TerraFin.data.providers.private_access.models import MarketBreadthResponse


def get_market_breadth_fallback() -> MarketBreadthResponse:
    return MarketBreadthResponse.model_validate(load_fallback_section("market_breadth"))
