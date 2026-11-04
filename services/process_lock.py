"""
Kernel-backed, fd-based exclusive process lock (2026-11, NBA game-lines single publisher).

Contract (the Linux path is the production contract):
  * Linux/POSIX: fcntl.flock(fd, LOCK_EX | LOCK_NB) on an fd opened O_RDWR|O_CREAT. The kernel releases the
    lock when the last fd referring to the open file description closes -- including when the process
    exits or crashes (SIGKILL, earlyoom SIGTERM, OOM). There are NO stale-lockfile semantics: the file's
    existence or content never means "locked"; only the kernel lock does. The file is never unlinked
    (unlinking a flock'd path lets a second process lock a NEW inode and breaks mutual exclusion).
  * Windows (local dev / QC only): msvcrt.locking(fd, LK_NBLCK, 1) on byte 0 -- also released by the OS
    when the handle closes or the process exits, so QC can exercise two-process contention locally.

The holder's pid / label / acquisition time are written into the file purely as operator information.
Pure stdlib; no app import.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

if os.name == "nt":  # pragma: no cover - platform branch
    import msvcrt
else:
    import fcntl


class LockUnavailable(OSError):
    """The lock file could not be opened/created (e.g. missing or unwritable lock directory)."""


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
    Raises LockUnavailable when the lock file cannot be opened (fail closed: the caller must not proceed)."""

    def __init__(self, path, label: str = ""):
        self.path = Path(path)
        self.label = label
        self.fd: int | None = None
        self.waited_seconds = 0.0

    def acquire(self, wait_seconds: float = 0.0, poll_seconds: float = 0.2) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            raise LockUnavailable(f"cannot open lock file {self.path}: {exc}") from exc
        start = time.monotonic()
        deadline = start + max(0.0, float(wait_seconds or 0.0))
        while True:
            if _try_lock(fd):
                self.fd = fd
                self.waited_seconds = round(time.monotonic() - start, 3)
                self._write_holder()
                return True
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
