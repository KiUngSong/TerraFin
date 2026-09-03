"""The turn claim must serialise real contention and never wedge a session."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from TerraFin.agent.contracts.conversation import TerraFinConversationMessage
from TerraFin.agent.runtime import inflight


@pytest.fixture()
def lock_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The lock must follow the same override the transcript store reads
    # (service/hosted.py), or two processes can share a store while locking in
    # different directories — a no-op lock with no symptom.
    monkeypatch.setenv("TERRAFIN_AGENT_TRANSCRIPT_DIR", str(tmp_path / "agent"))
    return tmp_path


def test_lock_lives_beside_the_transcripts_it_guards(lock_root: Path) -> None:
    handle, state = inflight.claim_or_unavailable("s")
    try:
        assert state == inflight.FREE
        assert inflight._lock_dir() == lock_root / "agent" / "locks"
    finally:
        inflight.release(handle)


def test_real_contention_is_reported(lock_root: Path) -> None:
    handle, state = inflight.claim_or_unavailable("s")
    try:
        assert handle is not None and state == inflight.FREE
        second, second_state = inflight.claim_or_unavailable("s")
        assert second is None and second_state == inflight.CONTENDED, "a held lock must read as contended"
        assert inflight.liveness("s") == inflight.CONTENDED
    finally:
        inflight.release(handle)
    assert inflight.liveness("s") == inflight.FREE


def test_an_unwritable_lock_dir_fails_open(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing closed here 409s every send and pins turnInFlight forever, which disables
    every exit in the client's poller — a total chat outage from a configuration that
    works without the lock (read-only rootfs, non-root user).
    """
    directory = inflight._lock_dir()
    directory.mkdir(parents=True, exist_ok=True)
    real_chmod = os.chmod
    real_chmod(directory, stat.S_IRUSR | stat.S_IXUSR)

    def _refuse(path, mode, *args, **kwargs):
        if Path(path) == directory:
            raise PermissionError("read-only")
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(inflight.os, "chmod", _refuse)
    try:
        handle, state = inflight.claim_or_unavailable("fresh")
        assert handle is None
        assert state == inflight.UNKNOWN, "an unusable lock is neither held nor free"
        assert inflight.liveness("fresh") == inflight.UNKNOWN, (
            "an unusable lock must be UNKNOWN, not FREE: FREE is the client's"
            " proof of death and it answers with 'resend'"
        )
    finally:
        # real_chmod, not os.chmod: monkeypatch tears down after this block, and
        # the injected refusal covers exactly this directory.
        real_chmod(directory, stat.S_IRWXU)


def test_a_lock_file_owned_by_another_user_fails_open(lock_root: Path) -> None:
    """A lock the caller cannot even open is neither held nor free."""
    path = inflight._lock_path("victim")
    assert path is not None
    path.touch()
    os.chmod(path, 0o000)
    try:
        handle, state = inflight.claim_or_unavailable("victim")
        assert handle is None and state == inflight.UNKNOWN
        assert inflight.liveness("victim") == inflight.UNKNOWN
    finally:
        os.chmod(path, 0o600)


def test_claimed_context_yields_true_when_locking_is_unavailable(lock_root: Path) -> None:
    directory = inflight._lock_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with inflight.claimed("fresh") as acquired:
            assert acquired, "the in-process transport must not refuse on an unusable lock"
    finally:
        os.chmod(directory, stat.S_IRWXU)


def test_claimed_context_yields_false_under_real_contention(lock_root: Path) -> None:
    handle, _state = inflight.claim_or_unavailable("busy")
    try:
        with inflight.claimed("busy") as acquired:
            assert not acquired
    finally:
        inflight.release(handle)


def test_the_read_path_never_creates_a_lock_file(lock_root: Path) -> None:
    """Creating the file on a read hands the first *viewer* of a session a say in who may
    write it — and the two writers this serialises are a service and a CLI, the pair
    most likely to differ in uid.
    """
    directory = lock_root / "agent" / "locks"

    assert inflight.liveness("never-sent") == inflight.FREE
    assert not directory.exists() or not any(
        directory.iterdir()
    ), "a read created a lock file"

    handle, _ = inflight.claim_or_unavailable("has-sent")
    try:
        assert handle is not None
        assert any(directory.iterdir()), "a claim must create its lock file"
    finally:
        inflight.release(handle)


