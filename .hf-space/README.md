---
title: TerraFin
emoji: 📈
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
---

# TerraFin

TerraFin is an agent-ready Python toolkit and FastAPI interface for pulling
financial data, normalizing it into chart-ready frames, running lightweight
analytics, and serving browser-based views for research, educational, and
agent-driven workflows. This Space combines:

- chart-first market exploration
- agent runtime, API surfaces, and reusable workflows
- stock analysis and valuation tools
- market-insights pages
- optional private-source dashboard widgets

This Space runs the Docker deployment of TerraFin.

## Runtime configuration

Set these in the Space settings before the first build:

- Variables
  - `TERRAFIN_HOST=0.0.0.0`
  - `TERRAFIN_PORT=7860`
  - `TERRAFIN_PRIVATE_SOURCE_ACCESS_KEY=X-API-Key`
  - `TERRAFIN_PRIVATE_SOURCE_TIMEOUT_SECONDS=10`
  - `TERRAFIN_CACHE_TIMEZONE=America/New_York`
- Secrets
  - `TERRAFIN_PRIVATE_SOURCE_ENDPOINT`
  - `TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE`

Optional secrets:

- `TERRAFIN_SEC_USER_AGENT`
- `FRED_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

This Space is synced from the GitHub TerraFin repository.
