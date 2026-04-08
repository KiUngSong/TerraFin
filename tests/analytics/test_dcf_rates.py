import pandas as pd

from TerraFin.analytics.analysis.fundamental.dcf.rates import fit_current_treasury_curve
from TerraFin.data.contracts import TimeSeriesDataFrame


def _make_rate_frame(close: float) -> TimeSeriesDataFrame:
    frame = TimeSeriesDataFrame(pd.DataFrame({"time": ["2026-04-04"], "close": [close]}))
    frame.name = "rate"
    return frame


class _FullRateFactory:
    def get_market_data(self, name: str):
        mapping = {
            "Treasury-13W": 5.2,
            "Treasury-2Y": 42.0,  # quoted as yield * 10
            "Treasury-5Y": 41.0,
            "Treasury-10Y": 43.0,
            "Treasury-30Y": 46.0,
        }
        return _make_rate_frame(mapping[name])


class _SparseRateFactory:
    def get_market_data(self, name: str):
        if name == "Treasury-10Y":
            return _make_rate_frame(43.0)
        raise ValueError(name)


def test_fit_current_treasury_curve_normalizes_yahoo_scaled_yields() -> None:
    curve = fit_current_treasury_curve(data_factory=_FullRateFactory())
    two_year = next(point for point in curve.points if point.label == "2Y")
    assert round(two_year.yield_pct, 2) == 4.20
    assert curve.fallback_used is False
    assert curve.fit_rmse is not None


def test_fit_current_treasury_curve_falls_back_when_points_are_sparse() -> None:
    curve = fit_current_treasury_curve(data_factory=_SparseRateFactory())
    assert curve.fallback_used is True
    assert round(curve.yield_at(5), 2) == 4.30
