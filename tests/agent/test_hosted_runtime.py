import time
from pathlib import Path

import pytest
from fakes import BaseFakeService as _FakeService
from fakes import fake_chart_opener as _fake_chart_opener

from TerraFin.agent.definitions import (
    DEFAULT_HOSTED_AGENT_NAME,
    TerraFinAgentDefinition,
    TerraFinAgentDefinitionRegistry,
    build_default_agent_definition_registry,
)
from TerraFin.agent.hosted_runtime import (
    TerraFinAgentApprovalRequiredError,
    TerraFinAgentPolicyError,
    TerraFinAgentSessionConflictError,
    TerraFinHostedAgentRuntime,
)
from TerraFin.agent.model_runtime import TerraFinRuntimeModel
from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.session_store import SQLiteHostedSessionStore
from TerraFin.agent.transcript_store import HostedTranscriptStore


def _runtime(
    agent_registry: TerraFinAgentDefinitionRegistry | None = None,
    *,
    transcript_root: Path | None = None,
) -> TerraFinHostedAgentRuntime:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    return TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        agent_registry=agent_registry,
        transcript_store=None if transcript_root is None else HostedTranscriptStore(root_dir=transcript_root),
    )


def test_hosted_runtime_lists_default_agent_definitions() -> None:
    runtime = _runtime()

    assert tuple(definition.name for definition in runtime.list_agents()) == (DEFAULT_HOSTED_AGENT_NAME,)


def test_create_session_records_agent_metadata(tmp_path) -> None:
    runtime = _runtime(transcript_root=tmp_path / "transcripts")

    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:test", metadata={"thread": "alpha"})

    assert context.session.session_id == "hosted:test"
    assert context.session.metadata["thread"] == "alpha"
    assert context.session.metadata["agentDefinition"] == DEFAULT_HOSTED_AGENT_NAME
    assert context.metadata["agentPolicy"]["chartAccess"] is True


def test_create_session_rejects_internal_agent_definitions_by_default(tmp_path) -> None:
    runtime = _runtime(
        agent_registry=build_default_agent_definition_registry(include_gurus=True),
        transcript_root=tmp_path / "transcripts",
    )

    with pytest.raises(TerraFinAgentPolicyError, match="internal-only"):
        runtime.create_session("warren-buffett", session_id="hosted:hidden")


def test_create_internal_session_allows_hidden_guru_definitions(tmp_path) -> None:
    runtime = _runtime(
        agent_registry=build_default_agent_definition_registry(include_gurus=True),
        transcript_root=tmp_path / "transcripts",
    )

    context = runtime.create_internal_session(
        "warren-buffett",
        session_id="hosted:hidden",
        metadata={"hiddenInternal": True},
    )

    assert context.session.session_id == "hosted:hidden"
    assert context.session.metadata["agentDefinition"] == "warren-buffett"


def test_existing_session_runtime_model_tracks_current_default_model(tmp_path) -> None:
    runtime = _runtime(transcript_root=tmp_path / "transcripts")
    runtime.default_runtime_model = TerraFinRuntimeModel(
        model_ref="openai/gpt-4.1-mini",
        provider_id="openai",
        provider_label="OpenAI",
        model_id="gpt-4.1-mini",
    )

    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:model-sync")
    record = runtime.get_session_record(context.session.session_id)
    assert record.context.session.metadata["runtimeModel"]["modelRef"] == "openai/gpt-4.1-mini"

    runtime.default_runtime_model = TerraFinRuntimeModel(
        model_ref="github-copilot/gpt-4o",
        provider_id="github-copilot",
        provider_label="GitHub Copilot",
        model_id="gpt-4o",
    )

    updated = runtime.get_session_record(context.session.session_id)
    assert updated.context.session.metadata["runtimeModel"]["modelRef"] == "github-copilot/gpt-4o"
    assert updated.metadata["runtimeModel"]["providerId"] == "github-copilot"


