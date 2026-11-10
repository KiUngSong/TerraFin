"""The `deep_research` capability: the research agent loop run as a background task.

The loop's model turns go through the parent session's model client on a
hidden child session. Its TerraFin data tools go through `task.call`, which
records them with the task's activity. The run heartbeats on every tool call,
stops at a cancel, and resumes from its last saved turn.
"""

import os
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Optional, Sequence

from ..deepresearch.agent import Budget, Message, ModelTurn, ReaderFetch, Toolbox, ToolCall, ToolSpec, research


if TYPE_CHECKING:
    from .capability import TerraFinCapability
    from .tasks import TerraFinTaskContext


# Categories whose read-only capabilities the research model may call.
_DATA_CATEGORIES = frozenset(
    {"market_macro", "fundamentals_valuation", "filings_research", "sentiment_regime", "screening_patterns"}
)

# Caller-set safety caps. The model sees its spend against them every turn.
_CAP_ENVS = {
    "max_tokens": ("TERRAFIN_AGENT_DEEPRESEARCH_MAX_TOKENS", 3_000_000),
    "max_seconds": ("TERRAFIN_AGENT_DEEPRESEARCH_MAX_SECONDS", 1800),
    "max_tool_calls": ("TERRAFIN_AGENT_DEEPRESEARCH_MAX_TOOL_CALLS", 200),
    # Set it to fit the model's context window: a character is about a quarter of a token.
    "max_context_chars": ("TERRAFIN_AGENT_DEEPRESEARCH_MAX_CONTEXT_CHARS", 500_000),
}
# A "provider/model" ref for the reviewer. Unset, the reviewer runs on the researcher's model.
_REVIEW_MODEL_ENV = "TERRAFIN_AGENT_DEEPRESEARCH_REVIEW_MODEL"
_RESULT_CHARS = 60_000


def research_budget(env: Mapping[str, str] = os.environ) -> Budget:
    caps: dict[str, Any] = {}
    for field_name, (name, default) in _CAP_ENVS.items():
        raw = str(env.get(name, "")).strip()
        if raw and not raw.isdigit():
            raise ValueError(f"{name} must be a positive whole number, got {raw!r}.")
        caps[field_name] = int(raw) if raw else default
    if caps["max_context_chars"] < 2 * _RESULT_CHARS:
        # A smaller cap elides a full-size result in the turn it arrives, so the model never reads it.
        raise ValueError(f"TERRAFIN_AGENT_DEEPRESEARCH_MAX_CONTEXT_CHARS must be at least {2 * _RESULT_CHARS:,}.")
    return Budget(**caps, max_result_chars=_RESULT_CHARS)


def data_tool_specs(capabilities: Iterable["TerraFinCapability"]) -> tuple[ToolSpec, ...]:
    """The read-only data capabilities, as tools the research model can call."""
    from ..contracts.tool_contracts import get_hosted_tool_contract

    specs = []
    for capability in capabilities:
        if capability.category not in _DATA_CATEGORIES or capability.side_effecting or capability.background_only:
            continue
        specs.append(
            ToolSpec(
                capability.name, capability.description, get_hosted_tool_contract(capability.name)["input_schema"]
            )
        )
    return tuple(specs)


