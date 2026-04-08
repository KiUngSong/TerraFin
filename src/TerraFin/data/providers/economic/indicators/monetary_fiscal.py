import pandas as pd

from TerraFin.data.providers.private_access.cape import get_cape_history

from ..fred_data import get_fred_data
from ..registry import EconomicIndicator


def money_multiplier(*args, **kwargs):
    m2 = get_fred_data("WM2NS")
    m0 = get_fred_data("BOGMBASE")

    # Calculate the common date range
    m0_min_date, m0_max_date = m0.index.min(), m0.index.max()
    m2_min_date, m2_max_date = m2.index.min(), m2.index.max()

    common_start_date = max(m0_min_date.to_period("M"), m2_min_date.to_period("M")).to_timestamp()
    common_end_date = (
        min(m0_max_date.to_period("M"), m2_max_date.to_period("M")).to_timestamp("M").to_period("M").to_timestamp("M")
    )

    # Filter the data by the common date range
    m0 = m0.loc[common_start_date:common_end_date]
    m2 = m2.loc[common_start_date:common_end_date]

    # Reindex the data
    m0_reindexed = m0.reindex(m2.index, method="nearest")

    # Divide m2 by the reindexed m0
    result_series = m2["Close"] / m0_reindexed["Close"]

    # Convert the result into a DataFrame with a specific column name
    result_df = pd.DataFrame(result_series, columns=["Close"])

    return result_df


def cape_ratio(*args, **kwargs):
    """CAPE (Shiller PE10): Cyclically Adjusted Price-to-Earnings Ratio.

    Fetches full history from DataFactory.
    """
    records = get_cape_history()
    if not records:
        return pd.DataFrame(columns=["Close"])

    rows = []
    for r in records:
        date_str = r["date"]
        # Convert "YYYY-MM" to timestamp (first day of month)
        rows.append({"Date": pd.Timestamp(date_str + "-01"), "Close": r["cape"]})

    df = pd.DataFrame(rows).set_index("Date").sort_index()
    return df


def buffett_indicator(*args, **kwargs):
    """Buffett Indicator: Total US equity market cap / GDP (as percentage).

    Uses NCBEILQ027S (total equity market cap in millions) and GDP (in billions).
    """
    mktcap = get_fred_data("NCBEILQ027S")  # Millions
    gdp = get_fred_data("GDP")  # Billions

    gdp_min, gdp_max = gdp.index.min(), gdp.index.max()
    mc_min, mc_max = mktcap.index.min(), mktcap.index.max()

    common_start = max(gdp_min.to_period("Q"), mc_min.to_period("Q")).to_timestamp()
    common_end = (
        min(gdp_max.to_period("Q"), mc_max.to_period("Q")).to_timestamp("Q").to_period("Q").to_timestamp("Q")
    )

    gdp = gdp.loc[common_start:common_end]
    mktcap = mktcap.loc[common_start:common_end]

    gdp_reindexed = gdp.reindex(mktcap.index, method="ffill")

    # mktcap is in millions, GDP in billions → convert GDP to millions
    ratio = mktcap["Close"] / (gdp_reindexed["Close"] * 1000) * 100
    return pd.DataFrame(ratio, columns=["Close"])


INDICATORS = {
    "TGA": EconomicIndicator(
        description="Treasury General Account: U.S. Treasury Department's primary account at the Federal Reserve.",
        key="WTREGEN",
    ),
    "M2": EconomicIndicator(
        description="M2 Money Stock: M2 is a broader measure of the money supply that includes M1 plus near-money assets like savings deposits and money market funds.",
        key="WM2NS",
    ),
    "M0": EconomicIndicator(
        description="M0 Money Stock: M0 is the most basic measure of the money supply and includes physical currency in circulation plus demand deposits at commercial banks.",
        key="BOGMBASE",
    ),
    "Money Multiplier": EconomicIndicator(
        description="Money Multiplier: The ratio of the money supply (M2) to the monetary base (M0).",
        get_data=money_multiplier,
    ),
    "Reserve Balance": EconomicIndicator(
        description="Reserve Balance: The total amount of reserves held by commercial banks at the Federal Reserve.",
        key="WRESBAL",
    ),
    "Term Spread": EconomicIndicator(
        description="Term Spread: The difference between the 10-year Treasury yield and the 2-year Treasury yield.",
        key="T10Y2Y",
    ),
    "SOMA": EconomicIndicator(
        description="SOMA: The total amount of reserves held by commercial banks at the Federal Reserve.",
        key="TREAST",
    ),
    "Buffett Indicator": EconomicIndicator(
        description="Buffett Indicator: Total US equity market cap as a percentage of GDP. Values above 100% suggest overvaluation.",
        get_data=buffett_indicator,
    ),
    "CAPE Index": EconomicIndicator(
        description="CAPE Index (Shiller PE10): Cyclically Adjusted Price-to-Earnings Ratio. 10-year inflation-adjusted P/E for the S&P 500.",
        get_data=cape_ratio,
    ),
    "M2 Velocity": EconomicIndicator(
        description="Velocity of M2 Money Stock: GDP divided by M2 money supply. Measures how quickly money circulates in the economy.",
        key="M2V",
    ),
}
