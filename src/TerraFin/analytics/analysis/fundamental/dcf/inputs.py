import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from TerraFin.analytics.analysis.risk import BETA_5Y_MONTHLY_METHOD_ID, estimate_beta_5y_monthly
from TerraFin.data import DataFactory
from TerraFin.data.providers.corporate.fundamentals import get_corporate_data
from TerraFin.data.providers.market.ticker_info import get_ticker_info

from .models import DCFInputTemplate, SP500DCFOverrides, SP500YearAssumption, StockDCFOverrides
from .rates import fit_current_treasury_curve


DEFAULT_ERP_PCT = 5.0
DEFAULT_TERMINAL_GROWTH_PCT = 3.0
DEFAULT_STOCK_GROWTH_PCT = 6.0
DEFAULT_STOCK_PROJECTION_YEARS = 5
ALLOWED_STOCK_PROJECTION_YEARS = (5, 10, 15)
SP500Methodology = Literal["shareholder_yield", "earnings_power"]

_SP500_DEFAULTS_PATH = Path(__file__).with_name("sp500_defaults.json")


def load_sp500_defaults() -> dict[str, Any]:
    return json.loads(_SP500_DEFAULTS_PATH.read_text())


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return float(parsed)


def _latest_close(symbol: str, data_factory: DataFactory) -> float | None:
    try:
        frame = data_factory.get_market_data(symbol)
    except Exception:
        return None
    if frame.empty or "close" not in frame.columns:
        return None
    series = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def _classify_quality(*, fallback_used: bool, warning_count: int) -> str:
    if fallback_used and warning_count:
        return "fallback"
    if fallback_used or warning_count:
        return "mixed"
    return "live"


def _statement_column_lookup(frame: pd.DataFrame) -> dict[str, str]:
    return {
        str(column).strip().lower().replace(" ", "").replace("-", ""): str(column)
        for column in frame.columns
        if str(column) != "date"
    }


def _statement_series(frame: pd.DataFrame | None, candidates: tuple[str, ...]) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    lookup = _statement_column_lookup(frame)
    for candidate in candidates:
        key = candidate.strip().lower().replace(" ", "").replace("-", "")
        matched = lookup.get(key)
        if matched is not None:
            return pd.to_numeric(frame[matched], errors="coerce")
    return None


def _annual_fcf_series(cashflow_frame: pd.DataFrame | None) -> pd.Series | None:
    if cashflow_frame is None or cashflow_frame.empty:
        return None
    operating_cf = _statement_series(
        cashflow_frame,
        (
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "Cash Flow From Continuing Operating Activities",
        ),
    )
    capex = _statement_series(
        cashflow_frame,
        (
            "Capital Expenditure",
            "Capital Expenditures",
            "Purchase Of PPE",
        ),
    )
    if operating_cf is None or capex is None:
        return None
    return operating_cf - capex.abs()


def _annual_revenue_series(income_frame: pd.DataFrame | None) -> pd.Series | None:
    if income_frame is None or income_frame.empty:
        return None
    return _statement_series(
        income_frame,
        (
            "Total Revenue",
            "Revenue",
            "Operating Revenue",
            "Net Sales",
            "Sales",
        ),
    )


def _latest_stock_fcf(cashflow_quarter: pd.DataFrame | None, cashflow_annual: pd.DataFrame | None) -> tuple[float | None, str]:
    quarterly_fcf = _annual_fcf_series(cashflow_quarter)
    if quarterly_fcf is not None and len(quarterly_fcf.dropna()) >= 4:
        return float(quarterly_fcf.head(4).sum()), "quarterly_ttm"

    annual_fcf = _annual_fcf_series(cashflow_annual)
    if annual_fcf is not None and not annual_fcf.dropna().empty:
        return float(annual_fcf.iloc[0]), "annual"

    return None, "missing"


def _three_year_avg_fcf(cashflow_annual: pd.DataFrame | None) -> float | None:
    series = _annual_fcf_series(cashflow_annual)
    if series is None:
        return None
    values = series.dropna().head(3)
    if len(values) < 2:
        return None
    return float(values.mean())


def _latest_annual_fcf(cashflow_annual: pd.DataFrame | None) -> float | None:
    series = _annual_fcf_series(cashflow_annual)
    if series is None:
        return None
    values = series.dropna()
    if values.empty:
        return None
    return float(values.iloc[0])


def _quarterly_ttm_fcf(cashflow_quarter: pd.DataFrame | None) -> float | None:
    series = _annual_fcf_series(cashflow_quarter)
    if series is None or len(series.dropna()) < 4:
        return None
    return float(series.head(4).sum())


