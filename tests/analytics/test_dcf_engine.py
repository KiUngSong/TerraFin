from datetime import date

from TerraFin.analytics.analysis.fundamental.dcf.engine import (
    build_linear_growth_rates,
    discount_explicit_cash_flows,
)


def test_build_linear_growth_rates_interpolates_horizon() -> None:
    growth_rates = build_linear_growth_rates(12.0, 4.0, 5)
    assert [round(value, 2) for value in growth_rates] == [12.0, 10.0, 8.0, 6.0, 4.0]


def test_discount_explicit_cash_flows_clamps_terminal_growth_and_anchors_dates() -> None:
    result = discount_explicit_cash_flows(
        [10.0, 11.0, 12.0],
        [10.0, 8.0, 6.0],
        [9.0, 9.5, 10.0],
        terminal_growth_pct=10.0,
        terminal_discount_rate_pct=10.5,
        as_of=date(2026, 4, 5),
    )

    assert result.projected_cash_flows[0].forecast_date == "2027-04-05"
    assert result.projected_cash_flows[-1].forecast_date == "2029-04-05"
    assert result.terminal_growth_pct == 9.5
    assert result.intrinsic_value > sum(row.present_value for row in result.projected_cash_flows)
