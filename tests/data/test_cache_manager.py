from datetime import UTC, datetime, timedelta

import TerraFin.data.cache.manager as cache_manager_module
from TerraFin.data.cache.manager import CacheManager, CachePayloadSpec, CacheSourceSpec
from TerraFin.data.cache.policy import get_default_cache_policies


def test_cache_manager_runs_clear_only_source() -> None:
    counter = {"count": 0}

    def _clear() -> None:
        counter["count"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.clear",
            mode="clear_only",
            interval_seconds=3600,
            clear_fn=_clear,
        )
    )
    manager.refresh_due_sources(force=True)
    assert counter["count"] == 1


def test_cache_manager_runs_refresh_source() -> None:
    counter = {"count": 0}

    def _refresh() -> None:
        counter["count"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.refresh",
            mode="refresh",
            interval_seconds=3600,
            refresh_fn=_refresh,
        )
    )
    manager.refresh_due_sources(force=True)
    assert counter["count"] == 1


def test_cache_manager_reports_status() -> None:
    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.status",
            mode="clear_only",
            interval_seconds=10,
            clear_fn=lambda: None,
        )
    )
    manager.refresh_due_sources(force=True)
    status = manager.get_status()
    assert len(status) == 1
    assert status[0]["source"] == "test.status"
    assert status[0]["mode"] == "clear_only"


def test_cache_manager_skips_not_due_source_without_force() -> None:
    counter = {"count": 0}

    def _refresh() -> None:
        counter["count"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.not_due",
            mode="refresh",
            interval_seconds=3600,
            refresh_fn=_refresh,
        )
    )
    manager.refresh_due_sources(force=True)
    manager.refresh_due_sources(force=False)
    assert counter["count"] == 1


def test_cache_manager_runs_due_source_without_force() -> None:
    counter = {"count": 0}

    def _refresh() -> None:
        counter["count"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.due",
            mode="refresh",
            interval_seconds=3600,
            refresh_fn=_refresh,
        )
    )
    manager.refresh_due_sources(force=True)
    state = manager._sources["test.due"]  # noqa: SLF001 - tests intentionally verify internal policy behavior
    state.last_run_at = state.last_run_at.replace(year=2000)  # force overdue without sleeping
    manager.refresh_due_sources(force=False)
    assert counter["count"] == 2


def test_cache_manager_boundary_schedule_uses_schedule_key_not_elapsed_interval() -> None:
    counter = {"count": 0}

    manager = CacheManager(poll_seconds=1, timezone_name="Asia/Seoul")
    manager.register(
        CacheSourceSpec(
            source="test.boundary",
            mode="refresh",
            interval_seconds=86400,
            schedule="boundary",
            refresh_fn=lambda: counter.__setitem__("count", counter["count"] + 1),
        )
    )

    state = manager._sources["test.boundary"]  # noqa: SLF001 - verifies schedule-driven due logic
    state.last_run_at = datetime.now(UTC)
    state.last_schedule_key = "2000-01-01:0"

    manager.refresh_due_sources(force=False)
    manager.refresh_due_sources(force=False)

    assert counter["count"] == 1


def test_cache_manager_boundary_schedule_computes_twice_daily_slots() -> None:
    manager = CacheManager(poll_seconds=1, timezone_name="Asia/Seoul")
    spec = CacheSourceSpec(
        source="test.boundary.slot",
        mode="refresh",
        interval_seconds=43200,
        schedule="boundary",
        slots_per_day=2,
    )

    morning_key = manager._schedule_key_for_state(spec, datetime(2026, 4, 6, 0, 30, tzinfo=UTC))  # noqa: SLF001
    afternoon_key = manager._schedule_key_for_state(spec, datetime(2026, 4, 6, 4, 0, tzinfo=UTC))  # noqa: SLF001

    assert morning_key == "2026-04-06:0"
    assert afternoon_key == "2026-04-06:1"


def test_cache_manager_force_runs_all_enabled_sources() -> None:
    runs = {"a": 0, "b": 0}
    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.force.refresh",
            mode="refresh",
            interval_seconds=99999,
            refresh_fn=lambda: runs.__setitem__("a", runs["a"] + 1),
        )
    )
    manager.register(
        CacheSourceSpec(
            source="test.force.clear",
            mode="clear_only",
            interval_seconds=99999,
            clear_fn=lambda: runs.__setitem__("b", runs["b"] + 1),
        )
    )

    manager.refresh_due_sources(force=True)
    manager.refresh_due_sources(force=True)
    assert runs == {"a": 2, "b": 2}


def test_cache_manager_skips_disabled_sources_even_when_force_true() -> None:
    counter = {"count": 0}

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.disabled",
            mode="refresh",
            interval_seconds=1,
            refresh_fn=lambda: counter.__setitem__("count", counter["count"] + 1),
            enabled=False,
        )
    )
    manager.refresh_due_sources(force=True)
    assert counter["count"] == 0


