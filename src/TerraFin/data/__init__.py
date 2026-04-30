"""Data access layer."""

from .contracts import (
    CalendarEvent,
    EventList,
    FilingDocument,
    FinancialStatementFrame,
    HistoryChunk,
    IndicatorSnapshot,
    PortfolioDataFrame,
    TimeSeriesDataFrame,
    TOCEntry,
)
from .factory import DataFactory, get_data_factory
from .providers.corporate.filings.sec_edgar import (
    build_toc,
    download_filing,
    get_company_filings,
    get_ticker_to_cik_dict_cached,
    parse_sec_filing,
)
from .providers.corporate.filings.sec_edgar.filing import (
    SecEdgarConfigurationError,
    SecEdgarError,
    SecEdgarUnavailableError,
)
from .providers.economic import indicator_registry
from .providers.market import INDEX_DESCRIPTIONS, INDEX_MAP, MARKET_INDICATOR_REGISTRY
from .providers.market.ticker_info import get_ticker_earnings, get_ticker_info


__all__ = [
    "DataFactory",
    "get_data_factory",
    "TimeSeriesDataFrame",
    "PortfolioDataFrame",
    "HistoryChunk",
    "FinancialStatementFrame",
    "CalendarEvent",
    "EventList",
    "TOCEntry",
    "FilingDocument",
    "IndicatorSnapshot",
    # Provider metadata re-exports — constants/registries, not data calls.
    "MARKET_INDICATOR_REGISTRY",
    "INDEX_MAP",
    "INDEX_DESCRIPTIONS",
    "indicator_registry",
    # SEC building blocks for routes that compose filing flows DataFactory
    # does not (yet) expose directly.
    "SecEdgarConfigurationError",
    "SecEdgarError",
    "SecEdgarUnavailableError",
    "build_toc",
    "download_filing",
    "get_company_filings",
    "get_ticker_to_cik_dict_cached",
    "parse_sec_filing",
    # Ticker metadata accessors used by stock payloads + DCF inputs.
    "get_ticker_earnings",
    "get_ticker_info",
]
