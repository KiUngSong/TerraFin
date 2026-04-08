import pandas as pd
import pytest

import TerraFin.data.providers.market.yfinance as yfinance_module


def _temp_cache(tmp_path):
    class _TempCache:
        @staticmethod
        def cache_root():
            return tmp_path

        @staticmethod
        def safe_key(key: str) -> str:
            return key.lower().replace(" ", "_").replace("/", "_")

        @staticmethod
        def file_cache_read(_namespace: str, _key: str, _ttl: int):
            return None

        @staticmethod
        def file_cache_write(_namespace: str, _key: str, _payload: dict) -> None:
            return None

        @staticmethod
        def file_cache_clear(_namespace: str, _key: str | None = None) -> None:
            return None

        @staticmethod
        def file_cache_remove_tree(_namespace: str, _key: str | None = None) -> None:
            return None

    return _TempCache


def _market_frame(dates: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes}, index=pd.to_datetime(dates))


def test_get_yf_data_uses_memory_cache_without_validation(monkeypatch) -> None:
    yfinance_module.YFINANCE_CACHE.clear()
    cached = _market_frame(["2026-01-01", "2026-01-02"], [100.0, 101.0])
    yfinance_module.YFINANCE_CACHE["SPY"] = cached

    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda _ticker: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(yfinance_module.yf, "download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))

    result = yfinance_module.get_yf_data("spy")
    assert result.equals(cached)

    yfinance_module.YFINANCE_CACHE.clear()


def test_get_yf_data_uses_v2_full_artifact_without_validation(monkeypatch, tmp_path) -> None:
    yfinance_module.YFINANCE_CACHE.clear()

    monkeypatch.setattr(yfinance_module, "_file_cache", lambda: _temp_cache(tmp_path))
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda _ticker: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(yfinance_module.yf, "download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    yfinance_module._write_v2_artifact(
        "SPY",
        "full",
        _market_frame(["2026-01-01", "2026-01-02"], [100.0, 101.0]),
        is_complete=True,
        has_older=False,
    )

    result = yfinance_module.get_yf_data("spy")
    assert list(result["Close"]) == [100.0, 101.0]

    yfinance_module.YFINANCE_CACHE.clear()


def test_get_yf_data_validates_only_when_download_is_empty(monkeypatch) -> None:
    yfinance_module.YFINANCE_CACHE.clear()

    class _NoCache:
        @staticmethod
        def file_cache_read(_namespace: str, _key: str, _ttl: int):
            return None

        @staticmethod
        def file_cache_write(_namespace: str, _key: str, _payload: dict) -> None:
            return None

        @staticmethod
        def file_cache_clear(_namespace: str, _key: str | None = None) -> None:
            return None

    download_calls: list[str] = []
    validation_calls: list[str] = []

    monkeypatch.setattr(yfinance_module, "_file_cache", lambda: _NoCache)
    monkeypatch.setattr(
        yfinance_module.yf,
        "download",
        lambda ticker, **kwargs: (download_calls.append(ticker), pd.DataFrame())[1],
    )
    monkeypatch.setattr(
        yfinance_module,
        "valid_ticker",
        lambda ticker: (validation_calls.append(ticker), False)[1],
    )

    with pytest.raises(ValueError, match="Invalid ticker: BAD"):
        yfinance_module.get_yf_data("bad")

    assert download_calls == ["BAD"]
    assert validation_calls == ["BAD"]


def test_get_yf_recent_history_prefers_full_v2_cache_tail_slice(monkeypatch, tmp_path) -> None:
    yfinance_module.YFINANCE_CACHE.clear()
    yfinance_module.YFINANCE_RECENT_CACHE.clear()

    full_dates = pd.date_range("2019-01-01", periods=2400, freq="D")
    full_df = pd.DataFrame(
        {
            "Open": [100.0 + idx for idx in range(len(full_dates))],
            "High": [101.0 + idx for idx in range(len(full_dates))],
            "Low": [99.0 + idx for idx in range(len(full_dates))],
            "Close": [100.5 + idx for idx in range(len(full_dates))],
        },
        index=full_dates,
    )

    monkeypatch.setattr(yfinance_module, "_file_cache", lambda: _temp_cache(tmp_path))
    monkeypatch.setattr(yfinance_module.yf, "download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda _ticker: (_ for _ in ()).throw(AssertionError))

    yfinance_module._write_v2_artifact("SPY", "full", full_df, is_complete=True, has_older=False)

    chunk = yfinance_module.get_yf_recent_history("spy", period="3y")

    assert not chunk.frame.empty
    assert chunk.has_older is True
    assert chunk.is_complete is False
    assert chunk.loaded_end == full_dates[-1].strftime("%Y-%m-%d")
    assert chunk.loaded_start >= "2022-01-01"

    yfinance_module.YFINANCE_CACHE.clear()
    yfinance_module.YFINANCE_RECENT_CACHE.clear()


def test_get_yf_recent_history_uses_seed_v2_artifact_without_download(monkeypatch, tmp_path) -> None:
    yfinance_module.YFINANCE_CACHE.clear()
    yfinance_module.YFINANCE_RECENT_CACHE.clear()

    seed_df = pd.DataFrame(
        {
            "Open": [109.0, 119.0, 129.0],
            "High": [111.0, 121.0, 131.0],
            "Low": [108.0, 118.0, 128.0],
            "Close": [110.0, 120.0, 130.0],
        },
        index=pd.to_datetime(["2024-01-01", "2025-01-01", "2026-01-01"]),
    )

    monkeypatch.setattr(yfinance_module, "_file_cache", lambda: _temp_cache(tmp_path))
    monkeypatch.setattr(yfinance_module.yf, "download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(yfinance_module, "valid_ticker", lambda _ticker: (_ for _ in ()).throw(AssertionError))
    yfinance_module._write_v2_artifact("SPY", "seed_3y", seed_df, is_complete=False, has_older=True)

    chunk = yfinance_module.get_yf_recent_history("spy", period="3y")

    assert not chunk.frame.empty
    assert (tmp_path / "yfinance_v2" / "spy" / "seed_3y" / "meta.json").exists()
    assert chunk.source_version == "v2-seed"
    assert chunk.has_older is True

    yfinance_module.YFINANCE_CACHE.clear()
    yfinance_module.YFINANCE_RECENT_CACHE.clear()
