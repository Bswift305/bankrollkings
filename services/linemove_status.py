"""
Bankroll Kings - governed, durable line-movement runner status (bk-linemove -> Run Status).

Why (owner review of d2187e5, 2026-11-07): the runner's summary was a best-effort file in the checkout's
data/tracking/ -- not in the governed runtime, not fsync'd, not mode/symlink/hard-link checked, and a failed
write still let a fully successful runner exit 0 while Run Status kept reading an older healthy summary for up
to 8h. This module closes that production-write boundary:

  * LOCATION   <runtime root>/status/line_movement/ (runtime root = services.nba_lines_publisher.runtime_root():
               $BK_RUNTIME_DIR, else the POSIX prod default; QCs are refused unless isolated). The directory is
               created/verified by services.process_lock._validated_lock_dir: contained, never a symlink, 0700 on
               POSIX, a loose mode repaired only when we own it, otherwise refused.
  * FILES      invocation.json  -- written FIRST by every runner invocation (state RUNNING), and
               summary.json     -- written LAST, carrying the same invocation_id.
               Both 0600 on POSIX, created O_CREAT|O_EXCL|O_NOFOLLOW under a unique same-directory temp name,
               flushed + fsync'd, atomically replaced, then the parent directory is fsync'd (POSIX). An existing
               target that is a symlink, not a regular file, hard-linked (st_nlink != 1), owned by another uid or
               looser than 0600 is REFUSED (never overwritten through). The published file is re-read and
               verified (regular, nlink 1, owner, mode, JSON, invocation_id) before success is reported.
  * MANDATORY  any failure raises StatusPublicationError; the runner turns it into exit 2 even when every child
               succeeded (no internal failure is hidden).
  * BINDING    Run Status reads invocation.json FIRST: the summary only describes the current run when its
               invocation_id equals the latest invocation's. A newer invocation without its summary is DEGRADED
               once past RUNNING_GRACE_SECONDS (an older healthy summary is never reported as current), and a
               PUBLICATION_FAILED marker is DEGRADED immediately.

Pure stdlib; no pandas, no app import.
"""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUS_SUBDIR = Path("status") / "line_movement"
INVOCATION_FILE = "invocation.json"
SUMMARY_FILE = "summary.json"
FILE_MODE = 0o600
INVOCATION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RUNNING_GRACE_SECONDS = 20 * 60          # 2 steps x 240s child timeout + generous slack
MAX_AGE_HOURS = 8                        # the timer runs every 4h; two missed runs is a missed refresh
STATE_RUNNING = "RUNNING"
STATE_PUBLICATION_FAILED = "PUBLICATION_FAILED"
POSIX = os.name != "nt"


class StatusPublicationError(OSError):
    """The status could not be published durably and safely (location, permission, write, replace, fsync or
    read-back verification). Callers MUST treat this as a hard failure."""


def new_invocation_id() -> str:
    return uuid.uuid4().hex


def is_valid_invocation_id(value) -> bool:
    return isinstance(value, str) and bool(INVOCATION_ID_RE.match(value))


def status_dir_spec() -> tuple[Path, Path]:
    """(canonical status dir, containment root). Raises (LockPathRejected) for a QC that is not isolated."""
    from services.nba_lines_publisher import runtime_root
    root = runtime_root()
    return root / STATUS_SUBDIR, root


def _validated_dir() -> Path:
    from services.process_lock import LockUnavailable, _validated_lock_dir
    d, root = status_dir_spec()
    try:
        return Path(_validated_lock_dir(Path(d), Path(root)))
    except LockUnavailable as exc:   # LockPathRejected is a subclass
        raise StatusPublicationError(f"line-movement status directory refused: {exc}") from exc


def _check_existing_target(path: Path) -> None:
    """Refuse to replace a target that is a symlink / not a regular file / hard-linked / foreign / loose."""
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise StatusPublicationError(f"{path.name} is a symlink (refused)")
    if not stat.S_ISREG(st.st_mode):
        raise StatusPublicationError(f"{path.name} is not a regular file (refused)")
    if POSIX:
        if st.st_nlink != 1:
            raise StatusPublicationError(f"{path.name} has {st.st_nlink} hard links (refused: alias)")
        if st.st_uid != os.geteuid():
            raise StatusPublicationError(f"{path.name} is owned by uid {st.st_uid}, not euid {os.geteuid()} (refused)")
        if st.st_mode & 0o077:
            raise StatusPublicationError(f"{path.name} mode {oct(stat.S_IMODE(st.st_mode))} is looser than 0600 (refused)")


