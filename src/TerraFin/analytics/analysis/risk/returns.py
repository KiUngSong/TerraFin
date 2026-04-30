import pandas as pd

from TerraFin.data.factory import DataFactory

from .benchmarks import normalize_symbol
from .models import ReturnWindow


_PRICE_COLUMNS = ("adj_close", "Adj Close", "close", "Close")
_MIN_MONTHLY_OBSERVATIONS = 24


def extract_close_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)

    price_column = next((column for column in _PRICE_COLUMNS if column in frame.columns), None)
    if price_column is None:
        return pd.Series(dtype=float)

    if "time" in frame.columns:
        index = pd.to_datetime(frame["time"], errors="coerce")
    else:
        index = pd.to_datetime(frame.index, errors="coerce")

    series = pd.Series(pd.to_numeric(frame[price_column], errors="coerce").values, index=index)
    series = series.dropna()
    series = series[~series.index.isna()]
    series = series.sort_index()
    series = series[~series.index.duplicated(keep="last")]
    return series.astype(float)


def build_monthly_return_window(
    symbol: str,
    benchmark_symbol: str,
    *,
    data_factory: DataFactory | None = None,
    lookback_years: int = 5,
) -> ReturnWindow:
    factory = data_factory or get_data_factory()
    normalized_symbol = normalize_symbol(symbol)
    normalized_benchmark = normalize_symbol(benchmark_symbol)

    stock_series = extract_close_series(factory.get_market_data(normalized_symbol))
    benchmark_series = extract_close_series(factory.get_market_data(normalized_benchmark))

    warnings: list[str] = []
    if stock_series.empty:
        warnings.append(f"No market history available for {normalized_symbol}.")
    if benchmark_series.empty:
        warnings.append(f"No market history available for benchmark {normalized_benchmark}.")
    if warnings:
        return ReturnWindow(
            symbol=normalized_symbol,
            benchmark_symbol=normalized_benchmark,
            returns=pd.DataFrame(columns=["stock", "benchmark"]),
            observations=0,
            start_date=None,
            end_date=None,
            warnings=warnings,
        )

    end_at = min(stock_series.index.max(), benchmark_series.index.max())
    start_at = end_at - pd.DateOffset(years=lookback_years)
    stock_series = stock_series[(stock_series.index >= start_at) & (stock_series.index <= end_at)]
    benchmark_series = benchmark_series[(benchmark_series.index >= start_at) & (benchmark_series.index <= end_at)]

    monthly_prices = pd.concat(
        [
            stock_series.resample("ME").last().rename("stock"),
            benchmark_series.resample("ME").last().rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()

    monthly_returns = monthly_prices.pct_change().dropna()
    observations = len(monthly_returns)

    if observations < _MIN_MONTHLY_OBSERVATIONS:
        warnings.append(
            f"Only {observations} monthly observations were available after alignment; "
            f"at least {_MIN_MONTHLY_OBSERVATIONS} are required."
        )
    elif observations < lookback_years * 12 - 6:
        warnings.append(
            "Less than a full 5-year monthly history was available after alignment; "
            "the estimate may be less stable."
        )

    start_date = monthly_returns.index.min().date().isoformat() if observations else None
    end_date = monthly_returns.index.max().date().isoformat() if observations else None
    return ReturnWindow(
        symbol=normalized_symbol,
        benchmark_symbol=normalized_benchmark,
        returns=monthly_returns,
        observations=observations,
        start_date=start_date,
        end_date=end_date,
        warnings=warnings,
    )
