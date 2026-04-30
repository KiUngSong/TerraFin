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
