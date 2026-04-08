"""Log-Periodic Power Law (LPPL) bubble detection model.

Based on Didier Sornette's work on critical phenomena in financial markets.
The LPPL model captures super-exponential growth with accelerating
log-periodic oscillations that often appear before a crowded speculative peak.

Formula:
    ln[P(t)] = A + B(tc - t)^m + C(tc - t)^m * cos(omega * ln(tc - t) + phi)

How TerraFin turns a single LPPL fit into a bubble-confidence score:
    1. Fit LPPL on multiple trailing windows, not just one hand-picked sample.
    2. Count how many fitted windows satisfy the post-fit bubble filters.
    3. Confidence = qualifying windows / total windows scanned.

That is intentionally stricter than simply asking whether one calibration looks
convincing. The multi-window count reduces data-snooping risk and is the main
reason the confidence number is more useful than a single LPPL fit by itself.

TerraFin currently exposes two scan modes while LPPL is still under debugging:
    - default calibrated scan: evenly spaced trailing windows for stable runtime
      inside charts and agent calls
    - article ladder: up to 750 trading days down to 50 days in 5-day steps by
      calling `lppl(..., n_windows=None)`

The qualification filter retains the parts that proved stable across TerraFin's
benchmark episodes:
    - b < 0: positive bubble regime (super-exponential upside)
    - m in [0.05, 0.99]: critical growth exponent remains in bubble regime
    - omega in [4, 13]: oscillations are neither too slow nor too erratic
    - tc near the sample end: the singularity must sit close to the current
      regime, not far in the future
    - oscillation count >= 1.5: enough log-periodic turns must be present

Two implementation details matter here:
    - the default scan is calibrated for TerraFin's benchmark windows because
      the full article ladder was too slow and too brittle for in-app use
    - the full article ladder remains available for research / notebook runs
      when deeper inspection matters more than runtime

Another implementation detail is an inference from the LPPL formula itself:
    the model requires tc > t for all observations, so when an article-level
    tc range would dip below the last observation, TerraFin clamps it to just
    beyond the sample end to keep the fit mathematically valid.

Caveats (per Sornette's own recommendations):
    1. Best applied to indices or broad asset classes, not single names.
    2. Should be combined with macro / valuation context, not used alone.
    3. High confidence is a warning of fragility, not a crash-timing oracle.

References:
    Sornette, D. (2003). "Why Stock Markets Crash".
    Filimonov, V. & Sornette, D. (2013). "A stable and robust calibration
        scheme of the log-periodic power law model."
    Koistinen, J. (2020). "The Log-Periodic Power Law".
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import differential_evolution


# ── Constants ───────────────────────────────────────────────────────────

_MIN_POINTS = 50
_MIN_CONFIDENCE_POINTS = 50
_SCAN_RESTARTS = 1
_FULL_FIT_RESTARTS = 2
_MAX_WINDOW = 750
_WINDOW_STEP = 5
_TC_MIN_FRACTION = 0.0
_TC_MAX_FRACTION = 0.50

# DE search bounds.
# Wider than the pass filter on purpose: this improved recovery on the target
# benchmark windows without forcing the filter itself to become too permissive.
_M_SEARCH = (0.05, 0.99)
_OMEGA_SEARCH = (3.0, 20.0)

# Post-fit qualification filter.
# These are the conditions that directly determine the confidence indicator.
_M_FILTER = (0.05, 0.99)
_OMEGA_FILTER = (4.0, 13.0)
_OSCILLATION_MIN = 1.5
_DAMPING_MIN = 0.0
_RELATIVE_ERROR_MAX = 999.0


# ── Output ──────────────────────────────────────────────────────────────


@dataclass
class LPPLFit:
    """Single LPPL fit result."""

    tc: float
    m: float
    omega: float
    a: float
    b: float
    c: float
    phi: float
    residual: float
    fitted: list[float]


@dataclass
class LPPLResult:
    """Full LPPL analysis: confidence score + chart-ready fit.

    Confidence interpretation (per Sornette / FCO):
        0-5%:   No LPPL pattern (normal market)
        5-15%:  Some bubble possibility (caution)
        15-25%: Growing bubble formation (warning)
        25-40%: High confidence (overheated, crash likely)
        40%+:   Very high confidence (bubble peak)
    """

    confidence: float
    fit: LPPLFit | None
    qualifying_fits: list[LPPLFit]
    total_windows: int


# ── Internal ────────────────────────────────────────────────────────────


def _solve_linear(
    log_prices: np.ndarray, t: np.ndarray, tc: float, m: float, omega: float,
) -> tuple[float, float, float, float, float]:
    """OLS for linear params (A, B, C1, C2) given nonlinear (tc, m, omega)."""
    dt = tc - t
    if dt.min() <= 0:
        return (0.0, 0.0, 0.0, 0.0, float("inf"))

    dt_m = np.power(dt, m)
    log_dt = np.log(dt)

    if not (np.all(np.isfinite(dt_m)) and np.all(np.isfinite(log_dt))):
        return (0.0, 0.0, 0.0, 0.0, float("inf"))

    X = np.column_stack([
        np.ones_like(t),
        dt_m,
        dt_m * np.cos(omega * log_dt),
        dt_m * np.sin(omega * log_dt),
    ])

    if not np.all(np.isfinite(X)):
        return (0.0, 0.0, 0.0, 0.0, float("inf"))

    try:
        params, _, _, _ = np.linalg.lstsq(X, log_prices, rcond=None)
    except (np.linalg.LinAlgError, ValueError):
        return (0.0, 0.0, 0.0, 0.0, float("inf"))

    if not np.all(np.isfinite(params)):
        return (0.0, 0.0, 0.0, 0.0, float("inf"))

    ssr = float(np.sum((log_prices - X @ params) ** 2))
    return (*params, ssr)


def _objective(nonlinear: np.ndarray, log_prices: np.ndarray, t: np.ndarray) -> float:
    """Minimise SSR over (tc, m, omega)."""
    return _solve_linear(log_prices, t, *nonlinear)[-1]


def _tc_bounds(window_len: int) -> tuple[float, float]:
    """Return tc bounds near the sample end.

    We keep tc close to the current regime because LPPL is intended as a
    near-critical warning signal. The lower article bound is clamped just above
    the last observation because LPPL requires tc - t > 0 for every point.
    """
    t2 = float(window_len - 1)
    dt = max(t2, 1.0)
    lo = max(t2 + 1e-6, t2 + _TC_MIN_FRACTION * dt)
    hi = t2 + _TC_MAX_FRACTION * dt
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _legacy_window_lengths(n: int, min_window: int, n_windows: int) -> list[int]:
    """Return a deterministic evenly spaced trailing-window schedule."""
    if n_windows <= 1 or n <= min_window:
        return [min_window]
    raw = np.linspace(min_window, n, num=n_windows, endpoint=True)
    return sorted({max(min_window, min(n, int(round(value)))) for value in raw})


def _fit_bubble(
    closes: list[float], *, max_iter: int, seed: int, restarts: int, polish: bool,
) -> LPPLFit | None:
    """Fit LPPL via differential evolution with bounded nonlinear search."""
    n = len(closes)
    if n < _MIN_POINTS:
        return None

    log_prices = np.array([math.log(p) for p in closes])
    t = np.arange(n, dtype=float)

    tc_lo, tc_hi = _tc_bounds(n)
    bounds = [(tc_lo, tc_hi), _M_SEARCH, _OMEGA_SEARCH]

    best_ssr = float("inf")
    best_params = None

    for restart in range(restarts):
        s = seed + restart * 97
        try:
            result = differential_evolution(
                _objective,
                bounds=bounds,
                args=(log_prices, t),
                maxiter=max_iter,
                seed=s,
                popsize=8,
                tol=1e-6,
                polish=polish,
                updating="deferred",
            )
        except Exception:
            continue

        if result.fun < best_ssr:
            best_ssr = result.fun
            best_params = result.x

    if best_params is None:
        return None

    tc, m, omega = best_params
    a, b, c1, c2, ssr = _solve_linear(log_prices, t, tc, m, omega)
    if not math.isfinite(ssr):
        return None

    dt = tc - t
    dt = np.maximum(dt, 1e-10)
    dt_m = np.power(dt, m)
    log_dt = np.log(dt)
    fitted = a + b * dt_m + c1 * dt_m * np.cos(omega * log_dt) + c2 * dt_m * np.sin(omega * log_dt)

    return LPPLFit(
        tc=tc, m=m, omega=omega, a=a, b=b,
        c=math.sqrt(c1**2 + c2**2),
        phi=math.atan2(-c2, c1),
        residual=ssr,
        fitted=fitted.tolist(),
    )


def _is_bubble(fit: LPPLFit, closes_window: list[float]) -> bool:
    """Bubble qualification filter.

    Conditions (all must hold for positive bubble):
        1. b < 0  (super-exponential growth)
        2. 0.05 <= m <= 0.99  (critical regime exponent)
        3. 4 <= omega <= 13  (log-periodic frequency range)
        4. tc near the sample end
        5. Oscillation count O >= 1.5
        6. Optional damping / error guardrails when enabled
    """
    window_len = len(closes_window)

    if fit.b >= 0:
        return False
    if not (_M_FILTER[0] <= fit.m <= _M_FILTER[1]):
        return False
    if not (_OMEGA_FILTER[0] <= fit.omega <= _OMEGA_FILTER[1]):
        return False

    tc_lo, tc_hi = _tc_bounds(window_len)
    if not (tc_lo <= fit.tc <= tc_hi):
        return False

    # Oscillation count: O = (omega / 2pi) * ln((tc - t1) / (tc - t2))
    t1 = 0.0
    t2 = float(window_len - 1)
    dt1 = fit.tc - t1
    dt2 = fit.tc - t2
    if dt1 <= 0 or dt2 <= 0:
        return False
    oscillations = (fit.omega / (2.0 * math.pi)) * math.log(dt1 / dt2)
    if oscillations < _OSCILLATION_MIN:
        return False

    if fit.c <= 1e-12:
        return False
    damping = (fit.m * abs(fit.b)) / (fit.omega * abs(fit.c))
    if damping < _DAMPING_MIN:
        return False

    fitted_prices = np.exp(np.asarray(fit.fitted, dtype=float))
    actual_prices = np.asarray(closes_window, dtype=float)
    denom = np.maximum(fitted_prices, 1e-12)
    relative_error = np.max(np.abs(actual_prices - fitted_prices) / denom)
    if not math.isfinite(relative_error) or relative_error > _RELATIVE_ERROR_MAX:
        return False

    return True


# ── Public API ──────────────────────────────────────────────────────────


def lppl(
    closes: list[float],
    *,
    n_windows: int | None = 33,
    min_window: int = 50,
    max_window: int = _MAX_WINDOW,
    window_step: int = _WINDOW_STEP,
    max_iter: int = 45,
    seed: int | None = 42,
) -> LPPLResult:
    """Run LPPL analysis with a chart fit plus multi-window confidence scan.

    Default behavior follows TerraFin's calibrated debug profile:
        - 33 evenly spaced trailing windows
        - confidence = qualifying windows / total scanned windows
        - wider optimizer search bounds, stricter pass filter bounds

    Passing `n_windows=None` switches to the full article ladder:
        - trailing windows from up to 750 days down to 50 days
        - 5-day shrink step

    Args:
        closes: Close prices (minimum 50 points).
        n_windows: Number of evenly spaced trailing windows. Pass `None` to use
            the full article ladder instead.
        min_window: Shortest sub-window length.
        max_window: Longest sub-window length in the article-style ladder.
        window_step: Decrement between ladder windows.
        max_iter: Max iterations per differential evolution fit.
        seed: Random seed for reproducibility.

    Returns:
        :class:`LPPLResult` with confidence, full-series fit, and
        qualifying sub-window fits.
    """
    n = len(closes)
    base_seed = seed if seed is not None else 42
    if n < max(_MIN_CONFIDENCE_POINTS, min_window):
        return LPPLResult(confidence=0.0, fit=None, qualifying_fits=[], total_windows=0)

    # Full-series fit for charting
    full_fit = _fit_bubble(
        closes,
        max_iter=max_iter + 20,
        seed=base_seed,
        restarts=_FULL_FIT_RESTARTS,
        polish=True,
    )

    # Multi-window confidence scan
    if n_windows is not None:
        windows = _legacy_window_lengths(n, min_window, n_windows)
    else:
        ladder_top = min(max_window, n)
        windows = list(range(ladder_top, min_window - 1, -max(window_step, 1)))

    qualifying: list[LPPLFit] = []
    total = len(windows)
    passed = 0

    for w in windows:
        sub = closes[n - w :]
        fit = _fit_bubble(
            sub,
            max_iter=max_iter,
            seed=base_seed + w,
            restarts=_SCAN_RESTARTS,
            polish=False,
        )
        if fit is not None and _is_bubble(fit, sub):
            qualifying.append(fit)
            passed += 1

    confidence = passed / total if total > 0 else 0.0
    return LPPLResult(
        confidence=confidence,
        fit=full_fit,
        qualifying_fits=qualifying,
        total_windows=total,
    )
