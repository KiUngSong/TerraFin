# Filings, news & verification recipes

Reference for the `terrafin` skill. Shell examples use `$TF` — define it first, in this shell:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

### SEC filings

Three-step recipe for analyzing US-listed company filings:

1. `sec_filings(ticker)` — list recent 10-K / 10-Q / 8-K with EDGAR URLs and
   `latestByForm[<form>]` shortcut.
2. `sec_filing_document(ticker, accession, primaryDocument)` — get the
   filing's table of contents (sections + char counts) WITHOUT pulling the
   full body. Keeps the agent's context small.
3. `sec_filing_section(ticker, accession, primaryDocument, sectionSlug)` —
   pull a single section's markdown body by slug.

```bash
# None of the three has a client method — HTTP or CLI only.
curl "$TF/agent/api/sec-filings?ticker=AAPL"
# take .latestByForm["10-K"].accession and .primaryDocument from that, then:
curl "$TF/agent/api/sec-filing-document?ticker=AAPL&accession=$ACC&primaryDocument=$PRIM&form=10-K"
curl "$TF/agent/api/sec-filing-section?ticker=AAPL&accession=$ACC&primaryDocument=$PRIM&sectionSlug=item-1-business&form=10-K"
```

If `sec_filing_section` raises with "section not found", the error message
includes the 5 largest sections in the filing — pick the largest neighbor
(10-K parsers often nest MD&A inside an oversized parent).

### Headlines / catalyst ("why now")

Find the narrative around a move instead of inferring one.

Use:

- `news(ticker=None, query=None, days=7, limit=25)`

Pass `ticker` for a symbol or `query` for a theme or company name — a plain company name usually beats the symbol for coverage. `days` is 1-90, `limit` is 1-100.

Response per item: `title` (raw, ends with " - Publisher"), `headline` (suffix stripped), `publishedAt`, `source`, `sourceUrl`, `url`.

Feed-level `fetchedAt` is when TerraFin fetched, not the window — a cached or stale-served feed reports its real vintage and can lag today; `null` means unknown.

**Headlines only.** No article bodies are fetched or stored, so never claim to have read an article. `url` is a `news.google.com` **redirect**, not the publisher's canonical address.

Limits worth stating in an answer:

- matching is keyword-based, so same-name companies and passing mentions appear — read the publisher and headline before calling an item material
- a week on a large cap routinely matches ~100 headlines; `warnings` tells you when the list was truncated
- an unreachable feed returns zero items **with a warning**, so an empty list means "nothing found or feed unavailable", never "no news happened"

For dated corporate events prefer `sec_filings` — an 8-K near an unexplained move is harder evidence — and `calendar_events`. Use `news` for the narrative around them.

```bash
curl "$TF/agent/api/news?ticker=TSLA&days=5&limit=5"
curl "$TF/agent/api/news?query=Samsung%20Electronics&days=7"
```

There is no `TerraFinAgentClient.news` method — use the HTTP route, the hosted agent tool, or `TerraFinAgentService` directly.

### Forward consensus (what is already priced in)

Answers "what does the street already expect?" with observable data, before you claim a differentiated view.
`earnings` gives *reported* history; `consensus` gives *forward* expectations and which way they are moving.

Use:

- `consensus(ticker)`

Period keys are relative: `0q` current quarter, `+1q` next quarter, `0y` current fiscal year, `+1y` next.

Response:

- `revisions[]` — analyst up/down counts over 7 and 30 days per period, plus `net30d` and `direction30d` (`"up"` / `"down"` / `"flat"`). **The 30-day window includes the 7-day one — do not add them.** A tiny `analystCount` makes the direction near-meaningless.
- `epsEstimates[]` / `revenueEstimates[]` — `avg`, `low`, `high`, `analystCount`, `growth` (a fraction), and `dispersion` = `(high-low)/|avg|`.
- `priceTargets` — `current`, `mean`, `median`, `low`, `high`, `upsideToMeanPct` (already a percent).
- `recommendations[]` — strongBuy/buy/hold/sell/strongSell by month offset (`0m`, `-1m`, …), so rating drift is visible.
- `hasCoverage` — **check this, and the flags below with it.** An empty field means "unknown", never "neutral".

> [!WARNING]
> **Never report "this ticker has no analyst coverage."** Upstream returns an empty result for a rate-limited endpoint and for a genuinely uncovered symbol alike, so the two are not distinguishable. The flags say which story is possible, not which is true:
>
> - `upstreamFailed` — nothing came back at all. `quoteTypeHint` (e.g. `INDEX`, `ETF`) is context only: it is recovered from endpoints that stay up when the estimate endpoint is down, so it cannot confirm the estimates are really absent. An all-empty response is deliberately **not cached**.
> - `estimatesMissing` — other surfaces responded but every estimate surface was empty: an uncovered symbol or a partial failure.
> - `cacheTier` — `stale` or `fallback` means these numbers are not fresh.

> [!WARNING]
> **Rising estimates are not evidence that something is "not yet priced in."** Sell-side analysts revise toward the tape, so price usually *leads* the revision — post-earnings-announcement drift and revision momentum are among the most documented anomalies there are. Treat up-revisions as closer to a momentum signal than to a contrarian edge.

What this capability legitimately adds: a **dated record** of what consensus said (checkable later, which a reverse DCF cannot give you), and **dispersion** — whether "consensus" is a coherent number at all. When dispersion is wide, a differentiated thesis has to beat the range, not the midpoint; near break-even it is just a small denominator, so check `avg` before quoting it.

`asOf` is the date TerraFin fetched, not the vintage of the estimates — upstream provides no estimate timestamp.

Pair it with `valuation`: the reverse DCF infers what the *price* implies, while revisions show what analysts are *doing*.

```bash
curl "$TF/agent/api/consensus?ticker=AAPL"
```

There is no `TerraFinAgentClient.consensus` method — use the HTTP route, the hosted agent tool, or `TerraFinAgentService` directly.

