from dataclasses import dataclass, field
from typing import Literal

import pandas as pd


BenchmarkStatus = Literal["ready", "unsupported_benchmark"]
BetaStatus = Literal["ready", "insufficient_data", "unsupported_benchmark"]


@dataclass(frozen=True)
class BenchmarkSelection:
    input_symbol: str
    benchmark_symbol: str | None
    benchmark_label: str | None
    status: BenchmarkStatus
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReturnWindow:
    symbol: str
    benchmark_symbol: str
    returns: pd.DataFrame = field(repr=False)
    observations: int
    start_date: str | None
    end_date: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BetaEstimate:
    symbol: str
    benchmark_symbol: str | None
    benchmark_label: str | None
    method_id: str
    lookback_years: int
    frequency: str
    beta: float | None
    observations: int
    r_squared: float | None
    status: BetaStatus
    warnings: list[str] = field(default_factory=list)
