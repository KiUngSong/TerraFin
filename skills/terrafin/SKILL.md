---
name: terrafin
description: Use when an agent needs structured market, macro, portfolio, calendar, fundamentals, valuation (DCF / reverse DCF / S&P 500 DCF, including turnaround mode), SEC filings, sentiment/breadth, or watchlist research through TerraFin's optimized processing pipeline, including progressive history metadata and optional chart opening.
version: "0.0.1"
allowed-tools:
  - Bash
  - Read
  - WebFetch
triggers:
  - terrafin
  - dcf
  - valuation
  - turnaround
  - reverse dcf
  - fcf
  - free cash flow
  - sec filing
  - 10-k
  - 10-q
  - earnings history
  - fear and greed
  - market regime
  - market breadth
  - p/e spread
  - watchlist
  - top companies
  - guru portfolio
  - lppl
  - bubble analysis
  - pattern signals
  - capitulation
  - golden cross
  - death cross
  - bollinger breakout
  - donchian breakout
  - rsi oversold
  - rsi overbought
  - wyckoff
  - minervini
  - 52-week high
---

# TerraFin

## Install (one-shot, multi-host)

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
./setup                # auto-detects Claude Code / Codex / opencode on PATH

# Optional: install the Python client + CLI for in-process / shell use
pip install -e .
```

`./setup` symlinks `skills/terrafin` into the skill dir of every AI host
it finds: `~/.claude/skills/`, `~/.codex/skills/`, `~/.config/opencode/
skills/`. Pass `--host claude|codex|opencode` to install to just one.
The installer pattern is adapted from [gstack](https://github.com/garrytan/gstack).

Because it's a symlink, `git pull` upgrades every host at once — no
re-copy step.

After installing, open a new session in your AI host and type `terrafin`
to invoke. For HTTP-only use you can skip `pip install` and run
TerraFin's server separately (see "HTTP" below).

### Environment variables

TerraFin reads env vars from the shell or a project-local `.env` (only
loaded by `terrafin-agent` / `python -m TerraFin.interface.server`, not
by the Python client directly — export them in your shell for
`TerraFinAgentClient` use).

Required for HTTP-only / stateless agent calls: none. The stateless
`/agent/api/*` routes work out of the box.

Optional, unlocks additional capabilities:

- `FRED_API_KEY` — enables `/agent/api/economic` and `/agent/api/macro-focus` (FRED series).
- `TERRAFIN_SEC_USER_AGENT` — required by SEC EDGAR (`/agent/api/sec-filings`, `/agent/api/sec-filing-document`, `/agent/api/sec-filing-section`). Format: `"Your Org Name contact@example.com"`.

Required only for the **hosted TerraFin Agent runtime** (conversational
UI at `/agent/*`, not the stateless `/agent/api/*` routes):

- `TERRAFIN_AGENT_MODEL_REF` — e.g. `openai:gpt-4.1`, `gemini:gemini-2.5-pro`, `copilot:gpt-4.1`.
- One of `OPENAI_API_KEY`, `GEMINI_API_KEY`, `COPILOT_GITHUB_TOKEN` — must match the provider in `TERRAFIN_AGENT_MODEL_REF`.

See [.env.example](../../.env.example) and [docs/configuration.md](../../docs/configuration.md) for the full list (MongoDB watchlist, private-access data source, host/port overrides, etc.).

## When to use

Use this skill when the task is financial research and TerraFin is available in
the current repo, Python environment, or as an HTTP service.

Prefer TerraFin over ad hoc scraping when you need:

- market or macro time series
- chart-matching technical indicators
- stock company info, earnings, or financial statements
- **DCF / reverse DCF / S&P 500 DCF — forward and turnaround mode**
- **historical FCF/share with 3yr-avg, latest-annual, and TTM candidates**
- SEC 10-K / 10-Q filings (list, table-of-contents, section bodies)
- guru portfolio holdings (Buffett, Marks, Druckenmiller)
- economic series
- calendar events
- sentiment/breadth widgets (fear & greed, market regime, breadth, P/E spreads)
- watchlist state
- the user's current view context (what panel they're looking at)
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
client.valuation("MOH", projection_years=10, fcf_base_source="3yr_avg")
```

CLI:

```bash
terrafin-agent snapshot AAPL
```

HTTP (parity with Python client — every capability has a route under
`/agent/api/*`):

```bash
curl "http://127.0.0.1:8001/agent/api/market-snapshot?ticker=AAPL"
curl "http://127.0.0.1:8001/agent/api/valuation?ticker=MOH&projection_years=10&fcf_base_source=3yr_avg"
curl "http://127.0.0.1:8001/agent/api/fcf-history?ticker=GOOGL&years=10"
```

## Programmatic capability discovery

Don't enumerate capabilities by parsing this Markdown — TerraFin is FastAPI,
so the canonical machine-readable surface is the **live OpenAPI spec**:

```bash
# Full OpenAPI document for the running TerraFin server
curl http://127.0.0.1:8001/openapi.json

# Filter to just the stateless agent capability routes
curl -s http://127.0.0.1:8001/openapi.json \
  | jq '.paths | with_entries(select(.key | startswith("/agent/api/") and (contains("/runtime") | not)))'
```

Each path entry carries the parameter schema (types, enums, ranges,
defaults), the response model, and the route's `summary` /  `description`.
That's the source of truth for argument validation — prefer it over copy-
pasting from the recipes below when you're building a programmatic call
generator.

The recipes in this file are still useful for:

- learning *when* to call which capability (the LLM-readable intent),
- worked examples showing the parameter combinations the model trained on
  (DCF turnaround, the SEC filings 3-step recipe, the FCF Base Source picker),
- the read-only-view-context contract and other non-schema constraints.

## Default depth rule

For market and macro tasks:

- start with `depth="auto"`
- inspect the returned `processing`
- rerun with `depth="full"` only when the user explicitly needs long-range,
  backtest-style, or `ALL`-style context

For company info, earnings, financials, portfolio, calendar, valuation, SEC
filings, sentiment, and watchlist:

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

### DCF valuation

Use:

- `valuation(ticker)` — full payload: forward DCF (5yr default horizon),
  reverse DCF, relative valuation (trailing/forward P/E, P/B), Graham number,
  margin of safety. Defaults are sane for healthy stable companies.

Tune the forward DCF with optional kwargs:

- `projection_years` — `5`, `10`, or `15`. Default `5`. Use `10`+ for
  long-cycle businesses or turnaround stories so terminal value carries less
  weight.
- `fcf_base_source` — `auto` (default), `3yr_avg`, `ttm`, or `latest_annual`.
  `auto` cascades `3yr_avg → latest_annual → ttm`. The 3-year average is the
  professional default for DCF (single-period TTM is too noisy from
  working-capital swings and capex lumps).

```python
client.valuation("AAPL", projection_years=10, fcf_base_source="3yr_avg")
```

### DCF turnaround mode

Use when current FCF is negative or volatile but the user has a thesis that
FCF turns positive. Supplying ALL three turnaround fields switches to an
explicit per-year schedule:

- `breakeven_year` — the year FCF turns positive (typical 1–5 for
  operational turnarounds)
- `breakeven_cash_flow_per_share` — FCF/share at the breakeven year
- `post_breakeven_growth_pct` — growth rate after breakeven, fades toward
  terminal growth across the remaining horizon

Pre-breakeven years interpolate linearly from current FCF (which can be
negative; cash-burn is *not* clipped — it reduces intrinsic value honestly)
to the breakeven value.

```python
# MOH thesis: $2/share by 2027, then 15% growth fading to terminal
client.valuation(
    "MOH",
    projection_years=10,
    breakeven_year=3,
    breakeven_cash_flow_per_share=2.0,
    post_breakeven_growth_pct=15.0,
)
```

### Historical FCF / share

Use before DCF when the user is unsure what base to choose, or to surface
candidate values for the FCF Base Source picker:

- `fcf_history(ticker, years=10)` — annual rows, TTM marker, and
  `candidates: {threeYearAvg, latestAnnual, ttm}` per share. Also returns
  `autoSelectedSource` (which candidate the `auto` cascade would pick under
  current data — `3yr_avg`, `annual`, or `quarterly_ttm`).

```python
hist = client.fcf_history("GOOGL", years=10)
# Inspect hist["candidates"] before calling valuation()
```

### S&P 500 DCF

Use:

- `sp500_dcf()` — index-level DCF using earnings power + shareholder yield
  blended methodology with consensus inputs.

### Reverse DCF

Bundled inside `valuation()` — see the `reverseDcf` field of the response.
Returns the implied growth rate the market is pricing in.

### Beta estimate

Use:

- `beta_estimate(ticker)` — TerraFin's `beta_5y_monthly` against the mapped
  benchmark (S&P 500 for US, KOSPI 200 for KS, etc.). Used as the discount
  rate input for DCF.

### SEC filings

Three-step recipe for analyzing US-listed company filings:

1. `sec_filings(ticker)` — list recent 10-K / 10-Q / 8-K with EDGAR URLs and
   `latestByForm[<form>]` shortcut.
2. `sec_filing_document(ticker, accession, primaryDocument)` — get the
   filing's table of contents (sections + char counts) WITHOUT pulling the
   full body. Keeps the agent's context small.
3. `sec_filing_section(ticker, accession, primaryDocument, sectionSlug)` —
   pull a single section's markdown body by slug.

```python
filings = client.sec_filings("AAPL")
acc = filings["latestByForm"]["10-K"]["accession"]
prim = filings["latestByForm"]["10-K"]["primaryDocument"]
toc = client.sec_filing_document("AAPL", acc, prim, form="10-K")
md = client.sec_filing_section("AAPL", acc, prim, "item-1-business", form="10-K")
```

If `sec_filing_section` raises with "section not found", the error message
includes the 5 largest sections in the filing — pick the largest neighbor
(10-K parsers often nest MD&A inside an oversized parent).

### Sentiment / breadth widgets

Stateless market-temperature signals:

- `fear_greed()` — current CNN-style fear & greed index
- `market_regime()` — TerraFin's regime classification
- `market_breadth()` — % advancing / new highs / etc.
- `trailing_forward_pe()` — S&P 500 trailing vs forward P/E spread

Use one of these (not all four) when the user asks "is the market frothy?" /
"what's the cycle?" / "are we in a bubble?". For a deep cycle answer pair
with `sp500_dcf()` and `lppl_analysis("S&P 500")`.

### Watchlist

Use:

- `watchlist()` — read the user's current watchlist (read-only from agent).

### Top companies

Use:

- `top_companies()` — market-cap-ranked equity list driving Market Insights.

### Read what the user is currently viewing

Use:

- `current_view_context()` — returns the page/panel the user is looking at,
  including form-state selection (e.g., the DCF input form's current
  `projectionYears`, `fcfBaseSource`, `turnaroundMode`, `breakevenYear`),
  FCF history candidates already loaded, the auto-selected DCF base source,
  and any active scenario state.

This is the agent's primary tool for matching what the user *sees* without
re-fetching. Always call it before answering "what am I looking at?" or
"explain this card" types of questions.

### Open chart

Use only when a chart is explicitly helpful.

- `open_chart("AAPL")`
- `open_chart(["S&P 500", "Nasdaq"])`

Chart requests by lookup name use TerraFin's progressive chart pipeline. Raw
dataframe chart requests are supported through the Python client and are treated
as complete from the start.

## Key client methods

<!-- The two lists below are auto-generated from src/TerraFin/agent/runtime.py
     by `python scripts/generate-agent-artefacts.py`. Edit the registry, not
     these lines. Hand-edits here will be overwritten on the next regen. -->

<!-- generated:capability-list:begin -->

Stateless data + analysis (each has a matching `/agent/api/*` HTTP route):

- `resolve` — Resolve a free-form query into a TerraFin route. `GET /agent/api/resolve`
- `market_data` — Chart-ready OHLC time series for one asset. `GET /agent/api/market-data`
- `indicators` — Chart-matching technical indicators for one asset. `GET /agent/api/indicators`
- `market_snapshot` — Compact market snapshot for one asset. `GET /agent/api/market-snapshot`
- `lppl_analysis` — LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection). `GET /agent/api/lppl`
- `company_info` — Company profile and valuation fields for a ticker. `GET /agent/api/company`
- `earnings` — Earnings history (estimate / reported / surprise) for a ticker. `GET /agent/api/earnings`
- `financials` — Financial statement table (income / balance / cashflow) for a ticker. `GET /agent/api/financials`
- `portfolio` — Guru portfolio holdings and summary metadata. `GET /agent/api/portfolio`
- `economic` — Economic indicator series (FRED-backed). `GET /agent/api/economic`
- `macro_focus` — Macro summary plus chart-ready series for one instrument. `GET /agent/api/macro-focus`
- `calendar_events` — TerraFin calendar events for a month. `GET /agent/api/calendar`
- `fear_greed` — CNN Fear & Greed index — score, rating, history. `GET /agent/api/fear-greed`
- `sp500_dcf` — Full S&P 500 DCF valuation (scenarios, sensitivity, methods). `GET /agent/api/sp500-dcf`
- `beta_estimate` — 5-year monthly beta with adjusted beta, R², benchmark. `GET /agent/api/beta-estimate`
- `top_companies` — Top companies (market-cap-ranked equity list). `GET /agent/api/top-companies`
- `market_regime` — Market regime classification with confidence and signals. `GET /agent/api/market-regime`
- `trailing_forward_pe` — S&P 500 trailing vs forward P/E spread (history + summary). `GET /agent/api/trailing-forward-pe`
- `market_breadth` — Standalone market-breadth metrics (% advancing, new highs, etc.). `GET /agent/api/market-breadth`
- `watchlist` — The user's current watchlist (read-only). `GET /agent/api/watchlist`
- `fundamental_screen` — Fundamental quality and moat screen for a ticker. `GET /agent/api/fundamental-screen`
- `risk_profile` — Statistical risk profile (tail risk, convexity, vol regime, drawdown). `GET /agent/api/risk-profile`
- `valuation` — DCF (incl. turnaround mode), reverse DCF, relative valuation, Graham number. `GET /agent/api/valuation`
- `sec_filings` — List recent 10-K / 10-Q / 8-K filings for a ticker with EDGAR URLs. `GET /agent/api/sec-filings`
- `sec_filing_document` — Filing table-of-contents (sections + char counts) without full body. `GET /agent/api/sec-filing-document`
- `sec_filing_section` — Verbatim markdown body of one filing section by slug. `GET /agent/api/sec-filing-section`

Hosted-runtime-only tools (require a live TerraFinAgentSession; not exposed as stateless HTTP routes):

- `open_chart` — Create or update a chart session bound to the conversation.

<!-- generated:capability-list:end -->

Task helpers are also exported from `TerraFin.agent`.

## Notes

- TerraFin's agent layer uses the same optimized pipeline as the chart and page flows.
- Time-series view transforms match the chart contract.
- Indicator math matches TerraFin's chart indicators.
- DCF math matches what the user sees in the DCF Valuation card on
  `/stock/{ticker}` — the agent and the user are looking at the same model.
- Charts are optional. Structured analysis should usually come first.
- The agent reads view context but **cannot currently write back** to the
  user's frontend form (no `apply_dcf_inputs` / `set_form_state` tool). If
  the user wants the agent to "set Breakeven Year to 3", suggest the values
  in the conversation — the user applies them manually.

## See also

- [`docs/agent/usage.md`](../../docs/agent/usage.md) — full request policy,
  `processing` metadata reference, route summary by category, hosted runtime
  routes (sessions / approvals / tasks).
- [`docs/agent/index.md`](../../docs/agent/index.md) — Glossary of terms
  used across the agent docs (Capability vs Tool vs Skill, persona allowlist
  semantics, view-context contract).
- [`docs/api-reference.md`](../../docs/api-reference.md) — per-route
  documentation for `/stock/api/*` and `/agent/api/*` including the new
  fields on `POST /stock/api/dcf` (`projectionYears`, `fcfBaseSource`,
  turnaround inputs).
- [`docs/analytics-notes.md`](../../docs/analytics-notes.md) — DCF model
  math: base FCF source cascade, projection horizon, turnaround schedule
  formulas, scenario shifts.
