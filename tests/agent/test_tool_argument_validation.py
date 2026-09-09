"""Argument validation at the tool boundary.

The declared `input_schema` used to be advisory: dispatch went straight from the
model's arguments to `capability.handler(**kwargs)`, so `additionalProperties:
False` enforced nothing and every undeclared handler parameter stayed reachable
from the agent. `valuation` is the case that matters — its hidden
`base_growth_pct` / `terminal_growth_pct` / `beta` let a caller tilt a valuation
toward a conclusion it already held, which is exactly what the locked-DCF rule
in the idea-loop design exists to prevent.
"""

import pytest

from TerraFin.agent.contracts.tool_contracts import validate_tool_arguments


def _problems(tool_name: str, arguments: dict) -> list[str]:
    """Just the problem list. `validate_tool_arguments` also returns the narrowed
    arguments to dispatch; the tests that care about narrowing read it directly."""

    return validate_tool_arguments(tool_name, arguments)[0]


def test_valid_arguments_pass() -> None:
    assert _problems("valuation", {"ticker": "AAPL", "projection_years": 10}) == []
    assert _problems("market_data", {"name": "AAPL", "depth": "full"}) == []


def test_undeclared_valuation_tilt_parameters_are_rejected() -> None:
    """The whole point: these exist on the handler but not in the schema."""

    for hidden in ("base_growth_pct", "terminal_growth_pct", "beta"):
        problems = _problems("valuation", {"ticker": "AAPL", hidden: 42})
        assert problems, f"{hidden} must not be reachable through the tool surface"
        assert hidden in problems[0]


def test_missing_required_argument_is_reported() -> None:
    assert _problems("valuation", {}) == ["ticker: required"]


def test_enum_violation_is_reported() -> None:
    problems = _problems("market_data", {"name": "AAPL", "depth": "everything"})

    assert len(problems) == 1
    assert "not one of" in problems[0]


def test_numeric_bounds_are_enforced() -> None:
    assert _problems("pattern_scan", {"limit": 1001})
    assert _problems("pattern_scan", {"limit": 0})
    assert _problems("pattern_scan", {"limit": 200}) == []


def test_integral_floats_are_narrowed_not_merely_accepted() -> None:
    """Models routinely emit 200.0 for an integer field; 200.5 is a real error.

    Accepting 200.0 without narrowing it to `int` only relocates the failure:
    once the matches outnumber the limit the handler reaches `matched[:limit]`
    and raises `TypeError: slice indices must be integers`, which no classifier
    recognises, so the run aborts instead of returning a tool error. Worse for
    being conditional — it depends on how many matches the scan found. The
    narrowed value is the contract.
    """

    problems, normalized = validate_tool_arguments("pattern_scan", {"limit": 200.0})
    assert problems == []
    assert normalized["limit"] == 200
    assert isinstance(normalized["limit"], int)

    assert _problems("pattern_scan", {"limit": 200.5})


def test_narrowing_leaves_other_arguments_untouched() -> None:
    _, normalized = validate_tool_arguments(
        "pattern_scan", {"limit": 200.0, "severity_min": "medium", "period": "6mo"}
    )

    assert normalized == {"limit": 200, "severity_min": "medium", "period": "6mo"}


def test_booleans_are_not_integers_or_strings() -> None:
    """bool is an int subclass in Python; JSON booleans are neither."""

    assert _problems("pattern_scan", {"limit": True})
    assert _problems("valuation", {"ticker": True})


def test_string_or_array_unions_accept_both_forms() -> None:
    assert _problems("pattern_scan", {"tickers": "NVDA,AMD"}) == []
    assert _problems("pattern_scan", {"tickers": ["NVDA", "AMD"]}) == []
    assert _problems("pattern_scan", {"tickers": 123})


def test_array_bounds_and_item_types_name_the_actual_problem() -> None:
    """A union branch must not report the value's own type back at the model.

    `tickers` is `anyOf: [string, array]`. Reporting "expected string or array,
    got list" for an over-long list is unactionable — the value *is* a list — so
    the model resends it, hits the same error fingerprint, and burns the retry
    budget. Assert the wording, not mere truthiness.
    """

    too_many = _problems("pattern_scan", {"tickers": ["X"] * 501})
    assert too_many == ["tickers: at most 500 item(s), got 501"]

    bad_item = _problems("pattern_scan", {"tickers": ["NVDA", 7]})
    assert bad_item == ["tickers[1]: expected string, got int"]

    # No branch matches on type, so the generic union message is the right one.
    assert _problems("pattern_scan", {"tickers": 123}) == [
        "tickers: expected string or array, got int"
    ]


def test_minimum_length_is_enforced() -> None:
    assert _problems("valuation", {"ticker": ""})


def test_optional_nulls_are_left_to_the_handler() -> None:
    """An omitted-as-null optional is common from models and is not a schema error."""

    assert _problems("news", {"ticker": "NVDA", "query": None}) == []