class HostedResearchModel:
    """Runs each research turn on the agent's own model, through its provider.

    The provider is called directly, not through the hosted loop's turn, so the
    loop's own context management is the only one: the hosted prompt budget
    would cut tool results and drop the question. The turns run on a hidden
    session that is never stored. Each loop (researcher, reviewer) keeps its own
    provider state across turns, keyed by its system prompt. Token usage is
    summed in `usage`.
    """

    def __init__(self, task: "TerraFinTaskContext", model_client: Any = None) -> None:
        from datetime import UTC, datetime

        from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY
        from ..contracts.definitions import DEFAULT_HOSTED_AGENT_NAME, build_default_agent_definition_registry
        from .session import TerraFinAgentSession

        self._session = TerraFinAgentSession(
            session_id=f"deep-research:{task.task_id}",
            metadata={"origin": "deep_research", "hiddenInternal": True, "parentSessionId": task.session_id},
        )
        if model_client is None:
            # The parent session's model, through the hosted loop's own client when one is bound.
            loop = getattr(task.model_turn, "__self__", None)
            model_client = getattr(loop, "model_client", None)
            if model_client is not None:
                try:
                    parent = loop.runtime.get_session(task.session_id).session
                except KeyError:  # the parent session expired: run on the client's default model
                    parent = None
                runtime_model = model_client.describe_runtime_model(session=parent)
                self._session.metadata[RUNTIME_MODEL_METADATA_KEY] = runtime_model.to_payload()
            else:
                from ..models.runtime import TerraFinProviderRoutedModelClient
                from ..service.hosted import build_hosted_model_provider_registry

                registry = build_hosted_model_provider_registry()
                model_client = TerraFinProviderRoutedModelClient(
                    registry=registry, default_model=registry.resolve_default_model_ref()
                )
        self._client = model_client
        self._agent = build_default_agent_definition_registry().get(DEFAULT_HOSTED_AGENT_NAME)
        self._provider_state: dict[str, dict[str, Any]] = {}
        # Each transcript position keeps the timestamp it was first sent with, so a
        # provider that resumes from the last message it sent sees only new ones.
        self._stamps: dict[str, dict[tuple[int, int], Any]] = {}
        self._epoch = datetime.now(UTC)
        self._clock = 0
        self.usage: dict[str, int] = {}

    def _stamp(self, system: str, key: Optional[tuple[int, int]]) -> Any:
        from datetime import timedelta

        stamps = self._stamps.setdefault(system, {})
        if key is not None and key in stamps:
            return stamps[key]
        self._clock += 1
        stamp = self._epoch + timedelta(microseconds=self._clock)
        if key is not None:
            stamps[key] = stamp
        return stamp

    def turn(self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelTurn:
        from ..contracts.conversation import TerraFinHostedConversation
        from ..tools import TerraFinToolDefinition

        conversation = TerraFinHostedConversation(
            session_id=self._session.session_id,
            agent_name=self._agent.name,
            metadata=self._provider_state.setdefault(system, {}),
        )
        conversation.messages.extend(_conversation_messages(system, messages, self._stamp))
        definitions = tuple(
            TerraFinToolDefinition(
                name=tool.name,
                capability_name=tool.name,
                description=tool.description,
                input_schema=tool.parameters,
                metadata={"internalOnly": True, "role": "deepResearch"},
            )
            for tool in tools
        )
        turn = self._client.complete(
            agent=self._agent,
            session=self._session,
            conversation=conversation,
            messages=tuple(conversation.messages),
            tools=definitions,
        )
        usage = turn.usage.to_payload() if turn.usage is not None else {}
        for key, value in usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        assistant = turn.assistant_message
        return ModelTurn(
            text=assistant.content if assistant is not None else "",
            calls=tuple(
                ToolCall(c.call_id, c.tool_name, dict(c.arguments), dict(c.provider_data)) for c in turn.tool_calls
            ),
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            cut_off=turn.stop_reason == "length",
            meta=dict(assistant.metadata) if assistant is not None else {},
        )


def _conversation_messages(
    system: str, messages: Sequence[Message], stamp: Callable[[str, Optional[tuple[int, int]]], Any]
) -> list[Any]:
    """The transcript as hosted conversation messages.

    An assistant turn's text and its tool calls become two messages, as the
    hosted loop stores them, so a provider replays both. The last message is the
    budget line, new every turn, so it never keeps a timestamp.
    """
    from ..contracts.conversation import (
        TerraFinConversationMessage,
        make_text_block,
        make_tool_result_block,
        make_tool_use_block,
    )

    def at(index: int, part: int) -> Any:
        return stamp(system, None if index == len(messages) - 1 else (index, part))

    out = [
        TerraFinConversationMessage(
            role="system", content=system, created_at=at(-1, 0), blocks=(make_text_block(system),)
        )
    ]
    for index, message in enumerate(messages):
        if message.role == "tool":
            out.append(
                TerraFinConversationMessage(
                    role="tool",
                    name=message.tool_name,
                    tool_call_id=message.call_id,
                    content=message.content,
                    created_at=at(index, 0),
                    blocks=(
                        make_tool_result_block(
                            call_id=message.call_id,
                            tool_name=message.tool_name,
                            capability_name=message.tool_name,
                            execution_mode="invoke",
                            payload={"text": message.content},
                        ),
                    ),
                )
            )
        elif message.role == "assistant":
            if message.content:
                out.append(
                    TerraFinConversationMessage(
                        role="assistant",
                        content=message.content,
                        created_at=at(index, 0),
                        metadata=dict(message.meta),
                        blocks=(make_text_block(message.content),),
                    )
                )
            if message.calls:
                out.append(
                    TerraFinConversationMessage(
                        role="assistant",
                        content="",
                        created_at=at(index, 1),
                        metadata={**message.meta, "internalOnly": True, "internalToolUse": True},
                        blocks=tuple(
                            make_tool_use_block(
                                call_id=c.call_id,
                                tool_name=c.name,
                                arguments=c.arguments,
                                provider_data=c.provider_data,
                            )
                            for c in message.calls
                        ),
                    )
                )
        else:
            out.append(
                TerraFinConversationMessage(
                    role="user",
                    content=message.content,
                    created_at=at(index, 0),
                    blocks=(make_text_block(message.content),),
                )
            )
    return out


def _title(report: str, question: str) -> str:
    for line in report.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return question[:200]


_STATUS = {"finished": "ok", "forced": "partial", "failed": "failed"}


def _fresh(
    model: Any, task: Optional["TerraFinTaskContext"], readers: Optional[list] = None
) -> Callable[[], Any]:
    """A new session on the run's own model, for `web_fetch`'s reader. Each one is kept in `readers`, for its usage."""
    if not (isinstance(model, HostedResearchModel) and task is not None):
        return lambda: model
    from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY

    def fresh() -> HostedResearchModel:
        reader = HostedResearchModel(task, model._client)
        # The client picks the model from the session, so the reader carries the researcher's.
        if RUNTIME_MODEL_METADATA_KEY in model._session.metadata:
            reader._session.metadata[RUNTIME_MODEL_METADATA_KEY] = model._session.metadata[RUNTIME_MODEL_METADATA_KEY]
        if readers is not None:
            readers.append(reader)
        return reader

    return fresh


def _review_model(model: Any, task: Optional["TerraFinTaskContext"]) -> Optional["HostedResearchModel"]:
    """The reviewer's own model when `TERRAFIN_AGENT_DEEPRESEARCH_REVIEW_MODEL` names one, else None."""
    ref = os.environ.get(_REVIEW_MODEL_ENV, "").strip()
    if not ref or not (isinstance(model, HostedResearchModel) and task is not None):
        return None
    from ..contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY

    registry = getattr(model._client, "registry", None)
    if registry is None:
        raise ValueError(f"{_REVIEW_MODEL_ENV} is set, but this model client cannot resolve another model.")
    reviewer = HostedResearchModel(task, model._client)
    reviewer._session.metadata[RUNTIME_MODEL_METADATA_KEY] = registry.resolve_model_ref(ref).to_payload()
    # A review that fails passes the report, so a reviewer model that cannot run would turn review off unseen.
    status = model._client.describe_runtime_status(session=reviewer._session)
    if not status["configured"]:
        raise ValueError(f"{_REVIEW_MODEL_ENV}={ref!r} cannot run: {status['message']}")
    return reviewer


def run_deep_research(
    *,
    question: str,
    documents: Optional[Sequence[str]] = None,
    task: Optional["TerraFinTaskContext"] = None,
    model: Any = None,
    call_data: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    data_tools: Sequence[ToolSpec] = (),
    budget: Optional[Budget] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Research `question` and return the report payload.

    `documents` are URLs the user supplied; the model reads them through the
    same `read` tool it reads web pages with. As a background task, model turns
    go through the parent session's model client and data calls through `task.call`; `model`,
    `call_data` and `data_tools` are injectable for the benchmark and tests.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("deep_research needs a `question`.")
    urls = [str(ref).strip() for ref in documents or () if str(ref).strip()]
    if any(not ref.startswith(("http://", "https://")) for ref in urls):
        raise ValueError("`documents` must be http(s) URLs.")
    if model is None:
        if task is None:
            raise ValueError("run_deep_research needs a `task`, or an explicit `model`.")
        model = HostedResearchModel(task)
    if call_data is None and task is not None:
        call_data = lambda name, arguments: task.call(name, **dict(arguments))  # noqa: E731
    budget = budget or research_budget()

    def report_progress(stage: str) -> None:
        if task is not None:
            task.heartbeat(stage[:200])
        if progress is not None:
            progress(stage)

    readers: list = []
    # The model reads each document with `read`, so a bad URL is a failed call, not a failed run.
    asked = question
    if urls:
        asked += "\n\nDocuments the user supplied (read them with `read`):\n" + "\n".join(f"- {url}" for url in urls)
    toolbox = Toolbox(
        data_tools=data_tools,
        call_data=call_data,
        fetch=ReaderFetch(_fresh(model, task, readers)),
        budget=budget,
    )
    review_model = _review_model(model, task)
    checkpoint = task.load_checkpoint() if task is not None else None
    result = research(
        asked,
        model=model,
        toolbox=toolbox,
        budget=budget,
        review_model=review_model,
        progress=report_progress,
        cancelled=task.cancelled if task is not None else (lambda: False),
        checkpoint=task.save_checkpoint if task is not None else None,
        resume=checkpoint or None,
    )
    payload = result.to_payload()
    payload.update(
        question=question,
        title=_title(result.report, question),
        status=_STATUS[result.status],
        documents=urls,
    )
    if isinstance(model, HostedResearchModel):
        usage = dict(model.usage)
        for other in (review_model, *readers):
            if isinstance(other, HostedResearchModel):
                for key, value in other.usage.items():
                    usage[key] = usage.get(key, 0) + value
        payload["usage"] = usage
    return payload


def build_deep_research_handler(
    service: Any, capabilities: Callable[[], Iterable["TerraFinCapability"]]
) -> Callable[..., dict[str, Any]]:
    """Build the registry handler. `capabilities` lists the registry at call time, for the data tools."""
    from ..deepresearch.flag import require_deepresearch_enabled

    def deep_research(
        *,
        question: str,
        documents: Optional[Sequence[str]] = None,
        progress: Optional[Callable[[str], None]] = None,
        task: Optional["TerraFinTaskContext"] = None,
    ) -> dict[str, Any]:
        require_deepresearch_enabled()
        call_data = None
        if task is None:
            call_data = lambda name, arguments: getattr(service, name)(**dict(arguments))  # noqa: E731
        return run_deep_research(
            question=question,
            documents=documents,
            task=task,
            call_data=call_data,
            data_tools=data_tool_specs(capabilities()),
            progress=progress,
        )

    return deep_research
