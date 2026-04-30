from fastapi import APIRouter, HTTPException, Query

from TerraFin.agent.conversation import is_internal_only_message
from TerraFin.agent.conversation_state import RUNTIME_MODEL_METADATA_KEY
from TerraFin.agent.definitions import is_internal_agent_definition
from TerraFin.agent.hosted_runtime import (
    TerraFinAgentApprovalRequiredError,
    TerraFinAgentPolicyError,
    TerraFinAgentSessionConflictError,
)
from TerraFin.agent.hosted_service import get_hosted_agent_loop
from TerraFin.agent.loop import TerraFinConversationMessage, TerraFinHostedRunResult
from TerraFin.agent.model_runtime import TerraFinModelConfigError, TerraFinModelResponseError
from TerraFin.agent.models import (
    CalendarResponse,
    CompanyInfoResponse,
    EarningsResponse,
    EconomicResponse,
    FinancialStatementResponse,
    HostedAgentCatalogResponse,
    HostedAgentDefinitionResponse,
    HostedAgentMessageRequest,
    HostedAgentRunResponse,
    HostedAgentSessionCreateRequest,
    HostedAgentSessionDeleteResponse,
    HostedAgentSessionListResponse,
    HostedAgentSessionResponse,
    HostedAgentSessionSummaryResponse,
    HostedApprovalDecisionRequest,
    HostedApprovalListResponse,
    HostedApprovalResponse,
    HostedArtifactResponse,
    HostedCapabilityCallResponse,
    HostedConversationMessageResponse,
    HostedPermissionAuditResponse,
    HostedRuntimeModelResponse,
    HostedSessionPolicyResponse,
    HostedTaskListResponse,
    HostedTaskResponse,
    HostedTaskSummaryResponse,
    HostedToolDefinitionResponse,
    HostedToolInvocationResponse,
    HostedViewContextResponse,
    HostedViewContextUpdateRequest,
    IndicatorsResponse,
    LPPLAnalysisResponse,
    MacroFocusResponse,
    MarketDataResponse,
    MarketSnapshotResponse,
    PortfolioResponse,
    ResolveResponse,
)
from TerraFin.agent.openai_model import TerraFinOpenAIConfigError, TerraFinOpenAIResponseError
from TerraFin.agent.runtime import TerraFinArtifact, TerraFinCapabilityCall, TerraFinTaskRecord
from TerraFin.agent.service import TerraFinAgentService
from TerraFin.agent.session_store import (
    TerraFinHostedApprovalRequest,
    TerraFinHostedPermissionEvent,
    TerraFinHostedSessionRecord,
    TerraFinHostedViewContextRecord,
)
from TerraFin.agent.tools import TerraFinToolDefinition, TerraFinToolInvocationResult
from TerraFin.data import SecEdgarConfigurationError, SecEdgarUnavailableError
from TerraFin.interface.errors import AppRuntimeError


AGENT_API_PREFIX = "/agent/api"


def _raise_if_internal_agent_name(loop, agent_name: str) -> None:
    definition = loop.runtime.get_agent_definition(agent_name)
    if is_internal_agent_definition(definition):
        raise AppRuntimeError(
            "The requested hosted agent is internal-only.",
            code="hosted_agent_not_found",
            status_code=404,
        )


def _get_public_session_record(loop, session_id: str) -> TerraFinHostedSessionRecord:
    try:
        return loop.runtime.get_public_session_record(session_id)
    except KeyError as exc:
        raise AppRuntimeError(
            "The requested hosted session was not found.",
            code="hosted_session_not_found",
            status_code=404,
        ) from exc


def _message_response(message: TerraFinConversationMessage) -> HostedConversationMessageResponse:
    return HostedConversationMessageResponse(
        role=message.role,
        content=message.content,
        createdAt=message.created_at.isoformat(),
        name=message.name,
        toolCallId=message.tool_call_id,
        metadata=dict(message.metadata),
    )


