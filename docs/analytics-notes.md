---
title: Analytics Notes
summary: DCF and beta implementation notes that sit close to the analytics code but deserve a stable docs entrypoint.
---

# Analytics Notes

These notes mirror the implementation guidance kept near the analytics code so
maintainers can reach it from the formal docs site as well.

## DCF

DCF code lives under `src/TerraFin/analytics/analysis/fundamental/dcf/`.

| Model | What it is trying to answer | Main checked-in data |
|------|------------------------------|----------------------|
| S&P 500 DCF | A year-end target framework | `fundamental/dcf/sp500_defaults.json` |
| Stock DCF | A spot equity valuation framework | derived from live company inputs plus explicit defaults |

### S&P 500 DCF

The index model is a year-end target model, not a spot fair-value model.

Refresh `sp500_defaults.json` in this order:

1. set a defensible public strategist target range
2. refresh the nominal base-year EPS context
3. refresh the explicit growth fade schedule
4. refresh payout and buyback assumptions
5. refresh ERP and terminal discounting assumptions
6. verify the resulting target still lands in a reasonable public range

### Stock DCF

The stock model needs one starting growth assumption (`Base Growth %`) and one
starting cash-flow level (`Base FCF / Share`). Both can be overridden; both have
fallback cascades when blank.

Current fallback order for `Base Growth %` in `build_stock_template()`:

1. user override
2. EPS growth from `forwardEps` versus `trailingEps`
3. annual revenue CAGR
4. annual FCF CAGR
5. default `6%`

Why revenue comes before FCF CAGR:

- revenue is usually more stable
- FCF is more sensitive to capex timing and working-capital noise
- revenue is often the better default growth anchor when explicit EPS guidance is missing

#### Base FCF source cascade

`Base FCF / Share` is selected by `_select_stock_fcf_base()` in
`src/TerraFin/analytics/analysis/fundamental/dcf/inputs.py`. Four sources, with
explicit picks via the `fcf_base_source` override on `StockDCFOverrides`:

| Source | Helper | Notes |
|---|---|---|
| `auto` *(default)* | cascade | 3yr_avg → annual → ttm → missing |
| `3yr_avg` | `_three_year_avg_fcf` | Mean of last 3 valid annual FCF/share rows. Returns `None` if fewer than 2 valid years. |
| `latest_annual` | `_latest_annual_fcf` | First non-NaN annual FCF/share row. |
| `ttm` | `_quarterly_ttm_fcf` | Sum of last 4 quarterly FCF rows; `None` if fewer than 4 valid quarters. |

The `auto` cascade prefers normalized over recent because DCF capitalizes the
base into perpetuity — single-period TTM can be distorted by working-capital
swings or one-off capex. McKinsey *Valuation* explicitly recommends a
multi-year normalized FCF as the DCF base.

Explicit `latest_annual`/`ttm`/`3yr_avg` picks **do not fall back** when the
chosen source has no data: the call returns `(None, "missing")` so the UI can
surface an accurate insufficient-data message instead of silently using a
different basis.

A user-supplied `base_cash_flow_per_share` override always wins over the source
cascade.

#### Projection horizon

`projection_years` (5 / 10 / 15) controls the explicit forecast length. The
treasury curve is sampled accordingly (`yield_at(1)` … `yield_at(N)`); the
terminal discount rate uses the 30-year long-term rate regardless of horizon.

#### Turnaround mode

When all three turnaround fields are supplied — `breakeven_year`,
`breakeven_cash_flow_per_share`, `post_breakeven_growth_pct` — the template
builds an explicit per-year FCF schedule via `_build_turnaround_schedule()`
instead of the single-base × growth-curve path. Schedule shape:

- **Years 1 … breakeven_year**: linear interpolation from the *current* TTM
  FCF/share (which may be negative — that's the whole point) to
  `breakeven_cash_flow_per_share` at year `breakeven_year`.
- **Years breakeven_year+1 … horizon**: compound at `post_breakeven_growth_pct`
  with a linear fade toward `terminal_growth_pct` across the remaining years.

Negative cash flows in the early years are reflected honestly in the DCF: each
year's present value is summed, so cash-burn periods reduce intrinsic value.
Status flips to `ready` when the year-N (horizon) FCF is positive; otherwise
the template stays at `insufficient_data` with an explanatory warning.

Bear/base/bull scenario shifts in turnaround mode apply a cumulative
year-over-year compounding bump (`growth_shift_pct` per year) so the three
scenarios diverge meaningfully even on a user-supplied schedule.

Related defaults:

- `Base FCF / Share`: source cascade (see above)
- `Beta`: provider beta first, then TerraFin's computed beta, then `1.0`
- `Equity Risk Premium %`: default `5.0%`
- `Terminal Growth %`: default `3.0%`
- `Projection Years`: default `5`
- `FCF Base Source`: default `auto`

Override the automatic growth input when:

- the business is in a regime shift
- provider EPS is stale
- revenue CAGR is acquisition-driven
- FCF is distorted by one-off capex or working-capital swings
- the company is a financial firm where FCF-style DCF is not a good framing

Use turnaround mode (instead of overrides) when:

- current FCF is negative but the investment thesis is on a future turn
- you need the schedule's losses to count against intrinsic value rather than
  being silently clipped to zero
- you can name a defensible breakeven year (typically 1–5 for operational
  turnarounds; longer is usually better modeled as a different framing)

## Beta

Risk code lives under `src/TerraFin/analytics/analysis/risk/`.

Current built-in methods:

- `beta_5y_monthly`
- `beta_5y_monthly_adjusted`

### Default Method

`beta_5y_monthly` is the reference method:

- lookback: 5 years
- frequency: month-end closes
- formula: `Cov(stock_returns, benchmark_returns) / Var(benchmark_returns)`

`beta_5y_monthly_adjusted` is the stability variant:

- start from `beta_5y_monthly`
- shrink toward `1.0`
- formula: `0.67 * beta_5y_monthly + 0.33 * 1.0`

### Benchmark Mapping

| Market | Benchmark |
|--------|-----------|
| U.S. / default | `^SPX` |
| Korea `.KS` | `^KS11` |
| Korea `.KQ` | `^KQ11` |
| Japan `.T` | `^N225` |

If TerraFin cannot map a ticker confidently, it returns
`unsupported_benchmark` instead of forcing a proxy.

## Code-Adjacent Source

The full code-adjacent source remains on GitHub:

[src/TerraFin/analytics/analysis/README.md](https://github.com/KiUngSong/TerraFin/blob/main/src/TerraFin/analytics/analysis/README.md)
