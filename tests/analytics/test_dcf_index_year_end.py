from datetime import date

from TerraFin.analytics.analysis.fundamental.dcf.engine import discount_explicit_cash_flows


def test_discount_explicit_cash_flows_supports_stub_periods() -> None:
    result = discount_explicit_cash_flows(
        [110.0, 120.0],
        [10.0, 9.0],
        [10.0, 10.0],
        terminal_growth_pct=3.0,
        terminal_discount_rate_pct=9.0,
        as_of=date(2026, 4, 6),
        period_year_fractions=[0.736, 1.0],
        forecast_dates=["2026-12-31", "2027-12-31"],
    )

    assert result.projected_cash_flows[0].forecast_date == "2026-12-31"
    assert round(result.projected_cash_flows[0].discount_factor, 4) == round((1.1) ** 0.736, 4)
