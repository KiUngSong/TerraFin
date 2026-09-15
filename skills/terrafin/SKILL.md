---
name: terrafin
description: Use when an agent needs structured market, macro, portfolio, calendar, fundamentals, valuation (DCF / reverse DCF / S&P 500 DCF, including turnaround mode), SEC filings, sentiment/breadth, or watchlist research through TerraFin's optimized processing pipeline, including progressive history metadata and optional chart opening.
version: "0.0.2"
allowed-tools:
  - Bash
  - Read
  - WebFetch
triggers:
  - terrafin
  - treasury
  - treasury yield
  - 10-year
  - 30-year
  - yield curve
  - term spread
  - credit spread
  - interest rate
  - 국채
  - 금리
  - indicator
  - indicator search
  - macro indicator
  - economic indicator
  - time series
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
TerraFin's server separately — see "Choose the entrypoint" below, which
also defines the `$TF` base URL every example uses.

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

- `TERRAFIN_AGENT_MODEL_REF` — `provider/model`, e.g. `openai/gpt-4.1` or `google/gemini-2.5-pro`.
- One of `OPENAI_API_KEY`, `GEMINI_API_KEY` — must match the provider in `TERRAFIN_AGENT_MODEL_REF`.

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
client.market_data("MOH")
```

`valuation` has no client method — reach it over HTTP or the CLI (see
"Choose the entrypoint"). The client covers a subset of the capabilities, so
check before assuming a method exists; `python -c "from TerraFin.agent import
TerraFinAgentClient; print([m for m in dir(TerraFinAgentClient) if not
m.startswith('_')])"` lists what it actually has. The `## Capability
inventory` section below groups capabilities by HTTP route, not by client
method, so it cannot answer this question for you.

CLI:

```bash
terrafin-agent snapshot AAPL
```

HTTP — the widest surface: nearly every capability has a route under
`/agent/api/*`. The few that do not are session-bound or in-process only;
reach those through the capability registry. The generated section
`## Capability inventory` below is regenerated from the registry, so its
"Hosted-runtime-only tools" sub-list names the exceptions and stays correct as
they change. Read it there rather than trusting names or a number written into
prose.

The server's address comes from `TERRAFIN_HOST`, `TERRAFIN_PORT` and
`TERRAFIN_BASE_PATH` (see `.env.example`), so derive it rather than
hardcoding — every example below uses `$TF`:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"

curl "$TF/agent/api/market-snapshot?ticker=AAPL"
curl "$TF/agent/api/valuation?ticker=MOH&projection_years=10&fcf_base_source=3yr_avg"
curl "$TF/agent/api/fcf-history?ticker=GOOGL&years=10"
```

## Programmatic capability discovery

Don't enumerate capabilities by parsing this Markdown — TerraFin is FastAPI,
so the canonical machine-readable surface is the **live OpenAPI spec**:

```bash
# Full OpenAPI document for the running TerraFin server
curl $TF/openapi.json

# Filter to just the stateless agent capability routes
curl -s $TF/openapi.json \
  | jq '.paths | with_entries(select(.key | startswith("/agent/api/") and (contains("/runtime") | not)))'
```

Each path entry carries the parameter schema (types, enums, ranges,
defaults), the response model, and the route's `summary` /  `description`.
That's the source of truth for argument validation — prefer it over copy-
pasting from the reference files when you're building a programmatic call
generator.

The recipes under `references/` are still useful for:

- learning *when* to call which capability (the LLM-readable intent),
- worked examples showing the parameter combinations the model trained on
  (DCF turnaround in `references/valuation.md`, the SEC filings 3-step recipe
  in `references/filings-and-news.md`, the FCF Base Source picker),
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

Recipes live in reference files — read the one your task needs:

- [references/market-and-indicators.md](references/market-and-indicators.md) — find what a series is called, macro/market history, snapshots, compare, calendar, patterns, similarity, LPPL, sentiment/breadth
- [references/valuation.md](references/valuation.md) — DCF (forward + turnaround), reverse DCF, S&P 500 DCF, FCF history, beta, fundamentals
- [references/filings-and-news.md](references/filings-and-news.md) — SEC filings, headlines, forward consensus, claim verification
- [references/portfolio-and-session.md](references/portfolio-and-session.md) — guru portfolios, watchlist, top companies, current view, chart

Start with `references/market-and-indicators.md` when you need a number and
do not yet know what TerraFin calls it.

## Capability inventory

<!-- The two lists below are auto-generated from src/TerraFin/agent/runtime/capability.py
     by `python scripts/generate-agent-artefacts.py`. Edit the registry, not
     these lines. Hand-edits here will be overwritten on the next regen. -->

<!-- generated:capability-list:begin -->

Stateless data + analysis (each has a matching `/agent/api/*` HTTP route):

- `resolve` — Resolve a free-form query into a TerraFin route. `GET /agent/api/resolve`
- `indicator_search` — Find an indicator's catalog name by substring. `GET /agent/api/indicator-search`
- `market_data` — Chart-ready OHLC time series for one asset. `GET /agent/api/market-data`
- `indicators` — Chart-matching technical indicators for one asset. `GET /agent/api/indicators`
- `patterns` — Named market patterns matching the latest bar for one asset. `GET /agent/api/patterns`
- `news` — Recent headlines for a ticker or query (metadata only). `GET /agent/api/news`
- `consensus` — Forward EPS/revenue consensus, revisions, and price targets. `GET /agent/api/consensus`
- `pattern_scan` — Sweep a watchlist group or ticker list for pattern triggers. `GET /agent/api/pattern-scan`
- `market_snapshot` — Compact market snapshot for one asset. `GET /agent/api/market-snapshot`
- `lppl_analysis` — LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection). `GET /agent/api/lppl`
- `company_info` — Company profile and valuation fields for a ticker. `GET /agent/api/company`
- `earnings` — Earnings history (estimate / reported / surprise) for a ticker. `GET /agent/api/earnings`
- `financials` — Financial statement table (income / balance / cashflow) for a ticker. `GET /agent/api/financials`
- `portfolio` — Guru 13F book — not the user's holdings. `GET /agent/api/portfolio`
- `economic` — Economic indicator series (FRED-backed). `GET /agent/api/economic`
- `macro_focus` — Macro summary plus chart-ready series for one instrument. `GET /agent/api/macro-focus`
- `calendar_events` — TerraFin calendar events for a month. `GET /agent/api/calendar`
- `fear_greed` — CNN Fear & Greed index — score, rating, history. `GET /agent/api/fear-greed`
- `sp500_dcf` — Full S&P 500 DCF valuation (scenarios, sensitivity, methods). `GET /agent/api/sp500-dcf`
- `beta_estimate` — 5-year monthly beta with adjusted beta, R², benchmark. `GET /agent/api/beta-estimate`
- `fcf_history` — FCF history + 3yr-avg / latest-annual / TTM candidates. `GET /agent/api/fcf-history`
- `similarity_search` — Chart-pattern similarity search across a stock universe. `GET /agent/api/similarity-search`
- `top_companies` — Top companies by market cap (private API or yfinance fallback). `GET /agent/api/top-companies`
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
