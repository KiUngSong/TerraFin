"""Offline tests for deferred-on-next-turn delivery of backgroundable task
completions (Part B for `deep_research`).

A backgrounded task's report is NOT pushed through a server-initiated model
turn. Instead, on completion the worker stashes a pending-completion marker in
an isolated store table; the user's next `submit_user_message` peeks the
markers and injects each one as a single user-role background-note message
(hidden from the UI via `internalOnly`, forwarded to the model). The marker is
only cleared AFTER its note is durably appended.

The `deep_research` capability is stubbed with a canned serialized report so the
tests stay deterministic and offline (no live LLM / web).
"""
import time

import pytest
from test_loop import _fake_chart_opener, _FakeService

from TerraFin.agent.contracts.conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    utc_now,
)
from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME, TerraFinAgentDefinition
from TerraFin.agent.hosted_runtime import TerraFinHostedAgentRuntime
from TerraFin.agent.loop import (
    TerraFinHostedAgentLoop,
    TerraFinModelTurn,
)
from TerraFin.agent.providers.google import (
    TerraFinGoogleModelConfig,
    TerraFinGoogleResponsesProvider,
)
from TerraFin.agent.providers.openai_compatible import OpenAICompatibleResponsesRunner
from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.runtime.capability import TerraFinCapability
from TerraFin.agent.runtime.tasks import TerraFinTaskRecord
from TerraFin.agent.session_store import SQLiteHostedSessionStore


_CANNED_REPORT = {
    "question": "How is Apple doing?",
    "title": "AAPL deep dive",
    "claims": [
        {"claimId": "g1", "text": "Revenue grew to a record.", "value": None, "quote": "", "unit": None, "citations": []},
    ],
    "gaps": [],
}


def _stub_deep_research(*, ticker, question=None, progress=None):
    if progress is not None:
        for stage in ("plan", "retrieve", "synthesize", "verify"):
            progress(stage)
    report = dict(_CANNED_REPORT)
    report["question"] = question or report["question"]
    report["title"] = f"{ticker} deep dive"
    return report


def _stubbed_registry(service):
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    # Replace the live spine-backed handler with a canned one so the async
    # execution path runs fully offline.
    registry._capabilities["deep_research"] = TerraFinCapability(
        name="deep_research",
        description="Stubbed deep research for tests.",
        handler=_stub_deep_research,
        backgroundable=True,
        summary="stub",
    )
    return registry


def _loop(model_client, *, session_store=None, transcript_store=None, max_messages_per_session=200):
    service = _FakeService()
    registry = _stubbed_registry(service)
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=session_store,
        transcript_store=transcript_store,
    )
    return TerraFinHostedAgentLoop(
        runtime=runtime,
        model_client=model_client,
        max_messages_per_session=max_messages_per_session,
    )


class _DirectAnswerModel:
    def __init__(self):
        self.seen_messages = None

    def complete(self, *, messages, tools, **kwargs):
        _ = tools, kwargs
        self.seen_messages = tuple(messages)
        return TerraFinModelTurn(
            assistant_message=TerraFinConversationMessage(
                role="assistant",
                content="Here is what your research found.",
            )
        )


