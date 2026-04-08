"""Nelson-Siegel yield curve fitting.

Fits a smooth yield curve to discrete Treasury rate observations,
enabling interpolation at arbitrary maturities and forward rate computation.

Model:
    y(m) = beta0 + beta1 * [(1 - e^(-m/tau)) / (m/tau)]
                 + beta2 * [(1 - e^(-m/tau)) / (m/tau) - e^(-m/tau)]

Parameters:
    beta0: Long-term level (where the curve flattens at long maturities)
    beta1: Slope (short-end vs long-end spread)
    beta2: Curvature (hump or dip in the middle of the curve)
    tau:   Decay (where along the maturity axis the hump peaks)
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass
class NelsonSiegelCurve:
    """Fitted Nelson-Siegel yield curve.

    Attributes:
        beta0: Long-term level.
        beta1: Slope factor.
        beta2: Curvature factor.
        tau: Decay parameter.
        maturities: Observed maturities used for fitting (years).
        observed_yields: Observed yields used for fitting (%).
        rmse: Root mean squared error of the fit (%).
    """

    beta0: float
    beta1: float
    beta2: float
    tau: float
    maturities: list[float]
    observed_yields: list[float]
    rmse: float

    def yield_at(self, maturity: float) -> float:
        """Interpolate yield at an arbitrary maturity.

        Args:
            maturity: Maturity in years (must be > 0).

        Returns:
            Yield in the same unit as input (typically %).
        """
        if maturity <= 0:
            raise ValueError(f"Maturity must be positive, got {maturity}")
        return _ns_yield(maturity, self.beta0, self.beta1, self.beta2, self.tau)

    def yields_at(self, maturities: list[float]) -> list[float]:
        """Interpolate yields at multiple maturities.

        Args:
            maturities: List of maturities in years (each must be > 0).

        Returns:
            List of yields.
        """
        return [self.yield_at(m) for m in maturities]

    def forward_rate(self, t1: float, t2: float) -> float:
        """Implied forward rate between two maturities.

        Computes the rate implied by the curve for borrowing from t1 to t2:
            f(t1, t2) = [y(t2)*t2 - y(t1)*t1] / (t2 - t1)

        This is the instantaneous forward rate approximation derived from
        the zero-coupon yield curve.

        Args:
            t1: Start maturity in years (must be > 0).
            t2: End maturity in years (must be > t1).

        Returns:
            Forward rate in the same unit as yields (typically %).
        """
        if t1 <= 0:
            raise ValueError(f"t1 must be positive, got {t1}")
        if t2 <= t1:
            raise ValueError(f"t2 must be greater than t1, got t1={t1}, t2={t2}")

        y1 = self.yield_at(t1)
        y2 = self.yield_at(t2)
        return (y2 * t2 - y1 * t1) / (t2 - t1)

    def fitted_yields(self) -> list[float]:
        """Yields predicted by the model at the observed maturities."""
        return self.yields_at(self.maturities)

    def residuals(self) -> list[float]:
        """Difference between observed and fitted yields at each maturity."""
        fitted = self.fitted_yields()
        return [obs - fit for obs, fit in zip(self.observed_yields, fitted)]


def _ns_yield(m: float, beta0: float, beta1: float, beta2: float, tau: float) -> float:
    """Evaluate the Nelson-Siegel yield at maturity m."""
    x = m / tau
    if x < 1e-10:
        # Limit as m/tau -> 0: factor1 -> 1, factor2 -> 0
        return beta0 + beta1
    exp_x = np.exp(-x)
    factor1 = (1 - exp_x) / x
    factor2 = factor1 - exp_x
    return beta0 + beta1 * factor1 + beta2 * factor2


def _ns_yields_vec(maturities: np.ndarray, beta0: float, beta1: float, beta2: float, tau: float) -> np.ndarray:
    """Vectorized Nelson-Siegel yields."""
    x = maturities / tau
    # Avoid division by zero for very small x
    safe_x = np.where(x < 1e-10, 1e-10, x)
    exp_x = np.exp(-safe_x)
    factor1 = (1 - exp_x) / safe_x
    factor2 = factor1 - exp_x
    return beta0 + beta1 * factor1 + beta2 * factor2


def fit(
    maturities: list[float],
    yields: list[float],
    tau_bounds: tuple[float, float] = (0.1, 30.0),
) -> NelsonSiegelCurve:
    """Fit a Nelson-Siegel curve to observed yield data.

    Args:
        maturities: Observed maturities in years (e.g., [0.25, 2, 5, 10, 30]).
        yields: Observed yields in % (e.g., [4.8, 4.2, 4.0, 4.3, 4.5]).
        tau_bounds: Bounds for the tau (decay) parameter search.

    Returns:
        Fitted NelsonSiegelCurve object.

    Raises:
        ValueError: If inputs are invalid or optimization fails.
    """
    if len(maturities) != len(yields):
        raise ValueError(f"Length mismatch: {len(maturities)} maturities vs {len(yields)} yields")
    if len(maturities) < 3:
        raise ValueError("Need at least 3 data points to fit Nelson-Siegel (4 parameters)")

    mat = np.array(maturities, dtype=float)
    obs = np.array(yields, dtype=float)

    if np.any(mat <= 0):
        raise ValueError("All maturities must be positive")

    def objective(params):
        b0, b1, b2, tau = params
        if tau <= 0:
            return 1e10
        predicted = _ns_yields_vec(mat, b0, b1, b2, tau)
        return np.sum((obs - predicted) ** 2)

    # Initial guess: beta0 ~ long-end yield, beta1 ~ short-long spread, beta2 ~ 0
    b0_init = obs[-1]
    b1_init = obs[0] - obs[-1]
    b2_init = 0.0
    tau_init = np.mean(mat)

    best_result = None
    best_cost = np.inf

    # Try multiple tau starting points for robustness
    tau_starts = [0.5, 1.0, 2.0, 5.0, tau_init]
    for tau_start in tau_starts:
        x0 = [b0_init, b1_init, b2_init, tau_start]
        result = minimize(
            objective,
            x0,
            method="L-BFGS-B",
            bounds=[
                (None, None),  # beta0
                (None, None),  # beta1
                (None, None),  # beta2
                (tau_bounds[0], tau_bounds[1]),  # tau
            ],
        )
        if result.fun < best_cost:
            best_cost = result.fun
            best_result = result

    b0, b1, b2, tau = best_result.x
    rmse = np.sqrt(best_cost / len(maturities))

    return NelsonSiegelCurve(
        beta0=float(b0),
        beta1=float(b1),
        beta2=float(b2),
        tau=float(tau),
        maturities=list(maturities),
        observed_yields=list(yields),
        rmse=float(rmse),
    )
