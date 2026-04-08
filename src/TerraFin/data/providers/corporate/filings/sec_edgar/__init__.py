# SEC EDGAR Data Module for TerraFin
# This module provides access to SEC EDGAR filing data

from typing import Any

from .filing import download_filing, get_company_filings, ticker_to_cik_dict
from .parser import parse_sec_filing


_TICKER2CIK_DICT: dict[Any, Any] | None = None


def _get_ticker_to_cik_dict() -> dict[Any, Any]:
    global _TICKER2CIK_DICT
    if _TICKER2CIK_DICT is None:
        _TICKER2CIK_DICT = ticker_to_cik_dict()
    return _TICKER2CIK_DICT


def get_sec_data(ticker: str, filing_type: str = "10-Q", filing_index: int = 0, parse: bool = True):
    """
    Main interface for getting SEC filing data.

    Args:
        ticker (str): Stock ticker symbol
        filing_type (str): Type of filing to retrieve ("10-K", "10-Q", "8-K")
        filing_index (int): Index of filing to retrieve (0 = latest)
        parse (bool): Whether to parse the filing content to markdown

    Returns:
        str or pd.DataFrame: Raw HTML content or parsed markdown, depending on parse parameter
    """
    cik = _get_ticker_to_cik_dict().get(ticker.upper())

    if cik is None:
        raise ValueError(f"CIK not found for ticker: {ticker}")

    # Get filings based on type
    include_8k = filing_type == "8-K"
    filings_df = get_company_filings(cik, include_8k=include_8k)

    if filings_df is None or len(filings_df) == 0:
        raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    # Filter by filing type if specified
    if filing_type != "all":
        filings_df = filings_df[filings_df.form == filing_type]
        if len(filings_df) == 0:
            raise ValueError(f"No {filing_type} filings found for ticker: {ticker}")

    if filing_index >= len(filings_df):
        raise ValueError(f"Filing index {filing_index} out of range. Available: 0-{len(filings_df) - 1}")

    # Get filing details
    accession_number = filings_df.accessionNumber.iloc[filing_index].replace("-", "")
    file_name = filings_df.primaryDocument.iloc[filing_index]
    filing_form = filings_df.primaryDocDescription.iloc[filing_index]

    # Download content
    html_content = download_filing(cik, accession_number, file_name)

    if parse:
        return parse_sec_filing(html_content, filing_form)
    else:
        return html_content