def test_a_null_required_argument_is_rejected() -> None:
    """`{"ticker": None}` satisfies "key is present" but not the handler.

    `service.valuation` calls `ticker.upper()`, so a null that passes validation
    becomes an `AttributeError` the classifier does not recognise, aborting the
    run. Absent and null are different errors, and both are errors.
    """

    assert _problems("valuation", {"ticker": None}) == ["ticker: required, but was null"]
    assert _problems("valuation", {}) == ["ticker: required"]


def test_unknown_tool_validates_vacuously() -> None:
    """An unregistered tool is a different error, reported elsewhere."""

    assert _problems("not_a_tool", {"anything": 1}) == []


@pytest.mark.parametrize("tool_name", ["consensus", "news", "pattern_scan"])
def test_unknown_arguments_are_rejected_for_every_recent_tool(tool_name: str) -> None:
    problems = _problems(tool_name, {"definitely_not_a_field": 1})

    # Not problems[0]: a missing required argument is reported first for tools
    # that have one.
    assert any("unknown argument" in problem for problem in problems), problems


def _adapter_and_session():
    """A tool adapter over the real registry with a stub service.

    Mirrors `tests/agent/test_tools.py::_adapter` — the runtime needs the service
    as well as the registry, and the session id lives at
    `session.session.session_id`.
    """

    from fakes import BaseFakeService, fake_chart_opener

    from TerraFin.agent.contracts.definitions import DEFAULT_HOSTED_AGENT_NAME
    from TerraFin.agent.runtime import build_default_capability_registry
    from TerraFin.agent.runtime.hosted import TerraFinHostedAgentRuntime
    from TerraFin.agent.tools import TerraFinHostedToolAdapter

    service = BaseFakeService()
    registry = build_default_capability_registry(service, chart_opener=fake_chart_opener)
    runtime = TerraFinHostedAgentRuntime(service=service, capability_registry=registry)
    adapter = TerraFinHostedToolAdapter(runtime)
    session = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="tool:schema")
    return adapter, session.session.session_id


@pytest.mark.parametrize("tool_name", ["valuation", "start_valuation_task"])
def test_tool_path_rejects_a_hidden_valuation_parameter(tool_name: str) -> None:
    """End to end: the schema is enforced on BOTH surfaces the model can call.

    `start_valuation_task` is the case that regressed. Validation keyed on
    `tool.name`, and the task variant is named `start_valuation_task`, which is not
    a `HOSTED_TOOL_CONTRACTS` key — so it validated vacuously and the tilt
    parameters stayed reachable through the exact capability this check protects.
    Every backgroundable capability had the same hole.
    """

    adapter, session_id = _adapter_and_session()

    result = adapter.run_tool(session_id, tool_name, {"ticker": "AAPL", "base_growth_pct": 40})

    assert result.is_error is True
    assert result.error_code == "tool_invalid_arguments"
    assert "base_growth_pct" in result.error_message
    assert result.payload["accepted"] is False
    assert result.payload["error"]["retryable"] is True
    assert "not available through the tool surface" in result.payload["error"]["modelHint"]


def test_every_exposed_tool_validates_against_a_contract() -> None:
    """No tool the model is handed may fall through validation.

    The task-variant bypass was invisible because the tests only ever exercised
    invoke-mode names. This asserts the property directly, over the full tool list
    the default agent actually sees, so a future execution mode with a new name
    shape cannot reintroduce it silently.
    """

    from TerraFin.agent.contracts.definitions import DEFAULT_HOSTED_AGENT_NAME
    from TerraFin.agent.contracts.tool_contracts import HOSTED_TOOL_CONTRACTS

    adapter, _ = _adapter_and_session()
    tools = adapter.list_tools_for_agent(DEFAULT_HOSTED_AGENT_NAME)

    assert len(tools) > 40, "expected the full tool surface, not a filtered subset"
    unvalidated = sorted(t.name for t in tools if t.capability_name not in HOSTED_TOOL_CONTRACTS)
    assert not unvalidated, f"tools whose arguments no contract constrains: {unvalidated}"


def test_task_variants_still_start_with_valid_arguments() -> None:
    """The D1 fix must reject the undeclared argument, not the whole task path."""

    adapter, session_id = _adapter_and_session()

    result = adapter.run_tool(session_id, "start_valuation_task", {"ticker": "AAPL"})

    assert result.is_error is False
    assert result.payload["accepted"] is True
    assert result.task is not None
    assert result.task.input_payload["ticker"] == "AAPL"


def test_tool_path_still_accepts_declared_arguments() -> None:
    adapter, session_id = _adapter_and_session()

    result = adapter.run_tool(session_id, "valuation", {"ticker": "AAPL", "projection_years": 10})

    assert result.is_error is False
    assert result.payload["ticker"] == "AAPL"


def test_internal_callers_keep_the_full_signature() -> None:
    """Locking the agent must not lock a route or controller.

    The service method deliberately still accepts the tilt parameters — a
    deliberate internal caller is trusted; the model is not.
    """

    import inspect

    from TerraFin.agent.service import TerraFinAgentService

    parameters = inspect.signature(TerraFinAgentService.valuation).parameters

    for hidden in ("base_growth_pct", "terminal_growth_pct", "beta"):
        assert hidden in parameters
