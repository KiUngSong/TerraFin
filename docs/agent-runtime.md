---
title: Agent Runtime
summary: Maintainer guide for TerraFin's agent-facing service, client, CLI, route contract, and portability artifacts.
read_when:
  - Changing the agent service, models, CLI, or HTTP routes
  - Debugging agent/chart behavior mismatches
  - Updating the shipped skill or OpenAPI contract
  - Reviewing agent-specific regression coverage
---

# Agent Runtime

This document is for maintainers.

If you are trying to use TerraFin as an agent tool, start with
[agent-skill.md](./agent-skill.md) and the shipped
[`skills/terrafin/SKILL.md`](../skills/terrafin/SKILL.md).

## The rule that matters

Do not create an agent-only shortcut path.

Market and macro agent requests should share the same core behavior as the rest
of the product:

- progressive history where supported
- the same view transforms
- the same indicator math
- explicit top-level `processing` metadata

If chart behavior changes, the agent path should usually change with it.

## Public surfaces to keep aligned

| Surface | Source of truth |
|---------|-----------------|
| Python client | `src/TerraFin/agent/client.py` |
| Task helpers | `src/TerraFin/agent/tasks.py` |
| Shared service | `src/TerraFin/agent/service.py` |
| HTTP routes | `src/TerraFin/interface/agent/data_routes.py` |
| Response models | `src/TerraFin/agent/models.py` |
| Portable skill | `skills/terrafin/SKILL.md` |
| OpenAPI | `/openapi.json` from the FastAPI app |

If one of these changes, check the rest before you call the work done.

## Core runtime path

For market and macro requests, the service should stay on TerraFin's shared
processing path:

- `DataFactory.get_recent_history(...)`
- `DataFactory.get(...)` when full depth is required
- `apply_view(...)`
- chart indicator adapters from
  `src/TerraFin/interface/chart/indicators/adapter.py`

For company info, earnings, financials, portfolios, and calendar data, the
response should still include `processing`, but the payload is expected to be
complete immediately.

## Processing contract

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
- company info, earnings, financials, portfolio, and calendar should be
  complete immediately
- chart-opening helpers are optional utilities, not the core analysis contract

## Current HTTP contract

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
| `GET` | `/agent/api/lppl` | LPPL bubble-confidence summary |
| `GET` | `/agent/api/calendar` | Calendar events |

## When you change the runtime

1. Update `src/TerraFin/agent/models.py` if the public contract changes.
2. Keep service, client, CLI, and HTTP route semantics aligned.
3. Keep [agent-skill.md](./agent-skill.md) and
   [`skills/terrafin/SKILL.md`](../skills/terrafin/SKILL.md) aligned with the
   real public entrypoints.
4. Preserve backward compatibility for existing `/agent/api/*` routes unless
   the user explicitly wants a breaking change.
5. Make sure `/openapi.json` still reflects the actual response models.

## Regression surfaces

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

## Defaults worth defending

- Do not hide partial-history responses. Surface them through `processing`.
- Do not fork indicator logic away from the chart layer.
- Do not add compatibility wrappers unless there is a clear migration need.
- Do not commit secrets, private endpoints, or operator credentials.

## Read next

- [agent-skill.md](./agent-skill.md) for the consumer-facing usage guide
- [interface.md](./interface.md) for the FastAPI route families
- [chart-architecture.md](./chart-architecture.md) for shared chart/session flow
- [data-layer.md](./data-layer.md) for `DataFactory` and provider contracts
