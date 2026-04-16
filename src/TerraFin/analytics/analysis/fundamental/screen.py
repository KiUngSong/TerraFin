"""Fundamental quality and moat screening from financial statement data.

General-purpose capability: any guru agent can call it and interpret the
results through their own investment philosophy.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class FundamentalScreenResult:
    ticker: str
    moat: dict[str, Any]
    earnings_quality: dict[str, Any]
    balance_sheet: dict[str, Any]
    capital_allocation: dict[str, Any]
    pricing_power: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _safe_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_row(df: pd.DataFrame, label: str) -> list[float | None]:
    """Pull a row from a pivoted financial statement DataFrame.

    The DataFrame has a 'date' column and metric rows as other columns,
    *or* a label-indexed structure. We try both layouts.
    """
    if df is None or df.empty:
        return []

    if "date" in df.columns:
        if label in df.columns:
            return [_safe_float(v) for v in df[label].tolist()]
        for col in df.columns:
            if col == "date":
                continue
            if str(col).lower().replace(" ", "") == label.lower().replace(" ", ""):
                return [_safe_float(v) for v in df[col].tolist()]
        return []

    for idx in df.index:
        if str(idx).lower().replace(" ", "") == label.lower().replace(" ", ""):
            return [_safe_float(v) for v in df.loc[idx].tolist()]
    return []


def _non_none(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def _cagr(values: list[float], years: int | None = None) -> float | None:
    clean = [v for v in values if v > 0]
    if len(clean) < 2:
        return None
    n = years if years is not None else len(clean) - 1
    if n <= 0:
        return None
    return ((clean[-1] / clean[0]) ** (1.0 / n)) - 1.0


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / abs(mean)


def _positive_streak(values: list[float | None]) -> int:
    """Count consecutive positive values from the most recent period."""
    streak = 0
    for v in reversed(values):
        if v is not None and v > 0:
            streak += 1
        else:
            break
    return streak


def _compute_moat(
    income: pd.DataFrame,
    balance: pd.DataFrame,
) -> dict[str, Any]:
    net_income = _non_none(_extract_row(income, "Net Income"))
    total_equity = _non_none(_extract_row(balance, "Total Stockholders Equity"))
    revenue = _non_none(_extract_row(income, "Total Revenue"))
    total_assets = _non_none(_extract_row(balance, "Total Assets"))
    operating_income = _non_none(_extract_row(income, "Operating Income"))
    gross_profit = _non_none(_extract_row(income, "Gross Profit"))

    roe_values: list[float] = []
    for ni, eq in zip(net_income, total_equity):
        if eq and eq != 0:
            roe_values.append(ni / eq)

    roe_above_15_pct = (
        round(sum(1 for r in roe_values if r > 0.15) / len(roe_values) * 100, 1)
        if roe_values
        else None
    )

    op_margins = [oi / rev for oi, rev in zip(operating_income, revenue) if rev and rev != 0]
    gross_margins = [gp / rev for gp, rev in zip(gross_profit, revenue) if rev and rev != 0]

    asset_turnover = (
        [rev / ta for rev, ta in zip(revenue, total_assets) if ta and ta != 0]
    )

    return {
        "roe_values": [round(r * 100, 2) for r in roe_values],
        "roe_above_15_pct": roe_above_15_pct,
        "operating_margin_values": [round(m * 100, 2) for m in op_margins],
        "operating_margin_cv": _coefficient_of_variation(op_margins),
        "gross_margin_values": [round(m * 100, 2) for m in gross_margins],
        "gross_margin_trend": (
            "expanding" if len(gross_margins) >= 2 and gross_margins[-1] > gross_margins[0]
            else "contracting" if len(gross_margins) >= 2 and gross_margins[-1] < gross_margins[0]
            else "stable" if len(gross_margins) >= 2
            else "insufficient_data"
        ),
        "asset_turnover_latest": round(asset_turnover[-1], 3) if asset_turnover else None,
    }


def _compute_earnings_quality(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> dict[str, Any]:
    net_income = _extract_row(income, "Net Income")
    net_income_clean = _non_none(net_income)
    depreciation = _non_none(_extract_row(cashflow, "Depreciation"))
    capex = _non_none(_extract_row(cashflow, "Capital Expenditure"))

    owner_earnings: list[float] = []
    length = min(len(net_income_clean), len(depreciation), len(capex))
    for i in range(length):
        ni = net_income_clean[i]
        da = depreciation[i]
        cx = abs(capex[i])
        maintenance_capex = cx * 0.5
        owner_earnings.append(ni + da - maintenance_capex)

    return {
        "earnings_growth_cagr": _cagr(net_income_clean),
        "positive_eps_streak": _positive_streak(net_income),
        "periods_available": len(net_income_clean),
        "owner_earnings": [round(oe, 2) for oe in owner_earnings],
        "owner_earnings_latest": round(owner_earnings[-1], 2) if owner_earnings else None,
    }


def _compute_balance_sheet(balance: pd.DataFrame) -> dict[str, Any]:
    current_assets = _non_none(_extract_row(balance, "Total Current Assets"))
    current_liabilities = _non_none(_extract_row(balance, "Total Current Liabilities"))
    total_debt = _non_none(_extract_row(balance, "Total Debt"))
    total_equity = _non_none(_extract_row(balance, "Total Stockholders Equity"))
    cash = _non_none(_extract_row(balance, "Cash And Cash Equivalents"))

    current_ratio = (
        round(current_assets[-1] / current_liabilities[-1], 2)
        if current_assets and current_liabilities and current_liabilities[-1] != 0
        else None
    )
    debt_to_equity = (
        round(total_debt[-1] / total_equity[-1], 2)
        if total_debt and total_equity and total_equity[-1] != 0
        else None
    )
    net_cash = (
        round(cash[-1] - total_debt[-1], 2) if cash and total_debt else None
    )

    return {
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "net_cash_position": net_cash,
        "has_net_cash": net_cash > 0 if net_cash is not None else None,
    }


def _compute_capital_allocation(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
    balance: pd.DataFrame,
) -> dict[str, Any]:
    buyback = _non_none(_extract_row(cashflow, "Repurchase Of Capital Stock"))
    issuance = _non_none(_extract_row(cashflow, "Issuance Of Capital Stock"))
    dividends = _non_none(_extract_row(cashflow, "Cash Dividends Paid"))
    rnd = _non_none(_extract_row(income, "Research Development"))
    revenue = _non_none(_extract_row(income, "Total Revenue"))

    net_buyback = sum(buyback) if buyback else 0
    net_issuance = sum(issuance) if issuance else 0

    rnd_intensity = (
        round(rnd[-1] / revenue[-1] * 100, 2)
        if rnd and revenue and revenue[-1] != 0
        else None
    )

    return {
        "net_buyback_signal": (
            "buyback" if net_buyback < net_issuance else "dilution"
        ) if buyback or issuance else "unknown",
        "dividend_periods": len(dividends),
        "dividend_consistent": len(dividends) >= 3 and all(d != 0 for d in dividends),
        "rnd_intensity_pct": rnd_intensity,
    }


def _compute_pricing_power(income: pd.DataFrame) -> dict[str, Any]:
    gross_profit = _non_none(_extract_row(income, "Gross Profit"))
    revenue = _non_none(_extract_row(income, "Total Revenue"))
    margins = [gp / rev for gp, rev in zip(gross_profit, revenue) if rev and rev != 0]

    if len(margins) < 3:
        return {"status": "insufficient_data", "margin_delta_pct": None}

    recent_avg = sum(margins[-2:]) / 2
    older_avg = sum(margins[:2]) / 2
    delta = recent_avg - older_avg

    return {
        "status": "expanding" if delta > 0.005 else "contracting" if delta < -0.005 else "stable",
        "margin_delta_pct": round(delta * 100, 2),
        "recent_margin_pct": round(recent_avg * 100, 2),
        "older_margin_pct": round(older_avg * 100, 2),
    }


def run_fundamental_screen(
    ticker: str,
    *,
    income: pd.DataFrame | None = None,
    balance: pd.DataFrame | None = None,
    cashflow: pd.DataFrame | None = None,
) -> FundamentalScreenResult:
    """Compute fundamental quality and moat metrics from financial statements."""
    warnings: list[str] = []
    empty = pd.DataFrame()

    if income is None or income.empty:
        income = empty
        warnings.append("Income statement data unavailable.")
    if balance is None or balance.empty:
        balance = empty
        warnings.append("Balance sheet data unavailable.")
    if cashflow is None or cashflow.empty:
        cashflow = empty
        warnings.append("Cash flow statement data unavailable.")

    return FundamentalScreenResult(
        ticker=ticker,
        moat=_compute_moat(income, balance),
        earnings_quality=_compute_earnings_quality(income, cashflow),
        balance_sheet=_compute_balance_sheet(balance),
        capital_allocation=_compute_capital_allocation(income, cashflow, balance),
        pricing_power=_compute_pricing_power(income),
        warnings=warnings,
    )