def _verify_fd(fd: int, what: str) -> None:
    fst = os.fstat(fd)
    if not stat.S_ISREG(fst.st_mode):
        raise StatusPublicationError(f"{what} is not a regular file")
    if POSIX:
        if fst.st_nlink != 1:
            raise StatusPublicationError(f"{what} has {fst.st_nlink} hard links (refused)")
        if fst.st_uid != os.geteuid():
            raise StatusPublicationError(f"{what} is owned by uid {fst.st_uid}, not euid {os.geteuid()}")
        if fst.st_mode & 0o077:
            raise StatusPublicationError(f"{what} mode {oct(stat.S_IMODE(fst.st_mode))} is looser than 0600")


def _fsync_dir(d: Path) -> None:
    if not POSIX:
        return
    fd = os.open(str(d), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_verified(path: Path) -> dict:
    """Open without following a symlink, verify the inode, parse JSON. Raises StatusPublicationError."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise StatusPublicationError(f"cannot open {path.name}: {exc}") from exc
    try:
        _verify_fd(fd, path.name)
        if POSIX:
            lst, fst = os.lstat(str(path)), os.fstat(fd)
            if (lst.st_dev, lst.st_ino) != (fst.st_dev, fst.st_ino):
                raise StatusPublicationError(f"{path.name} changed between check and open")
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as fh:
            data = json.loads(fh.read())
    except (OSError, ValueError) as exc:
        if isinstance(exc, StatusPublicationError):
            raise
        raise StatusPublicationError(f"{path.name} unreadable: {type(exc).__name__}: {exc}") from exc
    finally:
        os.close(fd)
    if not isinstance(data, dict):
        raise StatusPublicationError(f"{path.name} is not a JSON object")
    return data


def publish(name: str, payload: dict) -> Path:
    """Durably and safely publish one status file; verify it; return its path. Raises StatusPublicationError."""
    from services.receipt_io import replace_with_retry
    if name not in (INVOCATION_FILE, SUMMARY_FILE):
        raise StatusPublicationError(f"unknown status file {name!r}")
    if not is_valid_invocation_id(payload.get("invocation_id")):
        raise StatusPublicationError(f"refusing to publish {name}: invalid invocation_id {payload.get('invocation_id')!r}")
    d = _validated_dir()
    final = d / name
    _check_existing_target(final)
    tmp = d / f".{name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    data = json.dumps(payload, indent=2, default=str)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(tmp), flags, FILE_MODE)
    except OSError as exc:
        raise StatusPublicationError(f"cannot create temp for {name}: {exc}") from exc
    try:
        try:
            if POSIX:
                os.fchmod(fd, FILE_MODE)
            _verify_fd(fd, f"temp for {name}")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fd = -1
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if fd != -1:
                os.close(fd)
        _check_existing_target(final)            # re-check right before the replace
        replace_with_retry(tmp, final)
        _fsync_dir(d)
    except BaseException as exc:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        if isinstance(exc, StatusPublicationError):
            raise
        if isinstance(exc, OSError):
            raise StatusPublicationError(f"publishing {name} failed: {type(exc).__name__}: {exc}") from exc
        raise
    back = _read_verified(final)
    if back.get("invocation_id") != payload["invocation_id"]:
        raise StatusPublicationError(f"{name} read back with invocation_id {back.get('invocation_id')!r}, "
                                     f"not {payload['invocation_id']!r}")
    return final


def _now() -> datetime:
    return datetime.now(timezone.utc)


def begin(invocation_id: str, started_at: datetime | None = None) -> None:
    """Publish this invocation's marker (FIRST, before any child runs). Raises StatusPublicationError."""
    publish(INVOCATION_FILE, {"invocation_id": invocation_id, "state": STATE_RUNNING, "pid": os.getpid(),
                              "started_at": (started_at or _now()).isoformat(timespec="seconds")})


def mark_publication_failed(invocation_id: str, error: str) -> bool:
    """Best effort: record that this invocation could not publish its summary (Run Status -> DEGRADED now).
    Returns False if even this could not be written (the marker then still names this invocation, and Run
    Status degrades it once RUNNING_GRACE_SECONDS pass)."""
    try:
        publish(INVOCATION_FILE, {"invocation_id": invocation_id, "state": STATE_PUBLICATION_FAILED,
                                  "error": str(error)[:300], "failed_at": _now().isoformat(timespec="seconds")})
        return True
    except BaseException:   # noqa: BLE001 -- best effort only; the runner exits 2 regardless
        return False


def _parse(ts):
    try:
        dt = datetime.fromisoformat(str(ts))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def read_signals(now: datetime | None = None) -> tuple[list[str], dict]:
    """(DEGRADED reasons, info) bound to the LATEST invocation. Never raises."""
    now = now or _now()
    try:
        d, _root = status_dir_spec()
    except Exception as exc:   # noqa: BLE001 -- a refused location is itself a degraded signal
        return [f"line-movement status location refused: {type(exc).__name__}"], {"reported": None}
    inv_path, sum_path = Path(d) / INVOCATION_FILE, Path(d) / SUMMARY_FILE
    if not os.path.lexists(str(inv_path)) and not os.path.lexists(str(sum_path)):
        return [], {"reported": False}
    if not os.path.lexists(str(inv_path)):
        return ["line-movement summary exists without an invocation marker (cannot bind it to a run)"], {"reported": True}
    try:
        inv = _read_verified(inv_path)
    except StatusPublicationError as exc:
        return [f"line-movement invocation marker unreadable/unsafe: {exc}"], {"reported": True}
    inv_id = inv.get("invocation_id")
    info = {"reported": True, "invocation_id": inv_id, "state": inv.get("state")}
    if not is_valid_invocation_id(inv_id):
        return [f"line-movement invocation marker has an invalid invocation_id {inv_id!r}"], info
    if inv.get("state") == STATE_PUBLICATION_FAILED:
        return [f"line-movement invocation {inv_id[:8]} failed to publish its summary: {inv.get('error', '')}"], info
    summary = None
    if os.path.lexists(str(sum_path)):
        try:
            summary = _read_verified(sum_path)
        except StatusPublicationError as exc:
            return [f"line-movement summary unreadable/unsafe: {exc}"], info
    if summary is None or summary.get("invocation_id") != inv_id:
        started = _parse(inv.get("started_at"))
        age_s = (now - started).total_seconds() if started else None
        info["summary_invocation_id"] = (summary or {}).get("invocation_id")
        if age_s is not None and 0 <= age_s <= RUNNING_GRACE_SECONDS:
            info["in_progress"] = True       # the latest run is still inside its window; no older summary used
            return [], info
        return [f"line-movement invocation {inv_id[:8]} has no published summary (latest run's result unknown; "
                f"an older summary is never reported as current)"], info
    reasons = []
    steps = summary.get("steps")
    if not isinstance(steps, list) or not steps:
        reasons.append("line-movement summary has no step results")
        steps = []
    bad = [f"{r.get('label')}={r.get('status')}" for r in steps
           if not (isinstance(r, dict) and (r.get("status") == "OK" or str(r.get("status") or "").startswith("SKIPPED_")))]
    if bad:
        reasons.append("line-movement step(s) failed: " + ", ".join(bad))
    ec = summary.get("exit_code")
    if not (type(ec) is int and ec == 0) and not bad:
        reasons.append(f"line-movement runner exit {ec!r} with no step detail")
    finished = _parse(summary.get("finished_at"))
    info.update({"finished_at": summary.get("finished_at"), "exit_code": ec, "failed_steps": bad})
    if finished is None:
        reasons.append("line-movement summary has no valid finished_at")
    else:
        age_h = (now - finished).total_seconds() / 3600.0
        info["age_hours"] = round(age_h, 2)
        if age_h > MAX_AGE_HOURS:
            reasons.append(f"line-movement job has not reported in {age_h:.1f}h (> {MAX_AGE_HOURS}h)")
    return reasons, info
