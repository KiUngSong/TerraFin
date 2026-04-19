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

TerraFin is most useful to agents when it stays on the same path as the product.

That means:

- market and macro responses use the same progressive-history rules as the chart stack
- indicator math matches the chart indicators
- chart-opening uses the same session semantics as the browser UI
- every research response includes `processing`

If you are maintaining the runtime itself, read [hosted-runtime.md](./hosted-runtime.md)
and [architecture.md](./architecture.md). This document is the usage guide.

## Choose a surface

There are two agent-facing HTTP families:

- `GET/POST /agent/api/*`
  Stateless capability access, best when another agent already owns the model loop
- `GET/POST /agent/api/runtime/*`
  Stateful hosted runtime access, best when TerraFin should own the conversation and tool loop

In the browser, the hosted runtime is exposed through the floating **TerraFin Agent**
widget available on main interface pages such as `/dashboard`, `/chart`, and `/stock/<ticker>`.

That panel is always the public surface. There is no guru picker in the default
product flow.

If the deployment does not have a usable hosted model configured, the widget
stays in an info-only state:

- it shows the local setup warning
- it does not create a runtime session
- it does not accept chat input until the hosted model credentials are valid

Hosted runtime chat history is local transcript history:

- each session is stored as an append-only JSONL transcript
- history list and previews are derived from the transcript index
- deleting a session archives the transcript and removes it from active history
- raw tool JSON stays in the transcript for replay, but is hidden from user-facing previews

TerraFin Agent may also route some research questions through hidden investor
roles before replying. Today those roles include Warren Buffett, Howard Marks,
and Stanley Druckenmiller.

Important product rules:

