---
title: Agent Usage
summary: How to use TerraFin's agent-facing surfaces from Python, CLI, HTTP, and the hosted assistant widget.
read_when:
  - Using TerraFin as an agent tool
  - Choosing between stateless and hosted agent surfaces
  - Interpreting processing metadata
  - Finding the right transport for a workflow
---

# Agent Usage

TerraFin can be used by agents in two ways:

- **Your own agent calls TerraFin's tools.** Claude Code, Codex, or any other
  agent keeps its own model loop and calls TerraFin through Python, the CLI,
  or HTTP.
- **TerraFin's own agent.** TerraFin runs the model loop itself, behind the
  **TerraFin Agent** widget in the browser and the hosted runtime API.

Both use the same data path as the product:

- Market and macro responses start with a recent window and load older history
  on request, the way the chart does.
- Indicator math matches the chart.
- Every research response includes `processing`.

If you are maintaining the runtime itself, read [hosted-runtime.md](../harness/hosted-runtime.md)
and [architecture.md](../harness/architecture.md). This page is the usage guide.

## Tool lookup

Agents pick a tool from the skill's [tool lookup](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/references/tool-lookup.md), which also lists the
patterns not to hand-roll.

## Choose a surface

There are two agent-facing HTTP families:

- `/agent/api/*` is stateless capability access. Use it when your own agent
  already owns the model loop.
- `/agent/api/runtime/*` is TerraFin's own agent (the hosted runtime). Use it
  when TerraFin should own the conversation and tool loop.

In the browser, TerraFin's own agent is the floating **TerraFin Agent** widget
on the main pages, such as `/terminal`, `/chart`, and `/stock/<ticker>`.

If no usable hosted model is configured, the widget shows a setup warning,
creates no session, and accepts no chat input until the credentials are valid.

- Chat history is a local transcript per session.
- Deleting a session archives its transcript and removes it from the history list.
- Raw tool output stays in the transcript but is hidden from previews.

### Investor personas

