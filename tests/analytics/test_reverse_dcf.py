from datetime import date

import TerraFin.analytics.analysis.fundamental.dcf.reverse as reverse_module
from TerraFin.analytics.analysis.fundamental.dcf.models import DCFInputTemplate, RateCurvePoint, RateCurveSnapshot
from TerraFin.analytics.analysis.fundamental.dcf.reverse import build_stock_reverse_dcf_payload


class _FakeCurve:
    def yield_at(self, maturity_years: float) -> float:
        if maturity_years >= 30:
            return 4.6
        return 4.0 + (0.08 * float(maturity_years))


def _curve_snapshot() -> RateCurveSnapshot:
    points = [
        RateCurvePoint(maturity_years=0.25, yield_pct=4.8, label="13W"),
        RateCurvePoint(maturity_years=2.0, yield_pct=4.2, label="2Y"),
        RateCurvePoint(maturity_years=5.0, yield_pct=4.4, label="5Y"),
        RateCurvePoint(maturity_years=10.0, yield_pct=4.8, label="10Y"),
        RateCurvePoint(maturity_years=30.0, yield_pct=4.6, label="30Y"),
    ]
    return RateCurveSnapshot(
        as_of="2026-04-05",
        source="test",
        points=points,
        fitted_points=list(points),
        fallback_yield_pct=4.4,
        curve=_FakeCurve(),
    )


def _stock_template() -> DCFInputTemplate:
    return DCFInputTemplate(
        status="ready",
        entity_type="stock",
        symbol="AAPL",
        as_of=date(2026, 4, 5),
        current_price=None,
        base_cash_flow_per_share=8.0,
        base_growth_pct=10.0,
        terminal_growth_pct=3.0,
        yearly_risk_free_rates_pct=[4.08, 4.16, 4.24, 4.32, 4.40],
        terminal_risk_free_rate_pct=4.6,
        discount_spread_pct=6.0,
        rate_curve=_curve_snapshot(),
        assumptions={
            "beta": 1.2,
            "equityRiskPremiumPct": 5.0,
            "cashflowSource": "3yr_avg",
            "growthSource": "eps",
        },
        data_quality={"mode": "live", "sources": ["test"]},
        warnings=[],
    )


def test_reverse_dcf_solves_for_market_implied_growth(monkeypatch) -> None:
    template = _stock_template()
    expected_growth_pct = 12.75
    expected_result = reverse_module._result_for_initial_growth(
        template,
        years=10,
        profile_key="early_maturity",
        initial_growth_pct=expected_growth_pct,
    )
    template.current_price = expected_result.intrinsic_value

    monkeypatch.setattr(reverse_module, "build_stock_template", lambda ticker, overrides=None: template)

    payload = build_stock_reverse_dcf_payload("AAPL", projection_years=10, growth_profile="early_maturity")

    assert payload["status"] == "ready"
    assert abs(payload["impliedGrowthPct"] - expected_growth_pct) < 0.05
    assert abs(payload["modelPrice"] - template.current_price) < 0.05
    assert payload["projectionYears"] == 10
    assert payload["growthProfile"]["key"] == "early_maturity"
    assert len(payload["projectedCashFlows"]) == 10


def test_reverse_dcf_returns_insufficient_data_when_template_is_not_ready(monkeypatch) -> None:
    template = _stock_template()
    template.status = "insufficient_data"
    template.current_price = None
    template.warnings = ["Current price unavailable."]

    monkeypatch.setattr(reverse_module, "build_stock_template", lambda ticker, overrides=None: template)

    payload = build_stock_reverse_dcf_payload("AAPL")

    assert payload["status"] == "insufficient_data"
    assert payload["impliedGrowthPct"] is None
    assert payload["projectedCashFlows"] == []
    assert payload["warnings"] == ["Current price unavailable."]


def test_reverse_dcf_marks_payload_insufficient_when_price_is_below_model_floor(monkeypatch) -> None:
    template = _stock_template()
    floor_result = reverse_module._result_for_initial_growth(
        template,
        years=5,
        profile_key="fully_mature",
        initial_growth_pct=-99.0,
    )
    template.current_price = floor_result.intrinsic_value / 2.0

    monkeypatch.setattr(reverse_module, "build_stock_template", lambda ticker, overrides=None: template)

    payload = build_stock_reverse_dcf_payload("AAPL", projection_years=5, growth_profile="fully_mature")

    assert payload["status"] == "insufficient_data"
    assert payload["impliedGrowthPct"] is None
    assert any("model floor" in warning for warning in payload["warnings"])


def test_reverse_dcf_preserves_computed_beta_assumptions_from_stock_template(monkeypatch) -> None:
    template = _stock_template()
    expected_growth_pct = 11.5
    expected_result = reverse_module._result_for_initial_growth(
        template,
        years=5,
        profile_key="early_maturity",
        initial_growth_pct=expected_growth_pct,
    )
    template.current_price = expected_result.intrinsic_value
    template.assumptions = {
        **template.assumptions,
        "beta": 1.37,
        "betaSource": "computed",
        "betaMethodId": "beta_5y_monthly",
        "betaBenchmarkSymbol": "^SPX",
    }
    template.warnings = [
        "Ticker beta was unavailable from provider metadata; using computed beta_5y_monthly vs ^SPX."
    ]

    monkeypatch.setattr(reverse_module, "build_stock_template", lambda ticker, overrides=None: template)

    payload = build_stock_reverse_dcf_payload("AAPL", projection_years=5, growth_profile="early_maturity")

    assert payload["status"] == "ready"
    assert payload["assumptions"]["betaSource"] == "computed"
    assert payload["assumptions"]["betaMethodId"] == "beta_5y_monthly"
    assert payload["assumptions"]["betaBenchmarkSymbol"] == "^SPX"
    assert any("using computed beta_5y_monthly" in warning for warning in payload["warnings"])
