import TerraFin.data.cache.manager as cache_manager_module
from TerraFin.data.cache.registry import reset_cache_manager
from TerraFin.data.providers.private_access.fallbacks import get_calendar_fallback
from TerraFin.interface.private_data_service import PrivateDataService


class _FailingPrivateClient:
    def fetch_market_breadth(self):
        raise RuntimeError("breadth source unavailable")

    def fetch_calendar_events(self):
        raise RuntimeError("calendar source unavailable")

    def fetch_top_companies(self):
        raise RuntimeError("top companies source unavailable")


def test_private_data_service_falls_back_for_breadth_and_calendar(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    service = PrivateDataService(_FailingPrivateClient())

    service.refresh_market_breadth()
    service.refresh_calendar()

    breadth = service.get_market_breadth()
    sample_event = get_calendar_fallback().events[0]
    year = int(sample_event.start[:4])
    month = int(sample_event.start[5:7])
    events = service.get_calendar_events(year=year, month=month)

    assert isinstance(breadth, list)
    assert len(breadth) >= 1
    assert {"label", "value", "tone"}.issubset(breadth[0].keys())

    assert isinstance(events, list)
    assert len(events) >= 1
    assert {"title", "start", "category"}.issubset(events[0].keys())


def test_private_data_service_top_companies_falls_back_to_empty_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    service = PrivateDataService(_FailingPrivateClient())

    service.refresh_top_companies()

    assert service.get_top_companies() == []
