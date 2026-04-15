---
title: Agent Model Management
summary: How to inspect, authenticate, and switch TerraFin's hosted agent models from the CLI.
read_when:
  - You want the model-management layer TerraFin adapted from OpenClaw's provider UX
  - You want to use Gemini or GitHub Copilot without editing env vars by hand
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
- the GitHub Copilot device-login flow and local auth workflow

The following parts are TerraFin-specific:

- the saved state format in `.terrafin/agent-models.json`
- runtime resolution order between env vars, saved state, and legacy OpenAI
  config
- how the chosen model binds into TerraFin's hosted runtime, session metadata,
  widget, and FastAPI routes

Implementation lives in TerraFin's own code:

- `src/TerraFin/agent/model_management.py`
- `src/TerraFin/agent/model_runtime.py`
- `src/TerraFin/agent/providers/github_copilot.py`
- `src/TerraFin/agent/providers/google.py`
- `src/TerraFin/agent/providers/openai.py`

## What it manages

The model manager currently handles three providers:

- `openai/*`
- `google/*`
- `github-copilot/*`

It saves state to `.terrafin/agent-models.json` by default. Override that path
with `TERRAFIN_AGENT_MODELS_PATH` when you want a different location.

## Resolution order

When TerraFin resolves the hosted runtime model, it uses this precedence:

1. `TERRAFIN_AGENT_MODEL_REF`
2. saved CLI state from `.terrafin/agent-models.json`
3. legacy `TERRAFIN_OPENAI_MODEL`
4. built-in default `openai/gpt-4.1-mini`

Provider credentials follow the same pattern:

1. provider env vars such as `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `COPILOT_GITHUB_TOKEN`
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
terrafin-agent models use github-copilot/gpt-4o
```

Show provider auth status:

```bash
terrafin-agent models auth status
terrafin-agent models auth status --provider github-copilot
```

## GitHub Copilot login

The convenience command is:

```bash
terrafin-agent models auth login-github-copilot --set-default
```

This now follows the OpenClaw-style GitHub device flow. TerraFin requests a
GitHub device code, shows you the verification URL and one-time code, waits for
authorization, then saves the resulting GitHub token locally for later Copilot
token exchange.

You can still provide the token directly in non-interactive shells:

```bash
terrafin-agent models auth login-github-copilot \
  --token ghu_your_token_here \
  --set-default \
  --yes
```

The generic provider form is also available:

```bash
terrafin-agent models auth login --provider github-copilot --method device --set-default
terrafin-agent models auth login --provider google
terrafin-agent models auth login --provider openai
```

For GitHub Copilot, `--method auto` is the default on the generic command. That
means:

- with `--token`, TerraFin saves the token directly
- without `--token`, TerraFin runs the device-login flow

The device-login flow requires an interactive TTY. Use the token path in CI or
headless scripts.

TerraFin stores the GitHub login token in `.terrafin/agent-models.json`, then
exchanges it server-side for a short-lived Copilot API token when runtime
requests execute. The exchanged Copilot token cache remains separate in
`.terrafin/credentials/github-copilot.token.json`.

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
