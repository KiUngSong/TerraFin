---
title: Architecture Overview
summary: One-page map of TerraFin's components, with links into the deeper docs for each.
read_when:
  - Onboarding to TerraFin
  - Locating which component owns a behavior before reading detail docs
---

# Architecture Overview

TerraFin is a contract-first stack: every data source returns one of a small
set of predefined contracts, the `DataFactory` is the single facade in front
of those providers, and one `CacheManager` owns refresh and invalidation for
every source.

```
Routes / Agent / Frontend
        ↓
   DataFactory ──── CacheManager (uniform cache for all sources)
        ↓
   Providers (all return predefined contracts only)
   ├── yfinance        (market data, fundamentals)
   ├── FRED            (economic indicators)
   ├── market indicator (VIX, MOVE, ...)
   ├── economic        (UNRATE, M2, derived indicators)
   ├── private_access  (CAPE, fear/greed, breadth, P/E spread — HTTP to sibling DataFactory)
   ├── SEC EDGAR       (filings, 13F)
   └── corporate       (yfinance fundamentals)
```

## Signal pipeline

Signals (`name`, `ticker`, `severity`, `message`, `snapshot`) flow into
TerraFin from two directions, sharing one dataclass. The **pull side** is
`analytics/analysis/patterns/` — call `evaluate(ticker, ohlc)` and get
back any patterns that match the latest bar (used by the agent flow,
weekly reports, ad-hoc backtests). The **push side** is
`interface/monitor/` — an external realtime monitor service (DataFactory)
holds a broker WebSocket open, runs intraday detectors, and POSTs each
fired event to `/signals/api/signal`, where it is HMAC-verified, deduped,
and forwarded to the user's Telegram via `interface/channels/`.

## Components

- [Data Layer](./data-layer.md) — providers, contracts, `DataFactory`, caching
- [Interface Overview](./interface.md) — HTTP routes and page composition
- [Chart Architecture](./chart-architecture.md) — chart sessions, progressive history
- [Analytics](./analytics.md) — reusable indicator and valuation math
- [Agent Overview](./agent/index.md) — the hosted agent runtime built on top
- [Caching](./caching.md) — refresh policies and file-cache layout
- [Feature Integration](./feature-integration.md) — where new logic should live
- [License & Data Rights](./legal.md) — deployment and upstream data responsibilities

The single most important rule across components: providers never expose
ad-hoc dicts. They return a contract from `src/TerraFin/data/contracts/`, and
everything downstream — routes, agent, frontend — depends only on those
contract types.
