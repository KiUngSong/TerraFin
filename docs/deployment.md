---
title: Deployment & Operations
summary: Running TerraFin in local, demo, and operator-managed environments.
---

# Deployment & Operations

This page is the operational companion to [Getting Started](getting-started.md).
It focuses on running the interface safely and predictably.

## Start Modes

Run the interface from `src/TerraFin/interface/`.

```bash
python server.py run
python server.py start
python server.py stop
python server.py status
python server.py restart
```

| Command | Use when... |
|---------|-------------|
| `run` | You want a foreground dev server |
| `start` | You want a simple background process on one machine |
| `stop` | You need to stop the background process if it exists |
| `status` | You are checking whether the PID-managed process is alive |
| `restart` | You changed env vars or saved model credentials |

## Health And Readiness

These endpoints stay at the root even when `TERRAFIN_BASE_PATH` is set:

| Path | Purpose |
|------|---------|
| `/health` | Multi-component status page (HTML). Active probes for Agent / Telegram / Signals Provider with 30 s in-process cache and 2 s per-probe timeout. Append `?refresh=1` to bypass the cache. |
| `/health.json` | Same data as JSON for scripts and uptime checks |
| `/ready` | Readiness check with cache-manager and private-data validation |

Use `/ready` for orchestration startup gating; use `/health.json` for
periodic uptime probes (scrape interval should be ≥ the 30 s cache TTL to
avoid wasted upstream calls). The HTML `/health` is meant for humans
opening the page in a browser.

## Base Paths

`TERRAFIN_BASE_PATH` prefixes the feature routes, but not the health endpoints.

Example:

- `TERRAFIN_BASE_PATH=/terrafin`
- page routes become `/terrafin/chart`, `/terrafin/dashboard`, and so on
- `/health` and `/ready` remain unchanged

## Public / Demo Mode

TerraFin can run without private infrastructure.

Recommended public-safe baseline:

1. copy `.env.example` to `.env`
2. leave `TERRAFIN_PRIVATE_SOURCE_*` unset
3. optionally configure `FRED_API_KEY`
4. set `TERRAFIN_SEC_USER_AGENT` if you want SEC-backed features

In this mode:

- public market and economic providers still work
- private-only widgets fall back to bundled fixtures or empty defaults
- writable watchlists stay disabled unless MongoDB is configured

## Operator-Managed Mode

Use operator-managed mode when you want:

- private market-insight or dashboard data
- writable watchlists
- explicit hosted model/provider control
- a deployment-specific auth and persistence boundary

At minimum, define:

- `TERRAFIN_PRIVATE_SOURCE_*` for the private endpoint
- `TERRAFIN_MONGODB_URI` if you want watchlist writes
- provider credentials or `terrafin-agent models ...` state for hosted agent use

## Hosted Agent Operational Notes

- Restart the server after changing saved model-manager state.
- Sessions pin a resolved `provider/model` on creation, so new env changes do
  not silently rewrite existing sessions.
- GitHub Copilot login stores the GitHub token locally, then exchanges it for a
  short-lived Copilot API token at runtime.

## Formal Docs Hosting

This repo now includes a formal docs site scaffold using MkDocs Material and a
GitHub Pages workflow:

- site config: `mkdocs.yml`
- local preview: `mkdocs serve`
- CI build/deploy: `.github/workflows/docs-pages.yml`

That keeps the docs static-hostable on GitHub without depending on a separate
publish repo or docs SaaS.

### GitHub Pages Source

The workflow deploys through GitHub Actions, not by publishing the repository
root or `docs/` folder directly.

If `https://kiungsong.github.io/TerraFin/` is still showing the repository
README instead of the MkDocs site, the repository is almost certainly still set
to branch-based Pages publishing.

For this workflow to take over, switch the repository once in:

1. `Settings`
2. `Pages`
3. `Build and deployment`
4. `Source = GitHub Actions`

If that switch is not made, `actions/deploy-pages` may fail with a `404`, and
the old branch-based README site will continue to be served.

## Related Docs

- [Configuration](configuration.md)
- [Interface Overview](interface.md)
- [Agent Model Management](agent/models.md)
- [License & Data Rights](legal.md)
