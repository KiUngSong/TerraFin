"""Interest rate analytics — yield curve fitting and forward rate computation."""

from .nelson_siegel import NelsonSiegelCurve, fit


__all__ = ["NelsonSiegelCurve", "fit"]