- users still talk only to `TerraFin Agent`
- `TerraFin Agent` is the **orchestrator**; hidden persona roles are
  reached by its own LLM via `consult_warren_buffett`,
  `consult_howard_marks`, and `consult_stanley_druckenmiller` tool
  calls (no pre-intercept router — see the architecture diagrams in
  [architecture.md](./architecture.md#orchestrator--persona-subagents))
- the hidden guru path is research-only in v1
- hidden guru sessions are not shown in normal session history
- hidden guru roles cannot be created through the normal public runtime API
- hidden guru session ids are not valid public session/task/approval resources
- internal guru handoff uses a structured memo contract before the main assistant synthesizes a reply

## Disclosure

The hosted TerraFin Agent produces **research-oriented analysis, not personalized
investment advice**. A few properties follow from that framing and should be
called out to downstream product surfaces, integrators, and end users:

- the agent cannot place trades, hold funds, or take fiduciary responsibility
- outputs are grounded in tool results and what the user says in the same
  session; the agent should not invent numbers it has not seen in a tool result
- persona consults (Buffett, Marks, Druckenmiller) are framed as research
  voices, not registered advisor recommendations
- a `confidence` score ≥ 80 returned by a persona consult carries at least one
  citation — the `GuruResearchMemo` validator clamps unsupported high-confidence
  memos to 60 before returning them to the orchestrator (see
  [guru.py](../../src/TerraFin/agent/guru.py))

The orchestrator's system prompt carries a matching `DISCLOSURE` paragraph so the
model stays inside this framing. Product surfaces that embed the widget or call
the runtime HTTP API are responsible for any **user-facing** disclosure copy
their jurisdiction requires — the agent itself does not render one.

## Choose a transport

| Transport | Use it when... |
|-----------|----------------|
| Python client | TerraFin is importable locally and low latency matters |
| HTTP API | TerraFin is already running as a service |
| CLI | Shell composition is the simplest fit |
| Skill artifact | Another agent environment needs portable instructions |

`TerraFinAgentClient(transport="auto")` follows the normal rule:

1. Python when no `base_url` is set
2. HTTP when a `base_url` is set

## Default request policy

For market and macro requests:

- start with `depth="auto"`
- inspect the returned `processing`
- rerun with `depth="full"` only when the task genuinely needs long-range context

For company info, earnings, financials, portfolio, and calendar data:

- the payload should already be complete
- `processing.isComplete` is expected to be `true`

Charts are optional. Open them when the chart itself materially helps the task.

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
| `isComplete` | Whether older data still exists outside the response |
| `hasOlder` | Whether the request can be deepened |
| `sourceVersion` | Provider/cache version hint |
| `view` | Effective timeframe transform |

## Common tasks

| Task | Recommended entrypoint |
|------|------------------------|
| Ticker brief | `resolve(...)` then `market_snapshot(...)` |
| Market snapshot | `market_snapshot(name, depth="auto", view="daily")` |
| Compare assets | `compare_assets([...], depth="auto", view="daily")` |
| Macro context | `macro_context(name, depth="auto", view="daily")` |
| Portfolio context | `portfolio_context(guru)` |
| Stock fundamentals | `stock_fundamentals(ticker, statement="income", period="annual")` |
| Calendar scan | `calendar_events(year=..., month=..., categories=..., limit=...)` |
| Bubble analysis | `lppl_analysis(name, depth="auto", view="daily")` |
| Open chart | `open_chart(...)` when the chart is explicitly useful |

## Minimal examples

### Python client

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
snapshot = client.market_snapshot("AAPL", depth="auto", view="daily")
```

### Hosted runtime helper

```python
from TerraFin.agent import create_runtime_session

session = create_runtime_session("terrafin-assistant")
session.send("Compare the S&P 500 and Nasdaq.")
session.display_notebook()
```

### CLI

```bash
terrafin-agent snapshot AAPL
terrafin-agent runtime-create-session terrafin-assistant
terrafin-agent models list --all
```

### HTTP

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL&depth=auto&view=daily"

curl -X POST "http://127.0.0.1:8001/agent/api/runtime/sessions" \
  -H "Content-Type: application/json" \
  -d '{"agentName":"terrafin-assistant"}'
```

### Browser UI

```text
http://127.0.0.1:8001/dashboard
Use the TerraFin Agent button in the lower-right corner.
```

## Route summary

Stateless capability routes:

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

Hosted runtime routes:

- `GET /agent/api/runtime/agents`
- `POST /agent/api/runtime/sessions`
- `GET /agent/api/runtime/sessions`
- `GET /agent/api/runtime/sessions/{session_id}`
- `DELETE /agent/api/runtime/sessions/{session_id}`
- `POST /agent/api/runtime/sessions/{session_id}/messages`
- `GET /agent/api/runtime/sessions/{session_id}/approvals`
- `GET /agent/api/runtime/tasks/{task_id}`
- `POST /agent/api/runtime/tasks/{task_id}/cancel`
- `GET /agent/api/runtime/approvals/{approval_id}`
- `POST /agent/api/runtime/approvals/{approval_id}/approve`
- `POST /agent/api/runtime/approvals/{approval_id}/deny`

OpenAPI is available at `/openapi.json`.

## Managing hosted models

The hosted runtime now has a small built-in model manager. Use it when you want
OpenAI, Gemini, or GitHub Copilot without hand-editing env vars every time.

This command family was inspired by OpenClaw's provider/model UX, but TerraFin
implements and persists it through its own runtime and CLI layers. See
[models.md](./models.md) for the explicit attribution and boundary.

```bash
terrafin-agent models list --all
terrafin-agent models current
terrafin-agent models use github-copilot/gpt-4o
terrafin-agent models auth login-github-copilot --set-default
```

`login-github-copilot` now runs a full GitHub device-login flow by default. For
non-interactive shells, pass `--token` instead.

For the full model-management guide, read [models.md](./models.md).

## Read next

- [hosted-runtime.md](./hosted-runtime.md)
- [models.md](./models.md)
- [architecture.md](./architecture.md)
- [../interface.md](../interface.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
