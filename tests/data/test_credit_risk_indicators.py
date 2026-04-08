"""Tests for credit_risk economic indicator registration."""

import pandas as pd

import TerraFin.data.providers.market.market_indicator as market_indicator_module
from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame
from TerraFin.data.providers.economic import indicator_registry


def test_high_yield_spread_registered():
    assert "High Yield Spread" in indicator_registry._indicators
    ind = indicator_registry._indicators["High Yield Spread"]
    assert ind.key == "BAMLH0A0HYM2"


def test_rrp_registered():
    assert "RRP" in indicator_registry._indicators
    ind = indicator_registry._indicators["RRP"]
    assert ind.key == "RRPONTSYD"


def test_net_liquidity_registered():
    assert "Net Liquidity" in indicator_registry._indicators
    ind = indicator_registry._indicators["Net Liquidity"]
    assert ind.key == ""  # computed, no direct FRED key


def test_forward_rate_spread_registered():
    assert "18M Forward Rate Spread" in indicator_registry._indicators
    ind = indicator_registry._indicators["18M Forward Rate Spread"]
    assert ind.key == ""  # computed


def test_credit_spread_registered():
    assert "Credit Spread" in indicator_registry._indicators
    ind = indicator_registry._indicators["Credit Spread"]
    assert ind.key == ""  # computed


def test_all_credit_risk_indicators_present():
    """All five credit/risk indicators should be in the registry."""
    expected = {"High Yield Spread", "RRP", "Net Liquidity", "18M Forward Rate Spread", "Credit Spread"}
    registered = set(indicator_registry._indicators.keys())
    assert expected.issubset(registered)


def test_move_in_market_registry():
    """MOVE index should be in the market indicator registry."""
    from TerraFin.data.providers.market import MARKET_INDICATOR_REGISTRY

    assert "MOVE" in MARKET_INDICATOR_REGISTRY
    assert MARKET_INDICATOR_REGISTRY["MOVE"].key == "^MOVE"


def test_vol_regime_in_market_registry():
    """Vol Regime should be exposed as a searchable market series."""
    from TerraFin.data.providers.market import MARKET_INDICATOR_REGISTRY

    assert "Vol Regime" in MARKET_INDICATOR_REGISTRY
    assert "VIX Rank" not in MARKET_INDICATOR_REGISTRY
    assert "MOVE Rank" not in MARKET_INDICATOR_REGISTRY


def test_net_breadth_in_market_registry():
    """Net Breadth should be exposed as a searchable market series."""
    from TerraFin.data.providers.market import MARKET_INDICATOR_REGISTRY

    assert "Net Breadth" in MARKET_INDICATOR_REGISTRY
    assert MARKET_INDICATOR_REGISTRY["Net Breadth"].key == "net-breadth"


def test_vol_regime_recent_history_uses_progressive_yfinance_seed(monkeypatch) -> None:
    def _stub_recent_history(ticker: str, *, period: str = "3y") -> HistoryChunk:
        assert ticker == "^VIX"
        assert period == "5y"
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.date_range("2022-01-01", periods=320, freq="D"),
                    "close": [float(value) for value in range(1, 321)],
                }
            )
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2022-01-01",
            loaded_end="2022-11-16",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version="seed",
        )

    monkeypatch.setattr(market_indicator_module, "get_yf_recent_history", _stub_recent_history)

    chunk = market_indicator_module._vol_regime_recent_history("vol-regime", period="3y")

    assert chunk.requested_period == "3y"
    assert chunk.source_version == "seed:vol-regime"
    assert chunk.has_older is True
    assert chunk.frame.name == "Vol Regime"
    assert chunk.frame.chart_meta["zones"] == market_indicator_module.VOL_REGIME_ZONES


def test_vvix_vix_ratio_recent_history_uses_progressive_yfinance_seed(monkeypatch) -> None:
    def _stub_recent_history(ticker: str, *, period: str = "3y") -> HistoryChunk:
        assert period == "3y"
        base = 20.0 if ticker == "^VIX" else 100.0
        frame = TimeSeriesDataFrame(
            pd.DataFrame(
                {
                    "time": pd.date_range("2026-01-01", periods=3, freq="D"),
                    "close": [base, base + 5.0, base + 10.0],
                }
            )
        )
        return HistoryChunk(
            frame=frame,
            loaded_start="2026-01-01",
            loaded_end="2026-01-03",
            requested_period=period,
            is_complete=False,
            has_older=True,
            source_version=ticker,
        )

    monkeypatch.setattr(market_indicator_module, "get_yf_recent_history", _stub_recent_history)

    chunk = market_indicator_module._vvix_vix_ratio_recent_history("vvix-vix-ratio", period="3y")

    assert chunk.frame.name == "VVIX/VIX Ratio"
    assert chunk.source_version == "^VVIX:^VIX:vvix-vix-ratio"
    assert chunk.has_older is True
    assert [round(value, 4) for value in chunk.frame["close"].tolist()] == [5.0, 4.2, 3.6667]
