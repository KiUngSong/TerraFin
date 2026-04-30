"""Single-value scalar indicator snapshot contract."""

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
