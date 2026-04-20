---
title: Interface Layer
summary: How TerraFin's FastAPI app is started, how routes are organized, and how session-scoped state works.
read_when:
  - Adding or modifying API endpoints
  - Integrating with the chart or dashboard from Python
  - Debugging session isolation or caching
  - Building or serving the frontend
---

# Interface Layer

The interface layer exposes TerraFin through one FastAPI application, six page
routes, and several API families. It lives under `src/TerraFin/interface/`.

The key design choice is that interactive state is session-scoped. Unless a
request says otherwise, TerraFin uses the `default` session.

For deployment and upstream data-usage responsibilities, see
[License & Data Rights](./legal.md).

## Server

Source: `src/TerraFin/interface/server.py`

The server owns:

- application startup and shutdown
- router registration
- cache manager lifecycle
- readiness and health endpoints
- static frontend serving

### App factory

```python
create_app(
    initial_data: TimeSeriesDataFrame | None = None,
    base_path: str = "",
) -> FastAPI
```

`create_app(...)` resets session state, registers routers, installs exception
handlers, wires the private-data cache callbacks, and mounts the frontend static
assets.

### CLI

```bash
python server.py [run|start|stop|status|restart]
```

Run these commands from `src/TerraFin/interface/`.

| Command | Behavior |
|---------|----------|
| `run` | Start in the foreground |
| `start` | Start in the background and write a PID file |
| `stop` | Stop the background process if it exists |
| `status` | Show whether the background process is running |
| `restart` | Stop and start again |

Runtime config comes from `src/TerraFin/interface/config.py`.

| Field | Default | Env var | Notes |
|-------|---------|---------|-------|
| `host` | `127.0.0.1` | `TERRAFIN_HOST` | Empty values fall back to the default |
| `port` | `8001` | `TERRAFIN_PORT` | Must be an integer in `1..65535` |
| `base_path` | `""` | `TERRAFIN_BASE_PATH` | Normalized to leading slash, no trailing slash |
| `cache_timezone` | `"UTC"` | `TERRAFIN_CACHE_TIMEZONE` | Must be a valid IANA timezone; used for cache/date-bound scheduling |

### Root routes

| Method | Path | Behaviour |
|--------|------|-----------|
| `GET` | `/` | Redirect to the dashboard page, respecting `base_path` |
| `GET` | `/health` | Liveness endpoint |
| `GET` | `/ready` | Readiness endpoint with cache-manager and private-data checks |

`/health` and `/ready` stay at the root even when `TERRAFIN_BASE_PATH` is set.
Feature routes are prefixed by the base path.

### Error handling

Errors use a uniform JSON envelope:

```json
{"error": {"code": "...", "message": "...", "request_id": "..."}}
```

`details` is included when the handler has structured extra context to return.

### Session isolation

Stateful APIs read `X-Session-ID` and default to `"default"`. Chart payloads,
chart selections, and calendar selections are all stored per session.

In browser flows, TerraFin usually generates a per-tab session id and sends it
on every chart request. Notebook and direct Python helpers intentionally use the
`default` chart session unless an explicit session id is provided.

Use the accessors in `chart/state.py` and `calendar/state.py` instead of
touching their internal storage directly.

## Page routes

| Route | Purpose |
|-------|---------|
| `/chart` | Interactive chart page |
| `/dashboard` | Watchlist, breadth, valuation, and cache status |
| `/market-insights` | Regime summary, guru portfolios, top companies |
| `/calendar` | Earnings and macro event calendar |
| `/stock` and `/stock/{ticker}` | Stock Analysis page with chart-first loading |
| `/watchlist` | Personal watchlist management page |

Each page route respects `TERRAFIN_BASE_PATH`.

---

## Chart

Source: `src/TerraFin/interface/chart/`

The chart is TerraFin's main visualization surface. It stores a session-scoped
source payload, display payload, named series, pin state, and per-series
history metadata. Stock Analysis, Market Insights, the chart page, and notebook
helpers all use this same backend chart session model.

