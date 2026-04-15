---
title: Analytics Modules
summary: What analytics are available today, how they are shaped, and which ones are integrated into the UI and APIs.
read_when:
  - Computing technical indicators (RSI, MACD, MA, Bollinger, volatility, spectral)
  - Running fundamental valuations (DCF)
  - Analyzing options gamma exposure
  - Optimizing portfolios (Black-Litterman)
  - Simulating price paths (GBM)
---

# Analytics Modules

TerraFin's analytics package lives under `src/TerraFin/analytics/`. It is a mix
of:

- pure indicator functions used by the chart and agent APIs
- `TimeSeriesDataFrame` helpers for a few volatility transforms
- standalone analysis modules that are available from Python but not yet exposed
  as first-class interface pages or REST endpoints

The stable product-facing surface today is the chart overlay set plus the
agent-accessible technical indicators. DCF, options, portfolio optimization,
spectral helpers, and GBM simulation are usable from Python but are still
standalone or experimental from a UI/API perspective.

## Base utilities

`get_returns(df: TimeSeriesDataFrame)` in
`src/TerraFin/analytics/analysis/base_analytics.py` is the shared helper for
daily percentage returns with `NaN` rows removed.

## Technical analysis

The technical package is the most mature part of analytics. Most functions are
pure list-based helpers, which makes them easy to reuse from APIs, notebooks,
and adapter code.

### Core indicator contract

Most technical functions:

- accept `list[float]` input
- return an `offset` plus the computed values
- leave alignment to the caller, using `offset` to show how many leading points
  were consumed by the lookback window

| Function | Module | Signature | Returns |
|----------|--------|-----------|---------|
| `rsi` | `technical/rsi.py` | `rsi(closes, window=14)` | `(offset, values)` — offset = window + 1 |
| `macd` | `technical/macd.py` | `macd(closes, fast=12, slow=26, signal_window=9)` | `(offset, macd, signal, histogram)` — offset = slow - 1 |
| `moving_average` | `technical/ma.py` | `moving_average(closes, window)` | `(offset, values)` — offset = window - 1 |
| `bollinger_bands` | `technical/bollinger.py` | `bollinger_bands(closes, window=20, num_std=2.0)` | `(offset, upper, lower)` — offset = window - 1 |
| `realized_vol` | `technical/volatility.py` | `realized_vol(closes, window=21)` | `(offset, values)` — annualized, offset = window |
| `range_vol` | `technical/volatility.py` | `range_vol(highs, lows, window=20)` | `(offset, values)` — Parkinson's, offset = window - 1 |
| `trend_signal` | `technical/trend_signal.py` | `trend_signal(closes, window=126, distribution="normal", df=5)` | `(offset, values)` — Delta-Straddle signal in [-1, +1], offset = window + 1 |
| `trend_signal_composite` | `technical/trend_signal.py` | `trend_signal_composite(closes, windows=[32,64,126,252,504])` | `(offset, values)` — multi-timeframe averaged signal in [-1, +1] |
| `mandelbrot_fractal_dimension` | `technical/mandelbrot.py` | `mandelbrot_fractal_dimension(closes, window=65)` | `(offset, values)` — rolling path-complexity score in [1, 2], where lower is smoother / more fragile and higher is choppier / more anti-fragile. TerraFin's chart defaults to the 130-day view, while agent consumers can request 65, 130, and 260 explicitly. |
| `percentile_rank` | `technical/vol_regime.py` | `percentile_rank(values, window=126)` | `(offset, ranks)` — rolling min-max rank in [0, 100] |
| `vol_regime` | `technical/vol_regime.py` | `vol_regime(values, window=126, entry_threshold=20.0, exit_threshold=80.0)` | `(offset, regimes)` — 1=stable, 0=unstable with hysteresis |
| `lppl` | `technical/lppl.py` | `lppl(closes, n_windows=33, min_window=50, max_window=750, window_step=5, max_iter=45, seed=42)` | `LPPLResult` — confidence, full-series fit, qualifying sub-window fits. Pass `n_windows=None` to use the full article ladder (750→50 in 5-day steps). |

All module paths are relative to `src/TerraFin/analytics/analysis/`.

`technical/macd.py` also exposes `ema(values, span)` as a reusable helper.

### Spectral analysis

`technical/spectral.py` contains frequency-domain utilities for cycle analysis.
These are currently standalone helpers rather than chart overlays.

| Function | Purpose |
|----------|---------|
| `power_spectrum(closes, window_func="hanning")` | FFT periodogram of log returns |
| `dominant_cycles(closes, top_n=5, window_func="hanning")` | Highest-signal periodic cycles |
| `amplitude_phase(closes, window_func="hanning")` | Amplitude and phase per frequency |
| `spectral_filter(closes, min_period=2.0, max_period=inf)` | Band-pass filtering on returns |
| `spectrogram(closes, segment_size=64, overlap=48)` | Sliding-window time-frequency power map |

