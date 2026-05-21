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

## If you want to do X, use this tool

Scan this table **first** before reaching for `requests` / `urllib` /
`yfinance` / pandas-html / regex parsers. Every row below is already shipped
with rate-limit, retry, cache, and progressive-history handling.

| If you want to...                                          | Use this tool                                                       |
| ---------------------------------------------------------- | ------------------------------------------------------------------- |
| Resolve a ticker/name into a TerraFin route                | `resolve(query)`                                                    |
| Get a chart-ready OHLC series                              | `market_data(name, depth, view)`                                    |
| Get a one-asset snapshot (price action + indicators)       | `market_snapshot(name, depth, view, force_refresh=False)` — response `asof` is the ISO date of the last bar served; pass `force_refresh=True` only for time-sensitive snapshots (mid-session, freshly-closed bar) to bypass the 24h `yfinance.full` cache |
| Get company profile / valuation fields                     | `company_info(ticker)`                                              |
| Get earnings history (estimate / reported / surprise)      | `earnings(ticker)`                                                  |
| Get income / balance / cashflow statement                  | `financials(ticker, statement, period)`                             |
| List a ticker's recent 10-K / 10-Q / 8-K filings           | `sec_filings(ticker)`                                               |
| Get a single filing's TOC (no full body)                   | `sec_filing_document(ticker, accession, primaryDocument, form)`     |
| Pull one filing section's markdown body                    | `sec_filing_section(..., sectionSlug, form)`                        |
| Run DCF / reverse DCF / Graham / relative valuation        | `valuation(ticker, ...)` (see SKILL.md for turnaround inputs)       |
| Inspect FCF base candidates (3yr_avg / annual / TTM)       | `fcf_history(ticker, years)`                                        |
| Get S&P 500 index-level DCF                                | `sp500_dcf()`                                                       |
| Get 5y monthly beta vs mapped benchmark                    | `beta_estimate(ticker)`                                             |
| Get statistical risk profile (tail risk, drawdown, regime) | `risk_profile(name)`                                                |
| Run a fundamental quality / moat screen                    | `fundamental_screen(ticker)`                                        |
| Get guru portfolio holdings (Buffett / Marks / Druck.)     | `portfolio(guru)`                                                   |
| Get FRED-backed economic indicator series                  | `economic(indicators)`                                              |
| Get macro summary + chart-ready series                     | `macro_focus(name, depth, view)`                                    |
| Scan calendar events for a month                           | `calendar_events(year, month, categories, limit)`                   |
| Detect bubble (super-exp growth + log-periodic osc.)       | `lppl_analysis(name, depth, view)`                                  |
| Find chart-shape-similar historical episodes               | `similarity_search(ticker, universe, period, top_n)`                |
| Get market temperature signals                             | `fear_greed()`, `market_regime()`, `market_breadth()`, `trailing_forward_pe()` |
| Get top companies by market cap                            | `top_companies()`                                                   |
| Read the user's watchlist                                  | `watchlist()`                                                       |
| Get chart-matching technical indicators                    | `indicators(name, indicators, depth, view)`                         |
| Get named pattern signals matching the latest bar          | `patterns(name, depth, view)`                                       |
| Read which panel/form the user is currently looking at     | `current_view_context()` (hosted runtime only)                      |
| Open a chart artifact bound to the session                 | `open_chart(name)` (hosted runtime only)                            |
| List / authenticate / switch hosted models                 | `terrafin-agent models ...` (see [models.md](./models.md))          |
| Discover capability schemas programmatically               | `GET /openapi.json` — filter `paths` to `/agent/api/*`              |

