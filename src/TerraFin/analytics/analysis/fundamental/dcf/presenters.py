from datetime import date
from typing import Any

from .engine import build_linear_growth_rates, clamp_terminal_growth, discount_explicit_cash_flows, project_cash_flows
from .inputs import build_sp500_template, build_stock_template, load_sp500_defaults
from .models import SCENARIO_DEFINITIONS, DCFInputTemplate, DiscountedCashFlowResult, ScenarioDefinition


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _upside_pct(intrinsic_value: float | None, current_price: float | None) -> float | None:
    if intrinsic_value is None or current_price is None or current_price == 0:
        return None
    return round(((float(intrinsic_value) / float(current_price)) - 1.0) * 100.0, 2)


def _average_or_none(left: float | None, right: float | None, digits: int = 2) -> float | None:
    if left is None or right is None:
        return None
    return round((float(left) + float(right)) / 2.0, digits)


def _is_year_end_target(template: DCFInputTemplate) -> bool:
    return template.assumptions.get("valuationHorizon") == "year_end_target"


def _year_end_periods_and_dates(as_of: date, periods: int) -> tuple[list[float], list[str]]:
    if periods <= 0:
        return [], []
    first_year_end = date(as_of.year, 12, 31)
    stub_days = max((first_year_end - as_of).days, 0)
    first_period_years = float(stub_days / 365.25)
    period_years = [first_period_years] + [1.0] * max(periods - 1, 0)
    forecast_dates = [date(as_of.year + idx, 12, 31).isoformat() for idx in range(periods)]
    return period_years, forecast_dates


def _headline_intrinsic_value(template: DCFInputTemplate, result: DiscountedCashFlowResult) -> float:
    if _is_year_end_target(template) and result.projected_cash_flows:
        return round(result.intrinsic_value * result.projected_cash_flows[0].discount_factor, 2)
    return round(result.intrinsic_value, 2)


def _has_explicit_index_schedule(template: DCFInputTemplate) -> bool:
    return bool(template.assumptions.get("yearlyAssumptions")) and template.entity_type == "index"