def _select_stock_fcf_base(
    cashflow_quarter: pd.DataFrame | None,
    cashflow_annual: pd.DataFrame | None,
    *,
    source: str = "auto",
) -> tuple[float | None, str]:
    """Pick the base FCF for DCF from one of four sources.

    source: "auto" | "3yr_avg" | "ttm" | "latest_annual".
    Under "auto", cascade prefers normalized over recent: 3yr_avg → annual → quarterly_ttm.
    This is the professional default — DCF capitalizes FCF into perpetuity, so the base
    should be a defensible run-rate, not a single-period observation that may reflect
    working-capital swings or capex lumpiness.
    Explicit picks do not fall back; if the requested source has no data, returns
    (None, "missing") so callers surface an accurate insufficient-data message.
    """
    if source == "3yr_avg":
        value = _three_year_avg_fcf(cashflow_annual)
        return (value, "3yr_avg") if value is not None else (None, "missing")
    if source == "ttm":
        value = _quarterly_ttm_fcf(cashflow_quarter)
        return (value, "quarterly_ttm") if value is not None else (None, "missing")
    if source == "latest_annual":
        value = _latest_annual_fcf(cashflow_annual)
        return (value, "annual") if value is not None else (None, "missing")

    # auto cascade
    value = _three_year_avg_fcf(cashflow_annual)
    if value is not None:
        return value, "3yr_avg"
    value = _latest_annual_fcf(cashflow_annual)
    if value is not None:
        return value, "annual"
    value = _quarterly_ttm_fcf(cashflow_quarter)
    if value is not None:
        return value, "quarterly_ttm"
    return None, "missing"


def _series_cagr_pct(series: pd.Series | None, *, points: int = 4) -> float | None:
    if series is None:
        return None
    values = series.dropna().head(points)
    if len(values) < points:
        return None
    latest = float(values.iloc[0])
    oldest = float(values.iloc[-1])
    if latest <= 0 or oldest <= 0:
        return None
    years = len(values) - 1
    return float((((latest / oldest) ** (1 / years)) - 1.0) * 100.0)


def _fcf_cagr_pct(cashflow_annual: pd.DataFrame | None) -> float | None:
    return _series_cagr_pct(_annual_fcf_series(cashflow_annual))


def _revenue_cagr_pct(income_annual: pd.DataFrame | None) -> float | None:
    return _series_cagr_pct(_annual_revenue_series(income_annual))


def _coalesce_positive(value: float | None, fallback: float | None) -> float | None:
    if value is not None and value > 0:
        return float(value)
    if fallback is not None and fallback > 0:
        return float(fallback)
    return None


def _load_sp500_yearly_assumptions(
    defaults: dict[str, Any],
    overrides: SP500DCFOverrides | None,
) -> list[SP500YearAssumption]:
    override_rows = list(overrides.yearly_assumptions) if overrides and overrides.yearly_assumptions else []
    source_rows = override_rows or list(defaults.get("yearly_assumptions", []))
    assumptions: list[SP500YearAssumption] = []
    for index, row in enumerate(source_rows, start=1):
        if isinstance(row, SP500YearAssumption):
            assumptions.append(row)
            continue
        assumptions.append(
            SP500YearAssumption(
                year_offset=int(row.get("year_offset", row.get("yearOffset", index))),
                growth_pct=float(row.get("growth_pct", row.get("growthPct"))),
                payout_ratio_pct=float(row.get("payout_ratio_pct", row.get("payoutRatioPct"))),
                buyback_ratio_pct=float(row.get("buyback_ratio_pct", row.get("buybackRatioPct"))),
                equity_risk_premium_pct=float(
                    row.get("equity_risk_premium_pct", row.get("equityRiskPremiumPct"))
                ),
            )
        )
    return assumptions


