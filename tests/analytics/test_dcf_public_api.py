import TerraFin.analytics.analysis.fundamental as fundamental_module
import TerraFin.analytics.analysis.fundamental.dcf as dcf_module


def test_fundamental_public_api_removes_legacy_dcf_exports() -> None:
    assert hasattr(fundamental_module, "build_sp500_dcf_payload")
    assert hasattr(fundamental_module, "build_stock_dcf_payload")
    assert not hasattr(fundamental_module, "IndexDCF")
    assert not hasattr(fundamental_module, "StockDCF")
    assert not hasattr(fundamental_module, "DCF_CONSTANTS")


def test_dcf_package_exports_refactored_entry_points_only() -> None:
    assert hasattr(dcf_module, "build_sp500_template")
    assert hasattr(dcf_module, "build_stock_template")
    assert hasattr(dcf_module, "build_sp500_dcf_payload")
    assert hasattr(dcf_module, "build_stock_dcf_payload")
    assert not hasattr(dcf_module, "IndexDCF")
    assert not hasattr(dcf_module, "StockDCF")
