import TerraFin.data.cache.manager as cache_manager_module
from TerraFin.data.cache.registry import reset_cache_manager
from TerraFin.data.providers.private_access import (
    PRIVATE_SERIES,
    clear_private_series_cache,
    get_private_series_current,
    get_private_series_history,
)
from TerraFin.data.providers.private_access.client import PrivateAccessClient


_FG_SPEC = PRIVATE_SERIES["fear_greed"]


def test_fear_greed_history_uses_file_cache_after_first_fetch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    clear_private_series_cache(_FG_SPEC)

    history = [
        {"time": "2026-01-01", "close": 35},
        {"time": "2026-01-02", "close": 42},
        {"time": "2026-01-03", "close": 51},
    ]
    history_calls = {"count": 0}

    def _mock_history(self, series_key):
        _ = self, series_key
        history_calls["count"] += 1
        return list(history)

    monkeypatch.setattr(PrivateAccessClient, "fetch_series_history", _mock_history)

    first = get_private_series_history(_FG_SPEC)
    assert history_calls["count"] == 1
    assert int(first["close"].iloc[-1]) == 51

    second = get_private_series_history(_FG_SPEC)
    assert history_calls["count"] == 1
    assert second.equals(first)


def test_fear_greed_current_returns_snapshot_from_canonical_wire(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    clear_private_series_cache(_FG_SPEC)

    current_calls = {"count": 0}

    def _mock_current(self, series_key):
        _ = self, series_key
        current_calls["count"] += 1
        return {
            "name": "Fear & Greed",
            "value": 70,
            "as_of": "2026-02-01",
            "rating": "Greed",
            "change": 8.0,
            "change_pct": 12.9,
            "unit": None,
            "metadata": {"previous_close": 62, "previous_1_week": 40, "previous_1_month": 25},
        }

    monkeypatch.setattr(PrivateAccessClient, "fetch_series_current", _mock_current)

    snapshot = get_private_series_current(_FG_SPEC)

    assert current_calls["count"] == 1
    assert snapshot.value == 70
    assert snapshot.rating == "Greed"
    assert snapshot.as_of == "2026-02-01"
    assert snapshot.metadata["previous_close"] == 62
    assert snapshot.metadata["previous_1_week"] == 40
    assert snapshot.metadata["previous_1_month"] == 25