def build_sp500_template(
    *,
    methodology: SP500Methodology = "shareholder_yield",
    as_of: date | None = None,
    data_factory: DataFactory | None = None,
    overrides: SP500DCFOverrides | None = None,
) -> DCFInputTemplate:
    snapshot_date = as_of or date.today()
    defaults = load_sp500_defaults()
    factory = data_factory or DataFactory()
    warnings: list[str] = []

    current_price = _latest_close("^SPX", factory)
    curve = fit_current_treasury_curve(data_factory=factory, as_of=snapshot_date)
    base_year = int(defaults.get("base_year", snapshot_date.year - 1))
    configured_base_year_eps = _safe_float(defaults.get("base_year_eps"))
    base_year_eps = _coalesce_positive(
        overrides.base_year_eps if overrides else None,
        configured_base_year_eps,
    )
    yearly_assumptions = _load_sp500_yearly_assumptions(defaults, overrides)
    if not yearly_assumptions:
        raise ValueError("S&P 500 yearly assumptions are required")

    if base_year_eps is None:
        warnings.append("Base-year S&P 500 EPS unavailable.")
        base_growth_pct = DEFAULT_STOCK_GROWTH_PCT
    else:
        base_growth_pct = float(yearly_assumptions[0].growth_pct)

    first_year_assumption = yearly_assumptions[0]
    shareholder_payout_ratio_pct = float(
        first_year_assumption.payout_ratio_pct + first_year_assumption.buyback_ratio_pct
    )
    shareholder_yield_cash_flow = (base_year_eps * shareholder_payout_ratio_pct / 100.0) if base_year_eps is not None else None
    earnings_power_cash_flow = base_year_eps

    if methodology == "earnings_power":
        base_cash_flow = earnings_power_cash_flow
        valuation_method_label = "Earnings Power"
        valuation_method_description = "Cash flow is proxied by index EPS as a broad owner-earnings measure."
    else:
        base_cash_flow = shareholder_yield_cash_flow
        valuation_method_label = "Shareholder Yield"
        valuation_method_description = "Cash flow is proxied by dividends plus net buybacks distributed to shareholders."

    quality_mode = _classify_quality(
        fallback_used=curve.fallback_used,
        warning_count=len(warnings),
    )
    terminal_growth_pct = _coalesce_positive(
        overrides.terminal_growth_pct if overrides else None,
        _safe_float(defaults.get("terminal_growth_pct")),
    )
    terminal_equity_risk_premium_pct = _coalesce_positive(
        overrides.terminal_equity_risk_premium_pct if overrides else None,
        _safe_float(defaults.get("terminal_equity_risk_premium_pct")),
    )
    terminal_roe_pct = _coalesce_positive(
        overrides.terminal_roe_pct if overrides else None,
        _safe_float(defaults.get("terminal_roe_pct")),
    )
    if terminal_growth_pct is None:
        terminal_growth_pct = DEFAULT_TERMINAL_GROWTH_PCT
    if terminal_equity_risk_premium_pct is None:
        terminal_equity_risk_premium_pct = float(yearly_assumptions[-1].equity_risk_premium_pct)

    return DCFInputTemplate(
        status="ready" if current_price is not None and base_cash_flow is not None else "insufficient_data",
        entity_type="index",
        symbol="S&P 500",
        as_of=snapshot_date,
        current_price=current_price,
        base_cash_flow_per_share=base_cash_flow,
        base_growth_pct=base_growth_pct,
        terminal_growth_pct=terminal_growth_pct,
        yearly_risk_free_rates_pct=[curve.yield_at(maturity) for maturity in (1, 2, 3, 4, 5)],
        terminal_risk_free_rate_pct=curve.yield_at(30),
        discount_spread_pct=float(first_year_assumption.equity_risk_premium_pct),
        rate_curve=curve,
        assumptions={
            "priceSymbol": "^SPX",
            "valuationMethod": methodology,
            "valuationMethodLabel": valuation_method_label,
            "valuationMethodDescription": valuation_method_description,
            "valuationHorizon": "year_end_target",
            "valuationHeadlineLabel": f"{snapshot_date.year} Year-End Target",
            "targetYear": snapshot_date.year,
            "targetYearEndDate": f"{snapshot_date.year}-12-31",
            "baseYear": base_year,
            "baseYearEps": base_year_eps,
            "shareholderPayoutRatioPct": shareholder_payout_ratio_pct,
            "payoutRatioPct": float(first_year_assumption.payout_ratio_pct),
            "buybackRatioPct": float(first_year_assumption.buyback_ratio_pct),
            "baseGrowthPct": base_growth_pct,
            "baseCashFlowPerShare": base_cash_flow,
            "shareholderYieldCashFlowPerShare": shareholder_yield_cash_flow,
            "earningsPowerCashFlowPerShare": earnings_power_cash_flow,
            "equityRiskPremiumPct": float(first_year_assumption.equity_risk_premium_pct),
            "terminalEquityRiskPremiumPct": terminal_equity_risk_premium_pct,
            "terminalRoePct": terminal_roe_pct,
            "yearlyAssumptions": [
                {
                    "yearOffset": row.year_offset,
                    "year": base_year + row.year_offset,
                    "growthPct": float(row.growth_pct),
                    "payoutRatioPct": float(row.payout_ratio_pct),
                    "buybackRatioPct": float(row.buyback_ratio_pct),
                    "equityRiskPremiumPct": float(row.equity_risk_premium_pct),
                }
                for row in yearly_assumptions
            ],
            "defaultsVersion": defaults["version"],
            "sensitivityDiscountRateShiftsBps": defaults["sensitivity_discount_rate_shifts_bps"],
            "sensitivityTerminalGrowthShiftsBps": defaults["sensitivity_terminal_growth_shifts_bps"],
        },
        data_quality={
            "mode": quality_mode,
            "sources": ["market:^SPX", "treasury.market-indicators", "sp500_defaults"],
        },
        warnings=warnings,
    )


