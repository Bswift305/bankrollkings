"""
Kernel-backed, fd-based exclusive process lock (2026-11, NBA game-lines single publisher).

Contract (the Linux path is the production contract):
  * Linux/POSIX: fcntl.flock(fd, LOCK_EX | LOCK_NB) on an fd opened O_RDWR|O_CREAT|O_NOFOLLOW. The kernel
    releases the lock when the last fd referring to the open file description closes -- including when the
    process exits or crashes (SIGKILL, earlyoom SIGTERM, OOM). There are NO stale-lockfile semantics: the
    file's existence or content never means "locked"; only the kernel lock does. The file is never unlinked
    (unlinking a flock'd path lets a second process lock a NEW inode and breaks mutual exclusion).
  * Windows (local dev / QC only): msvcrt.locking(fd, LK_NBLCK, 1) on byte 0 -- also released by the OS
    when the handle closes or the process exits, so QC can exercise two-process contention locally.

Location enforcement (v4, owner decision 3) -- every check fails CLOSED with LockPathRejected (a
LockUnavailable), BEFORE the caller can make any paid request:
  * Containment: the lock file must resolve (os.path.realpath, all symlinks/junctions followed) to a path
    directly inside its lock directory, and the lock directory must resolve to a path inside the declared
    `root` (the runtime dir). A path that escapes the root is refused.
  * No symlink escape: a lock DIRECTORY that is itself a symlink is refused; a lock FILE that is a symlink
    is refused (lstat check, then O_NOFOLLOW where the platform has it -> ELOOP is refused too); after open
    the fd's inode must be the inode at the path (no swap between check and open) and, on POSIX, a regular
    file with exactly one link (a hard link could alias a file outside the root).
  * POSIX permissions: the lock dir is created 0700 and the lock file 0600. An EXISTING dir/file that is
    looser is REPAIRED (chmod 0700 / fchmod 0600) when this process's euid owns it, then re-verified; one
    owned by another uid, or still loose after repair, is REFUSED. Rationale: prod dirs created by an older
    install (`install -m 755`) self-heal on the first run instead of stranding the job, while a dir/file we
    do not own is never trusted. Windows has no POSIX modes: the mode checks are skipped there (dev only).

The holder's pid / label / acquisition time are written into the file purely as operator information.
Pure stdlib; no app import.
"""
from __future__ import annotations

import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

if os.name == "nt":  # pragma: no cover - platform branch
    import msvcrt
else:
    import fcntl

LOCK_DIR_MODE = 0o700
LOCK_FILE_MODE = 0o600
POSIX_MODES_ENFORCED = os.name != "nt"


class LockUnavailable(OSError):
    """The lock file could not be opened/created (e.g. missing or unwritable lock directory)."""


class LockPathRejected(LockUnavailable):
    """The lock location failed containment / symlink / ownership / permission enforcement."""


def real(path) -> str:
    """Canonical comparison form: every symlink/junction resolved, case-normalised on Windows."""
    return os.path.normcase(os.path.realpath(str(path)))


def is_within(child, root) -> bool:
    """True when real(child) is root or inside it (both already-resolved strings or paths)."""
    c, r = real(child), real(root)
    try:
        return os.path.commonpath([c, r]) == r
    except ValueError:   # different drives on Windows
        return False


def _repair_or_refuse(st, what: str, want: int, chmod) -> None:
    """POSIX only: refuse a loose mode we do not own; repair one we do (then the caller re-verifies)."""
    if not POSIX_MODES_ENFORCED or not (st.st_mode & 0o077):
        return
    if st.st_uid != os.geteuid():
        raise LockPathRejected(f"{what} mode {oct(stat.S_IMODE(st.st_mode))} is looser than {oct(want)} "
                               f"and is owned by uid {st.st_uid}, not this process (euid {os.geteuid()})")
    try:
        chmod(want)
    except OSError as exc:
        raise LockPathRejected(f"{what} mode {oct(stat.S_IMODE(st.st_mode))} is looser than {oct(want)} "
                               f"and could not be repaired: {exc}") from exc


def _validated_lock_dir(lock_dir: Path, root: Path) -> str:
    """Create (0700) or verify the lock directory; return its real path. Raises LockPathRejected/LockUnavailable."""
    try:
        os.makedirs(str(root), exist_ok=True)
    except OSError as exc:
        raise LockUnavailable(f"cannot create lock root {root}: {exc}") from exc
    if os.path.islink(str(lock_dir)):
        raise LockPathRejected(f"lock directory {lock_dir} is a symlink (refused: symlink escape)")
    if not is_within(lock_dir, root):
        raise LockPathRejected(f"lock directory {lock_dir} resolves outside the lock root {real(root)} (refused)")
    if not os.path.exists(str(lock_dir)):
        try:
            os.makedirs(str(lock_dir.parent), exist_ok=True)
            os.mkdir(str(lock_dir), LOCK_DIR_MODE)
        except FileExistsError:
            pass
        except OSError as exc:
            raise LockUnavailable(f"cannot create lock directory {lock_dir}: {exc}") from exc
        if os.path.islink(str(lock_dir)):
            raise LockPathRejected(f"lock directory {lock_dir} became a symlink (refused)")
    if not os.path.isdir(str(lock_dir)):
        raise LockUnavailable(f"lock directory {lock_dir} is not a directory")
    dir_real = real(lock_dir)
    if not is_within(dir_real, root):
        raise LockPathRejected(f"lock directory {lock_dir} resolves to {dir_real}, outside the lock root "
                               f"{real(root)} (refused: symlink/junction escape)")
    if POSIX_MODES_ENFORCED:
        st = os.lstat(str(lock_dir))
        if not stat.S_ISDIR(st.st_mode):
            raise LockPathRejected(f"lock directory {lock_dir} is not a real directory")
        _repair_or_refuse(st, f"lock directory {lock_dir}", LOCK_DIR_MODE, lambda m: os.chmod(str(lock_dir), m))
        if os.lstat(str(lock_dir)).st_mode & 0o077:
            raise LockPathRejected(f"lock directory {lock_dir} is still looser than {oct(LOCK_DIR_MODE)}")
    return dir_real


