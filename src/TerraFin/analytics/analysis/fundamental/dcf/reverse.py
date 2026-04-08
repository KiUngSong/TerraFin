from typing import Any

from .engine import discount_explicit_cash_flows, project_cash_flows
from .inputs import build_stock_template


GROWTH_PROFILE_DEFINITIONS: dict[str, dict[str, str]] = {
    "high_growth": {
        "label": "High Growth",
        "description": "Growth stays elevated longer before fading toward the terminal rate.",
    },
    "early_maturity": {
        "label": "Early Maturity",
        "description": "Growth fades linearly from the implied starting rate to the terminal rate.",
    },
    "fully_mature": {
        "label": "Fully Mature",
        "description": "Growth converges toward the terminal rate quickly, implying a more mature path.",
    },
}

DEFAULT_REVERSE_DCF_YEARS = 5
DEFAULT_REVERSE_DCF_PROFILE = "early_maturity"
_MIN_SOLVER_GROWTH_PCT = -99.0
_MAX_SOLVER_GROWTH_PCT = 500.0


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _profile_progress(profile_key: str, normalized_progress: float) -> float:
    if profile_key == "high_growth":
        return float(normalized_progress**2)
    if profile_key == "fully_mature":
        return float(normalized_progress**0.5)
    return float(normalized_progress)


def _growth_path(
    *,
    initial_growth_pct: float,
    terminal_growth_pct: float,
    years: int,
    profile_key: str,
) -> list[float]:
    if years <= 0:
        raise ValueError("Projection years must be positive")
    if years == 1:
        return [float(initial_growth_pct)]

    path: list[float] = []
    for index in range(years):
        progress = index / (years - 1)
        eased_progress = _profile_progress(profile_key, progress)
        growth_pct = initial_growth_pct + ((terminal_growth_pct - initial_growth_pct) * eased_progress)
        path.append(float(growth_pct))
    return path


def _rate_curve_payload(template) -> dict[str, Any]:
    return {
        "source": template.rate_curve.source,
        "asOf": template.rate_curve.as_of,
        "fitRmse": _round_or_none(template.rate_curve.fit_rmse, 4),
        "fallbackUsed": template.rate_curve.fallback_used,
        "points": [
            {
                "maturityYears": point.maturity_years,
                "yieldPct": round(point.yield_pct, 3),
                "label": point.label,
            }
            for point in template.rate_curve.points
        ],
        "fittedPoints": [
            {
                "maturityYears": point.maturity_years,
                "yieldPct": round(point.yield_pct, 3),
                "label": point.label,
            }
            for point in template.rate_curve.fitted_points
        ],
    }


def _result_for_initial_growth(template, *, years: int, profile_key: str, initial_growth_pct: float):
    growth_rates_pct = _growth_path(
        initial_growth_pct=initial_growth_pct,
        terminal_growth_pct=template.terminal_growth_pct,
        years=years,
        profile_key=profile_key,
    )
    cash_flows = project_cash_flows(template.base_cash_flow_per_share, growth_rates_pct)
    discount_rates_pct = [
        float(template.rate_curve.yield_at(year_offset) + template.discount_spread_pct)
        for year_offset in range(1, years + 1)
    ]
    terminal_discount_rate_pct = float(template.terminal_risk_free_rate_pct + template.discount_spread_pct)
    return discount_explicit_cash_flows(
        cash_flows,
        growth_rates_pct,
        discount_rates_pct,
        terminal_growth_pct=template.terminal_growth_pct,
        terminal_discount_rate_pct=terminal_discount_rate_pct,
        as_of=template.as_of,
    )


def _solve_implied_growth(template, *, years: int, profile_key: str) -> tuple[float, Any]:
    if template.current_price is None or template.current_price <= 0:
        raise ValueError("Current price must be positive for reverse DCF.")
    if template.base_cash_flow_per_share is None or template.base_cash_flow_per_share <= 0:
        raise ValueError("Base cash flow per share must be positive for reverse DCF.")

    target_price = float(template.current_price)
    lower_growth = _MIN_SOLVER_GROWTH_PCT
    upper_growth = 15.0

    lower_result = _result_for_initial_growth(
        template,
        years=years,
        profile_key=profile_key,
        initial_growth_pct=lower_growth,
    )
    if lower_result.intrinsic_value > target_price:
        raise ValueError("Current price is below the model floor even with near-zero growth.")

    upper_result = _result_for_initial_growth(
        template,
        years=years,
        profile_key=profile_key,
        initial_growth_pct=upper_growth,
    )
    while upper_result.intrinsic_value < target_price and upper_growth < _MAX_SOLVER_GROWTH_PCT:
        upper_growth = 40.0 if upper_growth < 20.0 else upper_growth * 1.5
        upper_result = _result_for_initial_growth(
            template,
            years=years,
            profile_key=profile_key,
            initial_growth_pct=upper_growth,
        )

    if upper_result.intrinsic_value < target_price:
        raise ValueError("Current price implies growth above the supported solver range.")

    solved_growth = upper_growth
    solved_result = upper_result
    for _ in range(80):
        mid_growth = (lower_growth + upper_growth) / 2.0
        mid_result = _result_for_initial_growth(
            template,
            years=years,
            profile_key=profile_key,
            initial_growth_pct=mid_growth,
        )
        solved_growth = mid_growth
        solved_result = mid_result
        price_gap = mid_result.intrinsic_value - target_price
        if abs(price_gap) <= max(0.01, target_price * 0.00001):
            break
        if price_gap < 0:
            lower_growth = mid_growth
        else:
            upper_growth = mid_growth

    return float(solved_growth), solved_result


