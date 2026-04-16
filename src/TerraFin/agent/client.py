import uuid
from typing import Any, Iterable

import requests

from TerraFin.data.contracts import TimeSeriesDataFrame
from TerraFin.interface.chart import client as chart_client
from TerraFin.interface.chart.formatters import build_multi_payload

from .conversation import is_internal_only_message
from .definitions import is_internal_agent_definition
from .models import ChartOpenResponse
from .service import TerraFinAgentService


class TerraFinAgentClient:
    def __init__(
        self,
        *,
        transport: str = "auto",
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.transport = (transport or "auto").strip().lower()
        if self.transport not in {"auto", "python", "http"}:
            raise ValueError(f"Unsupported transport: {transport}")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout
        self._service = TerraFinAgentService()

    def _resolved_transport(self) -> str:
        if self.transport == "auto":
            return "http" if self.base_url else "python"
        return self.transport

    def _service_call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return getattr(self._service, method)(*args, **kwargs)

    def _http_url(self, path: str) -> str:
        if not self.base_url:
            raise ValueError("base_url is required for HTTP transport")
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"

    def _http_response_json(self, response: requests.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = {}
            detail = payload.get("detail") or payload.get("error", {}).get("message") or f"HTTP {response.status_code}"
            raise RuntimeError(str(detail))
        return response.json()

    def _http_get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(self._http_url(path), params=params, timeout=self.timeout)
        return self._http_response_json(response)

    def _http_post(self, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(self._http_url(path), json=json, timeout=self.timeout)
        return self._http_response_json(response)

    def _http_delete(self, path: str) -> dict[str, Any]:
        response = requests.delete(self._http_url(path), timeout=self.timeout)
        return self._http_response_json(response)

    def _serialize_runtime_message(self, message: Any) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "createdAt": message.created_at.isoformat(),
            "name": message.name,
            "toolCallId": message.tool_call_id,
            "metadata": dict(message.metadata),
        }

    def _serialize_runtime_tool(self, tool: Any) -> dict[str, Any]:
        return {
            "name": tool.name,
            "capabilityName": tool.capability_name,
            "description": tool.description,
            "executionMode": tool.execution_mode,
            "sideEffecting": tool.side_effecting,
            "inputSchema": dict(tool.input_schema),
            "metadata": dict(tool.metadata),
        }

    def _serialize_runtime_task(self, task: Any) -> dict[str, Any]:
        return {
            "taskId": task.task_id,
            "capabilityName": task.capability_name,
            "status": task.status,
            "description": task.description,
            "sessionId": task.session_id,
            "createdAt": task.created_at.isoformat(),
            "startedAt": None if task.started_at is None else task.started_at.isoformat(),
            "completedAt": None if task.completed_at is None else task.completed_at.isoformat(),
            "inputPayload": dict(task.input_payload),
            "progress": dict(task.progress),
            "result": None if task.result is None else dict(task.result),
            "error": task.error,
        }

    def _serialize_runtime_tool_result(self, result: Any) -> dict[str, Any]:
        payload = {
            "toolName": result.tool_name,
            "capabilityName": result.capability_name,
            "executionMode": result.execution_mode,
            "payload": dict(result.payload),
            "task": None,
        }
        if result.task is not None:
            payload["task"] = self._serialize_runtime_task(result.task)
        return payload

    def _serialize_runtime_artifact(self, artifact: Any) -> dict[str, Any]:
        return {
            "artifactId": artifact.artifact_id,
            "kind": artifact.kind,
            "title": artifact.title,
            "capabilityName": artifact.capability_name,
            "createdAt": artifact.created_at.isoformat(),
            "payload": dict(artifact.payload),
        }

    def _serialize_runtime_capability_call(self, call: Any) -> dict[str, Any]:
        return {
            "capabilityName": call.capability_name,
            "calledAt": call.called_at.isoformat(),
            "inputs": dict(call.inputs),
            "outputKeys": list(call.output_keys),
            "focusItems": list(call.focus_items),
            "artifactIds": list(call.artifact_ids),
        }

    def _serialize_runtime_audit_event(self, event: Any) -> dict[str, Any]:
        return {
            "eventId": event.event_id,
            "createdAt": event.created_at.isoformat(),
            "action": event.action,
            "capabilityName": event.capability_name,
            "toolName": event.tool_name,
            "sideEffecting": event.side_effecting,
            "outcome": event.outcome,
            "reason": event.reason,
            "metadata": dict(event.metadata),
        }

    def _serialize_runtime_approval(self, approval: Any) -> dict[str, Any]:
        return {
            "approvalId": approval.approval_id,
            "createdAt": approval.created_at.isoformat(),
            "updatedAt": approval.updated_at.isoformat(),
            "resolvedAt": None if approval.resolved_at is None else approval.resolved_at.isoformat(),
            "sessionId": approval.session_id,
            "agentName": approval.agent_name,
            "action": approval.action,
            "capabilityName": approval.capability_name,
            "toolName": approval.tool_name,
            "sideEffecting": approval.side_effecting,
            "status": approval.status,
            "reason": approval.reason,
            "inputPayload": dict(approval.input_payload),
            "decisionNote": approval.decision_note,
            "metadata": dict(approval.metadata),
        }

    def _serialize_runtime_model(self, runtime_model: Any) -> dict[str, Any] | None:
        if runtime_model is None:
            return None
        if hasattr(runtime_model, "to_payload"):
            runtime_model = runtime_model.to_payload()
        if not isinstance(runtime_model, dict):
            return None
        model_ref = str(runtime_model.get("modelRef") or "").strip()
        provider_id = str(runtime_model.get("providerId") or "").strip()
        provider_label = str(runtime_model.get("providerLabel") or "").strip()
        model_id = str(runtime_model.get("modelId") or "").strip()
        if not model_ref or not provider_id or not provider_label or not model_id:
            return None
        return {
            "modelRef": model_ref,
            "providerId": provider_id,
            "providerLabel": provider_label,
            "modelId": model_id,
            "metadata": dict(runtime_model.get("metadata", {})),
        }

    def _serialize_runtime_session_summary(self, *, loop: Any, record: Any) -> dict[str, Any]:
        transcript_summary = None
        transcript_store = getattr(getattr(loop, "runtime", None), "transcript_store", None)
        if transcript_store is not None and transcript_store.session_exists(record.session_id):
            transcript_summary = transcript_store.build_summary(record.session_id)
        conversation = None
        if transcript_summary is None:
            try:
                conversation = loop.get_conversation(record.session_id)
            except Exception:
                conversation = getattr(record, "conversation", None)
        visible_messages = [] if conversation is None else [
            message
            for message in conversation.snapshot()
            if message.role not in {"system", "tool"} and not is_internal_only_message(message)
        ]
        first_user_message = next((message for message in visible_messages if message.role == "user"), None)
        last_message = visible_messages[-1] if visible_messages else None
        runtime_model = self._serialize_runtime_model(record.context.session.metadata.get("runtimeModel"))
        if runtime_model is None and hasattr(loop.model_client, "describe_runtime_model"):
            runtime_model = self._serialize_runtime_model(
                loop.model_client.describe_runtime_model(session=record.context.session)
            )
        if transcript_summary is not None and transcript_summary.runtime_model is not None:
            runtime_model = self._serialize_runtime_model(transcript_summary.runtime_model) or runtime_model
        return {
            "sessionId": record.session_id,
            "agentName": record.agent_name,
            "createdAt": record.created_at.isoformat(),
            "updatedAt": record.updated_at.isoformat(),
            "lastAccessedAt": record.last_accessed_at.isoformat(),
            "runtimeModel": runtime_model,
            "title": transcript_summary.title if transcript_summary is not None else None if first_user_message is None else first_user_message.content,
            "lastMessagePreview": transcript_summary.last_message_preview if transcript_summary is not None else None if last_message is None else last_message.content,
            "lastMessageAt": None if (transcript_summary is not None and transcript_summary.last_message_at is None) else transcript_summary.last_message_at.isoformat() if transcript_summary is not None else None if last_message is None else last_message.created_at.isoformat(),
            "messageCount": transcript_summary.message_count if transcript_summary is not None else len(visible_messages),
            "pendingTaskCount": sum(
                1
                for task in record.context.task_registry.list_for_session(record.session_id)
                if task.status not in {"completed", "failed", "cancelled"}
            ),
        }

    def _serialize_runtime_session(self, *, loop: Any, session_id: str, conversation: Any | None = None) -> dict[str, Any]:
        if hasattr(loop.runtime, "get_session_record"):
            record = loop.runtime.get_session_record(session_id)
            active_conversation = conversation
            if active_conversation is None:
                try:
                    active_conversation = loop.get_conversation(session_id)
                except Exception:
                    active_conversation = None
            snapshot = record.context.session.snapshot()
            runtime_model = self._serialize_runtime_model(record.context.session.metadata.get("runtimeModel"))
            if runtime_model is None and hasattr(loop.model_client, "describe_runtime_model"):
                runtime_model = self._serialize_runtime_model(
                    loop.model_client.describe_runtime_model(session=record.context.session)
                )
            return {
                "sessionId": record.session_id,
                "agentName": record.agent_name,
                "metadata": dict(record.context.session.metadata),
                "runtimeModel": runtime_model,
                "policy": dict(record.context.session.metadata.get("agentPolicy", {})),
                "focusItems": list(snapshot.focus_items),
                "artifacts": [self._serialize_runtime_artifact(artifact) for artifact in snapshot.artifacts],
                "capabilityCalls": [
                    self._serialize_runtime_capability_call(call) for call in snapshot.capability_calls
                ],
                "tasks": [
                    self._serialize_runtime_task(task)
                    for task in record.context.task_registry.list_for_session(record.session_id)
                ],
                "approvals": [
                    self._serialize_runtime_approval(approval)
                    for approval in getattr(record, "approval_requests", [])
                ],
                "auditTrail": [self._serialize_runtime_audit_event(event) for event in record.audit_log],
                "tools": [
                    self._serialize_runtime_tool(tool)
                    for tool in loop.tool_adapter.list_tools_for_session(record.session_id)
                ],
                "messages": []
                if active_conversation is None
                else [
                    self._serialize_runtime_message(message)
                    for message in active_conversation.snapshot()
                    if not is_internal_only_message(message)
                ],
            }

        resolved_conversation = conversation or loop.get_conversation(session_id)
        return {
            "sessionId": resolved_conversation.session_id,
            "agentName": resolved_conversation.agent_name,
            "metadata": dict(resolved_conversation.metadata),
            "runtimeModel": None,
            "approvals": [],
            "tools": [
                self._serialize_runtime_tool(tool)
                for tool in loop.tool_adapter.list_tools_for_session(resolved_conversation.session_id)
            ],
            "messages": [
                self._serialize_runtime_message(message)
                for message in resolved_conversation.snapshot()
                if not is_internal_only_message(message)
            ],
        }

    def _runtime_loop(self) -> Any:
        from .hosted_service import get_hosted_agent_loop

        return get_hosted_agent_loop()

    def resolve(self, query: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("resolve", query)
        return self._http_get("/agent/api/resolve", params={"q": query})

    def market_data(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("market_data", name, depth=depth, view=view)
        return self._http_get("/agent/api/market-data", params={"ticker": name, "depth": depth, "view": view})

    def indicators(self, name: str, indicators: str | Iterable[str], *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        indicator_text = indicators if isinstance(indicators, str) else ",".join(str(item) for item in indicators)
        if self._resolved_transport() == "python":
            return self._service_call("indicators", name, indicator_text, depth=depth, view=view)
        return self._http_get(
            "/agent/api/indicators",
            params={"ticker": name, "indicators": indicator_text, "depth": depth, "view": view},
        )

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("market_snapshot", name, depth=depth, view=view)
        return self._http_get("/agent/api/market-snapshot", params={"ticker": name, "depth": depth, "view": view})

    def economic(self, indicators: str | Iterable[str]) -> dict[str, Any]:
        indicator_text = indicators if isinstance(indicators, str) else ",".join(str(item) for item in indicators)
        if self._resolved_transport() == "python":
            return self._service_call("economic", indicator_text)
        return self._http_get("/agent/api/economic", params={"indicators": indicator_text})

    def portfolio(self, guru: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("portfolio", guru)
        return self._http_get("/agent/api/portfolio", params={"guru": guru})

    def company_info(self, ticker: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("company_info", ticker)
        return self._http_get("/agent/api/company", params={"ticker": ticker})

    def earnings(self, ticker: str) -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("earnings", ticker)
        return self._http_get("/agent/api/earnings", params={"ticker": ticker})

    def financials(self, ticker: str, *, statement: str = "income", period: str = "annual") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("financials", ticker, statement=statement, period=period)
        return self._http_get(
            "/agent/api/financials",
            params={"ticker": ticker, "statement": statement, "period": period},
        )

    def lppl_analysis(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("lppl_analysis", name, depth=depth, view=view)
        return self._http_get("/agent/api/lppl", params={"name": name, "depth": depth, "view": view})

    def macro_focus(self, name: str, *, depth: str = "auto", view: str = "daily") -> dict[str, Any]:
        if self._resolved_transport() == "python":
            return self._service_call("macro_focus", name, depth=depth, view=view)
        return self._http_get("/agent/api/macro-focus", params={"name": name, "depth": depth, "view": view})

    def calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: str | Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        category_text = None
        if isinstance(categories, str):
            category_text = categories
        elif categories is not None:
            category_text = ",".join(str(item) for item in categories)
        if self._resolved_transport() == "python":
            return self._service_call("calendar_events", year=year, month=month, categories=category_text, limit=limit)
        params: dict[str, Any] = {"year": year, "month": month}
        if category_text:
            params["categories"] = category_text
        if limit is not None:
            params["limit"] = limit
        return self._http_get("/agent/api/calendar", params=params)

    def runtime_agents(self) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get("/agent/api/runtime/agents")
        loop = self._runtime_loop()
        agents = []
        for definition in loop.runtime.list_agents():
            if is_internal_agent_definition(definition):
                continue
            agents.append(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "allowedCapabilities": list(definition.allowed_capabilities),
                    "defaultDepth": definition.default_depth,
                    "defaultView": definition.default_view,
                    "chartAccess": definition.chart_access,
                    "allowBackgroundTasks": definition.allow_background_tasks,
                    "metadata": dict(definition.metadata),
                    "tools": [
                        self._serialize_runtime_tool(tool)
                        for tool in loop.tool_adapter.list_tools_for_agent(definition.name)
                    ],
                }
            )
        return {"agents": agents}

    def runtime_create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_post(
                "/agent/api/runtime/sessions",
                json={
                    "agentName": agent_name,
                    "sessionId": session_id,
                    "systemPrompt": system_prompt,
                    "metadata": dict(metadata or {}),
                },
            )
        loop = self._runtime_loop()
        conversation = loop.create_session(
            agent_name,
            session_id=session_id,
            metadata=metadata,
            system_prompt=system_prompt,
        )
        return self._serialize_runtime_session(loop=loop, session_id=conversation.session_id, conversation=conversation)

    def runtime_sessions(self) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get("/agent/api/runtime/sessions")
        loop = self._runtime_loop()
        return {
            "sessions": [
                self._serialize_runtime_session_summary(loop=loop, record=record)
                for record in loop.runtime.list_sessions()
            ]
        }

    def runtime_session(self, session_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get(f"/agent/api/runtime/sessions/{session_id}")
        loop = self._runtime_loop()
        loop.runtime.get_public_session_record(session_id)
        conversation = loop.get_conversation(session_id)
        return self._serialize_runtime_session(loop=loop, session_id=session_id, conversation=conversation)

    def runtime_delete_session(self, session_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_delete(f"/agent/api/runtime/sessions/{session_id}")
        loop = self._runtime_loop()
        loop.runtime.get_public_session_record(session_id)
        removed = loop.runtime.delete_session(session_id)
        forget_conversation = getattr(loop, "forget_conversation", None)
        if callable(forget_conversation):
            forget_conversation(session_id)
        return {
            "sessionId": removed.session_id,
            "deletedAt": removed.updated_at.isoformat(),
        }

    def runtime_message(self, session_id: str, content: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_post(
                f"/agent/api/runtime/sessions/{session_id}/messages",
                json={"content": content},
            )
        loop = self._runtime_loop()
        loop.runtime.get_public_session_record(session_id)
        run_result = loop.submit_user_message(session_id, content)
        conversation = loop.get_conversation(session_id)
        return {
            "sessionId": run_result.session_id,
            "agentName": run_result.agent_name,
            "steps": run_result.steps,
            "finalMessage": None
            if run_result.final_message is None
            else self._serialize_runtime_message(run_result.final_message),
            "messagesAdded": [
                self._serialize_runtime_message(message)
                for message in run_result.messages_added
                if not is_internal_only_message(message)
            ],
            "toolResults": [
                self._serialize_runtime_tool_result(result)
                for result in run_result.tool_results
            ],
            "session": self._serialize_runtime_session(loop=loop, session_id=session_id, conversation=conversation),
        }

    def runtime_session_tasks(self, session_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get(f"/agent/api/runtime/sessions/{session_id}/tasks")
        loop = self._runtime_loop()
        tasks = loop.runtime.list_public_session_tasks(session_id)
        return {
            "sessionId": session_id,
            "tasks": [self._serialize_runtime_task(task) for task in tasks],
        }

    def runtime_session_approvals(self, session_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get(f"/agent/api/runtime/sessions/{session_id}/approvals")
        loop = self._runtime_loop()
        approvals = loop.runtime.list_public_session_approvals(session_id)
        return {
            "sessionId": session_id,
            "approvals": [self._serialize_runtime_approval(approval) for approval in approvals],
        }

    def runtime_task(self, task_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get(f"/agent/api/runtime/tasks/{task_id}")
        loop = self._runtime_loop()
        return self._serialize_runtime_task(loop.runtime.get_public_task(task_id))

    def runtime_approval(self, approval_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_get(f"/agent/api/runtime/approvals/{approval_id}")
        loop = self._runtime_loop()
        return self._serialize_runtime_approval(loop.runtime.get_public_approval(approval_id))

    def runtime_cancel_task(self, task_id: str) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_post(f"/agent/api/runtime/tasks/{task_id}/cancel", json={})
        loop = self._runtime_loop()
        return self._serialize_runtime_task(loop.runtime.cancel_public_task(task_id))

    def runtime_approve_approval(self, approval_id: str, *, note: str | None = None) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_post(f"/agent/api/runtime/approvals/{approval_id}/approve", json={"note": note})
        loop = self._runtime_loop()
        return self._serialize_runtime_approval(loop.runtime.approve_public_approval(approval_id, note=note))

    def runtime_deny_approval(self, approval_id: str, *, note: str | None = None) -> dict[str, Any]:
        if self._resolved_transport() == "http":
            return self._http_post(f"/agent/api/runtime/approvals/{approval_id}/deny", json={"note": note})
        loop = self._runtime_loop()
        return self._serialize_runtime_approval(loop.runtime.deny_public_approval(approval_id, note=note))

    def open_chart(
        self,
        data_or_names: str | list[str] | TimeSeriesDataFrame | list[TimeSeriesDataFrame],
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or f"agent:{uuid.uuid4().hex}"
        if isinstance(data_or_names, TimeSeriesDataFrame):
            frames = [data_or_names]
            names = None
        elif isinstance(data_or_names, list) and data_or_names and all(
            isinstance(item, TimeSeriesDataFrame) for item in data_or_names
        ):
            frames = list(data_or_names)
            names = None
        elif isinstance(data_or_names, str):
            frames = None
            names = [data_or_names]
        elif isinstance(data_or_names, list) and all(isinstance(item, str) for item in data_or_names):
            frames = None
            names = [str(item) for item in data_or_names]
        else:
            raise TypeError("open_chart expects a name, list of names, TimeSeriesDataFrame, or list of TimeSeriesDataFrame")

        transport = self._resolved_transport()
        if transport == "python":
            return self._open_local_chart(frames=frames, names=names, session_id=sid)
        return self._open_remote_chart(frames=frames, names=names, session_id=sid)

    def _ensure_local_chart_server(self) -> None:
        chart_client._ensure_server_ready()

    def _open_local_chart(
        self,
        *,
        frames: list[TimeSeriesDataFrame] | None,
        names: list[str] | None,
        session_id: str,
    ) -> dict[str, Any]:
        self._ensure_local_chart_server()
        if frames is not None:
            if not chart_client.update_chart(frames if len(frames) > 1 else frames[0], session_id=session_id):
                raise RuntimeError("Failed to update the local TerraFin chart session.")
            chart_url = chart_client._runtime_chart_url("/chart", session_id=session_id)
            return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

        assert names is not None
        headers = {"X-Session-ID": session_id}
        first, *rest = names
        seed = requests.post(
            chart_client._runtime_url("/chart/api/chart-series/progressive/set"),
            json={"name": first, "pinned": True, "seedPeriod": "3y"},
            headers=headers,
            timeout=self.timeout,
        )
        if seed.status_code >= 400:
            raise RuntimeError(seed.json().get("error") or seed.json().get("detail") or "Failed to seed chart")
        for name in rest:
            response = requests.post(
                chart_client._runtime_url("/chart/api/chart-series/add"),
                json={"name": name},
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to add chart series")
        chart_url = chart_client._runtime_chart_url("/chart", session_id=session_id)
        return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

    def _open_remote_chart(
        self,
        *,
        frames: list[TimeSeriesDataFrame] | None,
        names: list[str] | None,
        session_id: str,
    ) -> dict[str, Any]:
        headers = {"X-Session-ID": session_id}
        if frames is not None:
            payload = build_multi_payload(frames)
            response = requests.post(
                self._http_url("/chart/api/chart-data"),
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to update chart")
            chart_url = f"{self.base_url}/chart?sessionId={session_id}"
            return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()

        assert names is not None
        first, *rest = names
        seed = requests.post(
            self._http_url("/chart/api/chart-series/progressive/set"),
            json={"name": first, "pinned": True, "seedPeriod": "3y"},
            headers=headers,
            timeout=self.timeout,
        )
        if seed.status_code >= 400:
            raise RuntimeError(seed.json().get("error") or seed.json().get("detail") or "Failed to seed chart")
        for name in rest:
            response = requests.post(
                self._http_url("/chart/api/chart-series/add"),
                json={"name": name},
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(response.json().get("error") or response.json().get("detail") or "Failed to add chart series")
        chart_url = f"{self.base_url}/chart?sessionId={session_id}"
        return ChartOpenResponse(ok=True, sessionId=session_id, chartUrl=chart_url).model_dump()
