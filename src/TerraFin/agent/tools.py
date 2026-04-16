from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from TerraFin.interface.market_insights.payloads import canonical_macro_name, resolve_macro_type
from TerraFin.interface.stock.payloads import resolve_ticker_query

from .definitions import TerraFinAgentDefinition
from .hosted_runtime import (
    TerraFinAgentApprovalRequiredError,
    TerraFinHostedAgentRuntime,
)
from .runtime import TerraFinCapability, TerraFinTaskRecord
from .tool_contracts import HOSTED_TOOL_CONTRACT_VERSION, get_hosted_tool_contract


ToolExecutionMode = Literal["invoke", "task"]


@dataclass(frozen=True, slots=True)
class TerraFinToolDefinition:
    name: str
    capability_name: str
    description: str
    input_schema: dict[str, Any]
    execution_mode: ToolExecutionMode = "invoke"
    side_effecting: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_function_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True, slots=True)
class TerraFinToolInvocationResult:
    tool_name: str
    capability_name: str
    session_id: str
    execution_mode: ToolExecutionMode
    payload: dict[str, Any]
    task: TerraFinTaskRecord | None = None
    is_error: bool = False
    retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class _ToolErrorDisposition:
    code: str
    message: str
    retryable: bool
    expose_to_user: bool
    model_hint: str | None = None


