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

For deployment and upstream data-usage responsibilities, see
[License & Data Rights](./legal.md).

For most callers, the important pieces are:

- `DataFactory` for fetching data
- `TimeSeriesDataFrame` for chart-ready time series
- `HistoryChunk` for progressive chart-history loading
- `PortfolioOutput` for 13F holdings data

## Architecture

```
Routes / Agent / Frontend
        ↓
   DataFactory ──── CacheManager (uniform cache for all sources)
        ↓
   Providers (all return predefined contracts only)
   ├── yfinance        (market data, fundamentals)
   ├── FRED            (economic indicators)
   ├── market indicator (VIX, MOVE, ...)
   ├── economic        (UNRATE, M2, derived indicators)
   ├── private_access  (CAPE, fear/greed, breadth, P/E spread — HTTP to sibling DataFactory)
   ├── SEC EDGAR       (filings, 13F)
   └── corporate       (yfinance fundamentals)
```

## Rules of the road

These are hard rules. They apply to every provider, every route, every agent
capability.

- **Contracts are the only return type.** All providers return ONLY a
  predefined contract from `src/TerraFin/data/contracts/`. No ad-hoc dicts
  (`{date, cape}` etc.) — ever.
- **`DataFactory` is the single facade.** Routes, the agent, and the frontend
  never call providers directly. They go through `DataFactory`.
- **Caching is unified.** All caching goes through `CacheManager`. Providers
  themselves are pure fetchers.
- **`private_access` must shape to TerraFin contracts.** The HTTP server in
  the sibling `~/Downloads/work/DataFactory` repo MUST shape responses to
  match the contracts in this repo. Contract definitions in
  `src/TerraFin/data/contracts/` are the source of truth.
- **Adding a new data type is a three-step pattern, no exceptions:**
  1. Define a contract in `data/contracts/` (or reuse an existing one).
  2. Write a provider that returns that contract.
  3. Register the provider with `DataFactory`.

## Contracts

