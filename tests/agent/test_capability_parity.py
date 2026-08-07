"""Parity checks between the capability registry and its downstream surfaces.

`src/TerraFin/agent/runtime/capability.py` is the single source of truth for the
agent capability surface. Three things must stay in step with it, and each one
otherwise fails only at runtime (or silently, in generated docs):

* every capability needs a `HOSTED_TOOL_CONTRACTS` entry, because the tool
  adapter looks one up for each registered capability when listing tools
* every capability that declares an `http_route_path` needs that route to exist,
  since HTTP-only agents depend on the parity route
* declared metadata (`summary`, `response_model_name`) must be populated and the
  response model must actually exist somewhere in the package

These tests are deliberately derived from the registry rather than hardcoded, so
adding a capability requires no edit here.
"""

import ast
import pathlib

import pytest
from fakes import BaseFakeService, fake_chart_opener

from TerraFin.agent.contracts.tool_contracts import HOSTED_TOOL_CONTRACTS
from TerraFin.agent.runtime import build_default_capability_registry


# Hosted-only tools live outside the capability registry: the three guru
# consults and `current_view_context` need a live session, so they are wired
# straight into the tool adapter instead.
HOSTED_ONLY_TOOLS = frozenset(
    {
        "consult_warren_buffett",
        "consult_howard_marks",
        "consult_stanley_druckenmiller",
        "current_view_context",
    }
)

# `open_chart` mutates hosted session state and has no stateless HTTP surface.
CAPABILITIES_WITHOUT_ROUTE = frozenset({"open_chart"})

# `open_chart` is handed the injected `chart_opener` callable rather than a
# `TerraFinAgentService` method, so its handler name never matches the
# capability name.
CAPABILITIES_WITH_INJECTED_HANDLER = frozenset({"open_chart"})

# `patterns` declares `cli_subcommand_name="patterns"` but no such subparser is
# wired in `agent/cli/main.py`, so `terrafin-agent patterns` does not exist.
# Grandfathered to keep the invariant enforceable for everything else — fix by
# either wiring the subcommand or dropping the declaration, then delete this.
CAPABILITIES_WITH_UNWIRED_CLI = frozenset({"patterns"})

_SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "TerraFin"


@pytest.fixture(scope="module")
def capabilities():
    registry = build_default_capability_registry(BaseFakeService(), chart_opener=fake_chart_opener)
    return registry.list()


@pytest.fixture(scope="module")
def real_capabilities():
    """Registry built against the REAL service *and* the real chart opener.

    Signature checks must not measure a double. `BaseFakeService`'s stubs are
    narrower than the handlers they stand in for, so a declared property the real
    handler accepts (e.g. `market_snapshot`'s `force_refresh`) would read as a
    mismatch. `fake_chart_opener` has the opposite problem: it is *wider* than
    production `open_chart`, whose `client` parameter is undeclared and went
    undetected here. Passing no `chart_opener` binds the real one.

    Nothing is called — the handlers are only inspected — so this stays free of
    network and env mutation.
    """

    from TerraFin.agent.service import TerraFinAgentService

    registry = build_default_capability_registry(TerraFinAgentService())
    return registry.list()


@pytest.fixture(scope="module")
def live_route_paths() -> set[str | None]:
    """Paths served by the assembled app.

    Module-scoped because `create_app()` is not side-effect free: it loads the
    repo `.env` into `os.environ`, resets chart/calendar module state, and
    builds process-wide singletons. Build it once here rather than per test.
    """

    from TerraFin.interface.server import create_app

    return {getattr(route, "path", None) for route in create_app().routes}


def _declared_class_names() -> set[str]:
    """Collect every class name defined under src/TerraFin without importing it."""

    names: set[str] = set()
    for path in _SRC_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        names.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    return names


def test_every_capability_has_a_tool_contract(capabilities) -> None:
    missing = sorted(c.name for c in capabilities if c.name not in HOSTED_TOOL_CONTRACTS)
    assert not missing, (
        "capabilities registered without a HOSTED_TOOL_CONTRACTS entry "
        f"(tool listing would raise KeyError): {missing}"
    )


def test_every_tool_contract_is_registered_or_hosted_only(capabilities) -> None:
    registered = {c.name for c in capabilities}
    orphans = sorted(set(HOSTED_TOOL_CONTRACTS) - registered - HOSTED_ONLY_TOOLS)
    assert not orphans, f"tool contracts with no registered capability and no hosted-only exemption: {orphans}"


def test_every_capability_declares_generator_metadata(capabilities) -> None:
    missing_summary = sorted(c.name for c in capabilities if not c.summary)
    assert not missing_summary, f"capabilities missing `summary`: {missing_summary}"

    missing_model = sorted(c.name for c in capabilities if not c.response_model_name)
    assert not missing_model, f"capabilities missing `response_model_name`: {missing_model}"

    missing_route_path = sorted(
        c.name for c in capabilities if not c.http_route_path and c.name not in CAPABILITIES_WITHOUT_ROUTE
    )
    assert not missing_route_path, f"capabilities missing `http_route_path`: {missing_route_path}"


def test_declared_response_models_exist(capabilities) -> None:
    """Weak existence check: the name matches *some* class under src/TerraFin.

    Response models are spread across agent contracts, data contracts, private
    provider models, and page route modules, so this only catches an outright
    typo. `test_response_model_names_match_tool_contracts` is the strict check.
    """

    declared = _declared_class_names()
    unresolved = sorted(
        f"{c.name} -> {c.response_model_name}"
        for c in capabilities
        if c.response_model_name and c.response_model_name not in declared
    )
    assert not unresolved, f"`response_model_name` values with no matching class under src/TerraFin: {unresolved}"


