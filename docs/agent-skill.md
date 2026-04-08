---
title: Agent Skill
summary: How agents should use TerraFin through the shared processing layer, Python client, CLI, HTTP API, and optional chart helpers.
read_when:
  - Using TerraFin as a reusable agent skill
  - Choosing between Python and HTTP transport
  - Interpreting processing metadata
  - Mapping common research tasks to TerraFin client methods
---

# TerraFin As An Agent Skill

TerraFin is agent-friendly when agents use the same optimized processing path as
the product itself.

That means:

- market and macro tasks use the progressive-history aware data contract
- view transforms match the chart stack
- indicator computation matches chart math
- the result always exposes `processing` metadata so an agent can decide whether
  it needs a deeper rerun

The goal is not "a separate simplified API for bots." The goal is one shared
pipeline with multiple entrypoints.

## Public entrypoints

### 1. Python client

Source: `src/TerraFin/agent/client.py`

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
snapshot = client.market_snapshot("AAPL")
```

Use Python mode when:

- TerraFin is installed in the current environment
- the agent is running inside the same repo or Python environment
- low-latency local access is preferred

### 2. CLI

Console script: `terrafin-agent`

```bash
terrafin-agent market-data AAPL --json
terrafin-agent financials AAPL --statement income --period annual --json
```

Use the CLI when:

- the agent prefers shell tools over Python imports
- the workflow already composes terminal commands
- machine-readable stdout is needed with `--json`

### 3. HTTP API

Base route family: `/agent/api/*`

Use HTTP mode when:

- TerraFin is already running as a service
- the agent is remote from the Python environment
- OpenAPI or service boundaries matter more than direct imports

### 4. Skill artifact

Shipped skill: `skills/terrafin/SKILL.md`

That skill is the portable "how to use TerraFin" artifact for other agent
environments. It points agents to the client, CLI, and task recipes below.

## Transport rule

Use this decision rule:

- prefer Python when TerraFin is importable locally
- use HTTP when the server is already running elsewhere or only API access is available
- use the CLI when shell-native composition is easier than imports

`TerraFinAgentClient(transport="auto")` follows that pattern:

- with no `base_url`, it uses Python mode
- with a `base_url`, it uses HTTP mode

## Shared processing model

The agent layer lives in `src/TerraFin/agent/service.py`.

For market and macro series, it shares the optimized path already used by the
chart stack:

- `DataFactory.get_recent_history(...)`
- `DataFactory.get(...)` when full depth is required
- chart-style `apply_view(...)`
- chart indicator adapters from `src/TerraFin/interface/chart/indicators/adapter.py`

For non-progressive domains such as company info, earnings, financials,
portfolio, and calendar, TerraFin returns complete results immediately but still
includes `processing`.

## Processing metadata

Every agent response includes a top-level `processing` field.

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

Meaning:

- `requestedDepth`: what the caller asked for: `auto`, `recent`, or `full`
- `resolvedDepth`: what TerraFin actually returned: `recent` or `full`
- `loadedStart` / `loadedEnd`: loaded time span for time-series tasks
- `isComplete`: whether older data still exists outside the returned range
- `hasOlder`: whether the caller can deepen the request
- `sourceVersion`: provider/cache version hint
- `view`: effective timeframe transform used on the response

Upgrade rule:

- if the user asks for long-range context, full history, backtest-style work, or `ALL`-style analysis, rerun with `depth="full"`

## Task defaults

Default hybrid policy:

- `ticker_brief`, `market_snapshot`, `compare_assets`, and `macro_context` start with `depth="auto"`
- `company_info`, `earnings`, `financials`, `portfolio`, and `calendar_scan` are complete immediately
- explicit long-range analysis should use `depth="full"`

## Standard tasks

These are the intended reusable recipes.

| Task | Python helper | Client method(s) | CLI |
|------|---------------|------------------|-----|
| Ticker brief | `ticker_brief(...)` | `resolve`, `market_snapshot`, `company_info` | `resolve`, `snapshot`, `company` |
| Market snapshot | `market_snapshot(...)` | `market_snapshot` | `snapshot` |
| Compare assets | `compare_assets(...)` | repeated `market_snapshot` | repeated `snapshot` |
| Macro context | `macro_context(...)` | `macro_focus` | `macro-focus` |
| Portfolio context | `portfolio_context(...)` | `portfolio` | `portfolio` |
| Stock fundamentals | `stock_fundamentals(...)` | `company_info`, `earnings`, `financials` | `company`, `earnings`, `financials` |
| Calendar scan | `calendar_scan(...)` | `calendar_events` | `calendar` |
| Bubble analysis | `bubble_analysis(...)` | `lppl_analysis` | `lppl` |
| Open chart | `open_chart(...)` | `open_chart` | `open-chart` |

Task helpers live in `src/TerraFin/agent/tasks.py`.

LPPL note:
The shared `lppl_analysis` agent path uses TerraFin's calibrated default scan
from `technical/lppl.py`, which is the same behavior used by the chart layer.
The full article-style 750→50 ladder remains available only from the Python
analytics helper via `lppl(..., n_windows=None)` while LPPL tuning continues.

## HTTP surface

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

Time-series endpoints accept:

- `depth=auto|recent|full`
- `view=daily|weekly|monthly|yearly` where applicable

OpenAPI is available from the server at `/openapi.json`.

## Charts are optional

Charts are supported, but they are not the main agent contract.

Use `open_chart(...)` only when a chart is genuinely useful for the task.
Structured analysis should usually come first.

Chart rules:

- lookup-name chart requests use the existing progressive chart routes
- raw dataframe chart requests use the direct chart-data path
- notebook and page flows keep using TerraFin's existing chart/session model

## Minimal examples

### Python

```python
from TerraFin.agent import TerraFinAgentClient, stock_fundamentals

client = TerraFinAgentClient()
brief = client.market_snapshot("AAPL", depth="auto", view="daily")
fundamentals = stock_fundamentals("AAPL", client=client)
```

### HTTP

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL&depth=auto&view=daily"
```

### CLI

```bash
terrafin-agent snapshot AAPL --depth auto --view daily --json
```

## See also

- `skills/terrafin/SKILL.md`
- [interface.md](./interface.md)
- [chart-architecture.md](./chart-architecture.md)
- [analytics.md](./analytics.md)
