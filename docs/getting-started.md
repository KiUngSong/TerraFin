---
title: Getting Started
summary: Install TerraFin, configure the runtime, and run the first Python, CLI, and hosted-agent flows.
---

# Getting Started

This page is the shortest path from clone to a working TerraFin.

## Prerequisites

- Python 3.11+

## Install

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
pip install -e .   # the package, the terrafin-agent CLI and the server
./setup            # links the skill into Claude Code, Codex and opencode on PATH
```

Skip `./setup` if you will not use TerraFin from another agent. Extras:
`pip install -e ".[dev]"`, `".[db]"`, `".[notebooks]"`.

## What needs a server or a key

| You want | Server | Keys |
|----------|--------|------|
| Your agent calls TerraFin through the Python client or the CLI | No | None |
| Your agent calls the HTTP routes `/agent/api/*`, which cover more, valuation included | Yes | None |
| TerraFin Terminal, the web dashboard | Yes | None |
| TerraFin's own agent | Yes for the chat panel, no for the CLI | A model key |

Market data, company data and valuation work with no key. Some sources need one:

| Variable | Adds |
|----------|------|
| `FRED_API_KEY` | FRED economic series |
| `TERRAFIN_SEC_USER_AGENT` | SEC EDGAR filings and guru 13F holdings. SEC requires a name and an email, such as `"Jane Doe jane@example.com"` |
| `TERRAFIN_AGENT_MODEL_REF` | The model for TerraFin's own agent, as `provider/model`. Default `openai/gpt-6-luna` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | The key matching that provider |

Set them in your shell or in `.env` (`cp .env.example .env`). TerraFin reads
`.env` from the current directory or the checkout root. The full list is in
[Configuration](configuration.md).

## First DCF

Valuation runs over HTTP, so start the server first (see
[Run The Interface](#run-the-interface)), then:

```bash
curl "http://127.0.0.1:8001/agent/api/valuation?ticker=AAPL"
```

The result holds the DCF intrinsic value per share with bear, base and bull
scenarios, a reverse DCF, and relative multiples. From your own agent, ask
something like "run a DCF on AAPL with terrafin" while the server runs.

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

## First Session With TerraFin's Own Agent

This needs `TERRAFIN_AGENT_MODEL_REF` and its key (see the table above and
[Model Management](agent/models.md)).

```bash
terrafin-agent runtime-create-session terrafin-assistant
```

Then send a message, using the session id the first command printed:

```bash
terrafin-agent runtime-message <session-id> "Give me a compact AAPL market snapshot."
```

The same agent is the chat panel on every page once the interface server is
running. Chat history is stored locally under `.terrafin/`.

## Run The Interface

From `src/TerraFin/interface/`:

```bash
python server.py run
```

`run` stays in the foreground. `start`, `stop`, `status` and `restart`
manage a background process.

Pages, on the default local address:

| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:8001/chart` | Interactive chart |
| `http://127.0.0.1:8001/terminal` | Terminal |
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
- [Skills](skills/index.md): use TerraFin from your own agent (Claude Code,
  Codex, opencode).
- [Agent Docs](agent/index.md): TerraFin's own agent and the glossary both
  paths share.
