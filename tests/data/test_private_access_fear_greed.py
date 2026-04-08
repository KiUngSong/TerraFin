import TerraFin.data.cache.manager as cache_manager_module
import TerraFin.data.providers.private_access.fear_greed as fear_greed_module


class _StubClient:
    def __init__(self, history: list[dict], current: dict | Exception) -> None:
        self._history = history
        self._current = current
        self.history_calls = 0
        self.current_calls = 0

    def fetch_fear_greed(self) -> list[dict]:
        self.history_calls += 1
        return list(self._history)

    def fetch_fear_greed_current(self) -> dict:
        self.current_calls += 1
        if isinstance(self._current, Exception):
            raise self._current
        return dict(self._current)


def test_fear_greed_history_uses_file_cache_after_first_fetch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    fear_greed_module.clear_fear_greed_cache()

    history = [
        {"date": "2026-01-01", "score": 35},
        {"date": "2026-01-02", "score": 42},
        {"date": "2026-01-03", "score": 51},
    ]
    client = _StubClient(history=history, current={"score": 51, "rating": "neutral", "timestamp": "2026-01-03"})

    first = fear_greed_module.get_fear_greed_history(client=client)
    assert client.history_calls == 1
    assert first[-1]["score"] == 51

    second = fear_greed_module.get_fear_greed_history(client=client)
    assert client.history_calls == 1
    assert second == first


def test_fear_greed_current_falls_back_to_history_when_realtime_endpoint_misses(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    fear_greed_module.clear_fear_greed_cache()

    history = [
        {"date": "2026-01-01", "score": 25},
        {"date": "2026-01-10", "score": 40},
        {"date": "2026-01-28", "score": 62},
        {"date": "2026-02-01", "score": 70},
    ]
    client = _StubClient(history=history, current=RuntimeError("current endpoint unavailable"))

    current = fear_greed_module.get_fear_greed_current(client=client)

    assert client.current_calls == 1
    assert current["score"] == 70
    assert current["rating"] == "Greed"
    assert current["previous_close"] == 62
    assert current["previous_1_week"] == 40
    assert current["previous_1_month"] == 25
