"""End-to-end force_refresh behavior for market_snapshot.

Locks in the contract that ``force_refresh=True`` skips the cache READ
but never deletes the on-disk artifact, so a fetch failure cannot
strand callers with no data. Pre-existing 24h-stale artifact survives,
fresh fetch overrides it on success, and a failing fresh fetch leaves
the prior stale artifact intact for the next non-force caller.
"""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import TerraFin.agent.service as agent_service
from TerraFin.data.cache import manager as cache_manager_module
from TerraFin.data.cache import registry as cache_registry_module
from TerraFin.data.cache.serializers import ColumnarTimeSeriesSerializer
from TerraFin.data.providers.market import yfinance as yfinance_provider


_TICKER = "TESTSYM"


def _write_synthetic_artifact(tmp_path, *, age_hours: float, last_close: float) -> None:
    """Write a synthetic yfinance.full artifact aged ``age_hours`` hours.

    Mirrors what `_download_frame` + `manager.get_payload` would produce
    on a successful fetch — the directory layout the ColumnarTimeSeries
    serializer reads is reproduced exactly so the service code path
    reads it as if it were a real cached fetch.

    The last bar is anchored to today so the session-calendar staleness
    check (added alongside the wall-clock TTL) sees the artifact as
    fresh; the tests in this module isolate ``force_refresh`` semantics,
    not session-calendar behavior (covered by tests/data/test_session_calendar).
    """
    # End the series at today's date so the session-calendar staleness
    # check treats it as fresh — keeps these tests focused on the
    # force_refresh contract, not on calendar interaction.
    today = datetime.now(UTC).date()
    rows = pd.bdate_range(end=today, periods=400)
    base = np.arange(len(rows), dtype=float) + 100.0
    # Force the last close to a recognizable value so the test can assert
    # which payload was served.
    close = base + 0.5
    close[-1] = last_close
    raw = pd.DataFrame(
        {
            "Open": base,
            "High": base + 1,
            "Low": base - 1,
            "Close": close,
            "Volume": (base * 1000).astype(float),
        },
        index=rows,
    )

    artifact_dir = tmp_path / "yfinance_v2" / _TICKER.lower() / "full"
    ColumnarTimeSeriesSerializer().write(artifact_dir, raw)

    # Backdate cached_at so the artifact registers as stale (>24h) when
    # the service queries it.
    meta_path = artifact_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    backdated = datetime.now(UTC) - timedelta(hours=age_hours)
    meta["cached_at"] = backdated.isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point CacheManager at tmp_path and reset the registered singleton."""
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    cache_registry_module.reset_cache_manager()
    # Clear the yfinance.full payload-spec cache so register_payload runs
    # fresh against the new manager.
    yfinance_provider._managed_cache_manager()._payload_specs.pop(
        f"yfinance.full.{_TICKER}", None
    )
    yield tmp_path
    cache_registry_module.reset_cache_manager()


def test_force_refresh_false_serves_stale_artifact_when_present(isolated_cache, monkeypatch):
    """A 25h-old artifact is past TTL; without force_refresh the service
    will attempt a fetch when the artifact is stale. Mock the fetch to
    succeed with a distinct close so we can assert which payload won."""
    _write_synthetic_artifact(isolated_cache, age_hours=25.0, last_close=111.11)

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        # Return the same shape as the stale artifact but with a new close
        # so the assertion below can detect a fresh-fetch overwrite.
        rows = pd.bdate_range(end=datetime.now(UTC).date(), periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        close = base + 0.5
        close[-1] = 222.22
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": close,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    service = agent_service.TerraFinAgentService()
    snapshot = service.market_snapshot(_TICKER, force_refresh=False)

    # The artifact short-circuit in get_yf_recent_history is bounded by
    # the TTL via read_recent(max_age_seconds=...). A 25h-old artifact
    # is past TTL, so the service falls through to a fresh fetch.
    assert snapshot["price_action"]["current"] == pytest.approx(222.22)
    assert fetch_calls == [_TICKER]


def test_force_refresh_true_triggers_upstream_fetch(isolated_cache, monkeypatch):
    """``force_refresh=True`` must call the upstream fetch even when the
    on-disk artifact is brand-new (well within TTL)."""
    _write_synthetic_artifact(isolated_cache, age_hours=0.1, last_close=111.11)

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        rows = pd.bdate_range(end=datetime.now(UTC).date(), periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        close = base + 0.5
        close[-1] = 333.33
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": close,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    service = agent_service.TerraFinAgentService()

    # Sanity check: a non-force call against the fresh artifact does NOT
    # fetch (cache hit), so we know the fetch_calls below is attributable
    # to force_refresh, not to TTL expiry.
    snap_cold = service.market_snapshot(_TICKER, force_refresh=False)
    assert fetch_calls == []
    assert snap_cold["price_action"]["current"] == pytest.approx(111.11)

    # force_refresh=True bypasses the cache read and hits upstream.
    snap_force = service.market_snapshot(_TICKER, force_refresh=True)
    assert fetch_calls == [_TICKER]
    assert snap_force["price_action"]["current"] == pytest.approx(333.33)


def test_force_refresh_failure_preserves_prior_artifact(isolated_cache, monkeypatch):
    """If the fresh fetch fails on a ``force_refresh=True`` call, the
    on-disk artifact MUST survive — the next non-force caller still
    sees the prior payload. This is the regression that eager-evict
    used to break (it deleted the artifact before fetching).

    The data-factory layer now PROPAGATES the upstream failure when
    ``force_refresh=True`` (so a freshness-verification worker can
    detect the probe failed instead of receiving silently-stale data).
    The artifact itself is still preserved on disk for the next
    non-force caller — that property is what eager-evict broke.
    """
    _write_synthetic_artifact(isolated_cache, age_hours=0.1, last_close=111.11)

    artifact_dir = isolated_cache / "yfinance_v2" / _TICKER.lower() / "full"
    assert artifact_dir.exists(), "synthetic artifact precondition"

    fetch_calls: list[str] = []

    def failing_download(ticker, *, period):
        fetch_calls.append(ticker)
        raise RuntimeError("upstream blew up")

    monkeypatch.setattr(yfinance_provider, "_download_frame", failing_download)

    service = agent_service.TerraFinAgentService()

    # force_refresh=True now raises when the fresh fetch fails — the
    # caller is opting into freshness verification and must learn that
    # it failed rather than silently see stale data.
    with pytest.raises(Exception):
        service.market_snapshot(_TICKER, force_refresh=True)
    assert fetch_calls, "force_refresh=True must trigger an upstream fetch"
    assert artifact_dir.exists(), (
        "fetch failure must NOT delete the artifact; eager-evict was the bug"
    )

    # Subsequent non-force call serves the original close from the
    # preserved artifact.
    fetch_calls.clear()
    snap_after = service.market_snapshot(_TICKER, force_refresh=False)
    assert snap_after["price_action"]["current"] == pytest.approx(111.11)
