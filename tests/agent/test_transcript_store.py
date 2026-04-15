from datetime import UTC, datetime

from TerraFin.agent.loop import TerraFinConversationMessage
from TerraFin.agent.transcript_store import HostedTranscriptStore


def _ts(hour: int) -> datetime:
    return datetime(2026, 4, 16, hour, 0, tzinfo=UTC)


def test_transcript_store_derives_summary_and_conversation_from_events(tmp_path) -> None:
    store = HostedTranscriptStore(root_dir=tmp_path / "agent")
    store.create_session(
        session_id="session:alpha",
        agent_name="terrafin-assistant",
        created_at=_ts(9),
        runtime_model={
            "modelRef": "github-copilot/gpt-4o",
            "providerId": "github-copilot",
            "providerLabel": "GitHub Copilot",
            "modelId": "gpt-4o",
        },
        system_message=TerraFinConversationMessage(
            role="system",
            content="You are TerraFin Agent.",
            created_at=_ts(9),
        ),
    )
    store.append_message(
        "session:alpha",
        TerraFinConversationMessage(role="user", content="Check AAPL.", created_at=_ts(10)),
    )
    store.append_message(
        "session:alpha",
        TerraFinConversationMessage(role="assistant", content="AAPL looks stable.", created_at=_ts(11)),
    )
    store.append_message(
        "session:alpha",
        TerraFinConversationMessage(
            role="tool",
            content='{"ticker":"AAPL"}',
            created_at=_ts(12),
            name="market_snapshot",
        ),
    )

    summary = store.build_summary("session:alpha")
    conversation = store.load_conversation("session:alpha")

    assert summary.title == "Check AAPL."
    assert summary.last_message_preview == "AAPL looks stable."
    assert summary.message_count == 2
    assert summary.runtime_model is not None
    assert summary.runtime_model["modelRef"] == "github-copilot/gpt-4o"
    assert [message.role for message in conversation.snapshot()] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


def test_transcript_store_archives_deleted_sessions(tmp_path) -> None:
    store = HostedTranscriptStore(root_dir=tmp_path / "agent")
    store.create_session(
        session_id="session:delete-me",
        agent_name="terrafin-assistant",
        created_at=_ts(9),
    )

    archived = store.archive_session("session:delete-me", deleted_at=_ts(10))

    assert archived.deleted_at == _ts(10)
    assert store.session_exists("session:delete-me") is False
    assert store.list_sessions() == ()
    assert len(store.list_sessions(include_deleted=True)) == 1
    assert list((tmp_path / "agent" / "sessions").glob("session:delete-me.deleted.*.jsonl"))
