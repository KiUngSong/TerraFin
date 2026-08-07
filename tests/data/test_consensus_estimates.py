"""Tests for the forward consensus-estimate provider and contract."""

import json

import pandas as pd
import pytest

from TerraFin.data.contracts.estimates import ConsensusEstimates, PeriodEstimate, PriceTargets, RevisionCounts
from TerraFin.data.providers.market import estimates as estimates_module


def _eps_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "avg": [1.97, 2.90, 8.79, 9.54],
            "low": [1.93, 2.51, 8.28, 8.24],
            "high": [2.04, 3.42, 8.92, 10.67],
            "yearAgoEps": [1.85, 2.84, 7.45, 8.79],
            "numberOfAnalysts": [28, 23, 38, 41],
            "growth": [0.0678, 0.0243, 0.1796, 0.0851],
            "currency": ["USD"] * 4,
        },
        index=["0q", "+1q", "0y", "+1y"],
    )


def _revisions_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "upLast7days": [3, 2, 0, 2],
            "upLast30days": [4, 5, 5, 7],
            "downLast30days": [2, 0, 2, 1],
            "downLast7Days": [0, 0, 1, 0],
            "currency": ["USD"] * 4,
        },
        index=["0q", "+1q", "0y", "+1y"],
    )


def _recommendations_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": ["0m", "-1m"],
            "strongBuy": [6, 6],
            "buy": [21, 22],
            "hold": [14, 14],
            "sell": [2, 2],
            "strongSell": [3, 2],
        }
    )


@pytest.fixture()
def raw_payload(monkeypatch) -> dict:
    """The normalised payload `_fetch_raw` produces, without touching network."""

    class _FakeTicker:
        earnings_estimate = _eps_frame()
        revenue_estimate = _eps_frame()
        eps_revisions = _revisions_frame()
        analyst_price_targets = {"current": 309.38, "high": 400.0, "low": 215.0, "mean": 320.889, "median": 330.0}
        recommendations = _recommendations_frame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _FakeTicker())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)
    return estimates_module._fetch_raw("AAPL")


def test_fetch_payload_is_json_serialisable(raw_payload) -> None:
    """Regression: the cache persists dict payloads as JSON.

    A pandas DataFrame left in the payload is written out as its str() repr and
    silently loses every value, so the warm-cache read returns empty estimates
    while the cold read looks fine.
    """

    round_tripped = json.loads(json.dumps(raw_payload))

    assert round_tripped == raw_payload, "payload must survive a JSON round-trip unchanged"
    assert isinstance(round_tripped["eps"], dict)
    assert isinstance(round_tripped["recommendations"], list)


def test_shape_survives_the_cache_round_trip(raw_payload) -> None:
    direct = estimates_module._shape("AAPL", raw_payload, "2026-08-05")
    cached = estimates_module._shape("AAPL", json.loads(json.dumps(raw_payload)), "2026-08-05")

    assert direct == cached
    assert cached.currency == "USD"
    assert [r.period for r in cached.revisions] == ["0q", "+1q", "0y", "+1y"]
    assert cached.eps[2].avg == pytest.approx(8.79)


def test_revision_direction_and_net(raw_payload) -> None:
    shaped = estimates_module._shape("AAPL", raw_payload, "2026-08-05")

    by_period = {item.period: item for item in shaped.revisions}
    assert by_period["0q"].net_30d == 2
    assert by_period["0q"].direction_30d == "up"
    assert by_period["+1q"].net_30d == 5


def test_missing_surface_is_warned_not_fatal(monkeypatch) -> None:
    class _PartialTicker:
        earnings_estimate = _eps_frame()

        @property
        def revenue_estimate(self):
            raise RuntimeError("upstream blocked")

        eps_revisions = _revisions_frame()
        analyst_price_targets = {}
        recommendations = _recommendations_frame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _PartialTicker())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    shaped = estimates_module._shape("AAPL", estimates_module._fetch_raw("AAPL"), "2026-08-05")

    assert shaped.eps, "the surface that worked must still be returned"
    assert not shaped.revenue
    assert any("revenue_estimate" in warning for warning in shaped.warnings)
    assert shaped.has_coverage is True


