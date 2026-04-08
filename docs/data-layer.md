---
title: Data Acquisition Layer
summary: How TerraFin resolves names, normalizes outputs, and fetches public and private data.
read_when:
  - Adding a new data provider or indicator
  - Debugging data fetch failures or cache issues
  - Understanding how DataFactory resolves a ticker or indicator name
  - Working with TimeSeriesDataFrame or PortfolioDataFrame
---

# Data Acquisition Layer

The data layer lives under `src/TerraFin/data/`. Its job is to hide provider
differences behind a small set of entry points and return predictable output
shapes.

For deployment and upstream data-usage responsibilities, see the `Important`
notice in the project [README](../README.md).

For most callers, the important pieces are:

- `DataFactory` for fetching data
- `TimeSeriesDataFrame` for chart-ready time series
- `HistoryChunk` for progressive chart-history loading
- `PortfolioOutput` for 13F holdings data

## DataFactory

Source: `src/TerraFin/data/factory.py`

```python
DataFactory(api_keys: dict[str, str] | None = None)
```

`DataFactory` is the main entry point. Use `get(name)` when you want TerraFin
to decide where a name belongs, or call a domain-specific method when you
already know the source.

### Resolution order for `get(name)`

1. Market indicator registry (VIX, treasuries, ...)
2. Economic indicator registry (FRED series, macro, ...)
3. Index map + yfinance (tickers, index names)

### Which method to call

| Method | Return type | Description |
|--------|-------------|-------------|
| `get(name)` | `TimeSeriesDataFrame` | Universal lookup across market indicators, economic indicators, index aliases, and raw tickers |
| `get_recent_history(name, period="3y")` | `HistoryChunk` | Recent seed window used by progressive chart loading |
| `get_full_history_backfill(name, loaded_start=None)` | `HistoryChunk` | Older history to prepend onto an already-seeded chart |
| `get_fred_data(indicator_name)` | `TimeSeriesDataFrame` | Direct FRED lookup by FRED code such as `"UNRATE"` |
| `get_economic_data(indicator_name)` | `TimeSeriesDataFrame` | Human-readable economic lookup such as `"Unemployment Rate"` |
| `get_market_data(ticker_or_name)` | `TimeSeriesDataFrame` | Market lookup through the market provider layer |
| `get_corporate_data(ticker, statement_type="income", period="annual")` | `pd.DataFrame \| None` | Company financials via TerraFin's yfinance-backed statement adapter. |
| `get_portfolio_data(guru_name)` | `PortfolioOutput` | Guru portfolio holdings via SEC EDGAR 13F filings |

The time-series methods are normalized by the `@chart_output` decorator before
they are returned.

## Output types

Source: `src/TerraFin/data/utils/output_types.py`

### TimeSeriesDataFrame

`TimeSeriesDataFrame` is TerraFin's canonical time-series container. The class
extends `pd.DataFrame`, but it normalizes columns and validates the result on
construction.

| Behavior | Notes |
|----------|-------|
| Canonical columns | Keeps only `time`, `open`, `high`, `low`, `close`, `volume` when present |
| Required signal | `close` must exist after normalization |
| Time parsing | Uses a `time`-like column if available, otherwise the index |
| Ordering | Sorts by time and drops duplicate timestamps |
| Aliases | Normalizes names like `Date`, `datetime`, and `Close` to TerraFin's schema |
| Empty fallback | Returns an empty frame with the canonical columns on normalization failure |

Common conveniences:

- `.name` stores the series label used by the chart and interface layers
- `make_empty()` creates an empty frame with the expected schema
- slicing and pandas operations preserve the custom type

### PortfolioOutput and PortfolioDataFrame

`get_portfolio_data()` returns a `PortfolioOutput` dataclass:

- `info: dict` for metadata such as period and source
- `df: PortfolioDataFrame` for holdings rows

`PortfolioDataFrame` adds `make_figure()`, which renders a Plotly treemap of
portfolio holdings.

### HistoryChunk

Progressive chart loading uses `HistoryChunk` rather than a bare dataframe.

It carries:

