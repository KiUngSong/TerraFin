from datetime import UTC, datetime

from TerraFin.agent.contracts.conversation_state import RUNTIME_MODEL_METADATA_KEY
from TerraFin.agent.runtime import build_default_capability_registry
from TerraFin.agent.runtime.context import create_agent_context
from TerraFin.agent.runtime.session import TerraFinAgentSession
from TerraFin.agent.runtime.tasks import TerraFinTaskRegistry
from TerraFin.agent.session_store import (
    HostedSessionLightMeta,
    SQLiteHostedSessionStore,
    TerraFinHostedSessionRecord,
)

# Reuse the full-featured fake service + chart opener the hosted-runtime tests
# already maintain: build_default_capability_registry needs every service
# method, but list_light_metadata itself never invokes any capability.
from tests.agent.test_hosted_runtime import _FakeService, _fake_chart_opener


def _ts(hour: int) -> datetime:
    return datetime(2026, 4, 16, hour, 0, tzinfo=UTC)


def _make_record(
    registry,
    *,
    session_id: str,
    session_metadata: dict[str, object] | None = None,
    task_statuses: tuple[str, ...] = (),
) -> TerraFinHostedSessionRecord:
    session = TerraFinAgentSession(
        session_id=session_id,
        metadata=dict(session_metadata or {}),
    )
    task_registry = TerraFinTaskRegistry()
    for index, status in enumerate(task_statuses):
        task = task_registry.create(
            "financials",
            description=f"task-{index}",
            session_id=session_id,
        )
        # `create` always yields a pending task; rewrite the status directly to
        # exercise both terminal and non-terminal counting paths.
        from dataclasses import replace

        task_registry._tasks[task.task_id] = replace(task, status=status)
    context = create_agent_context(
        service=registry_service,
        registry=registry,
        session=session,
        task_registry=task_registry,
    )
    return TerraFinHostedSessionRecord(
        session_id=session_id,
        agent_name="terrafin-assistant",
        context=context,
        metadata={},
        created_at=_ts(9),
        updated_at=_ts(10),
        last_accessed_at=_ts(11),
    )


# The service instance is shared because create_agent_context stores it but
# list_light_metadata never calls into it.
registry_service = _FakeService()


def test_list_light_metadata_reads_payloads_without_building_contexts(tmp_path) -> None:
    registry = build_default_capability_registry(registry_service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "sessions.sqlite3"
    store = SQLiteHostedSessionStore(
        db_path=db_path,
        service=registry_service,
        registry=registry,
    )

    runtime_model = {
        "modelRef": "github-copilot/gpt-4o",
        "providerId": "github-copilot",
        "providerLabel": "GitHub Copilot",
        "modelId": "gpt-4o",
    }

    store.create(
        _make_record(
            registry,
            session_id="session:normal",
            session_metadata={RUNTIME_MODEL_METADATA_KEY: runtime_model},
            task_statuses=("completed",),
        )
    )
    store.create(
        _make_record(
            registry,
            session_id="session:hidden",
            session_metadata={"hiddenInternal": True},
        )
    )
    store.create(
        _make_record(
            registry,
            session_id="session:pending",
            task_statuses=("pending", "running", "completed", "failed"),
        )
    )

    metas = store.list_light_metadata()
    assert all(isinstance(meta, HostedSessionLightMeta) for meta in metas)
    by_id = {meta.session_id: meta for meta in metas}
    assert set(by_id) == {"session:normal", "session:hidden", "session:pending"}

    normal = by_id["session:normal"]
    assert normal.hidden_internal is False
    assert normal.pending_task_count == 0
    assert normal.runtime_model == runtime_model
    assert normal.created_at == _ts(9)
    assert normal.updated_at == _ts(10)
    assert normal.last_accessed_at == _ts(11)
    assert normal.agent_name == "terrafin-assistant"

    hidden = by_id["session:hidden"]
    assert hidden.hidden_internal is True
    assert hidden.runtime_model is None
    assert hidden.pending_task_count == 0

    pending = by_id["session:pending"]
    # pending + running are non-terminal; completed + failed are terminal.
    assert pending.pending_task_count == 2
    assert pending.hidden_internal is False


def test_list_light_metadata_does_not_deserialize_records(tmp_path, monkeypatch) -> None:
    """The light path must avoid building a full agent context per session —
    that is the whole point of the override. Guard it by failing the test if
    record deserialization runs during list_light_metadata."""
    registry = build_default_capability_registry(registry_service, chart_opener=_fake_chart_opener)
    db_path = tmp_path / "sessions.sqlite3"
    store = SQLiteHostedSessionStore(
        db_path=db_path,
        service=registry_service,
        registry=registry,
    )
    store.create(_make_record(registry, session_id="session:guard"))

    import TerraFin.agent.storage.session_store as store_module

    def _explode(*args, **kwargs):
        raise AssertionError("list_light_metadata must not deserialize full records")

    monkeypatch.setattr(store_module, "_deserialize_record", _explode)

    metas = store.list_light_metadata()
    assert [meta.session_id for meta in metas] == ["session:guard"]
