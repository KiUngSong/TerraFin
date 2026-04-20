import pandas as pd

import TerraFin.analytics.analysis.fundamental.dcf.inputs as inputs_module
from TerraFin.analytics.analysis.fundamental.dcf.inputs import build_sp500_template, build_stock_template
from TerraFin.analytics.analysis.fundamental.dcf.models import (
    RateCurvePoint,
    RateCurveSnapshot,
    SP500DCFOverrides,
    SP500YearAssumption,
    StockDCFOverrides,
)
from TerraFin.analytics.analysis.risk.models import BetaEstimate


class _FakeCurve:
    def yield_at(self, maturity_years: float) -> float:
        return {1: 4.0, 2: 4.1, 3: 4.2, 4: 4.25, 5: 4.3, 30: 4.6}.get(maturity_years, 4.3)


def _curve_snapshot() -> RateCurveSnapshot:
    points = [
        RateCurvePoint(maturity_years=0.25, yield_pct=4.8, label="13W"),
        RateCurvePoint(maturity_years=2.0, yield_pct=4.2, label="2Y"),
        RateCurvePoint(maturity_years=5.0, yield_pct=4.1, label="5Y"),
        RateCurvePoint(maturity_years=10.0, yield_pct=4.3, label="10Y"),
        RateCurvePoint(maturity_years=30.0, yield_pct=4.6, label="30Y"),
    ]
    return RateCurveSnapshot(
        as_of="2026-04-05",
        source="test",
        points=points,
        fitted_points=list(points),
        fallback_yield_pct=4.3,
        curve=_FakeCurve(),
    )


class _PriceFactory:
    def __init__(self, price_map: dict[str, float]) -> None:
        self.price_map = price_map

    def get_market_data(self, symbol: str):
        return pd.DataFrame({"time": ["2026-04-05"], "close": [self.price_map[symbol]]})


def test_build_sp500_template_uses_checked_in_yearly_schedule(monkeypatch) -> None:
    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "load_sp500_defaults",
        lambda: {
            "version": "test",
            "base_year": 2025,
            "base_year_eps": 200.0,
            "terminal_growth_pct": 3.9,
            "terminal_equity_risk_premium_pct": 4.5,
            "terminal_roe_pct": 20.0,
            "yearly_assumptions": [
                {
                    "year_offset": 1,
                    "growth_pct": 12.0,
                    "payout_ratio_pct": 30.0,
                    "buyback_ratio_pct": 40.0,
                    "equity_risk_premium_pct": 5.4,
                },
                {
                    "year_offset": 2,
                    "growth_pct": 10.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 41.0,
                    "equity_risk_premium_pct": 5.2,
                },
                {
                    "year_offset": 3,
                    "growth_pct": 8.0,
                    "payout_ratio_pct": 32.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 5.0,
                },
                {
                    "year_offset": 4,
                    "growth_pct": 7.0,
                    "payout_ratio_pct": 33.0,
                    "buyback_ratio_pct": 43.0,
                    "equity_risk_premium_pct": 4.9,
                },
                {
                    "year_offset": 5,
                    "growth_pct": 6.0,
                    "payout_ratio_pct": 34.0,
                    "buyback_ratio_pct": 44.0,
                    "equity_risk_premium_pct": 4.8,
                },
            ],
            "sensitivity_discount_rate_shifts_bps": [-100, 0, 100],
            "sensitivity_terminal_growth_shifts_bps": [-100, 0, 100],
        },
    )

    template = build_sp500_template(data_factory=_PriceFactory({"^SPX": 5000.0}))

    assert template.status == "ready"
    assert round(template.assumptions["baseYearEps"], 2) == 200.0
    assert round(template.base_growth_pct or 0.0, 2) == 12.0
    assert round(template.base_cash_flow_per_share or 0.0, 2) == 140.0
    assert template.assumptions["yearlyAssumptions"][0]["equityRiskPremiumPct"] == 5.4
    assert template.assumptions["valuationHorizon"] == "year_end_target"


