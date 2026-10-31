# TerraFin

**TerraFin** is terraform for financial research and investment decisions.
It has four parts:

- **Skills** that give any AI agent (Claude Code, Codex, opencode) a
  financial analyst's toolkit.
- **TerraFin Terminal**, a web dashboard for browsing markets and companies.
- **Its own agent**, built on the same skills, that sees what you have open in
  the dashboard.
    - Ask "is this cheap?" on a stock page and it knows which ticker you mean.
    - In the filing reader it works from the section you are reading. In the
      DCF workbench it reads the inputs you entered.
- **A data pipeline** that fetches, caches and normalizes each source once, so
  one agent can sweep a whole watchlist or search a stock universe in a few
  calls.

## Quickstart

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
pip install -e .   # the package, the terrafin-agent CLI and the server
./setup            # links the skill into Claude Code, Codex and opencode on PATH
```

Then ask your agent something like "give me a market snapshot of AAPL with
terrafin".

- No API key is needed for market data, company data or valuation.
- `FRED_API_KEY` adds FRED economic series. `TERRAFIN_SEC_USER_AGENT` adds SEC
  filings. Set them in your shell or in `.env` (copy `.env.example`).
- The Python client and the CLI run in-process, with no server. Capabilities
  they do not cover, such as valuation, go over HTTP and need the server.

To open TerraFin Terminal:

```bash
cd src/TerraFin/interface
python server.py run   # then open http://127.0.0.1:8001/terminal
```

## Two ways to use TerraFin

Capabilities live in one registry, and both surfaces read from it:

```
                    capability registry
                             │
          ┌──────────────────┴──────────────────┐
     skill layer                         TerraFin agent harness
     SKILL.md · /agent/api/* ·           sessions, model providers,
     terrafin-agent CLI · Python client  tool loop, view context
     → Claude Code, Codex, opencode      → chat panel on every page
```

Another agent can also call TerraFin's agent as a sub-agent: open a session
and send it a question over HTTP (`/agent/api/runtime/*`) or the
`terrafin-agent` CLI. It answers with the model configured in TerraFin.

**Your agent, TerraFin's skills.** Your agent keeps its own model and needs no
key from TerraFin. On a machine with no checkout, copy the whole
[`skills/terrafin/`](skills/terrafin/) directory, since the task recipes in
`references/` load from there on demand.

**TerraFin's own agent.** It runs in the chat panel on every page and needs a
model: set `TERRAFIN_AGENT_MODEL_REF` (`provider/model`, default
`openai/gpt-6-luna`) and the matching `OPENAI_API_KEY`, `GEMINI_API_KEY` or
`ANTHROPIC_API_KEY`.
Without one, the panel shows setup guidance instead of a chat. See the
[live demo](https://huggingface.co/spaces/sk851/TerraFin).

Not sure where to start? The docs site lays out each path:
[Pick your track](https://kiungsong.github.io/TerraFin/#pick-your-track).

## Example: a DCF

With the server running:

```bash
curl "http://127.0.0.1:8001/agent/api/valuation?ticker=AAPL"
```

Trimmed output, from a run on 2026-11-01:

```json
{
  "ticker": "AAPL",
  "currentPrice": 344.63,
  "dcf": {
    "currentIntrinsicValue": 115.7,
    "upsidePct": -66.43,
    "scenarios": {"bear": {"intrinsicValue": 92.44}, "base": {"intrinsicValue": 115.7}, "bull": {"intrinsicValue": 151.12}}
  },
  "reverseDcf": {"impliedGrowthPct": 68.51, "projectionYears": 5},
  "relative": {"trailingPE": 39.52, "forwardPE": 36.07},
  "processing": {"isComplete": true}
}
```

The base case puts AAPL's DCF value 66% below its price. The reverse DCF says
the price needs 68.5% cash-flow growth in year one, fading over five years. Negative-FCF companies get a
turnaround mode: pass `breakeven_year` and `breakeven_cash_flow_per_share`.

## Docs

- Formal docs site: <https://kiungsong.github.io/TerraFin/>
- Getting started: <https://kiungsong.github.io/TerraFin/getting-started/>
- Agent usage: <https://kiungsong.github.io/TerraFin/agent/usage/>
- Interface guide: <https://kiungsong.github.io/TerraFin/interface/>
- Model management: <https://kiungsong.github.io/TerraFin/agent/models/>

## Development

```bash
pip install -e ".[dev]"
pytest tests/
ruff check src tests
ruff format --check src tests
```

`src/TerraFin/interface/frontend/build/` is committed on purpose. If you change
frontend source, rebuild and commit the generated assets too.

## Credits

- The `./setup` install pattern is adapted from
  [gstack](https://github.com/garrytan/gstack).
- The CLI model-management UX was inspired by OpenClaw. The boundary is in
  [Model management](https://kiungsong.github.io/TerraFin/agent/models/).

## License And Data Rights

TerraFin is MIT-licensed open-source software, but the MIT license applies to
the software only. It does not grant rights to upstream market data, filings,
content, trademarks, or services accessed through this project.

Operator-managed deployments remain responsible for the sources they enable and
their own compliance/privacy posture. The maintainer-operated
[public demo Space](https://huggingface.co/spaces/sk851/TerraFin) is a public
TerraFin deployment. Access to that demo does not create any right to upstream
data. For the full notice, read
<https://kiungsong.github.io/TerraFin/legal/> and [LICENSE](LICENSE).