def _tool_response(tool: TerraFinToolDefinition) -> HostedToolDefinitionResponse:
    return HostedToolDefinitionResponse(
        name=tool.name,
        capabilityName=tool.capability_name,
        description=tool.description,
        executionMode=tool.execution_mode,
        sideEffecting=tool.side_effecting,
        inputSchema=dict(tool.input_schema),
        metadata=dict(tool.metadata),
    )


def _artifact_response(artifact: TerraFinArtifact) -> HostedArtifactResponse:
    return HostedArtifactResponse(
        artifactId=artifact.artifact_id,
        kind=artifact.kind,
        title=artifact.title,
        capabilityName=artifact.capability_name,
        createdAt=artifact.created_at.isoformat(),
        payload=dict(artifact.payload),
    )


def _capability_call_response(call: TerraFinCapabilityCall) -> HostedCapabilityCallResponse:
    return HostedCapabilityCallResponse(
        capabilityName=call.capability_name,
        calledAt=call.called_at.isoformat(),
        inputs=dict(call.inputs),
        outputKeys=list(call.output_keys),
        focusItems=list(call.focus_items),
        artifactIds=list(call.artifact_ids),
    )


def _audit_response(event: TerraFinHostedPermissionEvent) -> HostedPermissionAuditResponse:
    return HostedPermissionAuditResponse(
        eventId=event.event_id,
        createdAt=event.created_at.isoformat(),
        action=event.action,
        capabilityName=event.capability_name,
        toolName=event.tool_name,
        sideEffecting=event.side_effecting,
        outcome=event.outcome,
        reason=event.reason,
        metadata=dict(event.metadata),
    )


def _approval_response(approval: TerraFinHostedApprovalRequest) -> HostedApprovalResponse:
    return HostedApprovalResponse(
        approvalId=approval.approval_id,
        createdAt=approval.created_at.isoformat(),
        updatedAt=approval.updated_at.isoformat(),
        resolvedAt=None if approval.resolved_at is None else approval.resolved_at.isoformat(),
        sessionId=approval.session_id,
        agentName=approval.agent_name,
        action=approval.action,
        capabilityName=approval.capability_name,
        toolName=approval.tool_name,
        sideEffecting=approval.side_effecting,
        status=approval.status,
        reason=approval.reason,
        inputPayload=dict(approval.input_payload),
        decisionNote=approval.decision_note,
        metadata=dict(approval.metadata),
    )


def _view_context_response(record: TerraFinHostedViewContextRecord) -> HostedViewContextResponse:
    return HostedViewContextResponse(
        contextId=record.context_id,
        createdAt=record.created_at.isoformat(),
        updatedAt=record.updated_at.isoformat(),
        route=record.route,
        pageType=record.page_type,
        title=record.title,
        summary=record.summary,
        selection=dict(record.selection),
        entities=[dict(entity) for entity in record.entities],
        metadata=dict(record.metadata),
    )


def _task_response(task: TerraFinTaskRecord) -> HostedTaskResponse:
    return HostedTaskResponse(
        taskId=task.task_id,
        capabilityName=task.capability_name,
        status=task.status,
        description=task.description,
        sessionId=task.session_id,
        createdAt=task.created_at.isoformat(),
        startedAt=None if task.started_at is None else task.started_at.isoformat(),
        completedAt=None if task.completed_at is None else task.completed_at.isoformat(),
        inputPayload=dict(task.input_payload),
        progress=dict(task.progress),
        result=None if task.result is None else dict(task.result),
        error=task.error,
    )


def _runtime_model_response(payload: object) -> HostedRuntimeModelResponse | None:
    if hasattr(payload, "to_payload"):
        payload = payload.to_payload()
    if not isinstance(payload, dict):
        return None
    model_ref = str(payload.get("modelRef") or "").strip()
    provider_id = str(payload.get("providerId") or "").strip()
    provider_label = str(payload.get("providerLabel") or "").strip()
    model_id = str(payload.get("modelId") or "").strip()
    if not model_ref or not provider_id or not provider_label or not model_id:
        return None
    return HostedRuntimeModelResponse(
        modelRef=model_ref,
        providerId=provider_id,
        providerLabel=provider_label,
        modelId=model_id,
        metadata=dict(payload.get("metadata", {})),
    )