### TimeSeriesDataFrame wrappers

`technical/volatility.py` also exposes pandas-friendly wrappers:

| Function | Input | Output |
|----------|-------|--------|
| `realized_volatility(df, window_size=21)` | `TimeSeriesDataFrame` | `TimeSeriesDataFrame` |
| `range_volatility(df, window=20)` | `TimeSeriesDataFrame` | `TimeSeriesDataFrame` |

## Fundamental analysis

Fundamental analysis lives under `src/TerraFin/analytics/analysis/fundamental/`.
DCF now lives in the dedicated package `src/TerraFin/analytics/analysis/fundamental/dcf/`.

| Entry point | Purpose |
|-------------|---------|
| `build_sp500_dcf_payload()` | Build the S&P 500 valuation payload used by Market Insights |
| `build_stock_dcf_payload(ticker)` | Build the stock valuation payload used by the Stock Analysis page |
| `build_stock_reverse_dcf_payload(ticker)` | Build the reverse DCF payload used by the Stock Analysis page |
| `build_sp500_template()` / `build_stock_template(ticker)` | Build the underlying valuation templates before presentation |

DCF is exposed through the product and API endpoints:
- `GET /market-insights/api/dcf/sp500`
- `GET /stock/api/dcf?ticker=...`
- `GET /stock/api/reverse-dcf?ticker=...`

Current DCF assumption notes now live in
[Analytics Notes](./analytics-notes.md).

## Risk analysis

Risk analysis lives under `src/TerraFin/analytics/analysis/risk/`.

| Entry point | Purpose |
|-------------|---------|
| `estimate_beta_5y_monthly(symbol)` | Compute TerraFin's default 5-year monthly regression beta |
| `estimate_beta_5y_monthly_adjusted(symbol)` | Compute the adjusted companion beta that shrinks toward `1.0` |
| `select_default_benchmark(symbol)` | Resolve the exchange-aware benchmark TerraFin uses for beta |

This package is currently Python-first, but `beta_5y_monthly` is now used as
the stock DCF and reverse DCF fallback when provider beta is unavailable.
Stock Analysis also exposes `GET /stock/api/beta-estimate?ticker=...` for the
manual beta-compute action in the DCF workbenches.

Beta-method and benchmark-mapping notes also live in
[Analytics Notes](./analytics-notes.md).

## Options analysis

Options analysis lives under `src/TerraFin/analytics/analysis/options/`.

| Entry point | Purpose |
|-------------|---------|
| `get_current_gex(ticker)` | Fetch delayed options data and compute gamma exposure views |
| `GEX_Output` | Dataclass containing spot price and two Plotly figures |

This module currently works as a standalone Python utility. It is not served by
the TerraFin interface routes.

## Portfolio optimization

Portfolio optimization lives under `src/TerraFin/analytics/analysis/portfolio/`.

| Entry point | Purpose |
|-------------|---------|
| `black_litterman(...)` | Run a Black-Litterman allocation workflow |
| `BLOutput` | Dataclass with prior/posterior returns and weights |

This is implemented as a standalone computation module rather than a UI feature.

## Simulation

Simulation lives under `src/TerraFin/analytics/simulation/`.

| Entry point | Purpose |
|-------------|---------|
| `run_base_gbm(time_series_df, num_simulation=100, pred_ratio=0.2)` | Simulate price paths with geometric Brownian motion |

The simulation helper is available from Python and notebook workflows.

## Integration status

This is the quickest way to understand what is already connected to the product:

| Area | Status |
|------|--------|
| Chart auto-overlays | Stable |
| Agent API indicators | Stable |
| DCF | Stable on-demand UI/API feature in Market Insights and Stock Analysis |
| Options / portfolio / GBM | Standalone, not yet first-class UI/API features |
| Risk beta toolkit | Partially integrated — used as the stock DCF fallback and exposed through the stock beta-estimate API |
| Trend signal (Delta-Straddle) | Stable — chart overlay and agent API |
| Mandelbrot Fractal Dimension | Stable — chart overlay and agent API |
| Vol regime (percentile rank + hysteresis) | Stable — chart overlay and agent API |
| LPPL (Bubble detection) | Calibrated default active in chart overlay and agent API; full article ladder remains available in the analytics helper for research/debug runs |
| Spectral analysis | Experimental helper |
| Notebook demos | Supported but manual-only, not product-critical regression coverage |

Notebook demos live in `notebooks/analytics/`.
They should stay as manual/exploratory notebooks, not `test_*.py` replacements.
Each demo notebook should use the same explicit `configure()` bootstrap pattern
described in [Getting Started](./getting-started.md) and
[Interface Overview](./interface.md) at the top of the first code cell.

## See also

- [feature-integration.md](./feature-integration.md) for the ownership rule when a new indicator or analysis becomes a public feature
- [data-layer.md](./data-layer.md) for the input types analytics consume
- [interface.md](./interface.md) for the chart and agent APIs that call these helpers
