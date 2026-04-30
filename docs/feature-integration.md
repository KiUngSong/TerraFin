---
title: Feature Integration Guide
summary: Where new TerraFin logic should live and which UI, chart, agent, docs, and test surfaces must be updated when a feature becomes public.
read_when:
  - Adding a new indicator, market series, macro series, or research endpoint
  - Deciding whether logic belongs in data, analytics, interface, or agent layers
  - Making sure a public feature is wired through UI, chart, and agent surfaces consistently
---

# Feature Integration Guide

TerraFin works best when new features follow one rule:

- put the core logic in the narrowest reusable layer
- connect public surfaces as thin wrappers around that logic

This guide exists to answer two questions:

1. Where should the real logic live?
2. What else must be updated when the feature becomes public?

## The ownership rule

Use this order of responsibility.

### 1. Data layer owns acquisition and normalization

Put the feature here when it is about:

- fetching a new market, macro, or economic series
- mapping a new name such as `RRP` or `Reverse Repo`
- progressive history support
- caching behavior
- normalization into `TimeSeriesDataFrame`

Typical files:

- `src/TerraFin/data/providers/...`
- `src/TerraFin/data/factory.py`
- registries under `src/TerraFin/data/providers/market/` or `src/TerraFin/data/providers/economic/`

Important private-data rule:

- if a private-source feature needs TerraFin's optimized chart serving, it must
  be normalized into `TimeSeriesDataFrame`
- if it does not normalize into `TimeSeriesDataFrame`, it stays a widget/card
  payload and should not be treated as part of the progressive chart pipeline

### 2. Analytics layer owns reusable computation

Put the feature here when it is about:

- a new indicator formula
- a reusable analysis function
- math that should be shared by chart and agent consumers

Typical files:

- `src/TerraFin/analytics/analysis/...`
- `src/TerraFin/interface/chart/indicators/adapter.py` for product-facing overlay output

### 3. Interface routes own presentation-specific composition

Put the feature here when it is about:

- page-specific response shapes
- chart session mutation
- combining existing data or analytics pieces into a page payload
- resolving user-facing page actions

Typical files:

- `src/TerraFin/interface/chart/...`
- `src/TerraFin/interface/market_insights/...`
- `src/TerraFin/interface/stock/...`
- `src/TerraFin/interface/dashboard/...`
- `src/TerraFin/interface/calendar/...`

Important rule:

- route handlers should compose shared logic
- route handlers should not become the only place where core business logic exists

### 4. Agent layer owns structured agent consumption

Put the feature here when it is about:

- exposing a public capability to agents
- sharing the optimized processing pipeline with programmatic consumers
- adding agent-ready response models, client methods, CLI commands, or skill guidance

Typical files:

- `src/TerraFin/agent/service.py`
- `src/TerraFin/agent/models.py`
- `src/TerraFin/agent/client.py`
- `src/TerraFin/agent/tasks.py`
- `src/TerraFin/agent/cli.py`
- `src/TerraFin/interface/agent/data_routes.py`

Important rule:

- the agent layer should wrap the real feature
- it should not reimplement the feature in a private parallel path

## Verification assets rule

Keep verification artifacts separated by purpose.

Use `tests/` when:

- the coverage is automated
- the file is part of normal `pytest` runs
- the artifact should block regressions in CI

Rules for `tests/`:

- use real `test_*.py` files
- do not place `.ipynb` files under `tests/`

Use `notebooks/` when:

- the artifact is a human-guided demo
- the flow is exploratory or instructional
- the notebook is useful for manual research, walkthroughs, or visual checks

Rules for `notebooks/`:

- group notebooks by domain such as `notebooks/analytics/` or `notebooks/interface/`
- do not use a misleading `test_` filename prefix
- if a notebook scenario becomes required regression coverage, convert it into a real pytest case under `tests/`

## Feature types and expected wiring

### A. New time-series name or macro/market series

Examples:

- `RRP`
- a new treasury series
- a new index alias

Core work:

1. Add provider or registry mapping in the data layer.
2. Make sure `DataFactory.get(...)` can resolve the name.
3. If it should support progressive history, wire `get_recent_history(...)` and full-history behavior correctly.

