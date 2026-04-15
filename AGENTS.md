# TerraFin AGENTS.md

Read this file first when working inside the TerraFin repository.

## First stop

- Read [README.md](./README.md) for project shape, install, and the main documentation map.

## Choose the right path

### If you want to use TerraFin as a skill

Start with:

- [skills/terrafin/SKILL.md](./skills/terrafin/SKILL.md)
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
- [docs/caching.md](./docs/caching.md)