def _message_preview(content: str, *, limit: int = 96) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def _session_summary_response(
    record: TerraFinHostedSessionRecord,
    *,
    loop: object | None = None,
) -> HostedAgentSessionSummaryResponse:
    transcript_summary = None
    if loop is not None:
        transcript_store = getattr(getattr(loop, "runtime", None), "transcript_store", None)
        if transcript_store is not None and transcript_store.session_exists(record.session_id):
            transcript_summary = transcript_store.build_summary(record.session_id)
    conversation = None
    if transcript_summary is None and loop is not None:
        try:
            conversation = loop.get_conversation(record.session_id)
        except Exception:
            conversation = None
    visible_messages = (
        []
        if conversation is None
        else [
            message
            for message in conversation.snapshot()
            if message.role not in {"system", "tool"} and not is_internal_only_message(message)
        ]
    )
    last_message = visible_messages[-1] if visible_messages else None
    first_user_message = next((message for message in visible_messages if message.role == "user"), None)
    runtime_model = _runtime_model_response(record.context.session.metadata.get(RUNTIME_MODEL_METADATA_KEY))
    if runtime_model is None and loop is not None:
        runtime_model = _resolve_model_client_runtime_model(loop, session=record.context.session)
    if transcript_summary is not None and transcript_summary.runtime_model is not None:
        runtime_model = _runtime_model_response(transcript_summary.runtime_model) or runtime_model
    pending_task_count = sum(
        1
        for task in record.context.task_registry.list_for_session(record.session_id)
        if task.status not in {"completed", "failed", "cancelled"}
    )
    return HostedAgentSessionSummaryResponse(
        sessionId=record.session_id,
        agentName=record.agent_name,
        createdAt=record.created_at.isoformat(),
        updatedAt=record.updated_at.isoformat(),
        lastAccessedAt=record.last_accessed_at.isoformat(),
        runtimeModel=runtime_model,
        title=(
            transcript_summary.title
            if transcript_summary is not None
            else None
            if first_user_message is None
            else _message_preview(first_user_message.content, limit=72)
        ),
        lastMessagePreview=(
            transcript_summary.last_message_preview
            if transcript_summary is not None
            else None
            if last_message is None
            else _message_preview(last_message.content)
        ),
        lastMessageAt=(
            None
            if (transcript_summary is not None and transcript_summary.last_message_at is None)
            else transcript_summary.last_message_at.isoformat()
            if transcript_summary is not None
            else None
            if last_message is None
            else last_message.created_at.isoformat()
        ),
        messageCount=transcript_summary.message_count if transcript_summary is not None else len(visible_messages),
        pendingTaskCount=pending_task_count,
    )


def _resolve_model_client_runtime_model(
    loop: object, *, session: object | None = None
) -> HostedRuntimeModelResponse | None:
    describe = getattr(getattr(loop, "model_client", None), "describe_runtime_model", None)
    if not callable(describe):
        return None
    try:
        payload = describe(session=session)
    except TypeError:
        payload = describe()
    return _runtime_model_response(payload)


def _resolve_model_client_runtime_status(
    loop: object,
    *,
    session: object | None = None,
) -> tuple[HostedRuntimeModelResponse | None, bool, str | None]:
    describe = getattr(getattr(loop, "model_client", None), "describe_runtime_status", None)
    if callable(describe):
        try:
            payload = describe(session=session)
        except TypeError:
            payload = describe()
        runtime_model = _runtime_model_response((payload or {}).get("runtimeModel"))
        configured = bool((payload or {}).get("configured", False))
        message = (payload or {}).get("message")
        return runtime_model, configured, None if message is None else str(message)
    runtime_model = _resolve_model_client_runtime_model(loop, session=session)
    return runtime_model, runtime_model is not None, None


