# Tool lookup

Reference for the `terrafin` skill: which tool fits a task, and what not to
hand-roll.

## Pick a tool

Check this table before reaching for `requests`, `urllib`, `yfinance`, or a
regex parser. The data tools already handle rate limits, retries, caching,
and progressive history.

Rows name capabilities, not client methods. SKILL.md's Capability inventory
gives each one's HTTP route. Not every capability has a Python client or CLI
method, so check before calling one.

| If you want to...                                          | Use this tool                                                       |
| ---------------------------------------------------------- | ------------------------------------------------------------------- |
| Resolve a ticker/name into a TerraFin route                | `resolve(query)`                                                    |
| Get a chart-ready OHLC series                              | `market_data(name, depth, view)`                                    |
| Get a one-asset snapshot (price action + indicators)       | `market_snapshot(name, depth, view)` (pass `force_refresh=True` only when you need a fresher bar than the cache holds) |
| Get company profile / valuation fields                     | `company_info(ticker)`                                              |
| Get earnings history (estimate / reported / surprise)      | `earnings(ticker)`                                                  |
| Get forward consensus, revisions, and price targets        | `consensus(ticker)`                                                 |
| Find recent headlines / the catalyst behind a move         | `news(ticker, query, days, limit)`                                  |
| Get income / balance / cashflow statement                  | `financials(ticker, statement, period)`                             |
| List recent 10-K / 10-Q / 8-K filings and registration statements | `sec_filings(ticker)`                                        |
| Get a single filing's TOC (no full body)                   | `sec_filing_document(ticker, accession, primaryDocument, form)`     |
| Pull one filing section's markdown body                    | `sec_filing_section(..., sectionSlug, form)`                        |
| Run DCF / reverse DCF / Graham / relative valuation        | `valuation(ticker, ...)` (see [valuation.md](valuation.md) for turnaround inputs)|
| Inspect FCF base candidates (3yr_avg / annual / TTM)       | `fcf_history(ticker, years)`                                        |
| Get S&P 500 index-level DCF                                | `sp500_dcf()`                                                       |
| Get beta vs mapped benchmark                               | `beta_estimate(ticker)`                                             |
| Get statistical risk profile (tail risk, drawdown, regime) | `risk_profile(name)`                                                |
| Run a fundamental quality / moat screen                    | `fundamental_screen(ticker)`                                        |
| Get revenue / EPS YoY growth series (annual + quarterly)   | `growth_series(ticker)`                                             |
| Get guru portfolio holdings (Buffett / Marks / Druck.)     | `portfolio(guru)`                                                   |
| Get FRED-backed economic indicator series                  | `economic(indicators)`                                              |
| Get macro summary + chart-ready series                     | `macro_focus(name, depth, view)`                                    |
| Scan calendar events for a month                           | `calendar_events(year, month, categories, limit)`                   |
| Detect bubble (super-exp growth + log-periodic osc.)       | `lppl_analysis(name, depth, view)`                                  |
| Find chart-shape-similar historical episodes               | `similarity_search(ticker, universe, period, top_n)`                |
| Get market temperature signals                             | `fear_greed()`, `market_regime()`, `market_breadth()`, `trailing_forward_pe()` |
| Get top companies by market cap                            | `top_companies()`                                                   |
| Read the user's watchlist                                  | `watchlist()`                                                       |
| Get chart-matching technical indicators                    | `indicators(name, indicators, depth, view)`                         |
| Get named pattern signals matching the latest bar          | `patterns(name, depth, view)`                                       |
| Sweep many symbols for pattern triggers (idea sourcing)    | `pattern_scan(group, tickers, severity_min)`                        |
| Read which panel/form the user is currently looking at     | `current_view_context()` (TerraFin's own agent only)                |
| Open a chart artifact bound to the session                 | `open_chart(name)` (TerraFin's own agent only)                      |
| List / authenticate / switch hosted models                 | `terrafin-agent models ...` (see [Model management](https://kiungsong.github.io/TerraFin/getting-started/models/))          |
| Discover capability schemas programmatically               | `GET /openapi.json`, filtered to `/agent/api/*`                     |

Signatures, parameter ranges, and worked examples live in [SKILL.md](../SKILL.md)
and the other files in `references/`.

## Don't roll your own

Reach for the TerraFin helper before hand-rolling any of the patterns below.
Each one has broken before through rate limits, cache misses, or parser drift.

### SEC filings

Do not fetch `https://www.sec.gov/...` yourself, parse the accession folder
index, or strip HTML by hand. Use the three SEC tools instead:

1. `sec_filings(ticker)` lists filings. Its `latestByForm` gives the
   accession, primary document, and form for the latest filing of each type.
2. `sec_filing_document(..., form=...)` returns the table of contents.
   For an 8-K it includes the `EX-99.x` exhibits, such as the earnings press release.
3. `sec_filing_section(..., sectionSlug=..., form=...)` returns one section as
   clean markdown.

Why this matters:

- SEC rate-limits by IP. The helpers share one `SECClient` with rate limiting
  and retries. Raw `urllib` does not, and risks getting the host banned.
- Parsed filings are cached. Raw fetches pull the same filing again every time.

**Always pass the real `form`** ("10-K", "10-Q", "8-K", "8-K/A"). It defaults
to "10-Q", and an 8-K read as a 10-Q comes back as the cover sheet with no exhibits.
