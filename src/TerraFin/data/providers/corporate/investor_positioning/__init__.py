# Portfolio Data Module for TerraFin
# Guru holdings via SEC EDGAR 13F filings with quarter-over-quarter changes.
from dataclasses import dataclass

import pandas as pd

from TerraFin.data.contracts.dataframes import PortfolioDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import (
    sec_edgar_is_configured,
    sec_edgar_status_message,
)
from TerraFin.data.providers.corporate.filings.sec_edgar.holdings import (
    get_available_gurus,
    get_guru_filings_index,
    get_guru_holdings,
    get_guru_holdings_for_date,
    get_guru_holdings_history,
)


ALL_GURUS: list[str] = get_available_gurus()


@dataclass
class PortfolioOutput:
    info: dict[str, str]
    df: PortfolioDataFrame


@dataclass(frozen=True)
class InvestorPositioningCapability:
    enabled: bool
    message: str | None = None


def get_investor_positioning_capability() -> InvestorPositioningCapability:
    enabled = sec_edgar_is_configured()
    return InvestorPositioningCapability(
        enabled=enabled,
        message=None if enabled else sec_edgar_status_message(),
    )


def get_portfolio_data(guru_name: str, filing_date: str | None = None) -> PortfolioOutput:
    """Get portfolio data for a guru via SEC EDGAR 13F.

    When filing_date is None, returns the latest filing (fast path, 1 XML).
    When filing_date is given, fetches exactly that quarter + previous (2 XMLs).
    """
    if filing_date is None:
        info, rows = get_guru_holdings(guru_name)
    else:
        info, rows = get_guru_holdings_for_date(guru_name, filing_date)
    df = PortfolioDataFrame(pd.DataFrame(rows))
    df.guru_name = guru_name
    return PortfolioOutput(info=info, df=df)


def get_portfolio_history_data(guru_name: str) -> list[dict]:
    """Return filing index for a guru (filing_date, period, accession), newest first.

    No XML fetching — only the SEC submissions index. Fast enough to call on every
    guru selection to populate the period dropdown.
    """
    return get_guru_filings_index(guru_name)


__all__ = [
    "ALL_GURUS",
    "InvestorPositioningCapability",
    "PortfolioOutput",
    "get_investor_positioning_capability",
    "get_portfolio_data",
    "get_portfolio_history_data",
    "get_guru_filings_index",
    "get_guru_holdings_for_date",
]
