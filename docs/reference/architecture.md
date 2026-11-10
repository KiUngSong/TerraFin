---
title: Architecture Overview
summary: One-page map of TerraFin's components, with links into the deeper docs for each.
read_when:
  - Onboarding to TerraFin
  - Locating which component owns a behavior before reading detail docs
---

# Architecture Overview

TerraFin is a contract-first stack:

- Every data source returns one of a small set of predefined contracts.
- `DataFactory` is the single facade in front of those providers.
- One `CacheManager` owns refresh and invalidation for every source.

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
TerraFin from two directions, sharing one dataclass.

- **Pull side:** `analytics/analysis/patterns/`.
    - Call `evaluate(ticker, ohlc)` to get any patterns that match the latest bar.
    - Used by the agent flow, weekly reports and ad-hoc backtests.
- **Push side:** `interface/infra/monitor/`.
    - An external realtime monitor service (DataFactory) holds a broker
      WebSocket open and runs intraday detectors.
    - It POSTs each fired event to `/signals/api/signal`.
    - TerraFin HMAC-verifies and dedupes the event, then forwards it to the
      user's Telegram via `interface/infra/channels/`.

## Components

- [Data Layer](data-layer.md): providers, contracts, `DataFactory`, caching
- [Interface Overview](../guides/interface.md): HTTP routes and page composition
- [Chart Architecture](chart-architecture.md): chart sessions, progressive history
- [Analytics](analytics.md): reusable indicator and valuation math
- [Agent Overview](../skills/glossary.md): the hosted agent runtime built on top
- [Caching](caching.md): refresh policies and file-cache layout
- [Feature Integration](feature-integration.md): where new logic should live
- [License & Data Rights](../development/legal.md): deployment and upstream data responsibilities

The most important rule across components:

- **Providers never expose ad-hoc dicts.** They return a contract from
  `src/TerraFin/data/contracts/`.
- Everything downstream (routes, agent, frontend) depends only on those
  contract types.