def test_delete_session_cascades_hidden_child_sessions(tmp_path) -> None:
    runtime = _runtime(
        agent_registry=build_default_agent_definition_registry(include_gurus=True),
        transcript_root=tmp_path / "transcripts",
    )
    parent = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:parent")
    child = runtime.create_internal_session(
        "warren-buffett",
        session_id="hosted:child",
        metadata={
            "hiddenInternal": True,
            "parentSessionId": parent.session.session_id,
        },
    )

    runtime.delete_session(parent.session.session_id)

    assert runtime.transcript_store is not None
    assert runtime.transcript_store.session_exists(parent.session.session_id) is False
    assert runtime.transcript_store.session_exists(child.session.session_id) is False
    with pytest.raises(KeyError):
        runtime.get_session_record(child.session.session_id)


def test_invoke_applies_agent_default_depth_and_view() -> None:
    registry = TerraFinAgentDefinitionRegistry(
        [
            TerraFinAgentDefinition(
                name="macro-analyst",
                description="Macro-focused test agent.",
                allowed_capabilities=("macro_focus",),
                default_depth="auto",
                default_view="weekly",
                chart_access=False,
                allow_background_tasks=False,
            )
        ]
    )
    runtime = _runtime(agent_registry=registry)
    context = runtime.create_session("macro-analyst", session_id="hosted:macro")

    payload = runtime.invoke(context.session.session_id, "macro_focus", name="DXY")

    assert payload["processing"]["requestedDepth"] == "auto"
    assert payload["processing"]["view"] == "weekly"


def test_invoke_rejects_disallowed_capability() -> None:
    registry = TerraFinAgentDefinitionRegistry(
        [
            TerraFinAgentDefinition(
                name="portfolio-reader",
                description="Portfolio-only test agent.",
                allowed_capabilities=("portfolio", "company_info", "market_snapshot"),
                default_depth="auto",
                default_view="daily",
                chart_access=False,
                allow_background_tasks=True,
            )
        ]
    )
    runtime = _runtime(agent_registry=registry)
    context = runtime.create_session("portfolio-reader", session_id="hosted:portfolio")

    with pytest.raises(TerraFinAgentPolicyError, match="cannot use capability 'economic'"):
        runtime.invoke(context.session.session_id, "economic", indicators="UNRATE")


def test_invoke_rejects_chart_access_when_policy_disallows_it() -> None:
    registry = TerraFinAgentDefinitionRegistry(
        [
            TerraFinAgentDefinition(
                name="no-chart-operator",
                description="Cannot open charts.",
                allowed_capabilities=("market_snapshot", "open_chart"),
                default_depth="auto",
                default_view="daily",
                chart_access=False,
                allow_background_tasks=True,
            )
        ]
    )
    runtime = _runtime(agent_registry=registry)
    context = runtime.create_session("no-chart-operator", session_id="hosted:no-chart")

    with pytest.raises(TerraFinAgentPolicyError, match="chart"):
        runtime.invoke(context.session.session_id, "open_chart", data_or_names=["AAPL"])


def test_run_task_requires_background_policy_and_capability_support() -> None:
    runtime = _runtime()
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:foreground-only")

    with pytest.raises(TerraFinAgentPolicyError, match="backgroundable"):
        runtime.run_task(context.session.session_id, "company_info", ticker="AAPL")


def test_run_task_rejects_agents_without_background_permission() -> None:
    registry = TerraFinAgentDefinitionRegistry(
        [
            TerraFinAgentDefinition(
                name="foreground-only",
                description="Cannot launch background work.",
                allowed_capabilities=("market_snapshot",),
                default_depth="auto",
                default_view="daily",
                chart_access=False,
                allow_background_tasks=False,
            )
        ]
    )
    runtime = _runtime(agent_registry=registry)
    context = runtime.create_session("foreground-only", session_id="hosted:task-denied")

    with pytest.raises(TerraFinAgentPolicyError, match="background"):
        runtime.run_task(context.session.session_id, "market_snapshot", name="AAPL")


def test_run_task_completes_for_backgroundable_allowed_capability() -> None:
    runtime = _runtime()
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:task")

    task, result = runtime.run_task(context.session.session_id, "market_snapshot", name="AAPL")

    assert task.status == "completed"
    assert result["ticker"] == "AAPL"


def test_start_task_completes_async_and_is_visible_on_session() -> None:
    runtime = _runtime()
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:async-task")

    task = runtime.start_task(context.session.session_id, "market_snapshot", name="MSFT")

    assert any(item.task_id == task.task_id for item in runtime.list_session_tasks(context.session.session_id))
    for _ in range(40):
        current = runtime.get_task(task.task_id)
        if current.status == "completed":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Timed out waiting for async task completion.")

    assert current.result is not None
    assert current.result["ticker"] == "MSFT"


