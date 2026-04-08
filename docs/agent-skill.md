---
title: Agent Skill
summary: How to use TerraFin from Python, CLI, or HTTP for agent-driven research workflows.
read_when:
  - Using TerraFin as a reusable agent tool
  - Choosing between Python, CLI, and HTTP transport
  - Interpreting `processing` metadata
  - Mapping common research tasks to TerraFin entrypoints
---

# TerraFin as an Agent Tool

TerraFin is most useful for agents when it stays on the same processing path as
the product itself.

That means:

- market and macro requests share the progressive-history aware contract
- view transforms match the chart stack
- indicator math matches the chart indicators
- every response includes `processing` so an agent can decide whether to rerun
  with deeper history

If you are maintaining those surfaces, use [agent-runtime.md](./agent-runtime.md).
This document is the usage guide.

## What TerraFin is good at

Use TerraFin when you need:

- market or macro time series
- chart-matching technical indicators
- company info, earnings, or financial statements
- guru portfolio holdings
- calendar events
- optional chart opening tied to TerraFin's chart/session model

## Choose an entrypoint

| Entry point | Use it when... |
|-------------|----------------|
| Python client | TerraFin is importable locally and low-latency access is best |
| HTTP API | TerraFin is already running as a service or only API access is available |
| CLI | Shell-native composition is easier than Python imports |
| Skill artifact | Another agent environment needs portable usage instructions |

### Python client

Source: `src/TerraFin/agent/client.py`

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
snapshot = client.market_snapshot("AAPL")
```

### CLI

Console script: `terrafin-agent`

```bash
terrafin-agent snapshot AAPL --json
terrafin-agent financials AAPL --statement income --period annual --json
```

### HTTP API

Base route family: `/agent/api/*`

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL&depth=auto&view=daily"
```

### Skill artifact

The shipped portable instructions live in
[`skills/terrafin/SKILL.md`](../skills/terrafin/SKILL.md).

## Transport rule

Use this order:

1. Prefer Python when TerraFin is importable locally.
2. Use HTTP when the server is already running elsewhere.
3. Use the CLI when shell composition is the simplest fit.

`TerraFinAgentClient(transport="auto")` follows that rule:

- with no `base_url`, it uses Python mode
- with a `base_url`, it uses HTTP mode

## Default request policy

For market and macro work:

- start with `depth="auto"`
- inspect the returned `processing`
- rerun with `depth="full"` only when the user explicitly needs long-range,
  backtest-style, or `ALL`-style context

For company info, earnings, financials, portfolio, and calendar data:

- the payload is expected to be complete immediately
- `processing.isComplete` should already be `true`

Charts are optional. Use `open_chart(...)` only when a chart is genuinely
useful for the task.

## Processing metadata

Every agent response includes top-level `processing`.

```json
{
  "processing": {
    "requestedDepth": "auto",
    "resolvedDepth": "recent",
    "loadedStart": "2023-04-04",
    "loadedEnd": "2026-04-04",
    "isComplete": false,
    "hasOlder": true,
    "sourceVersion": "yfinance-v2",
    "view": "weekly"
  }
}
```

What the main fields mean:

| Field | Meaning |
|-------|---------|
| `requestedDepth` | What the caller asked for: `auto`, `recent`, or `full` |
| `resolvedDepth` | What TerraFin actually returned |
| `loadedStart` / `loadedEnd` | Loaded time span for time-series tasks |
| `isComplete` | Whether older data still exists outside the response |
| `hasOlder` | Whether the request can be deepened |
| `sourceVersion` | Provider/cache version hint |
| `view` | Effective timeframe transform used on the response |

## Common tasks

| Task | Recommended entrypoint |
|------|------------------------|
| Ticker brief | `ticker_brief(...)` or `resolve(...)` then `market_snapshot(...)` |
| Market snapshot | `market_snapshot(name, depth="auto", view="daily")` |
| Compare assets | `compare_assets([...], depth="auto", view="daily")` |
| Macro context | `macro_context(name, depth="auto", view="daily")` |
| Portfolio context | `portfolio_context(guru)` |
| Stock fundamentals | `stock_fundamentals(ticker, statement="income", period="annual")` |
| Calendar scan | `calendar_scan(year=..., month=..., categories=..., limit=...)` |
| Bubble analysis | `bubble_analysis(name, depth="auto", view="daily")` |
| Open chart | `open_chart(...)` when a chart is explicitly useful |

Task helpers live in `src/TerraFin/agent/tasks.py`.

LPPL note:

- `lppl_analysis` uses TerraFin's calibrated default scan from
  `technical/lppl.py`
- the full article-style 750→50 ladder remains available from the Python
  analytics helper via `lppl(..., n_windows=None)`

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

## HTTP route summary

Current agent routes:

- `GET /agent/api/resolve`
- `GET /agent/api/market-data`
- `GET /agent/api/indicators`
- `GET /agent/api/market-snapshot`
- `GET /agent/api/company`
- `GET /agent/api/earnings`
- `GET /agent/api/financials`
- `GET /agent/api/portfolio`
- `GET /agent/api/economic`
- `GET /agent/api/macro-focus`
- `GET /agent/api/lppl`
- `GET /agent/api/calendar`

OpenAPI is available at `/openapi.json`.

## Minimal examples

### Python

```python
from TerraFin.agent import TerraFinAgentClient, stock_fundamentals

client = TerraFinAgentClient()
brief = client.market_snapshot("AAPL", depth="auto", view="daily")
fundamentals = stock_fundamentals("AAPL", client=client)
```

### CLI

```bash
terrafin-agent snapshot AAPL --depth auto --view daily --json
```

### HTTP

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL&depth=auto&view=daily"
```

## Read next

- [`skills/terrafin/SKILL.md`](../skills/terrafin/SKILL.md)
- [agent-runtime.md](./agent-runtime.md) for the maintainer view
- [interface.md](./interface.md) for the FastAPI surface
- [chart-architecture.md](./chart-architecture.md) for shared chart/session flow
