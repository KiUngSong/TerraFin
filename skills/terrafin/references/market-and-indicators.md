# Market & indicator recipes

Reference for the `terrafin` skill. Shell examples use `$TF` — define it first, in this shell:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

### Find what a series is called (do this before asking for data)

Every data call takes a name from TerraFin's catalog, and the catalog spans
four registries (Index, Market, Economic, plus chart-only custom specs). If
you do not already know the exact name, search first — do **not** guess a
ticker and do not go fetch the number from an outside source.

```bash
curl "$TF/agent/api/indicator-search?q=trea"
# -> Treasury-13W, Treasury-2Y, Treasury-5Y, Treasury-10Y, Treasury-30Y,
#    TGA, Term Spread, High Yield Spread, 18M Forward Rate Spread, Credit Spread
```

```python
from TerraFin.agent import TerraFinAgentClient
TerraFinAgentClient().indicator_search("trea")
```

`resolve` is not a substitute: it matches exact names only and answers an
unrecognised string with a fabricated stock row (`"trea"` → `type: stock,
name: TREA`), which sends you down the wrong path silently.

### Macro / market series with history

Feed a match's `symbol` straight to `market_data`, or to `DataFactory` when
TerraFin is importable:

```python
from TerraFin.data.factory import DataFactory

df = DataFactory()
df.search_indicators("trea")                                # find the name
chunk = df.get_recent_history("Treasury-30Y", period="30y")  # 7531 rows, 1996→
chunk.frame[["time", "close"]]        # columns are lowercase: time, close
```

`period` accepts `30d` / `3m` / `5y` style offsets plus `ytd` and `max`
(`max` on Treasury-30Y reaches 1977). `get_indicator_snapshot` is **not** the
scalar reader for these — it serves private series only and raises on a market
or economic name.

### Ticker brief

Use:

- `ticker_brief(name)` or
- `resolve(name)` then `market_snapshot(...)` and `company_info(...)`

### Market snapshot

Use:

- `market_snapshot(name, depth="auto", view="daily")`

### Compare assets

Use:

- `compare_assets([name1, name2, ...], depth="auto", view="daily")`

If the user asks for long-range comparison, rerun with `depth="full"`.

### Macro context

Use:

- `macro_context(name, depth="auto", view="daily")`

### Calendar scan

Use:

- `calendar_scan(year=..., month=..., categories=..., limit=...)`

### Bubble analysis (LPPL)

Use:

- `bubble_analysis(name, depth="auto", view="daily")`

LPPL detects super-exponential growth with accelerating log-periodic
oscillations. Best for broad market indices, not individual stocks. Always
combine with macro context.

### Sentiment / breadth widgets

Stateless market-temperature signals:

- `fear_greed()` — current CNN-style fear & greed index
- `market_regime()` — TerraFin's regime classification
- `market_breadth()` — % advancing / new highs / etc.
- `trailing_forward_pe()` — S&P 500 trailing vs forward P/E spread

Use one of these (not all four) when the user asks "is the market frothy?" /
"what's the cycle?" / "are we in a bubble?". For a deep cycle answer pair
with `sp500_dcf()` and `lppl_analysis("S&P 500")`.

### Pattern sweep (idea sourcing)

Find which symbols are triggering technical patterns right now, instead of checking one ticker at a time.
`patterns` verifies a name you already have; `pattern_scan` is how you find candidates in the first place.

Use:

- `pattern_scan(group=None, tickers=None, severity_min="low")`

Parameters:

- `group` — one watchlist tag. Omit both arguments to sweep the entire watchlist.
- `tickers` — comma-separated string or list, to sweep symbols that are not on the watchlist.
- `severity_min` — `"low"` (default), `"medium"`, `"high"`. Raise it when sweeping a large set.

Patterns evaluated per symbol:

- close-vs-MA cross grid — `MA20/60/120/200_{GOLDEN,DEATH}_CROSS` (daily) and `MA20/60/120W_{GOLDEN,DEATH}_CROSS` (weekly)
- `52W_NEW_HIGH`, `52W_NEW_LOW`, `WEEKLY_NEW_HIGH`, `WEEKLY_NEW_LOW`, `MINERVINI_TEMPLATE`, `RSI_OVERBOUGHT` and `RSI_OVERSOLD` with their `WEEKLY_` counterparts, `WEEKLY_VOLUME_DRYUP`

Severity, as the catalogue actually emits it:

- no pattern emits `low`, so `severity_min="low"` and `"medium"` return the same set
- `"high"` narrows to exactly `52W_NEW_HIGH`, `52W_NEW_LOW`, `WEEKLY_NEW_HIGH`, `WEEKLY_NEW_LOW`, `MINERVINI_TEMPLATE`, `WEEKLY_RSI_OVERBOUGHT`, `WEEKLY_RSI_OVERSOLD`

Expect roughly 1–2 signals per symbol per scan — not a flood.

Coverage fields — check these before concluding "nothing is triggering":

- `requested` — symbols asked for
- `scanned` — symbols actually fetched and evaluated
- `failed` — the difference (a rate-limited sweep can silently scan far fewer)
- `matched` — hits before truncation; `returned` / `truncated` describe the clipped `signals[]` (`limit`, default 200)

Cost: one price-history fetch per symbol. Cache reads run 8-way concurrently, but cold downloads are serialised by a process-wide lock, so a cold sweep of hundreds of symbols takes minutes and slows other price requests in the same process. Use `start_pattern_scan_task` for large sets; keep interactive calls to a few dozen symbols.

```bash
curl "$TF/agent/api/pattern-scan?severity_min=high"
curl "$TF/agent/api/pattern-scan?tickers=NVDA,AMD,AVGO,MU"
```

There is no `TerraFinAgentClient.pattern_scan` method — like most capabilities added after the original set, this one is reachable through the HTTP route, the hosted agent tool, or `TerraFinAgentService` directly.

### Chart similarity search

Find historical periods where another stock's chart had the same shape as the target ticker's recent chart.

Use:

- `similarity_search(ticker, universe="sp500+nasdaq100+kospi200", period="1y", top_n=20)`

Parameters:

- `ticker` — the stock to match (required). Its recent close-price chart over `period` becomes the template.
- `universe` — `"sp500"`, `"nasdaq100"`, `"kospi200"`, `"sp500+kospi200"`, `"sp500+nasdaq100+kospi200"` (default), or `"watchlist"`.
- `period` — template length: `"1y"` (default), `"2y"`, `"6m"`.
- `top_n` — number of results (1–50, default 20).

Response fields per result: `symbol`, `name`, `score` ([0,1]), `matchStart`, `matchEnd`, `overlapDays`.

Algorithm: STUMPY MASS sliding-window z-normalized Euclidean distance on cumulative log returns — shape-matching, not level or trend. Score of 1 = perfect shape match; scores above 0.70 are meaningful.

```bash
# No client method — HTTP or CLI only.
curl "$TF/agent/api/similarity-search?ticker=NVDA&universe=sp500%2Bnasdaq100%2Bkospi200&period=1y&top_n=10"
```

Use the results to surface analogous historical episodes and estimate plausible forward price paths (look at `matchEnd + ~1 month` in those historical series).