def test_no_coverage_reports_false_rather_than_raising() -> None:
    empty = ConsensusEstimates.make_empty("^GSPC", "2026-08-05")

    assert empty.has_coverage is False
    assert empty.price_targets.upside_to_mean_pct is None


def test_dispersion_and_upside_maths() -> None:
    estimate = PeriodEstimate(period="0y", avg=10.0, low=8.0, high=12.0)
    assert estimate.dispersion == pytest.approx(0.4)

    assert PeriodEstimate(period="0y", avg=None, low=1.0, high=2.0).dispersion is None
    assert PeriodEstimate(period="0y", avg=0.0, low=1.0, high=2.0).dispersion is None

    assert PriceTargets(current=100.0, mean=120.0).upside_to_mean_pct == pytest.approx(20.0)
    assert PriceTargets(current=None, mean=120.0).upside_to_mean_pct is None
    assert PriceTargets(current=0.0, mean=120.0).upside_to_mean_pct is None


def test_revision_counts_tolerate_missing_values() -> None:
    assert RevisionCounts(period="0q").net_30d is None
    assert RevisionCounts(period="0q").direction_30d is None
    assert RevisionCounts(period="0q", up_30d=0, down_30d=0).direction_30d == "flat"
    assert RevisionCounts(period="0q", up_30d=1).net_30d == 1


def test_blank_ticker_is_rejected() -> None:
    with pytest.raises(ValueError, match="Ticker is required"):
        estimates_module.get_consensus_estimates("   ")


def _all_empty_yfinance(monkeypatch) -> None:
    """Every surface empty — what yfinance returns for a 404/429 or a non-equity.

    It runs with hide_exceptions=True, so nothing raises and the per-surface
    handler never fires.
    """

    import pandas as pd

    class _SilentlyEmptyTicker:
        earnings_estimate = pd.DataFrame()
        revenue_estimate = pd.DataFrame()
        eps_revisions = pd.DataFrame()
        analyst_price_targets: dict = {}
        recommendations = pd.DataFrame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _SilentlyEmptyTicker())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)


def test_all_empty_always_raises_and_is_never_cached(monkeypatch) -> None:
    """An all-empty upstream response is ambiguous, so it must not be cached.

    Two earlier attempts tried to disambiguate with a probe. Both used endpoints
    that stay up when the estimate endpoint is down — `valid_ticker` (v8 chart)
    and `get_ticker_info` (which falls back to the chart AND search endpoints by
    design) — so neither could detect the outage, and the wrong verdict was
    pinned for the full 24h TTL. Raising is the only honest option.
    """

    _all_empty_yfinance(monkeypatch)

    with pytest.raises(estimates_module.EstimatesUnavailableError, match="indistinguishable"):
        estimates_module._fetch_raw("AAPL")


def test_all_empty_raises_regardless_of_instrument_type(monkeypatch) -> None:
    """Even for an index: the quote type cannot confirm the estimates are absent."""

    _all_empty_yfinance(monkeypatch)

    import TerraFin.data.providers.market.ticker_info as ticker_info_module

    monkeypatch.setattr(ticker_info_module, "get_ticker_info", lambda ticker: {"quoteType": "INDEX"})

    with pytest.raises(estimates_module.EstimatesUnavailableError):
        estimates_module._fetch_raw("^GSPC")


def test_quote_type_hint_is_attached_but_only_as_a_hint(monkeypatch) -> None:
    import TerraFin.data.providers.market.ticker_info as ticker_info_module

    monkeypatch.setattr(ticker_info_module, "get_ticker_info", lambda ticker: {"quoteType": "etf"})

    assert estimates_module._quote_type_hint("SPY") == "ETF"

    def explode(ticker):
        raise TimeoutError("probe down")

    monkeypatch.setattr(ticker_info_module, "get_ticker_info", explode)
    assert estimates_module._quote_type_hint("SPY") is None, "a hint must never fail the fetch"