def _resolve_projection_years(requested: int | None) -> int:
    if requested is None:
        return DEFAULT_STOCK_PROJECTION_YEARS
    value = int(requested)
    if value not in ALLOWED_STOCK_PROJECTION_YEARS:
        raise ValueError(
            f"projection_years must be one of {ALLOWED_STOCK_PROJECTION_YEARS}, got {value}"
        )
    return value


def _turnaround_fields_complete(overrides: StockDCFOverrides | None) -> bool:
    if overrides is None:
        return False
    return (
        overrides.breakeven_year is not None
        and overrides.breakeven_cash_flow_per_share is not None
        and overrides.post_breakeven_growth_pct is not None
    )


def _build_turnaround_schedule(
    *,
    starting_cash_flow_per_share: float,
    breakeven_year: int,
    breakeven_cash_flow_per_share: float,
    post_breakeven_growth_pct: float,
    terminal_growth_pct: float,
    projection_years: int,
) -> list[float]:
    """Return explicit FCF/share schedule of length `projection_years`.

    Pre-breakeven years: linear interpolation from `starting_cash_flow_per_share`
    (possibly negative) to `breakeven_cash_flow_per_share` at year `breakeven_year`.
    Post-breakeven years: compound at `post_breakeven_growth_pct` with a linear
    fade toward `terminal_growth_pct` across the remaining horizon.
    """
    if projection_years <= 0:
        return []
    if breakeven_year < 1:
        raise ValueError("breakeven_year must be >= 1")
    if breakeven_year > projection_years:
        raise ValueError("breakeven_year must not exceed projection_years")

    schedule: list[float] = []
    start = float(starting_cash_flow_per_share)
    breakeven = float(breakeven_cash_flow_per_share)
    for year in range(1, breakeven_year + 1):
        fraction = year / breakeven_year
        schedule.append(start + (breakeven - start) * fraction)

    remaining = projection_years - breakeven_year
    if remaining <= 0:
        return schedule

    initial_growth = float(post_breakeven_growth_pct)
    terminal_growth = float(terminal_growth_pct)
    current = schedule[-1]
    for idx in range(remaining):
        if remaining == 1:
            growth_pct = terminal_growth
        else:
            progress = idx / (remaining - 1)
            growth_pct = initial_growth + (terminal_growth - initial_growth) * progress
        current = current * (1.0 + (growth_pct / 100.0))
        schedule.append(current)
    return schedule