def test_a_turn_running_unserialised_still_reports_in_flight(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-open must not also drop turnInFlight."""
    from TerraFin.interface.agent import data_routes

    monkeypatch.setattr(
        inflight,
        "claim_or_unavailable",
        lambda session_id, create=True: (None, inflight.UNKNOWN),
    )
    session_id = "terrafin-session:unserialised"

    assert data_routes._claim_turn(session_id), "unavailable locking must not refuse"
    try:
        assert data_routes._turn_in_flight(session_id), "a running turn must report in flight"
        assert not data_routes._claim_turn(session_id), "same-process double send must still 409"
    finally:
        data_routes._mark_turn_finished(session_id)
    assert not data_routes._turn_in_flight(session_id)


def test_an_unknowable_liveness_suppresses_the_death_report(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """turnUnfinished is the client's proof of death and it answers by telling the user to
    resend.
    """
    from TerraFin.agent.contracts.conversation import make_tool_use_block
    from TerraFin.interface.agent import data_routes
    from TerraFin.agent.loop import TerraFinConversationMessage

    def _Conv(messages=()):
        return tuple(messages)

    dead_mid_tool = _Conv(
        [
            TerraFinConversationMessage(role="user", content="Q"),
            TerraFinConversationMessage(
                role="assistant",
                content="",
                metadata={"internalOnly": True, "internalToolUse": True},
                blocks=(
                    make_tool_use_block(call_id="call_A", tool_name="market_snapshot", arguments={}),
                ),
            ),
        ]
    )

    # Knowable: the death is reported.
    monkeypatch.setattr(inflight, "liveness", lambda session_id: inflight.FREE)
    assert data_routes._reportable_death("s", messages=dead_mid_tool) == "mid-tool"

    # Unknowable: it is not.
    monkeypatch.setattr(inflight, "liveness", lambda session_id: inflight.UNKNOWN)
    assert data_routes._reportable_death("s", messages=dead_mid_tool) is None


def test_a_lock_the_caller_cannot_write_is_still_usable(lock_root: Path) -> None:
    """O_RDWR alone made the second writer EACCES out on the first writer's umask-governed
    0o644 file — which fails open, so the claim silently becomes a no-op and liveness
    reads UNKNOWN forever, suppressing every death report for that session.
    """
    path = inflight._lock_path("shared")
    assert path is not None
    path.touch()
    os.chmod(path, 0o444)  # stands in for another uid's 0o644
    try:
        handle, state = inflight.claim_or_unavailable("shared")
        try:
            assert handle is not None and state == inflight.FREE, (
                "a read-only lock file must still serialise the turn"
            )
            assert inflight.liveness("shared") == inflight.CONTENDED
        finally:
            inflight.release(handle)
    finally:
        os.chmod(path, 0o644)


def test_a_broken_symlink_lock_dir_reads_the_same_on_both_paths(lock_root: Path) -> None:
    """_can_create answers in permission bits what the writer answers with a syscall, and
    every disagreement resolves to FREE — a death report on a live turn.
    """
    base = lock_root / "agent"
    base.mkdir(parents=True, exist_ok=True)
    (base / "locks").symlink_to(base / "does-not-exist")

    handle, state = inflight.claim_or_unavailable("s")
    inflight.release(handle)
    assert handle is None and state == inflight.UNKNOWN, "the writer cannot create here"
    assert inflight.liveness("s") == state, "the read path must not disagree with the writer"


def test_one_probe_decides_both_turn_fields(lock_root: Path) -> None:
    """turnInFlight and turnUnfinished answer the same question."""
    from TerraFin.interface.agent import data_routes

    def _Conv(messages=()):
        return tuple(messages)

    handle, _state = inflight.claim_or_unavailable("held")
    try:
        assert data_routes._turn_state("held") == inflight.CONTENDED
        assert data_routes._reportable_death("held", messages=_Conv()) is None, (
            "a demonstrably live turn must never carry a death report"
        )
    finally:
        inflight.release(handle)

    probes = {"n": 0}
    real = inflight.liveness

    def _counted(session_id: str) -> str:
        probes["n"] += 1
        return real(session_id)

    import unittest.mock

    with unittest.mock.patch.object(inflight, "liveness", _counted):
        data_routes._turn_state("quiet")
    assert probes["n"] == 1, f"one probe per response, got {probes['n']}"


def test_a_writable_lock_is_opened_writable(lock_root: Path) -> None:
    """O_RDONLY-only loses the same-uid case on NFS, where Linux emulates flock() as a
    whole-file POSIX lock and F_SETLK/F_WRLCK on a descriptor not open for writing is
    EBADF — UNKNOWN for every session, on the one filesystem family this module's fail-
    open exists for.
    """
    import fcntl as _fcntl

    handle, state = inflight.claim_or_unavailable("writable")
    try:
        assert handle is not None and state == inflight.FREE
        mode = _fcntl.fcntl(handle, _fcntl.F_GETFL) & os.O_ACCMODE
        assert mode == os.O_RDWR, f"expected a writable descriptor, got {mode}"
    finally:
        inflight.release(handle)


def test_the_release_of_a_fallback_handle_frees_the_lock(lock_root: Path) -> None:
    """LOCK_UN on a read-only descriptor: if it were a no-op the session would be
    permanently CONTENDED, and CONTENDED is the one state that 409s every send."""
    path = inflight._lock_path("fallback")
    assert path is not None
    path.touch()
    os.chmod(path, 0o444)
    try:
        handle, state = inflight.claim_or_unavailable("fallback")
        assert handle is not None and state == inflight.FREE
        inflight.release(handle)
        assert inflight.liveness("fallback") == inflight.FREE, "the fallback handle did not release"
    finally:
        os.chmod(path, 0o644)


def test_the_lock_mode_follows_the_store_not_the_lock_dir(lock_root: Path) -> None:
    """Deriving from `locks/` is circular: this module creates it under the first writer's
    umask, so it reproduces exactly the umask-governance it replaced.
    """
    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    locks = inflight._lock_dir()
    locks.mkdir(parents=True, exist_ok=True)
    os.chmod(locks, 0o700)  # whatever locks/ says must not matter

    for store_mode, expected in ((0o755, 0o644), (0o750, 0o640), (0o700, 0o600), (0o711, 0o644)):
        os.chmod(store, store_mode)
        assert inflight._lock_mode(locks) == expected, (
            f"store {oct(store_mode)} should give {oct(expected)},"
            f" got {oct(inflight._lock_mode(locks))}"
        )
    os.chmod(store, 0o755)


def test_the_lock_dir_mirrors_the_store_in_both_directions(lock_root: Path) -> None:
    """mkdir is umask-governed both ways."""
    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)

    for store_mode in (0o700, 0o750, 0o755, 0o711):
        os.chmod(store, store_mode)
        assert inflight._lock_path("s") is not None
        got = os.stat(inflight._lock_dir()).st_mode & 0o7777
        wanted = store_mode | 0o700 | 0o2000 | 0o1000
        assert got == wanted, (
            f"store {oct(store_mode)} should give locks/ {oct(wanted)}, got {oct(got)}"
        )
    os.chmod(store, 0o755)


def test_a_claim_repairs_a_lock_left_too_narrow(lock_root: Path) -> None:
    """os.open's mode argument is masked by the umask and a file already on disk never gets
    one, so neither can widen a 0o600 lock left by an earlier rule or a hardened umask.
    """
    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o755)  # the operator's declaration; 0o644 follows from it
    path = inflight._lock_path("legacy")
    assert path is not None
    path.touch()
    os.chmod(path, 0o600)

    handle, state = inflight.claim_or_unavailable("legacy")
    try:
        assert handle is not None and state == inflight.FREE
        assert os.stat(path).st_mode & 0o777 == 0o644, (
            f"claim left the lock at {oct(os.stat(path).st_mode & 0o777)}"
        )
    finally:
        inflight.release(handle)


def test_the_read_path_leaves_an_existing_mode_alone(lock_root: Path) -> None:
    """A read must leave the store exactly as it found it. The next real send
    repairs the mode, which is when it matters."""
    path = inflight._lock_path("untouched")
    assert path is not None
    path.touch()
    os.chmod(path, 0o600)

    assert inflight.liveness("untouched") == inflight.FREE
    assert os.stat(path).st_mode & 0o777 == 0o600, "a read modified the store"


def test_a_claim_repairs_a_lock_it_had_to_open_read_only(lock_root: Path) -> None:
    """The one path that most needed widening was the one skipping it: the O_RDONLY
    fallback returned before the repair, so a lock this caller owns but that lacks
    owner-write stayed unwritable forever — and per the module docstring that descriptor
    is the NFS F_SETLK/EBADF case the fallback exists to avoid, so the session would
    read UNKNOWN indefinitely.
    """
    path = inflight._lock_path("readonly-own")
    assert path is not None
    path.touch()
    os.chmod(path, 0o444)

    handle, state = inflight.claim_or_unavailable("readonly-own")
    try:
        assert handle is not None and state == inflight.FREE
        assert os.stat(path).st_mode & 0o777 == 0o644, (
            f"the fallback path left the lock at {oct(os.stat(path).st_mode & 0o777)}"
        )
    finally:
        inflight.release(handle)


def test_a_narrow_lock_dir_this_process_owns_is_repaired(lock_root: Path) -> None:
    """The counterpart to the fail-open above."""
    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    directory = inflight._lock_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o755)
    os.chmod(directory, 0o500)

    handle, state = inflight.claim_or_unavailable("repairable")
    try:
        assert handle is not None and state == inflight.FREE, (
            "a narrow locks/ this process owns must be repaired, not failed open"
        )
        assert os.stat(directory).st_mode & 0o7777 == 0o3755
    finally:
        inflight.release(handle)


def test_narrowing_is_confined_to_a_lock_dir_this_process_placed(lock_root: Path) -> None:
    """`<store>/locks` may be a symlink, a bind mount or operator-precreated, and os.chmod
    follows symlinks — so mirroring would rewrite a directory this module neither made
    nor placed, stripping its sticky bit and its group write.
    """
    import tempfile

    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o750)
    shared = Path(tempfile.mkdtemp())
    os.chmod(shared, 0o1777)
    inflight._lock_dir().symlink_to(shared)

    assert inflight._lock_path("s") is not None, "a symlinked locks/ must still work"
    assert os.stat(shared).st_mode & 0o7777 == 0o1777, (
        f"rewrote a directory it did not place: {oct(os.stat(shared).st_mode & 0o7777)}"
    )


def test_the_sticky_bit_is_kept_on_a_group_shared_store(lock_root: Path) -> None:
    """Directory write permission is delete permission."""
    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o770)

    assert inflight._lock_path("s") is not None
    mode = os.stat(inflight._lock_dir()).st_mode
    assert mode & stat.S_ISVTX, f"locks/ is group-writable without sticky: {oct(mode & 0o7777)}"


def test_the_fallback_takes_the_writable_descriptor_it_just_earned(lock_root: Path) -> None:
    """Repairing the mode for the *next* claim leaves this turn holding exactly the read-
    only descriptor that is the NFS F_SETLK/EBADF case, so it would still read UNKNOWN —
    the repair would arrive one turn late.
    """
    import fcntl as _fcntl

    path = inflight._lock_path("late-repair")
    assert path is not None
    path.touch()
    os.chmod(path, 0o444)

    handle, state = inflight.claim_or_unavailable("late-repair")
    try:
        assert handle is not None and state == inflight.FREE
        accmode = _fcntl.fcntl(handle, _fcntl.F_GETFL) & os.O_ACCMODE
        assert accmode == os.O_RDWR, "the repair must be taken up in the same claim"
    finally:
        inflight.release(handle)


def test_a_self_created_store_root_matches_the_transcript_store(lock_root: Path) -> None:
    """Whichever component creates the store root first decides its mode, so they must
    agree.
    """
    store = inflight._lock_dir().parent
    assert not store.exists(), "precondition: a store that was never written"

    previous = os.umask(0o022)
    try:
        handle, state = inflight.claim_or_unavailable("s")
        try:
            assert handle is not None and state == inflight.FREE
            assert os.stat(store).st_mode & 0o777 == 0o755, (
                f"store root is {oct(os.stat(store).st_mode & 0o777)}; the transcript"
                " store's own mkdir at this umask would give 0o755"
            )
        finally:
            inflight.release(handle)
    finally:
        os.umask(previous)


def test_the_lock_dir_takes_the_stores_group_not_the_creators(lock_root: Path) -> None:
    """S_ISGID propagates *locks/*'s group, not the store's, and on Linux locks/ takes the
    creating writer's egid unless the store itself is setgid — so the bits come out
    right and the group wrong.
    """
    others = [g for g in os.getgroups() if g != os.getegid()]
    if not others:
        pytest.skip("needs a second group to tell the store's group from the creator's")

    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o770)
    os.chown(store, -1, others[0])
    locks = inflight._lock_dir()
    locks.mkdir(parents=True, exist_ok=True)
    os.chown(locks, -1, os.getegid())  # what mkdir gives on Linux
    assert os.stat(locks).st_gid != os.stat(store).st_gid, "precondition: groups differ"

    path = inflight._lock_path("s")
    assert path is not None
    assert os.stat(locks).st_gid == others[0], (
        f"locks/ kept gid {os.stat(locks).st_gid}; the store's is {others[0]}"
    )

    handle, _state = inflight.claim_or_unavailable("s")
    try:
        assert os.stat(path).st_gid == others[0], "the lock file must land in the store's group"
    finally:
        inflight.release(handle)


def test_a_chown_that_clears_setgid_is_repaired_in_the_same_claim(lock_root: Path) -> None:
    """A non-root chown clears S_ISGID from a directory on Darwin (measured: 0o3775 ->
    0o1775), even when the gid is unchanged.
    """
    others = [g for g in os.getgroups() if g != os.getegid()]
    if not others:
        pytest.skip("needs a second group to make the chown do anything")

    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o770)
    os.chown(store, -1, others[0])
    locks = inflight._lock_dir()
    locks.mkdir(parents=True, exist_ok=True)
    os.chown(locks, -1, os.getegid())
    os.chmod(locks, 0o770 | stat.S_ISGID | stat.S_ISVTX)  # already at `wanted`

    assert inflight._lock_path("s") is not None
    mode = os.lstat(locks).st_mode
    assert os.lstat(locks).st_gid == others[0], "the chown must land"
    assert mode & stat.S_ISGID, (
        f"the chown cleared setgid and the chmod was short-circuited: {oct(mode & 0o7777)}"
    )


def test_a_stale_lock_files_group_is_repaired(lock_root: Path) -> None:
    """Setgid on locks/ fixes the group of every *future* lock file and cannot reach one
    that already exists, and mode bits alone cannot rescue a wrong group: _shared_bits
    never grants group write and other is empty on a group-shared store, so a peer
    writer EACCESes both opens and that session reads UNKNOWN forever with every death
    report suppressed.
    """
    others = [g for g in os.getgroups() if g != os.getegid()]
    if not others:
        pytest.skip("needs a second group to tell a stale group from the store's")

    store = inflight._lock_dir().parent
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o770)
    os.chown(store, -1, others[0])
    path = inflight._lock_path("stale")
    assert path is not None
    path.touch()
    os.chown(path, -1, os.getegid())  # the pre-upgrade creator's egid
    os.chmod(path, 0o600)

    handle, state = inflight.claim_or_unavailable("stale")
    try:
        assert handle is not None and state == inflight.FREE
        assert os.stat(path).st_gid == others[0], (
            f"stale lock kept gid {os.stat(path).st_gid}; the store's is {others[0]}"
        )
        assert os.stat(path).st_mode & 0o777 == 0o640
    finally:
        inflight.release(handle)


class _RecordingLoop:
    """Enough of the loop to see whether its cache was dropped."""

    def __init__(self, *, has_store: bool = True, stamp: str = "t0") -> None:
        self.forgotten: list[str] = []
        store = None
        if has_store:
            entry = type("_Entry", (), {"updated_at": stamp})()
            store = type("_Store", (), {"get_session_index": lambda _self, _sid: entry})()
        self.runtime = type("_Rt", (), {"transcript_store": store})()

    def bump(self, stamp: str) -> None:
        entry = type("_Entry", (), {"updated_at": stamp})()
        self.runtime.transcript_store.get_session_index = lambda _sid: entry

    def forget_conversation(self, session_id: str) -> None:
        self.forgotten.append(session_id)


def test_a_foreign_write_drops_this_processes_cached_transcript(lock_root: Path) -> None:
    """get_conversation returns the cached object and re-reads the store only on a miss, so
    a turn run by the other writer is invisible here: the served messages never grow and
    the browser is never shown the answer the 409 told it to wait for.
    """
    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(stamp="t0")
    session_id = "terrafin-session:foreign"
    data_routes._TRANSCRIPT_SEEN.pop(session_id, None)
    try:
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id], "an unseen transcript must be read once"
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id], "an unchanged stamp must not reload"

        loop.bump("t1")  # the other writer appended, and never held the lock here
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id, session_id], "a foreign append must reload"
        data_routes._drop_stale_conversation(loop, session_id)
        assert len(loop.forgotten) == 2, "exactly one reload per change"
    finally:
        data_routes._TRANSCRIPT_SEEN.pop(session_id, None)


def test_this_processes_own_turn_does_not_trigger_a_reload(lock_root: Path) -> None:
    """Every local turn would otherwise leave the stamp behind its own append, so
    the next GET reloads the whole transcript for a change it made itself."""
    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(stamp="t0")
    session_id = "terrafin-session:ours"
    data_routes._TRANSCRIPT_SEEN.pop(session_id, None)
    try:
        data_routes._drop_stale_conversation(loop, session_id)
        loop.forgotten.clear()

        loop.bump("t1")  # our own submit_user_message appended
        data_routes._note_transcript_stamp(loop, session_id)
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [], "reloaded the transcript for our own append"
    finally:
        data_routes._TRANSCRIPT_SEEN.pop(session_id, None)


def test_a_local_turn_never_has_its_conversation_swapped(lock_root: Path) -> None:
    """The loop is mutating that object mid-turn."""
    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(stamp="t9")
    session_id = "terrafin-session:mine"
    data_routes._TRANSCRIPT_SEEN.pop(session_id, None)
    assert data_routes._claim_turn(session_id)
    try:
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [], "dropped the cache under a running local turn"
    finally:
        data_routes._mark_turn_finished(session_id)
        data_routes._TRANSCRIPT_SEEN.pop(session_id, None)


def test_without_a_transcript_store_the_stale_view_is_kept(lock_root: Path) -> None:
    """There is no stamp and nothing to reload from: get_conversation would raise KeyError
    and the served transcript would come back empty.
    """
    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(has_store=False)
    session_id = "terrafin-session:no-store"
    data_routes._TRANSCRIPT_SEEN.pop(session_id, None)
    try:
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == []
    finally:
        data_routes._TRANSCRIPT_SEEN.pop(session_id, None)


def test_concurrent_gets_never_serve_a_transcript_one_of_them_dropped(
    lock_root: Path,
) -> None:
    """The compare, the record and the drop are one critical section."""
    from concurrent.futures import ThreadPoolExecutor

    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(stamp="t1")
    session_id = "terrafin-session:concurrent"
    data_routes._TRANSCRIPT_SEEN.pop(session_id, None)
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda _: data_routes._drop_stale_conversation(loop, session_id), range(64)))
        assert loop.forgotten == [session_id], (
            f"{len(loop.forgotten)} reloads for one change; the section is not atomic"
        )
    finally:
        data_routes._TRANSCRIPT_SEEN.pop(session_id, None)


def test_the_stamp_tracks_a_real_transcript_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fakes above carry a string stamp, so nothing exercised a real `datetime`."""
    from TerraFin.agent.storage.transcript_store import HostedTranscriptStore
    from TerraFin.interface.agent import data_routes

    store = HostedTranscriptStore(root_dir=tmp_path / "agent")
    session_id = "terrafin-session:real-store"
    store.create_session(session_id=session_id, agent_name="a", created_at=datetime.now(UTC))

    class _Loop:
        def __init__(self) -> None:
            self.forgotten: list[str] = []
            self.runtime = type("_Rt", (), {"transcript_store": store})()

        def forget_conversation(self, sid: str) -> None:
            self.forgotten.append(sid)

    loop = _Loop()
    data_routes._forget_transcript_stamp(session_id)
    try:
        first = data_routes._transcript_stamp(loop, session_id)
        assert first and "+00:00" in first, f"expected an aware ISO stamp, got {first!r}"

        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id], "an unseen transcript must be read once"
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id], "an unchanged stamp must not reload"

        store.append_message(
            session_id,
            TerraFinConversationMessage(role="user", content="from the other writer"),
        )
        assert data_routes._transcript_stamp(loop, session_id) != first, "an append must move the stamp"
        data_routes._drop_stale_conversation(loop, session_id)
        assert loop.forgotten == [session_id, session_id], "a foreign append must reload"
    finally:
        data_routes._forget_transcript_stamp(session_id)


def test_a_deleted_session_does_not_leak_its_stamp(lock_root: Path) -> None:
    """The delete route calls forget_conversation one line away; the stamp has to
    go with it or the dict grows for the life of the process."""
    from TerraFin.interface.agent import data_routes

    loop = _RecordingLoop(stamp="t0")
    session_id = "terrafin-session:deleted"
    data_routes._drop_stale_conversation(loop, session_id)
    assert session_id in data_routes._TRANSCRIPT_SEEN
    data_routes._forget_transcript_stamp(session_id)
    assert session_id not in data_routes._TRANSCRIPT_SEEN


def _session_record(session_id: str):
    """The minimum `_session_response` reads off a record."""
    from types import SimpleNamespace

    from TerraFin.agent.runtime import TerraFinAgentSession

    session = TerraFinAgentSession(session_id=session_id, metadata={})
    return SimpleNamespace(
        session_id=session_id,
        agent_name="a",
        context=SimpleNamespace(session=session, task_registry=SimpleNamespace(list_for_session=lambda _s: ())),
        conversation=None,
        approval_requests=(),
        audit_log=(),
    )


def test_a_transcript_moving_under_the_read_reports_a_live_turn(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single liveness probe is taken before the transcript it judges, and a cold
    reload of index plus transcript is ~25ms.
    """
    from TerraFin.interface.agent import data_routes

    class _SettledConversation:
        def snapshot(self):
            return ()

    session_id = "terrafin-session:bracket"
    loop = _RecordingLoop(stamp="t0")
    conv = _SettledConversation()
    loop.get_conversation = lambda _sid: conv  # type: ignore[attr-defined]
    monkeypatch.setattr(inflight, "liveness", lambda _sid: inflight.FREE)
    monkeypatch.setattr(data_routes, "_turn_unfinished", lambda _c, **_kw: "no-answer")
    data_routes._forget_transcript_stamp(session_id)
    record = _session_record(session_id)
    try:
        quiet = data_routes._session_response(record, loop=loop, tools=())
        assert quiet.metadata["turnInFlight"] is False
        assert quiet.metadata["turnUnfinished"] == "no-answer", "a settled transcript still reports its death"

        # A foreign append lands while the transcript is being read.
        original = loop.get_conversation

        def _bump_then_read(sid):
            loop.bump("t1")
            return original(sid)

        loop.get_conversation = _bump_then_read  # type: ignore[attr-defined]
        raced = data_routes._session_response(record, loop=loop, tools=())
        assert raced.metadata["turnInFlight"] is True, (
            "a transcript that moved under the read must not be paired with a stale probe"
        )
        assert raced.metadata["turnUnfinished"] is None, "and must not report a death"
    finally:
        data_routes._forget_transcript_stamp(session_id)


def test_a_transcript_moving_during_the_snapshot_reports_a_live_turn(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verdict's own read has to be inside the bracket too."""
    from TerraFin.interface.agent import data_routes

    session_id = "terrafin-session:snapshot-race"
    loop = _RecordingLoop(stamp="t0")

    class _RacingConversation:
        def snapshot(self):
            loop.bump("t1")  # the other writer appends *during* the verdict's read
            return ()

    loop.get_conversation = lambda _sid: _RacingConversation()  # type: ignore[attr-defined]
    monkeypatch.setattr(inflight, "liveness", lambda _sid: inflight.FREE)
    monkeypatch.setattr(data_routes, "_turn_unfinished", lambda _m: "no-answer")
    data_routes._forget_transcript_stamp(session_id)
    record = _session_record(session_id)
    try:
        raced = data_routes._session_response(record, loop=loop, tools=())
        assert raced.metadata["turnInFlight"] is True, (
            "the snapshot the verdict comes from was taken outside the bracket"
        )
        assert raced.metadata["turnUnfinished"] is None, "and must not report a death"
    finally:
        data_routes._forget_transcript_stamp(session_id)


def test_an_unreadable_transcript_raises_rather_than_serving_an_empty_one(
    lock_root: Path,
) -> None:
    """`()` is indistinguishable from an empty transcript, and the client's handling of
    `{turnInFlight: false, turnUnfinished: null, messages: []}` is destructive: `grew`
    goes true, the on-screen transcript is replaced with an empty one, and the poller
    stops.
    """
    from TerraFin.interface.agent import data_routes

    class _Unreadable:
        def snapshot(self):
            raise RuntimeError("transcript unreadable")

    try:
        data_routes._conversation_snapshot(_Unreadable())
    except RuntimeError:
        pass
    else:
        raise AssertionError("an unreadable transcript was served as an empty one")

    assert data_routes._conversation_snapshot(None) == ()


def test_the_bracket_compares_the_stamp_the_drop_recorded(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three reads of one value became two, and the pre-bracket window went from
    a few microseconds to exactly zero."""
    from TerraFin.interface.agent import data_routes

    session_id = "terrafin-session:one-read"
    loop = _RecordingLoop(stamp="t0")
    data_routes._forget_transcript_stamp(session_id)
    reads = []
    real = data_routes._transcript_stamp
    monkeypatch.setattr(
        data_routes,
        "_transcript_stamp",
        lambda lp, sid: (reads.append(sid), real(lp, sid))[1],
    )
    try:
        recorded = data_routes._drop_stale_conversation(loop, session_id)
        assert recorded == "t0", "the drop must hand back the stamp it recorded"
        assert len(reads) == 1, f"the drop read the stamp {len(reads)} times"
    finally:
        data_routes._forget_transcript_stamp(session_id)


def test_a_real_death_reaches_the_response_through_the_snapshot(
    lock_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not the discriminator."""
    from TerraFin.agent.contracts.conversation import make_tool_use_block
    from TerraFin.agent.loop import TerraFinConversationMessage
    from TerraFin.interface.agent import data_routes

    class _DiedMidTool:
        def snapshot(self):
            return (
                TerraFinConversationMessage(role="user", content="Q"),
                TerraFinConversationMessage(
                    role="assistant",
                    content="",
                    metadata={"internalOnly": True, "internalToolUse": True},
                    blocks=(
                        make_tool_use_block(
                            call_id="call_orphan", tool_name="market_snapshot", arguments={}
                        ),
                    ),
                ),
            )

    session_id = "terrafin-session:real-death"
    loop = _RecordingLoop(stamp="t0")
    loop.get_conversation = lambda _sid: _DiedMidTool()  # type: ignore[attr-defined]
    monkeypatch.setattr(inflight, "liveness", lambda _sid: inflight.FREE)
    data_routes._forget_transcript_stamp(session_id)
    try:
        payload = data_routes._session_response(_session_record(session_id), loop=loop, tools=())
        assert payload.metadata["turnInFlight"] is False
        assert payload.metadata["turnUnfinished"] == "mid-tool", (
            "the snapshot the response serves is not the one the verdict is taken from"
        )
    finally:
        data_routes._forget_transcript_stamp(session_id)


def test_the_session_derived_fields_come_from_one_snapshot(lock_root: Path) -> None:
    """Three `session.snapshot()` calls in one return statement could describe
    three different states. Restoring them leaves the suite green, so pin it."""
    from types import SimpleNamespace

    from TerraFin.interface.agent import data_routes

    generation = {"n": 0}

    class _MovingSession:
        metadata: dict = {}

        def snapshot(self):
            generation["n"] += 1
            tag = generation["n"]
            return SimpleNamespace(
                focus_items=[f"focus-{tag}"],
                artifacts=[],
                capability_calls=[],
            )

    record = SimpleNamespace(
        session_id="terrafin-session:one-session-snapshot",
        agent_name="a",
        context=SimpleNamespace(
            session=_MovingSession(),
            task_registry=SimpleNamespace(list_for_session=lambda _s: ()),
        ),
        conversation=None,
        approval_requests=(),
        audit_log=(),
    )

    payload = data_routes._session_response(record, loop=None, tools=())
    assert payload.focusItems == ["focus-1"], f"served {payload.focusItems}"
    assert generation["n"] == 1, (
        f"the session was snapshotted {generation['n']} times in one response"
    )
