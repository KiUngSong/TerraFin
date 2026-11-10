import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..contracts.conversation import (
    TOKEN_USAGE_METADATA_KEY,
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinHostedRunResult,
    TerraFinModelTurn,
    TerraFinToolCall,
    make_text_block,
    make_tool_use_block,
)
from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY, record_tool_call_history
from ..contracts.definitions import TerraFinAgentDefinition
from ..contracts.model_client import TerraFinHostedModelClient, TerraFinTurnOptions
from ..contracts.tool_contracts import ASK_USER_TOOL_NAME
from ..models.runtime import TerraFinModelResponseError
from ..tools import TerraFinHostedToolAdapter, TerraFinToolDefinition, TerraFinToolInvocationResult
from ..tools.execution import ToolExecutionEngine
from .context_budget import (
    PROMPT_BUDGET_RETRY_LEVELS,
    ContextBudgetManager,
    PromptBudgetLevel,
    is_prompt_budget_error,
    truncate_text,
)
from .hooks import TerraFinTurnHook, default_turn_hooks
from .hosted import TerraFinHostedAgentRuntime
from .recovery import RecoveryPolicy, RecoveryTracker
from .session import TerraFinAgentSession
from .tool_batch import run_tool_batch
from .transcript_normalizer import COMPLETION_REPORT_METADATA_KEY, TranscriptNormalizer


_logger = logging.getLogger(__name__)

CONVERSATION_STATE_METADATA_KEY = "conversationState"
USAGE_TOTALS_METADATA_KEY = "usageTotals"
# Set on the reply of a turn that did not end on its own: "interrupted" when the
# user stopped it, "length" when the reply is cut at the output limit, and
# "step_limit" when the last step had to answer with tools off.
TURN_ENDING_METADATA_KEY = "turnEnding"
# The question an `ask_user` call put to the user, with its options, on the reply that ends the turn.
ASK_USER_METADATA_KEY = "askUser"
# The token usage of every model call in the turn, summed onto its final reply.
TURN_TOKEN_USAGE_METADATA_KEY = "turnTokenUsage"

# A text reply cut at the output limit is continued this many times before the
# partial is returned as the answer.
MAX_LENGTH_CONTINUATIONS = 2

# Characters of a result shown in its completion note: a report's head, or any other result's JSON.
_SUMMARY_PREVIEW_CHARS = 1500

# The last step cannot run tools, so it asks for an answer from what is in hand.
# Sent as pinned context, never as a system message the budget could drop.
_WRAP_UP_OPTIONS = TerraFinTurnOptions(
    tool_choice="none",
    pinned_context=(
        "This is the last step of the turn and no tool can run. Answer the user now from the tool "
        "results already in the conversation: state what is established, citing the tool result or "
        "filing behind each fact; what is still missing; and which data to fetch next to close the gap."
    ),
)
# A last step that continues a cut-off reply only finishes that reply.
_NO_TOOLS_OPTIONS = TerraFinTurnOptions(tool_choice="none")

# The reply of a stopped turn whose last step wrote no text.
_STOPPED_TEXT = "Stopped at your request before an answer was written."

_CONTINUE_NOTE = (
    "Your previous reply was cut off at the output limit. Continue exactly where it stopped. "
    "Do not repeat or recap what you already wrote."
)


