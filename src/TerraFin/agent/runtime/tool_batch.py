"""One model step's batch of tool calls, run for the main loop and the guru worker."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..contracts.conversation import TerraFinConversationMessage, TerraFinHostedConversation, TerraFinToolCall
from ..tools import TerraFinToolInvocationResult
from ..tools.execution import ToolExecutionOutcome
from .recovery import RecoveryTracker
from .session import TerraFinAgentSession


if TYPE_CHECKING:
    from .loop import TerraFinHostedAgentLoop


TRUNCATED_ARGUMENTS_REASON = (
    "The reply was cut off at the output limit, so the arguments of this call may be truncated. "
    "It was not run. Re-issue it with smaller arguments, or fewer calls in one reply."
)
INTERRUPTED_REASON = "Not run: the user stopped the turn before this call started."


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    invocations: tuple[TerraFinToolInvocationResult, ...]
    # The run's tool-call count after this batch.
    tool_call_count: int
    # A fatal tool or the max_tool_calls limit. Every call is answered, and the run must stop.
    error: Exception | None = None
    recovery_exhausted: bool = False
    retryable_invocation: TerraFinToolInvocationResult | None = None
    # The user stopped the turn. Every call not yet started is answered without running.
    interrupted: bool = False


def run_tool_batch(
    loop: "TerraFinHostedAgentLoop",
    session_id: str,
    conversation: TerraFinHostedConversation,
    tool_calls: tuple[TerraFinToolCall, ...],
    *,
    tool_call_count: int,
    fingerprint_counts: dict[str, int],
    recovery_tracker: RecoveryTracker,
    added: list[TerraFinConversationMessage] | None = None,
    cut_off: bool = False,
    message_transform: Callable[..., TerraFinConversationMessage] | None = None,
    max_parallel: int = 1,
    interrupted: Callable[[], bool] | None = None,
) -> BatchOutcome:
    """Run and answer every call in the batch, in call order.

    A consecutive run of read-only invoke-mode calls runs on up to
    `max_parallel` threads. Counting, the loop guard and every append stay on
    the calling thread. `message_transform(tool_call=, invocation=, message=)`
    rewrites a result before it is appended. `interrupted()` is asked before
    each call or parallel run starts, and a True answers the rest unrun.
    """
    safe_tools = (
        {
            tool.name
            for tool in loop.tool_adapter.list_tools_for_session(session_id)
            if tool.execution_mode == "invoke" and not tool.side_effecting
        }
        if max_parallel > 1
        else set()
    )
    # Where this batch's results begin. A model client may mint positional call
    # ids that repeat across steps, so answered-ness is judged from here on.
    batch_start = len(conversation.messages)
    invocations: list[TerraFinToolInvocationResult] = []
    retryable_fingerprints: list[str | None] = []
    retryable_invocation: TerraFinToolInvocationResult | None = None
    stop: Exception | None = None
    stopped_on = ""
    was_interrupted = False
    current = tool_calls[0].call_id if tool_calls else ""
    index = 0
    try:
        while index < len(tool_calls) and stop is None:
            if interrupted is not None and interrupted():
                was_interrupted = True
                for tool_call in tool_calls[index:]:
                    current = tool_call.call_id
                    message = loop.tool_execution_engine.build_unresolved_result_message(
                        tool_call, reason=INTERRUPTED_REASON
                    )
                    loop._append_conversation_message(conversation, message, added=added)
                break
            end = index + 1
            if tool_calls[index].tool_name in safe_tools:
                while end < len(tool_calls) and tool_calls[end].tool_name in safe_tools:
                    end += 1
            planned: list[tuple[TerraFinToolCall, ToolExecutionOutcome | None]] = []
            over_limit: TerraFinToolCall | None = None
            for tool_call in tool_calls[index:end]:
                current = tool_call.call_id
                tool_call_count += 1
                if tool_call_count > loop.max_tool_calls:
                    over_limit = tool_call
                    break
                planned.append((tool_call, _answer_without_running(loop, tool_call, cut_off, fingerprint_counts)))
            index = end
            # A raise from the run is pinned on the first call it executes.
            current = next((tool_call.call_id for tool_call, outcome in planned if outcome is None), current)
            for tool_call, outcome in _execute(loop, session_id, planned, max_parallel):
                current = tool_call.call_id
                if outcome.kind == "fatal_error":
                    assert outcome.error is not None
                    # Answered in place, so the later calls of a parallel run,
                    # which already ran, keep their own results.
                    loop._close_unresolved_tool_calls(
                        conversation,
                        (tool_call,),
                        since=batch_start,
                        stopped_on=tool_call.call_id,
                        error=outcome.error,
                        added=added,
                    )
                    if stop is None:
                        stop, stopped_on = outcome.error, tool_call.call_id
                    continue
                assert outcome.invocation is not None
                assert outcome.message is not None
                invocation = outcome.invocation
                message = outcome.message
                if message_transform is not None:
                    message = message_transform(tool_call=tool_call, invocation=invocation, message=message)
                invocations.append(invocation)
                loop._append_conversation_message(conversation, message, added=added)
                loop._call_hooks("after_tool", session_id, invocation)
                if outcome.kind == "retryable_error":
                    retryable_fingerprints.append(outcome.fingerprint)
                    retryable_invocation = invocation
            if stop is None and over_limit is not None:
                stop = RuntimeError(
                    f"Hosted TerraFin agent loop exceeded max_tool_calls={loop.max_tool_calls} "
                    f"for session '{session_id}'."
                )
                stopped_on = over_limit.call_id
        if stop is not None:
            loop._close_unresolved_tool_calls(
                conversation, tool_calls, since=batch_start, stopped_on=stopped_on, error=stop, added=added
            )
            return BatchOutcome(invocations=tuple(invocations), tool_call_count=tool_call_count, error=stop)
    except BaseException as exc:
        # The `tool_use` message covers every call and is already persisted,
        # so any exit but a normal finish (a tool, an append, an interrupt)
        # leaves calls unanswered, which the client reads as an interrupted turn.
        loop._close_unresolved_tool_calls(
            conversation, tool_calls, since=batch_start, stopped_on=current, error=exc, added=added
        )
        raise
    loop._persist_conversation_runtime_state(session_id, conversation)
    # Judged once per batch, after every call has its result.
    exhausted = bool(retryable_fingerprints) and recovery_tracker.record_round(retryable_fingerprints)
    return BatchOutcome(
        invocations=tuple(invocations),
        tool_call_count=tool_call_count,
        recovery_exhausted=exhausted,
        retryable_invocation=retryable_invocation,
        interrupted=was_interrupted,
    )


def _answer_without_running(
    loop: "TerraFinHostedAgentLoop",
    tool_call: TerraFinToolCall,
    cut_off: bool,
    fingerprint_counts: dict[str, int],
) -> ToolExecutionOutcome | None:
    """The result for a call that must not run, or None when it should run."""
    engine = loop.tool_execution_engine
    if cut_off:
        return engine.build_rejected_call_outcome(
            tool_call, code="tool_arguments_truncated", reason=TRUNCATED_ARGUMENTS_REASON
        )
    fingerprint = _tool_call_fingerprint(tool_call)
    fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
    # The same call a third time in one run is answered with a nudge to pivot,
    # not run again.
    if fingerprint_counts[fingerprint] > 2:
        return engine.build_loop_guard_outcome(tool_call, count=fingerprint_counts[fingerprint])
    return None


def _execute(
    loop: "TerraFinHostedAgentLoop",
    session_id: str,
    planned: list[tuple[TerraFinToolCall, ToolExecutionOutcome | None]],
    max_parallel: int,
) -> list[tuple[TerraFinToolCall, ToolExecutionOutcome]]:
    engine = loop.tool_execution_engine
    pending = [tool_call for tool_call, outcome in planned if outcome is None]
    if max_parallel <= 1 or len(pending) < 2:
        return [
            (tool_call, outcome if outcome is not None else engine.execute(session_id, tool_call))
            for tool_call, outcome in planned
        ]

    # A thread records on its own scratch activity, merged into the session
    # here in call order, because recording mutates the shared session record.
    def _run(tool_call: TerraFinToolCall) -> tuple[ToolExecutionOutcome, TerraFinAgentSession]:
        with loop.runtime.recording_on_scratch(session_id) as activity:
            return engine.execute(session_id, tool_call), activity

    with ThreadPoolExecutor(max_workers=min(max_parallel, len(pending)), thread_name_prefix="terrafin-tool") as pool:
        futures = [None if outcome is not None else pool.submit(_run, tool_call) for tool_call, outcome in planned]
        results: list[tuple[TerraFinToolCall, ToolExecutionOutcome]] = []
        activities: list[TerraFinAgentSession] = []
        for (tool_call, outcome), future in zip(planned, futures):
            if future is not None:
                outcome, activity = future.result()
                activities.append(activity)
            assert outcome is not None
            results.append((tool_call, outcome))
    loop.runtime.merge_activity(session_id, activities)
    return results


def _tool_call_fingerprint(tool_call: TerraFinToolCall) -> str:
    """Stable key for 'same tool, same arguments' loop detection.

    Canonicalises the arg mapping by sorted keys so dict ordering differences
    don't defeat the match.
    """
    try:
        args = json.dumps(dict(tool_call.arguments or {}), sort_keys=True, default=str)
    except Exception:
        args = repr(tool_call.arguments)
    return f"{tool_call.tool_name}::{args}"