TerraFin Agent can consult hidden investor personas (Warren Buffett,
Howard Marks, Stanley Druckenmiller) through `consult_<persona>` tool calls
before it replies. See
[architecture.md](../harness/architecture.md#orchestrator-persona-subagents).

- Users only ever talk to TerraFin Agent.
- Persona sessions are research-only and hidden from session history.
- Persona sessions cannot be created or addressed through the public runtime API.
- Each persona returns a structured memo, which TerraFin Agent turns into the reply.

## Disclosure

TerraFin Agent produces **research-oriented analysis, not personalized
investment advice**. Product surfaces, integrators, and end users should know:

- The agent cannot place trades, hold funds, or take fiduciary responsibility.
- Outputs are grounded in tool results and what the user says in the session.
  The agent should not invent numbers it has not seen in a tool result.
- Persona consults are research voices, not registered advisor recommendations.
- A persona memo with high confidence and no citations has its confidence
  lowered before TerraFin Agent sees it.

Who carries the disclosure:

- TerraFin Agent's system prompt carries a matching disclosure.
- A product that embeds the widget or calls the runtime API must add any
  **user-facing** disclosure its jurisdiction requires.
- The agent does not render a user-facing disclosure.

## Choose a transport

| Transport | Use it when... |
|-----------|----------------|
| Python client | TerraFin is importable locally and low latency matters |
| HTTP API | TerraFin is already running as a service |
| CLI | Shell composition is the simplest fit |
| Skill artifact | Another agent environment needs portable instructions |

`TerraFinAgentClient(transport="auto")` uses Python when no `base_url` is set,
and HTTP when one is.

## Default request policy

For market and macro requests:

- start with `depth="auto"`
- inspect the returned `processing`
- rerun with `depth="full"` only when the task needs long-range context

Company info, earnings, financials, portfolio, and calendar data come back
complete, so `processing.isComplete` should be `true`.

Charts are optional. Open one only when the chart itself helps the task.

## Processing metadata

Every structured research response includes a top-level `processing` object.

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

| Field | Meaning |
|-------|---------|
| `requestedDepth` | What the caller asked for |
| `resolvedDepth` | What TerraFin actually returned |
| `loadedStart` / `loadedEnd` | Loaded time span for time-series tasks |
| `isComplete` | Whether the response holds the full available history |
| `hasOlder` | Whether the request can be deepened |
| `sourceVersion` | Provider/cache version hint |
| `view` | Effective timeframe transform |

## Common tasks

Multi-step recipes. For single tools, use the
[tool lookup](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/references/tool-lookup.md).

Rows marked **(helper)** are plain functions in `TerraFin.agent`, not
registered capabilities. They combine capabilities, for example
`compare_assets` calls `market_snapshot` once per asset.

| Task | Recommended entrypoint |
|------|------------------------|
| Ticker brief | `resolve(...)` then `market_snapshot(...)` |
| Compare assets | `compare_assets([...], depth="auto", view="daily")` **(helper)** |
| Macro context | `macro_context(name, depth="auto", view="daily")` **(helper)** |
| Portfolio context | `portfolio_context(guru)` **(helper)** |
| Stock fundamentals | `stock_fundamentals(ticker, statement="income", period="annual")` **(helper)** |
| Read a filing | `sec_filings` then `sec_filing_document` then `sec_filing_section`, passing `form` each time (see [SEC filings](#sec-filings)) |

## Minimal examples

### Python client

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
snapshot = client.market_snapshot("AAPL", depth="auto", view="daily")
```

### TerraFin's own agent from Python

```python
from TerraFin.agent import create_runtime_session

session = create_runtime_session("terrafin-assistant")
session.send("Compare the S&P 500 and Nasdaq.")
session.display_notebook()
```

### CLI

```bash
terrafin-agent snapshot AAPL
terrafin-agent indicator-search trea --limit 5
terrafin-agent runtime-create-session terrafin-assistant
terrafin-agent models list --all
```

### HTTP

Build the address from `TERRAFIN_HOST`, `TERRAFIN_PORT`, and
`TERRAFIN_BASE_PATH` rather than hardcoding it:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"

curl "$TF/agent/api/market-snapshot?ticker=AAPL&depth=auto&view=daily"

curl -X POST "$TF/agent/api/runtime/sessions" \
  -H "Content-Type: application/json" \
  -d '{"agentName":"terrafin-assistant"}'
```

### Browser UI

Open `/terminal` and use the **TerraFin Agent** button in the lower-right corner.

## Route summary

Capability routes:

- The list below is generated from the registry and covers every capability
  with a route.
- Capabilities without a route only work inside a live session.
- The generated "Hosted-runtime-only tools" list in `skills/terrafin/SKILL.md`
  names the capabilities without a route.
- `terrafin-agent capabilities` prints every capability as JSON.

<!-- The route table below is auto-generated from
     src/TerraFin/agent/runtime/capability.py by
     `python scripts/generate-agent-artefacts.py`. Edit the registry, not
     this section. Hand-edits will be overwritten. -->

<!-- generated:route-summary:begin -->

Market, macro and news:

- `GET /agent/api/calendar` — TerraFin calendar events for a month.
- `GET /agent/api/economic` — Economic indicator series (FRED-backed).
- `GET /agent/api/indicator-search` — Find an indicator's catalog name by substring.
- `GET /agent/api/indicators` — Chart-matching technical indicators for one asset.
- `GET /agent/api/macro-focus` — Macro summary plus chart-ready series for one instrument.
- `GET /agent/api/market-data` — Chart-ready OHLC time series for one asset.
- `GET /agent/api/market-snapshot` — Compact market snapshot for one asset.
- `GET /agent/api/news` — Recent headlines for a ticker or query (metadata only).
- `GET /agent/api/resolve` — Resolve a free-form query into a TerraFin route.
- `GET /agent/api/top-companies` — Top companies by market cap (private API or yfinance fallback).

Company fundamentals and valuation:

- `GET /agent/api/beta-estimate` — 5-year monthly beta with adjusted beta, R², benchmark.
- `GET /agent/api/company` — Company profile and valuation fields for a ticker.
- `GET /agent/api/consensus` — Forward EPS/revenue consensus, revisions, and price targets.
- `GET /agent/api/earnings` — Earnings history (estimate / reported / surprise) for a ticker.
- `GET /agent/api/fcf-history` — FCF history + 3yr-avg / latest-annual / TTM candidates.
- `GET /agent/api/financials` — Financial statement table (income / balance / cashflow) for a ticker.
- `GET /agent/api/fundamental-screen` — Fundamental quality and moat screen for a ticker.
- `GET /agent/api/growth-series` — Revenue and EPS YoY growth series for a ticker.
- `GET /agent/api/sp500-dcf` — Full S&P 500 DCF valuation (scenarios, sensitivity, methods).
- `GET /agent/api/valuation` — DCF (incl. turnaround mode), reverse DCF, relative valuation, Graham number.

SEC filings and research:

- `GET /agent/api/sec-filing-document` — Filing table-of-contents (sections + char counts) without full body.
- `GET /agent/api/sec-filing-section` — Verbatim markdown body of one filing section by slug.
- `GET /agent/api/sec-filings` — List recent 10-K / 10-Q / 8-K filings and registration statements with EDGAR URLs.

Sentiment, risk and market regime:

- `GET /agent/api/fear-greed` — CNN Fear & Greed index — score, rating, history.
- `GET /agent/api/lppl` — LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection).
- `GET /agent/api/market-breadth` — Standalone market-breadth metrics (% advancing, new highs, etc.).
- `GET /agent/api/market-regime` — Market regime classification with confidence and signals.
- `GET /agent/api/risk-profile` — Statistical risk profile (tail risk, convexity, vol regime, drawdown).
- `GET /agent/api/trailing-forward-pe` — S&P 500 trailing vs forward P/E spread (history + summary).

Screening and patterns:

- `GET /agent/api/pattern-scan` — Sweep a watchlist group or ticker list for pattern triggers.
- `GET /agent/api/patterns` — Named market patterns matching the latest bar for one asset.
- `GET /agent/api/similarity-search` — Chart-pattern similarity search across a stock universe.

Portfolio and watchlist:

- `GET /agent/api/watchlist` — The user's current watchlist (read-only).

Investor personas:

- `GET /agent/api/portfolio` — Guru 13F book — not the user's holdings.

<!-- generated:route-summary:end -->

`current_view_context()` is read-only:

- TerraFin Agent can see the panel and form state the user is looking at, such
  as the DCF inputs.
- TerraFin Agent cannot write back to the form.
- If TerraFin Agent suggests input values, the user applies them by hand.

Runtime routes for TerraFin's own agent (sessions, messages, tasks, approvals)
are under `/agent/api/runtime/*`. `/openapi.json` lists them all, and
[hosted-runtime.md](../harness/hosted-runtime.md) explains how they fit together.

## Managing hosted models

TerraFin's own agent has a small model manager:

- It switches between OpenAI, Gemini and Anthropic without editing env vars.
- [models.md](../getting-started/models.md) is the full guide, including its OpenClaw attribution.

```bash
terrafin-agent models list --all
terrafin-agent models current
terrafin-agent models use google/gemini-4-argon
terrafin-agent models auth login --provider google --set-default
```

`models auth login` prompts for the credential on an interactive terminal.
In a non-interactive shell, pass `--token`.

## Read next

- [hosted-runtime.md](../harness/hosted-runtime.md)
- [models.md](../getting-started/models.md)
- [architecture.md](../harness/architecture.md)
- [../interface.md](../guides/interface.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
