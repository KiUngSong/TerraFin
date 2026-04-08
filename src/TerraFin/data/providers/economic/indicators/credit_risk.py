import pandas as pd

from ..fred_data import get_fred_data
from ..registry import EconomicIndicator


def net_liquidity(*args, **kwargs):
    """Net Liquidity: Bank Reserves minus Reverse Repo minus TGA.

    A widely-followed measure of system liquidity available to financial markets.
    Positive changes generally correlate with risk-asset strength.
    """
    reserves = get_fred_data("WRESBAL")
    rrp = get_fred_data("RRPONTSYD")
    tga = get_fred_data("WTREGEN")

    # Align all three series to a common date range
    common_index = reserves.index.intersection(rrp.index).intersection(tga.index)
    reserves = reserves.loc[common_index]
    rrp = rrp.loc[common_index]
    tga = tga.loc[common_index]

    result = reserves["Close"] - rrp["Close"] - tga["Close"]
    return pd.DataFrame(result, columns=["Close"])


def forward_rate_spread_18m(*args, **kwargs):
    """18-Month Forward Rate Spread: forward 3M rate implied by 1Y and 2Y yields, minus spot 3M yield.

    Favored by Fed Chair Powell as a recession predictor. Inversion (negative values)
    has historically preceded recessions.

    Calculation: derive the 18-month forward rate from 1Y (DGS1) and 2Y (DGS2) constant-maturity
    Treasury yields, then subtract the current 3M yield (DGS3MO).

    Forward rate formula:
        f(12,24) = (2 * y2 - 1 * y1) / (24 - 12)  (annualized 12-month forward starting in 12 months)
        Simplified: the implied 3M rate 18 months from now ~ (2*DGS2 - DGS1) * (18/12) - ...

    Using the standard forward rate derivation:
        (1 + y2)^2 = (1 + y1)^1 * (1 + f)^1
        f = ((1 + y2)^2 / (1 + y1)) - 1

    The spread = f - y_3m
    """
    y1 = get_fred_data("DGS1")  # 1-Year Treasury CMT
    y2 = get_fred_data("DGS2")  # 2-Year Treasury CMT
    y3m = get_fred_data("DGS3MO")  # 3-Month Treasury CMT

    common_index = y1.index.intersection(y2.index).intersection(y3m.index)
    y1 = y1.loc[common_index]
    y2 = y2.loc[common_index]
    y3m = y3m.loc[common_index]

    # Convert percentages to decimals
    y1_dec = y1["Close"] / 100
    y2_dec = y2["Close"] / 100
    y3m_dec = y3m["Close"] / 100

    # Implied 1-year forward rate starting 1 year from now
    forward_rate = ((1 + y2_dec) ** 2 / (1 + y1_dec)) - 1

    # Spread: forward rate minus current 3M yield (in percentage points)
    spread = (forward_rate - y3m_dec) * 100

    return pd.DataFrame(spread, columns=["Close"])


def credit_spread(*args, **kwargs):
    """Credit Spread (CP-Treasury): 3-Month Commercial Paper rate minus 3-Month Treasury yield.

    A successor to the TED spread (LIBOR - T-bill), which was discontinued in 2022.
    Measures unsecured short-term corporate funding cost relative to the risk-free rate.
    Rising values indicate increasing credit stress in the financial system.
    """
    cp = get_fred_data("DCPF3M")  # 3-Month AA Financial Commercial Paper Rate
    tbill = get_fred_data("DGS3MO")  # 3-Month Treasury CMT

    common_index = cp.index.intersection(tbill.index)
    cp = cp.loc[common_index]
    tbill = tbill.loc[common_index]

    spread = cp["Close"] - tbill["Close"]
    return pd.DataFrame(spread, columns=["Close"])


INDICATORS = {
    "High Yield Spread": EconomicIndicator(
        description="ICE BofA US High Yield Option-Adjusted Spread: measures credit stress via the yield premium of high-yield bonds over Treasuries.",
        key="BAMLH0A0HYM2",
    ),
    "RRP": EconomicIndicator(
        description="Overnight Reverse Repurchase Agreements (RRP): total value of the Fed's reverse repo facility, a key measure of excess liquidity in the financial system.",
        key="RRPONTSYD",
    ),
    "Net Liquidity": EconomicIndicator(
        description="Net Liquidity: Bank Reserves minus Reverse Repo minus TGA. Measures system liquidity available to financial markets.",
        get_data=net_liquidity,
    ),
    "18M Forward Rate Spread": EconomicIndicator(
        description="18-Month Forward Rate Spread: implied forward rate from 1Y/2Y Treasuries minus 3M yield. Powell's preferred recession predictor.",
        get_data=forward_rate_spread_18m,
    ),
    "Credit Spread": EconomicIndicator(
        description="Credit Spread (CP-Treasury): 3M Commercial Paper minus 3M Treasury yield. Successor to the TED spread for measuring interbank credit stress.",
        get_data=credit_spread,
    ),
}
