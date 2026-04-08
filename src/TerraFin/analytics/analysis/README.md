# Analytics Notes

This file keeps model assumptions and implementation notes close to the
analytics code instead of spreading them across multiple top-level docs pages.

## DCF

DCF code lives under `fundamental/dcf/`.

| Model | What it is trying to answer | Main checked-in data |
|------|------------------------------|----------------------|
| S&P 500 DCF | A year-end target framework | `fundamental/dcf/sp500_defaults.json` |
| Stock DCF | A spot equity valuation framework | derived from live company inputs plus explicit defaults |

### S&P 500 DCF

The index model is a `year-end target` model, not a spot fair-value model.

The operating rule is:

1. keep explicit checked-in assumptions for EPS, growth, payout, buybacks, and ERP
2. use the live Treasury curve for the risk-free rate
3. use `^SPX` as a comparison anchor, not as a way to reverse-engineer the model from spot multiples

When refreshing `sp500_defaults.json`, use this order:

1. set a defensible public strategist target range
2. refresh the nominal base-year EPS context
3. refresh the explicit growth fade schedule
4. refresh payout and buyback assumptions
5. refresh ERP and terminal discounting assumptions
6. verify the resulting target still lands in a reasonable public range

### Stock DCF

The stock model needs one starting growth assumption:

- `Base Growth %`

That field is the initial FCF-per-share growth rate before the model fades it
toward terminal growth.

Current fallback order in `build_stock_template()`:

1. user override
2. EPS growth from `forwardEps` versus `trailingEps`
3. annual revenue CAGR
4. annual FCF CAGR
5. default `6%`

Why revenue comes before FCF CAGR:

- revenue is usually more stable
- FCF is more sensitive to capex timing and working-capital noise
- revenue is often the better default growth anchor when explicit EPS guidance is missing

Related defaults:

- `Base FCF / Share`: TTM quarterly FCF if possible, else latest annual FCF
- `Beta`: provider beta first, then TerraFin's computed beta, then `1.0`
- `Equity Risk Premium %`: default `5.0%`
- `Terminal Growth %`: default `3.0%`

Override the automatic growth input when:

- the business is in a regime shift
- provider EPS is stale
- revenue CAGR is acquisition-driven
- FCF is distorted by one-off capex or working-capital swings
- the company is a financial firm where FCF-style DCF is not a good framing

## Beta

Risk code lives under `risk/`.

Current built-in methods:

- `beta_5y_monthly`
- `beta_5y_monthly_adjusted`

### Current default

`beta_5y_monthly` is the reference method:

- lookback: 5 years
- frequency: month-end closes
- formula: `Cov(stock_returns, benchmark_returns) / Var(benchmark_returns)`

`beta_5y_monthly_adjusted` is the stability variant:

- start from `beta_5y_monthly`
- shrink toward `1.0`
- formula: `0.67 * beta_5y_monthly + 0.33 * 1.0`

### Benchmark mapping

Default benchmark routing is intentionally narrow and exchange-aware:

| Market | Benchmark |
|--------|-----------|
| U.S. / default | `^SPX` |
| Korea `.KS` | `^KS11` |
| Korea `.KQ` | `^KQ11` |
| Japan `.T` | `^N225` |

If TerraFin cannot map a ticker confidently, it returns
`unsupported_benchmark` instead of forcing a proxy.

That is deliberate:

- a wrong-market beta is more misleading than no computed beta
- discount-rate inputs look precise, so bad benchmark fallbacks create false confidence

### Scope

This beta implementation is intentionally lightweight. It mainly supports:

- stock DCF fallback when provider beta is missing
- reverse DCF fallback when provider beta is missing
- the Stock Analysis manual compute action through `/stock/api/beta-estimate`

The current stable contract is simple:

- `beta_5y_monthly` is the default
- `beta_5y_monthly_adjusted` is the built-in alternative
