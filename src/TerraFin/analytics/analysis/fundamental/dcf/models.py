from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


DCFStatus = Literal["ready", "insufficient_data"]
EntityType = Literal["index", "stock"]


@dataclass(frozen=True)
class ScenarioDefinition:
    key: str
    label: str
    growth_shift_pct: float
    discount_shift_bps: int
    terminal_growth_shift_bps: int


SCENARIO_DEFINITIONS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition("bear", "Bear", growth_shift_pct=-2.0, discount_shift_bps=100, terminal_growth_shift_bps=-50),
    ScenarioDefinition("base", "Base", growth_shift_pct=0.0, discount_shift_bps=0, terminal_growth_shift_bps=0),
    ScenarioDefinition("bull", "Bull", growth_shift_pct=2.0, discount_shift_bps=-100, terminal_growth_shift_bps=50),
)


@dataclass
class RateCurvePoint:
    maturity_years: float
    yield_pct: float
    label: str


@dataclass
class RateCurveSnapshot:
    as_of: str
    source: str
    points: list[RateCurvePoint]
    fallback_used: bool = False
    fit_rmse: float | None = None
    fitted_points: list[RateCurvePoint] = field(default_factory=list)
    fallback_yield_pct: float | None = None
    curve: Any | None = field(default=None, repr=False)

    def yield_at(self, maturity_years: float) -> float:
        if self.curve is not None:
            return float(self.curve.yield_at(maturity_years))
        if self.fallback_yield_pct is not None:
            return float(self.fallback_yield_pct)
        if self.points:
            return float(self.points[-1].yield_pct)
        raise ValueError("No rate data available")


@dataclass
class ProjectionRow:
    year_offset: int
    forecast_date: str
    growth_pct: float
    cash_flow_per_share: float
    discount_rate_pct: float
    discount_factor: float
    present_value: float


@dataclass
class DiscountedCashFlowResult:
    projected_cash_flows: list[ProjectionRow]
    terminal_cash_flow_per_share: float
    terminal_growth_pct: float
    terminal_discount_rate_pct: float
    terminal_value: float
    intrinsic_value: float


@dataclass
class DCFInputTemplate:
    status: DCFStatus
    entity_type: EntityType
    symbol: str
    as_of: date
    current_price: float | None
    base_cash_flow_per_share: float | None
    base_growth_pct: float | None
    terminal_growth_pct: float
    yearly_risk_free_rates_pct: list[float]
    terminal_risk_free_rate_pct: float
    discount_spread_pct: float
    rate_curve: RateCurveSnapshot
    assumptions: dict[str, Any]
    data_quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SP500YearAssumption:
    year_offset: int
    growth_pct: float
    payout_ratio_pct: float
    buyback_ratio_pct: float
    equity_risk_premium_pct: float


@dataclass(frozen=True)
class SP500DCFOverrides:
    base_year_eps: float | None = None
    terminal_growth_pct: float | None = None
    terminal_equity_risk_premium_pct: float | None = None
    terminal_roe_pct: float | None = None
    yearly_assumptions: tuple[SP500YearAssumption, ...] | None = None


StockFcfBaseSource = Literal["auto", "3yr_avg", "ttm", "latest_annual"]


@dataclass(frozen=True)
class StockDCFOverrides:
    base_cash_flow_per_share: float | None = None
    base_growth_pct: float | None = None
    terminal_growth_pct: float | None = None
    beta: float | None = None
    equity_risk_premium_pct: float | None = None
    current_price: float | None = None
    # Source picker for how the DCF base FCF/share is derived from company data.
    # auto = 3yr_avg → annual → ttm cascade (normalized over recent, the professional
    # default). An explicit `base_cash_flow_per_share` override still wins over this.
    fcf_base_source: StockFcfBaseSource | None = None
    # Turnaround-mode inputs. When breakeven_year, breakeven_cash_flow_per_share,
    # and post_breakeven_growth_pct are all set, the template builds an explicit
    # schedule instead of the single-base × linear-growth path — lets users
    # value companies with negative current FCF whose thesis is a future turn.
    breakeven_year: int | None = None
    breakeven_cash_flow_per_share: float | None = None
    post_breakeven_growth_pct: float | None = None
