"""Cross-sectional factor signals — rank tickers against each other.

Sits at the analytics/ top level (like `similarity/`), NOT under `analysis/`:
analysis/* are per-ticker analytics; factors are cross-sectional (need the whole
universe). First member: relative-strength momentum.

Evidence basis: a premise backtest (terrafin_private.recommendation.premise_backtest)
found 12-1 momentum is the only signal beating an equal-weight universe over 8yr
of weekly rebalances — but marginally (P(mom>univ)=0.945, 90% CI [-0.005%, +0.31%],
survivorship-inflated). Treat as a WEAK factor, not validated alpha. The
per-ticker technical detectors (analysis/patterns) showed no cross-sectional edge.
"""

from TerraFin.analytics.factors.relative_strength import (
    ibd_rs_raw,
    relative_strength_score,
    rs_rating,
)


__all__ = [
    "relative_strength_score",  # 12-1 momentum (premise backtest baseline)
    "ibd_rs_raw",               # IBD RS raw figure
    "rs_rating",                # IBD RS rating 1-99 (SEPA criterion 8)
]
