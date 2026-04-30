import pandas as pd

import TerraFin.data.cache.manager as cache_manager_module
import TerraFin.data.providers.corporate.fundamentals.yfinance_adapter as fundamentals_module


class _FakeTicker:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.quarterly_cash_flow = pd.DataFrame(
            {
                pd.Timestamp("2025-12-31"): [300.0, -80.0],
                pd.Timestamp("2025-09-30"): [280.0, -70.0],
            },
            index=["Operating Cash Flow", "Capital Expenditure"],
        )


def test_get_corporate_data_normalizes_yfinance_statement_shape(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    fundamentals_module.clear_corporate_data_cache()
    monkeypatch.setattr(fundamentals_module.yf, "Ticker", _FakeTicker)

    frame = fundamentals_module.get_corporate_data("TEST", "cashflow", period="quarter")

    assert frame is not None
    assert frame.statement_type == "cashflow"
    assert frame.period == "quarterly"
    assert frame.ticker == "TEST"
    assert frame.columns.tolist() == ["2025-12-31", "2025-09-30"]
    assert frame.index.tolist() == ["Operating Cash Flow", "Capital Expenditure"]
    assert frame.loc["Operating Cash Flow"].tolist() == [300.0, 280.0]