def test_partially_empty_estimate_surfaces_are_warned(monkeypatch) -> None:
    """Targets responded but every estimate surface is empty — say so, don't stay silent."""

    import pandas as pd

    class _TargetsOnly:
        earnings_estimate = pd.DataFrame()
        revenue_estimate = pd.DataFrame()
        eps_revisions = pd.DataFrame()
        analyst_price_targets = {"current": 180.0}
        recommendations = pd.DataFrame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _TargetsOnly())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    raw = estimates_module._fetch_raw("NVDA")

    assert raw["estimatesMissing"] is True
    assert any("every estimate surface" in warning for warning in raw["warnings"])


def test_one_missing_estimate_surface_is_warned(monkeypatch) -> None:
    """A partial failure must not pass silently just because one surface worked."""

    import pandas as pd

    class _NoRevisions:
        earnings_estimate = _eps_frame()
        revenue_estimate = _eps_frame()
        eps_revisions = pd.DataFrame()
        analyst_price_targets = {"current": 309.0, "mean": 330.0}
        recommendations = _recommendations_frame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _NoRevisions())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    raw = estimates_module._fetch_raw("AAPL")

    assert any("returned no data: revisions" in warning for warning in raw["warnings"])


def _revenue_frame() -> pd.DataFrame:
    """Revenue rows carry `yearAgoRevenue`, not `yearAgoEps`."""

    return pd.DataFrame(
        {
            "avg": [1.2e11, 1.3e11, 4.2e11, 4.6e11],
            "low": [1.1e11, 1.2e11, 4.0e11, 4.3e11],
            "high": [1.3e11, 1.4e11, 4.4e11, 4.9e11],
            "numberOfAnalysts": [25, 22, 30, 28],
            "yearAgoRevenue": [1.0e11, 1.1e11, 3.9e11, 4.2e11],
            "growth": [0.15, 0.12, 0.08, 0.09],
            "currency": ["USD"] * 4,
        },
        index=["0q", "+1q", "0y", "+1y"],
    )


