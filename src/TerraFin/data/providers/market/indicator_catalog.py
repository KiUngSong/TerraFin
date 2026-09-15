"""Searchable catalog of the indicators TerraFin can serve.

Answers the question that comes before every other data call: *what is this
series called here?* Without it a caller who knows it wants the 10-year
Treasury has no way to reach ``Treasury-10Y``, because every other entry point
takes a name it cannot discover — ``resolve`` matches exact names only and
answers an unknown string with a fabricated stock row rather than a miss.

Covers the three registries that live in the data layer. The chart's custom
declarative indicators are registered in the interface layer, so callers that
want those merge them in themselves; pulling them down here would make the
data layer import the interface.
"""

from ...contracts.indicators import IndicatorCatalogEntry


def list_indicators() -> list[IndicatorCatalogEntry]:
    """Every indicator this layer can serve, as catalog rows."""
    from ..economic import indicator_registry
    from . import INDEX_DESCRIPTIONS, INDEX_MAP, MARKET_INDICATOR_REGISTRY

    out: list[IndicatorCatalogEntry] = []
    for name in INDEX_MAP:
        out.append(IndicatorCatalogEntry(
            symbol=name, name=INDEX_DESCRIPTIONS.get(name, name), group="Index"))
    for name, ind in MARKET_INDICATOR_REGISTRY.items():
        out.append(IndicatorCatalogEntry(
            symbol=name, name=ind.description or name, group="Market"))
    for name, ind in indicator_registry._indicators.items():
        out.append(IndicatorCatalogEntry(
            symbol=name, name=ind.description or name, group="Economic"))
    return out


def search_indicators(query: str, limit: int = 10) -> list[IndicatorCatalogEntry]:
    """Case-insensitive substring match over symbol and name.

    ``search_indicators("trea")`` returns the Treasury tenors. An empty query
    returns nothing rather than the whole catalog — call :func:`list_indicators`
    for that.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    matches = [
        entry for entry in list_indicators()
        if needle in f"{entry.symbol} {entry.name}".lower()
    ]
    return matches[:limit]
