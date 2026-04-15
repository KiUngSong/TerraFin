from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from .conversation_state import RUNTIME_MODEL_METADATA_KEY, record_tool_call_history
from .definitions import TerraFinAgentDefinition
from .hosted_runtime import TerraFinHostedAgentRuntime
from .runtime import TerraFinAgentSession
from .tools import TerraFinHostedToolAdapter, TerraFinToolDefinition, TerraFinToolInvocationResult


MessageRole = Literal["system", "user", "assistant", "tool"]
CONVERSATION_STATE_METADATA_KEY = "conversationState"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_default_system_prompt(definition: TerraFinAgentDefinition) -> str:
    allowed = (
        "all registered TerraFin capabilities"
        if "*" in definition.allowed_capabilities
        else ", ".join(definition.allowed_capabilities)
    )
    return (
        f"You are TerraFin's hosted agent '{definition.name}'. "
        f"{definition.description} "
        f"Use TerraFin tools when they materially improve correctness, stay within your allowed capabilities "
        f"({allowed}), and prefer concise research-oriented answers. "
        "If a user request depends on what they are currently viewing in TerraFin, use the "
        "`current_view_context` tool rather than guessing."
    )


@dataclass(frozen=True, slots=True)
class TerraFinConversationMessage:
    role: MessageRole
    content: str
    created_at: datetime = field(default_factory=_utc_now)
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinToolCall:
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerraFinModelTurn:
    assistant_message: TerraFinConversationMessage | None = None
    tool_calls: tuple[TerraFinToolCall, ...] = ()
    stop_reason: Literal["completed", "tool_calls", "max_steps"] = "completed"