Then check these public surfaces:

- chart search and named-series routes
- Market Insights quick-picks or Stock Analysis if relevant
- agent service methods such as `market_data`, `market_snapshot`, or `macro_focus`
- agent docs and skill task guidance if the feature is intended for general research use

### A1. Adding a new private series or data type — the contract-first flow

Every new data type follows the same four steps. There is no "wrapper module"
shortcut and providers do not invent their own response shapes:

1. Define a contract in `src/TerraFin/data/contracts/` if no existing one fits
   (see [Data Layer › Contracts](./data-layer.md#contracts) for the canonical
   list).
2. Write the provider so it returns that contract — never an ad-hoc dict.
3. Route the lookup through `DataFactory` so callers go through the single
   facade.
4. Wire caching through `CacheManager` rather than provider-local caches.

For private-source data, the same flow applies: the `private_access` HTTP
server in the sibling `~/Downloads/work/DataFactory` repo must shape its
responses to the TerraFin contracts; the contracts in this repo are the
source of truth.

### A2. Private-source series vs private widget

This distinction matters for scalability.

Use `PrivateSeries` when:

- the feature should be searchable as a chart series
- the feature should participate in `DataFactory`
- the feature should use `get_recent_history(...)` and backfill
- the feature may later be used by chart, Market Insights, Stock Analysis, or
  the agent pipeline as time-series data

Requirements for `PrivateSeries`:

- normalize to `TimeSeriesDataFrame`
- expose a stable name through the data layer
- use the same cache/progressive-history contract as other chartable series
- derive dashboard or summary views from the cached series artifact when practical

Use `PrivateWidget` when:

- the feature is only a dashboard/info payload
- the payload is not naturally time-series shaped
- chart/backfill/search support is not required

Rules for `PrivateWidget`:

- keep a simple cached JSON payload
- do not force it into the chart pipeline
- do not add chart-specific logic around it unless the product decision changes

This is the main anti-sprawl rule for private data:

- chart-optimized private data must enter TerraFin as `TimeSeriesDataFrame`
- widget-only private data must stay outside the chart/progressive contract

### B. New indicator

Examples:

- a new moving-average family
- `RRP spread`
- a new oscillator

Core work:

1. Add the formula in `src/TerraFin/analytics/analysis/...` when it is reusable math.
2. Adapt it into chart overlay format if it should appear on TerraFin charts.

Then check these public surfaces:

- chart indicator adapter and any auto-overlay logic
- chart search or discovery if the user can add it directly
- `TerraFin.agent.service` indicator computation
- `/agent/api/indicators` contract and docs
- CLI help text and skill docs if it becomes a standard agent-facing indicator

### C. New stock or fundamentals feature

Examples:

- analyst revisions
- valuation summary
- a new statement view

Core work:

1. Put raw fetching in the data/provider layer if it is reusable.
2. Put formatting/composition helpers in the stock module if they are page-specific.

Then check these public surfaces:

- Stock Analysis routes and frontend components
- agent service and agent routes if this should be queryable by agents
- docs if it becomes a supported public research task

### D. Pure UI-only feature

Examples:

- card layout change
- toolbar adjustment
- animation

Core work:

- frontend component or page only

Usually not required:

- agent pipeline changes
- data layer changes

But still check:

- docs if the public workflow materially changed
- tests if interaction behavior changed

## The public-surface checklist

When a feature becomes public, check each box deliberately.

### Data

- provider or registry added
- `DataFactory` resolution updated
- cache and normalization behavior updated
- progressive-history support decided

### Chart and UI

- chart routes updated if the feature is chartable
- page-specific routes updated where relevant
- frontend search, controls, labels, and cards updated
- empty, loading, and error states still make sense

### Agent pipeline

- `src/TerraFin/agent/service.py` updated if the feature should be available to agents
- `models.py` updated if the public response shape changed
- `client.py` updated if there is a new stable method or parameter
- `tasks.py` updated if the feature becomes part of a standard task recipe
- `cli.py` updated if the feature deserves first-class shell access
- `tool_contracts.py` schema updated for any new params (input enums, ranges, required fields)
- `runtime.py` capability registration with a description that names the new behaviour (the LLM reads this)
- `interface/agent/data_routes.py` updated if HTTP exposure is required (every internal capability should have a parity `/agent/api/*` route — external HTTP-only agents depend on it)
- `src/TerraFin/agent/personas/*.yaml` updated if the capability should be persona-callable (Buffett / Marks / Druckenmiller). YAML allowlists are the **single source of truth** — no hidden override layer.

### Skill and docs

- `docs/agent/usage.md` updated if agent usage changed (recipe / disclosure prose only — the route summary table is auto-generated; see below)
- `skills/terrafin/SKILL.md` recipe added / updated for the new feature (recipe prose only — the "Key client methods" list is auto-generated)
- `python scripts/generate-agent-artefacts.py` run to refresh the sentinel-bounded sections in SKILL.md and `usage.md`. CI guard: `pytest tests/agent/test_generated_artefacts_match.py` fails if you forget
- `docs/interface.md`, `docs/data-layer.md`, `docs/chart-architecture.md`, or `docs/analytics.md` updated where appropriate
- `README.md` updated if the feature changes the public product story

### Tests

- data/provider tests
- route contract tests
- agent service/client/CLI tests if agent-visible
- frontend tests where practical, or at least a build/runtime check for UI work

## Decision rule for agent updates

When adding something like `RRP`, ask:

- Is this now part of TerraFin's supported research surface?

If yes:

- the agent pipeline should be updated too

If no:

- it can stay internal to the data or UI layer for now

This is the main anti-drift rule:

- public research capability should not exist only in the UI
- public research capability should not exist only in the agent path

## Example: adding `RRP`

A good implementation order would be:

1. Add `RRP` resolution in the data layer.
2. Confirm `DataFactory.get("RRP")` returns a normalized `TimeSeriesDataFrame`.
3. Decide whether `RRP` belongs in macro or index search and Market Insights.
4. If `RRP` should be chartable, ensure chart routes and search can resolve it.
5. If agents should analyze it, make sure `market_data`, `market_snapshot`, or `macro_focus` can use it through the shared service.
6. Update the skill and docs if `RRP` is something agents should know to use.
7. Add tests at the data and agent/interface levels.

## Example: private-source `Fear & Greed` vs `CAPE`

`Fear & Greed` is a good example of why this rule exists.

- as a dashboard widget, it needs a latest-score payload
- as a chartable series, it needs `TimeSeriesDataFrame` plus recent/backfill behavior

The scalable pattern is:

- define one private series contract for the chartable time series
- derive widget/card payloads from that series cache when possible

`Net Breadth` now follows this pattern too: it remains a dashboard metric, but
its chart/search exposure comes from a private series contract rather than from
the widget payload.

The same rule would apply if `CAPE` or `Trailing-Forward P/E Spread` become
first-class chart series:

- once they need optimized chart serving, they should be treated as
  `PrivateSeries`
- until then, they can stay widget-oriented payloads

## Example: DCF turnaround mode (worked end-to-end)

A real recent feature that touched every layer. Use this as a template when
adding similar valuation/fundamental capabilities.

The goal: let users value companies whose current FCF is negative but whose
thesis is a future turn (MOH, SK Hynix during cycle bottoms, biotech,
restructuring stories). The single-base × growth-curve DCF model gates these
out at the `base_cash_flow_per_share <= 0 → insufficient_data` check, so the
existing DCF cannot answer the user's question.

Layer-by-layer landing zone:

| Layer | What changed | File(s) |
|---|---|---|
| Analytics | Added `_build_turnaround_schedule` (linear interp pre-breakeven; compounded post-breakeven fading to terminal). Added `_select_stock_fcf_base` selector (auto / 3yr_avg / ttm / latest_annual cascade). Added `_three_year_avg_fcf`, `_latest_annual_fcf`, `_quarterly_ttm_fcf` helpers. | `src/TerraFin/analytics/analysis/fundamental/dcf/inputs.py` |
| Analytics | New override fields (`fcf_base_source`, `breakeven_year`, `breakeven_cash_flow_per_share`, `post_breakeven_growth_pct`) on the model. | `src/TerraFin/analytics/analysis/fundamental/dcf/models.py` |
| Analytics | Presenter switches to the explicit-schedule path when turnaround fields are set; bear/base/bull scenarios apply YoY shifts to the schedule. | `src/TerraFin/analytics/analysis/fundamental/dcf/presenters.py` |
| Interface | `POST /stock/api/dcf` accepts the new fields via `StockDCFRequest`. | `src/TerraFin/interface/valuation_models.py`, `src/TerraFin/interface/stock/data_routes.py` |
| Interface | New `/stock/api/fcf-history` endpoint for the FCF Base Source picker (returns 3yr-avg / latest-annual / TTM candidates + which one `auto` picks). | `src/TerraFin/interface/stock/data_routes.py`, `src/TerraFin/interface/stock/payloads.py` |
| Frontend | DCF Workbench: Forecast Horizon segmented control, Turnaround Mode toggle, FCF Base Source segmented control with auto-fill + revert chip, Explain inputs toggle. | `src/TerraFin/interface/frontend/src/dcf/DcfWorkbench.tsx` |
| Frontend | New `FcfHistoryChart` (right-gutter TTM callout, 3yr Avg dashed line) and `ProjectedFcfChart` (bar / line+band based on horizon, bear/bull whiskers, hover tooltips). | `src/TerraFin/interface/frontend/src/stock/components/{FcfHistoryChart,ProjectedFcfChart}.tsx` |
| Agent service | `valuation()` accepts `projection_years`, `fcf_base_source`, and the three turnaround fields as keyword args. | `src/TerraFin/agent/service.py` |
| Agent runtime | `valuation` capability description rewritten to teach the LLM when to use turnaround mode. Schema for new params in `tool_contracts.py`. | `src/TerraFin/agent/runtime.py`, `src/TerraFin/agent/tool_contracts.py` |
| Agent HTTP | `GET /agent/api/valuation` and `/agent/api/fcf-history` HTTP routes (parity with internal tool). | `src/TerraFin/interface/agent/data_routes.py` |
| Persona | Druckenmiller / Marks / Buffett persona YAML allowlists keep `valuation` accessible (the hidden broad-market override layer was deleted in this batch — YAML is now the single source of truth). | `src/TerraFin/agent/personas/*.yaml` |
| Skill | New "DCF turnaround mode" recipe in SKILL.md with a copy-paste MOH example. | `skills/terrafin/SKILL.md` |
| Docs | Turnaround math + base FCF source cascade in Analytics Notes. New POST fields documented in API Reference. New stock page layout + DCF Workbench controls in Interface Overview. | `docs/analytics-notes.md`, `docs/api-reference.md`, `docs/interface.md` |
| View context | Frontend publishes `turnaroundMode`, `breakevenYear`, etc. through the existing `publishAgentViewContext` so `current_view_context()` already exposes them — no separate work. | `src/TerraFin/interface/frontend/src/dcf/DcfWorkbench.tsx` (sanitizeStockFormState) |
| Tests | Backend: `_build_turnaround_schedule` unit tests, `_select_stock_fcf_base` cascade tests, API route accepts override tests. Agent service test stub updated to pass kwargs through. Frontend: typecheck + build. | `tests/analytics/test_dcf_inputs.py`, `tests/interface/test_dcf_api.py`, `tests/agent/test_service.py` |

The single most important discipline: when you add a backend capability,
always land the parity `/agent/api/*` route in the same PR. External agents
that only use the HTTP transport otherwise can't see the feature, and the
SKILL.md instruction "every capability has a parity HTTP route" stops being
true.

## Practical shortcut

If you are unsure where new logic belongs:

- put raw fetching and normalization in data
- put reusable math in analytics
- put session, view, and page composition in interface
- put structured programmatic exposure in agent

That separation keeps TerraFin fast to extend without creating duplicate logic paths.

## See also

- [data-layer.md](./data-layer.md)
- [analytics.md](./analytics.md)
- [interface.md](./interface.md)
- [chart-architecture.md](./chart-architecture.md)
- [agent/index.md](./agent/index.md)
- [agent/usage.md](./agent/usage.md)
- [agent/architecture.md](./agent/architecture.md)
- [agent/hosted-runtime.md](./agent/hosted-runtime.md)
