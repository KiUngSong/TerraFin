---
title: TerraFin Docs
---

# TerraFin

An **agent-friendly** financial-research toolkit: 27 capabilities (DCF with
turnaround mode, reverse DCF, FCF history, SEC filings TOC + section bodies,
sentiment widgets, market breadth, guru portfolios, view-context reader)
callable from Claude Code, Codex, opencode, or TerraFin's own hosted agent.

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
./setup   # auto-detects Claude Code / Codex / opencode on PATH
```

Install pattern adapted from [gstack](https://github.com/garrytan/gstack) —
symlink-based, so `git pull` upgrades every host at once.

## What TerraFin Includes

| Area | Purpose |
|------|---------|
| Data layer | Unified access to market, economic, corporate, and private-access data |
| Analytics | Technical indicators, DCF tooling, risk helpers, and standalone analysis modules |
| Interface | FastAPI app with chart, dashboard, stock, market-insights, calendar, and watchlist surfaces |
| Agent harness | Shared capability kernel, hosted runtime, model-provider registry, and browser widget |
| Cache system | In-memory and on-disk warming, fallback behavior, and refresh coordination |

## Pick your track

=== "Mode A — Hosted TerraFin Agent"

    The TerraFin Agent runtime ships with a floating chat panel on every
    dashboard page, hidden guru routing (Buffett, Marks, Druckenmiller),
    and view-context awareness. Run it locally or as a public deployment.

    - [Getting Started](getting-started.md) — install, configure, run the
      first server.
    - [Hosted Runtime](agent/hosted-runtime.md) — runtime architecture,
      model bindings, session state.
    - [Agent Architecture](agent/architecture.md) — capability kernel,
      orchestrator-as-tool persona routing.
    - [Model Management](agent/models.md) — provider catalog, credentials,
      `provider/model` refs.

=== "Mode B — Skill for external agents (Claude Code, Codex, …)"

    Drop [`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
    into your agent's skill folder (or let `./setup` above do it) and
    TerraFin's full capability surface becomes callable from any
    Anthropic-Skills-compatible agent. External agents can also hit
    `/agent/api/*` over HTTP directly.

    ```bash
    ./setup --host claude    # or codex, opencode, auto
    ```

    - [Agent Docs Overview](agent/index.md) — surfaces, transports,
      disclosure rules.
    - [Agent Usage](agent/usage.md) — request policy, route summary, the
      view-context read-only contract, the form-mutation gap.
    - [API Reference](api-reference.md) — per-route docs for `/stock/api/*`
      and `/agent/api/*`.

=== "Maintainer / contributor"

    Working on TerraFin's internals? Start with the architecture and
    feature-integration rules so your change lands in the right layer.

    - [AGENTS.md](https://github.com/KiUngSong/TerraFin/blob/main/AGENTS.md) —
      repo-internal entry point for agents (and human contributors)
      working in this codebase.
    - [Feature Integration](feature-integration.md) — where new logic
      lives across data / analytics / interface / agent layers.
    - [Data Layer](data-layer.md), [Analytics](analytics.md),
      [Analytics Notes](analytics-notes.md) — DCF cascade, turnaround
      math, indicator contract.
    - [Chart Architecture](chart-architecture.md), [Caching](caching.md),
      [Development Guide](development.md).

## Also Useful

- [Configuration](configuration.md)
- [Deployment & Operations](deployment.md)
- [Examples & Workflows](examples.md)
- [License & Data Rights](legal.md)

!!! warning "Software rights are not data rights"
    TerraFin's code is MIT-licensed. That does **not** grant rights to Yahoo,
    SEC, FRED, private endpoints, or other upstream data sources. Read
    [License & Data Rights](legal.md) before running a public deployment.

## Read By Goal

| If you want to... | Start here |
|-------------------|------------|
| install TerraFin and try it locally | [Getting Started](getting-started.md) |
| understand the page routes and APIs | [Interface Overview](interface.md) |
| use TerraFin from an external or hosted agent | [Agent Docs](agent/index.md) |
| add a provider, indicator, or feature | [Data Layer](data-layer.md) and [Feature Integration](feature-integration.md) |
| operate the server in demo or private mode | [Deployment & Operations](deployment.md) |
| work on the repo itself | [Development Guide](development.md) |