def test_invoke_requires_human_approval_for_side_effecting_capability() -> None:
    runtime = _runtime()
    runtime.default_require_human_approval_for_side_effects = True
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:approval")

    with pytest.raises(TerraFinAgentApprovalRequiredError) as exc:
        runtime.invoke(context.session.session_id, "open_chart", data_or_names=["AAPL"])

    approval = exc.value.approval
    assert approval.status == "pending"
    assert runtime.list_session_approvals(context.session.session_id)[0].approval_id == approval.approval_id

    approved = runtime.approve_approval(approval.approval_id, note="looks good")
    assert approved.status == "approved"
    assert runtime.get_approval(approval.approval_id).status == "approved"


def test_read_linked_view_context_returns_published_page_state() -> None:
    runtime = _runtime()
    context = runtime.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="hosted:view",
        metadata={"viewContextId": "view:buffett"},
    )
    runtime.upsert_view_context(
        "view:buffett",
        route="/market-insights",
        page_type="market-insights",
        title="Buffett Portfolio",
        selection={"guru": "Buffett"},
        metadata={"topHoldingTickers": ["AAPL", "BAC"]},
    )

    payload = runtime.read_linked_view_context(context.session.session_id)

    assert payload["available"] is True
    assert payload["route"] == "/market-insights"
    assert payload["selection"]["guru"] == "Buffett"


def test_sqlite_session_store_reloads_cached_record_when_another_worker_persists(tmp_path) -> None:
    """Simulate two FastAPI workers sharing one SQLite DB. Worker A has the
    record cached in-process. Worker B mutates the session (e.g. relinks
    the viewContextId) and persists. The next `get()` on Worker A must
    return the fresh metadata — not the stale cached copy — or the
    pull-based `current_view_context` tool will read the wrong tab's
    view context.

    Regression for hostile-review finding C2: the get() path previously
    returned cached records unconditionally, and only the WRITE side of
    the relink fix (0a54535) was in place."""
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "coherency.sqlite3"
    store_a = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry)
    store_b = SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry)

    runtime_a = TerraFinHostedAgentRuntime(service=service, capability_registry=registry, session_store=store_a)
    runtime_b = TerraFinHostedAgentRuntime(service=service, capability_registry=registry, session_store=store_b)

    runtime_a.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="hosted:coherency",
        metadata={"viewContextId": "ctx-A"},
    )
    # Prime worker B's cache by doing a read first.
    record_before = runtime_b.get_session_record("hosted:coherency")
    assert record_before.context.session.metadata.get("viewContextId") == "ctx-A"

    # Worker A mutates through a relink — persist updates SQLite AND worker
    # A's cache, but leaves worker B's cache stale.
    import time as _time
    _time.sleep(0.01)  # ensure strictly-later updated_at
    runtime_a.relink_session_view_context("hosted:coherency", "ctx-B")

    # Worker B's next read should detect the newer SQLite updated_at and
    # reload, picking up the new viewContextId.
    record_after = runtime_b.get_session_record("hosted:coherency")
    assert record_after.context.session.metadata.get("viewContextId") == "ctx-B"

    runtime_a.shutdown()
    runtime_b.shutdown()


def test_relink_session_view_context_persists_across_runtime_instances(tmp_path) -> None:
    """The relink must survive a runtime restart — in-memory mutation alone is
    invisible to the SQLite store, so other workers / processes would keep
    reading the stale viewContextId. Regression for live-server bug where
    `relink_session_view_context` mutated the cached record but didn't save it,
    so `current_view_context` kept reading the creation-time snapshot."""
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "hosted-runtime.sqlite3"
    transcript_root = tmp_path / "transcripts"
    runtime_a = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )
    context = runtime_a.create_session(
        DEFAULT_HOSTED_AGENT_NAME,
        session_id="hosted:relink",
        metadata={"viewContextId": "creation-time-id"},
    )
    sid = context.session.session_id

    runtime_a.relink_session_view_context(sid, "live-id")
    runtime_a.shutdown()

    runtime_b = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )
    reloaded = runtime_b.get_session_record(sid)
    assert reloaded.context.session.metadata.get("viewContextId") == "live-id"
    runtime_b.shutdown()