For the full processing and management flow, see
[chart-architecture.md](./chart-architecture.md).

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/chart/api/chart-data` | Get the current display payload plus entries and `historyBySeries` |
| `POST` | `/chart/api/chart-data` | Set the current session from raw payload data and mark those series complete |
| `POST` | `/chart/api/chart-view` | Rebuild the display payload for a new view such as daily or monthly |
| `GET` | `/chart/api/chart-selection` | Read the current chart selection |
| `POST` | `/chart/api/chart-selection` | Save the current chart selection |
| `POST` | `/chart/api/chart-series/add` | Add a named series by TerraFin lookup name, seeded with recent history |
| `POST` | `/chart/api/chart-series/set` | Reset the session to one named series, seeded with recent history |
| `POST` | `/chart/api/chart-series/progressive/set` | Explicit progressive seed route for one named series |
| `POST` | `/chart/api/chart-series/progressive/backfill` | Backfill older history for a seeded series |
| `POST` | `/chart/api/chart-series/remove` | Remove a named series |
| `GET` | `/chart/api/chart-series/names` | List currently loaded named series |
| `GET` | `/chart/api/chart-series/search` | Search available indicator, index, and economic names |
| `GET` | `/chart` | Serve the chart page |

### Auto-computed indicators

When the payload contains exactly one candlestick series, TerraFin appends:

| Indicator | Default params | Indicator group |
|-----------|---------------|-----------------|
| Moving Averages | SMA 20, 60, 120, 200 | `ma-20`, `ma-60`, `ma-120`, `ma-200` |
| Bollinger Bands | window 20, ±2σ | `bb` |
| RSI | window 14, levels at 70/30 | `rsi` |
| MACD | fast 12, slow 26, signal 9 | `macd` |
| Realized Volatility | window 21 | `realized-vol` |
| Range Volatility | window 20 (Parkinson) | `range-vol` |
| Mandelbrot Fractal Dimension | windows 65, 130, 260 | `mfd` |

Indicator adapter source: `src/TerraFin/interface/chart/indicators/adapter.py`.

### Chart client (Python)

Source: `src/TerraFin/interface/chart/client.py`

| Function | Description |
|----------|-------------|
| `display_chart(df)` | Open chart in browser. Starts server if needed. Blocks. |
| `display_chart_notebook(data)` | Display in Jupyter notebook. Waits for readiness, seeds the default chart session, and returns an IFrame bound to that same session. |
| `update_chart(data, pinned=False, session_id=None)` | POST data to a running server. Returns `True` on success. |
| `get_chart_selection()` | GET the current selection from the server. |

These helpers accept `TimeSeriesDataFrame` or `list[TimeSeriesDataFrame]`.
Single OHLC series render as candlesticks; multi-series payloads render as
comparison lines.

Notebook and embedded use:

- `import TerraFin` does not auto-load `.env`
- env-backed features lazy-load `.env` on first use unless
  `TERRAFIN_DISABLE_DOTENV=1`
- for deterministic notebook or script setup, call:

```python
from TerraFin import configure

configure()
```

- if the kernel runs outside the repo root, use
  `configure(dotenv_path="/absolute/path/to/.env")`
- if you need the resolved typed settings, inspect
  `load_terrafin_config()` instead of reading env vars directly

---

## Dashboard

Source: `src/TerraFin/interface/dashboard/`

The dashboard is the main consumer of `PrivateDataService`. It mixes private
source data, cache status, and a few valuation-style summary endpoints. If the
private source is unavailable, TerraFin falls back to bundled public-safe
fixtures or empty defaults for those widgets.

Important boundary:

- dashboard/widget payloads are not automatically chart-series contracts
- if a private-source feature needs optimized chart serving, promote it into
  the data layer as a `TimeSeriesDataFrame` series first
- otherwise keep it as a widget payload in `PrivateDataService`

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard/api/watchlist` | Watchlist snapshot (symbols, names, moves) |
| `GET` | `/dashboard/api/market-breadth` | Market breadth metrics (label, value, tone) |
| `GET` | `/dashboard/api/trailing-forward-pe-spread` | Trailing minus forward P/E spread summary and history |
| `GET` | `/dashboard/api/cape` | Current CAPE snapshot |
| `GET` | `/dashboard/api/fear-greed` | Fear and Greed summary if available |
| `GET` | `/dashboard/api/cache-status` | Status of all registered cache sources |
| `POST` | `/dashboard/api/cache-refresh` | Refresh cache sources (`?force=bool`) |

