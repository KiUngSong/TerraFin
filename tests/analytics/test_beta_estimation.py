import math

import pandas as pd
import pytest

from TerraFin.analytics.analysis.risk import (
    BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID,
    BETA_5Y_MONTHLY_METHOD_ID,
    estimate_beta_5y_monthly,
    estimate_beta_5y_monthly_adjusted,
    select_default_benchmark,
)
from TerraFin.analytics.analysis.risk.beta import compute_adjusted_beta, compute_regression_beta


class FakeDataFactory:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_market_data(self, name: str) -> pd.DataFrame:
        return self._frames.get(name.upper(), pd.DataFrame(columns=["time", "close"]))


def _frame_from_monthly_returns(
    monthly_returns: list[float],
    *,
    start: str = "2019-01-31",
    initial_price: float = 100.0,
) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(monthly_returns) + 1, freq="ME")
    prices = [initial_price]
    for monthly_return in monthly_returns:
        prices.append(prices[-1] * (1.0 + monthly_return))
    return pd.DataFrame({"time": dates, "close": prices})


def _returns(length: int = 60) -> list[float]:
    base = [0.012, -0.018, 0.021, 0.007, -0.011, 0.016, 0.004, -0.006, 0.019, -0.009, 0.013, 0.005]
    repeats = math.ceil(length / len(base))
    return (base * repeats)[:length]


def test_select_default_benchmark_maps_supported_markets() -> None:
    assert select_default_benchmark("NVDA").benchmark_symbol == "^SPX"
    assert select_default_benchmark("005930.KS").benchmark_symbol == "^KS11"
    assert select_default_benchmark("035420.KQ").benchmark_symbol == "^KQ11"
    assert select_default_benchmark("7203.T").benchmark_symbol == "^N225"


def test_select_default_benchmark_marks_unsupported_markets() -> None:
    selection = select_default_benchmark("600519.SS")
    assert selection.status == "unsupported_benchmark"
    assert selection.benchmark_symbol is None
    assert selection.warnings


def test_compute_regression_beta_matches_expected_ratio() -> None:
    benchmark = pd.Series(_returns(), name="benchmark")
    stock = benchmark * 1.5
    beta, r_squared = compute_regression_beta(pd.concat([stock.rename("stock"), benchmark], axis=1))
    assert beta == pytest.approx(1.5)
    assert r_squared == pytest.approx(1.0)


def test_compute_adjusted_beta_shrinks_toward_one() -> None:
    assert compute_adjusted_beta(2.5) == pytest.approx(2.005)
    assert compute_adjusted_beta(0.4) == pytest.approx(0.598)


def test_estimate_beta_5y_monthly_uses_supported_benchmark_and_returns_ready() -> None:
    benchmark_returns = _returns()
    stock_returns = [value * 1.4 for value in benchmark_returns]
    factory = FakeDataFactory(
        {
            "NVDA": _frame_from_monthly_returns(stock_returns),
            "^SPX": _frame_from_monthly_returns(benchmark_returns),
        }
    )

    estimate = estimate_beta_5y_monthly("NVDA", data_factory=factory)

    assert estimate.method_id == BETA_5Y_MONTHLY_METHOD_ID
    assert estimate.status == "ready"
    assert estimate.benchmark_symbol == "^SPX"
    assert estimate.frequency == "monthly"
    assert estimate.observations == 60
    assert estimate.beta is not None
    assert estimate.beta == pytest.approx(1.4)
    assert estimate.r_squared == pytest.approx(1.0)


def test_estimate_beta_5y_monthly_adjusted_wraps_raw_beta() -> None:
    benchmark_returns = _returns()
    stock_returns = [value * 0.6 for value in benchmark_returns]
    factory = FakeDataFactory(
        {
            "005930.KS": _frame_from_monthly_returns(stock_returns),
            "^KS11": _frame_from_monthly_returns(benchmark_returns),
        }
    )

    estimate = estimate_beta_5y_monthly_adjusted("005930.KS", data_factory=factory)

    assert estimate.method_id == BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID
    assert estimate.status == "ready"
    assert estimate.beta is not None
    assert estimate.beta == pytest.approx(compute_adjusted_beta(0.6))


def test_estimate_beta_marks_insufficient_data_when_history_is_short() -> None:
    short_returns = _returns(12)
    factory = FakeDataFactory(
        {
            "KO": _frame_from_monthly_returns(short_returns),
            "^SPX": _frame_from_monthly_returns(short_returns),
        }
    )

    estimate = estimate_beta_5y_monthly("KO", data_factory=factory)

    assert estimate.status == "insufficient_data"
    assert estimate.beta is None
    assert estimate.observations == 12
    assert estimate.warnings


def test_estimate_beta_marks_unsupported_benchmark_without_fetching_data() -> None:
    estimate = estimate_beta_5y_monthly("600519.SS", data_factory=FakeDataFactory({}))

    assert estimate.status == "unsupported_benchmark"
    assert estimate.beta is None
    assert estimate.benchmark_symbol is None
    assert estimate.warnings
