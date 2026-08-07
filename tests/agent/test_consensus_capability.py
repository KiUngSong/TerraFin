"""Tests for the `consensus` capability handler."""

import pytest

from TerraFin.agent.service import TerraFinAgentService
from TerraFin.data.contracts.estimates import (
    ConsensusEstimates,
    PeriodEstimate,
    PriceTargets,
    RevisionCounts,
)


class _FakeFactory:
    def __init__(self, estimates: ConsensusEstimates) -> None:
        self._estimates = estimates

    def get_consensus_estimates(self, ticker: str, *, force_refresh: bool = False) -> ConsensusEstimates:
        return self._estimates


def _covered() -> ConsensusEstimates:
    return ConsensusEstimates(
        ticker="AAPL",
        as_of="2026-08-05",
        currency="USD",
        eps=(PeriodEstimate(period="0y", avg=10.0, low=8.0, high=12.0, analyst_count=38, growth=0.18),),
        revenue=(PeriodEstimate(period="0y", avg=4.2e11, analyst_count=30),),
        revisions=(RevisionCounts(period="0y", up_7d=2, down_7d=1, up_30d=5, down_30d=2),),
        price_targets=PriceTargets(current=100.0, mean=120.0, median=118.0, low=90.0, high=150.0),
        recommendations=({"period": "0m", "strongBuy": 6, "buy": 21, "hold": 14, "sell": 2, "strongSell": 3},),
    )


def test_consensus_exposes_revision_direction() -> None:
    service = TerraFinAgentService(data_factory=_FakeFactory(_covered()))

    payload = service.consensus("aapl")

    assert payload["hasCoverage"] is True
    assert payload["currency"] == "USD"
    revision = payload["revisions"][0]
    assert revision["net30d"] == 3
    assert revision["direction30d"] == "up"
    assert payload["processing"]["sourceVersion"] == "consensus-estimates"


def test_consensus_computes_dispersion_and_upside() -> None:
    service = TerraFinAgentService(data_factory=_FakeFactory(_covered()))

    payload = service.consensus("AAPL")

    assert payload["epsEstimates"][0]["dispersion"] == pytest.approx(0.4)
    assert payload["priceTargets"]["upsideToMeanPct"] == pytest.approx(20.0)


def test_all_empty_upstream_describes_the_ambiguity_with_a_hint() -> None:
    """The dangerous case: an empty response must not become a verdict.

    Earlier versions asserted either "no analyst coverage" or "not an equity —
    normal for indices", both of which are confident falsehoods when the estimate
    endpoint is merely rate-limited.
    """

    ambiguous = ConsensusEstimates(
        ticker="^GSPC",
        as_of="",
        upstream_failed=True,
        quote_type_hint="INDEX",
        cache_tier="fallback",
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(ambiguous))

    payload = service.consensus("^GSPC")
    joined = " ".join(payload["warnings"])

    assert payload["quoteTypeHint"] == "INDEX"
    assert "evidence of neither" in joined
    assert "hint only" in joined, "the instrument type must be labelled as a hint"
    assert "INDEX" in joined


def test_hint_is_omitted_when_unknown() -> None:
    ambiguous = ConsensusEstimates(
        ticker="ZZZZ", as_of="", upstream_failed=True, cache_tier="fallback"
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(ambiguous))

    joined = " ".join(service.consensus("ZZZZ")["warnings"])

    assert "evidence of neither" in joined
    assert "hint only" not in joined


def test_quote_without_estimates_asserts_neither_way() -> None:
    """Partial failure and an uncovered equity are indistinguishable — say so."""

    partial = ConsensusEstimates(
        ticker="NVDA",
        as_of="2026-08-05",
        price_targets=PriceTargets(current=180.0),
        estimates_missing=True,
        cache_tier="fresh",
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(partial))

    payload = service.consensus("NVDA")

    joined = " ".join(payload["warnings"])
    assert "evidence of neither" in joined
    assert "no analyst-estimate data" not in joined


def test_benign_cache_note_does_not_suppress_the_coverage_message() -> None:
    """A stale tier must not be mistaken for a failure.

    The earlier gate keyed off "is `warnings` non-empty", so any benign note
    silently swallowed the real explanation.
    """

    stale_index = ConsensusEstimates(
        ticker="^GSPC", as_of="2026-08-01", estimates_missing=True, cache_tier="stale"
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(stale_index))

    payload = service.consensus("^GSPC")

    joined = " ".join(payload["warnings"])
    assert "cache tier: stale" in joined
    assert "evidence of neither" in joined
    assert "no estimate data was returned at all" not in joined


def test_provider_warnings_are_passed_through() -> None:
    degraded = ConsensusEstimates(
        ticker="AAPL",
        as_of="2026-08-05",
        eps=(PeriodEstimate(period="0y", avg=10.0),),
        warnings=("revenue_estimate unavailable",),
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(degraded))

    payload = service.consensus("AAPL")

    assert "revenue_estimate unavailable" in payload["warnings"]
    assert payload["hasCoverage"] is True


def test_upstream_failure_is_not_reported_as_absent_coverage() -> None:
    """The distinction matters: "no analysts cover NVDA" is a confident wrong answer.

    An upstream failure and a genuinely uncovered symbol both arrive as an empty
    contract, so the no-coverage claim is only made when nothing else went wrong.
    """

    degraded = ConsensusEstimates(
        ticker="NVDA",
        as_of="",
        upstream_failed=True,
        cache_tier="fallback",
        warnings=("estimates upstream unavailable",),
    )
    service = TerraFinAgentService(data_factory=_FakeFactory(degraded))

    payload = service.consensus("NVDA")

    assert payload["hasCoverage"] is False
    joined = " ".join(payload["warnings"])
    assert "evidence of neither" in joined
    assert "no analyst coverage" not in joined, "an outage must never be stated as absent coverage"
    assert "normal for indices and ETFs) or an upstream failure" in joined


def test_unexplained_emptiness_falls_back_to_unavailable() -> None:
    """No flag set at all: say the reason is unknown rather than guess one."""

    bare = ConsensusEstimates(ticker="XYZ", as_of="2026-08-05", cache_tier="fresh")
    service = TerraFinAgentService(data_factory=_FakeFactory(bare))

    joined = " ".join(service.consensus("XYZ")["warnings"])

    assert "could not be determined" in joined
    assert "did not succeed" not in joined
    assert "no analyst-estimate data" not in joined
