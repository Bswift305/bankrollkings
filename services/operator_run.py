"""
Bankroll Kings - daily-operator CURRENT-RUN identity (D11, 2026-11-04).
========================================================================

Why: run_daily.py wrote its log and Last_Operator_Summary.json only at the END of a run, and the run had
no persisted identity. Any Run Status generated mid-run (the nested call at the end of the Edge Engine
pipeline step) therefore picked "the newest operator log by mtime" and "whatever summary exists" --
i.e. the PREVIOUS run -- and reported its reasons (e.g. 11-02's football_props VALIDATION_FAILED) as the
current state. A killed run left the same stale state unlabelled.

Design (successor hardening, 2026-11-04)
---------------------------------------
* LEASE (mutual exclusion + liveness): ``data/tracking/.operator_run.lock`` -- a permanent, never-deleted
  0600 file on which the running operator holds an EXCLUSIVE, NON-BLOCKING OS lock (POSIX ``flock``;
  Windows ``msvcrt.locking``) for its whole lifetime. The OS drops the lock when the process dies (kill -9,
  earlyoom, unit timeout), so "lease free" == "no live operator on this host". EVERY mutation of the marker
  files happens while holding the lease, so each read-check-write below is a real compare-and-swap.
  A second operator that cannot take the lease REFUSES to start (run_daily exits 75) and writes nothing.
* PER-RUN MARKER: ``data/tracking/operator_runs/<run_id>.json`` -- that run's own state record.
* CURRENT POINTER: ``data/tracking/Current_Operator_Run.json`` -- a copy of the current run's marker; what
  Run Status reads. Written only by the lease holder, after the per-run marker.
* Both written atomically (same-dir temp + fsync + os.replace), mode 0600 on POSIX, never through a
  symlink (a symlinked target/run dir is refused, a symlinked file is read as corrupt), contained in
  data/tracking.
* The run id is exported to every child as ``BK_OPERATOR_RUN_ID`` (inherited env); generated ONCE.

Marker schema ``bk.operator_run.v1``::

    {"schema", "run_id": "20261103T130000Z-<16 hex>", "state": RUNNING|COMPLETE|FAILED|INCOMPLETE,
     "started_at": "...Z", "deadline_at": "...Z", "max_runtime_seconds": N, "finished_at": "...Z"|null,
     "pid", "host", "log", "sports", "summary_written": bool|null,
     "incomplete_reason"/"detected_at"/"detected_by" (INCOMPLETE only)}

Lifecycle::

                 acquire lease (non-blocking; run_daily retries briefly)
                   |-- lease held by a live run ------------------> REFUSE (exit 75; nothing written)
                   v
     pointer RUNNING of another run?  (we hold the lease => its owner is dead on this host)
                   |-- same host, or past its deadline ----------> that run: RUNNING -> INCOMPLETE (persisted, CAS)
                   |-- foreign host, within its deadline --------> REFUSE (cannot prove it is dead)
                   v
     begin_run: per-run marker + pointer = RUNNING (this run) ; prune retention ; export run id
                   v
     ... steps (children inherit BK_OPERATOR_RUN_ID) ...
                   v
     summary (run_id/started_at/finished_at) -> close_run: RUNNING -> COMPLETE | FAILED
         CAS: lease bound to this run id, per-run marker must be RUNNING with this id; the pointer is
         updated only if it still names this run (a newer run is never touched)
                   v
     release lease

     Killed run (no close): the next run start, or ANY Run Status that can take the lease (owner gone),
     converts RUNNING -> INCOMPLETE atomically (CAS on run id + state RUNNING, under the lease). A run past
     its deadline whose owner still holds the lease (hung) is REPORTED INCOMPLETE (overdue) but not
     persisted; it can still close normally.

Time cap: ``max_runtime_seconds`` = sum of the planned step timeouts + post-refresh health + Run Status +
30 min slack (computed per run by run_daily); DEFAULT_MAX_RUNTIME_SECONDS (12h) when absent.

Retention: per-run markers are pruned at run start (under the lease) to at most RETENTION_MAX_FILES files
and RETENTION_MAX_AGE_DAYS days (age from the run id's own UTC stamp, not mtime). Only files named
``<valid run id>.json`` are ever deleted; the current run and the pointer's run are never deleted.

Identity is the run id -- never a log filename date, a file mtime, or the Eastern/UTC calendar day.
Pure stdlib; no app import.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_ID_ENV = "BK_OPERATOR_RUN_ID"
MARKER_FILENAME = "Current_Operator_Run.json"
LOCK_FILENAME = ".operator_run.lock"
RUNS_DIRNAME = "operator_runs"
SCHEMA = "bk.operator_run.v1"
DEFAULT_MAX_RUNTIME_SECONDS = 12 * 3600
SLACK_SECONDS = 1800
RETENTION_MAX_FILES = 90
RETENTION_MAX_AGE_DAYS = 45
REFUSED_EXIT_CODE = 75          # EX_TEMPFAIL: another operator run holds the lease

RUNNING = "RUNNING"
COMPLETE = "COMPLETE"
FAILED = "FAILED"
INCOMPLETE = "INCOMPLETE"
TERMINAL = frozenset({COMPLETE, FAILED})
STATES = frozenset({RUNNING, COMPLETE, FAILED, INCOMPLETE})

# UTC second stamp + 64 random bits (secrets). Only [0-9A-Za-z-] -> safe in logs/JSON/filenames.
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}$")
_LOG_TAG_RE = re.compile(r"^Operator run: (\S+)\s*$", re.MULTILINE)
LOG_TAG_PREFIX = "Operator run: "


class OperatorRunConflict(RuntimeError):
    """Another operator run is (or may be) active; this run must not start."""


# --------------------------------------------------------------------------------------------- time
def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    return utc_iso(datetime.now(timezone.utc))


def parse_utc(value) -> datetime | None:
    """Parse an ISO timestamp that carries a zone (Z or offset). Naive / malformed -> None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------------------------------------ run ids
