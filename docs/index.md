---
title: TerraFin Docs
---

# TerraFin

**TerraFin** is terraform for financial research and investment decisions.
It has four parts:

- **Skills** that give any AI agent (Claude Code, Codex, opencode) a
  financial analyst's toolkit.
- **TerraFin Terminal**, a web dashboard for browsing markets and companies.
    - Try it on the [public demo Space](https://huggingface.co/spaces/sk851/TerraFin),
      a maintainer-operated deployment.
- **Its own agent**, built on the same skills, that sees what you have open in
  the dashboard.
    - Ask "is this cheap?" on a stock page and it knows which ticker you mean.
    - In the filing reader it works from the section you are reading. In the
      DCF workbench it reads the inputs you entered.
- **A data pipeline** that fetches, caches and normalizes each source once, so
  one agent can sweep a whole watchlist or search a stock universe in a few
  calls.

## Architecture

The skills and the harness read one capability registry, which runs on the data pipeline:

```
                    capability registry
                             │
          ┌──────────────────┴──────────────────┐
     skill layer                         TerraFin agent harness
     SKILL.md · /agent/api/* ·           sessions, model providers,
     terrafin-agent CLI · Python client  tool loop, view context
     → Claude Code, Codex, opencode      → chat panel on every page
```

Another agent can also call TerraFin's agent as a sub-agent: open a session
and send it a question over HTTP (`/agent/api/runtime/*`) or the
`terrafin-agent` CLI. It answers with the model configured in TerraFin.

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
./setup   # auto-detects Claude Code / Codex / opencode on PATH
```

Install pattern adapted from [gstack](https://github.com/garrytan/gstack):
symlink-based, so `git pull` upgrades every host at once.

## Pick your track

=== "Use TerraFin's skills from your agent"

    Your agent (Claude Code, Codex, opencode, or anything that speaks HTTP)
    keeps its own model and loop, and calls TerraFin for data, valuation,
    and filings.

    ```bash
    ./setup --host claude    # or codex, opencode, auto
    ```

    - [Skills](skills/index.md): what the skill layer is, install, the
      surfaces, discovery.
    - [Route summary](skills/usage.md#route-summary): every capability with a route, grouped by kind.
    - [For External Agents](skills/external-agents.md): base URL, discovery,
      finding a series by name.
    - [Usage](skills/usage.md): request policy, route summary, the
      view-context read-only contract.

=== "Run TerraFin's own agent"

    TerraFin's harness owns the loop: sessions, model providers, the tool
    loop, and view context, behind a chat panel on every page. Guru personas
    (Buffett, Marks, Druckenmiller) run as hidden subagents. Run it locally
    or as a public deployment.

    - [Getting Started](getting-started/index.md): install, set a model key, run
      the server.
    - [Model Management](getting-started/models.md): choose a provider and model.

    How it works, for contributors: [Agent Harness](harness/index.md),
    [The Agent Loop](harness/loop.md), [Hosted Runtime](harness/hosted-runtime.md),
    [Architecture and Personas](harness/architecture.md).

=== "Contribute to TerraFin"

    Working on TerraFin's internals? Start with the architecture and
    feature-integration rules so your change lands in the right layer.

    - [AGENTS.md](https://github.com/KiUngSong/TerraFin/blob/main/AGENTS.md):
      the entry point for agents and people working in this codebase.
    - [Feature Integration](reference/feature-integration.md): where new logic
      lives across the data, analytics, interface and agent layers.
    - [Data Layer](reference/data-layer.md), [Analytics](reference/analytics.md),
      [Analytics Notes](reference/analytics-notes.md): DCF cascade, turnaround
      math, indicator contract.
    - [Chart Architecture](reference/chart-architecture.md), [Caching](reference/caching.md),
      [Development Guide](development/index.md).

## Also Useful

- [Configuration](getting-started/configuration.md)
- [Deployment & Operations](getting-started/deployment.md)
- [Examples & Workflows](guides/examples.md)
- [License & Data Rights](development/legal.md)

!!! warning "Software rights are not data rights"
    TerraFin's code is MIT-licensed. That does **not** grant rights to Yahoo,
    SEC, FRED, private endpoints, or other upstream data sources. Read
    [License & Data Rights](development/legal.md) before running a public deployment.

## Read By Goal

| If you want to... | Start here |
|-------------------|------------|
| install TerraFin and try it locally | [Getting Started](getting-started/index.md) |
| understand the page routes and APIs | [Interface Overview](guides/interface.md) |
| call TerraFin from your own agent | [Skills](skills/index.md) |
| run TerraFin's own agent | [Agent Harness](harness/index.md) |
| add a provider, indicator, or feature | [Data Layer](reference/data-layer.md) and [Feature Integration](reference/feature-integration.md) |
| operate the server in demo or private mode | [Deployment & Operations](getting-started/deployment.md) |
| work on the repo itself | [Development Guide](development/index.md) |
