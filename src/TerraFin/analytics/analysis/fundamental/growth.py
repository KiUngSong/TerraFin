"""Revenue and EPS growth series from income-statement payloads.

Takes the dicts `TerraFinAgentService.financials` returns (date-string columns,
label/values rows) and lists every value and year-over-year change the
statement carries, oldest first. Nothing is fetched here.
"""

from datetime import date
from typing import Any


TURNAROUND = "turnaround"

_REVENUE_ROW = "Total Revenue"
_EPS_ROWS = ("Diluted EPS", "Net Income")

# A year-ago column is the one nearest 365 days back, within this many days.
_YEAR_DAYS = 365
_MATCH_TOLERANCE_DAYS = 45


def _parse_date(column: str) -> date | None:
    try:
        return date.fromisoformat(str(column)[:10])
    except ValueError:
        return None


def _points(payload: dict[str, Any], label: str | None) -> list[tuple[date, float]]:
    """Dated values of one row, oldest first. Columns without a date or a value are skipped."""
    if label is None:
        return []
    row = next((r for r in payload.get("rows") or [] if r.get("label") == label), None)
    if row is None:
        return []
    values = row.get("values") or {}
    points = []
    for column in payload.get("columns") or []:
        when = _parse_date(column)
        value = values.get(column)
        if when is not None and value is not None:
            points.append((when, float(value)))
    return sorted(points)


def _eps_row(payload: dict[str, Any]) -> str | None:
    """The first of Diluted EPS and Net Income that yields a YoY pair, else the first with any value."""
    with_values = [label for label in _EPS_ROWS if _points(payload, label)]
    with_pairs = [label for label in with_values if _yoy_series(_points(payload, label))]
    return (with_pairs or with_values or [None])[0]


def _yoy(current: float, prior: float) -> float | str | None:
    """Percent change off a positive base. A positive value off a non-positive
    base is a turnaround, and two non-positive values have no change."""
    if prior > 0:
        return (current - prior) / prior * 100.0
    if current > 0:
        return TURNAROUND
    return None


def _yoy_series(points: list[tuple[date, float]]) -> list[dict[str, Any]]:
    """One entry per point that has a year-ago point, matched by date rather than position."""
    out = []
    for i, (when, value) in enumerate(points):
        target = when.toordinal() - _YEAR_DAYS
        prior = min(
            ((abs(d.toordinal() - target), v) for d, v in points[:i]),
            default=None,
        )
        if prior is not None and prior[0] <= _MATCH_TOLERANCE_DAYS:
            out.append({"date": when.isoformat(), "value": _yoy(value, prior[1])})
    return out


def _series(points: list[tuple[date, float]]) -> list[dict[str, Any]]:
    return [{"date": when.isoformat(), "value": value} for when, value in points]


def build_growth_series(ticker: str, *, annual: dict[str, Any], quarterly: dict[str, Any]) -> dict[str, Any]:
    """Revenue and EPS values with their YoY change, for the annual and the quarterly table."""
    result: dict[str, Any] = {"ticker": ticker}
    counts: dict[str, int] = {}
    for prefix, payload in (("annual", annual), ("quarterly", quarterly)):
        eps_row = _eps_row(payload)
        revenue = _points(payload, _REVENUE_ROW)
        eps = _points(payload, eps_row)
        result[f"{prefix}_revenue"] = _series(revenue)
        result[f"{prefix}_revenue_yoy"] = _yoy_series(revenue)
        result[f"{prefix}_eps"] = _series(eps)
        result[f"{prefix}_eps_yoy"] = _yoy_series(eps)
        result[f"{prefix}_eps_row"] = eps_row
        counts[f"{prefix}_columns"] = len(payload.get("columns") or [])
        counts[f"{prefix}_revenue_yoy"] = len(result[f"{prefix}_revenue_yoy"])
        counts[f"{prefix}_eps_yoy"] = len(result[f"{prefix}_eps_yoy"])
    result["counts"] = counts
    return result