The practical rule for future private-source additions is:

- chart/search/progressive use case -> build a private series contract first
  Examples: `Fear & Greed`, `Net Breadth`
- dashboard-only use case -> keep a private widget payload

---

## Calendar

Source: `src/TerraFin/interface/calendar/`

The calendar merges private calendar data and TerraFin-fetched macro events into
one session-aware view. Events are categorized as `earning`, `macro`, or
`event`. This page remains usable in public/demo mode because earnings and
macro events are still fetched through TerraFin's local provider paths, while
private calendar events use the same fallback chain as the dashboard. As with
the dashboard, a warmed private-source cache is not a substitute public data
source.

### API endpoints

| Method | Path | Query params | Description |
|--------|------|-------------|-------------|
| `GET` | `/calendar/api/events` | `month`, `year`, `categories`, `limit` | Filtered events |
| `POST` | `/calendar/api/events` | — | Upsert events |
| `GET` | `/calendar/api/selection` | — | Get selection state |
| `POST` | `/calendar/api/selection` | — | Set selection state |

---

## Market Insights

Source: `src/TerraFin/interface/market_insights/`

Market insights provides higher-level market context and institutional
positioning. The regime endpoint is currently a static placeholder response;
guru portfolio data is fully backed by the SEC EDGAR provider.
The top-companies widget also degrades cleanly when the private source is not
configured.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/market-insights/api/regime` | Market regime (placeholder) |
| `GET` | `/market-insights/api/macro-info` | Macro instrument summary (`?name=`) |
| `GET` | `/market-insights/api/investor-positioning/gurus` | List available guru names |
| `GET` | `/market-insights/api/investor-positioning/holdings` | Guru portfolio (`?guru=`) |
| `GET` | `/market-insights/api/top-companies` | Private-source top-companies snapshot |

Market Insights now uses the shared TerraFin chart routes directly:
- `POST /chart/api/chart-series/progressive/set` for initial seed
- `POST /chart/api/chart-series/add` for warm add
- `POST /chart/api/chart-series/remove` for warm remove

`macro-info` is the page-specific helper for the focused header block. The
chart session itself is no longer managed through separate `macro-focus`
routes.

---

## Stock Analysis

Source: `src/TerraFin/interface/stock/`

Stock Analysis combines a chart-first page route with a small API family for
company profile, earnings history, financials, SEC filings, and search routing.
The page itself uses the shared TerraFin chart session and progressive
`3Y -> full` history loading described in
[chart-architecture.md](./chart-architecture.md).

### Page routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/stock` and `/stock/` | Stock landing page |
| `GET` | `/stock/{ticker}` | Stock Analysis page for one ticker |

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/stock/api/company-info` | Company profile and price summary (`?ticker=`) |
| `GET` | `/stock/api/earnings` | Earnings history (`?ticker=`) |
| `GET` | `/stock/api/financials` | Financial statements (`?ticker=`, `statement=`, `period=`) |
| `GET` | `/stock/api/fcf-history` | Annual FCF/share history + 3yr-avg/latest-annual/TTM candidates and the source the `auto` cascade would pick (`?ticker=`, `years=10`). See [api-reference.md](./api-reference.md#stock-analysis). |
| `GET` / `POST` | `/stock/api/dcf` | Forward DCF. POST body accepts `projectionYears` (5/10/15), `fcfBaseSource` (`auto`/`3yr_avg`/`ttm`/`latest_annual`), and turnaround inputs (`breakevenYear`, `breakevenCashFlowPerShare`, `postBreakevenGrowthPct`) on top of the base overrides. |
| `GET` / `POST` | `/stock/api/reverse-dcf` | Reverse DCF (market-implied growth). POST accepts `projectionYears`, `growthProfile`, base overrides. |
| `GET` | `/stock/api/beta-estimate` | TerraFin's `beta_5y_monthly` estimate against the mapped benchmark. |
| `GET` | `/stock/api/filings` | Recent 10-K / 10-Q / 8-K list with EDGAR URLs (`?ticker=`, `limit=`) |
| `GET` | `/stock/api/filing-document` | Parsed markdown + TOC for one filing (`?ticker=`, `accession=`, `primaryDocument=`, `form=`, `includeImages=`) |
| `GET` | `/resolve-ticker` | Resolve free-form search into `/stock/...` or `/market-insights?...` |

### Page layout (`/stock/{ticker}`)

The stock-detail page is a vertical stack of sections. Row 2 (Earnings + FCF
history) is height-capped on desktop so the page stays scannable; longer
content scrolls inside the cards rather than expanding them.

| Row | Left card | Right card |
|---|---|---|
| 1 | **Market Chart** (price history + indicators) | **Overview & Valuation** (company profile, price context, key metrics) |
| 2 *(capped at 280px desktop)* | **Earnings History** (EPS estimate / reported / surprise table, vertical scroll) | **FCF / Share History** (annual FCF/share bars, latest-TTM right-gutter callout, 3yr-Avg dashed reference line) |
| 3 | **DCF Valuation** (input form + Projected FCF chart at the bottom) | **DCF Valuation Result** (intrinsic value tiles, sensitivity heatmap, projection table) |
| 4 | **Reverse DCF** *(toggled, collapsed by default)* — when expanded, shows input + result side-by-side mirroring Row 3. The Reverse DCF Result card carries its own Projected FCF chart at the bottom. |
| 5 | **SEC Filings** (US-listed issuers only; auto-hidden otherwise). |

### DCF Valuation card

The forward-DCF input card hosts:

- **Forecast Horizon** — segmented control (`5` / `10` / `15` years) and a
  **Turnaround Mode** checkbox. Turnaround mode swaps `Base Growth %` for
  `Breakeven Year` / `Breakeven FCF / Share` / `Post-Breakeven Growth %`
  inputs.
- **FCF Base Source** — segmented control (`Auto` / `3yr Avg` / `TTM` /
  `Latest Annual`). Selecting a source auto-fills the *Base FCF / Share*
  field with the corresponding candidate value (read from
  `/stock/api/fcf-history`'s `candidates`). If the user types over the
  auto-filled value, a `↺ Revert to {source} ($X)` chip surfaces under the
  field; clicking it restores the source's value.
- **Model Inputs grid** — Base FCF / Share, Base Growth %, Terminal Growth %,
  Beta (with a `Compute Beta` button that runs `beta_5y_monthly`), Equity
  Risk Premium %.
- **Explain inputs** toggle (top-right of the card header). OFF by default;
  hides every "i" icon for clean entry by power users. ON reveals all input
  hints. State is persisted in `localStorage` (`terrafin.dcf.explainInputs`)
  via the `useExplainInputs` hook. Implemented through an
  `InfoHintVisibilityContext` provider — the `InfoHint` component reads the
  context and returns `null` when hidden.
- **Projected FCF / Share chart** — appears at the bottom after running DCF.
  Bars for ≤15-year horizons; line + shaded band (bear/bull envelope, base
  line) for longer horizons. In bar mode with multi-scenario data, each base
  bar carries a vertical whisker from bear to bull with colored end-caps so
  the scenario spread is visible. The Reverse DCF Result card uses the same
  component (single-scenario, implied-schedule label).

### FCF / Share History chart

`FcfHistoryChart` renders historical annual FCF/share as filled bars
(green/red), the latest TTM as a small blue pill in the right gutter
connected by a dashed leader line to the last annual bar's top, and the 3yr
Avg as a teal dashed horizontal line with a halo'd inline label at the
left-inside of the plot. Y-axis uses nice-number ticks tightly clipped to the
data range (no forced 0 inclusion when all values share a sign). Hover on any
bar / TTM marker / 3yr Avg line shows a small white tooltip with the value.

### SEC Filings panel

The `/stock/{ticker}` page includes a **SEC Filings** card for every US-listed
issuer. The card is hidden automatically for tickers without an SEC CIK (e.g.
KOSPI / TSE / HKEX issuers) so non-US pages stay uncluttered.

For supported tickers the card surfaces:

- a form dropdown derived from `df.form.unique()` (covers 10-K, 10-Q,
  amendments, 8-K, 20-F, 40-F, etc.);
- a chronological filing list with a **View on EDGAR** link per row pointing
  at the SEC inline-XBRL viewer (`/ix?doc=/Archives/...`);
- a reader that opens inline below the list, with:
    - a two-level accordion preserving Part I / Part II as outer collapsibles
      and Items (Item 1, Item 2 MD&A, …) as nested inner collapsibles;
    - a compact custom markdown renderer that handles our `parse_sec_filing`
      output (`##`/`###` headings, paragraphs, GFM pipe tables, blockquote
      fallbacks, inline-image placeholders) without pulling in a general
      markdown dep;
    - a "View source on EDGAR" pill in the reader header.