def build_stock_reverse_dcf_payload(
    ticker: str,
    *,
    overrides=None,
    projection_years: int = DEFAULT_REVERSE_DCF_YEARS,
    growth_profile: str = DEFAULT_REVERSE_DCF_PROFILE,
) -> dict[str, Any]:
    normalized_profile = growth_profile if growth_profile in GROWTH_PROFILE_DEFINITIONS else DEFAULT_REVERSE_DCF_PROFILE
    years = int(projection_years or DEFAULT_REVERSE_DCF_YEARS)
    if years <= 0:
        raise ValueError("Projection years must be positive.")

    template = build_stock_template(ticker, overrides=overrides)
    warnings = list(template.warnings)
    profile_meta = GROWTH_PROFILE_DEFINITIONS[normalized_profile]
    payload = {
        "status": template.status,
        "entityType": template.entity_type,
        "symbol": template.symbol,
        "asOf": template.as_of.isoformat(),
        "currentPrice": _round_or_none(template.current_price, 2),
        "baseCashFlowPerShare": _round_or_none(template.base_cash_flow_per_share, 4),
        "impliedGrowthPct": None,
        "modelPrice": None,
        "projectionYears": years,
        "growthProfile": {
            "key": normalized_profile,
            "label": profile_meta["label"],
            "description": profile_meta["description"],
        },
        "priceToCashFlowMultiple": None,
        "terminalGrowthPct": _round_or_none(template.terminal_growth_pct, 2),
        "terminalDiscountRatePct": _round_or_none(template.terminal_risk_free_rate_pct + template.discount_spread_pct, 2),
        "terminalValue": None,
        "terminalPresentValueWeightPct": None,
        "discountSpreadPct": _round_or_none(template.discount_spread_pct, 2),
        "assumptions": {
            **template.assumptions,
            "cashFlowBasis": "gaap_fcf",
            "projectionYears": years,
            "growthProfile": normalized_profile,
            "growthProfileLabel": profile_meta["label"],
            "growthProfileDescription": profile_meta["description"],
        },
        "projectedCashFlows": [],
        "rateCurve": _rate_curve_payload(template),
        "dataQuality": {
            **template.data_quality,
            "valuationMode": "reverse_dcf",
        },
        "warnings": warnings,
    }

    if template.current_price and template.base_cash_flow_per_share:
        payload["priceToCashFlowMultiple"] = _round_or_none(
            template.current_price / template.base_cash_flow_per_share,
            2,
        )

    if template.status != "ready":
        return payload

    try:
        implied_growth_pct, result = _solve_implied_growth(
            template,
            years=years,
            profile_key=normalized_profile,
        )
    except ValueError as exc:
        payload["status"] = "insufficient_data"
        payload["warnings"] = [*warnings, str(exc)]
        return payload

    terminal_present_value = (
        result.terminal_value / result.projected_cash_flows[-1].discount_factor
        if result.projected_cash_flows
        else None
    )
    terminal_weight_pct = (
        (terminal_present_value / template.current_price) * 100.0
        if terminal_present_value is not None and template.current_price
        else None
    )

    payload.update(
        {
            "impliedGrowthPct": round(implied_growth_pct, 2),
            "modelPrice": round(result.intrinsic_value, 2),
            "terminalGrowthPct": round(result.terminal_growth_pct, 2),
            "terminalDiscountRatePct": round(result.terminal_discount_rate_pct, 2),
            "terminalValue": round(result.terminal_value, 2),
            "terminalPresentValueWeightPct": _round_or_none(terminal_weight_pct, 2),
            "projectedCashFlows": [
                {
                    "yearOffset": row.year_offset,
                    "forecastDate": row.forecast_date,
                    "growthPct": round(row.growth_pct, 2),
                    "cashFlowPerShare": round(row.cash_flow_per_share, 4),
                    "discountRatePct": round(row.discount_rate_pct, 2),
                    "discountFactor": round(row.discount_factor, 4),
                    "presentValue": round(row.present_value, 4),
                }
                for row in result.projected_cash_flows
            ],
        }
    )
    return payload
