import TerraFin.analytics.analysis.risk as risk_module


def test_risk_package_exports_beta_entry_points() -> None:
    assert hasattr(risk_module, "estimate_beta_5y_monthly")
    assert hasattr(risk_module, "estimate_beta_5y_monthly_adjusted")
    assert hasattr(risk_module, "select_default_benchmark")
    assert hasattr(risk_module, "BETA_5Y_MONTHLY_METHOD_ID")
    assert hasattr(risk_module, "BETA_5Y_MONTHLY_ADJUSTED_METHOD_ID")
