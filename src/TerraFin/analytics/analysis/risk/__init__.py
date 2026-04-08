"""Risk analytics helpers for benchmark-relative measures such as beta."""

from .benchmarks import select_default_benchmark
from .beta import (
    BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID,
    BETA_5Y_MONTHLY_METHOD_ID,
    estimate_beta_5y_monthly,
    estimate_beta_5y_monthly_adjusted,
)


__all__ = [
    "BETA_5Y_MONTHLY_METHOD_ID",
    "BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID",
    "estimate_beta_5y_monthly",
    "estimate_beta_5y_monthly_adjusted",
    "select_default_benchmark",
]
