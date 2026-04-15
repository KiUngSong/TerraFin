---
title: TerraFin Docs
---

# TerraFin

TerraFin documentation for installation, interface routes, data providers,
analytics modules, and the hosted agent runtime.

## Start Here

- [Getting Started](getting-started.md)
  Install TerraFin, configure the runtime, and run the first Python, CLI, and interface flows.

- [Interface Overview](interface.md)
  Understand the FastAPI app, page routes, session model, and main API families.

- [Agent Docs](agent/index.md)
  Use TerraFin from external agents, manage models, and understand the hosted runtime.

- [Reference](data-layer.md)
  Dive into the data layer, analytics, caching, chart architecture, and feature integration rules.

## Also Useful

- [Development Guide](development.md)
- [API Reference](api-reference.md)
- [License & Data Rights](legal.md)

## What TerraFin Includes

| Area | Purpose |
|------|---------|
| Data layer | Unified access to market, economic, corporate, and private-access data |
| Analytics | Technical indicators, DCF tooling, risk helpers, and standalone analysis modules |
| Interface | FastAPI app with chart, dashboard, stock, market-insights, calendar, and watchlist surfaces |
| Agent harness | Shared capability kernel, hosted runtime, model-provider registry, and browser widget |
| Cache system | In-memory and on-disk warming, fallback behavior, and refresh coordination |

!!! warning "Software rights are not data rights"
    TerraFin's code is MIT-licensed. That does **not** grant rights to Yahoo,
    SEC, FRED, private endpoints, or other upstream data sources. Read
    [License & Data Rights](legal.md) before running a public deployment.

## Read By Goal

| If you want to... | Start here |
|-------------------|------------|
| install TerraFin and try it locally | [Getting Started](getting-started.md) |
| understand the page routes and APIs | [Interface Overview](interface.md) |
| use TerraFin from an external or hosted agent | [Agent Docs](agent/index.md) |
| add a provider, indicator, or feature | [Data Layer](data-layer.md) and [Feature Integration](feature-integration.md) |
| operate the server in demo or private mode | [Deployment & Operations](deployment.md) |
| work on the repo itself | [Development Guide](development.md) |
