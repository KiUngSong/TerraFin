"""Tests for session-aware staleness of the ``yfinance.full`` cache.

The wall-clock 24h TTL is too coarse: an artifact written at 18:00 UTC
stays fresh by TTL until 18:00 UTC the next day, even though the US
session has closed at ~21:00 UTC and a newer bar exists. The
session-calendar helper closes that gap.
"""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from TerraFin.data.cache import manager as cache_manager_module
from TerraFin.data.cache import registry as cache_registry_module
from TerraFin.data.cache.serializers import ColumnarTimeSeriesSerializer
from TerraFin.data.providers.market import yfinance as yfinance_provider
from TerraFin.data.providers.market.session_calendar import (
    ASX,
    EURONEXT_PARIS,
    HKEX,
    KRX,
    LSE,
    NYSE,
    SIX_SWISS,
    SSE,
    SZSE,
    TSE,
    XETRA,
    is_cache_stale_by_session,
    latest_expected_close,
    resolve_exchange,
)


# --- pure helper coverage ----------------------------------------------------


def test_resolve_exchange_routes_us_tickers_to_nyse() -> None:
    assert resolve_exchange("AAPL").name == "NYSE"
    assert resolve_exchange("^VIX").name == "NYSE"
    assert resolve_exchange("^GSPC").name == "NYSE"


def test_resolve_exchange_routes_krx_six_digit_to_krx() -> None:
    assert resolve_exchange("005930").name == "KRX"
    assert resolve_exchange("005930.KS").name == "KRX"


def test_resolve_exchange_routes_crypto_and_forex_to_skip() -> None:
    crypto = resolve_exchange("BTC-USD")
    forex = resolve_exchange("USDKRW=X")
    assert crypto.trading_weekdays is None  # always-open
    assert forex.trading_weekdays == ()  # no daily close concept


# Fix 1: class-share dashes are not crypto. Tightened the crypto suffix
# allowlist so ``BRK-B`` / ``BF-B`` / ``BRK-A`` stay on the NYSE schedule
# (and therefore the staleness check), while real crypto pairs with known
# quote suffixes still resolve to CRYPTO.
def test_resolve_exchange_class_share_dashes_route_to_us() -> None:
    assert resolve_exchange("BRK-B").name == "NYSE"
    assert resolve_exchange("BRK-A").name == "NYSE"
    assert resolve_exchange("BF-B").name == "NYSE"


def test_resolve_exchange_known_crypto_suffixes_route_to_crypto() -> None:
    assert resolve_exchange("BTC-USD").name == "CRYPTO"
    assert resolve_exchange("ETH-USDT").name == "CRYPTO"
    assert resolve_exchange("XRP-USD").name == "CRYPTO"
    assert resolve_exchange("SOL-USDC").name == "CRYPTO"
    assert resolve_exchange("ETH-BTC").name == "CRYPTO"


def test_resolve_exchange_unknown_dash_suffix_defaults_to_us() -> None:
    # Defensive: anything with a dash but no recognized crypto quote
    # suffix falls through to NYSE (where it will be staleness-checked).
    assert resolve_exchange("RANDOM-FOO").name == "NYSE"


# Fix 3: foreign-exchange suffix map.
def test_resolve_exchange_foreign_suffixes() -> None:
    assert resolve_exchange("7203.T").name == "TSE"
    assert resolve_exchange("0700.HK").name == "HKEX"
    assert resolve_exchange("600519.SS").name == "SSE"
    assert resolve_exchange("000001.SZ").name == "SZSE"
    assert resolve_exchange("HSBA.L").name == "LSE"
    assert resolve_exchange("CBA.AX").name == "ASX"
    assert resolve_exchange("MC.PA").name == "EURONEXT_PARIS"
    assert resolve_exchange("SAP.DE").name == "XETRA"
    assert resolve_exchange("NESN.SW").name == "SIX_SWISS"


