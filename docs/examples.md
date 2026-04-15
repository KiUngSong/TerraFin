---
title: Examples & Workflows
summary: Short examples for Python, CLI, notebooks, and the hosted assistant.
---

# Examples & Workflows

This page collects the most common usage patterns in one place.

## Python: Market Data

```python
from TerraFin import configure
from TerraFin.data import DataFactory

configure()
data = DataFactory()

spy = data.get("S&P 500")
unrate = data.get_fred_data("UNRATE")
portfolio = data.get_portfolio_data("Warren Buffett")
```

## Python: External-Agent Client

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
snapshot = client.market_snapshot("AAPL")
macro = client.macro_focus("Nasdaq", depth="auto", view="weekly")
```

## Python: Hosted Agent Session

```python
from TerraFin.agent import TerraFinAgentClient

client = TerraFinAgentClient()
session = client.runtime_create_session("terrafin-assistant")
reply = client.runtime_message(session["sessionId"], "Compare the S&P 500 and Nasdaq.")
```

## CLI: Data Lookup

```bash
terrafin-agent snapshot AAPL
terrafin-agent indicators AAPL --indicators rsi,macd
terrafin-agent macro-focus "S&P 500" --view weekly
```

## CLI: Model Management

```bash
terrafin-agent models list --all
terrafin-agent models current
terrafin-agent models use google/gemini-3.1-pro-preview
terrafin-agent models auth login-github-copilot --set-default
```

## Notebook: Explicit Bootstrap

```python
from TerraFin import configure, load_terrafin_config

configure()
config = load_terrafin_config()
```

Then call the notebook helpers:

```python
from TerraFin.interface.chart.client import display_chart_notebook

display_chart_notebook(spy)
```

## Browser: View-Aware TerraFin Agent

When you use the hosted assistant widget inside the interface:

- chart, stock, market-insights, and DCF pages publish structured view context
- the assistant can inspect that context with `current_view_context`
- page state is available on demand rather than injected into every prompt

That means prompts like “retrieve information on the top 10 companies in this
portfolio” can resolve against the current page instead of relying on the user
to restate the visible context manually.

## Related Docs

- [Getting Started](getting-started.md)
- [Interface Overview](interface.md)
- [Agent Usage](agent/usage.md)
- [Model Management](agent/models.md)