def build_stock_template(
    ticker: str,
    *,
    as_of: date | None = None,
    data_factory: DataFactory | None = None,
    overrides: StockDCFOverrides | None = None,
    projection_years: int | None = None,
) -> DCFInputTemplate:
    normalized = ticker.upper()
    snapshot_date = as_of or date.today()
    factory = data_factory or DataFactory()
    warnings: list[str] = []
    curve = fit_current_treasury_curve(data_factory=factory, as_of=snapshot_date)
    horizon = _resolve_projection_years(projection_years)

    info = get_ticker_info(normalized) or {}
    current_price = _coalesce_positive(
        overrides.current_price if overrides else None,
        _safe_float(info.get("currentPrice")) or _safe_float(info.get("regularMarketPrice")),
    )
    if current_price is None:
        current_price = _latest_close(normalized, factory)
        if current_price is not None:
            warnings.append("Current price was inferred from market history instead of ticker metadata.")

    shares_outstanding = _safe_float(info.get("sharesOutstanding"))
    beta = _coalesce_positive(overrides.beta if overrides else None, _safe_float(info.get("beta")))
    beta_source = "provider"
    beta_method_id = None
    beta_benchmark_symbol = None
    if overrides and overrides.beta is not None:
        beta_source = "user_override"
    elif beta is None or beta <= 0:
        beta_estimate = estimate_beta_5y_monthly(normalized, data_factory=factory)
        if beta_estimate.status == "ready" and beta_estimate.beta is not None and beta_estimate.beta > 0:
            beta = float(beta_estimate.beta)
            beta_source = "computed"
            beta_method_id = beta_estimate.method_id
            beta_benchmark_symbol = beta_estimate.benchmark_symbol
            benchmark_text = beta_estimate.benchmark_symbol or "default benchmark"
            warnings.append(
                f"Ticker beta was unavailable from provider metadata; using computed {BETA_5Y_MONTHLY_METHOD_ID} vs {benchmark_text}."
            )
        else:
            beta = 1.0
            beta_source = "fallback_1.0"
            if beta_estimate.warnings:
                warnings.extend(beta_estimate.warnings)
            warnings.append("Ticker beta unavailable; using 1.0.")

    cashflow_quarter = get_corporate_data(normalized, "cashflow", period="quarter")
    cashflow_annual = get_corporate_data(normalized, "cashflow", period="annual")
    income_annual = get_corporate_data(normalized, "income", period="annual")
    fcf_base_source = (
        overrides.fcf_base_source
        if overrides is not None and overrides.fcf_base_source is not None
        else "auto"
    )
    latest_fcf, cashflow_source = _select_stock_fcf_base(
        cashflow_quarter, cashflow_annual, source=fcf_base_source
    )

    if latest_fcf is None and not (overrides and overrides.base_cash_flow_per_share is not None):
        warnings.append("Free cash flow data is unavailable.")

    if shares_outstanding is None or shares_outstanding <= 0:
        warnings.append("Shares outstanding data is unavailable.")

    derived_base_cash_flow_per_share = None
    if latest_fcf is not None and shares_outstanding and shares_outstanding > 0:
        derived_base_cash_flow_per_share = latest_fcf / shares_outstanding
    base_cash_flow_per_share = _coalesce_positive(
        overrides.base_cash_flow_per_share if overrides else None,
        derived_base_cash_flow_per_share,
    )
    if overrides and overrides.base_cash_flow_per_share is not None:
        cashflow_source = "user_override"

    trailing_eps = _safe_float(info.get("trailingEps"))
    forward_eps = _safe_float(info.get("forwardEps"))
    growth_source = "default"
    base_growth_pct = None
    if overrides and overrides.base_growth_pct is not None:
        base_growth_pct = float(overrides.base_growth_pct)
        growth_source = "user_override"
    elif trailing_eps and forward_eps and trailing_eps > 0 and forward_eps > 0:
        base_growth_pct = ((forward_eps / trailing_eps) - 1.0) * 100.0
        growth_source = "eps"
    else:
        revenue_cagr_pct = _revenue_cagr_pct(income_annual)
        if revenue_cagr_pct is not None:
            base_growth_pct = revenue_cagr_pct
            growth_source = "revenue_cagr"
            warnings.append("Growth was inferred from annual revenue CAGR because EPS guidance was unavailable.")
        else:
            fcf_cagr_pct = _fcf_cagr_pct(cashflow_annual)
            if fcf_cagr_pct is not None:
                base_growth_pct = fcf_cagr_pct
                growth_source = "fcf_cagr"
                warnings.append("Growth was inferred from annual FCF CAGR because EPS guidance and revenue history were unavailable.")
            else:
                base_growth_pct = DEFAULT_STOCK_GROWTH_PCT
                growth_source = "default"
                warnings.append("Growth was inferred from the default 6% fallback after EPS, revenue, and FCF growth inputs were unavailable.")

    turnaround_active = _turnaround_fields_complete(overrides)
    turnaround_schedule: list[float] | None = None
    turnaround_assumptions: dict[str, Any] | None = None

    equity_risk_premium_pct = _coalesce_positive(
        overrides.equity_risk_premium_pct if overrides else None,
        DEFAULT_ERP_PCT,
    )
    terminal_growth_pct = _coalesce_positive(
        overrides.terminal_growth_pct if overrides else None,
        DEFAULT_TERMINAL_GROWTH_PCT,
    )

    if turnaround_active and overrides is not None:
        breakeven_year = int(overrides.breakeven_year)  # type: ignore[arg-type]
        breakeven_cash_flow = float(overrides.breakeven_cash_flow_per_share)  # type: ignore[arg-type]
        post_breakeven_growth = float(overrides.post_breakeven_growth_pct)  # type: ignore[arg-type]
        if breakeven_year > horizon:
            raise ValueError("breakeven_year must not exceed projection_years")
        starting_cash_flow = (
            float(overrides.base_cash_flow_per_share)
            if overrides.base_cash_flow_per_share is not None
            else (derived_base_cash_flow_per_share if derived_base_cash_flow_per_share is not None else 0.0)
        )
        turnaround_schedule = _build_turnaround_schedule(
            starting_cash_flow_per_share=starting_cash_flow,
            breakeven_year=breakeven_year,
            breakeven_cash_flow_per_share=breakeven_cash_flow,
            post_breakeven_growth_pct=post_breakeven_growth,
            terminal_growth_pct=terminal_growth_pct,
            projection_years=horizon,
        )
        turnaround_assumptions = {
            "active": True,
            "breakevenYear": breakeven_year,
            "breakevenCashFlowPerShare": breakeven_cash_flow,
            "postBreakevenGrowthPct": post_breakeven_growth,
            "startingCashFlowPerShare": starting_cash_flow,
            "cashFlowsPerShare": [float(v) for v in turnaround_schedule],
        }
        # In turnaround mode, expose the year-1 projected FCF/share as the
        # template's displayed base so the headline panel still has a value.
        base_cash_flow_per_share = turnaround_schedule[0]
        cashflow_source = "turnaround_schedule"
        base_growth_pct = post_breakeven_growth
        growth_source = "turnaround_schedule"

    if not turnaround_active:
        if derived_base_cash_flow_per_share is not None and derived_base_cash_flow_per_share <= 0:
            warnings.append("Free cash flow per share is not positive; valuation marked as insufficient data.")
        elif base_cash_flow_per_share is not None and base_cash_flow_per_share <= 0:
            warnings.append("Free cash flow per share is not positive; valuation marked as insufficient data.")

    quality_mode = _classify_quality(
        fallback_used=curve.fallback_used or growth_source == "default",
        warning_count=len(warnings),
    )
    if turnaround_active:
        last_projected = turnaround_schedule[-1] if turnaround_schedule else None
        status = (
            "ready"
            if current_price is not None and last_projected is not None and last_projected > 0
            else "insufficient_data"
        )
        if status != "ready" and current_price is not None:
            warnings.append(
                "Turnaround schedule does not end with a positive FCF/share at the projection horizon."
            )
    else:
        status = (
            "ready"
            if current_price is not None and base_cash_flow_per_share is not None and base_cash_flow_per_share > 0
            else "insufficient_data"
        )

    assumptions: dict[str, Any] = {
        "baseCashFlowPerShare": base_cash_flow_per_share,
        "baseGrowthPct": base_growth_pct,
        "growthSource": growth_source,
        "cashflowSource": cashflow_source,
        "latestFcf": latest_fcf,
        "sharesOutstanding": shares_outstanding,
        "beta": beta,
        "betaSource": beta_source,
        "betaMethodId": beta_method_id,
        "betaBenchmarkSymbol": beta_benchmark_symbol,
        "equityRiskPremiumPct": equity_risk_premium_pct,
        "discountSpreadPct": float(beta * equity_risk_premium_pct),
        "trailingEps": trailing_eps,
        "forwardEps": forward_eps,
    }
    if turnaround_assumptions is not None:
        assumptions["turnaround"] = turnaround_assumptions

    return DCFInputTemplate(
        status=status,
        entity_type="stock",
        symbol=normalized,
        as_of=snapshot_date,
        current_price=current_price,
        base_cash_flow_per_share=base_cash_flow_per_share,
        base_growth_pct=base_growth_pct,
        terminal_growth_pct=terminal_growth_pct,
        yearly_risk_free_rates_pct=[curve.yield_at(year) for year in range(1, horizon + 1)],
        terminal_risk_free_rate_pct=curve.yield_at(30),
        discount_spread_pct=float(beta * equity_risk_premium_pct),
        rate_curve=curve,
        assumptions=assumptions,
        data_quality={
            "mode": quality_mode,
            "sources": [f"market-info:{normalized}", f"market:{normalized}", "treasury.market-indicators", "yfinance_fundamentals"],
        },
        warnings=warnings,
    )


def with_status(template: DCFInputTemplate, *, status: str, warning: str | None = None) -> DCFInputTemplate:
    warnings = list(template.warnings)
    if warning:
        warnings.append(warning)
    return replace(template, status=status, warnings=warnings)