def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8)


def valid_run_id(value) -> bool:
    return isinstance(value, str) and bool(RUN_ID_RE.match(value))


def run_id_time(run_id: str) -> datetime | None:
    if not valid_run_id(run_id):
        return None
    return datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def env_run_id(environ=None) -> str | None:
    """The current operator run id inherited from run_daily, or None (absent/malformed)."""
    value = (environ if environ is not None else os.environ).get(RUN_ID_ENV, "")
    value = (value or "").strip()
    return value if valid_run_id(value) else None


def log_tag_line(run_id: str | None) -> list[str]:
    """Header line(s) a log writer adds so its log is attributable to an operator run by ID."""
    return [f"{LOG_TAG_PREFIX}{run_id}"] if valid_run_id(run_id) else []


def read_log_tag(path: Path, max_bytes: int = 4096) -> str | None:
    try:
        if Path(path).is_symlink():
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(max_bytes)
    except OSError:
        return None
    m = _LOG_TAG_RE.search(head)
    return m.group(1) if m and valid_run_id(m.group(1)) else None


# ----------------------------------------------------------------------------------------- paths/io
def tracking_dir(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking"


def _contained(path: Path, parent: Path) -> Path:
    """`path` must be a direct child of `parent`. The final component is NOT resolved (a symlink there is
    detected and refused by the reader/writer, never followed); a name with separators/'..' is refused."""
    pp = parent.resolve()
    name = path.name
    if path.parent.resolve() != pp or name in ("", ".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"operator-run path escapes {pp}: {path}")
    return pp / name


def marker_path(base_dir) -> Path:
    """The current-run POINTER path, contained in <base>/data/tracking."""
    tdir = tracking_dir(base_dir)
    return _contained(tdir / MARKER_FILENAME, tdir)


def lock_path(base_dir) -> Path:
    tdir = tracking_dir(base_dir)
    return _contained(tdir / LOCK_FILENAME, tdir)


def runs_dir(base_dir) -> Path:
    d = tracking_dir(base_dir) / RUNS_DIRNAME
    if d.is_symlink():
        raise ValueError(f"operator-run dir must not be a symlink: {d}")
    return d


def run_marker_path(base_dir, run_id: str) -> Path:
    if not valid_run_id(run_id):
        raise ValueError(f"invalid run id {run_id!r}")
    d = runs_dir(base_dir)
    return _contained(d / f"{run_id}.json", d)


def atomic_write_json(path: Path, obj, mode: int = 0o600) -> None:
    """temp file in the SAME directory + fsync + os.replace: a reader sees the old file or the new one,
    never a partial one; a failed write leaves the prior file intact. Never writes through a symlink.
    Mode 0600 by default (POSIX). Retries a Windows sharing violation (concurrent reader) briefly."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"refusing to write through a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.01)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def read_json_status(path: Path) -> tuple[str, dict | None]:
    """('absent'|'ok'|'corrupt', payload). A symlink is never followed (-> corrupt). Retries a transient
    Windows sharing violation."""
    path = Path(path)
    for _ in range(20):
        try:
            if path.is_symlink():
                return "corrupt", None
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "absent", None
        except PermissionError:
            time.sleep(0.01)
            continue
        except OSError:
            return "corrupt", None
        try:
            payload = json.loads(text)
        except ValueError:
            return "corrupt", None
        return ("ok", payload) if isinstance(payload, dict) else ("corrupt", None)
    return "corrupt", None


def _valid_marker(payload) -> bool:
    return (isinstance(payload, dict) and valid_run_id(payload.get("run_id"))
            and payload.get("state") in STATES and parse_utc(payload.get("started_at")) is not None)


def read_marker(base_dir) -> tuple[str, dict | None]:
    """The current-run POINTER: ('absent'|'ok'|'corrupt', marker)."""
    status, payload = read_json_status(marker_path(base_dir))
    if status == "ok" and not _valid_marker(payload):
        return "corrupt", None
    return status, payload


def read_run_marker(base_dir, run_id) -> tuple[str, dict | None]:
    try:
        status, payload = read_json_status(run_marker_path(base_dir, run_id))
    except ValueError:
        return "corrupt", None
    if status == "ok" and not (_valid_marker(payload) and payload.get("run_id") == run_id):
        return "corrupt", None
    return status, payload


# -------------------------------------------------------------------------------------------- lease
class OperatorLease:
    """An exclusive OS lock on data/tracking/.operator_run.lock. Released by release() or process death."""

    def __init__(self, fd: int, path: Path):
        self.fd = fd
        self.path = path
        self.run_id: str | None = None     # bound by begin_run; close_run only closes this run

    @property
    def held(self) -> bool:
        return self.fd is not None

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            _unlock(self.fd)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def _try_lock(fd: int) -> bool:
    if sys.platform.startswith("win"):
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (BlockingIOError, PermissionError):
        return False


def _unlock(fd: int) -> None:
    if sys.platform.startswith("win"):
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def acquire_lease(base_dir, wait_seconds: float = 0.0) -> OperatorLease | None:
    """Take the operator lease without blocking (retrying up to `wait_seconds`). None when another live
    process holds it. Raises OSError/ValueError when the lock file cannot be opened safely (symlink,
    containment, permissions) -- callers fail CLOSED."""
    path = lock_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"operator lock must not be a symlink: {path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    for attempt in range(50):          # a transient Windows sharing violation (e.g. AV scan) on open
        try:
            fd = os.open(str(path), flags, 0o600)
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    while True:
        if _try_lock(fd):
            return OperatorLease(fd, path)
        if time.monotonic() >= deadline:
            os.close(fd)
            return None
        time.sleep(0.05)


def _require(lease: OperatorLease | None) -> None:
    if lease is None or not lease.held:
        raise OperatorRunConflict("operator lease not held")


def _write_marker(base_dir, marker: dict, *, pointer: bool) -> None:
    atomic_write_json(run_marker_path(base_dir, marker["run_id"]), marker)
    if pointer:
        atomic_write_json(marker_path(base_dir), marker)


# --------------------------------------------------------------------------------------- lifecycle
def convert_incomplete(base_dir, lease: OperatorLease, run_id: str, reason: str, *,
                       detected_by: str, now: datetime | None = None) -> bool:
    """Atomically persist RUNNING -> INCOMPLETE for `run_id` (CAS: the record must still be RUNNING with
    this id). Requires the lease. The pointer is updated only if it still names `run_id`."""
    _require(lease)
    now = now or datetime.now(timezone.utc)
    p_status, pointer = read_marker(base_dir)
    r_status, record = read_run_marker(base_dir, run_id)
    base = record if (r_status == "ok") else (pointer if (p_status == "ok" and pointer.get("run_id") == run_id) else None)
    if base is None or base.get("state") != RUNNING:
        return False
    converted = dict(base)
    converted.update({"state": INCOMPLETE, "incomplete_reason": reason, "detected_at": utc_iso(now),
                      "detected_by": detected_by, "finished_at": None})
    on_pointer = p_status == "ok" and pointer.get("run_id") == run_id and pointer.get("state") == RUNNING
    _write_marker(base_dir, converted, pointer=on_pointer)
    return True


def _overdue(marker: dict, now: datetime) -> tuple[bool, datetime | None]:
    started = parse_utc(marker.get("started_at"))
    deadline = parse_utc(marker.get("deadline_at"))
    if deadline is None and started is not None:
        deadline = started + timedelta(seconds=DEFAULT_MAX_RUNTIME_SECONDS)
    return (deadline is not None and now > deadline), deadline


def prune_run_markers(base_dir, keep: set[str], now: datetime | None = None) -> list[str]:
    """Bounded retention for per-run markers (age + count cap). Never deletes `keep`, a symlink, or any
    file not named <valid run id>.json. Returns the deleted run ids."""
    now = now or datetime.now(timezone.utc)
    d = runs_dir(base_dir)
    if not d.is_dir():
        return []
    entries = []
    for p in d.iterdir():
        rid = p.name[:-5] if p.name.endswith(".json") else ""
        if not valid_run_id(rid) or p.is_symlink() or not p.is_file():
            continue
        entries.append((run_id_time(rid), rid, p))
    entries.sort(reverse=True)                   # newest first by the run id's own UTC stamp
    protected = {rid for _, rid, _ in entries if rid in keep}
    others = [e for e in entries if e[1] not in protected]
    budget = max(0, RETENTION_MAX_FILES - len(protected))
    cutoff = now - timedelta(days=RETENTION_MAX_AGE_DAYS)
    deleted = []
    for idx, (ts, rid, p) in enumerate(others):
        if ts < cutoff or idx >= budget:
            try:
                p.unlink()
                deleted.append(rid)
            except OSError:
                pass
    return deleted


def begin_run(base_dir, lease: OperatorLease, *, log_name: str, sports, max_runtime_seconds: int | None = None,
              now: datetime | None = None, environ=None, host: str | None = None) -> dict:
    """Start a NEW run while holding the lease: settle any previous RUNNING pointer (dead owner ->
    INCOMPLETE, persisted), write this run's per-run marker + pointer (RUNNING), prune retention, export
    the run id. Raises OperatorRunConflict when a foreign-host run may still be live."""
    _require(lease)
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    host = socket.gethostname() if host is None else host
    p_status, pointer = read_marker(base_dir)
    previous_id = pointer.get("run_id") if p_status == "ok" else None
    if p_status == "ok" and pointer.get("state") == RUNNING:
        overdue, _ = _overdue(pointer, now)
        if pointer.get("host") == host or overdue:
            why = ("operator process gone (lease free at next run start)" if pointer.get("host") == host
                   else "past its deadline (foreign host)")
            convert_incomplete(base_dir, lease, pointer["run_id"], why, detected_by="run_start", now=now)
        else:
            raise OperatorRunConflict(f"run {pointer['run_id']} on host {pointer.get('host')} may still be "
                                      f"active (started {pointer.get('started_at')})")
    cap = int(max_runtime_seconds) if max_runtime_seconds and int(max_runtime_seconds) > 0 \
        else DEFAULT_MAX_RUNTIME_SECONDS
    marker = {
        "schema": SCHEMA,
        "run_id": new_run_id(now),
        "state": RUNNING,
        "started_at": utc_iso(now),
        "max_runtime_seconds": cap,
        "deadline_at": utc_iso(now + timedelta(seconds=cap)),
        "finished_at": None,
        "pid": os.getpid(),
        "host": host,
        "log": str(log_name),
        "sports": sorted(sports or []),
        "summary_written": None,
    }
    _write_marker(base_dir, marker, pointer=True)
    lease.run_id = marker["run_id"]
    environ[RUN_ID_ENV] = marker["run_id"]
    try:
        prune_run_markers(base_dir, keep={marker["run_id"], previous_id} - {None}, now=now)
    except (OSError, ValueError):
        pass
    return marker


def close_run(base_dir, lease: OperatorLease, marker: dict, state: str, *, summary_written: bool,
              finished_at: datetime | None = None) -> bool:
    """Atomically flip THIS run RUNNING -> COMPLETE/FAILED. CAS: the lease must be bound to this run id
    and the per-run record must still be RUNNING with this id. The pointer is rewritten only while it
    still names this run, so a newer run is never closed. Returns False when the CAS fails."""
    if state not in TERMINAL:
        raise ValueError(f"close_run state must be COMPLETE/FAILED, got {state!r}")
    _require(lease)
    run_id = marker.get("run_id")
    if lease.run_id != run_id:
        return False
    r_status, record = read_run_marker(base_dir, run_id)
    if r_status != "ok" or record.get("state") != RUNNING:
        return False
    closed = dict(record)
    closed["state"] = state
    closed["finished_at"] = utc_iso(finished_at or datetime.now(timezone.utc))
    closed["summary_written"] = bool(summary_written)
    p_status, pointer = read_marker(base_dir)
    _write_marker(base_dir, closed, pointer=(p_status == "ok" and pointer.get("run_id") == run_id))
    return True


def settle_running(base_dir, marker: dict, now: datetime, *, host: str | None = None) -> tuple[str, str, bool]:
    """Run Status side, for a RUNNING pointer with no matching final summary. Returns
    (RUNNING|INCOMPLETE, why, persisted). If the lease can be taken the owner is gone (same host) -> the
    marker is converted to INCOMPLETE ATOMICALLY (CAS) and persisted. A foreign-host marker is converted
    only once past its deadline. A live owner past its deadline is reported INCOMPLETE (overdue), not
    persisted."""
    host = socket.gethostname() if host is None else host
    overdue, deadline = _overdue(marker, now)
    same_host = bool(marker.get("host")) and marker.get("host") == host
    try:
        lease = acquire_lease(base_dir, 0.0)
    except (OSError, ValueError):
        lease = None
    if lease is not None:
        with lease:
            if same_host or overdue:
                why = ("operator process gone (lease free)" if same_host
                       else f"still RUNNING past its deadline {utc_iso(deadline)}")
                persisted = convert_incomplete(base_dir, lease, marker["run_id"], why, detected_by="run_status", now=now)
                return INCOMPLETE, why, persisted
        return RUNNING, "in progress", False
    if overdue:
        return INCOMPLETE, f"still RUNNING past its deadline {utc_iso(deadline)} (owner holds the lease)", False
    return RUNNING, "in progress", False


def expire_pending_payload(payload: dict, now: datetime | None = None) -> dict:
    """Reader-side guard for a Run_Status.json that was written mid-run (PENDING) by a run that was then
    killed: once that run's recorded deadline passes, the persisted PENDING must read INCOMPLETE, never
    'in progress' forever. Returns a (shallow-copied) payload; unchanged when not applicable."""
    if not isinstance(payload, dict):
        return payload
    op = payload.get("operator")
    if not isinstance(op, dict) or op.get("state") != "PENDING":
        return payload
    cur = op.get("current_run") if isinstance(op.get("current_run"), dict) else {}
    deadline = parse_utc(cur.get("deadline_at"))
    now = now or datetime.now(timezone.utc)
    if deadline is None or now <= deadline:
        return payload
    out = dict(payload)
    op = dict(op)
    op["state"] = INCOMPLETE
    op["status_label"] = "INCOMPLETE"
    out["operator"] = op
    note = f"Incomplete: run {cur.get('run_id')} started {cur.get('started_at')} did not finish"
    rows = []
    for row in payload.get("rows") or []:
        if isinstance(row, dict) and row.get("Status") in ("IN_PROGRESS", "PENDING"):
            row = dict(row)
            row["Status"] = INCOMPLETE
            row["StatusNote"] = note
        rows.append(row)
    out["rows"] = rows
    reasons = list(payload.get("degraded_reasons") or [])
    reasons.append(f"operator run {cur.get('run_id')} (started {cur.get('started_at')}) did not finish "
                   "(INCOMPLETE: past its deadline)")
    out["degraded_reasons"] = reasons
    if out.get("overall") != "RED":
        out["overall"] = "DEGRADED"
    return out
