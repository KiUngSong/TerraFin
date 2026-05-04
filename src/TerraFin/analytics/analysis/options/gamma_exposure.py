from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import requests


"""
Reference: https://github.com/Matteo-Ferrara/gex-tracker/blob/master/main.py
"""

contract_size = 100


@dataclass
class GEX_Output:
    spot_price: float
    gex_by_expiration: go.Figure
    gex_by_strike: go.Figure


def get_current_gex(ticker):
    spot_price, option_data = scrape_data(ticker)
    if option_data is None:
        return None

    compute_total_gex(spot_price, option_data)

    return GEX_Output(spot_price, gex_by_expiration(option_data), gex_by_strike(spot_price, option_data))


@lru_cache(maxsize=100)  # Adjust cache size as needed
def scrape_data(ticker):
    # Fix ticker format
    if ticker.startswith("^"):
        ticker = ticker[1:]

    urls = [
        f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{ticker}.json",
        f"https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json",
    ]

    for url in urls:
        try:
            data = requests.get(url)
            data.raise_for_status()  # Raise an error for HTTP errors
            break  # Exit the loop if the request was successful
        except (requests.RequestException, ValueError):
            data = None
            continue  # Try the next URL if one fails

    if data is None:
        return None, None

    # Convert json to pandas DataFrame
    data = pd.DataFrame.from_dict(data.json())

    spot_price = data.loc["current_price", "data"]
    option_data = pd.DataFrame(data.loc["options", "data"])

    return spot_price, fix_option_data(option_data)


def fix_option_data(data):
    """
    Fix option data columns.

    From the name of the option derive type of option, expiration and strike price
    """
    data["type"] = data.option.str.extract(r"\d([A-Z])\d")
    data["strike"] = data.option.str.extract(r"\d[A-Z](\d+)\d\d\d").astype(int)
    data["expiration"] = data.option.str.extract(r"[A-Z](\d+)").astype(str)
    # Convert expiration to datetime format
    data["expiration"] = pd.to_datetime(data["expiration"], format="%y%m%d")
    return data


def compute_total_gex(spot, data):
    """Compute dealers' total GEX"""
    # Compute gamma exposure for each option
    data["GEX"] = spot * data.gamma * data.open_interest * contract_size * spot * 0.01

    # For put option we assume negative gamma, i.e. dealers sell puts and buy calls
    data["GEX"] = data.apply(lambda x: -x.GEX if x.type == "P" else x.GEX, axis=1)


def gex_by_expiration(data):
    """Compute and plot GEX by expiration"""
    # Limit data to options expiring in the next 90 days
    selected_date = datetime.today() + timedelta(days=90)
    data = data.loc[data.expiration < selected_date]

    # Compute GEX by expiration date
    gex_by_expiration = data.groupby("expiration")["GEX"].sum() / 10**9

    # Return plotly figure
    fig = go.Figure()
    fig.add_trace(go.Bar(x=gex_by_expiration.index, y=gex_by_expiration.values, marker_color="#FE53BB", opacity=0.5))

    # Enhance the plot layout
    fig.update_layout(
        autosize=True,
        width=None,
        height=None,
        xaxis_rangeslider_visible=False,
        margin={"t": 25, "b": 25},
    )

    return fig


def gex_by_strike(spot, data):
    """Compute and plot GEX by strike price"""
    # Limit data to options expiring in the next 90 days
    selected_date = datetime.today() + timedelta(days=90)
    data = data.loc[data.expiration < selected_date]

    # Compute GEX by strike price
    gex_by_strike = data.groupby("strike")["GEX"].sum() / 10**9

    # Limit data to +- 15% from spot price
    limit_criteria = (gex_by_strike.index > spot * 0.85) & (gex_by_strike.index < spot * 1.15)
    gex_by_strike = gex_by_strike.loc[limit_criteria]

    # Return plotly figure
    fig = go.Figure()
    fig.add_trace(go.Bar(x=gex_by_strike.index, y=gex_by_strike.values, marker_color="#FE53BB", opacity=0.5))

    # Enhance the plot layout
    fig.update_layout(
        autosize=True,
        width=None,
        height=None,
        xaxis_rangeslider_visible=False,
        margin={"t": 25, "b": 25},
    )

    return fig