def test_build_sp500_template_supports_overrides_and_earnings_power_methodology(monkeypatch) -> None:
    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "load_sp500_defaults",
        lambda: {
            "version": "test",
            "base_year": 2025,
            "base_year_eps": 180.0,
            "terminal_growth_pct": 3.9,
            "terminal_equity_risk_premium_pct": 4.5,
            "terminal_roe_pct": 20.0,
            "yearly_assumptions": [
                {
                    "year_offset": 1,
                    "growth_pct": 11.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 5.1,
                },
                {
                    "year_offset": 2,
                    "growth_pct": 10.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 5.0,
                },
                {
                    "year_offset": 3,
                    "growth_pct": 9.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 4.9,
                },
                {
                    "year_offset": 4,
                    "growth_pct": 8.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 4.8,
                },
                {
                    "year_offset": 5,
                    "growth_pct": 7.0,
                    "payout_ratio_pct": 31.0,
                    "buyback_ratio_pct": 42.0,
                    "equity_risk_premium_pct": 4.7,
                },
            ],
            "sensitivity_discount_rate_shifts_bps": [-100, 0, 100],
            "sensitivity_terminal_growth_shifts_bps": [-100, 0, 100],
        },
    )

    template = build_sp500_template(
        methodology="earnings_power",
        data_factory=_PriceFactory({"^SPX": 5000.0}),
        overrides=SP500DCFOverrides(
            base_year_eps=210.0,
            terminal_growth_pct=4.1,
            yearly_assumptions=(
                SP500YearAssumption(
                    year_offset=1,
                    growth_pct=14.0,
                    payout_ratio_pct=30.0,
                    buyback_ratio_pct=45.0,
                    equity_risk_premium_pct=5.6,
                ),
                SP500YearAssumption(
                    year_offset=2,
                    growth_pct=12.0,
                    payout_ratio_pct=30.0,
                    buyback_ratio_pct=45.0,
                    equity_risk_premium_pct=5.4,
                ),
                SP500YearAssumption(
                    year_offset=3,
                    growth_pct=10.0,
                    payout_ratio_pct=30.0,
                    buyback_ratio_pct=45.0,
                    equity_risk_premium_pct=5.2,
                ),
                SP500YearAssumption(
                    year_offset=4,
                    growth_pct=8.0,
                    payout_ratio_pct=30.0,
                    buyback_ratio_pct=45.0,
                    equity_risk_premium_pct=5.0,
                ),
                SP500YearAssumption(
                    year_offset=5,
                    growth_pct=6.0,
                    payout_ratio_pct=30.0,
                    buyback_ratio_pct=45.0,
                    equity_risk_premium_pct=4.8,
                ),
            ),
        ),
    )

    assert template.status == "ready"
    assert template.assumptions["valuationMethod"] == "earnings_power"
    assert round(template.base_cash_flow_per_share or 0.0, 2) == 210.0
    assert round(template.terminal_growth_pct, 2) == 4.1


def test_build_stock_template_prefers_3yr_avg_fcf_and_eps_growth(monkeypatch) -> None:
    quarterly_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            "Operating Cash Flow": [300.0, 280.0, 260.0, 240.0],
            "Capital Expenditure": [-80.0, -70.0, -60.0, -50.0],
        }
    )
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [900.0, 850.0, 780.0, 720.0],
            "Capital Expenditure": [-210.0, -190.0, -175.0, -160.0],
        }
    )

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": 1.2,
            "trailingEps": 5.0,
            "forwardEps": 6.0,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": quarterly_cashflow if period == "quarter" else annual_cashflow,
    )

    template = build_stock_template("AAPL", data_factory=_PriceFactory({"AAPL": 150.0}))

    # Default `auto` source picks 3yr_avg when annual data is available.
    # 3yr avg FCF = (690 + 660 + 605) / 3 = 651.67; per share with 100 shares = 6.5167.
    assert template.status == "ready"
    assert template.assumptions["cashflowSource"] == "3yr_avg"
    assert round(template.base_cash_flow_per_share or 0.0, 2) == 6.52
    assert template.assumptions["growthSource"] == "eps"