def test_latest_expected_close_for_tse_basic() -> None:
    # Wed 07:00 UTC = 16:00 JST — past 15:00 JST close.
    now = datetime(2025, 1, 8, 7, 0, tzinfo=UTC)
    close = latest_expected_close(TSE, now_utc=now)
    assert close is not None
    jst_close = close.astimezone(ZoneInfo("Asia/Tokyo"))
    assert jst_close.date() == datetime(2025, 1, 8).date()
    assert jst_close.hour == 15
    assert jst_close.minute == 0


def test_latest_expected_close_for_lse_mid_session_returns_prior_day() -> None:
    # Wed 14:00 UTC = 14:00 GMT (winter) — pre-16:30 GMT close, so most
    # recent close is Tuesday.
    now = datetime(2025, 1, 8, 14, 0, tzinfo=UTC)
    close = latest_expected_close(LSE, now_utc=now)
    assert close is not None
    london = close.astimezone(ZoneInfo("Europe/London"))
    assert london.date() == datetime(2025, 1, 7).date()


def test_latest_expected_close_for_lse_summer_dst_handled() -> None:
    # Wed July 9 2025, 16:00 UTC = 17:00 BST — past 16:30 BST close.
    now = datetime(2025, 7, 9, 16, 0, tzinfo=UTC)
    close = latest_expected_close(LSE, now_utc=now)
    assert close is not None
    london = close.astimezone(ZoneInfo("Europe/London"))
    assert london.date() == datetime(2025, 7, 9).date()
    assert london.hour == 16
    assert london.minute == 30


def test_latest_expected_close_for_xetra_summer_dst() -> None:
    # Wed July 9 2025, 16:00 UTC = 18:00 CEST — past 17:30 CEST close.
    now = datetime(2025, 7, 9, 16, 0, tzinfo=UTC)
    close = latest_expected_close(XETRA, now_utc=now)
    assert close is not None
    berlin = close.astimezone(ZoneInfo("Europe/Berlin"))
    assert berlin.date() == datetime(2025, 7, 9).date()
    assert berlin.hour == 17
    assert berlin.minute == 30


def test_is_cache_stale_for_tse_after_close() -> None:
    # last bar Tuesday, now Wed 08:00 UTC = 17:00 JST (past 15:00 JST close).
    last_bar = datetime(2025, 1, 7, 6, 0, tzinfo=UTC)
    now = datetime(2025, 1, 8, 8, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "7203.T", now_utc=now) is True


def test_is_cache_stale_for_tse_mid_session_false() -> None:
    # Wed 05:00 UTC = 14:00 JST — pre-close; Tuesday's bar still fresh.
    last_bar = datetime(2025, 1, 7, 6, 0, tzinfo=UTC)
    now = datetime(2025, 1, 8, 5, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "7203.T", now_utc=now) is False


def test_is_cache_stale_for_lse_mid_session_false_summer() -> None:
    # Wed July 9 2025 15:00 UTC = 16:00 BST — pre-16:30 BST close.
    last_bar = datetime(2025, 7, 8, 15, 30, tzinfo=UTC)
    now = datetime(2025, 7, 9, 15, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "HSBA.L", now_utc=now) is False


def test_is_cache_stale_for_brk_b_uses_us_schedule() -> None:
    # Regression for the original misroute: BRK-B must hit the staleness
    # check, not get skipped under CRYPTO.
    last_bar = datetime(2025, 1, 7, 21, 0, tzinfo=UTC)
    now = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "BRK-B", now_utc=now) is True


def test_latest_expected_close_for_nyse_during_session_returns_prior_close() -> None:
    # Wednesday 14:00 ET (= 18:00 UTC) — today's 16:00 ET close hasn't
    # happened yet, so the most recent expected close is Tuesday 16:00 ET.
    now = datetime(2025, 1, 8, 18, 0, tzinfo=UTC)  # Wed 13:00 ET (winter)
    close = latest_expected_close(NYSE, now_utc=now)
    assert close is not None
    et_close = close.astimezone(ZoneInfo("America/New_York"))
    assert et_close.date() == datetime(2025, 1, 7).date()  # Tuesday


