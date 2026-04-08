---
title: Chart Architecture
summary: How TerraFin seeds, transforms, mutates, backfills, and isolates chart sessions across pages, APIs, and notebook workflows.
read_when:
  - Debugging chart loading, empty states, or session mismatches
  - Modifying chart routes, state, or frontend chart components
  - Working on Stock Analysis, Market Insights, or notebook chart flows
  - Understanding progressive history loading and chart cache behavior
---

# Chart Architecture

TerraFin's chart system is built around one shared idea:

- the backend owns session-scoped chart state
- the frontend renders one long-lived chart instance per session
- named-series pages use progressive history loading
- raw dataframe writes use the same session model, but start as complete

That gives TerraFin one chart engine with different entry points:

- chart page search/add flows
- Stock Analysis
- Market Insights
- Python and notebook helpers
- agent chart helpers layered on top of the same chart session routes

## Core principles

### 1. Session-scoped state is the source of truth

Chart state lives in `src/TerraFin/interface/chart/state.py`.

Each session stores:

- current display payload
- current source payload before view transforms
- selected chart view such as `daily` or `monthly`
- chart selection state
- named series dataframes
- preformatted named series items
- pinned series names
- per-series history status

Unless a caller says otherwise, the backend uses the `default` session.

### 2. TerraFin uses one standard chart contract

There are two response shapes:

- bootstrap responses return `snapshot + historyBySeries`
- warm updates return `mutation + historyBySeries`

For raw dataframe writes, TerraFin treats the series as "complete from start".
For progressive named-series loads, TerraFin starts with a recent seed window
and fills older history in later.

### 3. The chart instance stays mounted

The React chart layer keeps one lightweight-charts instance alive and applies
payload changes incrementally. TerraFin no longer relies on page-level chart
remounts as the normal update path.

## End-to-end processing flow

### A. Data acquisition

The chart stack uses `DataFactory` from `src/TerraFin/data/factory.py`.

There are three important time-series entry points:

- `get(name)` for complete chart-ready history
- `get_recent_history(name, period="3y")` for progressive seed windows
- `get_full_history_backfill(name, loaded_start=...)` for older-history backfill

The progressive methods return `HistoryChunk`, which carries:

- `frame`
- `loaded_start`
- `loaded_end`
- `requested_period`
- `is_complete`
- `has_older`
- `source_version`

### B. Normalization

Providers return or are normalized into `TimeSeriesDataFrame`, TerraFin's
canonical chart-ready dataframe. It preserves the series label in `.name` and
normalizes columns into the standard `time/open/high/low/close/volume` shape.

### C. Source payload formatting

The chart routes format source data with:

- `build_multi_payload(...)`
- `build_multi_payload_from_items(...)`
- `format_series_item(...)`

The source payload is the pre-view-transform representation. TerraFin keeps
that source in session so later view changes can be rebuilt deterministically.

### D. View transform

`apply_view(...)` in `src/TerraFin/interface/chart/chart_view.py` transforms the
source payload for the selected timeframe. The transformed payload becomes the
display payload for the current session.

### E. Indicator overlays

If the transformed payload contains exactly one candlestick series, TerraFin
automatically appends:

- moving averages
- Bollinger Bands
- RSI
- MACD
- realized volatility
- range volatility

Indicator overlays are cached by payload signature in the chart state module so
repeated view rebuilds do not recompute the same indicator stack unnecessarily.

### F. Frontend render

The frontend entry point is `ChartComponent` in
`src/TerraFin/interface/frontend/src/chart/ChartComponent.tsx`.

The main responsibilities are:

- fetch or receive the session snapshot
- manage `historyBySeries`
- trigger progressive backfills when needed
- keep timeframe controls in sync with loaded history
- keep the top bar, canvas, and bottom bar on the same session id

`ChartCanvas` owns the actual lightweight-charts instance.

## Agent consumers use the same optimized history path

The agent layer in `src/TerraFin/agent/service.py` does not bypass chart
processing decisions for market and macro series.

Instead, it reuses the same core ingredients:

- progressive history acquisition through `get_recent_history(...)`
- complete-history fallback through `get(...)`
- chart-style `apply_view(...)`
- the shared indicator adapters used by chart overlays

That means an agent asking for `weekly` AAPL data and a user looking at the
same symbol in the chart are working from the same transform and indicator
rules, even though one receives structured JSON and the other sees pixels.

Optional chart opening from `TerraFin.agent.TerraFinAgentClient.open_chart(...)`
then hands off to the existing chart/session routes rather than inventing a
parallel chart path.

## Session management

### Backend session ids

Backend routes read `X-Session-ID`. If the header is absent, they use
`"default"`.

### Frontend session ids

The frontend creates per-tab session ids in
`src/TerraFin/interface/frontend/src/chart/api.ts`:

- each browser tab gets one tab id
- each page scope prefixes that tab id, for example `chart-page:<tab-id>`

That prevents hidden cross-page churn between:

- chart page
- Stock Analysis
- Market Insights

### Explicit session override for chart page

`ChartPage.tsx` also accepts `?sessionId=...` in the page URL. This matters for
embedded or notebook flows that must open a specific pre-seeded backend session.

