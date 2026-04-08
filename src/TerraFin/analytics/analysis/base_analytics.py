from TerraFin.data import TimeSeriesDataFrame


def get_returns(df: TimeSeriesDataFrame):
    """
    Calculate daily returns from a time series DataFrame.

    Args:
        df: DataFrame with time series data

    Returns:
        DataFrame with daily returns
    """

    return df.close.astype(float).pct_change().dropna()
