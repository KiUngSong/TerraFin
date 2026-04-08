import math

import numpy as np


def run_base_gbm(time_series_df, num_simulation=100, pred_ratio=0.2):
    """
    Args:
        time_series_df: pd.DataFrame, time series data.
            It conforms to `TimeSeriesDataFrame` from `TerraFin.data.contracts.dataframes`.
            For example, it can be the stock price data.
        num_simulation: int, number of simulations.
        pred_ratio: float, ratio of days to predict.

    Returns:
        simulations: np.ndarray, simulations of time series such as stock price.
    """

    # Set up simulation parameters
    s0 = time_series_df["close"].iloc[-1]  # Starting stock price: last available close price.
    max_pred_days = min(math.ceil(len(time_series_df) * pred_ratio), 30)  # Number of days to predict, max 30 days.
    total_steps = len(time_series_df)
    dt = 1 / total_steps  # Time step (e.g. 1 trading day, 1 hour, 1 minute, etc.)

    # Compute returns
    returns = time_series_df["close"].pct_change(fill_method=None).dropna()
    assert len(returns) == len(time_series_df) - 1

    """
    Underlying stochastic process: Geometric Brownian Motion (GBM)
        -  dS_t = mu * S_t * dt + sigma * S_t * dW_t
    With log-returns:
        - X_t = log(S_t)
    We get the following stochastic differential equation (SDE):
        -  dX_t = (mu - 0.5 * sigma^2) * dt + sigma * dW_t
        - This can be solved explicitly:
            - X_t = X_0 + (mu - 0.5 * sigma^2) * t + sigma * W_t
            - S_t = S_0 * exp((mu - 0.5 * sigma^2) * t + sigma * W_t)
    """

    # Estimate GBM parameters with returns: annualized return and volatility
    mu = np.mean(returns) * total_steps
    sigma = np.std(returns) * np.sqrt(total_steps)

    # Run simulation with parallel.
    simulations = np.zeros((max_pred_days, num_simulation))
    simulations[0] = s0
    for t in range(1, max_pred_days):
        z = np.random.standard_normal(num_simulation)
        simulations[t] = simulations[t - 1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)

    return simulations