def test_build_stock_template_honors_fcf_base_source_ttm(monkeypatch) -> None:
    """Explicit fcf_base_source="ttm" still produces the quarterly-TTM base."""
    quarterly_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            "Operating Cash Flow": [300.0, 280.0, 260.0, 240.0],
            "Capital Expenditure": [-80.0, -70.0, -60.0, -50.0],
        }
    )
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [900.0, 850.0, 780.0, 720.0],
            "Capital Expenditure": [-210.0, -190.0, -175.0, -160.0],
        }
    )

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": 1.2,
            "trailingEps": 5.0,
            "forwardEps": 6.0,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": quarterly_cashflow if period == "quarter" else annual_cashflow,
    )

    template = build_stock_template(
        "AAPL",
        data_factory=_PriceFactory({"AAPL": 150.0}),
        overrides=StockDCFOverrides(fcf_base_source="ttm"),
    )

    assert template.status == "ready"
    assert template.assumptions["cashflowSource"] == "quarterly_ttm"
    assert round(template.base_cash_flow_per_share or 0.0, 2) == 8.20


def test_three_year_avg_requires_two_valid_years() -> None:
    from TerraFin.analytics.analysis.fundamental.dcf.inputs import _three_year_avg_fcf

    only_one = pd.DataFrame(
        {
            "date": ["2025-12-31"],
            "Operating Cash Flow": [800.0],
            "Capital Expenditure": [-200.0],
        }
    )
    assert _three_year_avg_fcf(only_one) is None

    two_years = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31"],
            "Operating Cash Flow": [800.0, 700.0],
            "Capital Expenditure": [-200.0, -180.0],
        }
    )
    avg = _three_year_avg_fcf(two_years)
    assert avg is not None
    assert round(avg, 2) == 560.0  # (600 + 520) / 2


def test_build_stock_template_auto_cascade_falls_back_to_ttm(monkeypatch) -> None:
    """If annual data has only 1 valid row (3yr avg + latest annual fail), TTM rescues the cascade."""
    quarterly_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            "Operating Cash Flow": [300.0, 280.0, 260.0, 240.0],
            "Capital Expenditure": [-80.0, -70.0, -60.0, -50.0],
        }
    )
    annual_cashflow = None  # No annual data at all.

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": 1.2,
            "trailingEps": 5.0,
            "forwardEps": 6.0,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": quarterly_cashflow if period == "quarter" else annual_cashflow,
    )

    template = build_stock_template("AAPL", data_factory=_PriceFactory({"AAPL": 150.0}))

    assert template.status == "ready"
    assert template.assumptions["cashflowSource"] == "quarterly_ttm"


def test_build_stock_template_falls_back_to_revenue_cagr_before_fcf_cagr(monkeypatch) -> None:
    quarterly_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            "Operating Cash Flow": [140.0, 135.0, 130.0, 125.0],
            "Capital Expenditure": [-40.0, -38.0, -36.0, -35.0],
        }
    )
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [520.0, 500.0, 470.0, 430.0],
            "Capital Expenditure": [-150.0, -145.0, -140.0, -130.0],
        }
    )
    annual_income = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Total Revenue": [1500.0, 1350.0, 1210.0, 1100.0],
        }
    )

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": 1.1,
            "trailingEps": None,
            "forwardEps": None,
        },
    )

    def _corporate_data(ticker, statement_type, period="annual"):
        if statement_type == "cashflow" and period == "quarter":
            return quarterly_cashflow
        if statement_type == "cashflow" and period == "annual":
            return annual_cashflow
        if statement_type == "income" and period == "annual":
            return annual_income
        return pd.DataFrame()

    monkeypatch.setattr(inputs_module, "get_corporate_data", _corporate_data)

    template = build_stock_template("AAPL", data_factory=_PriceFactory({"AAPL": 150.0}))

    expected_growth = (((1500.0 / 1100.0) ** (1 / 3)) - 1.0) * 100.0
    assert template.status == "ready"
    assert template.assumptions["growthSource"] == "revenue_cagr"
    assert round(template.base_growth_pct or 0.0, 2) == round(expected_growth, 2)
    assert any("annual revenue CAGR" in warning for warning in template.warnings)


