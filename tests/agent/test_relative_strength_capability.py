"""Tests for the `relative_strength` universe-ranking capability.

The price fan-out is stubbed: a live run fetches one history per universe
member (~500 for sp500), which is a background-task workload, not a unit test.
"""

import pytest

from TerraFin.agent.service import TerraFinAgentService
from TerraFin.analytics.factors import universe_prices


def _rising(step: float, length: int = 400) -> list[float]:
    """Monotonic series; a bigger `step` means stronger relative strength."""

    return [100.0 + step * i for i in range(length)]


@pytest.fixture(autouse=True)
def _stub_universe(monkeypatch):
    prices = {
        "AAA": _rising(1.0),
        "BBB": _rising(0.5),
        "CCC": _rising(0.1),
        "SHORT": _rising(1.0, length=10),  # too little history to rank
    }
    monkeypatch.setattr(universe_prices, "universe_symbols", lambda universe: list(prices))
    monkeypatch.setattr(
        universe_prices,
        "fetch_closes_detailed",
        lambda symbols, **kwargs: ({s: prices[s] for s in symbols if s in prices}, []),
    )
    return prices


@pytest.fixture()
def service() -> TerraFinAgentService:
    return TerraFinAgentService()


def test_leaderboard_is_ordered_strongest_first(service) -> None:
    payload = service.relative_strength(universe="sp500", top_n=3)

    symbols = [row["symbol"] for row in payload["results"]]
    assert symbols == ["AAA", "BBB", "CCC"]
    assert [row["rank"] for row in payload["results"]] == [1, 2, 3]
    assert payload["results"][0]["rsRating"] >= payload["results"][-1]["rsRating"]
    assert payload["processing"]["sourceVersion"] == "relative-strength"


def test_top_n_limits_the_leaderboard(service) -> None:
    payload = service.relative_strength(top_n=2)

    assert len(payload["results"]) == 2


def test_coverage_reports_unrankable_members(service) -> None:
    payload = service.relative_strength()

    assert payload["universeSize"] == 4, "every requested member counts toward coverage"
    assert payload["ranked"] == 3, "SHORT lacks the ~253 sessions the RS blend needs"


def test_single_ticker_returns_only_that_row(service) -> None:
    payload = service.relative_strength("BBB")

    assert payload["ticker"] == "BBB"
    assert [row["symbol"] for row in payload["results"]] == ["BBB"]
    assert payload["results"][0]["rank"] == 2
    assert payload["results"][0]["momentum12m1"] is not None


def test_ticker_is_normalised_and_may_sit_outside_the_universe(service, monkeypatch) -> None:
    outsider = _rising(2.0)
    monkeypatch.setattr(
        universe_prices,
        "fetch_closes_detailed",
        lambda symbols, **kwargs: (
            {s: (outsider if s == "ZZZ" else _rising(0.5)) for s in symbols},
            [],
        ),
    )

    payload = service.relative_strength("zzz")

    assert payload["ticker"] == "ZZZ"
    assert payload["universeSize"] == 4, "universeSize describes the universe, not the request"
    assert payload["results"][0]["symbol"] == "ZZZ"
    assert "not a sp500 member" in payload["results"][0]["note"]


def test_unrankable_ticker_is_warned_not_raised(service) -> None:
    payload = service.relative_strength("SHORT")

    assert payload["results"] == []
    assert any("too little history" in warning for warning in payload["warnings"])


def test_empty_universe_returns_a_warning(service, monkeypatch) -> None:
    monkeypatch.setattr(universe_prices, "fetch_closes_detailed", lambda symbols, **kwargs: ({}, []))

    payload = service.relative_strength()

    assert payload["ranked"] == 0
    assert payload["results"] == []
    assert payload["warnings"]
