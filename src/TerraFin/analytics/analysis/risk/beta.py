import math

import pandas as pd

from TerraFin.data.factory import DataFactory

from .benchmarks import select_default_benchmark
from .models import BetaEstimate
from .returns import build_monthly_return_window


BETA_5Y_MONTHLY_METHOD_ID = "beta_5y_monthly"
BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID = "beta_5y_monthly_adjusted"
LOOKBACK_YEARS = 5
FREQUENCY = "monthly"


def compute_regression_beta(returns: pd.DataFrame) -> tuple[float | None, float | None]:
    if returns.empty or "stock" not in returns.columns or "benchmark" not in returns.columns:
        return None, None

    variance = returns["benchmark"].var(ddof=1)
    if not math.isfinite(variance) or variance <= 0:
        return None, None

    covariance = returns["stock"].cov(returns["benchmark"])
    if covariance is None or not math.isfinite(covariance):
        return None, None

    beta = float(covariance / variance)
    correlation = returns["stock"].corr(returns["benchmark"])
    r_squared = None if correlation is None or not math.isfinite(correlation) else float(correlation * correlation)
    return beta, r_squared


def compute_adjusted_beta(raw_beta: float) -> float:
    return float(0.67 * raw_beta + 0.33 * 1.0)


def estimate_beta_5y_monthly(symbol: str, *, data_factory: DataFactory | None = None) -> BetaEstimate:
    return _estimate(symbol, adjusted=False, data_factory=data_factory)


def estimate_beta_5y_monthly_adjusted(symbol: str, *, data_factory: DataFactory | None = None) -> BetaEstimate:
    return _estimate(symbol, adjusted=True, data_factory=data_factory)


def _estimate(symbol: str, *, adjusted: bool, data_factory: DataFactory | None) -> BetaEstimate:
    method_id = BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID if adjusted else BETA_5Y_MONTHLY_METHOD_ID
    benchmark = select_default_benchmark(symbol)
    if benchmark.status != "ready":
        return BetaEstimate(
            symbol=benchmark.input_symbol,
            benchmark_symbol=benchmark.benchmark_symbol,
            benchmark_label=benchmark.benchmark_label,
            method_id=method_id,
            lookback_years=LOOKBACK_YEARS,
            frequency=FREQUENCY,
            beta=None,
            observations=0,
            r_squared=None,
            status="unsupported_benchmark",
            warnings=list(benchmark.warnings),
        )

    window = build_monthly_return_window(
        benchmark.input_symbol,
        benchmark.benchmark_symbol or "",
        data_factory=data_factory,
        lookback_years=LOOKBACK_YEARS,
    )
    if window.observations == 0:
        return BetaEstimate(
            symbol=window.symbol,
            benchmark_symbol=benchmark.benchmark_symbol,
            benchmark_label=benchmark.benchmark_label,
            method_id=method_id,
            lookback_years=LOOKBACK_YEARS,
            frequency=FREQUENCY,
            beta=None,
            observations=window.observations,
            r_squared=None,
            status="insufficient_data",
            warnings=list(window.warnings),
        )

    raw_beta, r_squared = compute_regression_beta(window.returns)
    if raw_beta is None:
        warnings = list(window.warnings)
        warnings.append("Benchmark variance was unavailable, so beta could not be computed.")
        return BetaEstimate(
            symbol=window.symbol,
            benchmark_symbol=benchmark.benchmark_symbol,
            benchmark_label=benchmark.benchmark_label,
            method_id=method_id,
            lookback_years=LOOKBACK_YEARS,
            frequency=FREQUENCY,
            beta=None,
            observations=window.observations,
            r_squared=None,
            status="insufficient_data",
            warnings=warnings,
        )

    if window.observations < 24:
        return BetaEstimate(
            symbol=window.symbol,
            benchmark_symbol=benchmark.benchmark_symbol,
            benchmark_label=benchmark.benchmark_label,
            method_id=method_id,
            lookback_years=LOOKBACK_YEARS,
            frequency=FREQUENCY,
            beta=None,
            observations=window.observations,
            r_squared=r_squared,
            status="insufficient_data",
            warnings=list(window.warnings),
        )

    beta = compute_adjusted_beta(raw_beta) if adjusted else raw_beta
    return BetaEstimate(
        symbol=window.symbol,
        benchmark_symbol=benchmark.benchmark_symbol,
        benchmark_label=benchmark.benchmark_label,
        method_id=method_id,
        lookback_years=LOOKBACK_YEARS,
        frequency=FREQUENCY,
        beta=float(beta),
        observations=window.observations,
        r_squared=r_squared,
        status="ready",
        warnings=list(window.warnings),
    )