def _wait_for_marker(runtime, session_id, *, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        markers = runtime.session_store.peek_pending_completions(session_id)
        if markers:
            return markers
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for a pending-completion marker.")


def _delivery_notes(messages):
    return [
        message
        for message in messages
        if message.role == "user" and message.metadata.get("internalCompletionDelivery")
    ]


# --- Marker on completion --------------------------------------------------


def test_completion_records_pending_marker_on_session_record() -> None:
    loop = _loop(_DirectAnswerModel())
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:marker")
        loop.runtime.start_task(
            conversation.session_id,
            "deep_research",
            origin_tool_call_id="orig-call-1",
            ticker="AAPL",
            question="How is Apple doing?",
        )
        markers = _wait_for_marker(loop.runtime, conversation.session_id)
    finally:
        loop.runtime.shutdown()

    assert len(markers) == 1
    marker = markers[0]
    assert marker["capabilityName"] == "deep_research"
    assert marker["originToolCallId"] == "orig-call-1"
    assert marker["inputPayload"]["ticker"] == "AAPL"
    assert marker["result"]["title"] == "AAPL deep dive"


def test_start_task_captures_origin_tool_call_id_on_task_record() -> None:
    loop = _loop(_DirectAnswerModel())
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:origin")
        task = loop.runtime.start_task(
            conversation.session_id,
            "deep_research",
            origin_tool_call_id="orig-xyz",
            ticker="MSFT",
        )
        assert task.origin_tool_call_id == "orig-xyz"
    finally:
        loop.runtime.shutdown()


def test_pending_marker_is_cross_worker_visible(tmp_path) -> None:
    service = _FakeService()
    registry_a = _stubbed_registry(service)
    db_path = tmp_path / "deferred.sqlite3"
    store_a = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_a)
    runtime_a = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_a, session_store=store_a)

    runtime_b = None
    try:
        context = runtime_a.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:xworker")
        runtime_a.start_task(
            context.session.session_id,
            "deep_research",
            origin_tool_call_id="orig-1",
            ticker="NVDA",
        )
        _wait_for_marker(runtime_a, context.session.session_id)

        # A second worker on the same DB has never cached this session; the
        # pending-completions table is read fresh, so it sees the marker.
        registry_b = _stubbed_registry(service)
        store_b = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_b)
        runtime_b = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_b, session_store=store_b)
        markers_b = store_b.peek_pending_completions(context.session.session_id)
        assert len(markers_b) == 1
        assert markers_b[0]["result"]["title"] == "NVDA deep dive"
    finally:
        runtime_a.shutdown()
        if runtime_b is not None:
            runtime_b.shutdown()


# --- FIX #4: whole-record persist must not clobber an isolated marker ------


def test_completion_persist_does_not_clobber_sibling_marker(tmp_path) -> None:
    """Multi-worker SQLite: a worker completing its task persists its whole
    (stale) record. That write must NOT erase a pending-completion marker a
    sibling background task wrote during the run — markers live in an isolated
    table the record payload never touches.
    """
    service = _FakeService()
    registry_a = _stubbed_registry(service)
    registry_b = _stubbed_registry(service)
    db_path = tmp_path / "clobber.sqlite3"
    store_a = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_a)
    store_b = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_b)
    runtime_a = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_a, session_store=store_a)
    runtime_b = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_b, session_store=store_b)
    try:
        context = runtime_a.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:clobber")
        session_id = context.session.session_id

        record_a = runtime_a.get_session_record(session_id)
        store_b.append_pending_completion(
            session_id,
            marker={"taskId": "t-sibling", "capabilityName": "deep_research", "result": {"title": "SIBLING"}},
        )
        runtime_a._persist_task_record(record_a)

        survivors = [(m.get("result") or {}).get("title") for m in store_b.peek_pending_completions(session_id)]
        assert survivors == ["SIBLING"]
    finally:
        runtime_a.shutdown()
        runtime_b.shutdown()


def test_marker_survives_concurrent_relink_persist(tmp_path) -> None:
    """`relink_session_view_context` runs on ~every submit and persists the
    whole record. It must not erase a sibling worker's completion marker.
    """
    service = _FakeService()
    registry_a = _stubbed_registry(service)
    registry_b = _stubbed_registry(service)
    db_path = tmp_path / "relink.sqlite3"
    store_a = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_a)
    store_b = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry_b)
    runtime_a = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_a, session_store=store_a)
    runtime_b = TerraFinHostedAgentRuntime(service=service, capability_registry=registry_b, session_store=store_b)
    try:
        context = runtime_a.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:relink")
        session_id = context.session.session_id
        store_b.append_pending_completion(
            session_id,
            marker={"taskId": "t1", "capabilityName": "deep_research", "result": {"title": "SURVIVOR"}},
        )
        runtime_a.relink_session_view_context(session_id, "view-ctx-1")
        survivors = [m["result"]["title"] for m in store_b.peek_pending_completions(session_id)]
        assert survivors == ["SURVIVOR"]
    finally:
        runtime_a.shutdown()
        runtime_b.shutdown()