def test_latest_expected_close_after_today_close_returns_today() -> None:
    # Wednesday 22:00 UTC = 17:00 ET — past today's 16:00 ET close.
    now = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
    close = latest_expected_close(NYSE, now_utc=now)
    assert close is not None
    et_close = close.astimezone(ZoneInfo("America/New_York"))
    assert et_close.date() == datetime(2025, 1, 8).date()  # Wed
    assert et_close.hour == 16


def test_latest_expected_close_weekend_walks_back_to_friday() -> None:
    # Sunday — must walk back through Saturday to Friday.
    now = datetime(2025, 1, 12, 18, 0, tzinfo=UTC)  # Sun
    close = latest_expected_close(NYSE, now_utc=now)
    assert close is not None
    et_close = close.astimezone(ZoneInfo("America/New_York"))
    assert et_close.weekday() == 4  # Friday


def test_is_cache_stale_for_us_after_session_close_returns_true() -> None:
    # Artifact's last bar dated 2025-01-07 (Tue), now Wed 22:00 UTC
    # (17:00 ET — past today's close). Today's bar should exist upstream.
    last_bar = datetime(2025, 1, 7, 21, 0, tzinfo=UTC)
    now = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "AAPL", now_utc=now) is True


def test_is_cache_stale_for_us_mid_session_returns_false() -> None:
    # Artifact's last bar dated 2025-01-07, now Wed 16:00 UTC (11:00 ET
    # — today's close hasn't happened). Today's bar is not yet expected
    # upstream, so the artifact is fresh by session-calendar.
    last_bar = datetime(2025, 1, 7, 21, 0, tzinfo=UTC)
    now = datetime(2025, 1, 8, 16, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "AAPL", now_utc=now) is False


def test_is_cache_stale_for_krx_after_session_close_returns_true() -> None:
    # Artifact's last bar dated 2025-01-07 (Tue), now Wed 08:00 UTC
    # (17:00 KST — past KRX's 15:30 KST close). Today's bar should exist.
    last_bar = datetime(2025, 1, 7, 6, 30, tzinfo=UTC)  # Tue KRX close
    now = datetime(2025, 1, 8, 8, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "005930", now_utc=now) is True


def test_is_cache_stale_for_crypto_always_false() -> None:
    # Crypto runs 24/7 — no concept of session close.
    last_bar = datetime(2020, 1, 1, tzinfo=UTC)
    now = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "BTC-USD", now_utc=now) is False


def test_is_cache_stale_for_forex_always_false() -> None:
    # Forex runs 24/5 — no single daily close to wait on.
    last_bar = datetime(2020, 1, 1, tzinfo=UTC)
    now = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
    assert is_cache_stale_by_session(last_bar, "USDKRW=X", now_utc=now) is False


def test_latest_expected_close_for_krx_basic() -> None:
    # Wed 09:00 UTC = 18:00 KST — past 15:30 KST close.
    now = datetime(2025, 1, 8, 9, 0, tzinfo=UTC)
    close = latest_expected_close(KRX, now_utc=now)
    assert close is not None
    kst_close = close.astimezone(ZoneInfo("Asia/Seoul"))
    assert kst_close.date() == datetime(2025, 1, 8).date()
    assert kst_close.hour == 15
    assert kst_close.minute == 30


# --- end-to-end: cache read path actually re-fetches ------------------------


_TICKER = "TESTSESH"


def _write_synthetic_artifact(tmp_path, *, last_bar_date: str, cached_at: datetime) -> None:
    """Write a synthetic yfinance.full artifact with a controlled last
    bar date and cached_at timestamp."""
    rows = pd.bdate_range(end=last_bar_date, periods=400)
    base = np.arange(len(rows), dtype=float) + 100.0
    raw = pd.DataFrame(
        {
            "Open": base,
            "High": base + 1,
            "Low": base - 1,
            "Close": base + 0.5,
            "Volume": (base * 1000).astype(float),
        },
        index=rows,
    )

    artifact_dir = tmp_path / "yfinance_v2" / _TICKER.lower() / "full"
    ColumnarTimeSeriesSerializer().write(artifact_dir, raw)

    meta_path = artifact_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["cached_at"] = cached_at.isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_manager_module, "_FILE_CACHE_DIR", tmp_path)
    cache_registry_module.reset_cache_manager()
    yfinance_provider._managed_cache_manager()._payload_specs.pop(
        f"yfinance.full.{_TICKER}", None
    )
    yield tmp_path
    cache_registry_module.reset_cache_manager()


