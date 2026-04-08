from datetime import date

from pandas import DateOffset, Timestamp

from .models import DiscountedCashFlowResult, ProjectionRow


def build_linear_growth_rates(initial_growth_pct: float, terminal_growth_pct: float, years: int) -> list[float]:
    if years <= 0:
        return []
    if years == 1:
        return [float(terminal_growth_pct)]

    step = (terminal_growth_pct - initial_growth_pct) / (years - 1)
    return [float(initial_growth_pct + (step * idx)) for idx in range(years)]


def project_cash_flows(base_cash_flow_per_share: float, growth_rates_pct: list[float]) -> list[float]:
    cash_flows: list[float] = []
    current_cash_flow = float(base_cash_flow_per_share)
    for growth_pct in growth_rates_pct:
        current_cash_flow = current_cash_flow * (1.0 + (float(growth_pct) / 100.0))
        cash_flows.append(current_cash_flow)
    return cash_flows


def clamp_terminal_growth(terminal_growth_pct: float, terminal_discount_rate_pct: float) -> float:
    ceiling = float(terminal_discount_rate_pct) - 1.0
    return float(min(float(terminal_growth_pct), ceiling))


def discount_explicit_cash_flows(
    cash_flows_per_share: list[float],
    growth_rates_pct: list[float],
    discount_rates_pct: list[float],
    *,
    terminal_growth_pct: float,
    terminal_discount_rate_pct: float,
    as_of: date,
    period_year_fractions: list[float] | None = None,
    forecast_dates: list[str] | None = None,
) -> DiscountedCashFlowResult:
    if len(cash_flows_per_share) == 0:
        raise ValueError("At least one projected cash flow is required")
    if len(cash_flows_per_share) != len(discount_rates_pct):
        raise ValueError("Cash-flow and discount-rate lengths must match")
    if growth_rates_pct and len(growth_rates_pct) != len(cash_flows_per_share):
        raise ValueError("Growth-rate and cash-flow lengths must match")
    if period_year_fractions is not None and len(period_year_fractions) != len(cash_flows_per_share):
        raise ValueError("Period-year fractions and cash-flow lengths must match")
    if forecast_dates is not None and len(forecast_dates) != len(cash_flows_per_share):
        raise ValueError("Forecast-date and cash-flow lengths must match")

    growth_path = list(growth_rates_pct) if growth_rates_pct else [0.0] * len(cash_flows_per_share)
    period_lengths = list(period_year_fractions) if period_year_fractions is not None else [1.0] * len(cash_flows_per_share)
    projection_rows: list[ProjectionRow] = []
    cumulative_discount_factor = 1.0
    cumulative_years = 0.0

    for idx, (cash_flow, growth_pct, discount_rate_pct, period_years) in enumerate(
        zip(cash_flows_per_share, growth_path, discount_rates_pct, period_lengths),
        start=1,
    ):
        if float(period_years) < 0:
            raise ValueError("Period-year fractions must be non-negative")

        discount_factor = (1.0 + (float(discount_rate_pct) / 100.0)) ** float(period_years)
        cumulative_discount_factor *= discount_factor
        cumulative_years += float(period_years)
        if forecast_dates is not None:
            forecast_date = forecast_dates[idx - 1]
        elif abs(cumulative_years - round(cumulative_years)) < 1e-9:
            forecast_date = (Timestamp(as_of) + DateOffset(years=int(round(cumulative_years)))).date().isoformat()
        else:
            forecast_date = (Timestamp(as_of) + DateOffset(days=int(round(cumulative_years * 365.25)))).date().isoformat()
        present_value = float(cash_flow) / cumulative_discount_factor
        projection_rows.append(
            ProjectionRow(
                year_offset=idx,
                forecast_date=forecast_date,
                growth_pct=float(growth_pct),
                cash_flow_per_share=float(cash_flow),
                discount_rate_pct=float(discount_rate_pct),
                discount_factor=float(cumulative_discount_factor),
                present_value=float(present_value),
            )
        )

    safe_terminal_growth_pct = clamp_terminal_growth(terminal_growth_pct, terminal_discount_rate_pct)
    terminal_cash_flow = float(cash_flows_per_share[-1]) * (1.0 + (safe_terminal_growth_pct / 100.0))
    denominator = (float(terminal_discount_rate_pct) - safe_terminal_growth_pct) / 100.0
    if denominator <= 0:
        raise ValueError("Terminal discount rate must exceed terminal growth rate by at least 100bps")
    terminal_value = terminal_cash_flow / denominator
    intrinsic_value = sum(row.present_value for row in projection_rows) + (
        terminal_value / projection_rows[-1].discount_factor
    )

    return DiscountedCashFlowResult(
        projected_cash_flows=projection_rows,
        terminal_cash_flow_per_share=float(terminal_cash_flow),
        terminal_growth_pct=float(safe_terminal_growth_pct),
        terminal_discount_rate_pct=float(terminal_discount_rate_pct),
        terminal_value=float(terminal_value),
        intrinsic_value=float(intrinsic_value),
    )