def test_build_stock_template_supports_user_overrides(monkeypatch) -> None:
    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": None,
            "trailingEps": None,
            "forwardEps": None,
        },
    )
    monkeypatch.setattr(inputs_module, "get_corporate_data", lambda *args, **kwargs: pd.DataFrame())

    template = build_stock_template(
        "AAPL",
        data_factory=_PriceFactory({"AAPL": 150.0}),
        overrides=StockDCFOverrides(
            base_cash_flow_per_share=7.5,
            base_growth_pct=9.0,
            terminal_growth_pct=3.5,
            beta=1.15,
            equity_risk_premium_pct=4.8,
        ),
    )

    assert template.status == "ready"
    assert template.assumptions["cashflowSource"] == "user_override"
    assert template.assumptions["growthSource"] == "user_override"
    assert round(template.assumptions["discountSpreadPct"], 2) == 5.52
    assert round(template.terminal_growth_pct, 2) == 3.5
    assert template.assumptions["betaSource"] == "user_override"


def test_build_stock_template_uses_computed_beta_when_provider_beta_is_missing(monkeypatch) -> None:
    quarterly_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
            "Operating Cash Flow": [300.0, 280.0, 260.0, 240.0],
            "Capital Expenditure": [-80.0, -70.0, -60.0, -50.0],
        }
    )
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [900.0, 850.0, 780.0, 720.0],
            "Capital Expenditure": [-210.0, -190.0, -175.0, -160.0],
        }
    )

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 150.0,
            "sharesOutstanding": 100.0,
            "beta": None,
            "trailingEps": 5.0,
            "forwardEps": 6.0,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": quarterly_cashflow if period == "quarter" else annual_cashflow,
    )
    monkeypatch.setattr(
        inputs_module,
        "estimate_beta_5y_monthly",
        lambda ticker, data_factory=None: BetaEstimate(
            symbol=ticker,
            benchmark_symbol="^SPX",
            benchmark_label="S&P 500",
            method_id="beta_5y_monthly",
            lookback_years=5,
            frequency="monthly",
            beta=1.37,
            observations=60,
            r_squared=0.72,
            status="ready",
            warnings=[],
        ),
    )

    template = build_stock_template("AAPL", data_factory=_PriceFactory({"AAPL": 150.0}))

    assert template.status == "ready"
    assert template.assumptions["beta"] == 1.37
    assert template.assumptions["betaSource"] == "computed"
    assert template.assumptions["betaMethodId"] == "beta_5y_monthly"
    assert template.assumptions["betaBenchmarkSymbol"] == "^SPX"
    assert round(template.assumptions["discountSpreadPct"], 2) == 6.85
    assert any("using computed beta_5y_monthly" in warning for warning in template.warnings)


def test_build_stock_template_falls_back_to_fcf_cagr_and_marks_insufficient(monkeypatch) -> None:
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [150.0, 120.0, 100.0, 80.0],
            "Capital Expenditure": [-250.0, -220.0, -210.0, -180.0],
        }
    )

    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: {
            "currentPrice": 25.0,
            "sharesOutstanding": 50.0,
            "beta": 1.0,
            "trailingEps": None,
            "forwardEps": None,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": annual_cashflow,
    )

    template = build_stock_template("LOSS", data_factory=_PriceFactory({"LOSS": 25.0}))

    assert template.assumptions["growthSource"] == "default"
    assert template.status == "insufficient_data"
    assert any("not positive" in warning for warning in template.warnings)


