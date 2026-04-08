# Agent Runtime

Use this document when you are maintaining TerraFin's agent-facing surfaces.
If you are trying to consume TerraFin as a skill, start with
[agent-skill.md](./agent-skill.md) and `skills/terrafin/SKILL.md` instead.

## Read first

- [README.md](../README.md) for repo shape and install
- [feature-integration.md](./feature-integration.md) for the "where should this logic live?" checklist
- [data-layer.md](./data-layer.md) for `DataFactory` and provider contracts
- [interface.md](./interface.md) for server and public routes
- [chart-architecture.md](./chart-architecture.md) for progressive history and chart/session flow
- [analytics.md](./analytics.md) for indicator math
- [caching.md](./caching.md) for cache policy and provider storage

## Design rule

Do not create an agent-only shortcut path that bypasses TerraFin's optimized
processing pipeline.

Agent consumers should share the same core behavior as the product:

- progressive history where supported
- the same view transforms
- the same indicator math
- explicit `processing` metadata on every response

## Public agent surfaces

### Python

- `TerraFin.agent.TerraFinAgentClient`
- task helpers from `TerraFin.agent`

### CLI

- `terrafin-agent`

### HTTP

- `/agent/api/*`
- `/openapi.json`

### Skill artifact

- `skills/terrafin/SKILL.md`
- `skills/terrafin/agents/openai.yaml`

## Shared implementation points

Keep these layers aligned:

- `src/TerraFin/agent/service.py`
- `src/TerraFin/agent/client.py`
- `src/TerraFin/agent/tasks.py`
- `src/TerraFin/interface/agent/data_routes.py`

For market and macro tasks, the service should rely on:

- `DataFactory.get_recent_history(...)`
- `DataFactory.get(...)` when full depth is required
- `apply_view(...)`
- chart indicator adapter functions

If chart view logic or indicator math changes, check the agent service too.

## Processing metadata contract

Every agent response should expose top-level `processing` with:

- `requestedDepth`
- `resolvedDepth`
- `loadedStart`
- `loadedEnd`
- `isComplete`
- `hasOlder`
- `sourceVersion`
- `view`

Rules:

- market and macro tasks may return recent/progressive results
- company info, earnings, financials, portfolio, and calendar should be complete immediately
- chart-opening helpers are optional utilities, not the core analysis contract

## Current agent routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/agent/api/resolve` | Resolve a free-form name into TerraFin stock or macro routing |
| `GET` | `/agent/api/market-data` | Time-series data with `depth` and `view` |
| `GET` | `/agent/api/indicators` | Shared indicator outputs with `depth` and `view` |
| `GET` | `/agent/api/market-snapshot` | Summary bundle for one instrument |
| `GET` | `/agent/api/company` | Company profile and price summary |
| `GET` | `/agent/api/earnings` | Earnings history |
| `GET` | `/agent/api/financials` | Financial statement table |
| `GET` | `/agent/api/portfolio` | Guru portfolio holdings |
| `GET` | `/agent/api/economic` | Economic indicator series |
| `GET` | `/agent/api/macro-focus` | Macro summary plus series data |
| `GET` | `/agent/api/calendar` | Calendar events |

## Maintenance checklist

When changing the agent runtime:

1. Update `src/TerraFin/agent/models.py` if the public contract changes.
2. Keep Python client, CLI, and HTTP routes aligned on method names and semantics.
3. Keep `docs/agent-skill.md` and `skills/terrafin/SKILL.md` in sync with the real public entrypoints.
4. Preserve backward compatibility for existing `/agent/api/*` routes unless the user explicitly wants a breaking change.
5. Make sure `/openapi.json` still reflects the real response models.

## Test surfaces

Relevant tests:

- `tests/agent/test_service.py`
- `tests/agent/test_client.py`
- `tests/agent/test_cli.py`
- `tests/interface/test_agent_api.py`

Useful commands:

```bash
pytest tests/agent/test_service.py tests/agent/test_client.py tests/agent/test_cli.py tests/interface/test_agent_api.py
ruff check src tests
ruff format --check src tests
```

## Safety defaults

- Do not add agent-specific logic that silently diverges from chart/view behavior.
- Do not hide partial-history responses; surface them through `processing`.
- Do not introduce new compatibility layers unless there is a clear migration need.
- Do not commit secrets, internal endpoints, or provider credentials.

## See also

- [data-layer.md](./data-layer.md) — DataFactory, providers, data types
- [interface.md](./interface.md) — Server, API endpoints, chart client
- [analytics.md](./analytics.md) — Analysis and simulation modules
- [caching.md](./caching.md) — CacheManager, policies, configuration