def get_gex_payload(ticker: str, lookahead_days: int = 90, strike_window_pct: float = 0.15):
    """Structured GEX snapshot suitable for JSON serialization (frontend, archive).

    Returns ``None`` when the underlying option chain isn't available — call
    sites use that as the "no options listed for this ticker" signal.

    The payload bundles:
      * spot price + total GEX (in USD billions, signed)
      * regime label (long_gamma / short_gamma) inferred from the sign of
        total GEX. Long gamma = dealers buy dips/sell rallies (mean-revert);
        short gamma = dealers chase moves (amplifies trend).
      * GEX bucketed by strike (within ±strike_window_pct of spot) and by
        expiration (within the next lookahead_days), so a UI can render
        per-bucket bars and a zero-gamma crossing point without re-doing
        the math.
      * zero_gamma_strike — the strike at which the cumulative GEX flips
        sign as you walk strikes from low → high. Often used as a regime
        boundary by intraday traders.
      * largest_call_wall / largest_put_wall — the strike with the most
        positive (call) and most negative (put) GEX. The "wall" levels
        mean-revert price intraday in long-gamma regimes.
    """
    spot, option_data = scrape_data(ticker)
    if option_data is None:
        return None

    compute_total_gex(spot, option_data)
    cutoff = datetime.today() + timedelta(days=lookahead_days)
    near = option_data.loc[option_data.expiration < cutoff]
    if near.empty:
        return None

    by_strike_full = near.groupby("strike")["GEX"].sum() / 10**9
    in_window = (by_strike_full.index > spot * (1 - strike_window_pct)) & (
        by_strike_full.index < spot * (1 + strike_window_pct)
    )
    by_strike = by_strike_full.loc[in_window].sort_index()
    by_expiration = near.groupby("expiration")["GEX"].sum().sort_index() / 10**9

    total_gex = float(by_strike_full.sum())
    regime = "long_gamma" if total_gex >= 0 else "short_gamma"

    cumulative = by_strike_full.sort_index().cumsum()
    zero_gamma_strike = None
    prev_strike, prev_val = None, None
    for strike, cum in cumulative.items():
        if prev_val is not None and (prev_val < 0 <= cum or prev_val > 0 >= cum):
            # Linear interpolation between the bracketing strikes.
            denom = cum - prev_val
            zero_gamma_strike = float(prev_strike) if denom == 0 else float(
                prev_strike + (strike - prev_strike) * (-prev_val) / denom
            )
            break
        prev_strike, prev_val = strike, cum

    if not by_strike.empty:
        call_wall_strike = float(by_strike.idxmax())
        call_wall_gex = float(by_strike.max())
        put_wall_strike = float(by_strike.idxmin())
        put_wall_gex = float(by_strike.min())
    else:
        call_wall_strike = call_wall_gex = put_wall_strike = put_wall_gex = None

    return {
        "ticker": ticker,
        "spot_price": float(spot),
        "total_gex_b": total_gex,
        "regime": regime,
        "zero_gamma_strike": zero_gamma_strike,
        "largest_call_wall": (
            {"strike": call_wall_strike, "gex_b": call_wall_gex}
            if call_wall_strike is not None
            else None
        ),
        "largest_put_wall": (
            {"strike": put_wall_strike, "gex_b": put_wall_gex}
            if put_wall_strike is not None
            else None
        ),
        "by_strike": [
            {"strike": float(k), "gex_b": float(v)} for k, v in by_strike.items()
        ],
        "by_expiration": [
            {"expiration": d.strftime("%Y-%m-%d"), "gex_b": float(v)}
            for d, v in by_expiration.items()
        ],
        "lookahead_days": lookahead_days,
        "strike_window_pct": strike_window_pct,
    }


if __name__ == "__main__":
    get_current_gex("^SPX")