def test_revenue_maps_year_ago_revenue_not_year_ago_eps(monkeypatch) -> None:
    """The two surfaces use different year-ago column names.

    The main fixture reuses the EPS frame for revenue, which would hide a
    mis-mapping because `yearAgoRevenue` would simply be absent.
    """

    class _Ticker:
        earnings_estimate = _eps_frame()
        revenue_estimate = _revenue_frame()
        eps_revisions = _revisions_frame()
        analyst_price_targets: dict = {}
        recommendations = _recommendations_frame()

    fake_yf = type("_FakeYF", (), {"Ticker": staticmethod(lambda ticker: _Ticker())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    shaped = estimates_module._shape("AAPL", estimates_module._fetch_raw("AAPL"), "2026-08-05")

    by_period = {item.period: item for item in shaped.revenue}
    assert by_period["0y"].year_ago == pytest.approx(3.9e11)
    assert by_period["0y"].avg == pytest.approx(4.2e11)
    # EPS still maps its own column.
    assert {item.period: item.year_ago for item in shaped.eps}["0y"] == pytest.approx(7.45)


def test_as_of_comes_from_the_cached_fetch_date(monkeypatch) -> None:
    """`CachePayloadResult` has no timestamp, so the fetch date rides in the payload."""

    from types import SimpleNamespace

    class _FakeManager:
        _payload_specs: dict = {}

        def register_payload(self, spec) -> None:
            type(self)._payload_specs[spec.source] = spec

        def get_payload(self, source, **kwargs):
            return SimpleNamespace(
                payload={"fetchedAt": "2026-07-01", "eps": {"0y": {"avg": 5.0}}},
                freshness="fresh",
                error=None,
            )

    monkeypatch.setattr(estimates_module, "_manager", lambda: _FakeManager())

    result = estimates_module.get_consensus_estimates("aapl")

    assert result.ticker == "AAPL"
    assert result.as_of == "2026-07-01", "as_of must be the fetch date, not today"
    assert result.warnings == ()


def test_non_fresh_cache_tier_is_surfaced(monkeypatch) -> None:
    from types import SimpleNamespace

    class _StaleManager:
        _payload_specs: dict = {}

        def register_payload(self, spec) -> None:
            type(self)._payload_specs[spec.source] = spec

        def get_payload(self, source, **kwargs):
            return SimpleNamespace(
                payload={"fetchedAt": "2026-06-01", "eps": {"0y": {"avg": 5.0}}},
                freshness="stale",
                error=None,
            )

    monkeypatch.setattr(estimates_module, "_manager", lambda: _StaleManager())

    result = estimates_module.get_consensus_estimates("AAPL")

    assert result.cache_tier == "stale", "tier is a field, not a warning string"
    assert result.upstream_failed is False, "a stale copy is not a failure"
    assert result.as_of == "2026-06-01", "the stale tier must report the original vintage"


@pytest.fixture(autouse=True)
def _clear_empty_memo():
    """The observation memo is module-level; leaving it set leaks between tests."""

    estimates_module.clear_empty_memo()
    yield
    estimates_module.clear_empty_memo()


def _fallback_manager(calls: list[str]):
    """A manager that always lands on the fallback tier, counting invocations."""

    from types import SimpleNamespace

    class _Manager:
        _payload_specs: dict = {}

        def register_payload(self, spec) -> None:
            type(self)._payload_specs[spec.source] = spec

        def get_payload(self, source, **kwargs):
            calls.append(source)
            return SimpleNamespace(
                payload={"warnings": ["estimates upstream returned nothing"], "upstreamFailed": True},
                freshness="fallback",
                error=None,
            )

    return _Manager()


def test_an_all_empty_observation_is_remembered_so_repeat_calls_are_cheap(monkeypatch) -> None:
    """Never cached, but remembered: an index queried ten times must not refetch ten times.

    Not caching the result at all was correct on epistemics and wrong on cost —
    every call re-hit five quoteSummary endpoints for the most-queried symbols.
    """

    calls: list[str] = []
    monkeypatch.setattr(estimates_module, "_manager", lambda: _fallback_manager(calls))
    monkeypatch.setattr(estimates_module, "_quote_type_hint", lambda ticker: "INDEX")

    first = estimates_module.get_consensus_estimates("SPY")
    second = estimates_module.get_consensus_estimates("SPY")

    assert len(calls) == 1, "the second call must be served from the observation memo"
    assert first.upstream_failed and second.upstream_failed
    assert second.quote_type_hint == "INDEX"
    assert any("not retried" in warning for warning in second.warnings)
    assert any("force_refresh" in warning for warning in second.warnings)


def test_force_refresh_bypasses_the_observation_memo(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(estimates_module, "_manager", lambda: _fallback_manager(calls))
    monkeypatch.setattr(estimates_module, "_quote_type_hint", lambda ticker: None)

    estimates_module.get_consensus_estimates("SPY")
    estimates_module.get_consensus_estimates("SPY", force_refresh=True)

    assert len(calls) == 2, "force_refresh must always reach upstream"


def test_the_observation_memo_expires(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(estimates_module, "_manager", lambda: _fallback_manager(calls))
    monkeypatch.setattr(estimates_module, "_quote_type_hint", lambda ticker: None)

    estimates_module.get_consensus_estimates("SPY")

    with estimates_module._memo_mutex:
        deadline, observed = estimates_module._empty_observations["SPY"]
        estimates_module._empty_observations["SPY"] = (deadline - 9999, observed)

    estimates_module.get_consensus_estimates("SPY")

    assert len(calls) == 2, "an expired observation must allow a real retry"


def test_the_observation_memo_is_per_ticker(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(estimates_module, "_manager", lambda: _fallback_manager(calls))
    monkeypatch.setattr(estimates_module, "_quote_type_hint", lambda ticker: None)

    estimates_module.get_consensus_estimates("SPY")
    estimates_module.get_consensus_estimates("QQQ")

    assert len(calls) == 2, "one symbol's emptiness says nothing about another's"