def _raise_if_hosted_runtime_unavailable(loop: object, *, session: object | None = None) -> None:
    _runtime_model, configured, setup_message = _resolve_model_client_runtime_status(loop, session=session)
    if configured:
        return
    raise AppRuntimeError(
        setup_message or "A hosted model provider must be configured before TerraFin Agent can run.",
        code="hosted_agent_not_configured",
        status_code=503,
        details={"feature": "hosted_agent_runtime"},
    )


def _session_response(
    record: TerraFinHostedSessionRecord,
    *,
    loop: object | None = None,
    tools: tuple[TerraFinToolDefinition, ...],
) -> HostedAgentSessionResponse:
    conversation = None
    if loop is not None:
        try:
            conversation = loop.get_conversation(record.session_id)
        except Exception:
            conversation = None
    else:
        conversation = record.conversation
    session_policy = record.context.session.metadata.get("agentPolicy", {})
    runtime_model = _runtime_model_response(record.context.session.metadata.get(RUNTIME_MODEL_METADATA_KEY))
    if runtime_model is None and loop is not None:
        runtime_model = _resolve_model_client_runtime_model(loop, session=record.context.session)
    return HostedAgentSessionResponse(
        sessionId=record.session_id,
        agentName=record.agent_name,
        metadata=dict(record.context.session.metadata),
        runtimeModel=runtime_model,
        policy=HostedSessionPolicyResponse(**session_policy) if session_policy else None,
        focusItems=list(record.context.session.snapshot().focus_items),
        artifacts=[_artifact_response(artifact) for artifact in record.context.session.snapshot().artifacts],
        capabilityCalls=[
            _capability_call_response(call) for call in record.context.session.snapshot().capability_calls
        ],
        tasks=[_task_response(task) for task in record.context.task_registry.list_for_session(record.session_id)],
        approvals=[_approval_response(approval) for approval in record.approval_requests],
        auditTrail=[_audit_response(event) for event in record.audit_log],
        tools=[_tool_response(tool) for tool in tools],
        messages=[]
        if conversation is None
        else [_message_response(message) for message in conversation.snapshot() if not is_internal_only_message(message)],
    )


def _tool_invocation_response(result: TerraFinToolInvocationResult) -> HostedToolInvocationResponse:
    task = None
    if result.task is not None:
        task = HostedTaskSummaryResponse(
            taskId=result.task.task_id,
            status=result.task.status,
            description=result.task.description,
        )
    return HostedToolInvocationResponse(
        toolName=result.tool_name,
        capabilityName=result.capability_name,
        executionMode=result.execution_mode,
        payload=dict(result.payload),
        task=task,
    )