Source: `src/TerraFin/data/contracts/` (canonical list in
[`__init__.py`](https://github.com/KiUngSong/TerraFin/blob/main/src/TerraFin/data/contracts/__init__.py))

Every provider's public return type is one of the contracts below. Each entry
gives the file location, the key fields, the validation the contract enforces
on construction, and one short example.

### `TimeSeriesDataFrame`

- Location: `src/TerraFin/data/contracts/dataframes.py`
- Subclass of `pd.DataFrame`
- Columns kept (in order): `time`, `open`, `high`, `low`, `close`, `volume`
- Validation: `close` is required after normalization; `time` must parse as
  datetime; rows are sorted by `time` and de-duplicated; non-positive prices
  are dropped; column aliases (`Date`, `datetime`, `Close`, ...) are
  normalized; on failure the constructor returns an empty frame with the
  canonical schema.
- Carries `.name` (series label) and `.chart_meta` (chart-side metadata).
- Example: `df = factory.get("AAPL")` → `TimeSeriesDataFrame` chart-ready.

### `HistoryChunk`

- Location: `src/TerraFin/data/contracts/history.py`
- Dataclass with `frame: TimeSeriesDataFrame`, `loaded_start`, `loaded_end`,
  `requested_period`, `is_complete`, `has_older`, `source_version`.
- Used for progressive chart loading. Bounds and flags let the frontend
  decide whether to backfill older history.
- Example: `chunk = factory.get_recent_history("S&P 500", period="3y")` →
  seed window plus `has_older=True` to drive the backfill request.

### `PortfolioDataFrame` and `PortfolioOutput`

- Location: `src/TerraFin/data/contracts/dataframes.py`
- `PortfolioDataFrame` is a `pd.DataFrame` subclass with a `make_figure()`
  method that renders a Plotly treemap of 13F holdings.
- `PortfolioOutput` (defined alongside `DataFactory`) bundles `info: dict`
  metadata and `df: PortfolioDataFrame`.
- Validation: `Stock` / `Ticker` / `% of Portfolio` / `Updated` /
  `Recent Activity` columns are expected by `make_figure()`.
- Example: `out = factory.get_portfolio_data("Warren Buffett")` →
  `out.df.make_figure()` for the treemap.

### `FinancialStatementFrame`

- Location: `src/TerraFin/data/contracts/statements.py`
- `pd.DataFrame` subclass. Columns are reporting-period dates (ISO strings or
  `pd.Timestamp`); rows are line items.
- Required at construction: `statement_type` ∈ {`income`, `balance`,
  `cashflow`}, `period` ∈ {`annual`, `quarterly`}, `ticker`. Column-shape
  validation rejects non-date columns.
- Example: `frame = factory.get_corporate_data("AAPL",
  statement_type="income", period="annual")` → income statement keyed by
  fiscal year.

### `CalendarEvent` and `EventList`

- Location: `src/TerraFin/data/contracts/events.py`
- `CalendarEvent` is a frozen dataclass with `id`, `title`, `start`
  (timezone-aware datetime — enforced), `category` ∈ {`macro`, `earning`,
  `fed`, `dividend`, `ipo`}, `importance` ∈ {`low`, `medium`, `high`},
  `display_time`, plus optional `description`, `source`, `metadata`.
- `EventList` wraps `list[CalendarEvent]` and supports iteration and
  indexing.
- Example: macro calendar provider returns an `EventList` of FOMC and
  release-date events; the calendar route serializes them directly.

### `TOCEntry` and `FilingDocument`

- Location: `src/TerraFin/data/contracts/filings.py`
- `TOCEntry`: frozen dataclass — `id`, `title`, `level`, `anchor`.
- `FilingDocument`: dataclass with `ticker`, `filing_type` ∈ {`10-K`,
  `10-Q`, `8-K`, `13F`, `S-1`, `DEF 14A`}, `accession`, `filing_date`,
  `markdown`, `toc: list[TOCEntry]`, optional `metadata`.
- Example: SEC EDGAR provider returns a `FilingDocument` whose `markdown`
  body and `toc` drive the Stock Analysis filings panel.

### `IndicatorSnapshot`

- Location: `src/TerraFin/data/contracts/indicators.py`
- Frozen dataclass: `name`, `value` (number or string), `as_of`,
  optional `unit`, `change`, `change_pct`, `rating`, `metadata`.
- Use for single-value scalar indicators (current Fear & Greed score, latest
  CAPE, breadth-of-the-day) where a full time series isn't needed.
- Example: dashboard fear/greed widget reads
  `snapshot = factory.get_indicator("fear_greed")` and renders
  `snapshot.value` and `snapshot.rating`.

### `chart_output`

- Location: `src/TerraFin/data/contracts/markers.py`
- Decorator that normalizes the return of any time-series-shaped
  `DataFactory` method into a `TimeSeriesDataFrame` via `_to_timeseries`,
  tagging the source for cache and debug visibility.
- Not a return type itself — a marker applied to factory methods that
  promise time-series output.

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

## Output type conveniences

The contract definitions above are the source of truth. A few notes about
working with them in practice:

- `TimeSeriesDataFrame.make_empty()` returns an empty frame with the canonical
  schema; `.name` and `.chart_meta` survive slicing and pandas operations.
- `FinancialStatementFrame.make_empty(statement_type, period, ticker)`
  creates an empty statement frame with the right metadata for a missing
  source.
- `EventList.make_empty()` and `FilingDocument.make_empty(ticker, filing_type)`
  exist for the same reason — empty results stay typed.

## Provider map

| Domain | Backing source | Typical access path | Notes |
|--------|----------------|---------------------|-------|
| Market prices | yfinance | `get("AAPL")`, `get("S&P 500")`, `get("Shanghai Composite")` | Handles tickers and index aliases |
| Market indicators | Registry-backed market series | `get("VIX")`, `get("MOVE")`, `get("Net Breadth")` | Mix of yfinance-backed and private-series-backed names resolved before raw tickers |
| Economic series | FRED | `get_fred_data("UNRATE")`, `get("Unemployment Rate")` | Human-readable names map to FRED codes |
| Computed macro indicators | FRED-derived logic | `get("Buffett Indicator")` | Built from public series |
| Credit and risk indicators | FRED and FRED-derived | `get("High Yield Spread")`, `get("Net Liquidity")` | HY spread, RRP, net liquidity, 18M forward rate spread, credit spread |
| Corporate fundamentals | yfinance statement adapter | `get_corporate_data("AAPL")` | Returns a plain pandas frame |
| SEC filings | SEC EDGAR | `get_sec_data(ticker, filing_type)`, `get_sec_toc(ticker, filing_type)` | Parses 10-K / 10-Q HTML into markdown + TOC; cached 30 days under the `sec_filings` namespace |
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

Private-access features are TerraFin's bridge beyond the public core. They let
the same public interfaces connect to deployment-specific data and
operator-side workflows without making those extensions part of the default
open-source path.

These are intentional private-access extensions, not arbitrary hidden features.
They provide one authenticated boundary where operator-managed deployments can
attach broader workflow-specific data while public/demo deployments continue to
run on public providers and safe fallbacks.

Private-access features provide proprietary or deployment-specific data behind
an authenticated endpoint. They are optional: if the endpoint is unavailable,
TerraFin may fall back to local file cache first and then to bundled fixtures
or empty defaults, depending on the resource. This means local or private
installs can continue to function without private credentials, with reduced
coverage for private dashboard data. That fallback behavior should be treated
as an operational convenience for controlled deployments, not as a blanket
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
