from datetime import date

from TerraFin.analytics.analysis.rates.nelson_siegel import fit
from TerraFin.data import DataFactory

from .models import RateCurvePoint, RateCurveSnapshot


TREASURY_SERIES: tuple[tuple[str, float, str], ...] = (
    ("Treasury-13W", 0.25, "13W"),
    ("Treasury-2Y", 2.0, "2Y"),
    ("Treasury-5Y", 5.0, "5Y"),
    ("Treasury-10Y", 10.0, "10Y"),
    ("Treasury-30Y", 30.0, "30Y"),
)


def _latest_close(name: str, data_factory: DataFactory) -> float:
    frame = data_factory.get_market_data(name)
    if frame.empty or "close" not in frame.columns:
        raise ValueError(f"No market data for {name}")
    value = float(frame["close"].dropna().iloc[-1])
    # Yahoo Treasury tickers are often quoted as yield * 10.
    if abs(value) > 20:
        value = value / 10.0
    return float(value)


def fit_current_treasury_curve(
    *,
    data_factory: DataFactory | None = None,
    as_of: date | None = None,
) -> RateCurveSnapshot:
    factory = data_factory or DataFactory()
    snapshot_date = (as_of or date.today()).isoformat()
    points: list[RateCurvePoint] = []

    for indicator_name, maturity_years, label in TREASURY_SERIES:
        try:
            points.append(
                RateCurvePoint(
                    maturity_years=maturity_years,
                    yield_pct=_latest_close(indicator_name, factory),
                    label=label,
                )
            )
        except Exception:
            continue

    fallback_yield = None
    if points:
        ten_year = next((point.yield_pct for point in points if point.label == "10Y"), None)
        fallback_yield = ten_year if ten_year is not None else points[-1].yield_pct

    if len(points) < 3:
        return RateCurveSnapshot(
            as_of=snapshot_date,
            source="treasury.market-indicators",
            points=points,
            fallback_used=True,
            fit_rmse=None,
            fitted_points=list(points),
            fallback_yield_pct=fallback_yield if fallback_yield is not None else 4.0,
        )

    curve = fit(
        [point.maturity_years for point in points],
        [point.yield_pct for point in points],
    )
    fitted_points = [
        RateCurvePoint(maturity_years=maturity, yield_pct=float(curve.yield_at(maturity)), label=label)
        for _, maturity, label in TREASURY_SERIES
    ]
    return RateCurveSnapshot(
        as_of=snapshot_date,
        source="treasury.market-indicators",
        points=points,
        fallback_used=False,
        fit_rmse=curve.rmse,
        fitted_points=fitted_points,
        fallback_yield_pct=fallback_yield,
        curve=curve,
    )
