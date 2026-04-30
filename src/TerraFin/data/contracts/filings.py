"""SEC filing contracts."""

import re
from dataclasses import dataclass, field
from typing import Literal


FilingType = Literal["10-K", "10-Q", "8-K", "13F", "S-1", "DEF 14A"]
_FILING_TYPES = {"10-K", "10-Q", "8-K", "13F", "S-1", "DEF 14A"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class TOCEntry:
    id: str
    title: str
    level: int
    anchor: str

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError(f"TOCEntry.level must be >= 0, got {self.level}")


@dataclass
class FilingDocument:
    ticker: str
    filing_type: FilingType
    accession: str
    filing_date: str
    markdown: str
    toc: list[TOCEntry]
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.filing_type not in _FILING_TYPES:
            raise ValueError(
                f"FilingDocument.filing_type must be one of {sorted(_FILING_TYPES)}, got {self.filing_type!r}"
            )
        # Allow empty filing_date for make_empty(); else require YYYY-MM-DD.
        if self.filing_date != "" and not _DATE_RE.match(self.filing_date):
            raise ValueError(
                f"FilingDocument.filing_date must match YYYY-MM-DD, got {self.filing_date!r}"
            )
        # accession may only be empty for the make_empty() sentinel (filing_date also empty).
        if self.accession == "" and self.filing_date != "":
            raise ValueError("FilingDocument.accession must be non-empty")

    @classmethod
    def make_empty(cls, ticker: str, filing_type: FilingType) -> "FilingDocument":
        return cls(
            ticker=ticker,
            filing_type=filing_type,
            accession="",
            filing_date="",
            markdown="",
            toc=[],
        )
