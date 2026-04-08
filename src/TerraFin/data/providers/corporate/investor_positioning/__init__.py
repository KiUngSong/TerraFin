# Portfolio Data Module for TerraFin
# Guru holdings via SEC EDGAR 13F filings with quarter-over-quarter changes.
from dataclasses import dataclass

import pandas as pd

from TerraFin.data.contracts.dataframes import PortfolioDataFrame
from TerraFin.data.providers.corporate.filings.sec_edgar.filing import (
    sec_edgar_is_configured,
    sec_edgar_status_message,
)
from TerraFin.data.providers.corporate.filings.sec_edgar.holdings import get_available_gurus, get_guru_holdings


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


def get_portfolio_data(guru_name: str) -> PortfolioOutput:
    """Get portfolio data for a guru via SEC EDGAR 13F.

    Fetches latest two quarterly filings and computes share changes
    (Buy, Add, Reduce) between them. Cached to disk (7-day TTL).
    """
    info, rows = get_guru_holdings(guru_name)
    df = PortfolioDataFrame(pd.DataFrame(rows))
    df.guru_name = guru_name
    return PortfolioOutput(info=info, df=df)


__all__ = [
    "ALL_GURUS",
    "InvestorPositioningCapability",
    "PortfolioOutput",
    "get_investor_positioning_capability",
    "get_portfolio_data",
]