Capability signatures with full parameter ranges and worked examples live in
[`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md).
The route summary further down this page is auto-generated and lists every
HTTP route.

## Don't roll your own

Reach for the TerraFin helper before hand-rolling any of the patterns below.
Each one has been a real source of breakage (rate-limit, cache miss,
parser inconsistency, hidden-API drift).

### SEC EDGAR — don't roll your own scrape

If you find yourself reaching for `urllib.request.urlopen("https://www.sec.gov/...")`,
regex-parsing the accession folder index, or stripping `<html>` tags by hand —
stop. The same content is one tool call away through the parsed + cached path:

| Manual approach (DON'T)                                              | TerraFin tool (DO)                                                                          |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `urlopen("https://www.sec.gov/Archives/edgar/data/<cik>/<acc>/")` to list exhibits | `sec_filing_document(ticker, accession, primaryDocument, form="8-K")` → `toc` carries `exhibit-991-press-release` / `exhibit-992-supplemental-material` slugs |
| `urlopen("https://www.sec.gov/.../q1fy27pr.htm")` to grab the earnings PR | `sec_filing_section(..., sectionSlug="exhibit-991-press-release", form="8-K")` → returns parsed markdown body |
| Strip `<p>` / `<table>` / `&nbsp;` with regex                        | already done — `sec_filing_section` returns clean markdown                                  |
| Strip the `/ix?doc=` viewer wrapper off `documentUrl`                | use `sec_filing_document` / `sec_filing_section` instead of dereferencing the URL yourself |

Why this matters:
- SEC rate-limits aggressively (~10 req/s per IP). The TerraFin helpers
  share a single `SECClient` with rate-limit + retry; raw `urllib` does not.
- Parsed markdown is cached 30 days under `sec.parsed`; raw fetches re-pull
  every newsletter run.
- Bypassing the cache risks SEC IP-banning the host.

The `form` arg is required for 8-K exhibit content — service defaults to
`"10-Q"`, and 8-Ks called without `form="8-K"` produce only the 4 KB cover
sheet stub (no exhibits appended). Pull `form` from
`sec_filings(...)["latestByForm"][...]["form"]` (or from any flat-list entry)
and pass it through every call.

### 8-K exhibits — don't bypass `fetch_and_parse_filing`

If you're tempted to call `download_filing(...)` then `parse_sec_filing(...)`
yourself for an 8-K, you'll get the 4 KB cover sheet with **no exhibits
appended**. The exhibit-appending logic lives only in
`fetch_and_parse_filing(cik, accession, doc, "8-K", include_images)`.

| Manual approach (DON'T)                                                                | TerraFin tool (DO)                                                                  |
| -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `parse_sec_filing(download_filing(cik, acc, doc), "8-K")`                              | `fetch_and_parse_filing(cik, acc, doc, "8-K", include_images=False)` — appends every `EX-99.x` exhibit |
| Manually loop `list_filing_files()` → `download_exhibit()` → `parse_sec_filing()`      | `fetch_and_parse_filing(...)` — already does this with per-exhibit error markers    |
| Call `sec_filing_section` without `form="8-K"`                                         | always pass `form="8-K"` — service defaults to `"10-Q"`                             |

The agent-facing path (`sec_filing_section`) wraps `fetch_and_parse_filing`
under the cache; only fall through to `fetch_and_parse_filing` directly when
writing non-agent data-layer code (route handlers, batch ingestion).

### Model catalog — don't reach into `_PROVIDER_CATALOG`

The provider catalog is a public function, not a private dict.

| Manual approach (DON'T)                                                   | TerraFin tool (DO)                                                       |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `from TerraFin.agent.models.management import _PROVIDER_CATALOG`          | `from TerraFin.agent.models.management import list_provider_catalog`     |
| `_PROVIDER_CATALOG["openai"].featured_model_refs`                         | `get_provider_catalog("openai").featured_model_refs`                     |
| Iterate the private dict to discover providers                            | `for entry in list_provider_catalog(): ...`                              |

The private `_PROVIDER_CATALOG` mapping may be renamed or reshaped without
notice; `list_provider_catalog()` / `get_provider_catalog(provider_id)` are
the stable surface.

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
  [architecture.md](./architecture.md#orchestrator-persona-subagents))
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
  [guru/memo.py](https://github.com/KiUngSong/TerraFin/blob/main/src/TerraFin/agent/guru/memo.py))

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

Multi-step task recipes. For a one-row "what tool do I need" lookup, scan the
[tool-index table at the top](#if-you-want-to-do-x-use-this-tool) instead.

Rows marked **(helper)** are composed module-level functions exported from
`from TerraFin.agent import …` — not registered capabilities. They wrap
one or more capabilities (e.g. `compare_assets` calls `resolve` + `market_snapshot`
under the hood). They're not in the 30-row capability table because they
don't appear in the agent capability registry.

| Task | Recommended entrypoint |
|------|------------------------|
| Ticker brief | `resolve(...)` then `market_snapshot(...)` |
| Market snapshot | `market_snapshot(name, depth="auto", view="daily")` |
| Compare assets | `compare_assets([...], depth="auto", view="daily")` **(helper)** |
| Macro context | `macro_context(name, depth="auto", view="daily")` **(helper)** |
| Portfolio context | `portfolio_context(guru)` **(helper)** |
| Stock fundamentals | `stock_fundamentals(ticker, statement="income", period="annual")` **(helper)** |
| Stock DCF | `valuation(ticker, projection_years=..., fcf_base_source=..., breakeven_year=..., breakeven_cash_flow_per_share=..., post_breakeven_growth_pct=...)` |
| FCF history candidates | `fcf_history(ticker, years=10)` |
| SEC filings | `sec_filings(ticker)` → `sec_filing_document(..., form=...)` → `sec_filing_section(..., sectionSlug=..., form=...)`. **Pass the actual `form` string** ("10-K" / "10-Q" / "8-K" / "8-K/A") on every call — service defaults to "10-Q". For 8-K, the TOC includes `exhibit-991-press-release` / `exhibit-992-supplemental-material` slugs holding the earnings PR + CFO commentary bodies. |
| Sentiment / breadth | `fear_greed()`, `market_regime()`, `market_breadth()`, `trailing_forward_pe()` |
| Calendar scan | `calendar_events(year=..., month=..., categories=..., limit=...)` |
| Bubble analysis | `lppl_analysis(name, depth="auto", view="daily")` |
| Chart similarity search | `similarity_search(ticker, universe="sp500+nasdaq100+kospi200", period="1y", top_n=20)` |
| Open chart | `open_chart(...)` when the chart is explicitly useful |

> See [Don't roll your own → SEC EDGAR](#sec-edgar--dont-roll-your-own-scrape)
> for the anti-pattern table and why the helper exists. The summary: pass
> `form="8-K"` explicitly (service defaults to `"10-Q"`), pull it from
> `sec_filings(...)["latestByForm"][...]["form"]`.

> The full per-capability call signature, parameter ranges, and worked
> examples (including DCF turnaround mode) live in
> [`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md) —
> the skill is the authoritative capability reference for both this doc and
> external agents.

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

