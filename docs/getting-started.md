---
title: Getting Started
summary: Install TerraFin, configure the runtime, and run the first Python, CLI, and hosted-agent flows.
---

# Getting Started

This page is the shortest path from clone to a working TerraFin environment.

## Prerequisites

- Python 3.11+
- A local `.env` file if you want FRED, SEC EDGAR, private-access widgets, or
  hosted-model credentials

## Install

Core install:

```bash
pip install .
```

Editable install:

```bash
pip install -e .
```

Useful extras:

```bash
pip install -e ".[dev]"
pip install -e ".[db]"
pip install -e ".[notebooks]"
```

## Configure The Runtime

Start with the example file:

```bash
cp .env.example .env
```

The most common env vars are:

| Variable | Why you care |
|----------|---------------|
| `FRED_API_KEY` | Enables FRED-backed economic series |
| `TERRAFIN_SEC_USER_AGENT` | Required for SEC EDGAR filings and guru 13F holdings |
| `TERRAFIN_HOST` / `TERRAFIN_PORT` | Server bind address |
| `TERRAFIN_AGENT_MODEL_REF` | Hosted model ref in `provider/model` format |
| `TERRAFIN_AGENT_TRANSCRIPT_DIR` | Optional override for local hosted chat history storage |

For the full matrix, read [Configuration](configuration.md).

## First Python Request

```python
from TerraFin import configure
from TerraFin.data import DataFactory

configure()
data = DataFactory()

spy = data.get("S&P 500")
aapl = data.get("AAPL")
```

## First CLI Request

```bash
terrafin-agent snapshot AAPL
terrafin-agent macro-focus "S&P 500" --view weekly
```

## First Hosted Agent Session

```bash
terrafin-agent runtime-create-session terrafin-assistant
```

Then send a message:

```bash
terrafin-agent runtime-message runtime:example "Give me a compact AAPL market snapshot."
```

The hosted assistant can also be used from the browser widget once the
interface server is running.

Hosted agent chat history is stored locally as transcript files under
`.terrafin/agent/sessions/` by default.

## Run The Interface

From `src/TerraFin/interface/`:

```bash
python server.py run
```

Useful commands:

| Command | Behavior |
|---------|----------|
| `python server.py run` | Run in the foreground |
| `python server.py start` | Start in the background |
| `python server.py stop` | Stop the background process |
| `python server.py status` | Show whether the background process is running |
| `python server.py restart` | Restart the background process |

Default pages:

| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:8001/chart` | Interactive chart surface |
| `http://127.0.0.1:8001/dashboard` | Dashboard and cache status |
| `http://127.0.0.1:8001/market-insights` | Macro and portfolio views |
| `http://127.0.0.1:8001/stock/AAPL` | Stock analysis page |
| `http://127.0.0.1:8001/calendar` | Earnings and macro calendar |

## Notebooks And Scripts

Keep notebook setup explicit:

```python
from TerraFin import configure, load_terrafin_config

configure()
config = load_terrafin_config()
```

Use `configure(dotenv_path="/absolute/path/to/.env")` if the kernel is not
started from a directory where TerraFin can discover `.env` normally.

Notebook rules and layout guidance live in [Notebooks](notebooks.md).

## Next Reads

- [Configuration](configuration.md)
- [Deployment & Operations](deployment.md)
- [Examples & Workflows](examples.md)
- [Agent Docs](agent/index.md) — both Hosted TerraFin Agent (Mode A) and the
  external-agent skill / HTTP surface (Mode B).
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md) —
  drop-in for Claude Code / Codex (`cp -r skills/terrafin ~/.claude/skills/`).
