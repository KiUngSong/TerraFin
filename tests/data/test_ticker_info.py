import pandas as pd

from TerraFin.data.providers.market import ticker_info as ticker_info_module


class _FakeCacheManager:
    @staticmethod
    def file_cache_read(_namespace, _key, _ttl):
        return None

    @staticmethod
    def file_cache_write(_namespace, _key, _payload):
        return None

    @staticmethod
    def file_cache_clear(_namespace):
        return None


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

    ticker_info_module._INFO_CACHE.clear()
    monkeypatch.setattr(ticker_info_module, "_file_cache", lambda: _FakeCacheManager)
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

    ticker_info_module._INFO_CACHE.clear()
    monkeypatch.setattr(ticker_info_module, "_file_cache", lambda: _FakeCacheManager)
    monkeypatch.setattr(ticker_info_module.yf, "Ticker", lambda ticker: _FakeTicker())

    info = ticker_info_module.get_ticker_info("msft")

    assert info["currentPrice"] == 110.0
    assert info["regularMarketPrice"] == 110.0
    assert info["previousClose"] == 105.0
    assert info["regularMarketPreviousClose"] == 105.0
    assert info["fiftyTwoWeekHigh"] == 112.0
    assert info["fiftyTwoWeekLow"] == 98.0