Stateless capability routes (every hosted-runtime tool also has a parity HTTP
route under `/agent/api/*` — see `skills/terrafin/SKILL.md` for the full
30-capability table with Python / CLI signatures).

<!-- The route table below is auto-generated from
     src/TerraFin/agent/runtime/capability.py by
     `python scripts/generate-agent-artefacts.py`. Edit the registry, not
     this section. Hand-edits will be overwritten. -->

<!-- generated:route-summary:begin -->

Data + chart:

- `GET /agent/api/calendar` — TerraFin calendar events for a month.
- `GET /agent/api/company` — Company profile and valuation fields for a ticker.
- `GET /agent/api/earnings` — Earnings history (estimate / reported / surprise) for a ticker.
- `GET /agent/api/economic` — Economic indicator series (FRED-backed).
- `GET /agent/api/financials` — Financial statement table (income / balance / cashflow) for a ticker.
- `GET /agent/api/indicators` — Chart-matching technical indicators for one asset.
- `GET /agent/api/lppl` — LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection).
- `GET /agent/api/macro-focus` — Macro summary plus chart-ready series for one instrument.
- `GET /agent/api/market-data` — Chart-ready OHLC time series for one asset.
- `GET /agent/api/market-snapshot` — Compact market snapshot for one asset.
- `GET /agent/api/portfolio` — Guru portfolio holdings and summary metadata.
- `GET /agent/api/resolve` — Resolve a free-form query into a TerraFin route.

Valuation + fundamentals:

- `GET /agent/api/beta-estimate` — 5-year monthly beta with adjusted beta, R², benchmark.
- `GET /agent/api/fundamental-screen` — Fundamental quality and moat screen for a ticker.
- `GET /agent/api/risk-profile` — Statistical risk profile (tail risk, convexity, vol regime, drawdown).
- `GET /agent/api/sp500-dcf` — Full S&P 500 DCF valuation (scenarios, sensitivity, methods).
- `GET /agent/api/valuation` — DCF (incl. turnaround mode), reverse DCF, relative valuation, Graham number.

SEC filings:

- `GET /agent/api/sec-filing-document` — Filing table-of-contents (sections + char counts) without full body.
- `GET /agent/api/sec-filing-section` — Verbatim markdown body of one filing section by slug.
- `GET /agent/api/sec-filings` — List recent 10-K / 10-Q / 8-K filings for a ticker with EDGAR URLs.

Sentiment / breadth / market state:

- `GET /agent/api/fear-greed` — CNN Fear & Greed index — score, rating, history.
- `GET /agent/api/market-breadth` — Standalone market-breadth metrics (% advancing, new highs, etc.).
- `GET /agent/api/market-regime` — Market regime classification with confidence and signals.
- `GET /agent/api/top-companies` — Top companies by market cap (private API or yfinance fallback).
- `GET /agent/api/trailing-forward-pe` — S&P 500 trailing vs forward P/E spread (history + summary).
- `GET /agent/api/watchlist` — The user's current watchlist (read-only).

Other:

- `GET /agent/api/fcf-history` — FCF history + 3yr-avg / latest-annual / TTM candidates.
- `GET /agent/api/patterns` — Named market patterns matching the latest bar for one asset.
- `GET /agent/api/similarity-search` — Chart-pattern similarity search across a stock universe.

<!-- generated:route-summary:end -->

> **View context is read-only.** The hosted runtime exposes a
> `current_view_context()` tool that returns the panel and form state the
> user is currently looking at — including the DCF input form's
> `projectionYears` / `fcfBaseSource` / `turnaroundMode` selections, the FCF
> history candidates already loaded, and the auto-selected DCF base source.
> The agent **cannot currently write back to the user's frontend form** (no
> `apply_dcf_inputs` / `set_form_state` tool exists). If the agent suggests
> input values, the user applies them manually. This gap is tracked.

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
