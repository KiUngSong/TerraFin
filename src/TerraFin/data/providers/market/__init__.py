from .market_indicator import MARKET_INDICATOR_REGISTRY
from .yfinance import get_yf_data


INDEX_MAP = {
    "Dow": "^DJI",
    "S&P 500": "^SPX",
    "Nasdaq": "^IXIC",
    "Shanghai Composite": "000001.SS",
    "Kospi": "^KS11",
    "Kosdaq": "^KQ11",
    "Nikkei 225": "^N225",
}

INDEX_DESCRIPTIONS = {
    "Dow": "Price-weighted U.S. blue-chip equity index.",
    "S&P 500": "Benchmark U.S. large-cap equity index.",
    "Nasdaq": "Technology-heavy U.S. equity index.",
    "Shanghai Composite": "Broad mainland China equity benchmark tracking the Shanghai market.",
    "Kospi": "Benchmark South Korean large-cap equity index.",
    "Kosdaq": "South Korean growth and technology-focused equity index.",
    "Nikkei 225": "Price-weighted Japanese large-cap equity index.",
}


def get_index_ticker_if_exists(index_name: str):
    return INDEX_MAP.get(index_name, index_name)


def get_market_data(ticker_or_index_name_or_indicator_name: str):
    if ticker_or_index_name_or_indicator_name in MARKET_INDICATOR_REGISTRY:
        indicator = MARKET_INDICATOR_REGISTRY[ticker_or_index_name_or_indicator_name]
        data = indicator.get_data(indicator.key)
    else:
        ticker = get_index_ticker_if_exists(ticker_or_index_name_or_indicator_name)
        data = get_yf_data(ticker)

    # Return raw dataframe here.
    # DataFactory-level chart_output normalization handles unified output contract.
    return data


__all__ = [
    "get_market_data",
    "get_index_ticker_if_exists",
    "INDEX_MAP",
    "INDEX_DESCRIPTIONS",
    "MARKET_INDICATOR_REGISTRY",
]
