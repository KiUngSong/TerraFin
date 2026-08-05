import pytest
from fakes import BaseFakeService as _FakeService
from fakes import fake_chart_opener as _fake_chart_opener

import TerraFin.agent.runtime as agent_runtime


class _ExplodingService(_FakeService):
    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, object]:
        _ = name, depth, view
        raise RuntimeError("snapshot failed")


# Capabilities that must always be present. Membership is asserted rather than
# an exact ordered tuple so that adding a capability does not require editing
# this list; `test_default_capability_registry_ordering_convention` covers the
# grouping rule that ordering is actually meant to express.
KERNEL_CAPABILITIES = frozenset(
    {
        "resolve",
        "market_data",
        "indicators",
        "patterns",
        "market_snapshot",
        "lppl_analysis",
        "company_info",
        "earnings",
        "financials",
        "portfolio",
        "economic",
        "macro_focus",
        "calendar_events",
        "fear_greed",
        "sp500_dcf",
        "beta_estimate",
        "fcf_history",
        "similarity_search",
        "top_companies",
        "market_regime",
        "trailing_forward_pe",
        "market_breadth",
        "watchlist",
        "open_chart",
        "fundamental_screen",
        "risk_profile",
        "valuation",
        "sec_filings",
        "sec_filing_document",
        "sec_filing_section",
    }
)


def _registry_names() -> tuple[str, ...]:
    registry = agent_runtime.build_default_capability_registry(_FakeService(), chart_opener=_fake_chart_opener)
    return registry.names()


def test_default_capability_registry_contains_kernel_capabilities() -> None:
    names = _registry_names()

    missing = KERNEL_CAPABILITIES - set(names)
    assert not missing, f"kernel capabilities missing from the registry: {sorted(missing)}"
    assert len(names) == len(set(names)), "registry contains duplicate capability names"


def test_default_capability_registry_ordering_convention() -> None:
    """Registry order groups research read-only, then chart-opening, then SEC filings."""

    names = _registry_names()
    sec_positions = [index for index, name in enumerate(names) if name.startswith("sec_")]

    assert sec_positions, "expected SEC filing capabilities in the registry"
    assert sec_positions == list(
        range(sec_positions[0], sec_positions[-1] + 1)
    ), f"SEC filing capabilities must stay contiguous, got positions {sec_positions}"
    assert names.index("open_chart") < sec_positions[0], "`open_chart` must precede the SEC filing group"


def test_context_call_records_focus_and_capability_history() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    payload = context.call("market_snapshot", name="AAPL", depth="auto", view="weekly")

    assert payload["ticker"] == "AAPL"
    snapshot = context.session.snapshot()
    assert snapshot.focus_items == ("AAPL",)
    assert len(snapshot.capability_calls) == 1
    assert snapshot.capability_calls[0].capability_name == "market_snapshot"
    assert "processing" in snapshot.capability_calls[0].output_keys


def test_context_call_records_chart_artifact() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    payload = context.call("open_chart", data_or_names=["AAPL", "MSFT"], session_id="agent:test-chart")

    assert payload["ok"] is True
    snapshot = context.session.snapshot()
    assert snapshot.focus_items == ("AAPL", "MSFT")
    assert len(snapshot.artifacts) == 1
    artifact = snapshot.artifacts[0]
    assert artifact.kind == "chart"
    assert artifact.artifact_id == "agent:test-chart"
    assert artifact.title == "Chart: AAPL, MSFT"


def test_run_task_completes_and_persists_result() -> None:
    context = agent_runtime.create_agent_context(
        service=_FakeService(),
        chart_opener=_fake_chart_opener,
    )

    task, result = context.run_task("company_info", ticker="MSFT", description="load company profile")

    assert result["ticker"] == "MSFT"
    assert task.status == "completed"
    stored = context.task_registry.get(task.task_id)
    assert stored.status == "completed"
    assert stored.result is not None
    assert stored.result["ticker"] == "MSFT"


def test_run_task_marks_failure_when_capability_raises() -> None:
    context = agent_runtime.create_agent_context(
        service=_ExplodingService(),
        chart_opener=_fake_chart_opener,
    )

    with pytest.raises(RuntimeError, match="snapshot failed"):
        context.run_task("market_snapshot", name="NVDA")

    tasks = context.task_registry.list()
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert tasks[0].error == "snapshot failed"