# --- FIX #6: dedupe on double-append (lease-expiry re-claim) ----------------


def test_duplicate_taskid_marker_dedupes_at_store(tmp_path) -> None:
    service = _FakeService()
    registry = _stubbed_registry(service)
    db_path = tmp_path / "dedupe.sqlite3"
    store = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry)
    runtime = TerraFinHostedAgentRuntime(service=service, capability_registry=registry, session_store=store)
    try:
        context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:dedupe")
        session_id = context.session.session_id
        # Two workers re-claiming an expired lease both record the same task.
        store.append_pending_completion(
            session_id,
            marker={"taskId": "same", "capabilityName": "deep_research", "result": {"title": "FIRST"}},
        )
        store.append_pending_completion(
            session_id,
            marker={"taskId": "same", "capabilityName": "deep_research", "result": {"title": "SECOND"}},
        )
        markers = store.peek_pending_completions(session_id)
        assert len(markers) == 1
        assert markers[0]["result"]["title"] == "FIRST"
    finally:
        runtime.shutdown()


# --- Drain + inject on next turn -------------------------------------------


def test_next_submit_drains_marker_and_injects_background_note() -> None:
    model = _DirectAnswerModel()
    loop = _loop(model)
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:drain")
        loop.runtime.start_task(
            conversation.session_id,
            "deep_research",
            origin_tool_call_id="orig-1",
            ticker="AAPL",
            question="How is Apple doing?",
        )
        _wait_for_marker(loop.runtime, conversation.session_id)

        loop.submit_user_message(conversation.session_id, "What did the research find?")
        conversation = loop.get_conversation(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    # The completed report landed in the transcript as a single background note.
    notes = _delivery_notes(conversation.snapshot())
    assert len(notes) == 1
    assert "AAPL deep dive" in notes[0].content
    # Hidden from the UI transcript.
    assert notes[0].metadata.get("internalOnly") is True

    # The marker is cleared after durable delivery.
    assert loop.runtime.session_store.peek_pending_completions(conversation.session_id) == ()

    # The model saw the delivered report in its prompt.
    seen_notes = _delivery_notes(model.seen_messages or ())
    assert len(seen_notes) == 1
    assert "AAPL deep dive" in seen_notes[0].content


def test_multiple_pending_completions_coalesce_into_one_drain() -> None:
    model = _DirectAnswerModel()
    loop = _loop(model)
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:coalesce")
        loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o1", ticker="AAPL")
        loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o2", ticker="MSFT")

        deadline = time.time() + 5.0
        while time.time() < deadline:
            markers = loop.runtime.session_store.peek_pending_completions(conversation.session_id)
            if len(markers) == 2:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("Timed out waiting for both markers.")

        loop.submit_user_message(conversation.session_id, "Summarize both.")
        conversation = loop.get_conversation(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    delivered = sorted(
        title
        for note in _delivery_notes(conversation.snapshot())
        for title in ("AAPL deep dive", "MSFT deep dive")
        if title in note.content
    )
    assert delivered == ["AAPL deep dive", "MSFT deep dive"]
    assert loop.runtime.session_store.peek_pending_completions(conversation.session_id) == ()


# --- FIX #1: the delivered note is wire-valid on every provider adapter -----


def _drained_conversation():
    """Run a real drain and return (loop, conversation, agent_definition)."""
    loop = _loop(_DirectAnswerModel())
    conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:adapters")
    loop.runtime.start_task(
        conversation.session_id,
        "deep_research",
        origin_tool_call_id="orig-1",
        ticker="AAPL",
        question="How is Apple doing?",
    )
    _wait_for_marker(loop.runtime, conversation.session_id)
    loop.submit_user_message(conversation.session_id, "What did the research find?")
    conversation = loop.get_conversation(conversation.session_id)
    return loop, conversation


def test_delivered_completion_is_valid_on_openai_responses_adapter() -> None:
    loop, conversation = _drained_conversation()
    try:
        normalized = loop.transcript_normalizer.normalize_for_model(conversation)
    finally:
        loop.runtime.shutdown()

    runner = OpenAICompatibleResponsesRunner(
        provider_id="openai",
        max_retries=0,
        response_error_cls=RuntimeError,
    )
    items = runner._messages_to_input(normalized)

    # No orphaned function_call_output: every function_call_output must have a
    # matching function_call in the SAME batch. The old synthetic tool_result
    # emitted a function_call_output whose fabricated call_id had no match →
    # HTTP 400 "No tool call found for function call output".
    fc_ids = {item["call_id"] for item in items if item.get("type") == "function_call"}
    fco_ids = {item["call_id"] for item in items if item.get("type") == "function_call_output"}
    assert fco_ids <= fc_ids
    assert not fco_ids  # the delivery contributes zero function_call_output

    # The report rides as a user message and is forwarded to the model.
    user_texts = [
        content["text"]
        for item in items
        if item.get("type") == "message" and item.get("role") == "user"
        for content in item.get("content", [])
        if content.get("type") == "input_text"
    ]
    assert any("background research completed" in text for text in user_texts)
    assert any("AAPL deep dive" in text for text in user_texts)

    # Incremental (previous_response_id) path: serializing only the delivery
    # tail must also emit no orphaned function_call_output.
    delivery_index = next(
        idx for idx, message in enumerate(normalized) if message.metadata.get("internalCompletionDelivery")
    )
    tail_items = runner._messages_to_input(normalized[delivery_index:])
    assert not any(item.get("type") == "function_call_output" for item in tail_items)


def test_delivered_completion_is_valid_on_google_adapter() -> None:
    loop, conversation = _drained_conversation()
    try:
        normalized = loop.transcript_normalizer.normalize_for_model(conversation)
    finally:
        loop.runtime.shutdown()

    provider = TerraFinGoogleResponsesProvider(config=TerraFinGoogleModelConfig(api_key="test-key"))
    agent = TerraFinAgentDefinition(
        name=DEFAULT_HOSTED_AGENT_NAME,
        description="hosted",
        allowed_capabilities=("deep_research",),
    )
    payload = provider._build_request_payload(
        agent=agent,
        conversation=conversation,
        messages=normalized,
        tools=(),
    )
    contents = payload["contents"]
    # No orphaned functionResponse referencing the removed delivery tool.
    assert not any(
        "functionResponse" in part
        for content in contents
        for part in content.get("parts", [])
    )
    user_texts = [
        part["text"]
        for content in contents
        if content["role"] == "user"
        for part in content["parts"]
        if "text" in part
    ]
    assert any("AAPL deep dive" in text for text in user_texts)


# --- Idempotency + robustness ----------------------------------------------


def test_second_turn_does_not_redeliver_a_drained_completion() -> None:
    loop = _loop(_DirectAnswerModel())
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:idem-drain")
        loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o1", ticker="AAPL")
        _wait_for_marker(loop.runtime, conversation.session_id)

        loop.submit_user_message(conversation.session_id, "First follow-up.")
        loop.submit_user_message(conversation.session_id, "Second follow-up.")
        conversation = loop.get_conversation(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    assert len(_delivery_notes(conversation.snapshot())) == 1


def test_injection_failure_preserves_marker_for_redelivery() -> None:
    """FIX #3: if injecting the note fails (message-budget overflow) before it
    is durably appended, the marker must survive and redeliver next turn."""
    loop = _loop(_DirectAnswerModel(), max_messages_per_session=1)
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:fail")
        loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o1", ticker="AAPL")
        _wait_for_marker(loop.runtime, conversation.session_id)

        # Budget is exhausted by the system message alone → the note append
        # raises before it lands in the transcript.
        with pytest.raises(RuntimeError):
            loop.submit_user_message(conversation.session_id, "hello")

        # Marker survived — it was NOT cleared on the failed injection.
        assert len(loop.runtime.session_store.peek_pending_completions(conversation.session_id)) == 1

        # Room restored → next turn redelivers exactly once.
        loop.max_messages_per_session = 200
        loop.submit_user_message(conversation.session_id, "now answer")
        conversation = loop.get_conversation(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    assert len(_delivery_notes(conversation.snapshot())) == 1
    assert loop.runtime.session_store.peek_pending_completions(conversation.session_id) == ()


def test_marker_whose_note_is_already_in_transcript_is_not_redelivered() -> None:
    """If a prior turn delivered the note but its clear never committed, the
    surviving marker must be dropped at drain, not re-appended."""
    loop = _loop(_DirectAnswerModel())
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:redup")
        task = loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o1", ticker="AAPL")
        _wait_for_marker(loop.runtime, conversation.session_id)

        loop.submit_user_message(conversation.session_id, "first")  # delivers + clears

        # Simulate a clear that never committed: the same-taskId marker survives.
        loop.runtime.session_store.append_pending_completion(
            conversation.session_id,
            marker={"taskId": task.task_id, "capabilityName": "deep_research", "result": {"title": "AAPL deep dive"}},
        )
        assert len(loop.runtime.session_store.peek_pending_completions(conversation.session_id)) == 1

        loop.submit_user_message(conversation.session_id, "second")
        conversation = loop.get_conversation(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    assert len(_delivery_notes(conversation.snapshot())) == 1
    assert loop.runtime.session_store.peek_pending_completions(conversation.session_id) == ()


def test_recompleting_a_terminal_task_does_not_enqueue_a_second_marker() -> None:
    from threading import Event

    loop = _loop(_DirectAnswerModel())
    try:
        conversation = loop.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="deferred:idem-complete")
        task = loop.runtime.start_task(conversation.session_id, "deep_research", origin_tool_call_id="o1", ticker="AAPL")
        _wait_for_marker(loop.runtime, conversation.session_id)

        # Re-run the async execution for the already-completed task, simulating a
        # duplicate re-claim. The `already_terminal` guard plus store-level
        # dedupe must prevent a second marker even though the capability re-runs.
        loop.runtime._execute_async_task(
            conversation.session_id,
            task.task_id,
            "deep_research",
            Event(),
        )
        markers = loop.runtime.session_store.peek_pending_completions(conversation.session_id)
    finally:
        loop.runtime.shutdown()

    assert len(markers) == 1


def test_drain_on_missing_session_is_a_noop_and_does_not_crash() -> None:
    loop = _loop(_DirectAnswerModel())
    try:
        conversation = TerraFinHostedConversation(session_id="deferred:gone", agent_name=DEFAULT_HOSTED_AGENT_NAME)
        added: list = []
        # No such session in the store — drain must be a graceful no-op.
        loop._drain_pending_completions("deferred:gone", conversation, added=added)
        assert added == []
        assert conversation.messages == []

        # Marker write against a deleted/archived session is also graceful.
        dummy = TerraFinTaskRecord(
            task_id="task:x",
            capability_name="deep_research",
            status="completed",
            description="d",
            session_id="deferred:gone",
            created_at=utc_now(),
        )
        loop.runtime._record_pending_completion("deferred:gone", task=dummy, result={"title": "x"})
    finally:
        loop.runtime.shutdown()