def _patch_stock_env(monkeypatch, *, annual_cashflow=None, ticker_info=None) -> None:
    monkeypatch.setattr(inputs_module, "fit_current_treasury_curve", lambda **_: _curve_snapshot())
    monkeypatch.setattr(
        inputs_module,
        "get_ticker_info",
        lambda ticker: ticker_info or {
            "currentPrice": 25.0,
            "sharesOutstanding": 50.0,
            "beta": 1.0,
            "trailingEps": None,
            "forwardEps": None,
        },
    )
    monkeypatch.setattr(
        inputs_module,
        "get_corporate_data",
        lambda ticker, statement_type, period="annual": annual_cashflow
        if annual_cashflow is not None
        else pd.DataFrame(),
    )


def test_build_stock_template_honors_projection_years_10(monkeypatch) -> None:
    _patch_stock_env(monkeypatch)
    template = build_stock_template(
        "AAPL",
        data_factory=_PriceFactory({"AAPL": 25.0}),
        overrides=StockDCFOverrides(base_cash_flow_per_share=2.0, base_growth_pct=5.0),
        projection_years=10,
    )

    assert len(template.yearly_risk_free_rates_pct) == 10
    assert template.status == "ready"


def test_build_stock_template_rejects_invalid_projection_years(monkeypatch) -> None:
    _patch_stock_env(monkeypatch)
    import pytest

    with pytest.raises(ValueError):
        build_stock_template(
            "AAPL",
            data_factory=_PriceFactory({"AAPL": 25.0}),
            overrides=StockDCFOverrides(base_cash_flow_per_share=2.0),
            projection_years=7,
        )


def test_build_stock_template_turnaround_flips_status_to_ready(monkeypatch) -> None:
    # Company with negative TTM FCF — would normally be insufficient_data.
    annual_cashflow = pd.DataFrame(
        {
            "date": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"],
            "Operating Cash Flow": [150.0, 120.0, 100.0, 80.0],
            "Capital Expenditure": [-250.0, -220.0, -210.0, -180.0],
        }
    )
    _patch_stock_env(monkeypatch, annual_cashflow=annual_cashflow)

    template = build_stock_template(
        "LOSS",
        data_factory=_PriceFactory({"LOSS": 25.0}),
        overrides=StockDCFOverrides(
            breakeven_year=3,
            breakeven_cash_flow_per_share=1.5,
            post_breakeven_growth_pct=15.0,
        ),
        projection_years=5,
    )

    assert template.status == "ready"
    assert template.assumptions["turnaround"]["active"] is True
    assert template.assumptions["turnaround"]["breakevenYear"] == 3
    schedule = template.assumptions["turnaround"]["cashFlowsPerShare"]
    assert len(schedule) == 5
    # Starting FCF/share is derived (negative). Year-3 should be the breakeven value.
    assert round(schedule[2], 2) == 1.50
    # After breakeven, schedule must be positive and growing.
    assert schedule[3] > schedule[2] > 0.0
    assert schedule[4] > schedule[3]


def test_turnaround_schedule_linear_interp_pre_breakeven() -> None:
    from TerraFin.analytics.analysis.fundamental.dcf.inputs import _build_turnaround_schedule

    schedule = _build_turnaround_schedule(
        starting_cash_flow_per_share=-1.0,
        breakeven_year=3,
        breakeven_cash_flow_per_share=2.0,
        post_breakeven_growth_pct=10.0,
        terminal_growth_pct=3.0,
        projection_years=5,
    )
    assert len(schedule) == 5
    # Linear interp from -1 to 2 across 3 years: year1=0, year2=1, year3=2.
    assert round(schedule[0], 6) == 0.0
    assert round(schedule[1], 6) == 1.0
    assert round(schedule[2], 6) == 2.0
    # Year 4 and 5 apply the fading growth path.
    assert schedule[3] > schedule[2]
    assert schedule[4] > schedule[3]
