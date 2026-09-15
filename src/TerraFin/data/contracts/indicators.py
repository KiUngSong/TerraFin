"""Indicator contracts: a scalar snapshot, and a catalog entry."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndicatorSnapshot:
    name: str
    value: float | int | str
    as_of: str
    unit: str | None = None
    change: float | None = None
    change_pct: float | None = None
    rating: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def make_empty(cls) -> "IndicatorSnapshot":
        return cls(name="", value=0, as_of="")


@dataclass(frozen=True)
class IndicatorCatalogEntry:
    """One row of the searchable indicator catalog.

    ``symbol`` is the name every other call takes — pass it to
    ``DataFactory.get_recent_history`` or ``get_market_data``. ``group`` says
    which registry it came from, which is also what decides where its data
    comes from: Index and Market are market series, Economic is FRED-backed.
    """

    symbol: str
    name: str
    group: str
