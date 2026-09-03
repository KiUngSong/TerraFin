"""Cross-process claim on a session's turn.

Two processes reach `submit_user_message`: the HTTP route and
`TerraFinAgentClient.runtime_message` over the in-process transport. Each
builds its own conversation cache, so an in-memory set cannot see the other.

The lock lives beside the transcripts it guards, resolved from the same
`TERRAFIN_AGENT_TRANSCRIPT_DIR` the store uses, so two processes sharing a
store cannot lock in different directories.

Every "cannot lock" outcome fails **open**. Unserialised turns are the
pre-lock status quo; failing closed would 409 a session forever and pin
`turnInFlight`, disabling every exit in the client's poller.

The lock's reach is a function of a mode this module never chose: an
operator's chmod on the store, or failing that the umask their own `mkdir`
would have used. `flock` is released by the kernel when a holder dies, which
is why it beats a pid file — but there is no breaker for a holder that is
alive and wedged.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import stat as stat_module
from contextlib import contextmanager
from pathlib import Path

from TerraFin.env import resolve_state_dir

FREE = "free"            # demonstrably nobody holds it
CONTENDED = "contended"  # demonstrably some writer holds it, here or elsewhere
UNKNOWN = "unknown"      # locking is unusable here; no verdict is possible


def _lock_dir() -> Path:
    # Same override the transcript store reads (service/hosted.py), so the lock
    # always sits beside the data it protects.
    # Read exactly as service/hosted.py does, so the lock cannot land somewhere
    # other than the store on a padded or empty value.
    root = os.environ.get("TERRAFIN_AGENT_TRANSCRIPT_DIR")
    base = Path(root) if root is not None else resolve_state_dir() / "agent"
    return base / "locks"


def _lock_path(session_id: str, *, create_dir: bool = True) -> Path | None:
    directory = _lock_dir()
    if create_dir:
        try:
            # `parents`, at umask, exactly as HostedTranscriptStore creates the
            # same root (transcript_store.py). Whichever component gets there
            # first decides the mode, so they must agree: a private mode here
            # would make the store's reach depend on whether transcripts happen
            # to be enabled (`transcript_store` defaults to None in
            # runtime/hosted.py), and a `0o700` root nothing later corrects
            # denies a peer uid traversal for the life of the deployment.
            #
            # That leaves this module reading back a mode it may have authored
            # itself, which is the circularity rejected for `locks/`. It is not
            # avoidable here — where nobody has created the store, no operator
            # declaration exists to read — and the exposure it carries is one
            # empty file at the deployment's own umask, named by a digest of a
            # uuid4 session id.
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        _repair_dir_mode(directory)
    # No secret: both writers compute this from a session id they share.
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return directory / f"{digest}.lock"


def _can_create(directory: Path) -> bool:
    """Whether a writer could create a lock file here.

    Answers in permission bits what the writer answers with a syscall, and every
    disagreement resolves to FREE — a death report on a live turn. So it is
    pessimistic: `lexists` and an explicit `is_dir`, because a broken symlink or
    a non-directory component is something `mkdir` refuses. A full partition or
    an immutable mount stay invisible to `access(2)`.
    """
    probe = directory
    while True:
        if os.path.lexists(probe):
            return probe.is_dir() and os.access(probe, os.W_OK | os.X_OK)
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent


def _shared_bits(store: Path) -> int:
    """Who the store lets in, as read bits.

    Derived from the store directory, not from `locks/`: this module creates
    `locks/` under the first writer's umask, so reading it back would just
    reproduce that umask. Execute alone, not r-x — opening a known path needs
    traversal, not listing, and the lock's name is no secret.
    """
    try:
        granted = os.stat(store).st_mode & 0o777
    except OSError:
        return 0o400
    reachable = 0
    for read, execute in ((0o400, 0o100), (0o040, 0o010), (0o004, 0o001)):
        if granted & execute:
            reachable |= read
    return reachable | 0o400


def _lock_mode(directory: Path) -> int:
    """The mode a lock file should carry. `directory` is the lock dir itself."""
    return _shared_bits(directory.parent) | 0o600


def _repair_dir_mode(directory: Path) -> None:
    """Let `locks/` reach exactly as far as the store, and no further.

    `mkdir` is umask-governed both ways, so this both widens and narrows — the
    one place here that narrows. Setgid and an explicit chown because a lock
    file otherwise takes the creating writer's group, leaving the bits right and
    the group wrong. Sticky because directory write is delete permission and the
    store this supports is group-shared.

    Confined to a directory this euid owns and that is not a symlink: otherwise
    `<store>/locks` may be a bind mount or operator-made, and mirroring would
    rewrite something this module never placed.
    """
    try:
        wanted = (os.stat(directory.parent).st_mode & 0o777) | 0o700
        wanted |= stat_module.S_ISGID | stat_module.S_ISVTX
    except OSError:
        return
    try:
        info = os.lstat(directory)
    except OSError:
        return
    if stat_module.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
        return  # not ours to place, so not ours to narrow
    store_gid = _store_gid(directory.parent)
    if store_gid is not None and info.st_gid != store_gid:
        try:
            os.chown(directory, -1, store_gid)
        except OSError:
            # Not a group this euid belongs to. Proceed rather than refuse: the
            # writer needed w+x on the store to create `locks/` at all, so it
            # holds that through owner or other, and `wanted` carries the
            # store's other-r-x — the peer traverses and reads regardless.
            # Refusing here would wedge exactly those deployments.
            pass
        else:
            # Re-read: a non-root chown clears S_ISGID from a directory on
            # Darwin (measured: 0o3775 -> 0o1775), even when the gid is
            # unchanged. Comparing the pre-chown mode below would short-circuit
            # the chmod that the chown itself just made necessary, leaving one
            # claim to create its lock file with the creator's egid.
            try:
                info = os.lstat(directory)
            except OSError:
                return
    if info.st_mode & 0o7777 == wanted:
        return
    try:
        os.chmod(directory, wanted)
    except OSError:
        pass


def _store_gid(store: Path) -> int | None:
    try:
        return os.stat(store).st_gid
    except OSError:
        return None


def _repair_mode(handle: int, wanted: int, *, store_gid: int | None = None) -> None:
    """Widen a lock left too narrow, and correct its group.

    `os.open`'s mode is umask-masked and a file already on disk never gets one,
    so neither can grant the bits the store implies. Setgid fixes the group of
    future files only; `fchown` reaches the one already here. Only ever widens.
    """
    try:
        info = os.fstat(handle)
    except OSError:
        return
    if store_gid is not None and info.st_gid != store_gid:
        try:
            os.fchown(handle, -1, store_gid)
        except OSError:
            pass  # same reasoning as the directory: proceed, do not refuse
    current = info.st_mode & 0o777
    if current | wanted == current:
        return
    try:
        os.fchmod(handle, current | wanted)
    except OSError:
        pass


def _open_lock(path: Path, *, create: bool) -> int:
    """A descriptor on the lock file, writable where permitted.

    `O_RDWR` is what NFS's POSIX-lock emulation needs; `O_RDONLY` is what
    another uid's file permits. Neither alone works.
    """
    creation = os.O_CREAT if create else 0
    mode = _lock_mode(path.parent)
    try:
        handle = os.open(path, os.O_RDWR | creation, mode)
    except FileNotFoundError:
        raise  # "no writer has ever claimed" — the caller reads it as such
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise
        # Another uid's file, or a read-only mount. flock takes a read handle on
        # every local filesystem. Falls through to the repair below: a lock this
        # caller *owns* but that lacks owner-write lands here, and leaving it
        # unrepaired is the NFS EBADF case the fallback exists to avoid — so the
        # one path that most needs widening was the one skipping it.
        handle = os.open(path, os.O_RDONLY | creation, mode)
        if create:
            _repair_mode(handle, mode, store_gid=_store_gid(path.parent.parent))
            # Take the writable descriptor the repair just made possible. Fixing
            # the mode for the *next* claim leaves this turn holding exactly the
            # read-only descriptor that is the NFS F_SETLK/EBADF case, so it
            # would still read UNKNOWN — the repair would arrive one turn late.
            try:
                writable = os.open(path, os.O_RDWR, mode)
            except OSError:
                pass
            else:
                os.close(handle)
                return writable
        return handle
    if create:
        # Write path only: a read must leave the store exactly as it found it.
        # The next real send repairs the mode, which is when it matters.
        _repair_mode(handle, mode, store_gid=_store_gid(path.parent.parent))
    return handle


def claim_or_unavailable(session_id: str, *, create: bool = True) -> tuple[int | None, str]:
    """(handle, state) where state is FREE, CONTENDED or UNKNOWN.

    Only CONTENDED may refuse a turn. UNKNOWN must let it proceed, but must
    never be reported as "nothing is running": the client treats that as proof
    of death. `create=False` is the read path — creating the file there would
    hand ownership to whichever process first *viewed* the session.
    """
    path = _lock_path(session_id, create_dir=create)
    if path is None:
        return None, UNKNOWN
    try:
        handle = _open_lock(path, create=create)
    except FileNotFoundError:
        # Normally "no writer has ever claimed". But where a writer could not
        # have created a lock either, absence proves nothing — judged on the
        # nearest existing ancestor, since the locks dir itself may simply not
        # exist yet on a session that has never sent.
        return None, FREE if _can_create(path.parent) else UNKNOWN
    except OSError:
        return None, UNKNOWN  # another uid's file, or a read-only dir
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(handle)
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None, CONTENDED
        return None, UNKNOWN  # flock refused for a reason other than contention
    return handle, FREE


def release(handle: int | None) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def liveness(session_id: str) -> str:
    """FREE, CONTENDED or UNKNOWN, without creating anything."""
    handle, state = claim_or_unavailable(session_id, create=False)
    if handle is None:
        return state
    release(handle)
    return FREE


@contextmanager
def claimed(session_id: str):
    """Hold the turn lock, yielding False only if another writer holds it."""
    handle, state = claim_or_unavailable(session_id)
    try:
        yield state != CONTENDED
    finally:
        release(handle)
