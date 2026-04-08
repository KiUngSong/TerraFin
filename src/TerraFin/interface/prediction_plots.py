"""Time series visualization utilities for financial data."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from TerraFin.data import TimeSeriesDataFrame


def timeseries_with_predictions(
    df: TimeSeriesDataFrame,
    simulation_results: np.ndarray,
    percentiles: tuple = (20, 80),
) -> go.Figure:
    last_day = df.time.max()
    date_index = df.time
    num_days = simulation_results.shape[0]
    try:
        new_index = pd.date_range(start=last_day, periods=num_days + 1, freq="B")[1:]
    except Exception:
        new_index = range(len(df), len(df) + num_days)

    simulation_df = pd.DataFrame(simulation_results, index=new_index)
    pct_low = simulation_df.apply(lambda x: np.percentile(x, percentiles[0]), axis=1)
    pct_high = simulation_df.apply(lambda x: np.percentile(x, percentiles[1]), axis=1)
    pct_median = simulation_df.apply(lambda x: np.percentile(x, 50), axis=1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=date_index, y=df.close, mode="lines", showlegend=False, hoverinfo="skip"))

    max_paths_to_show = min(20, simulation_df.shape[1])
    sample_cols = np.random.choice(simulation_df.columns, size=max_paths_to_show, replace=False)
    for col in sample_cols:
        fig.add_trace(
            go.Scatter(
                x=simulation_df.index,
                y=simulation_df[col],
                mode="lines",
                line={"width": 0.5, "color": "lightgray"},
                showlegend=False,
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=simulation_df.index,
            y=pct_median,
            mode="lines",
            name="Median Prediction",
            line={"width": 2, "color": "orange"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=simulation_df.index,
            y=pct_low,
            mode="lines",
            name=f"{percentiles[0]}th Percentile",
            line={"width": 2, "color": "red"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=simulation_df.index,
            y=pct_high,
            mode="lines",
            name=f"{percentiles[1]}th Percentile",
            line={"width": 2, "color": "red"},
            fill="tonexty",
            fillcolor="rgba(255,0,0,0.1)",
        )
    )
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        margin={"t": 50, "b": 25},
        legend={"x": 0.02, "y": 0.98},
    )
    return fig