def test_sqlite_session_store_restores_session_state_after_runtime_restart(tmp_path) -> None:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "hosted-runtime.sqlite3"
    transcript_root = tmp_path / "transcripts"
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )

    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:sqlite-restore")
    runtime.invoke(context.session.session_id, "market_snapshot", name="AAPL")
    task, _ = runtime.run_task(context.session.session_id, "financials", ticker="AAPL")
    runtime.shutdown()

    reloaded = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )
    record = reloaded.get_session_record(context.session.session_id)
    snapshot = record.context.session.snapshot()

    assert "AAPL" in snapshot.focus_items
    assert len(snapshot.capability_calls) == 2
    assert record.context.task_registry.get(task.task_id).status == "completed"
    reloaded.shutdown()


def test_hosted_runtime_lists_and_deletes_sessions(tmp_path) -> None:
    runtime = _runtime(transcript_root=tmp_path / "transcripts")
    runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:first")
    runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:second")

    listed = tuple(record.session_id for record in runtime.list_sessions())
    assert listed == ("hosted:second", "hosted:first")

    removed = runtime.delete_session("hosted:first")

    assert removed.session_id == "hosted:first"
    assert tuple(record.session_id for record in runtime.list_sessions()) == ("hosted:second",)
    assert list((tmp_path / "transcripts" / "sessions").glob("hosted:first.deleted.*.jsonl"))


def test_hosted_runtime_rejects_delete_when_session_has_active_tasks() -> None:
    runtime = _runtime()
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:delete-blocked")
    record = runtime.get_session_record(context.session.session_id)
    task = record.context.task_registry.create(
        "market_snapshot",
        description="market snapshot",
        session_id=context.session.session_id,
        input_payload={"name": "AAPL"},
    )
    record.context.task_registry.mark_running(task.task_id)
    runtime.session_store.persist(record)

    with pytest.raises(TerraFinAgentSessionConflictError, match="active background tasks"):
        runtime.delete_session(context.session.session_id)


def test_sqlite_session_store_restores_view_context_after_runtime_restart(tmp_path) -> None:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "hosted-view-context.sqlite3"
    transcript_root = tmp_path / "transcripts"
    runtime = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )

    runtime.upsert_view_context(
        "view:macro",
        route="/market-insights",
        page_type="market-insights",
        selection={"instrument": "DXY"},
        metadata={"routeSource": "widget"},
    )
    runtime.shutdown()

    reloaded = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )
    context = reloaded.get_view_context("view:macro")

    assert context.route == "/market-insights"
    assert context.page_type == "market-insights"
    assert context.selection["instrument"] == "DXY"
    reloaded.shutdown()


def test_sqlite_store_allows_another_runtime_to_execute_pending_task(tmp_path) -> None:
    service = _FakeService()
    registry = build_default_capability_registry(service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "hosted-shared.sqlite3"
    transcript_root = tmp_path / "transcripts"
    runtime_a = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )

    context = runtime_a.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="hosted:shared-task")
    task = runtime_a.start_task(context.session.session_id, "market_snapshot", name="QQQ")
    runtime_a.shutdown()

    runtime_b = TerraFinHostedAgentRuntime(
        service=service,
        capability_registry=registry,
        session_store=SQLiteHostedSessionStore(db_path=db_path, service=service, registry=registry),
        transcript_store=HostedTranscriptStore(root_dir=transcript_root),
    )
    for _ in range(40):
        current = runtime_b.get_task(task.task_id)
        if current.status == "completed":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Timed out waiting for the second runtime to complete the shared task.")

    assert current.result is not None
    assert current.result["ticker"] == "QQQ"
    runtime_b.shutdown()


def test_transcript_first_runtime_ignores_legacy_blob_only_sessions(tmp_path) -> None:
    runtime = _runtime()
    context = runtime.create_session(DEFAULT_HOSTED_AGENT_NAME, session_id="legacy:blob-only")
    runtime.transcript_store = HostedTranscriptStore(root_dir=tmp_path / "transcripts")

    assert runtime.list_sessions() == ()
    with pytest.raises(KeyError):
        runtime.get_session_record(context.session.session_id)