The parsed markdown is cached for 30 days via the shared `sec_filings`
CacheManager namespace (see [caching.md](./caching.md)), so reopening a filing
is free across sessions. See [data-layer.md](./data-layer.md) for the
underlying `parse_sec_filing` / `build_toc` / `get_sec_data` helpers.

### Agent integration

When the user opens a filing, the panel publishes the currently-focused
section to the agent side-panel via `publishAgentViewContext`. The `selection`
carries `ticker`, `form`, `accession`, `primaryDocument`, `sectionSlug`,
`sectionTitle`, a bounded `sectionExcerpt` (≤ 4 KB), and EDGAR URLs. The
hosted agent's `current_view_context` tool reads this payload, and the agent
can call `sec_filings`, `sec_filing_document`, or `sec_filing_section` to
fetch the full body when the excerpt is not enough (e.g. "summarize their
business" on a 10-Q will trigger a cross-filing pivot to the most recent
10-K's Item 1. Business). See the `sec_filings` row in the common-tasks
table at [agent/usage.md](./agent/usage.md#common-tasks).

For the view-context pipeline (how `publishAgentViewContext` reaches the
agent, session/context identity, and how `current_view_context()` reads
the current panel), see [agent/architecture.md](./agent/architecture.md)
and [agent/hosted-runtime.md](./agent/hosted-runtime.md).

---

## Watchlist

Source: `src/TerraFin/interface/watchlist/`

The watchlist page is a dedicated personal-management surface. It reuses the
dashboard watchlist API family rather than exposing a separate `/watchlist/api`
namespace.

### Page routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/watchlist` and `/watchlist/` | Personal watchlist page |

---

## Agent API

Source: `src/TerraFin/interface/agent/data_routes.py`

The Agent API exposes TerraFin's optimized processing pipeline for programmatic
consumers. It is backed by the shared service in `src/TerraFin/agent/service.py`
rather than a separate simplified path.

That means:

- market and macro requests use the same progressive-history aware data contract
- view transforms match the chart stack
- indicator computation matches chart indicator math
- every response includes top-level `processing` metadata

For most consumers, prefer the Python client in `src/TerraFin/agent/client.py`
or the `terrafin-agent` CLI over calling raw routes directly.

### API endpoints

| Method | Path | Query Params | Description |
|--------|------|-------------|-------------|
| `GET` | `/agent/api/resolve` | `q` | Resolve a free-form name into TerraFin's stock or macro path |
| `GET` | `/agent/api/market-data` | `ticker`, `depth`, `view` | Market or macro series plus processing metadata |
| `GET` | `/agent/api/indicators` | `ticker`, `indicators`, `depth`, `view` | Raw indicator results computed from the shared processing pipeline |
| `GET` | `/agent/api/market-snapshot` | `ticker`, `depth`, `view` | Price action + indicator summaries + breadth + watchlist |
| `GET` | `/agent/api/company` | `ticker` | Company profile and price summary |
| `GET` | `/agent/api/earnings` | `ticker` | Earnings history |
| `GET` | `/agent/api/financials` | `ticker`, `statement`, `period` | Financial statement table |
| `GET` | `/agent/api/portfolio` | `guru` | Guru portfolio holdings |
| `GET` | `/agent/api/economic` | `indicators` (comma-separated FRED codes) | Economic indicator series |
| `GET` | `/agent/api/macro-focus` | `name`, `depth`, `view` | Macro instrument summary plus series data |
| `GET` | `/agent/api/lppl` | `name`, `depth`, `view` | LPPL bubble-confidence summary from the shared agent/chart processing pipeline |
| `GET` | `/agent/api/calendar` | `year`, `month`, `categories`, `limit` | Calendar events with processing metadata |
| `GET` | `/agent/api/runtime/agents` | - | Hosted runtime agent catalog plus exposed tools and runtime readiness metadata |
| `POST` | `/agent/api/runtime/sessions` | body: `agentName`, optional `sessionId`, `systemPrompt`, `metadata` | Create a hosted runtime conversation session when the selected hosted model is configured |
| `GET` | `/agent/api/runtime/sessions` | - | List hosted sessions from the transcript-derived session index |
| `GET` | `/agent/api/runtime/sessions/{session_id}` | - | Read hosted runtime session state, transcript-derived message history, and tools |
| `DELETE` | `/agent/api/runtime/sessions/{session_id}` | - | Archive a hosted session transcript and remove it from active history |
| `POST` | `/agent/api/runtime/sessions/{session_id}/messages` | body: `content` | Append a user turn and run the hosted model/tool loop |
| `GET` | `/agent/api/runtime/sessions/{session_id}/approvals` | - | List approval requests for a hosted session |
| `GET` | `/agent/api/runtime/tasks/{task_id}` | - | Read a hosted background task |
| `POST` | `/agent/api/runtime/tasks/{task_id}/cancel` | - | Cancel a hosted background task |
| `GET` | `/agent/api/runtime/approvals/{approval_id}` | - | Read one approval request |
| `POST` | `/agent/api/runtime/approvals/{approval_id}/approve` | body: optional `note` | Approve a pending request |
| `POST` | `/agent/api/runtime/approvals/{approval_id}/deny` | body: optional `note` | Deny a pending request |

Time-series endpoints use `depth=auto|recent|full`.

- `auto` starts with the optimized recent/progressive path for market and macro series
- `full` forces complete-history loading from the start

LPPL route note:
`/agent/api/lppl` uses TerraFin's calibrated default LPPL scan from the shared
analytics helper. The full article-style 750→50 ladder is kept as a notebook /
research option via `lppl(..., n_windows=None)` and is not exposed over HTTP.

Runtime route note:
`/agent/api/runtime/*` is the stateful hosted-agent family. It uses the same
shared capability kernel as the Python client, CLI, and stateless
`/agent/api/*` routes, but persists conversation history through append-only
local transcripts plus a transcript-derived session index. Tasks, approvals,
audit, and published view context remain in the hosted runtime store. Hosted
model execution is provider-driven rather than OpenAI-only.

Supported `view` values:

- `daily`
- `weekly`
- `monthly`
- `yearly`

Supported indicator names for `/agent/api/indicators`:

- `rsi`
- `macd`
- `bb`
- `sma_N` such as `sma_20`
- `realized_vol`
- `range_vol`
- `mfd`
- `mfd_65`
- `mfd_130`
- `mfd_260`

Unknown indicator names are skipped and returned in the `unknown` field.

For chart overlays, TerraFin shows the medium-horizon `MFD 130` line by
default to preserve readability. The agent/API still exposes the explicit
`mfd_65`, `mfd_130`, and `mfd_260` series plus the aggregate `mfd` response.

### Python client and CLI

Preferred public entrypoints:

- `TerraFin.agent.TerraFinAgentClient`
- `terrafin-agent`

Both wrap the same service layer and normalized response shapes exposed by the
HTTP API.

### OpenAPI

The FastAPI schema is available at `/openapi.json`. The agent routes use
explicit response models so generic agents can inspect the contract without
reverse-engineering route handlers.

---

## Frontend

Source: `src/TerraFin/interface/frontend/`

The frontend is a React SPA. Built assets live in `frontend/build/` and are
served directly by FastAPI, so Node.js is only needed when you are editing the
frontend itself.

### Building from source

```bash
cd src/TerraFin/interface/frontend
npm install
npm run build
```

Do not commit `node_modules/`. The built output is committed so the server can
run in environments without a frontend toolchain.

## See also

- [data-layer.md](./data-layer.md) for the provider and output model underneath these APIs
- [chart-architecture.md](./chart-architecture.md) for chart sessions, mutations, progressive history, and notebook flow
- [feature-integration.md](./feature-integration.md) for the cross-layer checklist when exposing a new feature through UI or APIs
- [analytics.md](./analytics.md) for the indicator functions used by chart and agent routes
- [caching.md](./caching.md) for cache-manager behavior exposed through the dashboard
