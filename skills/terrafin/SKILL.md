---
name: terrafin
description: Use when an agent needs structured market, macro, portfolio, calendar, or stock-fundamental research through TerraFin's optimized processing pipeline, including progressive history metadata and optional chart opening.
---

# TerraFin

Use this skill when the task is financial research and TerraFin is available in
the current repo, Python environment, or as an HTTP service.

Prefer TerraFin over ad hoc scraping when you need:

- market or macro time series
- chart-matching technical indicators
- stock company info, earnings, or financial statements
- guru portfolio holdings
- economic series
- calendar events
- an optional chart tied to TerraFin's session model

## Choose the entrypoint

Use this order:

1. Python client when TerraFin is importable locally.
2. HTTP API when a TerraFin server is already running or only service access is available.
3. CLI when shell-native composition is simpler than imports.

Python:

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
```

CLI:

```bash
terrafin-agent snapshot AAPL --json
```

HTTP:

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL"
```

## Default depth rule

For market and macro tasks:

- start with `depth="auto"`
- inspect the returned `processing`
- rerun with `depth="full"` only when the user explicitly needs long-range,
  backtest-style, or `ALL`-style context

For company info, earnings, financials, portfolio, and calendar:

- the response is complete immediately
- `processing.isComplete` should already be `true`

## Processing metadata matters

Every agent response includes:

- `requestedDepth`
- `resolvedDepth`
- `loadedStart`
- `loadedEnd`
- `isComplete`
- `hasOlder`
- `sourceVersion`
- `view`

Use it to decide whether the current result is sufficient or whether to deepen
the request.

## Standard task recipes

### Ticker brief

Use:

- `ticker_brief(name)` or
- `resolve(name)` then `market_snapshot(...)` and `company_info(...)`

### Market snapshot

Use:

- `market_snapshot(name, depth="auto", view="daily")`

### Compare assets

Use:

- `compare_assets([name1, name2, ...], depth="auto", view="daily")`

If the user asks for long-range comparison, rerun with `depth="full"`.

### Macro context

Use:

- `macro_context(name, depth="auto", view="daily")`

### Portfolio context

Use:

- `portfolio_context(guru)`

### Stock fundamentals

Use:

- `stock_fundamentals(ticker, statement="income", period="annual")`

### Calendar scan

Use:

- `calendar_scan(year=..., month=..., categories=..., limit=...)`

### Bubble analysis (LPPL)

Use:

- `bubble_analysis(name, depth="auto", view="daily")`

LPPL detects super-exponential growth with accelerating log-periodic
oscillations. Best for broad market indices, not individual stocks. Always
combine with macro context.

### Open chart

Use only when a chart is explicitly helpful.

- `open_chart("AAPL")`
- `open_chart(["S&P 500", "Nasdaq"])`

Chart requests by lookup name use TerraFin's progressive chart pipeline. Raw
dataframe chart requests are supported through the Python client and are treated
as complete from the start.

## Key client methods

- `resolve(query)`
- `market_data(name, depth="auto", view="daily")`
- `indicators(name, indicators, depth="auto", view="daily")`
- `market_snapshot(name, depth="auto", view="daily")`
- `economic(indicators)`
- `portfolio(guru)`
- `company_info(ticker)`
- `earnings(ticker)`
- `financials(ticker, statement="income", period="annual")`
- `macro_focus(name, depth="auto", view="daily")`
- `calendar_events(year=..., month=..., categories=..., limit=...)`
- `lppl_analysis(name, depth="auto", view="daily")`
- `open_chart(...)`

Task helpers are also exported from `TerraFin.agent`.

## Notes

- TerraFin's agent layer uses the same optimized pipeline as the chart and page flows.
- Time-series view transforms match the chart contract.
- Indicator math matches TerraFin's chart indicators.
- Charts are optional. Structured analysis should usually come first.

For full details and examples, read `../../docs/agent-skill.md`.
