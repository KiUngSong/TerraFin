import pandas as pd

from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.providers.market import ticker_info as ticker_info_module


def _reset_manager_caches(monkeypatch) -> None:
    manager = get_cache_manager()
    for source in list(manager._payload_specs.keys()):
        if source.startswith("market.ticker_info.") or source.startswith("market.earnings."):
            manager.clear_payload(source)
    manager._memory_payloads.clear()
    monkeypatch.setattr(
        ticker_info_module,
        "_manager",
        lambda: _PatchedManager(manager),
    )


class _PatchedManager:
    """Wrap manager so file_cache_* are no-ops in tests (avoid disk writes)."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def get_payload(self, source, **kwargs):
        spec = self._real._payload_specs[source]
        from TerraFin.data.cache.manager import CachePayloadResult

        memory = self._real._read_memory_payload(source, spec.ttl_seconds)
        if memory is not None:
            return CachePayloadResult(payload=memory, freshness="fresh")
        payload = spec.fetch_fn()
        self._real._write_memory_payload(source, payload)
        return CachePayloadResult(payload=payload, freshness="fresh")


def test_get_ticker_info_falls_back_to_fast_info_when_info_is_empty(monkeypatch) -> None:
    class _FakeTicker:
        @property
        def info(self):
            return {}

        @property
        def fast_info(self):
            return {
                "lastPrice": 123.45,
                "previousClose": 120.0,
                "marketCap": 987654321.0,
                "yearHigh": 150.0,
                "yearLow": 95.0,
                "exchange": "NMS",
            }

        def history(self, period="1y", auto_adjust=True):
            assert period == "1y"
            assert auto_adjust is True
            return pd.DataFrame()

    _reset_manager_caches(monkeypatch)
    monkeypatch.setattr(ticker_info_module.yf, "Ticker", lambda ticker: _FakeTicker())

    info = ticker_info_module.get_ticker_info("aapl")

    assert info["currentPrice"] == 123.45
    assert info["regularMarketPrice"] == 123.45
    assert info["previousClose"] == 120.0
    assert info["regularMarketPreviousClose"] == 120.0
    assert info["marketCap"] == 987654321.0
    assert info["fiftyTwoWeekHigh"] == 150.0
    assert info["fiftyTwoWeekLow"] == 95.0
    assert info["exchange"] == "NMS"


def test_get_ticker_info_falls_back_to_history_when_fast_info_is_incomplete(monkeypatch) -> None:
    class _FakeTicker:
        @property
        def info(self):
            return {}

        @property
        def fast_info(self):
            return {}

        def history(self, period="1y", auto_adjust=True):
            assert period == "1y"
            assert auto_adjust is True
            return pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0],
                    "High": [101.0, 108.0, 112.0],
                    "Low": [98.0, 103.0, 107.0],
                }
            )

    _reset_manager_caches(monkeypatch)
    monkeypatch.setattr(ticker_info_module.yf, "Ticker", lambda ticker: _FakeTicker())

    info = ticker_info_module.get_ticker_info("msft")

    assert info["currentPrice"] == 110.0
    assert info["regularMarketPrice"] == 110.0
    assert info["previousClose"] == 105.0
    assert info["regularMarketPreviousClose"] == 105.0
    assert info["fiftyTwoWeekHigh"] == 112.0
    assert info["fiftyTwoWeekLow"] == 98.0
