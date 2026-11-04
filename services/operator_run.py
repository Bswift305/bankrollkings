"""
Bankroll Kings - daily-operator CURRENT-RUN identity (D11, 2026-11-04).
========================================================================

Why: run_daily.py wrote its log and Last_Operator_Summary.json only at the END of a run, and the run had
no persisted identity. Any Run Status generated mid-run (the nested call at the end of the Edge Engine
pipeline step) therefore picked "the newest operator log by mtime" and "whatever summary exists" --
i.e. the PREVIOUS run -- and reported its reasons (e.g. 11-02's football_props VALIDATION_FAILED) as the
current state. A killed run left the same stale state unlabelled.

The fix gives every operator run an immutable identity at START:

  * A current-run MARKER, ``data/tracking/Current_Operator_Run.json`` (gitignored; same governed tracking
    dir as Last_Operator_Summary.json / Run_Status.json / the _child_outcomes_* sidecars it pairs with),
    written atomically (temp file in the same dir + fsync + os.replace) so a reader never sees a torn file.
  * The run id is exported to every child as ``BK_OPERATOR_RUN_ID`` (children inherit os.environ; the id
    is generated ONCE by run_daily and never regenerated mid-run).
  * Child-outcome sidecars are stamped with the run id; only sidecars of the current run count.
  * The final summary carries run_id/started_at/finished_at and the marker is then closed atomically.

Marker schema (``bk.operator_run.v1``)::

    {"schema": "bk.operator_run.v1", "run_id": "20261103T130000Z-<16 hex>", "state": "RUNNING",
     "started_at": "2026-11-03T13:00:00Z", "deadline_at": "...Z", "max_runtime_seconds": N,
     "finished_at": null, "pid": 1234, "host": "<hostname>", "log": "daily_operator_<stamp>.log",
     "sports": [...], "summary_written": null}

State machine (marker ``state``)::

    (none) --begin_run--> RUNNING --close_run--> COMPLETE | FAILED
                             |
                             +-- (reader-derived) INCOMPLETE when the deadline passed, or the marker's
                                 process is gone on this host, with no matching final summary.

Time cap: ``max_runtime_seconds`` = the sum of the planned step timeouts + post-refresh health + Run
Status + 30 min slack (computed by run_daily per run and recorded in the marker). A marker without a
usable cap falls back to DEFAULT_MAX_RUNTIME_SECONDS (12h). The process-liveness check (same host only;
the repo is OneDrive-synced between machines, so a foreign host's pid is never probed) catches a killed
run immediately; the deadline is the backstop.

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
SCHEMA = "bk.operator_run.v1"
DEFAULT_MAX_RUNTIME_SECONDS = 12 * 3600
SLACK_SECONDS = 1800

RUNNING = "RUNNING"
COMPLETE = "COMPLETE"
FAILED = "FAILED"
INCOMPLETE = "INCOMPLETE"
TERMINAL = frozenset({COMPLETE, FAILED})

# UTC second stamp + 64 random bits (secrets). Only [0-9A-Za-z-] -> safe in logs/JSON/filenames.
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}$")
_LOG_TAG_RE = re.compile(r"^Operator run: (\S+)\s*$", re.MULTILINE)
LOG_TAG_PREFIX = "Operator run: "


# --------------------------------------------------------------------------------------------- time
def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(max_bytes)
    except OSError:
        return None
    m = _LOG_TAG_RE.search(head)
    return m.group(1) if m and valid_run_id(m.group(1)) else None


# ----------------------------------------------------------------------------------------- paths/io
def tracking_dir(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking"


def marker_path(base_dir) -> Path:
    """The marker path, contained in <base>/data/tracking (refuses anything that resolves outside)."""
    tdir = tracking_dir(base_dir).resolve()
    path = (tdir / MARKER_FILENAME).resolve()
    if path.parent != tdir:
        raise ValueError(f"operator-run marker path escapes tracking dir: {path}")
    return path


def atomic_write_json(path: Path, obj) -> None:
    """temp file in the SAME directory + fsync + os.replace: a reader sees the old file or the new one,
    never a partial one; a failed write leaves the prior file intact. Retries a Windows sharing
    violation (a concurrent reader holding the file open) briefly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
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
    """('absent'|'ok'|'corrupt', payload). Retries a transient Windows sharing violation."""
    for attempt in range(20):
        try:
            text = Path(path).read_text(encoding="utf-8")
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


def read_marker(base_dir) -> tuple[str, dict | None]:
    status, payload = read_json_status(marker_path(base_dir))
    if status == "ok" and not (valid_run_id(payload.get("run_id"))
                               and payload.get("state") in (RUNNING, COMPLETE, FAILED)
                               and parse_utc(payload.get("started_at"))):
        return "corrupt", None
    return status, payload


# --------------------------------------------------------------------------------------- lifecycle
def begin_run(base_dir, *, log_name: str, sports, max_runtime_seconds: int | None = None,
              now: datetime | None = None, environ=None) -> dict:
    """Create the RUNNING marker atomically and export the run id to the environment children inherit.
    Always a NEW run (run_daily is the run start). Returns the marker dict."""
    environ = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
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
        "host": socket.gethostname(),
        "log": str(log_name),
        "sports": sorted(sports or []),
        "summary_written": None,
    }
    environ[RUN_ID_ENV] = marker["run_id"]
    atomic_write_json(marker_path(base_dir), marker)
    return marker


def close_run(base_dir, marker: dict, state: str, *, summary_written: bool,
              finished_at: datetime | None = None) -> bool:
    """Atomically flip the marker to COMPLETE/FAILED. Never clobbers a marker that now belongs to a
    different run (returns False)."""
    if state not in TERMINAL:
        raise ValueError(f"close_run state must be COMPLETE/FAILED, got {state!r}")
    status, current = read_marker(base_dir)
    if status == "ok" and current.get("run_id") != marker.get("run_id"):
        return False
    closed = dict(marker)
    closed["state"] = state
    closed["finished_at"] = utc_iso(finished_at or datetime.now(timezone.utc))
    closed["summary_written"] = bool(summary_written)
    atomic_write_json(marker_path(base_dir), closed)
    return True


def pid_alive(pid) -> bool | None:
    """True/False when determinable on this host, None when unknown. Never signals the process (on
    Windows os.kill(pid, 0) would send CTRL_C_EVENT, so it is not used there)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False if ctypes.get_last_error() == 87 else None   # 87 = invalid parameter
            try:
                code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259                          # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def assess_running(marker: dict, now: datetime, *, host: str | None = None, alive_fn=pid_alive) -> tuple[str, str]:
    """For a RUNNING marker with no matching final summary: (RUNNING|INCOMPLETE, why)."""
    started = parse_utc(marker.get("started_at"))
    deadline = parse_utc(marker.get("deadline_at"))
    if deadline is None and started is not None:
        deadline = started + timedelta(seconds=DEFAULT_MAX_RUNTIME_SECONDS)
    if deadline is not None and now > deadline:
        return INCOMPLETE, f"still RUNNING past its deadline {utc_iso(deadline)}"
    host = socket.gethostname() if host is None else host
    if marker.get("host") and marker.get("host") == host:
        if alive_fn(marker.get("pid")) is False:
            return INCOMPLETE, f"operator process {marker.get('pid')} is gone"
    return RUNNING, "in progress"


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