- `frame`: the actual `TimeSeriesDataFrame`
- `loaded_start` and `loaded_end`: the time span currently covered
- `requested_period`: the seed period, such as `3y`, when relevant
- `is_complete`: whether the entire history is already loaded
- `has_older`: whether more data exists before `loaded_start`
- `source_version`: a lightweight debug label for the source/cache path used

## Provider map

| Domain | Backing source | Typical access path | Notes |
|--------|----------------|---------------------|-------|
| Market prices | yfinance | `get("AAPL")`, `get("S&P 500")`, `get("Shanghai Composite")` | Handles tickers and index aliases |
| Market indicators | Registry-backed market series | `get("VIX")`, `get("MOVE")`, `get("Net Breadth")` | Mix of yfinance-backed and private-series-backed names resolved before raw tickers |
| Economic series | FRED | `get_fred_data("UNRATE")`, `get("Unemployment Rate")` | Human-readable names map to FRED codes |
| Computed macro indicators | FRED-derived logic | `get("Buffett Indicator")` | Built from public series |
| Credit and risk indicators | FRED and FRED-derived | `get("High Yield Spread")`, `get("Net Liquidity")` | HY spread, RRP, net liquidity, 18M forward rate spread, credit spread |
| Corporate fundamentals | yfinance statement adapter | `get_corporate_data("AAPL")` | Returns a plain pandas frame |
| SEC filings | SEC EDGAR | provider-level usage | Corporate filing helpers live under `providers/corporate/filings/` |
| Guru portfolios | SEC EDGAR 13F | `get_portfolio_data("Warren Buffett")` | Returns `PortfolioOutput` |
| Private dashboard data | Private endpoint with fallbacks | dashboard and market-insights APIs | Watchlist, breadth, trailing-forward P/E spread, CAPE, calendar, fear/greed, top companies |
| Macro events | FRED plus yfinance | calendar API | Fetched locally, but managed through the private-data cache lifecycle |

Registry locations:

- Market indicators: `src/TerraFin/data/providers/market/market_indicator.py`
- Economic indicators: `src/TerraFin/data/providers/economic/registry.py`
- Guru portfolio registry: `src/TerraFin/data/providers/corporate/filings/sec_edgar/guru_cik.json`

The supported guru names for the 13F feature are maintained in the JSON
registry above rather than hardcoded inline in Python, so additions and edits
can stay data-backed and easier to review.

If `TERRAFIN_SEC_USER_AGENT` is missing, TerraFin still exposes the supported
guru list but treats SEC-backed holdings as disabled. The interface and agent
API return explicit configuration errors instead of silently falling back to
third-party proxies.

### Private access

Private-access features provide proprietary or deployment-specific data behind an
authenticated endpoint. They are optional: if the endpoint is unavailable,
TerraFin may fall back to local file cache first and then to bundled fixtures
or empty defaults, depending on the resource. This means local or private
installs can continue to function without private credentials, with reduced
coverage for private dashboard data. That fallback behavior should be treated as
an operational convenience for controlled deployments, not as a blanket
permission to serve cached restricted data publicly.

Configuration via env vars:

| Variable | Description |
|----------|-------------|
| `TERRAFIN_PRIVATE_SOURCE_ENDPOINT` | Base endpoint URL for the private source |
| `TERRAFIN_PRIVATE_SOURCE_ACCESS_KEY` | Header name used for authentication |
| `TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE` | Header value used for authentication |
| `TERRAFIN_PRIVATE_SOURCE_TIMEOUT_SECONDS` | HTTP timeout (default: 10) |
| `TERRAFIN_SEC_USER_AGENT` | Required SEC EDGAR user-agent string for filings and 13F access |
| `TERRAFIN_MONGODB_URI` / `MONGODB_URI` | Optional MongoDB backend for watchlist write mode |

Implementation lives under `src/TerraFin/data/providers/private_access/`.

The private endpoint currently backs these dashboard and market-insight
resources:

- watchlist
- market breadth
- trailing-forward P/E spread
- CAPE
- calendar data
- fear/greed
- top companies

### Private series vs private widget

Private-source data in TerraFin should be classified one of two ways.

#### PrivateSeries

Use this when the data should behave like a real TerraFin series.

Requirements:

- normalize to `TimeSeriesDataFrame`
- be usable through `DataFactory`
- support `HistoryChunk` semantics if optimized chart serving is needed
- share the same cache and progressive-history contract as other chartable series

