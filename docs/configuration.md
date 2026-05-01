---
title: Configuration
summary: Environment-variable reference for TerraFin's server, data sources, private access, persistence, and hosted models.
---

# Configuration

TerraFin stays side-effect free on import. Runtime entrypoints such as
`terrafin-agent` and `python src/TerraFin/interface/server.py ...` load `.env`
themselves, and notebooks/scripts should call `configure()` explicitly.

## Resolution Rules

Hosted model selection resolves in this order:

1. `TERRAFIN_AGENT_MODEL_REF`
2. saved CLI state from `.terrafin/agent-models.json`
3. legacy `TERRAFIN_OPENAI_MODEL`
4. built-in default `openai/gpt-4.1-mini`

Provider credentials resolve in this order:

1. provider env vars
2. saved CLI credentials in `.terrafin/agent-models.json`

That means ops-managed env vars always override locally saved model-manager
state.

## Core Server

| Variable | Purpose | Notes |
|----------|---------|-------|
| `TERRAFIN_HOST` | FastAPI bind host | Defaults to `127.0.0.1` |
| `TERRAFIN_PORT` | FastAPI bind port | Defaults to `8001` |
| `TERRAFIN_BASE_PATH` | Prefix for feature routes | Root `/health`, `/health.json`, and `/ready` stay unprefixed |
| `TERRAFIN_CACHE_TIMEZONE` | IANA timezone for cache scheduling | Defaults to `UTC` |
| `TERRAFIN_DISABLE_DOTENV` | Disable lazy dotenv loading | Useful for stricter production environments |

## Public Data Sources

| Variable | Purpose |
|----------|---------|
| `FRED_API_KEY` | Enables FRED-backed economic series |
| `TERRAFIN_SEC_USER_AGENT` | Required SEC EDGAR contact string for filings and 13F access |

## Private Access And Watchlist Persistence

| Variable | Purpose |
|----------|---------|
| `TERRAFIN_PRIVATE_SOURCE_ENDPOINT` | Base URL for the private-access endpoint |
| `TERRAFIN_PRIVATE_SOURCE_ACCESS_KEY` | Header name used for private-access auth |
| `TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE` | Header value used for private-access auth |
| `TERRAFIN_PRIVATE_SOURCE_TIMEOUT_SECONDS` | Timeout for private-source requests |
| `TERRAFIN_MONGODB_URI` / `MONGODB_URI` | Optional MongoDB backend for writable watchlists |
| `TERRAFIN_WATCHLIST_MONGODB_DATABASE` | Watchlist database override |
| `TERRAFIN_WATCHLIST_*` | Collection or document overrides for watchlist storage |

## Hosted Agent Model Runtime

| Variable | Purpose |
|----------|---------|
| `TERRAFIN_AGENT_MODEL_REF` | Canonical hosted model ref such as `openai/gpt-4.1` or `github-copilot/gpt-4o` |
| `TERRAFIN_AGENT_MODELS_PATH` | Override path for saved CLI model/auth state |
| `TERRAFIN_AGENT_SESSION_DB_PATH` | Override path for hosted runtime task/approval/view-context state |
| `TERRAFIN_AGENT_TRANSCRIPT_DIR` | Override root directory for hosted transcript JSONL history and `sessions.json` |
| `TERRAFIN_OPENAI_MODEL` | Legacy OpenAI-only model fallback |

Provider credentials:

| Provider | Variables |
|----------|-----------|
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| GitHub Copilot | `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` |

Copilot-specific tuning:

| Variable | Purpose |
|----------|---------|
| `TERRAFIN_COPILOT_TIMEOUT_SECONDS` | Copilot request timeout |
| `TERRAFIN_COPILOT_MAX_RETRIES` | Retry count for the Copilot transport |
| `TERRAFIN_COPILOT_TOKEN_CACHE_PATH` | Override the exchanged Copilot API-token cache path |

## Recommended Local Setup

For local development, the shortest path is:

1. save model auth with `terrafin-agent models auth ...`
2. keep `.env` for public data-source config only
3. let `TERRAFIN_AGENT_MODEL_REF` stay unset unless you want a hard operator override

For CI, Docker, or production:

1. set explicit env vars
2. avoid relying on local saved model state
3. treat `.terrafin/` as machine-local, not deploy config

## Related Docs

- [Getting Started](getting-started.md)
- [Deployment & Operations](deployment.md)
- [Agent Model Management](agent/models.md)
- [Data Layer](data-layer.md)
