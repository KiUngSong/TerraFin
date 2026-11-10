# Skill catalog

<!-- Auto-generated from src/TerraFin/agent/runtime/capability.py by
     `python scripts/generate-agent-artefacts.py`. Edit the registry, not
     this page. Hand-edits will be overwritten. -->

<!-- generated:capability-catalog:begin -->

A capability is one research operation TerraFin can run: fetch a price series, run a DCF,
read a section of a 10-K. Each one is registered once, in
`build_default_capability_registry` in `src/TerraFin/agent/runtime/capability.py`.
The `/agent/api/*` HTTP routes, the `terrafin-agent` CLI and the hosted agent all expose
capabilities from that registry.

This page is generated from the registry by `scripts/generate-agent-artefacts.py`, so it
lists every released capability in the registry. The category of each capability is a field of its
registration. To print the live set as JSON, run:

```bash
terrafin-agent capabilities
```

How to read the **How to reach it** column:

- An HTTP route is served by a running TerraFin server.
- A `terrafin-agent` command runs the capability from the CLI.
- **Hosted agent only** means there is no HTTP route and no CLI command: only TerraFin's
  own agent calls it, inside a session.

Capabilities behind a feature flag are not listed here.

## Market, macro and news

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `resolve` | Resolve a free-form query into a TerraFin route. | `GET /agent/api/resolve`, `terrafin-agent resolve` |
| `indicator_search` | Find an indicator's catalog name by substring. | `GET /agent/api/indicator-search`, `terrafin-agent indicator-search` |
| `market_data` | Chart-ready OHLC time series for one asset. | `GET /agent/api/market-data`, `terrafin-agent market-data` |
| `indicators` | Chart-matching technical indicators for one asset. | `GET /agent/api/indicators`, `terrafin-agent indicators` |
| `news` | Recent headlines for a ticker or query (metadata only). | `GET /agent/api/news` |
| `market_snapshot` | Compact market snapshot for one asset. | `GET /agent/api/market-snapshot`, `terrafin-agent snapshot` |
| `economic` | Economic indicator series (FRED-backed). | `GET /agent/api/economic`, `terrafin-agent economic` |
| `macro_focus` | Macro summary plus chart-ready series for one instrument. | `GET /agent/api/macro-focus`, `terrafin-agent macro-focus` |
| `calendar_events` | TerraFin calendar events for a month. | `GET /agent/api/calendar`, `terrafin-agent calendar` |
| `top_companies` | Top companies by market cap (private API or yfinance fallback). | `GET /agent/api/top-companies` |

## Company fundamentals and valuation

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `consensus` | Forward EPS/revenue consensus, revisions, and price targets. | `GET /agent/api/consensus` |
| `company_info` | Company profile and valuation fields for a ticker. | `GET /agent/api/company`, `terrafin-agent company` |
| `earnings` | Earnings history (estimate / reported / surprise) for a ticker. | `GET /agent/api/earnings`, `terrafin-agent earnings` |
| `financials` | Financial statement table (income / balance / cashflow) for a ticker. | `GET /agent/api/financials`, `terrafin-agent financials` |
| `sp500_dcf` | Full S&P 500 DCF valuation (scenarios, sensitivity, methods). | `GET /agent/api/sp500-dcf` |
| `beta_estimate` | 5-year monthly beta with adjusted beta, R², benchmark. | `GET /agent/api/beta-estimate` |
| `fcf_history` | FCF history + 3yr-avg / latest-annual / TTM candidates. | `GET /agent/api/fcf-history` |
| `fundamental_screen` | Fundamental quality and moat screen for a ticker. | `GET /agent/api/fundamental-screen` |
| `growth_series` | Revenue and EPS YoY growth series for a ticker. | `GET /agent/api/growth-series`, `terrafin-agent growth-series` |
| `valuation` | DCF (incl. turnaround mode), reverse DCF, relative valuation, Graham number. | `GET /agent/api/valuation` |

## SEC filings and research

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `sec_filings` | List recent 10-K / 10-Q / 8-K filings and registration statements with EDGAR URLs. | `GET /agent/api/sec-filings` |
| `sec_filing_document` | Filing table-of-contents (sections + char counts) without full body. | `GET /agent/api/sec-filing-document` |
| `sec_filing_section` | Verbatim markdown body of one filing section by slug. | `GET /agent/api/sec-filing-section` |

## Sentiment, risk and market regime

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `lppl_analysis` | LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection). | `GET /agent/api/lppl`, `terrafin-agent lppl` |
| `fear_greed` | CNN Fear & Greed index — score, rating, history. | `GET /agent/api/fear-greed` |
| `market_regime` | Market regime classification with confidence and signals. | `GET /agent/api/market-regime` |
| `trailing_forward_pe` | S&P 500 trailing vs forward P/E spread (history + summary). | `GET /agent/api/trailing-forward-pe` |
| `market_breadth` | Standalone market-breadth metrics (% advancing, new highs, etc.). | `GET /agent/api/market-breadth` |
| `risk_profile` | Statistical risk profile (tail risk, convexity, vol regime, drawdown). | `GET /agent/api/risk-profile` |

## Screening and patterns

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `patterns` | Named market patterns matching the latest bar for one asset. | `GET /agent/api/patterns` |
| `pattern_scan` | Sweep a watchlist group or ticker list for pattern triggers. | `GET /agent/api/pattern-scan` |
| `similarity_search` | Chart-pattern similarity search across a stock universe. | `GET /agent/api/similarity-search` |

## Portfolio and watchlist

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `watchlist` | The user's current watchlist (read-only). | `GET /agent/api/watchlist` |

## Investor personas

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `portfolio` | Guru 13F book — not the user's holdings. | `GET /agent/api/portfolio`, `terrafin-agent portfolio` |

## Charts and session

| Capability | What it does | How to reach it |
| --- | --- | --- |
| `open_chart` | Create or update a chart session bound to the conversation. | `terrafin-agent open-chart` |

<!-- generated:capability-catalog:end -->
