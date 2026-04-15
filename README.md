# TerraFin

**TerraFin** — *terraform finance*.

TerraFin is an agent-ready Python toolkit and FastAPI interface for
financial research workflows.

It combines:

- market, macro, and filings data access
- chart-first browser pages
- DCF and research tooling
- a hosted TerraFin Agent runtime for local personal use

> [!IMPORTANT]
> **TerraFin is MIT-licensed open-source software, and the MIT license applies to the software only.**
> It does **not** grant any right to third-party data, content, trademarks, or
> services accessed through this project. TerraFin is not affiliated with or
> endorsed by any upstream data provider unless explicitly stated.
>
> TerraFin may access multiple source families, including Yahoo-derived data via
> `yfinance`, SEC EDGAR, FRED, news headlines, and user-operated private
> endpoints. **Rights to the actual data remain subject to the applicable
> provider terms, licenses, and law.** Depending on the source, personal,
> public, automated, cached, redistributed, or commercial use of upstream data
> may be restricted or prohibited.
>
> Anyone operating a public deployment of TerraFin is responsible for the
> sources they enable, any connected private API, and the privacy and
> compliance posture of that service. Authentication, caching, or proxying do
> not create rights to upstream data. End users are responsible only for their
> own downstream copying, scraping, caching, redistribution, or other reuse of
> displayed data.
>
> The maintainer-operated public demo Space at
> [`https://huggingface.co/spaces/sk851/TerraFin`](https://huggingface.co/spaces/sk851/TerraFin)
> is one such deployment and is referenced here because it is a publicly
> accessible TerraFin demo. Access to that demo does not create any right to
> upstream data. Nothing in this notice modifies the [LICENSE](LICENSE).

## Docs

- Formal docs site: <https://kiungsong.github.io/TerraFin/>
- Getting started: <https://kiungsong.github.io/TerraFin/getting-started/>
- Agent usage: <https://kiungsong.github.io/TerraFin/agent/usage/>
- Interface guide: <https://kiungsong.github.io/TerraFin/interface/>
- Hosted runtime details: <https://kiungsong.github.io/TerraFin/agent/hosted-runtime/>

Public demo:

- Hugging Face Space: <https://huggingface.co/spaces/sk851/TerraFin>

## Quickstart

Prerequisite:

- Python 3.11+

Install and run:

```bash
cp .env.example .env
pip install -e .
cd src/TerraFin/interface
python server.py run
```

Useful optional env vars:

| Variable | Use |
|----------|-----|
| `FRED_API_KEY` | Enable FRED-backed economic data |
| `TERRAFIN_SEC_USER_AGENT` | Enable SEC EDGAR filings and guru 13F access |
| `TERRAFIN_AGENT_MODEL_REF` | Choose the hosted model in `provider/model` format |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `COPILOT_GITHUB_TOKEN` | Provider credentials for TerraFin Agent |

## Quick Examples

Python:

```python
from TerraFin.data import DataFactory

data = DataFactory()
spy = data.get("S&P 500")
unrate = data.get_fred_data("UNRATE")
```

Hosted agent:

```python
from TerraFin.agent import TerraFinAgentClient

agent = TerraFinAgentClient()
session = agent.runtime_create_session("terrafin-assistant")
run = agent.runtime_message(session["sessionId"], "Give me a compact AAPL market snapshot.")
```

CLI:

```bash
terrafin-agent snapshot AAPL
terrafin-agent models list --all
terrafin-agent models auth login-github-copilot --set-default
```

## TerraFin Agent

The browser UI is exposed through the floating **TerraFin Agent** panel on the
main interface pages.

If the deployment does not have a valid hosted model configured, the widget
stays in warning/info mode:

- it shows setup guidance
- it does not create a session
- it does not accept chat input until provider credentials are valid

Model management follows canonical `provider/model` refs such as
`openai/gpt-4.1-mini`, `google/gemini-3.1-pro-preview`, or
`github-copilot/gpt-4o`.

The CLI model-management UX was inspired by OpenClaw. TerraFin's runtime
binding, saved-state format, hosted session model, and widget integration are
TerraFin-specific. See
<https://kiungsong.github.io/TerraFin/agent/models/> for the explicit
attribution boundary.

## Development

```bash
pip install -e ".[dev]"
pytest tests/
ruff check src tests
ruff format --check src tests
```

Frontend note:

- `src/TerraFin/interface/frontend/build/` is committed on purpose
- if you change frontend source, rebuild and commit the generated assets too

## License And Data Rights

TerraFin is MIT-licensed open-source software, but the MIT license applies to
the software only. It does not grant rights to upstream market data, filings,
content, trademarks, or services accessed through this project.

Operator-managed deployments remain responsible for the sources they enable and
their own compliance/privacy posture. For the full notice, read
<https://kiungsong.github.io/TerraFin/legal/> and [LICENSE](LICENSE).
