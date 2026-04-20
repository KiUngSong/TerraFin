# TerraFin AGENTS.md

Read this file first when working inside the TerraFin repository.

TerraFin is an **agent-friendly** financial-research toolkit with two
supported usage modes (see [README.md](./README.md) "Two ways to use
TerraFin"):

- **Mode A — Hosted TerraFin Agent.** Runtime in `src/TerraFin/agent/` +
  `src/TerraFin/interface/agent/`, browser panel on every page, hidden
  guru routing (Buffett, Marks, Druckenmiller).
- **Mode B — TerraFin as a skill for external agents.** [`skills/terrafin/SKILL.md`](./skills/terrafin/SKILL.md)
  is the source of truth for the public capability surface; external Claude
  Code / Codex / OpenAI Assistants instances consume it directly.

## First stop

- Read [README.md](./README.md) for project shape, install, and the main documentation map.
- Read [skills/terrafin/SKILL.md](./skills/terrafin/SKILL.md) for the
  authoritative list of agent-callable capabilities (27 tools at last count
  including the 14 stateless `/agent/api/*` routes added in the recent
  agent-surface parity work).

## Capability surface (current)

All of these have parity Python (`TerraFinAgentClient`), CLI
(`terrafin-agent`), and HTTP (`/agent/api/*`) surfaces:

- **Data + chart**: `resolve`, `market_data`, `indicators`,
  `market_snapshot`, `company_info`, `earnings`, `financials`, `portfolio`,
  `economic`, `macro_focus`, `lppl_analysis`, `calendar_events`
- **Valuation + fundamentals**: `valuation` (DCF — supports
  `projection_years`, `fcf_base_source`, and turnaround mode via
  `breakeven_year` / `breakeven_cash_flow_per_share` /
  `post_breakeven_growth_pct`), `fcf_history` (3yr-avg / latest-annual / TTM
  candidates + auto-selected source), `sp500_dcf`, `fundamental_screen`,
  `risk_profile`, `beta_estimate`
- **SEC filings**: `sec_filings`, `sec_filing_document`, `sec_filing_section`
- **Sentiment / breadth / market state**: `fear_greed`, `market_regime`,
  `market_breadth`, `trailing_forward_pe`, `top_companies`, `watchlist`

Hosted-runtime-only tools (no stateless HTTP route):

- `current_view_context()` — the agent reads which panel and form state the
  user is currently viewing (DCF input form values, FCF history candidates,
  auto-selected DCF base source, Reverse DCF state, SEC filing section in
  view, etc.). **Read-only.** No corresponding `apply_dcf_inputs` /
  `set_form_state` tool exists today; the agent suggests values in
  conversation and the user applies them manually. This gap is tracked.
- `open_chart(...)` — creates a chart artifact bound to the session.

## Persona allowlists

Persona tool access is defined in YAML files under
[`src/TerraFin/agent/personas/`](./src/TerraFin/agent/personas/). The
`allowed_capabilities` field on each persona is the **single source of
truth** — there is no longer a hidden `_select_guru_worker_tools`
broad-market override (removed in the recent agent-friendly cleanup).

To grant or revoke a capability for Buffett / Marks / Druckenmiller, edit
the corresponding YAML.

## Choose the right path

### If you want to use TerraFin as a skill

Start with:

- [skills/terrafin/SKILL.md](./skills/terrafin/SKILL.md) — install recipe at
  the top (one-shot `cp -r skills/terrafin ~/.claude/skills/`).
- [docs/agent/usage.md](./docs/agent/usage.md)

Use these when the goal is to consume TerraFin through:

- `TerraFin.agent.TerraFinAgentClient`
- `terrafin-agent`
- `/agent/api/*`

### If you are maintaining TerraFin's agent runtime

Start with:

- [docs/agent/hosted-runtime.md](./docs/agent/hosted-runtime.md)
- [docs/agent/architecture.md](./docs/agent/architecture.md)

Use this when changing:

- `src/TerraFin/agent/`
- `src/TerraFin/interface/agent/`
- public agent contracts, client methods, CLI commands, or skill docs

When you add a new capability:

1. Register it in `src/TerraFin/agent/runtime.py` capability list. Populate
   `summary`, `cli_subcommand_name` (if exposed via the CLI), `http_route_path`,
   and `response_model_name` so downstream artefacts can derive accurate
   metadata.
2. Add a parity HTTP route to
   `src/TerraFin/interface/agent/data_routes.py` (the `http_route_path` you
   declared above).
3. Add the recipe / worked example to
   [skills/terrafin/SKILL.md](./skills/terrafin/SKILL.md) — recipe sections
   stay hand-edited.
4. Update the relevant persona YAML in
   `src/TerraFin/agent/personas/` if it should be persona-callable.
5. Run `python scripts/generate-agent-artefacts.py` to refresh the
   sentinel-bounded "Key client methods" list in SKILL.md and the "Route
   summary" table in `docs/agent/usage.md`. CI fails (`pytest
   tests/agent/test_generated_artefacts_match.py`) if you forget. Verify
   externally with `terrafin-agent capabilities --name <new-cap>`.

### If you are adding or extending a feature

Start with:

- [docs/feature-integration.md](./docs/feature-integration.md)

Use this when deciding:

- where the core logic should live
- which UI, chart, agent, docs, and test surfaces must also be updated

## Important rule

Do not create a parallel agent-only shortcut path that bypasses TerraFin's
shared optimized processing pipeline.

Repository hygiene rule:

- `tests/` is only for automated pytest files such as `test_*.py`
- manual notebooks belong under `notebooks/`
- manual notebooks should not use a misleading `test_` filename prefix

For public features:

- data acquisition and normalization belong in the data layer
- reusable math belongs in analytics
- page and session composition belong in the interface layer
- structured programmatic exposure belongs in the agent layer

## Related docs

- [docs/data-layer.md](./docs/data-layer.md)
- [docs/interface.md](./docs/interface.md)
- [docs/chart-architecture.md](./docs/chart-architecture.md)
- [docs/analytics.md](./docs/analytics.md)
- [docs/analytics-notes.md](./docs/analytics-notes.md) — DCF model details
  including the `auto` cascade, turnaround schedule math, and projection
  horizon.
- [docs/api-reference.md](./docs/api-reference.md) — per-route documentation
  for `/stock/api/*` and `/agent/api/*`.
- [docs/caching.md](./docs/caching.md)