def test_get_yf_recent_history_refetches_when_session_stale(isolated_cache, monkeypatch):
    """A wall-clock-fresh artifact whose last bar predates today's
    expected NYSE close should trigger a re-fetch."""
    # cached_at = real-recent so the cache-manager + serializer wall-clock
    # TTL checks (which use the real datetime, not our mock) both PASS —
    # the only reason a re-fetch should happen is the session-calendar
    # gate flagging the in-data last_bar as stale.
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-01-07",
        cached_at=cached_at,
    )

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        rows = pd.bdate_range(end="2025-01-08", periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": base + 0.5,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    # Freeze "now" to Wednesday 22:00 UTC (post-NYSE-close), past which
    # the Tue-2025-01-07 last bar is session-stale.
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            frozen = datetime(2025, 1, 8, 22, 0, tzinfo=UTC)
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(yfinance_provider, "datetime", _FrozenDatetime)

    chunk = yfinance_provider.get_yf_recent_history(_TICKER, period="1y")

    assert fetch_calls == [_TICKER], (
        "session-stale artifact should have triggered an upstream re-fetch"
    )
    assert not chunk.frame.empty


def test_get_yf_recent_history_serves_cache_when_session_fresh(isolated_cache, monkeypatch):
    """During the trading session — before today's expected close — the
    artifact is fresh by session-calendar and must NOT trigger a fetch."""
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-01-07",
        cached_at=cached_at,
    )

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        return pd.DataFrame()

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    # Wed 16:00 UTC = 11:00 ET — pre-NYSE-close; today's bar not yet
    # expected upstream, so Tue's bar in the artifact is still fresh.
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            frozen = datetime(2025, 1, 8, 16, 0, tzinfo=UTC)
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(yfinance_provider, "datetime", _FrozenDatetime)

    chunk = yfinance_provider.get_yf_recent_history(_TICKER, period="1y")

    assert fetch_calls == [], "pre-close cache hit must not re-fetch"
    assert not chunk.frame.empty


# --- Fix 2: holiday-loop sentinel --------------------------------------------


def _freeze_yfinance_now(monkeypatch, frozen_utc: datetime) -> None:
    """Pin ``yfinance.datetime.now`` to a fixed UTC instant."""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return frozen_utc.replace(tzinfo=None)
            return frozen_utc.astimezone(tz)

    monkeypatch.setattr(yfinance_provider, "datetime", _FrozenDatetime)


