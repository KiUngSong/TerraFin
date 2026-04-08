from dataclasses import dataclass

from .dataframes import TimeSeriesDataFrame


@dataclass
class HistoryChunk:
    frame: TimeSeriesDataFrame
    loaded_start: str | None
    loaded_end: str | None
    requested_period: str | None
    is_complete: bool
    has_older: bool
    source_version: str | None = None