def open_validated_lock_file(path, root) -> int:
    """Open (create 0600) the lock file after full location enforcement. Returns the fd.
    Raises LockPathRejected (enforcement) or LockUnavailable (cannot open). Never follows a symlinked file."""
    path, root = Path(path), Path(root)
    dir_real = _validated_lock_dir(path.parent, root)
    if os.path.islink(str(path)):
        raise LockPathRejected(f"lock file {path} is a symlink (refused: symlink escape)")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags, LOCK_FILE_MODE)
    except OSError as exc:
        import errno
        if exc.errno == getattr(errno, "ELOOP", -1):
            raise LockPathRejected(f"lock file {path} is a symlink (O_NOFOLLOW refused it)") from exc
        raise LockUnavailable(f"cannot open lock file {path}: {exc}") from exc
    try:
        if os.path.normcase(os.path.dirname(real(path))) != dir_real:
            raise LockPathRejected(f"lock file {path} resolves to {real(path)}, not inside {dir_real}")
        fst = os.fstat(fd)
        lst = os.lstat(str(path))
        if stat.S_ISLNK(lst.st_mode):
            raise LockPathRejected(f"lock file {path} is a symlink (refused)")
        if not stat.S_ISREG(fst.st_mode):
            raise LockPathRejected(f"lock file {path} is not a regular file")
        if POSIX_MODES_ENFORCED:
            if (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
                raise LockPathRejected(f"lock file {path} changed between check and open (refused)")
            if fst.st_nlink != 1:
                raise LockPathRejected(f"lock file {path} has {fst.st_nlink} hard links (refused: alias escape)")
            _repair_or_refuse(fst, f"lock file {path}", LOCK_FILE_MODE, lambda m: os.fchmod(fd, m))
            if os.fstat(fd).st_mode & 0o077:
                raise LockPathRejected(f"lock file {path} is still looser than {oct(LOCK_FILE_MODE)}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _try_lock(fd: int) -> bool:
    if os.name == "nt":  # pragma: no cover - platform branch
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except OSError as exc:
        import errno
        if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return False
        raise


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - platform branch
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class ExclusiveLock:
    """Non-blocking (optionally bounded-wait) exclusive lock. Use acquire()/release() or `with`.

    acquire() returns True when held, False when another process holds it after `wait_seconds`.
    Raises LockUnavailable (incl. LockPathRejected) when the lock location fails enforcement or the file
    cannot be opened (fail closed: the caller must not proceed). `root` is the containment root (the
    runtime dir); it defaults to the lock file's own directory. After acquire, `contended` says whether the
    first attempt found the lock held by another process (i.e. this process waited for someone)."""

    def __init__(self, path, label: str = "", root=None):
        self.path = Path(path)
        self.root = Path(root) if root is not None else self.path.parent
        self.label = label
        self.fd: int | None = None
        self.waited_seconds = 0.0
        self.contended = False

    def acquire(self, wait_seconds: float = 0.0, poll_seconds: float = 0.2) -> bool:
        fd = open_validated_lock_file(self.path, self.root)
        start = time.monotonic()
        deadline = start + max(0.0, float(wait_seconds or 0.0))
        first = True
        while True:
            if _try_lock(fd):
                self.fd = fd
                self.waited_seconds = round(time.monotonic() - start, 3)
                self._write_holder()
                return True
            if first:
                self.contended = True
                first = False
            if time.monotonic() >= deadline:
                self.waited_seconds = round(time.monotonic() - start, 3)
                os.close(fd)   # the loser holds nothing and wrote nothing
                return False
            time.sleep(max(0.01, float(poll_seconds)))

    def _write_holder(self) -> None:
        # Informational only (never consulted to decide lock state). Byte 0 stays the locked region on
        # Windows; on Linux flock covers the whole file regardless of content.
        info = json.dumps({"pid": os.getpid(), "label": self.label,
                           "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        try:
            os.lseek(self.fd, 0, os.SEEK_SET)
            if os.name != "nt":
                os.ftruncate(self.fd, 0)
            os.write(self.fd, (info + "\n").encode("utf-8"))
        except OSError:
            pass

    @property
    def held(self) -> bool:
        return self.fd is not None

    def release(self) -> None:
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        _unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False