@dataclass
class TerraFinHostedConversation:
    session_id: str
    agent_name: str
    messages: list[TerraFinConversationMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> tuple[TerraFinConversationMessage, ...]:
        return tuple(self.messages)


@dataclass(frozen=True, slots=True)
class TerraFinHostedRunResult:
    session_id: str
    agent_name: str
    final_message: TerraFinConversationMessage | None
    messages_added: tuple[TerraFinConversationMessage, ...]
    tool_results: tuple[TerraFinToolInvocationResult, ...]
    steps: int


class TerraFinHostedModelClient(Protocol):
    def complete(
        self,
        *,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> TerraFinModelTurn: ...


class TerraFinHostedAgentLoop:
    def __init__(
        self,
        *,
        runtime: TerraFinHostedAgentRuntime,
        model_client: TerraFinHostedModelClient,
        tool_adapter: TerraFinHostedToolAdapter | None = None,
        system_prompt_builder: Callable[[TerraFinAgentDefinition], str] | None = None,
        max_steps: int = 8,
        max_tool_calls: int = 24,
        max_messages_per_session: int = 200,
    ) -> None:
        self.runtime = runtime
        self.model_client = model_client
        self.tool_adapter = tool_adapter or TerraFinHostedToolAdapter(runtime)
        self.system_prompt_builder = system_prompt_builder or build_default_system_prompt
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.max_messages_per_session = max_messages_per_session
        self._conversation_cache: dict[str, TerraFinHostedConversation] = {}

    def create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> TerraFinHostedConversation:
        context = self.runtime.create_session(agent_name, session_id=session_id, metadata=metadata)
        definition = self.runtime.get_session_definition(context.session.session_id)
        conversation = TerraFinHostedConversation(
            session_id=context.session.session_id,
            agent_name=definition.name,
            metadata=dict(metadata or {}),
        )
        runtime_model = context.session.metadata.get(RUNTIME_MODEL_METADATA_KEY)
        if isinstance(runtime_model, dict):
            conversation.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(runtime_model)
        prompt = system_prompt if system_prompt is not None else self.system_prompt_builder(definition)
        system_message: TerraFinConversationMessage | None = None
        if prompt:
            system_message = TerraFinConversationMessage(role="system", content=prompt)
            conversation.messages.append(system_message)
        if self.runtime.transcript_store is not None:
            if not self.runtime.transcript_store.session_exists(conversation.session_id):
                self.runtime.transcript_store.create_session(
                    session_id=conversation.session_id,
                    agent_name=definition.name,
                    created_at=conversation.created_at,
                    runtime_model=conversation.metadata.get(RUNTIME_MODEL_METADATA_KEY),
                    system_message=system_message,
                )
            elif system_message is not None:
                self.runtime.transcript_store.append_message(conversation.session_id, system_message)
        self.runtime.attach_conversation(conversation.session_id, conversation)
        self._conversation_cache[conversation.session_id] = conversation
        self._persist_conversation_runtime_state(conversation.session_id, conversation)
        return conversation

    def get_conversation(self, session_id: str) -> TerraFinHostedConversation:
        record = self.runtime.get_session_record(session_id)
        cached = self._conversation_cache.get(session_id)
        if cached is not None:
            self._merge_conversation_runtime_state(cached, record.metadata)
            self.runtime.attach_conversation(session_id, cached)
            return cached
        if self.runtime.transcript_store is None or not self.runtime.transcript_store.session_exists(session_id):
            raise KeyError(f"Unknown TerraFin hosted conversation: {session_id}")
        conversation = self.runtime.transcript_store.load_conversation(
            session_id,
            metadata=self._conversation_runtime_state(record.metadata),
        )
        self.runtime.attach_conversation(session_id, conversation)
        self._conversation_cache[session_id] = conversation
        return conversation

    def forget_conversation(self, session_id: str) -> None:
        self._conversation_cache.pop(session_id, None)

    def submit_user_message(self, session_id: str, content: str) -> TerraFinHostedRunResult:
        conversation = self.get_conversation(session_id)
        added: list[TerraFinConversationMessage] = []
        tool_results: list[TerraFinToolInvocationResult] = []
        final_message: TerraFinConversationMessage | None = None
        total_tool_calls = 0

        self._ensure_message_budget(conversation, incoming_messages=1)
        user_message = TerraFinConversationMessage(role="user", content=content)
        conversation.messages.append(user_message)
        added.append(user_message)
        if self.runtime.transcript_store is not None:
            self.runtime.transcript_store.append_message(session_id, user_message)
        self.runtime.attach_conversation(session_id, conversation)
        self._conversation_cache[session_id] = conversation

        for step in range(1, self.max_steps + 1):
            definition = self.runtime.get_session_definition(session_id)
            context = self.runtime.get_session(session_id)
            tools = self.tool_adapter.list_tools_for_session(session_id)
            turn = self.model_client.complete(
                agent=definition,
                session=context.session,
                conversation=conversation,
                messages=conversation.snapshot(),
                tools=tools,
            )

            if turn.assistant_message is not None:
                assistant_message = self._normalize_assistant_message(turn.assistant_message)
                self._ensure_message_budget(conversation, incoming_messages=1)
                conversation.messages.append(assistant_message)
                added.append(assistant_message)
                final_message = assistant_message
                if self.runtime.transcript_store is not None:
                    self.runtime.transcript_store.append_message(session_id, assistant_message)
                self.runtime.attach_conversation(session_id, conversation)
                self._persist_conversation_runtime_state(session_id, conversation)

            if not turn.tool_calls:
                self._persist_conversation_runtime_state(session_id, conversation)
                return TerraFinHostedRunResult(
                    session_id=session_id,
                    agent_name=conversation.agent_name,
                    final_message=final_message,
                    messages_added=tuple(added),
                    tool_results=tuple(tool_results),
                    steps=step,
                )

            record_tool_call_history(conversation, turn.tool_calls)
            self.runtime.attach_conversation(session_id, conversation)
            self._persist_conversation_runtime_state(session_id, conversation)
            for tool_call in turn.tool_calls:
                total_tool_calls += 1
                if total_tool_calls > self.max_tool_calls:
                    raise RuntimeError(
                        f"Hosted TerraFin agent loop exceeded max_tool_calls={self.max_tool_calls} "
                        f"for session '{session_id}'."
                    )
                invocation = self.tool_adapter.run_tool(
                    session_id,
                    tool_call.tool_name,
                    tool_call.arguments,
                )
                tool_results.append(invocation)
                tool_message = TerraFinConversationMessage(
                    role="tool",
                    name=tool_call.tool_name,
                    tool_call_id=tool_call.call_id,
                    content=self._serialize_tool_result(invocation),
                    metadata={
                        "executionMode": invocation.execution_mode,
                        "capabilityName": invocation.capability_name,
                    },
                )
                self._ensure_message_budget(conversation, incoming_messages=1)
                conversation.messages.append(tool_message)
                added.append(tool_message)
                if self.runtime.transcript_store is not None:
                    self.runtime.transcript_store.append_message(session_id, tool_message)
                self.runtime.attach_conversation(session_id, conversation)
            self._persist_conversation_runtime_state(session_id, conversation)

        raise RuntimeError(
            f"Hosted TerraFin agent loop exceeded max_steps={self.max_steps} for session '{session_id}'."
        )

    def _ensure_message_budget(
        self,
        conversation: TerraFinHostedConversation,
        *,
        incoming_messages: int,
    ) -> None:
        if len(conversation.messages) + incoming_messages > self.max_messages_per_session:
            raise RuntimeError(
                f"Hosted TerraFin session '{conversation.session_id}' exceeded "
                f"max_messages_per_session={self.max_messages_per_session}."
            )

    def _normalize_assistant_message(
        self,
        message: TerraFinConversationMessage,
    ) -> TerraFinConversationMessage:
        if message.role == "assistant":
            return message
        return TerraFinConversationMessage(
            role="assistant",
            content=message.content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            metadata=dict(message.metadata),
        )

    def _serialize_tool_result(self, invocation: TerraFinToolInvocationResult) -> str:
        payload: dict[str, Any] = {
            "toolName": invocation.tool_name,
            "capabilityName": invocation.capability_name,
            "executionMode": invocation.execution_mode,
            "payload": invocation.payload,
        }
        if invocation.task is not None:
            payload["task"] = {
                "taskId": invocation.task.task_id,
                "status": invocation.task.status,
                "description": invocation.task.description,
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _persist_conversation_runtime_state(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
    ) -> None:
        record = self.runtime.session_store.get(session_id)
        record.metadata[CONVERSATION_STATE_METADATA_KEY] = dict(conversation.metadata)
        self.runtime.session_store.persist(record)
        self._conversation_cache[session_id] = conversation

    def _conversation_runtime_state(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        payload = metadata.get(CONVERSATION_STATE_METADATA_KEY, {})
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    def _merge_conversation_runtime_state(
        self,
        conversation: TerraFinHostedConversation,
        metadata: Mapping[str, Any],
    ) -> None:
        state = self._conversation_runtime_state(metadata)
        if state:
            conversation.metadata.update(state)
        runtime_model = metadata.get(RUNTIME_MODEL_METADATA_KEY)
        if isinstance(runtime_model, dict):
            conversation.metadata[RUNTIME_MODEL_METADATA_KEY] = dict(runtime_model)