def test_response_model_names_match_tool_contracts(capabilities) -> None:
    """The registry and the tool contract declare the same response model.

    `HOSTED_TOOL_CONTRACTS[name]["response_model"]` is shipped to the model as
    tool metadata, so a disagreement between the two declarations sends the LLM
    a response shape that does not match the route's.
    """

    mismatches = sorted(
        f"{c.name}: registry={c.response_model_name!r} contract={HOSTED_TOOL_CONTRACTS[c.name].get('response_model')!r}"
        for c in capabilities
        if c.name in HOSTED_TOOL_CONTRACTS
        and HOSTED_TOOL_CONTRACTS[c.name].get("response_model") != c.response_model_name
    )
    assert not mismatches, f"registry / tool-contract response_model disagreement: {mismatches}"


def test_every_capability_handler_binds_on_the_real_service() -> None:
    """Guard the one thing the shared stub cannot catch.

    `BaseFakeService.__getattr__` resolves any attribute, so a capability whose
    handler names a method the real `TerraFinAgentService` does not implement
    (a typo, or a handler added before its service method) passes every
    stub-backed test. Building the registry against the real service is the
    check that fails loudly, and it is cheap: no network, no env mutation.
    """

    from TerraFin.agent.service import TerraFinAgentService

    registry = build_default_capability_registry(TerraFinAgentService(), chart_opener=fake_chart_opener)

    mislabelled = sorted(
        f"{c.name} -> {getattr(c.handler, '__name__', repr(c.handler))}"
        for c in registry.list()
        if c.name not in CAPABILITIES_WITH_INJECTED_HANDLER
        and getattr(c.handler, "__name__", None) not in (c.name, None)
    )
    assert not mislabelled, (
        "capability handlers bound to a differently-named service method "
        f"(likely a copy-paste error): {mislabelled}"
    )


def test_declared_cli_subcommands_are_wired(capabilities) -> None:
    """A declared `cli_subcommand_name` must exist as an argparse subparser.

    The CLI dispatches through `TerraFinAgentClient` methods, so most newer
    capabilities deliberately declare no CLI name at all. Declaring one that is
    not wired advertises a command that fails.
    """

    import re

    cli_source = (_SRC_ROOT / "agent" / "cli" / "main.py").read_text(encoding="utf-8")
    wired = set(re.findall(r"add_parser\(\"([a-z0-9\-]+)\"", cli_source))

    unwired = sorted(
        f"{c.name} -> {c.cli_subcommand_name}"
        for c in capabilities
        if c.cli_subcommand_name
        and c.cli_subcommand_name not in wired
        and c.name not in CAPABILITIES_WITH_UNWIRED_CLI
    )
    assert not unwired, f"capabilities declaring a CLI subcommand that is not wired: {unwired}"


# Handler parameters deliberately NOT in the tool schema. Each entry is a
# decision, not an oversight, and the tool boundary rejects them (see
# `tests/agent/test_tool_argument_validation.py`):
#   valuation  — the three tilt inputs. An LLM that can set its own growth rate,
#                terminal growth, or beta can make a DCF agree with whatever it
#                already believed, which is the failure the locked-DCF rule in
#                the idea-loop design exists to prevent.
#   macro_focus, open_chart — `session_id` is injected by the runtime
#                (`_apply_defaults`), never supplied by a caller.
#   open_chart — `client` is the `TerraFinAgentClient` the CLI passes in-process;
#                a model naming its own HTTP client makes no sense.
INTERNAL_ONLY_HANDLER_PARAMS = {
    "valuation": {"base_growth_pct", "terminal_growth_pct", "beta"},
    "macro_focus": {"session_id"},
    "open_chart": {"session_id", "client"},
}


def test_no_new_undeclared_handler_parameters(real_capabilities) -> None:
    """A handler parameter absent from the tool schema must be a deliberate choice.

    Adding one silently widens what the model could reach if validation were ever
    bypassed, so new ones have to be named here on purpose.
    """

    import inspect

    surprises: dict[str, list[str]] = {}
    for capability in real_capabilities:
        contract = HOSTED_TOOL_CONTRACTS.get(capability.name)
        if contract is None:
            continue
        declared = set((contract.get("input_schema") or {}).get("properties") or {})
        try:
            parameters = inspect.signature(capability.handler).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        accepted = {
            name
            for name, parameter in parameters.items()
            if parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
        }
        undeclared = accepted - declared - INTERNAL_ONLY_HANDLER_PARAMS.get(capability.name, set())
        if undeclared:
            surprises[capability.name] = sorted(undeclared)

    assert not surprises, (
        "handler parameters that are not in the tool schema and not listed as "
        f"deliberately internal: {surprises}"
    )


def test_declared_properties_are_acceptable_by_the_handler(real_capabilities) -> None:
    """A declared property the handler cannot take is a TypeError waiting to happen."""

    import inspect

    broken: dict[str, list[str]] = {}
    for capability in real_capabilities:
        contract = HOSTED_TOOL_CONTRACTS.get(capability.name)
        if contract is None:
            continue
        declared = set((contract.get("input_schema") or {}).get("properties") or {})
        try:
            parameters = inspect.signature(capability.handler).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        if any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()):
            continue
        missing = sorted(declared - set(parameters))
        if missing:
            broken[capability.name] = missing

    assert not broken, f"schema declares properties the handler cannot accept: {broken}"


def test_declared_http_routes_exist(capabilities, live_route_paths) -> None:
    missing = sorted(
        f"{c.name} -> {c.http_route_path}"
        for c in capabilities
        if c.http_route_path and c.http_route_path not in live_route_paths
    )
    assert not missing, f"capabilities whose declared http_route_path has no live route: {missing}"
