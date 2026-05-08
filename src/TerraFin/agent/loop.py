from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .context_budget import (
    PROMPT_BUDGET_RETRY_LEVELS,
    ContextBudgetManager,
    PromptBudgetLevel,
    is_prompt_budget_error,
)
from .conversation import (
    MessageRole,
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinHostedRunResult,
    TerraFinModelTurn,
    TerraFinToolCall,
    make_text_block,
    make_tool_use_block,
)
from .conversation_state import RUNTIME_MODEL_METADATA_KEY, record_tool_call_history
from .definitions import DEFAULT_HOSTED_AGENT_NAME, TerraFinAgentDefinition
from .hosted_runtime import TerraFinHostedAgentRuntime
from .recovery import RecoveryPolicy, RecoveryTracker
from .runtime import TerraFinAgentSession
from .tool_execution import ToolExecutionEngine
from .tools import TerraFinHostedToolAdapter, TerraFinToolDefinition, TerraFinToolInvocationResult
from .transcript_normalizer import TranscriptNormalizer


CONVERSATION_STATE_METADATA_KEY = "conversationState"


def build_default_system_prompt(definition: TerraFinAgentDefinition) -> str:
    if str(definition.metadata.get("role", "")).strip().lower() == "guru":
        from .personas import build_default_persona_registry, build_guru_system_prompt

        try:
            persona = build_default_persona_registry().get(definition.name)
        except KeyError:
            persona = None
        if persona is not None:
            return build_guru_system_prompt(persona)
    allowed = (
        "all registered TerraFin capabilities"
        if "*" in definition.allowed_capabilities
        else ", ".join(definition.allowed_capabilities)
    )
    return (
        f"You are TerraFin's hosted agent '{definition.name}'. "
        f"{definition.description} "
        f"You are the orchestrator: the user talks to you, and you decide per-turn which tools to call. "
        f"Use TerraFin tools when they materially improve correctness, stay within your allowed capabilities "
        f"({allowed}), and prefer concise research-oriented answers. "
        "VIEW CONTEXT — MANDATORY RULE: NEVER ask the user 'which ticker?', 'what stock?', "
        "'what symbol?', or any equivalent question when their message contains ANY implicit or deictic "
        "reference to a stock — phrases such as 'this stock', 'this company', 'the stock I'm looking at', "
        "'analyze this', 'how does this look', 'what do you think of this', or anything in any language "
        "that refers to what the user is viewing. Instead: call `current_view_context` FIRST, read the "
        "ticker from the returned entities or selection, and proceed with that ticker. "
        "The user is interacting through a UI and almost always has a specific page open; the answer "
        "is already in the view. Only ask for clarification if `current_view_context` returns "
        "`available: false` and there is genuinely no implicit entity in the message. "
        "\n\n"
        "SITUATIONAL AWARENESS: actively listen to the user's messages for personal-context signals "
        "that change what good advice looks like — cost basis ('I bought at $X'), position size relative "
        "to savings ('this is 80% of my portfolio'), investment horizon ('I'm retiring in 2 years'), "
        "tax posture (taxable vs. tax-advantaged account), debt situation, and risk tolerance. "
        "When the user has volunteered these facts, reference them by name in your reply and let them "
        "shape the answer. When a specific fact is MISSING and would materially change your answer, "
        "ask exactly ONE focused follow-up question — do not ask a multi-field questionnaire, do not "
        "fabricate placeholder values, do not proceed on assumed numbers. If the user's emotional tone "
        "reads as anxious or desperate ('I'm about to lose everything', 'please help', 'I can't sleep'), "
        "acknowledge the weight of the moment in your first sentence, slow your pace, and avoid "
        "action-oriented verbs ('sell', 'buy') — surface the tradeoffs rather than prescribing a move. "
        "\n\n"
        "VERBATIM CITATIONS: when you quote from an SEC filing section, copy the exact wording from "
        "the `sec_filing_section` tool result. Do NOT paraphrase risk factors, MD&A language, or "
        "forward-looking statements — quote them verbatim inside quotation marks and cite the section. "
        "Users need to verify what the filing says, not what you think it says. "
        "\n\n"
        "DISCLOSURE: you produce research-oriented analysis, not personalized investment advice. "
        "You cannot place trades, you hold no fiduciary duty, and you may be wrong. Keep replies "
        "grounded in what the tools returned and what the user told you — do not guess prices, "
        "earnings, or numbers you haven't seen in a tool result. "
        "\n\n"
        "INVESTOR-LENS TOOLS: you also have three hidden persona subagents available as tools — "
        "`consult_warren_buffett`, `consult_howard_marks`, `consult_stanley_druckenmiller`. "
        "Each runs a hidden research session in that investor's voice and returns a structured memo "
        "(stance, confidence, thesis, key_evidence, risks, open_questions, citations). "
        "Call one (or more, in parallel) when the user's question benefits from an investor's judgment "
        "rather than a pure factual lookup — e.g. 'is this a good business', 'is it overvalued', "
        "'what's priced in', 'what would [Buffett/Marks/Druckenmiller] say', 'what's the bear case', "
        "'how does the macro backdrop affect this', 'should I worry about downside'. "
        "Do NOT call these for pure lookups (price, filing section fetch, calendar, ticker resolve) — "
        "use the research tools directly. After getting persona memo(s) as tool results, synthesize "
        "your own user-facing reply grounded in those memos; do not dump raw JSON at the user. "
        "Persona routing is YOUR decision based on context — there is no regex gate in front of you."
    )


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
        # The adapter dispatches `consult_<persona>` tool-calls through
        # `self.consult_guru(...)`, so it needs a back-reference to this
        # loop. Plain capability tools don't need the back-reference —
        # they go through runtime.invoke directly.
        self.tool_adapter.attach_loop(self)
        self.system_prompt_builder = system_prompt_builder or build_default_system_prompt
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.max_messages_per_session = max_messages_per_session
        self.transcript_normalizer = TranscriptNormalizer()
        self.context_budget_manager = ContextBudgetManager(normalizer=self.transcript_normalizer)
        self.tool_execution_engine = ToolExecutionEngine(self.tool_adapter)
        self.recovery_policy = RecoveryPolicy()
        self._conversation_cache: dict[str, TerraFinHostedConversation] = {}

    def create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        system_prompt: str | None = None,
        allow_internal: bool = False,
    ) -> TerraFinHostedConversation:
        context = self.runtime.create_session(
            agent_name,
            session_id=session_id,
            metadata=metadata,
            allow_internal=allow_internal,
        )
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
            system_message = TerraFinConversationMessage(
                role="system",
                content=prompt,
                blocks=(make_text_block(prompt),),
            )
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
        self.transcript_normalizer.normalize_loaded_conversation(conversation)
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
        self.transcript_normalizer.normalize_loaded_conversation(conversation)
        self.runtime.attach_conversation(session_id, conversation)
        self._conversation_cache[session_id] = conversation
        return conversation

    def forget_conversation(self, session_id: str) -> None:
        self._conversation_cache.pop(session_id, None)

    def prepare_model_messages(
        self,
        conversation: TerraFinHostedConversation,
        *,
        level: PromptBudgetLevel = "default",
    ) -> tuple[TerraFinConversationMessage, ...]:
        return self.context_budget_manager.prepare_messages(conversation, level=level)

    def complete_model_turn(
        self,
        *,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> TerraFinModelTurn:
        last_prompt_budget_error: Exception | None = None
        preferred_level = self.context_budget_manager.choose_level(conversation)
        levels = (preferred_level,) + tuple(level for level in PROMPT_BUDGET_RETRY_LEVELS if level != preferred_level)
        for level in levels:
            messages = self.prepare_model_messages(conversation, level=level)
            try:
                return self.model_client.complete(
                    agent=agent,
                    session=session,
                    conversation=conversation,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:
                if not is_prompt_budget_error(exc):
                    raise
                last_prompt_budget_error = exc
                continue
        raise RuntimeError(
            "The assistant context exceeded the model limit even after internal compaction. "
            "Please start a new chat or clear recent history and try again."
        ) from last_prompt_budget_error

    def submit_user_message(self, session_id: str, content: str) -> TerraFinHostedRunResult:
        conversation = self.get_conversation(session_id)
        added: list[TerraFinConversationMessage] = []
        tool_results: list[TerraFinToolInvocationResult] = []
        final_message: TerraFinConversationMessage | None = None
        total_tool_calls = 0
        recovery_tracker = RecoveryTracker(self.recovery_policy)

        self._ensure_message_budget(conversation, incoming_messages=1)
        user_message = TerraFinConversationMessage(
            role="user",
            content=content,
            blocks=(make_text_block(content),),
        )
        self._append_conversation_message(conversation, user_message, added=added)

        # No pre-intercept router. The orchestrator agent's own LLM decides
        # when to consult a hidden persona (Buffett / Marks / Druckenmiller)
        # via `consult_<persona>` tool-calls handled by the tool adapter.
        # See `docs/agent/architecture.md#orchestrator--persona-subagents`.

        # Track (tool_name, canonical_args) call counts across this run so we
        # can break LLM loops that re-issue the same tool call step after step.
        tool_call_fingerprint_counts: dict[str, int] = {}
        for step in range(1, self.max_steps + 1):
            definition = self.runtime.get_session_definition(session_id)
            context = self.runtime.get_session(session_id)
            tools = self.tool_adapter.list_tools_for_session(session_id)
            turn = self.complete_model_turn(
                agent=definition,
                session=context.session,
                conversation=conversation,
                tools=tools,
            )

            if turn.assistant_message is not None:
                assistant_message = self._normalize_assistant_message(turn.assistant_message)
                self._append_conversation_message(conversation, assistant_message, added=added)
                final_message = assistant_message

            if turn.tool_calls:
                tool_use_message = self._build_tool_use_message(turn.tool_calls)
                self._append_conversation_message(conversation, tool_use_message, added=added)

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
            self._persist_conversation_runtime_state(session_id, conversation)
            for tool_call in turn.tool_calls:
                total_tool_calls += 1
                if total_tool_calls > self.max_tool_calls:
                    raise RuntimeError(
                        f"Hosted TerraFin agent loop exceeded max_tool_calls={self.max_tool_calls} "
                        f"for session '{session_id}'."
                    )
                fingerprint = _tool_call_fingerprint(tool_call)
                tool_call_fingerprint_counts[fingerprint] = (
                    tool_call_fingerprint_counts.get(fingerprint, 0) + 1
                )
                if tool_call_fingerprint_counts[fingerprint] > 2:
                    # LLM is wedged — calling the same tool with the same args
                    # repeatedly. Short-circuit with a synthetic error nudging
                    # the model to pivot or answer with what it already has,
                    # instead of burning all max_steps on dead repeats.
                    outcome = self.tool_execution_engine.build_loop_guard_outcome(
                        tool_call,
                        count=tool_call_fingerprint_counts[fingerprint],
                    )
                else:
                    outcome = self.tool_execution_engine.execute(session_id, tool_call)
                if outcome.kind == "fatal_error":
                    assert outcome.error is not None
                    raise outcome.error
                assert outcome.invocation is not None
                assert outcome.message is not None
                invocation = outcome.invocation
                tool_results.append(invocation)
                self._append_conversation_message(conversation, outcome.message, added=added)
                if outcome.kind == "retryable_error":
                    fallback_required = recovery_tracker.record(outcome.fingerprint)
                    if not fallback_required:
                        continue
                    fallback_message = self._build_recoverable_tool_error_message(invocation)
                    self._append_conversation_message(conversation, fallback_message, added=added)
                    final_message = fallback_message
                    self._persist_conversation_runtime_state(session_id, conversation)
                    return TerraFinHostedRunResult(
                        session_id=session_id,
                        agent_name=conversation.agent_name,
                        final_message=final_message,
                        messages_added=tuple(added),
                        tool_results=tuple(tool_results),
                        steps=step,
                    )
            self._persist_conversation_runtime_state(session_id, conversation)

        if recovery_tracker.recoverable_error_rounds > 0:
            retryable_invocation = next(
                (result for result in reversed(tool_results) if result.is_error and result.retryable),
                None,
            )
            fallback_message = self._build_recoverable_tool_error_message(retryable_invocation)
            self._append_conversation_message(conversation, fallback_message, added=added)
            final_message = fallback_message
            self._persist_conversation_runtime_state(session_id, conversation)
            return TerraFinHostedRunResult(
                session_id=session_id,
                agent_name=conversation.agent_name,
                final_message=final_message,
                messages_added=tuple(added),
                tool_results=tuple(tool_results),
                steps=self.max_steps,
            )

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
            if message.blocks:
                return message
            return TerraFinConversationMessage(
                role="assistant",
                content=message.content,
                name=message.name,
                tool_call_id=message.tool_call_id,
                metadata=dict(message.metadata),
                blocks=(make_text_block(message.content),) if message.content else (),
            )
        return TerraFinConversationMessage(
            role="assistant",
            content=message.content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            metadata=dict(message.metadata),
            blocks=(make_text_block(message.content),) if message.content else (),
        )

    def _append_conversation_message(
        self,
        conversation: TerraFinHostedConversation,
        message: TerraFinConversationMessage,
        *,
        added: list[TerraFinConversationMessage] | None = None,
    ) -> None:
        self._ensure_message_budget(conversation, incoming_messages=1)
        conversation.messages.append(message)
        if added is not None:
            added.append(message)
        if self.runtime.transcript_store is not None:
            self.runtime.transcript_store.append_message(conversation.session_id, message)
        self.runtime.attach_conversation(conversation.session_id, conversation)
        self._conversation_cache[conversation.session_id] = conversation

    def _build_tool_use_message(
        self,
        tool_calls: tuple[TerraFinToolCall, ...],
    ) -> TerraFinConversationMessage:
        return TerraFinConversationMessage(
            role="assistant",
            content="",
            metadata={"internalOnly": True, "internalToolUse": True},
            blocks=tuple(
                make_tool_use_block(
                    call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                )
                for tool_call in tool_calls
            ),
        )

    def _build_recoverable_tool_error_message(
        self,
        invocation: TerraFinToolInvocationResult | None,
    ) -> TerraFinConversationMessage:
        content = (
            "I couldn't confidently resolve the right symbol or data source from that request. "
            "Try naming a specific ticker or supported macro instrument, or keep the relevant TerraFin page open and ask again."
        )
        metadata: dict[str, Any] = {}
        if invocation is not None and invocation.error_code:
            metadata["internalToolRecovery"] = True
            metadata["recoveryErrorCode"] = invocation.error_code
        return TerraFinConversationMessage(
            role="assistant",
            content=content,
            metadata=metadata,
            blocks=(make_text_block(content),),
        )

    def _persist_conversation_runtime_state(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
    ) -> None:
        record = self.runtime.session_store.get(session_id)
        record.metadata[CONVERSATION_STATE_METADATA_KEY] = dict(conversation.metadata)
        self.runtime.session_store.persist(record)
        self.transcript_normalizer.normalize_loaded_conversation(conversation)
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

    def consult_guru(
        self,
        session_id: str,
        guru_name: str,
        question: str,
    ) -> dict[str, Any]:
        """Spawn a hidden persona subagent and return its structured memo.

        Public entry point for `consult_<persona>` tool-calls from the
        main orchestrator agent. Dispatches to `guru.run_guru_consult`,
        which owns the hidden-session lifecycle and memo-tool contract.

        Hidden-internal sessions (the persona subagents themselves) are
        never allowed to call this method — `TerraFinHostedToolAdapter`
        only registers the `consult_<persona>` tools for non-internal
        agent definitions, so persona subagents cannot recurse.
        """
        from .guru import run_guru_consult

        return run_guru_consult(
            loop=self,
            parent_session_id=session_id,
            guru_name=guru_name,
            question=question,
        )


def _tool_call_fingerprint(tool_call: TerraFinToolCall) -> str:
    """Stable key for 'same tool, same arguments' loop detection.

    Canonicalises the arg mapping by sorted keys so dict ordering differences
    don't defeat the match.
    """
    import json as _json

    try:
        args = _json.dumps(dict(tool_call.arguments or {}), sort_keys=True, default=str)
    except Exception:
        args = repr(tool_call.arguments)
    return f"{tool_call.tool_name}::{args}"