def _run_response(
    run_result: TerraFinHostedRunResult,
    *,
    record: TerraFinHostedSessionRecord,
    loop: object | None = None,
    tools: tuple[TerraFinToolDefinition, ...],
) -> HostedAgentRunResponse:
    return HostedAgentRunResponse(
        sessionId=run_result.session_id,
        agentName=run_result.agent_name,
        steps=run_result.steps,
        finalMessage=None if run_result.final_message is None else _message_response(run_result.final_message),
        messagesAdded=[_message_response(message) for message in run_result.messages_added if not is_internal_only_message(message)],
        toolResults=[_tool_invocation_response(result) for result in run_result.tool_results],
        session=_session_response(record, loop=loop, tools=tools),
    )


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, AppRuntimeError):
        raise exc
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, TerraFinOpenAIConfigError):
        raise AppRuntimeError(
            str(exc),
            code="hosted_agent_not_configured",
            status_code=503,
            details={"feature": "hosted_agent_runtime"},
        ) from exc
    if isinstance(exc, TerraFinModelConfigError):
        raise AppRuntimeError(
            str(exc),
            code="hosted_agent_not_configured",
            status_code=503,
            details={"feature": "hosted_agent_runtime"},
        ) from exc
    if isinstance(exc, TerraFinOpenAIResponseError):
        raise AppRuntimeError(
            str(exc),
            code="hosted_agent_provider_error",
            status_code=502,
            details={"feature": "hosted_agent_runtime"},
        ) from exc
    if isinstance(exc, TerraFinModelResponseError):
        raise AppRuntimeError(
            str(exc),
            code="hosted_agent_provider_error",
            status_code=502,
            details={"feature": "hosted_agent_runtime"},
        ) from exc
    if isinstance(exc, TerraFinAgentPolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, TerraFinAgentSessionConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, TerraFinAgentApprovalRequiredError):
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "approvalId": exc.approval.approval_id,
                "status": exc.approval.status,
            },
        ) from exc
    if isinstance(exc, SecEdgarConfigurationError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_not_configured",
            status_code=503,
            details={"feature": "agent_portfolio"},
        ) from exc
    if isinstance(exc, SecEdgarUnavailableError):
        raise AppRuntimeError(
            str(exc),
            code="sec_edgar_unavailable",
            status_code=503,
            details={"feature": "agent_portfolio"},
        ) from exc
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def create_agent_data_router() -> APIRouter:
    router = APIRouter()
    service = TerraFinAgentService()

    @router.get(f"{AGENT_API_PREFIX}/runtime/agents", response_model=HostedAgentCatalogResponse)
    def api_hosted_agent_catalog():
        try:
            loop = get_hosted_agent_loop()
            default_runtime_model, runtime_configured, runtime_setup_message = _resolve_model_client_runtime_status(
                loop
            )
            agents = []
            for definition in loop.runtime.list_agents():
                if is_internal_agent_definition(definition):
                    continue
                agents.append(
                    HostedAgentDefinitionResponse(
                        name=definition.name,
                        description=definition.description,
                        allowedCapabilities=list(definition.allowed_capabilities),
                        defaultDepth=definition.default_depth,
                        defaultView=definition.default_view,
                        chartAccess=definition.chart_access,
                        allowBackgroundTasks=definition.allow_background_tasks,
                        runtimeModel=default_runtime_model,
                        runtimeConfigured=runtime_configured,
                        runtimeSetupMessage=runtime_setup_message,
                        metadata=dict(definition.metadata),
                        tools=[
                            _tool_response(tool) for tool in loop.tool_adapter.list_tools_for_agent(definition.name)
                        ],
                    )
                )
            return HostedAgentCatalogResponse(agents=agents)
        except Exception as exc:
            _raise_http_error(exc)

    @router.post(f"{AGENT_API_PREFIX}/runtime/sessions", response_model=HostedAgentSessionResponse)
    def api_hosted_agent_create_session(request: HostedAgentSessionCreateRequest):
        try:
            loop = get_hosted_agent_loop()
            _raise_if_hosted_runtime_unavailable(loop)
            _raise_if_internal_agent_name(loop, request.agentName)
            conversation = loop.create_session(
                request.agentName,
                session_id=request.sessionId,
                metadata=request.metadata,
                system_prompt=request.systemPrompt,
            )
            record = loop.runtime.get_session_record(conversation.session_id)
            return _session_response(
                record,
                loop=loop,
                tools=loop.tool_adapter.list_tools_for_session(conversation.session_id),
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/runtime/sessions", response_model=HostedAgentSessionListResponse)
    def api_hosted_agent_list_sessions():
        try:
            loop = get_hosted_agent_loop()
            records = loop.runtime.list_sessions()
            return HostedAgentSessionListResponse(
                sessions=[_session_summary_response(record, loop=loop) for record in records],
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/runtime/sessions/{{session_id}}", response_model=HostedAgentSessionResponse)
    def api_hosted_agent_get_session(session_id: str):
        try:
            loop = get_hosted_agent_loop()
            record = _get_public_session_record(loop, session_id)
            return _session_response(
                record,
                loop=loop,
                tools=loop.tool_adapter.list_tools_for_session(session_id),
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.delete(
        f"{AGENT_API_PREFIX}/runtime/sessions/{{session_id}}",
        response_model=HostedAgentSessionDeleteResponse,
    )
    def api_hosted_agent_delete_session(session_id: str):
        try:
            loop = get_hosted_agent_loop()
            _get_public_session_record(loop, session_id)
            removed = loop.runtime.delete_session(session_id)
            forget_conversation = getattr(loop, "forget_conversation", None)
            if callable(forget_conversation):
                forget_conversation(session_id)
            return HostedAgentSessionDeleteResponse(
                sessionId=removed.session_id,
                deletedAt=removed.updated_at.isoformat(),
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.put(
        f"{AGENT_API_PREFIX}/runtime/view-contexts/{{context_id}}",
        response_model=HostedViewContextResponse,
    )
    def api_hosted_agent_upsert_view_context(
        context_id: str,
        request: HostedViewContextUpdateRequest,
    ):
        try:
            loop = get_hosted_agent_loop()
            record = loop.runtime.upsert_view_context(
                context_id,
                route=request.route,
                page_type=request.pageType,
                title=request.title,
                summary=request.summary,
                selection=request.selection,
                entities=request.entities,
                metadata=request.metadata,
            )
            return _view_context_response(record)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(
        f"{AGENT_API_PREFIX}/runtime/view-contexts/{{context_id}}",
        response_model=HostedViewContextResponse,
    )
    def api_hosted_agent_get_view_context(context_id: str):
        try:
            loop = get_hosted_agent_loop()
            return _view_context_response(loop.runtime.get_view_context(context_id))
        except Exception as exc:
            _raise_http_error(exc)

    @router.post(
        f"{AGENT_API_PREFIX}/runtime/sessions/{{session_id}}/messages",
        response_model=HostedAgentRunResponse,
    )
    def api_hosted_agent_submit_message(session_id: str, request: HostedAgentMessageRequest):
        try:
            loop = get_hosted_agent_loop()
            record = _get_public_session_record(loop, session_id)
            _raise_if_hosted_runtime_unavailable(loop, session=record.context.session)
            # Refresh the session's viewContextId link before running the loop
            # so `current_view_context` reads the user's live view, not the
            # stale snapshot captured at session-creation time.
            if request.viewContextId:
                loop.runtime.relink_session_view_context(session_id, request.viewContextId)
            run_result = loop.submit_user_message(session_id, request.content)
            record = _get_public_session_record(loop, session_id)
            return _run_response(
                run_result,
                record=record,
                loop=loop,
                tools=loop.tool_adapter.list_tools_for_session(session_id),
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(
        f"{AGENT_API_PREFIX}/runtime/sessions/{{session_id}}/tasks",
        response_model=HostedTaskListResponse,
    )
    def api_hosted_agent_list_tasks(session_id: str):
        try:
            loop = get_hosted_agent_loop()
            tasks = loop.runtime.list_public_session_tasks(session_id)
            return HostedTaskListResponse(
                sessionId=session_id,
                tasks=[_task_response(task) for task in tasks],
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(
        f"{AGENT_API_PREFIX}/runtime/sessions/{{session_id}}/approvals",
        response_model=HostedApprovalListResponse,
    )
    def api_hosted_agent_list_approvals(session_id: str):
        try:
            loop = get_hosted_agent_loop()
            approvals = loop.runtime.list_public_session_approvals(session_id)
            return HostedApprovalListResponse(
                sessionId=session_id,
                approvals=[_approval_response(approval) for approval in approvals],
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/runtime/tasks/{{task_id}}", response_model=HostedTaskResponse)
    def api_hosted_agent_get_task(task_id: str):
        try:
            loop = get_hosted_agent_loop()
            return _task_response(loop.runtime.get_public_task(task_id))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/runtime/approvals/{{approval_id}}", response_model=HostedApprovalResponse)
    def api_hosted_agent_get_approval(approval_id: str):
        try:
            loop = get_hosted_agent_loop()
            return _approval_response(loop.runtime.get_public_approval(approval_id))
        except Exception as exc:
            _raise_http_error(exc)

    @router.post(f"{AGENT_API_PREFIX}/runtime/tasks/{{task_id}}/cancel", response_model=HostedTaskResponse)
    def api_hosted_agent_cancel_task(task_id: str):
        try:
            loop = get_hosted_agent_loop()
            return _task_response(loop.runtime.cancel_public_task(task_id))
        except Exception as exc:
            _raise_http_error(exc)

    @router.post(
        f"{AGENT_API_PREFIX}/runtime/approvals/{{approval_id}}/approve",
        response_model=HostedApprovalResponse,
    )
    def api_hosted_agent_approve_approval(
        approval_id: str,
        request: HostedApprovalDecisionRequest,
    ):
        try:
            loop = get_hosted_agent_loop()
            return _approval_response(loop.runtime.approve_public_approval(approval_id, note=request.note))
        except Exception as exc:
            _raise_http_error(exc)

    @router.post(
        f"{AGENT_API_PREFIX}/runtime/approvals/{{approval_id}}/deny",
        response_model=HostedApprovalResponse,
    )
    def api_hosted_agent_deny_approval(
        approval_id: str,
        request: HostedApprovalDecisionRequest,
    ):
        try:
            loop = get_hosted_agent_loop()
            return _approval_response(loop.runtime.deny_public_approval(approval_id, note=request.note))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/resolve", response_model=ResolveResponse)
    def api_agent_resolve(q: str = Query(..., min_length=1)):
        try:
            return ResolveResponse(**service.resolve(q))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-data", response_model=MarketDataResponse)
    def api_agent_market_data(
        ticker: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MarketDataResponse(**service.market_data(ticker, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/indicators", response_model=IndicatorsResponse)
    def api_agent_indicators(
        ticker: str = Query(..., min_length=1),
        indicators: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return IndicatorsResponse(**service.indicators(ticker, indicators, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-snapshot", response_model=MarketSnapshotResponse)
    def api_agent_market_snapshot(
        ticker: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MarketSnapshotResponse(**service.market_snapshot(ticker, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/company", response_model=CompanyInfoResponse)
    def api_agent_company(ticker: str = Query(..., min_length=1)):
        try:
            return CompanyInfoResponse(**service.company_info(ticker))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/earnings", response_model=EarningsResponse)
    def api_agent_earnings(ticker: str = Query(..., min_length=1)):
        try:
            return EarningsResponse(**service.earnings(ticker))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/financials", response_model=FinancialStatementResponse)
    def api_agent_financials(
        ticker: str = Query(..., min_length=1),
        statement: str = Query(default="income", pattern="^(income|balance|cashflow)$"),
        period: str = Query(default="annual", pattern="^(annual|quarter)$"),
    ):
        try:
            return FinancialStatementResponse(**service.financials(ticker, statement=statement, period=period))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/portfolio", response_model=PortfolioResponse)
    def api_agent_portfolio(guru: str = Query(..., min_length=1)):
        try:
            return PortfolioResponse(**service.portfolio(guru))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/economic", response_model=EconomicResponse)
    def api_agent_economic(indicators: str = Query(..., min_length=1)):
        try:
            return EconomicResponse(**service.economic(indicators))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/macro-focus", response_model=MacroFocusResponse)
    def api_agent_macro_focus(
        name: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return MacroFocusResponse(**service.macro_focus(name, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/lppl", response_model=LPPLAnalysisResponse)
    def api_agent_lppl(
        name: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
        view: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
    ):
        try:
            return LPPLAnalysisResponse(**service.lppl_analysis(name, depth=depth, view=view))
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/calendar", response_model=CalendarResponse)
    def api_agent_calendar(
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=1970, le=2200),
        categories: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=500),
    ):
        try:
            return CalendarResponse(
                **service.calendar_events(year=year, month=month, categories=categories, limit=limit)
            )
        except Exception as exc:
            _raise_http_error(exc)

    # ------------------------------------------------------------------
    # Stateless capability routes for the rest of the agent surface.
    # These mirror the hosted-runtime tool registry one-to-one so external
    # HTTP-only agents (Claude Code consuming SKILL.md, n8n flows, etc.) have
    # parity with internally-hosted agents. Response payloads are returned as
    # raw dicts pending the dedicated Pydantic response models tracked
    # separately. Each route is a thin pass-through to TerraFinAgentService.
    # ------------------------------------------------------------------

    @router.get(f"{AGENT_API_PREFIX}/valuation")
    def api_agent_valuation(
        ticker: str = Query(..., min_length=1),
        projection_years: int | None = Query(default=None, ge=1, le=20),
        fcf_base_source: str | None = Query(
            default=None, pattern="^(auto|3yr_avg|ttm|latest_annual)$"
        ),
        breakeven_year: int | None = Query(default=None, ge=1, le=15),
        breakeven_cash_flow_per_share: float | None = Query(default=None),
        post_breakeven_growth_pct: float | None = Query(default=None),
    ) -> dict:
        try:
            return service.valuation(
                ticker,
                projection_years=projection_years,
                fcf_base_source=fcf_base_source,
                breakeven_year=breakeven_year,
                breakeven_cash_flow_per_share=breakeven_cash_flow_per_share,
                post_breakeven_growth_pct=post_breakeven_growth_pct,
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/fcf-history")
    def api_agent_fcf_history(
        ticker: str = Query(..., min_length=1),
        years: int = Query(default=10, ge=1, le=20),
    ) -> dict:
        from TerraFin.interface.stock.payloads import build_fcf_history_payload

        try:
            return build_fcf_history_payload(ticker, years=years)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/sp500-dcf")
    def api_agent_sp500_dcf() -> dict:
        try:
            return service.sp500_dcf()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/fundamental-screen")
    def api_agent_fundamental_screen(ticker: str = Query(..., min_length=1)) -> dict:
        try:
            return service.fundamental_screen(ticker)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/risk-profile")
    def api_agent_risk_profile(
        name: str = Query(..., min_length=1),
        depth: str = Query(default="auto", pattern="^(auto|recent|full)$"),
    ) -> dict:
        try:
            return service.risk_profile(name, depth=depth)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/beta-estimate")
    def api_agent_beta_estimate(ticker: str = Query(..., min_length=1)) -> dict:
        try:
            return service.beta_estimate(ticker)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/sec-filings")
    def api_agent_sec_filings(ticker: str = Query(..., min_length=1)) -> dict:
        try:
            return service.sec_filings(ticker)
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/sec-filing-document")
    def api_agent_sec_filing_document(
        ticker: str = Query(..., min_length=1),
        accession: str = Query(..., min_length=1),
        primaryDocument: str = Query(..., min_length=1),
        form: str = Query(default="10-Q", min_length=1),
    ) -> dict:
        try:
            return service.sec_filing_document(
                ticker, accession, primaryDocument, form=form
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/sec-filing-section")
    def api_agent_sec_filing_section(
        ticker: str = Query(..., min_length=1),
        accession: str = Query(..., min_length=1),
        primaryDocument: str = Query(..., min_length=1),
        sectionSlug: str = Query(..., min_length=1),
        form: str = Query(default="10-Q", min_length=1),
    ) -> dict:
        try:
            return service.sec_filing_section(
                ticker, accession, primaryDocument, sectionSlug, form=form
            )
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/fear-greed")
    def api_agent_fear_greed() -> dict:
        try:
            return service.fear_greed()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/top-companies")
    def api_agent_top_companies() -> dict:
        try:
            return service.top_companies()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-regime")
    def api_agent_market_regime() -> dict:
        try:
            return service.market_regime()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/trailing-forward-pe")
    def api_agent_trailing_forward_pe() -> dict:
        try:
            return service.trailing_forward_pe()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/market-breadth")
    def api_agent_market_breadth() -> dict:
        try:
            return service.market_breadth()
        except Exception as exc:
            _raise_http_error(exc)

    @router.get(f"{AGENT_API_PREFIX}/watchlist")
    def api_agent_watchlist() -> dict:
        try:
            return service.watchlist()
        except Exception as exc:
            _raise_http_error(exc)

    return router