def test_holiday_sentinel_short_circuits_repeat_refetch(isolated_cache, monkeypatch):
    """On a market holiday the first auto-stale fetch returns the same
    bar; a sentinel must then be written so subsequent reads serve cache
    instead of re-fetching on every call across the long weekend."""
    # Pre-write artifact: Friday's last bar, wall-clock TTL fresh.
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-07-03",  # Thu (US Independence Day is Fri 7/4)
        cached_at=cached_at,
    )

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        # Upstream still has the same last bar — no new session printed.
        rows = pd.bdate_range(end="2025-07-03", periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": base + 0.5,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    # Saturday July 5 18:00 UTC — well past Friday's NYSE close.
    _freeze_yfinance_now(monkeypatch, datetime(2025, 7, 5, 18, 0, tzinfo=UTC))

    # First call: auto-stale → re-fetch → same last_bar → sentinel written.
    yfinance_provider._get_yf_full(_TICKER)
    assert fetch_calls == [_TICKER]

    # Verify sentinel landed in meta.json.
    artifact_dir = isolated_cache / "yfinance_v2" / _TICKER.lower() / "full"
    meta = json.loads((artifact_dir / "meta.json").read_text())
    assert "last_session_check_at" in meta

    # Second call within the TTL window — sentinel must short-circuit,
    # NO re-fetch. Advance "now" by 1 hour to make sure the check covers
    # the original expected close.
    _freeze_yfinance_now(monkeypatch, datetime(2025, 7, 5, 19, 0, tzinfo=UTC))
    yfinance_provider._get_yf_full(_TICKER)
    assert fetch_calls == [_TICKER], (
        "sentinel must short-circuit the holiday re-fetch loop"
    )


def test_holiday_sentinel_does_not_short_circuit_past_next_close(
    isolated_cache, monkeypatch
):
    """Sentinel only covers expected closes at-or-before its timestamp.
    Once a NEW expected close has passed since the sentinel was written,
    the staleness check must fire again."""
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-07-03",
        cached_at=cached_at,
    )

    # Pre-stamp a sentinel claiming we already verified at Saturday noon UTC.
    artifact_dir = isolated_cache / "yfinance_v2" / _TICKER.lower() / "full"
    meta_path = artifact_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["last_session_check_at"] = datetime(2025, 7, 5, 12, 0, tzinfo=UTC).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        rows = pd.bdate_range(end="2025-07-07", periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": base + 0.5,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)

    # Tuesday July 8 22:00 UTC — Monday's and Tuesday's closes have both
    # passed since the recorded sentinel. Must re-fetch.
    _freeze_yfinance_now(monkeypatch, datetime(2025, 7, 8, 22, 0, tzinfo=UTC))
    yfinance_provider._get_yf_full(_TICKER)
    assert fetch_calls == [_TICKER], (
        "sentinel must NOT cover expected closes after its timestamp"
    )


# --- Fix 4: _get_yf_full / get_yf_data session-stale gate --------------------


def test_get_yf_data_refetches_when_session_stale(isolated_cache, monkeypatch):
    """``get_yf_data`` (the path ``ChartComponent`` and indicators use)
    must honor the session-aware staleness gate, not just the 24h TTL."""
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-01-07",
        cached_at=cached_at,
    )

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        rows = pd.bdate_range(end="2025-01-08", periods=400)
        base = np.arange(len(rows), dtype=float) + 100.0
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1,
                "Low": base - 1,
                "Close": base + 0.5,
                "Volume": (base * 1000).astype(float),
            },
            index=rows,
        )

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)
    _freeze_yfinance_now(monkeypatch, datetime(2025, 1, 8, 22, 0, tzinfo=UTC))

    frame = yfinance_provider.get_yf_data(_TICKER)
    assert fetch_calls == [_TICKER], (
        "get_yf_data must promote to force_refresh when session-stale"
    )
    assert not frame.empty


def test_get_yf_data_serves_cache_when_session_fresh(isolated_cache, monkeypatch):
    """Pre-close: the session-stale gate must NOT trigger a fetch."""
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-01-07",
        cached_at=cached_at,
    )

    fetch_calls: list[str] = []

    def fake_download(ticker, *, period):
        fetch_calls.append(ticker)
        return pd.DataFrame()

    monkeypatch.setattr(yfinance_provider, "_download_frame", fake_download)
    _freeze_yfinance_now(monkeypatch, datetime(2025, 1, 8, 16, 0, tzinfo=UTC))

    frame = yfinance_provider.get_yf_data(_TICKER)
    assert fetch_calls == [], "pre-close call must not re-fetch via get_yf_data"
    assert not frame.empty


# --- Subtle: -stale source_version tag ---------------------------------------


def test_stale_fallback_marks_source_version(isolated_cache, monkeypatch):
    """When the auto-stale fetch fails and we serve the cached chunk, the
    returned ``source_version`` must be distinguishable from a clean cache hit."""
    cached_at = datetime.now(UTC) - timedelta(hours=2)
    _write_synthetic_artifact(
        isolated_cache,
        last_bar_date="2025-01-07",
        cached_at=cached_at,
    )

    def boom(ticker, *, period):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(yfinance_provider, "_download_frame", boom)
    _freeze_yfinance_now(monkeypatch, datetime(2025, 1, 8, 22, 0, tzinfo=UTC))

    chunk = yfinance_provider.get_yf_recent_history(_TICKER, period="1y")

    assert chunk.source_version == "managed-artifact-tail-stale"
    assert not chunk.frame.empty