class TerraFinHostedToolAdapter:
    def __init__(self, runtime: TerraFinHostedAgentRuntime) -> None:
        self.runtime = runtime

    def list_tools_for_agent(self, agent_name: str) -> tuple[TerraFinToolDefinition, ...]:
        definition = self.runtime.get_agent_definition(agent_name)
        return self._tools_for_definition(definition)

    def list_tools_for_session(self, session_id: str) -> tuple[TerraFinToolDefinition, ...]:
        definition = self.runtime.get_session_definition(session_id)
        return self._tools_for_definition(definition)

    def list_function_tools_for_agent(self, agent_name: str) -> list[dict[str, Any]]:
        return [tool.as_function_tool() for tool in self.list_tools_for_agent(agent_name)]

    def list_function_tools_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [tool.as_function_tool() for tool in self.list_tools_for_session(session_id)]

    def get_tool_for_agent(self, agent_name: str, tool_name: str) -> TerraFinToolDefinition:
        tools = {tool.name: tool for tool in self.list_tools_for_agent(agent_name)}
        try:
            return tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown TerraFin hosted tool '{tool_name}' for agent '{agent_name}'.") from exc

    def run_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> TerraFinToolInvocationResult:
        tool = self._get_tool_for_session(session_id, tool_name)
        payload: dict[str, Any]
        task: TerraFinTaskRecord | None = None
        resolved_arguments = _normalize_common_alias_arguments(dict(arguments or {}))
        preflight_result = self._preflight_tool_misuse(tool, session_id, resolved_arguments)
        if preflight_result is not None:
            return preflight_result
        try:
            if tool.name == "current_view_context":
                payload = self.runtime.read_linked_view_context(
                    session_id,
                    view_context_id=_optional_string(resolved_arguments.get("viewContextId")),
                )
            elif tool.execution_mode == "task":
                task = self.runtime.start_task(session_id, tool.capability_name, **resolved_arguments)
                payload = {
                    "accepted": True,
                    "taskId": task.task_id,
                    "status": task.status,
                }
            else:
                payload = self.runtime.invoke(session_id, tool.capability_name, **resolved_arguments)
        except TerraFinAgentApprovalRequiredError as exc:
            payload = {
                "accepted": False,
                "approvalRequired": True,
                "approval": {
                    "approvalId": exc.approval.approval_id,
                    "status": exc.approval.status,
                    "action": exc.approval.action,
                    "capabilityName": exc.approval.capability_name,
                    "toolName": exc.approval.tool_name,
                    "reason": exc.approval.reason,
                },
            }
        except Exception as exc:
            retried_arguments = self._repair_retryable_arguments(tool, resolved_arguments, exc)
            if retried_arguments is None:
                disposition = self._classify_tool_error(tool, resolved_arguments, exc)
                if disposition is None or disposition.expose_to_user:
                    raise
                return TerraFinToolInvocationResult(
                    tool_name=tool.name,
                    capability_name=tool.capability_name,
                    session_id=session_id,
                    execution_mode=tool.execution_mode,
                    payload={
                        "accepted": False,
                        "error": {
                            "code": disposition.code,
                            "message": disposition.message,
                            "detail": str(exc),
                            "retryable": disposition.retryable,
                            "modelHint": disposition.model_hint,
                        },
                    },
                    task=None,
                    is_error=True,
                    retryable=disposition.retryable,
                    error_code=disposition.code,
                    error_message=disposition.message,
                )
            if tool.name == "current_view_context":
                payload = self.runtime.read_linked_view_context(
                    session_id,
                    view_context_id=_optional_string(retried_arguments.get("viewContextId")),
                )
            elif tool.execution_mode == "task":
                task = self.runtime.start_task(session_id, tool.capability_name, **retried_arguments)
                payload = {
                    "accepted": True,
                    "taskId": task.task_id,
                    "status": task.status,
                }
            else:
                payload = self.runtime.invoke(session_id, tool.capability_name, **retried_arguments)
        return TerraFinToolInvocationResult(
            tool_name=tool.name,
            capability_name=tool.capability_name,
            session_id=session_id,
            execution_mode=tool.execution_mode,
            payload=payload,
            task=task,
        )

    def _get_tool_for_session(self, session_id: str, tool_name: str) -> TerraFinToolDefinition:
        tools = {tool.name: tool for tool in self.list_tools_for_session(session_id)}
        try:
            return tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown TerraFin hosted tool '{tool_name}' for session '{session_id}'.") from exc

    def _tools_for_definition(self, definition: TerraFinAgentDefinition) -> tuple[TerraFinToolDefinition, ...]:
        tools: list[TerraFinToolDefinition] = []
        for capability in self.runtime.capability_registry.list():
            if not definition.allows(capability.name):
                continue
            if capability.name == "open_chart" and not definition.chart_access:
                continue
            tools.append(self._build_tool_definition(capability, execution_mode="invoke"))
            if definition.allow_background_tasks and capability.backgroundable:
                tools.append(self._build_tool_definition(capability, execution_mode="task"))
        tools.append(self._build_current_view_context_tool())
        return tuple(tools)

    def _preflight_tool_misuse(
        self,
        tool: TerraFinToolDefinition,
        session_id: str,
        arguments: Mapping[str, Any],
    ) -> TerraFinToolInvocationResult | None:
        business_only_tools = {"company_info", "earnings", "financials", "fundamental_screen"}
        if tool.capability_name not in business_only_tools:
            return None

        requested_value = _optional_string(arguments.get("ticker")) or _optional_string(arguments.get("name"))
        if not _looks_like_equity_index_or_etf(requested_value):
            return None

        message = (
            "This tool expects an operating-business ticker, not a broad equity benchmark or ETF shell. "
            "Use market_snapshot, market_data, risk_profile, or valuation for SPY/QQQ/DIA/VT-style market questions."
        )
        return TerraFinToolInvocationResult(
            tool_name=tool.name,
            capability_name=tool.capability_name,
            session_id=session_id,
            execution_mode=tool.execution_mode,
            payload={
                "accepted": False,
                "error": {
                    "code": "tool_wrong_equity_benchmark_analysis",
                    "message": message,
                    "detail": requested_value,
                    "retryable": True,
                    "modelHint": (
                        "Do not use company_info, earnings, financials, or fundamental_screen on SPY, QQQ, DIA, VT, "
                        "or similar market-benchmark ETFs. Retry with market_snapshot, market_data, risk_profile, "
                        "or valuation depending on the question."
                    ),
                },
            },
            task=None,
            is_error=True,
            retryable=True,
            error_code="tool_wrong_equity_benchmark_analysis",
            error_message=message,
        )

    def _build_tool_definition(
        self,
        capability: TerraFinCapability,
        *,
        execution_mode: ToolExecutionMode,
    ) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract(capability.name)
        description = capability.description
        tool_name = capability.name
        if execution_mode == "task":
            tool_name = f"start_{capability.name}_task"
            description = f"Start a background TerraFin task for: {capability.description}"

        return TerraFinToolDefinition(
            name=tool_name,
            capability_name=capability.name,
            description=description,
            input_schema=contract["input_schema"],
            execution_mode=execution_mode,
            side_effecting=capability.side_effecting or execution_mode == "task",
            metadata={
                "backgroundable": capability.backgroundable,
                "capabilityName": capability.name,
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

    def _build_current_view_context_tool(self) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract("current_view_context")
        return TerraFinToolDefinition(
            name="current_view_context",
            capability_name="current_view_context",
            description=(
                "Read the user's current TerraFin page/view context when the request depends on "
                "what they are looking at right now. Do not use unless the request is view-dependent."
            ),
            input_schema=contract["input_schema"],
            execution_mode="invoke",
            side_effecting=False,
            metadata={
                "backgroundable": False,
                "capabilityName": "current_view_context",
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

    def _repair_retryable_arguments(
        self,
        tool: TerraFinToolDefinition,
        arguments: Mapping[str, Any],
        error: Exception,
    ) -> dict[str, Any] | None:
        message = str(error or "")
        if not any(
            marker in message
            for marker in (
                "Invalid ticker:",
                "No data found for",
                "Unknown macro instrument:",
            )
        ):
            return None

        repaired = dict(arguments)
        if "name" in repaired:
            value = _optional_string(repaired.get("name"))
            if tool.name == "macro_focus":
                fixed = _repair_macro_focus_name(value)
            else:
                fixed = _repair_symbol_or_name(value, allow_macro=True)
            if fixed and fixed != value:
                repaired["name"] = fixed
                return repaired
        if "ticker" in repaired:
            value = _optional_string(repaired.get("ticker"))
            fixed = _repair_symbol_or_name(value, allow_macro=False)
            if fixed and fixed != value:
                repaired["ticker"] = fixed
                return repaired
        return None

    def _classify_tool_error(
        self,
        tool: TerraFinToolDefinition,
        arguments: Mapping[str, Any],
        error: Exception,
    ) -> _ToolErrorDisposition | None:
        message = str(error or "").strip()
        lowered = message.lower()

        fatal_markers = (
            "rate limit",
            "quota",
            "too many requests",
            "api key",
            "invalid api key",
            "authentication",
            "unauthorized",
            "forbidden",
            "credential",
            "401",
            "403",
            "429",
        )
        if any(marker in lowered for marker in fatal_markers):
            return _ToolErrorDisposition(
                code="upstream_auth_or_quota_error",
                message=message or "The upstream API rejected the request.",
                retryable=False,
                expose_to_user=True,
            )

        name_value = _optional_string(arguments.get("name"))
        ticker_value = _optional_string(arguments.get("ticker"))
        requested_value = name_value or ticker_value or ""
        generic_phrase = (
            "looks like a descriptive phrase rather than a ticker or supported macro instrument."
            if _looks_like_descriptive_phrase(requested_value)
            else "could not be resolved to a valid ticker or supported macro instrument."
        )

        if tool.name == "macro_focus" and _looks_like_equity_index_or_etf(requested_value):
            return _ToolErrorDisposition(
                code="tool_wrong_market_tool",
                message=(
                    "The requested name looks like an equity index or ETF rather than a macro instrument. "
                    "Use market_snapshot, market_data, risk_profile, or valuation for SPY/QQQ/DIA/VT-style benchmarks."
                ),
                retryable=True,
                expose_to_user=False,
                model_hint=(
                    "Do not call `macro_focus` on SPY, QQQ, DIA, VT, or other equity benchmarks. "
                    "Use `market_snapshot`, `market_data`, `risk_profile`, or `valuation` for equity-index questions. "
                    "Reserve `macro_focus` for macro instruments like VIX, DXY, Fear & Greed, Treasury-10Y, "
                    "Federal Funds Effective Rate, M2, or SOMA."
                ),
            )

        recoverable_markers = (
            "invalid ticker:",
            "no data found for",
            "unknown macro instrument:",
            "unknown instrument:",
            "not found for ticker",
        )
        if any(marker in lowered for marker in recoverable_markers):
            if tool.name == "macro_focus":
                model_hint = (
                    "Retry `macro_focus` only with a supported macro instrument such as VIX, DXY, Fear & Greed, "
                    "Treasury-10Y, Federal Funds Effective Rate, M2, or SOMA. For SPY/QQQ/DIA/VT and other equity "
                    "benchmarks, use `market_snapshot`, `market_data`, or `risk_profile` instead."
                )
            else:
                model_hint = (
                    "If the user is asking about the page they are currently viewing, call "
                    "`current_view_context` first. Otherwise retry with a concrete ticker or supported "
                    "macro instrument instead of a descriptive phrase."
                )
            return _ToolErrorDisposition(
                code="tool_input_resolution_error",
                message=(
                    f"The requested symbol or market name {generic_phrase} "
                    "Retry with a concrete ticker or macro instrument, or inspect the current view first."
                ),
                retryable=True,
                expose_to_user=False,
                model_hint=model_hint,
            )

        validation_markers = (
            "missing required",
            "validation",
            "must be one of",
            "expected ",
        )
        if any(marker in lowered for marker in validation_markers):
            return _ToolErrorDisposition(
                code="tool_input_validation_error",
                message="The tool input was malformed. Retry with corrected arguments.",
                retryable=True,
                expose_to_user=False,
                model_hint="Correct the tool arguments and retry.",
            )
        return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_EQUITY_INDEX_ALIASES = {
    "spx": "SPY",
    "spx index": "SPY",
    "sp500": "SPY",
    "s&p 500": "SPY",
    "ndx": "QQQ",
    "ndx index": "QQQ",
    "nasdaq-100": "QQQ",
    "nasdaq 100": "QQQ",
    "djia": "DIA",
    "dji": "DIA",
    "dow jones industrial average": "DIA",
    "rty": "IWM",
}


def _normalize_common_alias_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)
    for key in ("name", "ticker"):
        value = normalized.get(key)
        if value is None:
            continue
        alias = _EQUITY_INDEX_ALIASES.get(str(value).strip().casefold())
        if alias:
            normalized[key] = alias
    return normalized


def _repair_symbol_or_name(value: str | None, *, allow_macro: bool) -> str | None:
    if not value:
        return None
    alias = _EQUITY_INDEX_ALIASES.get(str(value).strip().casefold())
    if alias:
        return alias
    canonical = canonical_macro_name(value)
    if allow_macro and resolve_macro_type(canonical) is not None:
        return canonical
    resolved = resolve_ticker_query(value)
    resolved_type = str(resolved.get("type") or "").strip().lower()
    resolved_name = _optional_string(resolved.get("name"))
    if allow_macro and resolved_type == "macro" and resolved_name:
        return resolved_name
    if resolved_type == "stock" and resolved_name:
        return resolved_name
    return None


def _repair_macro_focus_name(value: str | None) -> str | None:
    if not value:
        return None
    canonical = canonical_macro_name(value)
    return canonical if resolve_macro_type(canonical) is not None else None


def _looks_like_equity_index_or_etf(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    normalized = text.casefold()
    if normalized in _EQUITY_INDEX_ALIASES:
        return True
    if normalized in {
        "spy",
        "qqq",
        "dia",
        "vt",
        "iwm",
        "s&p 500",
        "nasdaq",
        "nasdaq 100",
        "dow",
        "dow jones",
        "dow jones industrial average",
        "russell 2000",
    }:
        return True
    try:
        resolved = resolve_ticker_query(text)
    except Exception:
        return False
    resolved_name = _optional_string(resolved.get("name"))
    return (resolved_name or "").upper() in {"SPY", "QQQ", "DIA", "VT", "IWM"}


def _looks_like_descriptive_phrase(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return " " in text
