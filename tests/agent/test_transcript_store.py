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
            "modelRef": "google/gemini-3.1-pro-preview",
            "providerId": "google",
            "providerLabel": "Google AI Studio",
            "modelId": "gemini-3.1-pro-preview",
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
    assert summary.runtime_model["modelRef"] == "google/gemini-3.1-pro-preview"
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


def test_the_index_cache_is_invalidated_by_a_foreign_publish(tmp_path) -> None:
    """st_ino is the load-bearing field."""
    import json
    import os

    store = HostedTranscriptStore(root_dir=tmp_path)
    session_id = "s-ino"
    store.create_session(session_id=session_id, agent_name="a", created_at=_ts(1))
    first = store.get_session_index(session_id).updated_at  # warms the cache
    key = store._index_stat_key()

    index_path = tmp_path / "sessions" / "sessions.json"
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    old_stamp = raw["sessions"][session_id]["updatedAt"]
    new_stamp = ("2031" + old_stamp[4:])[: len(old_stamp)]
    assert len(new_stamp) == len(old_stamp), "the probe must not change the file size"
    raw["sessions"][session_id]["updatedAt"] = new_stamp
    temp = index_path.with_name("probe.tmp")
    temp.write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.utime(temp, ns=(key[0], key[0]))  # force a coarse-mtime filesystem's behaviour
    temp.replace(index_path)

    assert store._index_stat_key()[:2] == key[:2], "probe should leave mtime and size equal"
    assert store.get_session_index(session_id).updated_at != first, (
        "a publish with an unchanged mtime and size was not seen"
    )


def test_an_unlocked_write_does_not_cache_its_own_entries(tmp_path, monkeypatch) -> None:
    """A read stats before parsing, so its version of this race self-heals on the next
    call.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-unlocked", agent_name="a", created_at=_ts(1))

    monkeypatch.setattr(store.lock, "_acquire_index_file", lambda: None)
    store.append_custom_title("s-unlocked", title="t")

    assert store._index_snapshot is None, (
        "an unlocked write must not trust the stat it takes after replace()"
    )
    assert store.get_session_index("s-unlocked").title == "t", "the write itself must stand"


def test_a_failed_index_lock_does_not_leak_the_reentrancy_count(tmp_path, monkeypatch) -> None:
    """Keying the decrement on the handle leaked the count on every fail-open,
    after which no later writer would ever take the lock."""
    store = HostedTranscriptStore(root_dir=tmp_path)
    monkeypatch.setattr(store.lock, "_acquire_index_file", lambda: None)
    for hour in (1, 2, 3):
        store.create_session(session_id=f"s{hour}", agent_name="a", created_at=_ts(hour))
    assert store.lock._index_depth == 0, f"depth leaked to {store.lock._index_depth}"

    monkeypatch.undo()
    store.create_session(session_id="s-after", agent_name="a", created_at=_ts(4))
    assert store.lock._index_depth == 0


def test_readers_take_no_cross_process_lock(tmp_path, monkeypatch) -> None:
    """Serialising readers measured 2.2x worse than no cross-process lock at all: a
    6201-entry save holds for ~89ms and a session GET reads the index about nine times.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-read", agent_name="a", created_at=_ts(1))

    acquisitions = []
    real = store.lock._acquire_index_file
    monkeypatch.setattr(
        store.lock, "_acquire_index_file", lambda: (acquisitions.append(1), real())[1]
    )

    store.get_session_index("s-read")
    store.list_sessions()
    store.session_exists("s-read")
    assert acquisitions == [], "a read must not take the index file lock"

    store.append_custom_title("s-read", title="t")
    assert len(acquisitions) == 1, "a write must take it"


def test_nothing_unlinks_a_temp_file_it_does_not_own(tmp_path) -> None:
    """The reaper this replaces globbed `sessions.*.tmp` and unlinked without the lock, so
    it could delete a temp another process was mid-write: that save's replace() raises,
    the index update is lost while the transcript event is already on disk, and on the
    corrupt-index path it can leave no sessions.json at all and the next construction
    writing a fresh empty one.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-tmp", agent_name="a", created_at=_ts(1))

    foreign = tmp_path / "sessions" / "sessions.99999.deadbeef.tmp"
    foreign.write_text("half a doc", encoding="utf-8")

    other = HostedTranscriptStore(root_dir=tmp_path)  # a second process starting
    other.create_session(session_id="s-two", agent_name="a", created_at=_ts(2))

    assert foreign.exists(), "a store deleted a temp file it did not create"
    assert store._index_temp_path != other._index_temp_path, "two stores share a temp name"
    assert other.get_session_index("s-tmp").session_id == "s-tmp"


def test_a_store_reuses_one_temp_name_across_saves(tmp_path) -> None:
    """A fresh name per write leaked the whole 5 MB file on every SIGKILL, and
    collecting those is what needed the unsafe reaper."""
    store = HostedTranscriptStore(root_dir=tmp_path)
    for hour in (1, 2, 3):
        store.create_session(session_id=f"s{hour}", agent_name="a", created_at=_ts(hour))

    leftover = sorted((tmp_path / "sessions").glob("sessions.*.tmp"))
    assert leftover == [], f"a completed save left a temp file behind: {leftover}"


def test_a_read_takes_neither_lock(tmp_path, monkeypatch) -> None:
    """Dropping the file lock left the in-process RLock, and a writer holds that across the
    whole serialise-and-rename — 56 ms mean on a 6201-entry index.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-free", agent_name="a", created_at=_ts(1))

    frames: list[str] = []
    real = type(store.lock).index

    def _record(self):
        frames.append("index")
        return real(self)

    monkeypatch.setattr(type(store.lock), "index", _record)

    store.get_session_index("s-free")
    store.list_sessions()
    store.session_exists("s-free")
    assert frames == [], f"a read entered an index frame: {frames}"

    store.append_custom_title("s-free", title="t")
    assert frames == ["index"], "a write must take the index frame"


