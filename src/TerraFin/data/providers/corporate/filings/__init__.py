def get_sec_filing_data(ticker: str, filing_type: str = "10-Q", filing_index: int = 0, parse: bool = True):
    """
    Get SEC filing data for a company.

    Args:
        ticker (str): Stock ticker symbol
        filing_type (str): Type of filing ("10-K", "10-Q", "8-K")
        filing_index (int): Index of filing to retrieve (0 = latest)
        parse (bool): Whether to parse the filing content to markdown

    Returns:
        str: Raw HTML content or parsed markdown content
    """
    from .sec_edgar import get_sec_data

    return get_sec_data(ticker, filing_type, filing_index, parse)


__all__ = ["get_sec_filing_data"]
