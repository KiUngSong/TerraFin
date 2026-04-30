import TerraFin.data.cache.manager as cache_manager_module
from TerraFin.data import DataFactory
from TerraFin.data.cache.registry import reset_cache_manager
from TerraFin.data.providers.private_access.client import PrivateAccessClient
from TerraFin.data.providers.private_access.fallbacks import get_calendar_fallback


def _install_failing_client(monkeypatch) -> None:
    def _raise(self, resource):
        _ = self, resource
        raise RuntimeError(f"private source unavailable: {resource}")

    monkeypatch.setattr(PrivateAccessClient, "fetch_panel", _raise)


def test_panels_fall_back_for_breadth_and_calendar(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    _install_failing_client(monkeypatch)
    factory = DataFactory()

    factory.refresh_panel("market_breadth")
    factory.refresh_panel("private.calendar")

    breadth = factory.get_panel_data("market_breadth")
    sample_event = get_calendar_fallback().events[0]
    year = int(sample_event.start[:4])
    month = int(sample_event.start[5:7])
    events = factory.get_calendar_events(year=year, month=month)

    assert isinstance(breadth, list)
    assert len(breadth) >= 1
    assert {"label", "value", "tone"}.issubset(breadth[0].keys())

    assert isinstance(events, list)
    assert len(events) >= 1
    assert {"title", "start", "category"}.issubset(events[0].keys())


def test_top_companies_falls_back_to_empty_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    reset_cache_manager()
    _install_failing_client(monkeypatch)
    factory = DataFactory()

    factory.refresh_panel("top_companies")
    assert factory.get_panel_data("top_companies") == []