def test_the_snapshot_cannot_be_read_torn(tmp_path) -> None:
    """Key and entries were two attributes, so a lock-free reader could pair a new
    key with old entries. One attribute, one assignment, one read."""
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-snap", agent_name="a", created_at=_ts(1))
    store.get_session_index("s-snap")

    assert store._index_snapshot is not None
    key, entries = store._index_snapshot
    assert key == store._index_stat_key()
    assert "s-snap" in entries


def test_an_unchanged_runtime_model_takes_no_lock(tmp_path, monkeypatch) -> None:
    """_sync_transcript_runtime_model calls this on every get_session_record, so it runs on
    every session GET, and every entry in a real index already carries a runtimeModel.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    model = {"provider": "openai", "modelId": "m"}
    store.create_session(
        session_id="s-rm", agent_name="a", created_at=_ts(1), runtime_model=model
    )

    frames: list[str] = []
    real = type(store.lock).index

    def _record(self):
        frames.append("index")
        return real(self)

    monkeypatch.setattr(type(store.lock), "index", _record)

    entry = store.append_runtime_model("s-rm", model)
    assert entry.runtime_model == model
    assert frames == [], f"the unchanged path entered an index frame: {frames}"

    changed = store.append_runtime_model("s-rm", {"provider": "openai", "modelId": "n"})
    assert changed.runtime_model["modelId"] == "n"
    assert frames == ["index"], "a real change must take the index frame"


def test_a_missing_session_still_raises_from_the_authoritative_read(tmp_path) -> None:
    """The lock-free pre-check must not answer for a session it cannot see."""
    store = HostedTranscriptStore(root_dir=tmp_path)
    try:
        store.append_runtime_model("s-absent", {"provider": "p"})
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown session must still raise KeyError")


def test_an_unavailable_index_lock_is_reported_once(tmp_path, monkeypatch, caplog) -> None:
    """The fail-open is deliberate; its cost is not obvious."""
    import fcntl

    store = HostedTranscriptStore(root_dir=tmp_path)
    monkeypatch.setattr(fcntl, "flock", lambda *a, **k: (_ for _ in ()).throw(OSError("no flock")))

    with caplog.at_level("WARNING"):
        store.create_session(session_id="s-nolock", agent_name="a", created_at=_ts(1))
        store.append_custom_title("s-nolock", title="t")

    warnings = [r for r in caplog.records if "index lock unavailable" in r.getMessage()]
    assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
    assert store.get_session_index("s-nolock").title == "t", "the writes must still stand"


def test_a_lock_with_no_path_configured_also_warns(tmp_path, caplog) -> None:
    """It has the same symptom as a failed flock and was the only silent one: no lock means
    every write nulls the snapshot, and a lock-free reader then pays a full re-parse.
    """
    from TerraFin.agent.storage.transcript_store import HostedTranscriptLock

    lock = HostedTranscriptLock()
    with caplog.at_level("WARNING"):
        with lock.index():
            pass
    assert [r for r in caplog.records if "index lock unavailable" in r.getMessage()]


def test_whether_the_lock_was_taken_is_only_obtainable_inside_a_frame(tmp_path, monkeypatch) -> None:
    """It was ambient state before — first instance-wide, where reader threads holding
    nothing read True 4331 times, then thread-scoped, where they read False while a
    frame on their own thread held it.
    """
    store = HostedTranscriptStore(root_dir=tmp_path)
    lock = store.lock

    assert not hasattr(lock, "index_held"), "the flag is readable as ambient state again"
    assert not hasattr(lock, "_index_held"), "the flag is readable as ambient state again"

    with lock.index() as locked:
        assert locked is True, "the outermost frame took the lock and must say so"
        with lock.index() as inner:
            assert inner is False, (
                "an inner frame did not take the lock and must not be the frame"
                " that decides to trust a stat"
            )

    monkeypatch.setattr(lock, "_acquire_index_file", lambda: None)
    with lock.index() as locked:
        assert locked is False, "a fail-open frame must report that it holds nothing"


def test_an_unlocked_frames_write_does_not_cache(tmp_path, monkeypatch) -> None:
    """The yielded flag has one consumer and this is what it decides."""
    store = HostedTranscriptStore(root_dir=tmp_path)
    store.create_session(session_id="s-yield", agent_name="a", created_at=_ts(1))

    monkeypatch.setattr(store.lock, "_acquire_index_file", lambda: None)
    store.append_custom_title("s-yield", title="t")
    assert store._index_snapshot is None, "an unlocked write trusted its own stat"

    monkeypatch.undo()
    store.append_custom_title("s-yield", title="u")
    assert store._index_snapshot is not None, "a locked write must cache"
    assert store.get_session_index("s-yield").title == "u"