def test_cache_manager_records_error_and_continues_other_sources() -> None:
    runs = {"ok": 0}

    def _fail() -> None:
        raise RuntimeError("boom")

    def _ok() -> None:
        runs["ok"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.error",
            mode="refresh",
            interval_seconds=1,
            refresh_fn=_fail,
        )
    )
    manager.register(
        CacheSourceSpec(
            source="test.ok",
            mode="refresh",
            interval_seconds=1,
            refresh_fn=_ok,
        )
    )

    manager.refresh_due_sources(force=True)
    status = {item["source"]: item for item in manager.get_status()}

    assert runs["ok"] == 1
    assert status["test.error"]["lastRunAt"] is not None
    assert status["test.error"]["lastSuccessAt"] is None
    assert "boom" in status["test.error"]["lastError"]
    assert status["test.ok"]["lastRunAt"] is not None
    assert status["test.ok"]["lastSuccessAt"] is not None
    assert status["test.ok"]["lastError"] is None


def test_cache_manager_startup_force_only_runs_refresh_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    runs = {"refresh": 0, "clear": 0}

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.startup.refresh",
            mode="refresh",
            interval_seconds=3600,
            refresh_fn=lambda: runs.__setitem__("refresh", runs["refresh"] + 1),
        )
    )
    manager.register(
        CacheSourceSpec(
            source="test.startup.clear",
            mode="clear_only",
            interval_seconds=3600,
            clear_fn=lambda: runs.__setitem__("clear", runs["clear"] + 1),
        )
    )

    manager.refresh_due_sources(force=True, force_modes={"refresh"})
    assert runs == {"refresh": 1, "clear": 0}


def test_cache_manager_persists_clear_only_due_state_across_restarts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    runs = {"count": 0}

    def _clear() -> None:
        runs["count"] += 1

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="test.persisted.clear",
            mode="clear_only",
            interval_seconds=3600,
            clear_fn=_clear,
        )
    )
    manager.refresh_due_sources(force=True)
    assert runs["count"] == 1

    restarted = CacheManager(poll_seconds=1)
    restarted.register(
        CacheSourceSpec(
            source="test.persisted.clear",
            mode="clear_only",
            interval_seconds=3600,
            clear_fn=_clear,
        )
    )
    restarted.refresh_due_sources(force=True, force_modes={"refresh"})
    restarted.refresh_due_sources(force=False)
    assert runs["count"] == 1

    state = restarted._sources["test.persisted.clear"]  # noqa: SLF001 - verifies persisted scheduling state
    state.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    state.last_anchor_at = state.last_run_at
    restarted.refresh_due_sources(force=False)
    assert runs["count"] == 2


def test_default_cache_policies_include_portfolio_source() -> None:
    policies = {policy.source: policy for policy in get_default_cache_policies()}

    assert "portfolio.cache" in policies
    assert policies["portfolio.cache"].mode == "clear_only"


def test_default_cache_policies_include_fear_greed_private_source() -> None:
    policies = {policy.source: policy for policy in get_default_cache_policies()}

    assert "private.fear_greed" in policies
    assert policies["private.fear_greed"].mode == "refresh"
    assert policies["private.fear_greed"].interval_seconds == 43200
    assert policies["private.fear_greed"].schedule == "boundary"
    assert policies["private.fear_greed"].slots_per_day == 2


def test_default_cache_policies_use_12h_for_hot_private_refresh_sources() -> None:
    policies = {policy.source: policy for policy in get_default_cache_policies()}

    assert policies["private.market_breadth"].interval_seconds == 43200
    assert policies["private.trailing_forward_pe"].interval_seconds == 43200
    assert policies["private.market_breadth"].schedule == "boundary"
    assert policies["private.market_breadth"].slots_per_day == 2
    assert policies["private.trailing_forward_pe"].schedule == "boundary"
    assert policies["private.trailing_forward_pe"].slots_per_day == 2


def test_default_cache_policies_include_top_companies_private_source() -> None:
    policies = {policy.source: policy for policy in get_default_cache_policies()}

    assert "private.top_companies" in policies
    assert policies["private.top_companies"].mode == "refresh"


def test_cache_manager_reads_stale_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    CacheManager.file_cache_write("test.namespace", "companies", [{"ticker": "AAPL"}])

    stale = CacheManager.file_cache_read_stale("test.namespace", "companies")

    assert stale == [{"ticker": "AAPL"}]


def test_register_payload_upgrades_pre_registered_source(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    calls = {"count": 0}

    manager = CacheManager(poll_seconds=1)
    manager.register(
        CacheSourceSpec(
            source="private.test",
            mode="refresh",
            interval_seconds=3600,
        )
    )
    manager.register_payload(
        CachePayloadSpec(
            source="private.test",
            namespace="test_payload",
            key="value",
            ttl_seconds=3600,
            fetch_fn=lambda: {"ok": calls.__setitem__("count", calls["count"] + 1) or True},
        )
    )

    manager.refresh_due_sources(force=True)

    assert calls["count"] == 1
    assert manager.get_payload("private.test").payload == {"ok": True}


def test_register_does_not_drop_existing_payload_callbacks(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    calls = {"count": 0}

    manager = CacheManager(poll_seconds=1)
    manager.register_payload(
        CachePayloadSpec(
            source="private.payload",
            namespace="test_payload",
            key="value",
            ttl_seconds=3600,
            fetch_fn=lambda: {"count": calls.__setitem__("count", calls["count"] + 1) or calls["count"]},
        )
    )
    manager.register(
        CacheSourceSpec(
            source="private.payload",
            mode="refresh",
            interval_seconds=7200,
        )
    )

    manager.refresh_due_sources(force=True)

    assert calls["count"] == 1
    status = {item["source"]: item for item in manager.get_status()}
    assert status["private.payload"]["intervalSeconds"] == 7200
