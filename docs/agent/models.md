---
title: Agent Model Management
summary: How to inspect, authenticate, and switch TerraFin's hosted agent models from the CLI.
read_when:
  - You want the model-management layer TerraFin adapted from OpenClaw's provider UX
  - You want to use Gemini without editing env vars by hand
  - You need to understand how saved model/auth state interacts with runtime env vars
---

# Agent Model Management

TerraFin's hosted assistant now supports a small built-in model manager through
the `terrafin-agent models ...` CLI.

This layer exists for the same reason it does in OpenClaw: the provider runtime
is much more usable when people can inspect models, save credentials, and
switch defaults without editing `.env` every time.

## Attribution

The following parts of TerraFin's model-management UX were inspired by
OpenClaw:

- canonical `provider/model` refs
- the `models list/current/use/auth ...` command shape

The following parts are TerraFin-specific:

- the saved state format in `.terrafin/agent-models.json`
- runtime resolution order between env vars, saved state, and legacy OpenAI
  config
- how the chosen model binds into TerraFin's hosted runtime, session metadata,
  widget, and FastAPI routes

Implementation lives in TerraFin's own code:

- `src/TerraFin/agent/models/management.py` (public surface:
  `list_provider_catalog()`, `get_provider_catalog(provider_id)` — do not
  reach into the private `_PROVIDER_CATALOG` dict)
- `src/TerraFin/agent/models/runtime.py`
- `src/TerraFin/agent/models/providers/google.py`
- `src/TerraFin/agent/models/providers/openai.py`

The old top-level paths (`agent/model_management.py`, `agent/model_runtime.py`,
`agent/providers/*`) remain as compatibility shims that re-export the new
locations.

## What it manages

The model manager currently handles two providers:

- `openai/*`
- `google/*`

It saves state to `.terrafin/agent-models.json` by default. Override that path
with `TERRAFIN_AGENT_MODELS_PATH` when you want a different location.

## Resolution order

When TerraFin resolves the hosted runtime model, it uses this precedence:

1. `TERRAFIN_AGENT_MODEL_REF`
2. saved CLI state from `.terrafin/agent-models.json`
3. legacy `TERRAFIN_OPENAI_MODEL`
4. built-in default `openai/gpt-4.1-mini`

Provider credentials follow the same pattern:

1. provider env vars such as `OPENAI_API_KEY` or `GEMINI_API_KEY`
2. saved CLI credentials in `.terrafin/agent-models.json`

That means env vars still win when both are present.

## Common commands

List providers:

```bash
terrafin-agent models list
```

List providers and featured model refs:

```bash
terrafin-agent models list --all
```

Show the model TerraFin would use if the hosted runtime started now:

```bash
terrafin-agent models current
```

Switch the saved default model:

```bash
terrafin-agent models use google/gemini-3.1-pro-preview
```

Show provider auth status:

```bash
terrafin-agent models auth status
terrafin-agent models auth status --provider google
```

## Provider login

Save a provider credential and optionally pin it as the default model:

```bash
terrafin-agent models auth login --provider google --set-default
terrafin-agent models auth login --provider openai
```

Without `--token`, TerraFin prompts for the credential on an interactive TTY.
Pass `--token` in CI or headless scripts.

No provider supports device login; `--method device` is rejected.

## Running server note

If TerraFin's FastAPI server is already running, restart it after changing the
saved default model or saved credentials:

```bash
cd src/TerraFin/interface
python server.py restart
```

The CLI updates the saved state immediately, but a running hosted runtime keeps
its provider clients and default model selection in memory until restart.

## When to still use env vars

Env vars are still the right choice when:

- you are deploying TerraFin in CI, Docker, or a hosted environment
- secrets should come from an operator-managed secret store
- you want explicit per-process overrides

For local development and day-to-day switching, `terrafin-agent models ...` is
usually the easier path.
