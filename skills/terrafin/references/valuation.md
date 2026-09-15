# Valuation & fundamentals recipes

Reference for the `terrafin` skill. Shell examples use `$TF` — define it first, in this shell:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

### Stock fundamentals

Use:

- `stock_fundamentals(ticker, statement="income", period="annual")`

### DCF valuation

Use:

- `valuation(ticker)` — full payload: forward DCF (5yr default horizon),
  reverse DCF, relative valuation (trailing/forward P/E, P/B), Graham number,
  margin of safety. Defaults are sane for healthy stable companies.

Tune the forward DCF with optional kwargs:

- `projection_years` — `5`, `10`, or `15`. Default `5`. Use `10`+ for
  long-cycle businesses or turnaround stories so terminal value carries less
  weight.
- `fcf_base_source` — `auto` (default), `3yr_avg`, `ttm`, or `latest_annual`.
  `auto` cascades `3yr_avg → latest_annual → ttm`. The 3-year average is the
  professional default for DCF (single-period TTM is too noisy from
  working-capital swings and capex lumps).

```bash
curl "$TF/agent/api/valuation?ticker=AAPL&projection_years=10&fcf_base_source=3yr_avg"
```

### DCF turnaround mode

Use when current FCF is negative or volatile but the user has a thesis that
FCF turns positive. Supplying ALL three turnaround fields switches to an
explicit per-year schedule:

- `breakeven_year` — the year FCF turns positive (typical 1–5 for
  operational turnarounds)
- `breakeven_cash_flow_per_share` — FCF/share at the breakeven year
- `post_breakeven_growth_pct` — growth rate after breakeven, fades toward
  terminal growth across the remaining horizon

Pre-breakeven years interpolate linearly from current FCF (which can be
negative; cash-burn is *not* clipped — it reduces intrinsic value honestly)
to the breakeven value.

```bash
# MOH thesis: $2/share by 2027, then 15% growth fading to terminal
curl "$TF/agent/api/valuation?ticker=MOH&projection_years=10\
&breakeven_year=3&breakeven_cash_flow_per_share=2.0&post_breakeven_growth_pct=15.0"
```

### Historical FCF / share

Use before DCF when the user is unsure what base to choose, or to surface
candidate values for the FCF Base Source picker:

- `fcf_history(ticker, years=10)` — annual rows, TTM marker, and
  `candidates: {threeYearAvg, latestAnnual, ttm}` per share. Also returns
  `autoSelectedSource` (which candidate the `auto` cascade would pick under
  current data — `3yr_avg`, `annual`, or `quarterly_ttm`).

```bash
# Inspect .candidates before calling valuation
curl "$TF/agent/api/fcf-history?ticker=GOOGL&years=10"
```

### S&P 500 DCF

Use:

- `sp500_dcf()` — index-level DCF using earnings power + shareholder yield
  blended methodology with consensus inputs.

### Reverse DCF

Bundled inside `valuation()` — see the `reverseDcf` field of the response.
Returns the implied growth rate the market is pricing in.

### Beta estimate

Use:

- `beta_estimate(ticker)` — TerraFin's `beta_5y_monthly` against the mapped
  benchmark (S&P 500 for US, KOSPI 200 for KS, etc.). Used as the discount
  rate input for DCF.
