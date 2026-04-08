from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


def date_filter(df: TimeSeriesDataFrame, date_start: str, date_end: str) -> TimeSeriesDataFrame:
    assert isinstance(df, TimeSeriesDataFrame), "Data must be a TimeSeriesDataFrame"

    date_start = pd.to_datetime(date_start)
    date_end = pd.to_datetime(date_end)

    # Use `time` column for slicing
    df = df.set_index("time")
    df = df.loc[date_start:date_end]
    df = df.reset_index()

    return df


def date_subtract(date: str, period_value: str = "1y") -> str:
    def month_subtract(x: int) -> str:
        return (datetime.strptime(date, "%Y-%m-%d") - relativedelta(months=x)).strftime("%Y-%m-%d")

    def year_subtract(x: int) -> str:
        return (datetime.strptime(date, "%Y-%m-%d") - relativedelta(years=x)).strftime("%Y-%m-%d")

    if period_value == "1m":
        return month_subtract(1)
    elif period_value == "3m":
        return month_subtract(3)
    elif period_value == "6m":
        return month_subtract(6)
    elif period_value == "1y":
        return year_subtract(1)
    elif period_value == "2y":
        return year_subtract(2)
    elif period_value == "5y":
        return year_subtract(5)
    elif period_value == "10y":
        return year_subtract(10)
    elif period_value == "max":
        return year_subtract(50)
    else:
        raise ValueError("Invalid period value. Please select a valid period value.")
