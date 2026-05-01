---
title: API Reference
summary: Route map for TerraFin's page APIs, chart APIs, and hosted assistant APIs.
---

# API Reference

TerraFin serves one FastAPI application with several route families. This page
is the quick route map; the deeper behavior and state model live in
[Interface Overview](interface.md).

OpenAPI is available at `/openapi.json`.

## Root And Operational Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Redirect to the dashboard page |
| `GET` | `/health` | Multi-component status page (HTML, 30 s in-process cache, `?refresh=1` to force) |
| `GET` | `/health.json` | Same data as JSON |
| `GET` | `/ready` | Readiness endpoint |

## Chart

Prefix: `/chart/api/*`

Key routes:

- `GET /chart/api/chart-data`
- `POST /chart/api/chart-data`
- `POST /chart/api/chart-view`
- `GET /chart/api/chart-selection`
- `POST /chart/api/chart-selection`
- `POST /chart/api/chart-series/add`
- `POST /chart/api/chart-series/set`
- `POST /chart/api/chart-series/progressive/set`
- `POST /chart/api/chart-series/progressive/backfill`
- `POST /chart/api/chart-series/remove`
- `GET /chart/api/chart-series/names`
- `GET /chart/api/chart-series/search`

## Dashboard

Prefix: `/dashboard/api/*`

Representative routes include watchlist, breadth, valuation, and cache-backed
widget payloads. See [Interface Overview](interface.md) for the current widget
contract and private-access fallback behavior.

## Market Insights

Prefix: `/market-insights/api/*`

Representative routes include:

- guru portfolio views
- top-company payloads
- S&P 500 DCF payloads
- market-regime and macro widgets

## Stock Analysis

Prefix: `/stock/api/*`

Representative routes include:

- `GET /stock/api/overview?ticker=...`
- `GET /stock/api/dcf?ticker=...&projectionYears=5|10|15`
- `POST /stock/api/dcf?ticker=...` — accepts a `StockDCFRequest` body to override
  derived inputs. Beyond the existing `baseCashFlowPerShare`, `baseGrowthPct`,
  `terminalGrowthPct`, `beta`, `equityRiskPremiumPct`, `currentPrice` fields, the
  body now supports:
  - `projectionYears` (5 | 10 | 15) — explicit DCF horizon. Treasury rate curve
    is sized to match.
  - `fcfBaseSource` (`auto` | `3yr_avg` | `ttm` | `latest_annual`) — picks the
    base FCF/share. `auto` cascades 3yr_avg → annual → ttm. Default is `auto`.
  - `breakevenYear`, `breakevenCashFlowPerShare`, `postBreakevenGrowthPct` —
    when all three are supplied, the model switches to **turnaround mode**: the
    base FCF/share input becomes the *current* (possibly negative) FCF; the
    schedule linearly interpolates from current FCF to the breakeven value
    across `breakevenYear` years, then compounds at the post-breakeven rate
    fading toward terminal growth.
- `GET /stock/api/reverse-dcf?ticker=...`
- `GET /stock/api/beta-estimate?ticker=...`
- `GET /stock/api/fcf-history?ticker=...&years=10` — returns annual FCF/share
  history plus the base candidates the DCF would use:
  - `history`: chronological list of `{year, fcf, fcfPerShare}` (NaN years
    dropped, oldest→newest).
  - `ttmFcfPerShare`, `ttmSource` — most recent trailing-12-month value from
    quarterly cashflow when ≥4 quarters available, else latest annual.
  - `candidates`: `{threeYearAvg, latestAnnual, ttm}` per-share values, each
    nullable when the underlying data is absent.
  - `autoSelectedSource` — which candidate the backend's `auto` cascade would
    pick under the current data (one of `3yr_avg`, `annual`, `quarterly_ttm`,
    `missing`).
  - `sharesOutstanding`, `sharesNote` — caveat that per-year FCF/share is
    computed using *current* sharesOutstanding (no per-year dilution
    adjustment).

## Calendar

Prefix: `/calendar/api/*`

Representative routes include macro and earnings event payloads plus
session-scoped calendar selection state.

## Agent Data APIs

Prefix: `/agent/api/*`

Current external-agent routes:

- `GET /agent/api/resolve`
- `GET /agent/api/market-data`
- `GET /agent/api/indicators`
- `GET /agent/api/market-snapshot`
- `GET /agent/api/company`
- `GET /agent/api/earnings`
- `GET /agent/api/financials`
- `GET /agent/api/portfolio`
- `GET /agent/api/economic`
- `GET /agent/api/macro-focus`
- `GET /agent/api/lppl`
- `GET /agent/api/calendar`

## Hosted Agent Runtime

Prefix: `/agent/api/runtime/*`

Core routes:

- `GET /agent/api/runtime/agents`
- `POST /agent/api/runtime/sessions`
- `GET /agent/api/runtime/sessions/{session_id}`
- `POST /agent/api/runtime/sessions/{session_id}/messages`
- `GET /agent/api/runtime/sessions/{session_id}/tasks`
- `GET /agent/api/runtime/sessions/{session_id}/approvals`
- `GET /agent/api/runtime/tasks/{task_id}`
- `POST /agent/api/runtime/tasks/{task_id}/cancel`
- `GET /agent/api/runtime/approvals/{approval_id}`
- `POST /agent/api/runtime/approvals/{approval_id}/approve`
- `POST /agent/api/runtime/approvals/{approval_id}/deny`

## Session Model

The important rule for route consumers is that stateful APIs are session-scoped.

- chart and calendar state default to the `"default"` session unless overridden
- browser flows usually use a per-tab session id
- hosted assistant sessions are persisted separately from chart sessions

For the implementation details, read [Interface Overview](interface.md) and
[Hosted Runtime](agent/hosted-runtime.md).