### Notebook behavior

`display_chart_notebook(...)` in `src/TerraFin/interface/chart/client.py` now:

1. waits for `/ready`
2. starts the server if needed
3. posts chart data into the `default` chart session
4. opens `/chart?sessionId=default` in the notebook IFrame

That explicit session handoff prevents the empty-chart problem where the iframe
would otherwise generate a fresh frontend session unrelated to the seeded
backend payload.

## API families

### 1. Direct payload API

Used when the caller already has dataframes.

Main routes:

- `GET /chart/api/chart-data`
- `POST /chart/api/chart-data`
- `POST /chart/api/chart-view`
- `GET /chart/api/chart-selection`
- `POST /chart/api/chart-selection`

This path is used by:

- raw dataframe notebook updates
- direct chart bootstraps

Direct writes still initialize named-series and history metadata in the session,
but they are marked complete immediately.

### 2. Named-series progressive API

Used when TerraFin should resolve a name and manage older-history loading.

Main routes:

- `POST /chart/api/chart-series/add`
- `POST /chart/api/chart-series/set`
- `POST /chart/api/chart-series/progressive/set`
- `POST /chart/api/chart-series/progressive/backfill`
- `POST /chart/api/chart-series/remove`
- `GET /chart/api/chart-series/names`
- `GET /chart/api/chart-series/search`

This path is used by:

- chart page search-box adds
- Stock Analysis
- Market Insights macro quick-picks

## Progressive history model

TerraFin's progressive-history model is staged hydration, not transport-level
streaming.

Current default behavior:

- seed with recent `3Y`
- render immediately
- backfill older history in the background
- keep the current visible range stable

### Per-series history metadata

`historyBySeries` entries contain:

- `loadedStart`
- `loadedEnd`
- `isComplete`
- `hasOlder`
- `seedPeriod`
- `backfillInFlight`
- `requestToken`

`requestToken` lets TerraFin ignore stale backfill responses after ticker or
session changes.

### Frontend behavior

`ChartComponent` watches `historyBySeries` and automatically posts progressive
backfill requests for series that are:

- present in the chart
- not complete
- marked as having older history
- currently in backfill mode

Long-range controls are enabled only when the loaded history supports them:

- `3M`, `6M`, `1Y` are available immediately
- `5Y` waits until the loaded span covers five years
- `ALL` waits until `isComplete=true`

### Visible-range stability

Backfill mutations update the existing series rather than replacing the whole
chart session. The frontend keeps the current visible range instead of fitting
content again, so older history appears to the left without snapping the view.

## Page-specific flows

### Chart page

The plain chart page is the most general surface:

- it reads whatever the current session holds
- search-box adds use the progressive named-series API
- direct dataframe writes can also seed the page through the same session model

### Stock Analysis

Stock Analysis is chart-first:

- seed one ticker with `3Y`
- mount the chart immediately
- defer the slower information panels until the chart is ready
- let the shared chart layer backfill older history

### Market Insights

Market Insights uses the same TerraFin chart, not a separate chart stack.

Its macro quick-pick flow now uses the same shared chart contract as Stock
Analysis:

- `POST /chart/api/chart-series/progressive/set` for initial seed
- `POST /chart/api/chart-series/add` for warm add
- `POST /chart/api/chart-series/remove` for warm remove

`/market-insights/api/macro-info` remains as a thin page-specific helper for
the focused header block, but the chart session itself is no longer managed by
separate Market Insights chart endpoints.

## Cache interaction

The chart layer depends on the data-layer cache strategy, especially for
yfinance-backed prices.

The important chart-facing behavior is:

- memory caches can satisfy recent or full history directly
- `yfinance_v2` stores typed on-disk artifacts under `~/.terrafin/cache/`
- recent seeds can come from the tail of a full artifact without reconstructing
  the whole dataset eagerly
- backfill uses the full artifact or a full upstream download

See [caching.md](./caching.md) for the exact cache layout.

## Debugging checklist

### Empty chart in notebook

Check that the chart page and the notebook seed request are using the same
session id. The notebook helper should open `/chart?sessionId=default`.

If env-backed data is unexpectedly missing in a notebook, remember that Jupyter
does not auto-load TerraFin's `.env` on import. TerraFin now lazy-loads `.env`
when an env-backed provider is first used, but notebook users can make startup
deterministic with `from TerraFin import configure; configure()` or
`configure(dotenv_path="/absolute/path/to/.env")`.

### Chart shows stale series after rapid page actions

Check the session id first. Then check whether the page is applying mutation
responses in sequence rather than aborting them mid-flight.

### `5Y` or `ALL` stays disabled

Inspect `historyBySeries` for the active entry. The chart only enables those
controls when the loaded span actually supports them.

### Slow warm updates

Check whether the operation is returning a mutation patch or forcing a full
snapshot rebuild. Also check indicator-cache reuse and provider cache hits.

## See also

- [interface.md](./interface.md) for route families and page modules
- [data-layer.md](./data-layer.md) for `DataFactory`, `TimeSeriesDataFrame`, and `HistoryChunk`
- [caching.md](./caching.md) for cache-manager behavior and `yfinance_v2`
