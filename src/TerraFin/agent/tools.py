from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from TerraFin.interface.market_insights.payloads import canonical_macro_name, resolve_macro_type
from TerraFin.interface.stock.payloads import resolve_ticker_query

from .definitions import TerraFinAgentDefinition, is_internal_agent_definition
from .hosted_runtime import (
    TerraFinAgentApprovalRequiredError,
    TerraFinHostedAgentRuntime,
)
from .runtime import TerraFinCapability, TerraFinTaskRecord
from .tool_contracts import HOSTED_TOOL_CONTRACT_VERSION, get_hosted_tool_contract


if TYPE_CHECKING:
    from .loop import TerraFinHostedAgentLoop


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


_PERSONA_CONSULT_TOOLS = {
    "consult_warren_buffett": "warren-buffett",
    "consult_howard_marks": "howard-marks",
    "consult_stanley_druckenmiller": "stanley-druckenmiller",
}


class TerraFinHostedToolAdapter:
    def __init__(self, runtime: TerraFinHostedAgentRuntime) -> None:
        self.runtime = runtime
        # The loop reference is injected after loop construction because the
        # adapter and loop are mutually dependent: the loop owns the adapter;
        # the adapter needs the loop to dispatch `consult_<persona>` tools
        # (persona subagents are full model loops, which the top-level loop
        # runs). Plain session-scoped capability calls don't need the loop —
        # they go through `runtime.invoke`.
        self._loop: "TerraFinHostedAgentLoop | None" = None

    def attach_loop(self, loop: "TerraFinHostedAgentLoop") -> None:
        self._loop = loop

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
            elif tool.name in _PERSONA_CONSULT_TOOLS:
                if self._loop is None:
                    raise RuntimeError(
                        "Tool adapter has no loop reference; consult_<persona> "
                        "tools require `attach_loop(...)` to have been called "
                        "after loop construction."
                    )
                guru_name = _PERSONA_CONSULT_TOOLS[tool.name]
                question = _optional_string(resolved_arguments.get("question")) or ""
                if not question:
                    raise ValueError(
                        f"{tool.name} requires a non-empty `question` argument."
                    )
                payload = self._loop.consult_guru(session_id, guru_name, question)
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
        # Persona-consult tools — only the user-facing orchestrator gets
        # them. Persona subagents themselves (hiddenInternal guru roles)
        # must not recurse through consult_* onto each other, so they are
        # filtered out by `is_internal_agent_definition`.
        if not is_internal_agent_definition(definition):
            tools.append(self._build_consult_warren_buffett_tool())
            tools.append(self._build_consult_howard_marks_tool())
            tools.append(self._build_consult_stanley_druckenmiller_tool())
        return tuple(tools)

    def _build_consult_warren_buffett_tool(self) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract("consult_warren_buffett")
        return TerraFinToolDefinition(
            name="consult_warren_buffett",
            capability_name="consult_warren_buffett",
            description=(
                "Consult the hidden Warren Buffett subagent for a business-quality / "
                "long-term-ownership lens. Best when the user asks about moats, "
                "competitive advantage, earnings power, capital allocation, intrinsic "
                "value under conservative assumptions, or whether a business is worth "
                "owning for the long run. Pass the specific question as `question`. "
                "Returns a structured memo with stance, confidence (0-100, "
                "self-reported by the persona agent based on evidence quality), "
                "thesis, key_evidence, risks, open_questions, citations. "
                "Call this alongside `consult_howard_marks` or "
                "`consult_stanley_druckenmiller` when the user explicitly asks for "
                "multiple investor perspectives."
            ),
            input_schema=contract["input_schema"],
            execution_mode="invoke",
            side_effecting=False,
            metadata={
                "backgroundable": False,
                "capabilityName": "consult_warren_buffett",
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

    def _build_consult_howard_marks_tool(self) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract("consult_howard_marks")
        return TerraFinToolDefinition(
            name="consult_howard_marks",
            capability_name="consult_howard_marks",
            description=(
                "Consult the hidden Howard Marks subagent for a cycle / "
                "risk-premium / second-level-thinking lens. Best when the user asks "
                "about downside risk, what's priced in, cycle position, bear cases, "
                "valuation sensitivity, or whether the market is complacent. "
                "Returns a structured memo (same schema as `consult_warren_buffett`). "
                "Complementary to Buffett for quality vs. price tension."
            ),
            input_schema=contract["input_schema"],
            execution_mode="invoke",
            side_effecting=False,
            metadata={
                "backgroundable": False,
                "capabilityName": "consult_howard_marks",
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

    def _build_consult_stanley_druckenmiller_tool(self) -> TerraFinToolDefinition:
        contract = get_hosted_tool_contract("consult_stanley_druckenmiller")
        return TerraFinToolDefinition(
            name="consult_stanley_druckenmiller",
            capability_name="consult_stanley_druckenmiller",
            description=(
                "Consult the hidden Stanley Druckenmiller subagent for a macro / "
                "liquidity / regime / momentum lens. Best when the user asks about "
                "Fed policy impact, rates higher-for-longer, risk-on/off regime, "
                "liquidity conditions, currency or commodity backdrop, or when an "
                "asset's fate depends more on the macro tape than on its own "
                "fundamentals. Returns a structured memo (same schema)."
            ),
            input_schema=contract["input_schema"],
            execution_mode="invoke",
            side_effecting=False,
            metadata={
                "backgroundable": False,
                "capabilityName": "consult_stanley_druckenmiller",
                "contractVersion": HOSTED_TOOL_CONTRACT_VERSION,
                "responseModel": contract["response_model"],
            },
        )

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
                "Read the user's current TerraFin page/view context. This is your ground-truth "
                "channel for what the user is actually looking at — the UI publishes the live "
                "ticker, filing, chart selection, and other on-screen entities here. Call this "
                "tool BEFORE asking the user to name a ticker or filing whenever their message "
                "refers to an entity deictically or implicitly (in any language) instead of "
                "naming it. Assume the user has a relevant page open until the tool tells you "
                "otherwise; asking 'which ticker?' when the answer is already in the view is a "
                "failure mode.\n"
                "If the user is viewing a SEC filing, `selection` will carry "
                "`{ticker, form, accession, primaryDocument, sectionSlug, sectionTitle, "
                "sectionExcerpt, documentUrl, indexUrl}`. Key rules:\n"
                "1. USE `selection.accession` AND `selection.primaryDocument` DIRECTLY (don't "
                "call `sec_filings` first) — the filing the user is viewing is already identified. "
                "But the `selection.sectionSlug` may be stale relative to the filing's current TOC "
                "(the browser cached it earlier). So the correct workflow when user asks about the "
                "in-view filing:\n"
                "   a. Call `sec_filing_document(ticker=selection.ticker, accession=selection.accession, "
                "primaryDocument=selection.primaryDocument, form=selection.form)` FIRST to get the "
                "current TOC.\n"
                "   b. Pick a `sectionSlug` from that TOC that matches the user's question. For "
                "earnings / revenue / MD&A / financial statements in a 10-K, prefer the LARGEST slug "
                "in Part II — 10-K parsers sometimes leave MD&A and Financial Statements inside an "
                "oversized neighbor slug (e.g. `item-6-reserved` with 200 KB of body).\n"
                "   c. Call `sec_filing_section(...)` with the TOC-sourced slug.\n"
                "If `selection.sectionSlug` exists AND the user's question is scoped to that exact "
                "section, you MAY skip step (a) and pass `selection.sectionSlug` directly — but on "
                "a 'section not found' error, always fall back to the TOC workflow above.\n"
                "2. The excerpt is only ~4 KB, usually a small slice of a much larger section "
                "(Item 1 Business in a 10-K is typically 100-200 KB). For any substantive question — "
                "business model, operations, strategy, risk factors, segment descriptions, etc. — "
                "ALWAYS call `sec_filing_section` to get the full body before answering. Writing a "
                "two-sentence summary off the excerpt alone is a UX failure.\n"
                "3. `documentUrl` and `indexUrl` are citation links, NOT places to send the user — "
                "they are ALREADY reading this filing in TerraFin's reader. Do NOT write 'you can "
                "view the filing here' or 'open on EDGAR for details' as a tail to your answer. "
                "Only mention an external link if the user explicitly asks for the source URL.\n"
                "4. Cross-filing pivots: if the user asks about content that lives in a *different* "
                "filing than the one in view (e.g. they're on a 10-Q but ask 'what is their business' — "
                "Item 1 Business is a 10-K section, not a 10-Q section), call `sec_filings(ticker)` "
                "ONCE to get the response, then read `filings_response.latestByForm['10-K']` to get "
                "the target filing's accession + primaryDocument directly. Do NOT scan the "
                "chronological `filings` array — 8-Ks cluster at the top and hide the 10-K/10-Q."
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

        # Missing section slug on `sec_filing_section` — the service
        # layer raises LookupError with a full slug list + explicit
        # retry instructions, but without this classifier branch the
        # error bubbles up with no `retryable=True` / `modelHint`
        # signal. The model then paraphrases the error and gives up
        # instead of reissuing the call with a valid slug. Surface it
        # as a retryable tool-input error so the loop retries and the
        # model sees a clear hint. The full slug list from the raised
        # message becomes the `modelHint`.
        if tool.name == "sec_filing_section" and "not found" in lowered and "slug" in lowered:
            requested_slug = _optional_string(arguments.get("sectionSlug"))
            return _ToolErrorDisposition(
                code="sec_filing_section_slug_not_found",
                message=(
                    f"The requested section slug "
                    f"{repr(requested_slug) if requested_slug else 'provided'} "
                    "is not in this filing's TOC. Retry with one of the slugs listed "
                    "in the error body."
                ),
                retryable=True,
                expose_to_user=False,
                model_hint=(
                    "DO NOT tell the user the section doesn't exist. The error body "
                    "contains the full TOC slug list with sizes. Pick ONE slug from "
                    "that list verbatim and call `sec_filing_section` again — "
                    "prefer the largest slug in Part II of a 10-K when the user "
                    "asked about earnings / revenue / MD&A / financial statements, "
                    "because 10-K parsers sometimes leave those sections buried "
                    "inside an oversized neighbor slug. Full error message for "
                    "reference:\n" + message
                ),
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
