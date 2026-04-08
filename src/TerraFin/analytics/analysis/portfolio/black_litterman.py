"""Black-Litterman portfolio allocation model.

Combines market equilibrium returns with investor views to produce
stable posterior expected returns and optimized portfolio weights.

References:
    Black, F. & Litterman, R. (1992). Global Portfolio Optimization.
    Financial Analysts Journal, 48(5), 28-43.

    He, G. & Litterman, R. (1999). The Intuition Behind Black-Litterman
    Model Portfolios. Goldman Sachs Investment Management Research.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class BLOutput:
    """Output of the Black-Litterman model.

    Attributes:
        tickers: Asset ticker symbols.
        prior_returns: Implied equilibrium returns (pi).
        posterior_returns: Blended expected returns after incorporating views.
        prior_weights: Market-cap equilibrium weights (input).
        posterior_weights: Optimized weights from posterior returns.
    """

    tickers: list[str]
    prior_returns: list[float]
    posterior_returns: list[float]
    prior_weights: list[float]
    posterior_weights: list[float]


def _implied_equilibrium_returns(
    risk_aversion: float,
    cov_matrix: np.ndarray,
    market_weights: np.ndarray,
) -> np.ndarray:
    """Reverse-optimize CAPM equilibrium returns from market-cap weights.

    pi = delta * Sigma * w_mkt
    """
    return risk_aversion * cov_matrix @ market_weights


def _posterior_returns(
    tau: float,
    cov_matrix: np.ndarray,
    pi: np.ndarray,
    P: np.ndarray,
    Q: np.ndarray,
    omega: np.ndarray,
) -> np.ndarray:
    """Compute Black-Litterman posterior expected returns.

    mu_BL = [(tau*Sigma)^-1 + P^T * Omega^-1 * P]^-1
            * [(tau*Sigma)^-1 * pi + P^T * Omega^-1 * Q]
    """
    tau_cov_inv = np.linalg.inv(tau * cov_matrix)
    omega_inv = np.linalg.inv(omega)

    # Posterior precision and mean
    precision = tau_cov_inv + P.T @ omega_inv @ P
    mean_part = tau_cov_inv @ pi + P.T @ omega_inv @ Q

    return np.linalg.solve(precision, mean_part)


def _optimal_weights(
    risk_aversion: float,
    cov_matrix: np.ndarray,
    expected_returns: np.ndarray,
) -> np.ndarray:
    """Mean-variance optimal weights: w* = (delta * Sigma)^-1 * mu."""
    raw = np.linalg.solve(risk_aversion * cov_matrix, expected_returns)
    # Normalize to sum to 1 (fully invested)
    return raw / np.sum(raw)


def black_litterman(
    tickers: list[str],
    closes_matrix: list[list[float]],
    market_caps: list[float],
    view_assets: list[list[int]],
    view_returns: list[float],
    view_confidences: list[float] | None = None,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> BLOutput:
    """Run the Black-Litterman model.

    Args:
        tickers: List of N asset ticker symbols.
        closes_matrix: List of N lists, each containing close prices
            for one asset. All lists must have the same length.
        market_caps: Market capitalizations for each asset (used to
            derive equilibrium weights).
        view_assets: Each element is a list of asset indices that a
            view applies to. For an absolute view on asset *i*, use
            ``[i]``. For a relative view (asset *i* outperforms *j*),
            use ``[i, j]``.
        view_returns: Expected return for each view. For a relative
            view ``[i, j]``, this is the expected outperformance of
            *i* over *j*.
        view_confidences: Confidence in each view, from 0.0 (no
            confidence) to 1.0 (full certainty). Defaults to 0.5 for
            all views if not provided.
        risk_aversion: Risk aversion coefficient (delta). Higher values
            produce more conservative allocations. Default 2.5.
        tau: Scalar weighting the uncertainty of the prior. Smaller
            values make the prior (equilibrium) harder to move.
            Default 0.05.

    Returns:
        BLOutput dataclass with prior/posterior returns and weights.

    Raises:
        ValueError: If input dimensions are inconsistent.
    """
    n_assets = len(tickers)
    n_views = len(view_returns)

    # ── Validate inputs ──────────────────────────────────────────────
    if len(closes_matrix) != n_assets:
        raise ValueError(f"closes_matrix has {len(closes_matrix)} assets, expected {n_assets}")
    if len(market_caps) != n_assets:
        raise ValueError(f"market_caps has {len(market_caps)} entries, expected {n_assets}")
    if len(view_assets) != n_views:
        raise ValueError(f"view_assets has {len(view_assets)} entries, expected {n_views}")

    series_len = len(closes_matrix[0])
    if series_len < 2:
        raise ValueError("Need at least 2 price observations")
    for i, series in enumerate(closes_matrix):
        if len(series) != series_len:
            raise ValueError(f"Asset {i} has {len(series)} prices, expected {series_len}")

    if view_confidences is None:
        view_confidences = [0.5] * n_views
    if len(view_confidences) != n_views:
        raise ValueError(f"view_confidences has {len(view_confidences)} entries, expected {n_views}")

    # ── Compute log returns and covariance matrix ────────────────────
    log_returns = np.zeros((series_len - 1, n_assets))
    for i, series in enumerate(closes_matrix):
        for t in range(1, series_len):
            log_returns[t - 1, i] = np.log(series[t] / series[t - 1])

    cov_matrix = np.cov(log_returns, rowvar=False) * 252  # annualize

    # ── Market-cap equilibrium weights ───────────────────────────────
    caps = np.array(market_caps, dtype=float)
    market_weights = caps / caps.sum()

    # ── Implied equilibrium returns ──────────────────────────────────
    pi = _implied_equilibrium_returns(risk_aversion, cov_matrix, market_weights)

    # ── Build pick matrix P and view vector Q ────────────────────────
    P = np.zeros((n_views, n_assets))
    Q = np.array(view_returns, dtype=float)

    for k, assets in enumerate(view_assets):
        if len(assets) == 1:
            # Absolute view: "asset i will return Q[k]"
            P[k, assets[0]] = 1.0
        elif len(assets) == 2:
            # Relative view: "asset i will outperform asset j by Q[k]"
            P[k, assets[0]] = 1.0
            P[k, assets[1]] = -1.0
        else:
            raise ValueError(f"View {k}: expected 1 or 2 asset indices, got {len(assets)}")

    # ── Build uncertainty matrix Omega ───────────────────────────────
    # Omega diagonal: low confidence → high variance, high confidence → low variance
    # Scale relative to the prior uncertainty (tau * P * Sigma * P^T)
    prior_view_var = np.diag(P @ (tau * cov_matrix) @ P.T)
    omega_diag = np.zeros(n_views)
    for k in range(n_views):
        conf = np.clip(view_confidences[k], 0.01, 0.99)
        # confidence=1 → omega≈0 (view dominates), confidence=0 → omega≈inf (view ignored)
        omega_diag[k] = prior_view_var[k] * (1.0 - conf) / conf
    omega = np.diag(omega_diag)

    # ── Posterior returns and weights ────────────────────────────────
    mu_bl = _posterior_returns(tau, cov_matrix, pi, P, Q, omega)
    weights_bl = _optimal_weights(risk_aversion, cov_matrix, mu_bl)

    return BLOutput(
        tickers=tickers,
        prior_returns=pi.tolist(),
        posterior_returns=mu_bl.tolist(),
        prior_weights=market_weights.tolist(),
        posterior_weights=weights_bl.tolist(),
    )