def _scenario_result_for_index_schedule(
    template: DCFInputTemplate,
    scenario: ScenarioDefinition,
) -> DiscountedCashFlowResult:
    yearly_assumptions = list(template.assumptions.get("yearlyAssumptions", []))
    if not yearly_assumptions:
        raise ValueError("Index schedule assumptions are unavailable")

    base_year_eps = template.assumptions.get("baseYearEps")
    if not isinstance(base_year_eps, (int, float)) or base_year_eps <= 0:
        raise ValueError("Base-year EPS is unavailable")

    methodology = str(template.assumptions.get("valuationMethod", "shareholder_yield"))
    period_year_fractions = None
    forecast_dates = None
    if _is_year_end_target(template):
        period_year_fractions, forecast_dates = _year_end_periods_and_dates(template.as_of, len(yearly_assumptions))

    eps = float(base_year_eps)
    final_eps = eps
    growth_rates_pct: list[float] = []
    cash_flows: list[float] = []
    discount_rates_pct: list[float] = []
    discount_shift_pct = scenario.discount_shift_bps / 100.0

    for index, row in enumerate(yearly_assumptions):
        growth_pct = float(row["growthPct"]) + scenario.growth_shift_pct
        payout_ratio_pct = float(row.get("payoutRatioPct", 0.0))
        buyback_ratio_pct = float(row.get("buybackRatioPct", 0.0))
        equity_risk_premium_pct = float(row["equityRiskPremiumPct"])
        eps = eps * (1.0 + (growth_pct / 100.0))
        final_eps = eps
        cash_flow = eps if methodology == "earnings_power" else eps * ((payout_ratio_pct + buyback_ratio_pct) / 100.0)
        growth_rates_pct.append(growth_pct)
        cash_flows.append(cash_flow)
        discount_rates_pct.append(
            float(template.yearly_risk_free_rates_pct[index]) + equity_risk_premium_pct + discount_shift_pct
        )

    terminal_growth_pct = template.terminal_growth_pct + (scenario.terminal_growth_shift_bps / 100.0)
    terminal_equity_risk_premium_pct = float(
        template.assumptions.get("terminalEquityRiskPremiumPct", template.discount_spread_pct)
    )
    terminal_discount_rate_pct = template.terminal_risk_free_rate_pct + terminal_equity_risk_premium_pct + discount_shift_pct
    discounted_result = discount_explicit_cash_flows(
        cash_flows,
        growth_rates_pct,
        discount_rates_pct,
        terminal_growth_pct=terminal_growth_pct,
        terminal_discount_rate_pct=terminal_discount_rate_pct,
        as_of=template.as_of,
        period_year_fractions=period_year_fractions,
        forecast_dates=forecast_dates,
    )

    safe_terminal_growth_pct = clamp_terminal_growth(terminal_growth_pct, terminal_discount_rate_pct)
    if methodology == "shareholder_yield" and isinstance(template.assumptions.get("terminalRoePct"), (int, float)):
        terminal_roe_pct = float(template.assumptions["terminalRoePct"])
        terminal_eps = final_eps * (1.0 + (safe_terminal_growth_pct / 100.0))
        shareholder_return_ratio = 1.0 - (safe_terminal_growth_pct / terminal_roe_pct)
        terminal_cash_flow_per_share = terminal_eps * shareholder_return_ratio
    else:
        terminal_cash_flow_per_share = float(cash_flows[-1]) * (1.0 + (safe_terminal_growth_pct / 100.0))

    denominator = (float(terminal_discount_rate_pct) - safe_terminal_growth_pct) / 100.0
    if denominator <= 0:
        raise ValueError("Terminal discount rate must exceed terminal growth rate by at least 100bps")
    terminal_value = terminal_cash_flow_per_share / denominator
    intrinsic_value = sum(row.present_value for row in discounted_result.projected_cash_flows) + (
        terminal_value / discounted_result.projected_cash_flows[-1].discount_factor
    )

    return DiscountedCashFlowResult(
        projected_cash_flows=discounted_result.projected_cash_flows,
        terminal_cash_flow_per_share=float(terminal_cash_flow_per_share),
        terminal_growth_pct=float(safe_terminal_growth_pct),
        terminal_discount_rate_pct=float(terminal_discount_rate_pct),
        terminal_value=float(terminal_value),
        intrinsic_value=float(intrinsic_value),
    )


def _scenario_result(template: DCFInputTemplate, scenario: ScenarioDefinition) -> DiscountedCashFlowResult:
    if template.base_cash_flow_per_share is None or template.base_growth_pct is None:
        raise ValueError("Template does not have enough data for valuation")
    if _has_explicit_index_schedule(template):
        return _scenario_result_for_index_schedule(template, scenario)

    terminal_growth_pct = template.terminal_growth_pct + (scenario.terminal_growth_shift_bps / 100.0)
    growth_rates_pct = build_linear_growth_rates(
        template.base_growth_pct + scenario.growth_shift_pct,
        terminal_growth_pct,
        len(template.yearly_risk_free_rates_pct),
    )
    cash_flows = project_cash_flows(template.base_cash_flow_per_share, growth_rates_pct)
    discount_shift_pct = scenario.discount_shift_bps / 100.0
    discount_rates_pct = [
        risk_free_rate_pct + template.discount_spread_pct + discount_shift_pct
        for risk_free_rate_pct in template.yearly_risk_free_rates_pct
    ]
    terminal_discount_rate_pct = (
        template.terminal_risk_free_rate_pct + template.discount_spread_pct + discount_shift_pct
    )
    period_year_fractions = None
    forecast_dates = None
    if _is_year_end_target(template):
        period_year_fractions, forecast_dates = _year_end_periods_and_dates(
            template.as_of,
            len(template.yearly_risk_free_rates_pct),
        )
    return discount_explicit_cash_flows(
        cash_flows,
        growth_rates_pct,
        discount_rates_pct,
        terminal_growth_pct=terminal_growth_pct,
        terminal_discount_rate_pct=terminal_discount_rate_pct,
        as_of=template.as_of,
        period_year_fractions=period_year_fractions,
        forecast_dates=forecast_dates,
    )