def build_default_system_prompt(definition: TerraFinAgentDefinition) -> str:
    if str(definition.metadata.get("role", "")).strip().lower() == "guru":
        from ..guru.personas import build_default_persona_registry, build_guru_system_prompt

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
        "FINANCIAL WRITING QUALITY: when producing financial content (analysis, summaries, briefs): "
        "(1) FORMAT COMPLIANCE — if the user specifies an exact output format with placeholders or bullet patterns, fill it precisely. Do not add sections, headers, or paragraphs outside the specified format. "
        "(2) DECLARATIVE OVER INTERROGATIVE — in Korean financial writing, use declarative form (X가 Y했다, X이다) not question form (X했을까요?, 어떻게 될까요?). Questions signal uncertainty; declarations signal authority. "
        "(3) CAUSAL CHAINS — when explaining market moves, state the full chain: [trigger] → [mechanism] → [market effect]. Never stop at just naming the trigger. "
        "(4) NO VAGUE HEDGING — '할 수 있습니다', '가능성이 있습니다', '예상됩니다' weaken every sentence. Use them only when the uncertainty is the actual point. Replace with: X가 Y를 넘으면 Z가 발생한다. "
        "(5) SPECIFICITY — every claim about a stock, index, or indicator must include the actual number from your data. '크게 상승했습니다' is unacceptable if you have the exact percentage. "
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
        max_parallel_tool_calls: int = 1,
        hooks: tuple[TerraFinTurnHook, ...] | None = None,
    ) -> None:
        self.runtime = runtime
        self.model_client = model_client
        runtime.bind_turn_runner(self.complete_model_turn)
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
        # Above 1, a run of read-only calls in one batch shares this many threads.
        self.max_parallel_tool_calls = max_parallel_tool_calls
        self.transcript_normalizer = TranscriptNormalizer()
        self.context_budget_manager = ContextBudgetManager(normalizer=self.transcript_normalizer)
        self.tool_execution_engine = ToolExecutionEngine(self.tool_adapter)
        self.recovery_policy = RecoveryPolicy()
        self._conversation_cache: dict[str, TerraFinHostedConversation] = {}
        # The transcript store's `updated_at` that each cached conversation
        # matches. Another writer on the same store moves it, and the cache is
        # then reloaded rather than served.
        self._transcript_stamps: dict[str, datetime | None] = {}
        self._cache_lock = threading.RLock()
        self.hooks = default_turn_hooks(self) if hooks is None else tuple(hooks)
        self._owned_metadata_tags: frozenset[str] = frozenset().union(*self._call_hooks("owned_metadata_tags"))

    def _call_hooks(self, method: str, *args: Any) -> list[Any]:
        """Every hook's non-None result of `method`."""
        return [result for hook in self.hooks if (result := self._call_hook(hook, method, *args)) is not None]

    def _call_hook(self, hook: TerraFinTurnHook, method: str, *args: Any) -> Any:
        """A hook without `method` is a no-op. A hook that raises is logged and yields None."""
        call = getattr(hook, method, None)
        if call is None:
            return None
        try:
            return call(*args)
        except Exception:
            _logger.exception("Turn hook %s.%s raised; skipping it.", type(hook).__name__, method)
            return None

    def _turn_options(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
        turn_states: list[tuple[TerraFinTurnHook, Any]],
        base: TerraFinTurnOptions | None,
    ) -> TerraFinTurnOptions | None:
        """`base` with the hooks' pinned text ahead of its own, or None when both are empty."""
        parts = [
            self._call_hook(hook, "pinned_context", session_id, conversation, state) for hook, state in turn_states
        ]
        hook_text = "\n\n".join(part for part in parts if part)
        pinned = "\n\n".join(part for part in [hook_text, base.pinned_context if base else ""] if part)
        if not pinned:
            return base
        return replace(base or TerraFinTurnOptions(), pinned_context=pinned)

    def _is_hook_owned(self, message: TerraFinConversationMessage) -> bool:
        return any(message.metadata.get(tag) for tag in self._owned_metadata_tags)

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
        with self._cache_lock:
            self._conversation_cache[conversation.session_id] = conversation
            self._transcript_stamps[conversation.session_id] = self._transcript_stamp(conversation.session_id)
        self._persist_conversation_runtime_state(conversation.session_id, conversation)
        return conversation

    def get_conversation(self, session_id: str) -> TerraFinHostedConversation:
        """The session's conversation, reloaded when the store has moved past the cache.

        Every entry point reads through here, so a turn appended by another
        process is picked up before the next turn runs or is served.
        """
        record = self.runtime.get_session_record(session_id)
        with self._cache_lock:
            stamp = self._transcript_stamp(session_id)
            cached = self._conversation_cache.get(session_id)
            if cached is not None and self._transcript_stamps.get(session_id) == stamp:
                self._merge_conversation_runtime_state(cached, record.metadata)
                self.runtime.attach_conversation(session_id, cached)
                return cached
            if self.runtime.transcript_store is None or not self.runtime.transcript_store.session_exists(session_id):
                raise KeyError(f"Unknown TerraFin hosted conversation: {session_id}")
            # Stamp read before the load: a write landing in between leaves the
            # cache marked stale, never marked fresh.
            conversation = self.runtime.transcript_store.load_conversation(
                session_id,
                metadata=self._conversation_runtime_state(record.metadata),
            )
            self.transcript_normalizer.normalize_loaded_conversation(conversation)
            self.runtime.attach_conversation(session_id, conversation)
            self._conversation_cache[session_id] = conversation
            self._transcript_stamps[session_id] = stamp
            return conversation

    def forget_conversation(self, session_id: str) -> None:
        with self._cache_lock:
            self._conversation_cache.pop(session_id, None)
            self._transcript_stamps.pop(session_id, None)

    def _transcript_stamp(self, session_id: str) -> datetime | None:
        store = self.runtime.transcript_store
        if store is None:
            return None
        try:
            return store.get_session_index(session_id).updated_at
        except KeyError:
            return None

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
        turn, _ = self._complete_model_turn_at_level(
            agent=agent, session=session, conversation=conversation, tools=tools
        )
        return turn

    def _complete_model_turn_at_level(
        self,
        *,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        tools: tuple[TerraFinToolDefinition, ...],
        options: TerraFinTurnOptions | None = None,
    ) -> tuple[TerraFinModelTurn, PromptBudgetLevel]:
        """The turn and the budget level its prompt was sent at.

        `options` is passed only when set, so a client without the parameter
        still serves every default turn.
        """
        last_prompt_budget_error: Exception | None = None
        preferred_level = self.context_budget_manager.choose_level(conversation)
        # A retry only moves to a tighter level than the one rejected.
        levels = PROMPT_BUDGET_RETRY_LEVELS[PROMPT_BUDGET_RETRY_LEVELS.index(preferred_level) :]
        for level in levels:
            messages = self.prepare_model_messages(conversation, level=level)
            try:
                turn = self.model_client.complete(
                    agent=agent,
                    session=session,
                    conversation=conversation,
                    messages=messages,
                    tools=tools,
                    **({"options": options} if options is not None else {}),
                )
            except Exception as exc:
                if not is_prompt_budget_error(exc):
                    raise
                last_prompt_budget_error = exc
                continue
            if turn.usage is not None:
                _add_usage_totals(conversation, turn.usage.to_payload())
            return turn, level
        raise RuntimeError(
            "The assistant context exceeded the model limit even after internal compaction. "
            "Please start a new chat or clear recent history and try again."
        ) from last_prompt_budget_error

    def submit_user_message(self, session_id: str, content: str) -> TerraFinHostedRunResult:
        started_at = datetime.now(UTC)

        def stop_requested() -> bool:
            # A failed read of the stop flag counts as no stop: the flag never ends a turn by itself.
            try:
                return self.runtime.turn_interrupt_requested(session_id, since=started_at)
            except Exception:
                _logger.warning("Reading the stop flag of session %s failed.", session_id, exc_info=True)
                return False

        conversation = self.get_conversation(session_id)
        # The session cap is checked here, once, and never on an append: a turn
        # that has started must be able to close every tool call it opens.
        self._ensure_message_budget(conversation, incoming_messages=1)
        added: list[TerraFinConversationMessage] = []
        tool_results: list[TerraFinToolInvocationResult] = []
        final_message: TerraFinConversationMessage | None = None
        total_tool_calls = 0
        recovery_tracker = RecoveryTracker(self.recovery_policy)

        # Deferred-completion delivery: before the model sees this turn, drain
        # any background tasks (e.g. deep_research) that finished while the user
        # was away and inject their reports into the transcript so the
        # orchestrator integrates them and can answer follow-ups. See
        # `docs/harness/hosted-runtime.md`.
        self._drain_pending_completions(session_id, conversation, added=added)

        # A hook re-adds what it owns each turn, so last turn's copy is dropped
        # first, whether or not the hook still adds one.
        conversation.messages[:] = [message for message in conversation.messages if not self._is_hook_owned(message)]
        hook_start = len(conversation.messages)
        turn_states = [
            (hook, self._call_hook(hook, "before_turn", session_id, content, conversation)) for hook in self.hooks
        ]
        added.extend(conversation.messages[hook_start:])

        user_message = TerraFinConversationMessage(
            role="user",
            content=content,
            blocks=(make_text_block(content),),
        )
        self._append_conversation_message(conversation, user_message, added=added)

        # No pre-intercept router. The orchestrator agent's own LLM decides
        # when to consult a hidden persona (Buffett / Marks / Druckenmiller)
        # via `consult_<persona>` tool-calls handled by the tool adapter.
        # See `docs/harness/architecture.md#orchestrator--persona-subagents`.

        # Track (tool_name, canonical_args) call counts across this run so we
        # can break LLM loops that re-issue the same tool call step after step.
        tool_call_fingerprint_counts: dict[str, int] = {}
        length_stops = 0
        continued_parts: list[str] = []
        # A stop makes the next step the last: a model call already running is
        # never aborted, and the wrap-up answers from what the turn has gathered.
        interrupted = False
        turn_usage: dict[str, int] = {}
        for step in range(1, self.max_steps + 1):
            interrupted = interrupted or stop_requested()
            last_step = step == self.max_steps or interrupted
            wrap_up = last_step and not length_stops
            definition = self.runtime.get_session_definition(session_id)
            context = self.runtime.get_session(session_id)
            tools = self.tool_adapter.list_tools_for_session(session_id)
            options = self._turn_options(
                session_id,
                conversation,
                turn_states,
                (_NO_TOOLS_OPTIONS if length_stops else _WRAP_UP_OPTIONS) if last_step else None,
            )
            turn, level = self._complete_model_turn_at_level(
                agent=definition,
                session=context.session,
                conversation=conversation,
                tools=tools,
                options=options,
            )
            if turn.usage is not None:
                turn_usage = {key: turn_usage.get(key, 0) + value for key, value in turn.usage.to_payload().items()}
            # The turn's first message anchors the measured prompt size for later budgeting.
            usage_metadata = (
                {TOKEN_USAGE_METADATA_KEY: {**turn.usage.to_payload(), "promptLevel": level}}
                if turn.usage is not None
                else {}
            )

            # No step remains to read a result, so a call made on the last step
            # is dropped unrun.
            tool_calls = () if last_step else turn.tool_calls
            if not tool_calls and not _has_text(turn.assistant_message):
                if turn.tool_calls:
                    break
                # An empty, blocked or cut-off reply is a failed completion,
                # never a finished turn with nothing to show.
                raise TerraFinModelResponseError(
                    f"The model returned an empty reply (stop_reason={turn.stop_reason!r}). "
                    "Please send your message again."
                )

            cut_off = turn.stop_reason == "length"
            length_stops = length_stops + 1 if cut_off and not tool_calls else 0
            continuing = length_stops > 0 and length_stops <= MAX_LENGTH_CONTINUATIONS and not last_step

            if turn.assistant_message is not None:
                truncated = {"truncated": True} if length_stops > 0 and not continuing else {}
                ending = "interrupted" if interrupted else "length" if truncated else "step_limit" if wrap_up else ""
                assistant_message = _with_metadata(
                    self._normalize_assistant_message(turn.assistant_message),
                    {
                        **usage_metadata,
                        **truncated,
                        **({TURN_ENDING_METADATA_KEY: ending} if ending else {}),
                        **(_turn_usage_metadata(turn_usage) if not tool_calls and not continuing else {}),
                    },
                )
                usage_metadata = {}
                self._append_conversation_message(conversation, assistant_message, added=added)
                final_message = assistant_message
                # A continued reply is returned whole. The transcript keeps its parts.
                if continuing:
                    continued_parts.append(assistant_message.content)
                elif continued_parts:
                    whole = "".join([*continued_parts, assistant_message.content])
                    final_message = replace(assistant_message, content=whole, blocks=(make_text_block(whole),))
            if not continuing:
                continued_parts = []

            if tool_calls:
                tool_use_message = _with_metadata(self._build_tool_use_message(tool_calls), usage_metadata)
                self._append_conversation_message(conversation, tool_use_message, added=added)

            if continuing:
                self._append_conversation_message(conversation, _build_continuation_note(), added=added)
                self._persist_conversation_runtime_state(session_id, conversation)
                continue

            if not tool_calls:
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
            batch = run_tool_batch(
                self,
                session_id,
                conversation,
                turn.tool_calls,
                tool_call_count=total_tool_calls,
                fingerprint_counts=tool_call_fingerprint_counts,
                recovery_tracker=recovery_tracker,
                added=added,
                cut_off=cut_off,
                max_parallel=self.max_parallel_tool_calls,
                interrupted=stop_requested,
            )
            interrupted = batch.interrupted
            total_tool_calls = batch.tool_call_count
            tool_results.extend(batch.invocations)
            if batch.error is not None:
                raise batch.error
            if batch.recovery_exhausted:
                # No step follows, so a stop the batch saw or one requested since is marked here.
                stopped = {TURN_ENDING_METADATA_KEY: "interrupted"} if interrupted or stop_requested() else {}
                fallback_message = _with_metadata(
                    self._build_recoverable_tool_error_message(batch.retryable_invocation),
                    {**stopped, **_turn_usage_metadata(turn_usage)},
                )
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
            # A question to the user ends the turn. Its answer arrives as the next user message.
            asked = next(
                (
                    result
                    for result in batch.invocations
                    if result.tool_name == ASK_USER_TOOL_NAME and not result.is_error
                ),
                None,
            )
            if asked is not None:
                question = str(asked.payload.get("question") or "")
                final_message = TerraFinConversationMessage(
                    role="assistant",
                    content=question,
                    metadata={
                        ASK_USER_METADATA_KEY: {
                            "question": question,
                            "options": list(asked.payload.get("options") or []),
                        },
                        **_turn_usage_metadata(turn_usage),
                    },
                    blocks=(make_text_block(question),),
                )
                self._append_conversation_message(conversation, final_message, added=added)
                self._persist_conversation_runtime_state(session_id, conversation)
                return TerraFinHostedRunResult(
                    session_id=session_id,
                    agent_name=conversation.agent_name,
                    final_message=final_message,
                    messages_added=tuple(added),
                    tool_results=tuple(tool_results),
                    steps=step,
                )

        # Reached only when the last step called tools and wrote no text.
        if interrupted:
            final_message = TerraFinConversationMessage(
                role="assistant",
                content=_STOPPED_TEXT,
                metadata={TURN_ENDING_METADATA_KEY: "interrupted", **_turn_usage_metadata(turn_usage)},
                blocks=(make_text_block(_STOPPED_TEXT),),
            )
            self._append_conversation_message(conversation, final_message, added=added)
            self._persist_conversation_runtime_state(session_id, conversation)
            return TerraFinHostedRunResult(
                session_id=session_id,
                agent_name=conversation.agent_name,
                final_message=final_message,
                messages_added=tuple(added),
                tool_results=tuple(tool_results),
                steps=step,
            )
        if recovery_tracker.recoverable_error_rounds > 0:
            retryable_invocation = next(
                (result for result in reversed(tool_results) if result.is_error and result.retryable),
                None,
            )
            fallback_message = _with_metadata(
                self._build_recoverable_tool_error_message(retryable_invocation), _turn_usage_metadata(turn_usage)
            )
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

        raise TerraFinModelResponseError(
            f"The model called tools on the last of max_steps={self.max_steps} steps instead of answering "
            f"(session '{session_id}'). Please send your message again."
        )

    def _ensure_message_budget(
        self,
        conversation: TerraFinHostedConversation,
        *,
        incoming_messages: int,
    ) -> None:
        # Hook-owned messages are stripped before the user turn is appended,
        # so they never count against the cap.
        kept = sum(1 for message in conversation.messages if not self._is_hook_owned(message))
        if kept + incoming_messages > self.max_messages_per_session:
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

    def _close_unresolved_tool_calls(
        self,
        conversation: TerraFinHostedConversation,
        tool_calls: tuple[TerraFinToolCall, ...],
        *,
        since: int,
        stopped_on: str,
        error: BaseException,
        added: list[TerraFinConversationMessage] | None = None,
    ) -> None:
        """Give every call in the batch its result before the run aborts.

        Answered-ness is read from the conversation from `since` on, never from
        a set kept alongside it: an append that half-succeeds leaves the message
        in the conversation, and a second result for the same call would reach
        the model as two contradictory answers. The bound matters as much — call
        ids are not guaranteed unique across steps, and an earlier turn's answer
        must not mark this call answered.

        Best effort by construction: this runs while another exception is
        propagating, so an append that fails here is dropped rather than
        allowed to replace the cause and re-open the gap being closed.
        """
        answered = {message.tool_call_id for message in conversation.messages[since:] if message.role == "tool"}
        cause = f"{type(error).__name__}: {error}"
        for tool_call in tool_calls:
            if tool_call.call_id in answered:
                continue
            reason = (
                cause
                if tool_call.call_id == stopped_on
                else f"Never executed: the turn stopped on another call in this batch ({cause})."
            )
            message = self.tool_execution_engine.build_unresolved_result_message(
                tool_call,
                reason=reason,
            )
            try:
                self._append_conversation_message(conversation, message, added=added)
            except Exception:
                continue
            answered.add(tool_call.call_id)

    def _append_conversation_message(
        self,
        conversation: TerraFinHostedConversation,
        message: TerraFinConversationMessage,
        *,
        added: list[TerraFinConversationMessage] | None = None,
    ) -> None:
        session_id = conversation.session_id
        conversation.messages.append(message)
        if added is not None:
            added.append(message)
        with self._cache_lock:
            if self.runtime.transcript_store is not None:
                # Adopt the post-append stamp only if this copy was current
                # before it. Otherwise a foreign write would be absorbed into
                # this stamp and never reloaded.
                in_sync = self._transcript_stamps.get(session_id) == self._transcript_stamp(session_id)
                self.runtime.transcript_store.append_message(session_id, message)
                if in_sync:
                    self._transcript_stamps[session_id] = self._transcript_stamp(session_id)
            self.runtime.attach_conversation(session_id, conversation)
            self._conversation_cache[session_id] = conversation

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
                    provider_data=tool_call.provider_data,
                )
                for tool_call in tool_calls
            ),
        )

    def _drain_pending_completions(
        self,
        session_id: str,
        conversation: TerraFinHostedConversation,
        *,
        added: list[TerraFinConversationMessage],
    ) -> None:
        """Deliver background-task completions queued since the last turn.

        Peek-then-clear: a marker is only cleared AFTER its delivery message is
        durably appended to the transcript, so a mid-drain failure (message
        budget, etc.) leaves the marker intact for redelivery next turn — no
        silent loss, no half-appended orphan. If the session was
        deleted/archived, the drain is a graceful no-op.

        Delivery is deduped by taskId twice over: `INSERT OR IGNORE` collapses
        duplicate markers at the store, and here a marker whose note already
        exists in the transcript is skipped-and-cleared. This keeps a re-claimed
        task or a clear that didn't commit last turn from re-appending the note.

        Each completion is delivered as a single USER-role context message (a
        background-note) carrying a bounded summary of the report and a pointer
        to the full report, which `read_tool_result(task_id=...)` reads. Unlike a synthesized tool_use /
        tool_result pair, a user message is forwarded verbatim by every provider
        adapter (OpenAI Responses drops assistant/tool_use turns and only sends
        user messages + function_call_output — a fabricated function_call_output
        with no matching server-side function_call is rejected with HTTP 400).
        `internalOnly` hides it from the UI transcript but not from the model.
        """
        try:
            markers = self.runtime.session_store.peek_pending_completions(session_id)
        except KeyError:
            return
        if not markers:
            return
        delivered_task_ids = {
            str(message.metadata.get("taskId") or "").strip()
            for message in conversation.snapshot()
            if message.metadata.get("internalCompletionDelivery")
        }
        for marker in markers:
            task_id = str(marker.get("taskId") or "").strip()
            if task_id and task_id in delivered_task_ids:
                # Already delivered in a prior turn (e.g. a clear that never
                # committed). Drop the stale marker without re-appending.
                self.runtime.session_store.clear_pending_completions(session_id, task_ids=(task_id,))
                continue
            note_message = self._build_completion_delivery_message(marker)
            self._append_conversation_message(conversation, note_message, added=added)
            # A background task's model turns count toward the session that started it.
            result = marker.get("result")
            task_usage = result.get("usage") if isinstance(result, Mapping) else None
            if isinstance(task_usage, Mapping):
                _add_usage_totals(conversation, task_usage)
            if task_id:
                delivered_task_ids.add(task_id)
                self.runtime.session_store.clear_pending_completions(session_id, task_ids=(task_id,))
            self._call_hooks("after_completion", session_id, marker, marker.get("result"))
        self._persist_conversation_runtime_state(session_id, conversation)

    def _build_completion_delivery_message(
        self,
        marker: Mapping[str, Any],
    ) -> TerraFinConversationMessage:
        capability_name = str(marker.get("capabilityName") or "deep_research")
        task_id = str(marker.get("taskId") or "")
        report = marker.get("result")
        if isinstance(report, Mapping) and "error" in report:
            content = (
                "[Automated system note: background task failed]\n\n"
                f"A background TerraFin '{capability_name}' task the user started earlier failed. "
                "In your reply to the user's next message, tell them it failed and that they can start it again.\n\n"
                f"Error: {truncate_text(json.dumps(report['error'], ensure_ascii=False), 500)}"
            )
        else:
            # The pointer comes before the summary so a cut that keeps only the
            # head of the note still says where the full report is.
            content = (
                "[Automated system note — background research completed]\n\n"
                f"A background TerraFin '{capability_name}' task the user started earlier has finished. "
                "Integrate its findings into your reply to the user's next message; do not re-run the task.\n"
                f'Full report: read_tool_result(task_id="{task_id}"). Read it before quoting a figure, '
                "a gap or a source this summary does not show.\n\n"
                f"{_report_summary(report)}"
            )
        return TerraFinConversationMessage(
            role="user",
            content=content,
            metadata={
                "internalOnly": True,
                "internalCompletionDelivery": True,
                "capabilityName": capability_name,
                "taskId": marker.get("taskId"),
                COMPLETION_REPORT_METADATA_KEY: report,
            },
            blocks=(make_text_block(content),),
        )

    def _build_recoverable_tool_error_message(
        self,
        invocation: TerraFinToolInvocationResult | None,
    ) -> TerraFinConversationMessage:
        last_error = ""
        if invocation is not None and invocation.error_message:
            last_error = f" The last error was: {truncate_text(invocation.error_message, 300)}"
        content = (
            f"I couldn't complete that request because the tools I called kept returning errors.{last_error} "
            "Try rephrasing it, for example by naming a specific ticker or supported macro instrument, "
            "or keep the relevant TerraFin page open and ask again."
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
        from ..guru import run_guru_consult

        return run_guru_consult(
            loop=self,
            parent_session_id=session_id,
            guru_name=guru_name,
            question=question,
        )


def _report_summary(report: Any) -> str:
    """Title, status, the run's counts and the head of the report, bounded in size.

    The report is written from web pages, so its text is fenced as untrusted.
    A result without a report is not a research report and shows as a JSON head.
    """
    if not isinstance(report, Mapping):
        return "(no report)"
    if not isinstance(report.get("report"), str):
        return truncate_text(json.dumps(report, ensure_ascii=False), _SUMMARY_PREVIEW_CHARS)
    from ..deepresearch.reader import UNTRUSTED_SOURCE_NOTE, untrusted_source

    lines = [
        UNTRUSTED_SOURCE_NOTE,
        f"Title: {truncate_text(str(report.get('title') or ''), 200)}",
        f"Status: {report.get('status') or 'unknown'} ({truncate_text(str(report.get('stopReason') or ''), 120)})",
        f"Turns: {report.get('turns')}, tool calls: {report.get('toolCalls')}, reviews: {len(report.get('reviews') or ())}",
        "Report head:",
        untrusted_source("deep-research-report", truncate_text(report["report"], _SUMMARY_PREVIEW_CHARS)),
    ]
    return "\n".join(lines)


def _with_metadata(message: TerraFinConversationMessage, metadata: Mapping[str, Any]) -> TerraFinConversationMessage:
    return replace(message, metadata={**message.metadata, **metadata}) if metadata else message


def _turn_usage_metadata(turn_usage: Mapping[str, int]) -> dict[str, Any]:
    return {TURN_TOKEN_USAGE_METADATA_KEY: dict(turn_usage)} if turn_usage else {}


def _add_usage_totals(conversation: TerraFinHostedConversation, usage: Mapping[str, int]) -> None:
    totals = conversation.metadata.get(USAGE_TOTALS_METADATA_KEY)
    totals = totals if isinstance(totals, dict) else {}
    conversation.metadata[USAGE_TOTALS_METADATA_KEY] = {
        **totals,
        **{key: int(totals.get(key) or 0) + int(value) for key, value in usage.items()},
    }


def _build_continuation_note() -> TerraFinConversationMessage:
    return TerraFinConversationMessage(
        role="user",
        content=_CONTINUE_NOTE,
        metadata={"internalOnly": True, "internalContinuation": True},
        blocks=(make_text_block(_CONTINUE_NOTE),),
    )


def _has_text(message: TerraFinConversationMessage | None) -> bool:
    if message is None:
        return False
    if message.content.strip():
        return True
    return any(block.kind == "text" and str(block.payload.get("text") or "").strip() for block in message.blocks)
