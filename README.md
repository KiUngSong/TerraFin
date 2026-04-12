# TerraFin

**TerraFin** — *terraform finance*. An agent-ready Python toolkit and FastAPI
interface for pulling financial data, normalizing it into chart-ready frames,
running lightweight analytics, and serving browser-based views for research,
educational, and agent-driven workflows.
The public core is designed to stand on its own while still connecting cleanly
to private-access extensions for deployment-specific data and operator-side
workflows used in real deployments.


---

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

---

## What TerraFin Includes

The table below describes the public core. Optional private-access support is
part of that design so the same interfaces can connect to deployment-specific
extensions without turning them into the default open-source path.

| Area | Purpose |
|------|---------|
| Data layer | Fetch market, economic, corporate, and private-access data through a single entry point |
| Analytics | Compute technical indicators and run standalone valuation, options, portfolio, and simulation models |
| Interface | Serve chart, dashboard, market insights, and calendar pages from one FastAPI app |
| Agent runtime | Expose an agent client, CLI, reusable skill, and JSON API over the same optimized processing pipeline used by charts |
| Cache system | Keep provider data warm in memory and on disk with background refresh or lazy invalidation |

## Documentation Map

| Doc | Read this when... |
|-----|-------------------|
| [data-layer.md](docs/data-layer.md) | You need to fetch data, add a provider, or understand output types |
| [interface.md](docs/interface.md) | You are running the server, calling APIs, or editing the UI |
| [chart-architecture.md](docs/chart-architecture.md) | You need to understand chart sessions, progressive loading, notebook flow, or chart state management |
| [agent-skill.md](docs/agent-skill.md) | You want to use TerraFin as an agent skill through Python, CLI, HTTP, or OpenAPI |
| [feature-integration.md](docs/feature-integration.md) | You are adding a new feature and need to know which logic layer and public surfaces must be updated |
| [analytics.md](docs/analytics.md) | You are using indicators or the standalone analysis modules |
| [caching.md](docs/caching.md) | You are tuning refresh behavior or registering a cached source |
| [agent-runtime.md](docs/agent-runtime.md) | You are maintaining the agent service, client, skill, or API contract |

## Install

### Prerequisites

- Python 3.11+

### Core install

```bash
pip install .
```

### Editable install

```bash
pip install -e .
```

### Optional extras

```bash
pip install -e ".[dev]"
pip install -e ".[db]"
pip install -e ".[notebooks]"
```

## Feature Matrix

| Feature area | Status | Notes |
|--------------|--------|-------|
| Market charts and stock pages | Works out of the box | Uses yfinance-backed market data |
| Corporate financial statements | Works out of the box | Uses TerraFin's yfinance-backed fundamentals adapter |
| Stock and index DCF tools | Works out of the box | No separate fundamentals API key required |
| FRED economic series | Requires public API/config | Set `FRED_API_KEY` |
| SEC EDGAR filings and guru 13F portfolios | Requires public API/config | Set `TERRAFIN_SEC_USER_AGENT` to a descriptive contact string |
| Watchlist write mode | Requires operator-owned/private infrastructure | Configure MongoDB env vars |
| Dashboard / market-insights private widgets | Requires operator-owned/private infrastructure | Optional private endpoint for proprietary extras |

### Runtime setup

Common runtime knobs:

| Variable | Purpose |
|----------|---------|
| `FRED_API_KEY` | Enable FRED-backed economic series |
| `TERRAFIN_SEC_USER_AGENT` | Enable SEC EDGAR filings and guru 13F access |
| `TERRAFIN_HOST` / `TERRAFIN_PORT` | Bind address for the FastAPI server |
| `TERRAFIN_BASE_PATH` | Optional prefix for feature routes |
| `TERRAFIN_CACHE_TIMEZONE` | IANA timezone for cache/date-bound scheduling |
| `TERRAFIN_PRIVATE_SOURCE_*` | Optional authenticated private-source endpoint for dashboard and market-insights extras |
| `TERRAFIN_MONGODB_URI` / `MONGODB_URI` | Optional MongoDB backend for writable watchlist mode |
| `TERRAFIN_WATCHLIST_*` | Optional MongoDB collection and document overrides |

`import TerraFin` stays side-effect free. Explicit entrypoints such as
`terrafin-agent` and `python src/TerraFin/interface/server.py ...` load `.env`
themselves. For notebooks and scripts, call `configure()` once at startup:

```python
from TerraFin import configure

configure()
```