def _scenario_payload(
    template: DCFInputTemplate,
    scenario: ScenarioDefinition,
    result: DiscountedCashFlowResult,
) -> dict[str, Any]:
    return {
        "key": scenario.key,
        "label": scenario.label,
        "status": template.status,
        "growthShiftPct": scenario.growth_shift_pct,
        "discountRateShiftBps": scenario.discount_shift_bps,
        "terminalGrowthShiftBps": scenario.terminal_growth_shift_bps,
        "intrinsicValue": _headline_intrinsic_value(template, result),
        "upsidePct": _upside_pct(_headline_intrinsic_value(template, result), template.current_price),
        "terminalValue": round(result.terminal_value, 2),
        "terminalGrowthPct": round(result.terminal_growth_pct, 2),
        "terminalDiscountRatePct": round(result.terminal_discount_rate_pct, 2),
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


def _rate_curve_payload(template: DCFInputTemplate) -> dict[str, Any]:
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


def _sensitivity_payload(template: DCFInputTemplate) -> dict[str, Any]:
    if template.status != "ready":
        return {
            "discountRateShiftBps": [],
            "terminalGrowthShiftBps": [],
            "cells": [],
        }

    defaults = load_sp500_defaults()
    discount_shifts = list(defaults["sensitivity_discount_rate_shifts_bps"])
    terminal_growth_shifts = list(defaults["sensitivity_terminal_growth_shifts_bps"])
    cells: list[dict[str, Any]] = []

    for terminal_growth_shift in terminal_growth_shifts:
        for discount_shift in discount_shifts:
            sensitivity_scenario = ScenarioDefinition(
                key="sensitivity",
                label="Sensitivity",
                growth_shift_pct=0.0,
                discount_shift_bps=int(discount_shift),
                terminal_growth_shift_bps=int(terminal_growth_shift),
            )
            result = _scenario_result(template, sensitivity_scenario)
            cells.append(
                {
                    "terminalGrowthShiftBps": int(terminal_growth_shift),
                    "discountRateShiftBps": int(discount_shift),
                    "intrinsicValue": round(result.intrinsic_value, 2),
                    "upsidePct": _upside_pct(result.intrinsic_value, template.current_price),
                }
            )

    return {
        "discountRateShiftBps": discount_shifts,
        "terminalGrowthShiftBps": terminal_growth_shifts,
        "cells": cells,
    }


def build_valuation_payload(template: DCFInputTemplate) -> dict[str, Any]:
    payload = {
        "status": template.status,
        "entityType": template.entity_type,
        "symbol": template.symbol,
        "asOf": template.as_of.isoformat(),
        "currentPrice": _round_or_none(template.current_price, 2),
        "currentIntrinsicValue": None,
        "upsidePct": None,
        "scenarios": {},
        "assumptions": {
            **template.assumptions,
            "projectionYears": len(template.yearly_risk_free_rates_pct),
            "terminalGrowthPct": round(template.terminal_growth_pct, 2),
            "terminalRiskFreeRatePct": round(template.terminal_risk_free_rate_pct, 3),
        },
        "sensitivity": _sensitivity_payload(template),
        "rateCurve": _rate_curve_payload(template),
        "dataQuality": template.data_quality,
        "warnings": list(template.warnings),
    }
    if template.status != "ready":
        return payload

    scenario_payloads: dict[str, Any] = {}
    base_result: DiscountedCashFlowResult | None = None
    for scenario in SCENARIO_DEFINITIONS:
        result = _scenario_result(template, scenario)
        scenario_payloads[scenario.key] = _scenario_payload(template, scenario, result)
        if scenario.key == "base":
            base_result = result

    payload["scenarios"] = scenario_payloads
    if base_result is not None:
        payload["currentIntrinsicValue"] = _headline_intrinsic_value(template, base_result)
        payload["assumptions"]["presentValueToday"] = round(base_result.intrinsic_value, 2)
        if _is_year_end_target(template) and base_result.projected_cash_flows:
            payload["assumptions"]["yearEndDiscountFactor"] = round(base_result.projected_cash_flows[0].discount_factor, 4)
    payload["upsidePct"] = _upside_pct(payload["currentIntrinsicValue"], template.current_price)
    return payload


def build_sp500_dcf_payload(overrides=None) -> dict[str, Any]:
    shareholder_payload = build_valuation_payload(
        build_sp500_template(methodology="shareholder_yield", overrides=overrides)
    )
    earnings_power_payload = build_valuation_payload(
        build_sp500_template(methodology="earnings_power", overrides=overrides)
    )
    return _blend_sp500_payload(shareholder_payload, earnings_power_payload)


def build_stock_dcf_payload(ticker: str, overrides=None) -> dict[str, Any]:
    return build_valuation_payload(build_stock_template(ticker, overrides=overrides))


def _blend_sp500_payload(
    shareholder_payload: dict[str, Any],
    earnings_power_payload: dict[str, Any],
) -> dict[str, Any]:
    current_price = shareholder_payload.get("currentPrice")
    methods = [
        {
            "key": "shareholder_yield",
            "label": "Shareholder Yield",
            "description": "Cash flow = EPS x (dividends + net buybacks).",
            "weight": 0.5,
            "currentIntrinsicValue": shareholder_payload.get("currentIntrinsicValue"),
            "upsidePct": shareholder_payload.get("upsidePct"),
        },
        {
            "key": "earnings_power",
            "label": "Earnings Power",
            "description": "Cash flow = EPS, using index earnings as an owner-earnings proxy.",
            "weight": 0.5,
            "currentIntrinsicValue": earnings_power_payload.get("currentIntrinsicValue"),
            "upsidePct": earnings_power_payload.get("upsidePct"),
        },
    ]
    blended_payload = {
        **shareholder_payload,
        "currentIntrinsicValue": _average_or_none(
            shareholder_payload.get("currentIntrinsicValue"),
            earnings_power_payload.get("currentIntrinsicValue"),
        ),
        "upsidePct": None,
        "scenarios": _blend_scenarios(
            shareholder_payload.get("scenarios", {}),
            earnings_power_payload.get("scenarios", {}),
            current_price,
        ),
        "sensitivity": _blend_sensitivity(
            shareholder_payload.get("sensitivity", {}),
            earnings_power_payload.get("sensitivity", {}),
            current_price,
        ),
        "methods": methods,
        "warnings": _merge_warnings(shareholder_payload.get("warnings", []), earnings_power_payload.get("warnings", [])),
    }
    blended_payload["upsidePct"] = _upside_pct(blended_payload["currentIntrinsicValue"], current_price)
    assumptions = dict(shareholder_payload.get("assumptions", {}))
    assumptions["valuationMethod"] = "blended_two_case_index"
    assumptions["valuationMethodLabel"] = "Blended Two-Case Index DCF"
    assumptions["valuationMethodDescription"] = (
        "TerraFin blends a shareholder-yield case and an earnings-power case 50/50 for the S&P 500 headline value."
    )
    assumptions["blendedCaseWeights"] = {"shareholderYield": 0.5, "earningsPower": 0.5}
    assumptions["shareholderYieldIntrinsicValue"] = shareholder_payload.get("currentIntrinsicValue")
    assumptions["earningsPowerIntrinsicValue"] = earnings_power_payload.get("currentIntrinsicValue")
    assumptions["baseCashFlowPerShare"] = _average_or_none(
        shareholder_payload.get("assumptions", {}).get("baseCashFlowPerShare"),
        earnings_power_payload.get("assumptions", {}).get("baseCashFlowPerShare"),
        digits=4,
    )
    blended_payload["assumptions"] = assumptions
    blended_payload["dataQuality"] = {
        **shareholder_payload.get("dataQuality", {}),
        "valuationMode": "blended_two_case_index",
    }
    return blended_payload


def _blend_scenarios(
    shareholder_scenarios: dict[str, Any],
    earnings_power_scenarios: dict[str, Any],
    current_price: float | None,
) -> dict[str, Any]:
    blended: dict[str, Any] = {}
    for key, shareholder_scenario in shareholder_scenarios.items():
        earnings_power_scenario = earnings_power_scenarios.get(key)
        if earnings_power_scenario is None:
            blended[key] = shareholder_scenario
            continue
        intrinsic_value = _average_or_none(
            shareholder_scenario.get("intrinsicValue"),
            earnings_power_scenario.get("intrinsicValue"),
        )
        blended[key] = {
            **shareholder_scenario,
            "intrinsicValue": intrinsic_value,
            "upsidePct": _upside_pct(intrinsic_value, current_price),
            "terminalValue": _average_or_none(
                shareholder_scenario.get("terminalValue"),
                earnings_power_scenario.get("terminalValue"),
            ),
            "terminalGrowthPct": _average_or_none(
                shareholder_scenario.get("terminalGrowthPct"),
                earnings_power_scenario.get("terminalGrowthPct"),
            ),
            "terminalDiscountRatePct": _average_or_none(
                shareholder_scenario.get("terminalDiscountRatePct"),
                earnings_power_scenario.get("terminalDiscountRatePct"),
            ),
            "projectedCashFlows": _blend_projection_rows(
                shareholder_scenario.get("projectedCashFlows", []),
                earnings_power_scenario.get("projectedCashFlows", []),
            ),
        }
    return blended


def _blend_projection_rows(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(left_rows) != len(right_rows):
        return left_rows
    blended_rows: list[dict[str, Any]] = []
    for left_row, right_row in zip(left_rows, right_rows):
        blended_rows.append(
            {
                **left_row,
                "growthPct": _average_or_none(left_row.get("growthPct"), right_row.get("growthPct")),
                "cashFlowPerShare": _average_or_none(
                    left_row.get("cashFlowPerShare"),
                    right_row.get("cashFlowPerShare"),
                    digits=4,
                ),
                "discountRatePct": _average_or_none(left_row.get("discountRatePct"), right_row.get("discountRatePct")),
                "discountFactor": _average_or_none(left_row.get("discountFactor"), right_row.get("discountFactor"), digits=4),
                "presentValue": _average_or_none(left_row.get("presentValue"), right_row.get("presentValue"), digits=4),
            }
        )
    return blended_rows


def _blend_sensitivity(
    shareholder_sensitivity: dict[str, Any],
    earnings_power_sensitivity: dict[str, Any],
    current_price: float | None,
) -> dict[str, Any]:
    left_cells = {
        (cell["terminalGrowthShiftBps"], cell["discountRateShiftBps"]): cell
        for cell in shareholder_sensitivity.get("cells", [])
    }
    right_cells = {
        (cell["terminalGrowthShiftBps"], cell["discountRateShiftBps"]): cell
        for cell in earnings_power_sensitivity.get("cells", [])
    }
    blended_cells: list[dict[str, Any]] = []
    for key, left_cell in left_cells.items():
        right_cell = right_cells.get(key)
        if right_cell is None:
            blended_cells.append(left_cell)
            continue
        intrinsic_value = _average_or_none(left_cell.get("intrinsicValue"), right_cell.get("intrinsicValue"))
        blended_cells.append(
            {
                "terminalGrowthShiftBps": key[0],
                "discountRateShiftBps": key[1],
                "intrinsicValue": intrinsic_value,
                "upsidePct": _upside_pct(intrinsic_value, current_price),
            }
        )
    return {
        "discountRateShiftBps": shareholder_sensitivity.get("discountRateShiftBps", []),
        "terminalGrowthShiftBps": shareholder_sensitivity.get("terminalGrowthShiftBps", []),
        "cells": blended_cells,
    }


def _merge_warnings(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for warning in [*left, *right]:
        if warning not in merged:
            merged.append(warning)
    return merged