Examples:

- `Fear & Greed` when used as a chart/searchable series
- `Net Breadth` as a chart/searchable breadth history series
- future chartable private series such as `CAPE` or
  `Trailing-Forward P/E Spread`, if promoted into the chart/search flow

#### PrivateWidget

Use this when the data is only a dashboard or page payload.

Characteristics:

- arbitrary JSON/dict/list response shape
- simple cache and refresh behavior
- no `DataFactory` or chart progressive-history requirement

Examples:

- top-companies payloads
- dashboard-only summaries that are not intended to become chart series

The rule is:

- if a private-source feature wants TerraFin's optimized chart serving, it must
  enter the system as `TimeSeriesDataFrame`
- otherwise it remains a widget payload and should not be forced into the chart
  pipeline

If TerraFin is deployed publicly, keep those private-source resources behind the
authenticated endpoint and treat fallback caches as an operational convenience,
not as redistribution permission. Public/demo deployments should rely on public
providers and bundled public-safe fixtures, not warmed private-source caches.

### Watchlist write mode

The watchlist page always remains available in read-only sample mode. Writable
watchlist CRUD is optional and only turns on when MongoDB is configured
through:

- `TERRAFIN_MONGODB_URI` or `MONGODB_URI`
- `TERRAFIN_WATCHLIST_MONGODB_DATABASE`
- `TERRAFIN_WATCHLIST_MONGODB_COLLECTION`
- `TERRAFIN_WATCHLIST_DOCUMENT_ID`

Without those settings, TerraFin keeps the page visible and serves bundled
sample data instead of failing startup.

### Macro events and the private-data lifecycle

Macro calendar events are fetched by TerraFin itself from public sources, not
from the private endpoint. They still participate in the same
`PrivateDataService` refresh and fallback flow as private data so the interface
has one consistent cache lifecycle.

| Module | Path | Responsibility |
|--------|------|----------------|
| Macro calendar | `src/TerraFin/data/providers/economic/macro_calendar.py` | Fetches release dates from FRED API |
| Macro values | `src/TerraFin/data/providers/economic/macro_values.py` | Enriches events with Latest/Previous from FRED series observations |
| Cache source | `private.macro` in CacheManager | Daily refresh via `PrivateDataService.refresh_macro()` |

Current limitation: macro events do not yet carry a reliable consensus
`expected` value. The current enrichment step only guarantees actual and prior
values.

## Caching

Provider caches are described in [caching.md](./caching.md). The short version:

- public providers such as yfinance and FRED use in-memory plus file cache
- yfinance also exposes progressive-history helpers backed by `yfinance_v2`
  columnar artifacts for `3Y` seed + full-history backfill flows
- guru portfolios use file cache and now participate in manager-driven invalidation
- private-access resources are also registered with the background cache manager
- file cache sits under `~/.terrafin/cache/`

When deploying TerraFin publicly, review private-access cache usage carefully.
Local cache can preserve previously fetched restricted data; that does not make
the data public-safe to serve. If a deployment mixes public traffic with
private-source access, treat cache contents as potentially restricted unless the
upstream terms clearly allow that storage and display pattern.

## Adding a provider

Use this checklist when extending the data layer:

1. Add a provider function under the correct domain package.
2. Return `TimeSeriesDataFrame` for chartable time series, or a clearly
   different type when the data is not time-series shaped.
3. Register the name in the market or economic registry if it should be
   discoverable through `DataFactory.get(...)`.
4. Add cache behavior only if the source benefits from reuse or background
   refresh.
5. For private-source features, decide explicitly whether the feature is a
   `PrivateSeries` or a `PrivateWidget` before wiring UI, chart, or agent
   surfaces.

## See also

- [feature-integration.md](./feature-integration.md) for the cross-layer checklist when a new data capability becomes public
- [interface.md](./interface.md) for the API layer built on top of these outputs
- [chart-architecture.md](./chart-architecture.md) for the shared chart session and progressive-history contract
- [analytics.md](./analytics.md) for modules that consume `TimeSeriesDataFrame`
- [caching.md](./caching.md) for refresh policies and file-cache behavior