For explicit dotenv paths, lazy-load behavior, or typed config inspection, see
[docs/interface.md](docs/interface.md). Private-source behavior lives in
[docs/data-layer.md](docs/data-layer.md), and cache policy details live in
[docs/caching.md](docs/caching.md).

### Public/demo mode

TerraFin can run without private infrastructure. Copy `.env.example` to `.env`,
leave the private-access variables empty, and start the server. Public providers
still work, and private-only widgets fall back to bundled public-safe fixtures
or empty defaults.

```bash
cp .env.example .env
pip install -e .
cd src/TerraFin/interface
python server.py run
```

Private access remains optional. When `TERRAFIN_PRIVATE_SOURCE_*` is configured,
TerraFin will use the authenticated endpoint for dashboard and market-insight
data. Otherwise it stays on public sources and bundled fallbacks.

## Quickstart

### Use TerraFin from Python

```python
from TerraFin.data import DataFactory

data = DataFactory()

spy = data.get("S&P 500")
aapl = data.get("AAPL")
vix = data.get("VIX")

unrate = data.get_fred_data("UNRATE")
income = data.get_corporate_data("AAPL", "income", "annual")
portfolio = data.get_portfolio_data("Warren Buffett")
```

`get_corporate_data(...)` uses TerraFin's yfinance-backed statement adapter, so
it does not require a separate fundamentals API key.

`get_portfolio_data(...)` and other SEC EDGAR helpers require
`TERRAFIN_SEC_USER_AGENT` to be set.

### Use TerraFin as an agent skill

Python client:

```python
from TerraFin.agent import TerraFinAgentClient

agent = TerraFinAgentClient()
snapshot = agent.market_snapshot("AAPL")
macro = agent.macro_focus("Nasdaq", depth="auto", view="weekly")
```

CLI:

```bash
terrafin-agent snapshot AAPL --json
terrafin-agent macro-focus "S&P 500" --view weekly --json
```

The client, CLI, and `/agent/api/*` routes all use the same optimized
processing layer. For market and macro requests they return `processing`
metadata that tells an agent whether the response is recent/progressive or
already complete. See [docs/agent-skill.md](docs/agent-skill.md) and the shipped
skill at [skills/terrafin/SKILL.md](skills/terrafin/SKILL.md).

### Run the interface

Run the server from `src/TerraFin/interface/`:

```bash
python server.py run
```

Useful commands:

| Command | Description |
|---------|-------------|
| `python server.py run` | Run in the foreground |
| `python server.py start` | Start in the background |
| `python server.py stop` | Stop the background process |
| `python server.py status` | Show whether the server is running |
| `python server.py restart` | Restart the background process |

Default pages:

| URL | Page |
|-----|------|
| `http://127.0.0.1:8001/chart` | Interactive chart |
| `http://127.0.0.1:8001/dashboard` | Watchlist, breadth, cache status |
| `http://127.0.0.1:8001/market-insights` | Regime summary and guru portfolios |
| `http://127.0.0.1:8001/calendar` | Earnings and macro calendar |
| `http://127.0.0.1:8001/stock/AAPL` | Stock Analysis example page |
| `http://127.0.0.1:8001/watchlist` | Watchlist page |

### Frontend build policy

The generated frontend assets under
`src/TerraFin/interface/frontend/build/` are committed on purpose so the server
can run without a Node.js install at runtime. If you change frontend source
files, rebuild the app and commit the refreshed build output together with the
source change.

## Development

```bash
pip install -e ".[dev]"
pytest tests/
ruff check src tests
ruff format --check src tests
```

Testing and demo rule:

- keep automated regression coverage in `tests/` as `test_*.py`
- keep manual or exploratory notebooks in `notebooks/`
- do not place `.ipynb` files under `tests/`
- do not name manual notebooks with a misleading `test_` prefix

## Project Layout

| Path | What lives there |
|------|------------------|
| `src/TerraFin/data/` | DataFactory, provider integrations, cache utilities, output types |
| `src/TerraFin/analytics/` | Technical indicators and standalone analysis/simulation modules |
| `src/TerraFin/agent/` | Shared agent processing layer, client, task helpers, and CLI |
| `src/TerraFin/interface/` | FastAPI server, route handlers, session state, React frontend |
| `skills/` | Reusable skill artifacts for external agents |
| `tests/` | Automated pytest coverage for data, analytics, agent, and interface layers |
| `notebooks/` | Human-guided demos and manual exploration notebooks |
| `docs/` | Module-level documentation |
