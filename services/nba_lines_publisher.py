"""
THE single NBA game-lines publisher (2026-11, Gap 3 of the NBA game-lines v3 correction).
=========================================================================================

Every NBA game-lines publish -- bk-daily's NBA refresh (refresh_nba_daily -> fetch_game_lines.py), the
4-hourly NBA lines job, and any manual `fetch_game_lines.py --sport basketball_nba` -- enters through
publish(). There is no other path: fetch_game_lines.run_fetch() refuses an event-aware (NBA) fetch unless
this module holds the lock.

Order of operations (each step fails closed):
  1. Acquire the shared kernel lock (services.process_lock: fcntl.flock on Linux) at lock_path() BEFORE
     any paid request. Contention (after an optional bounded wait) -> SKIPPED_LOCKED: no paid request, no
     receipt, no file write, exit EXIT_LOCKED (75), and the output never says OK/PASS. A lock file that
     cannot be opened -> LOCK_UNAVAILABLE, exit EXIT_LOCK_UNAVAILABLE (76), likewise no request/no write.
  2. (callers that opt in, i.e. bk-daily) Reuse: if the other job published a receipt-verified NBA lines
     file within REUSE_WINDOW_MINUTES, record REUSED_FRESH and stop -- no paid request.
  3. Otherwise run the ONE shared fetch + event validation + atomic 3-file publish
     (fetch_game_lines.run_fetch, contract game_lines_event_v1).
  4. Write the publisher receipt (data/tracking/_last_nba_lines_publish.json) -- only ever by the lock
     holder -- and release the lock (also released by the kernel on exit/crash).

Lock path (one explicit path, OUTSIDE the checkout on prod):
  $BK_NBA_LINES_LOCK_PATH                         explicit override (QC only)
  $BK_RUNTIME_DIR/locks/nba_game_lines.lock       when BK_RUNTIME_DIR is set (repo convention, bk_runtime)
  /opt/bankrollkings-runtime/locks/nba_game_lines.lock   POSIX default (prod)
  <repo>/.runtime/generated/locks/nba_game_lines.lock    Windows dev only (gitignored)

Reuse window: REUSE_WINDOW_MINUTES = 90. It is deliberately far inside the 6h executable-price rule
(LIVE_LINES_MAX_AGE_HOURS, CLOCK A), so a reused file is at most 1.5h past its publish when bk-daily's
props step runs, leaving >= 4.5h of customer-executable life; and it is wide enough that the 4-hourly job's
12:45 UTC tick is reused by bk-daily's NBA step that follows the 13:00 UTC start. Reuse requires ALL of:
fetch receipt outcome UPDATED, exit_code 0, published True, contract game_lines_event_v1, receipt `at`
parseable, not in the future, and within the window, and every output's current sha256 equal to the
receipt's sha256_after (the file on disk is exactly what that verified publish wrote).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.process_lock import ExclusiveLock, LockUnavailable
from services.run_outcomes import (
    NO_ACTIVE_EVENTS, PROVIDER_ERROR, REUSED_FRESH, SCHEDULE_UNAVAILABLE, SKIPPED_LOCKED, UPDATED,
    VALIDATION_FAILED,
)

SPORT = "basketball_nba"
CONTRACT = "game_lines_event_v1"
REUSE_WINDOW_MINUTES = 90
LOCK_FILENAME = "nba_game_lines.lock"
POSIX_DEFAULT_RUNTIME_DIR = "/opt/bankrollkings-runtime"
LOCK_UNAVAILABLE = "LOCK_UNAVAILABLE"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOCKED = 75            # EX_TEMPFAIL
EXIT_LOCK_UNAVAILABLE = 76

_ACTIVE_LOCK: ExclusiveLock | None = None


def lock_path() -> Path:
    env = (os.environ.get("BK_NBA_LINES_LOCK_PATH") or "").strip()
    if env:
        return Path(env)
    runtime = (os.environ.get("BK_RUNTIME_DIR") or "").strip()
    if runtime:
        return Path(runtime) / "locks" / LOCK_FILENAME
    if os.name != "nt":
        return Path(POSIX_DEFAULT_RUNTIME_DIR) / "locks" / LOCK_FILENAME
    import bk_runtime   # Windows dev: the gitignored in-repo runtime dir
    return bk_runtime.runtime_dir() / "locks" / LOCK_FILENAME


def lock_is_held() -> bool:
    """True only inside publish() while THIS process holds the shared lock."""
    return _ACTIVE_LOCK is not None and _ACTIVE_LOCK.held


def fetch_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / f"_last_game_lines_fetch_{SPORT}.json"


def publish_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_lines_publish.json"


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha256(path: Path):
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _parse_utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None   # naive -> unknown zone -> not trusted


def reuse_check(base_dir, outputs: dict, now: datetime | None = None,
                window_minutes: int = REUSE_WINDOW_MINUTES) -> tuple[bool, str]:
    """(reusable, detail). `outputs` maps receipt output keys (odds/schedules/schedule_alias) -> Path."""
    now = now or datetime.now(timezone.utc)
    receipt = _read_json(fetch_receipt_path(base_dir))
    if not receipt:
        return False, "no NBA lines receipt"
    if receipt.get("outcome") != UPDATED or receipt.get("exit_code") != 0 or receipt.get("published") is not True:
        return False, f"last NBA lines receipt is not a publish (outcome={receipt.get('outcome')})"
    if receipt.get("contract") != CONTRACT:
        return False, f"last publish not on {CONTRACT} (contract={receipt.get('contract')})"
    at = _parse_utc(receipt.get("fetch_end") or receipt.get("at"))
    if at is None:
        return False, "receipt publish time missing / not timezone-aware"
    age = now - at
    if age < timedelta(0):
        return False, "receipt publish time is in the future"
    if age > timedelta(minutes=window_minutes):
        return False, f"last publish {age.total_seconds() / 60:.0f} min ago (> {window_minutes} min reuse window)"
    recorded = receipt.get("outputs") or {}
    for key, path in outputs.items():
        want = (recorded.get(key) or {}).get("sha256_after")
        have = _sha256(path)
        if not want or have != want:
            return False, f"{key} on disk does not match the verified publish (sha mismatch)"
    return True, (f"reusing the NBA lines published {age.total_seconds() / 60:.0f} min ago by run "
                  f"{str(receipt.get('run_id'))[:8]} (within the {window_minutes}-min window)")


def _write_publish_receipt(base_dir, payload: dict) -> None:
    # Only the lock holder calls this; atomic temp + replace.
    path = publish_receipt_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"[WARN] could not write the NBA lines publisher receipt: {exc}")


def _fetch_outcome(base_dir, run_id_before, rc: int) -> str:
    receipt = _read_json(fetch_receipt_path(base_dir)) or {}
    if not receipt or receipt.get("run_id") == run_id_before:
        return UPDATED if rc == 0 else VALIDATION_FAILED   # no receipt from THIS run: no benign proof
    got = str(receipt.get("outcome") or "")
    if rc == 0:
        return UPDATED if got == UPDATED else VALIDATION_FAILED
    if got == NO_ACTIVE_EVENTS:
        return SCHEDULE_UNAVAILABLE
    return got if got in (PROVIDER_ERROR, VALIDATION_FAILED, SCHEDULE_UNAVAILABLE) else (got or VALIDATION_FAILED)


def publish(args, *, run_fetch, base_dir, outputs: dict, caller: str = "unspecified",
            allow_reuse: bool = False, lock_wait_seconds: float = 0.0) -> int:
    """Run one governed NBA lines publish. Returns the process exit code (see module docstring)."""
    global _ACTIVE_LOCK
    path = lock_path()
    lock = ExclusiveLock(path, label=f"nba_game_lines:{caller}")
    try:
        got = lock.acquire(wait_seconds=lock_wait_seconds)
    except LockUnavailable as exc:
        print(f"[{LOCK_UNAVAILABLE}] NBA game lines ({caller}): {exc}. No paid request made, nothing written.",
              flush=True)
        return EXIT_LOCK_UNAVAILABLE
    if not got:
        print(f"[{SKIPPED_LOCKED}] NBA game lines ({caller}): another process holds {path} "
              f"(waited {lock.waited_seconds:.1f}s). No paid request made, nothing written.", flush=True)
        return EXIT_LOCKED
    _ACTIVE_LOCK = lock
    started = datetime.now(timezone.utc)
    try:
        if allow_reuse:
            ok, detail = reuse_check(base_dir, outputs, now=started)
            if ok:
                _write_publish_receipt(base_dir, {
                    "caller": caller, "outcome": REUSED_FRESH, "exit_code": EXIT_OK, "detail": detail,
                    "lock_path": str(path), "lock_waited_seconds": lock.waited_seconds, "paid_requests": 0,
                    "reuse_window_minutes": REUSE_WINDOW_MINUTES, "at": started.isoformat(timespec="seconds"),
                })
                print(f"[{REUSED_FRESH}] NBA game lines ({caller}): {detail}. No paid request made.", flush=True)
                return EXIT_OK
            print(f"[INFO] NBA game lines ({caller}): not reusing -- {detail}.", flush=True)
        before = (_read_json(fetch_receipt_path(base_dir)) or {}).get("run_id")
        try:
            rc = int(run_fetch(args))
        except Exception as exc:   # a crash is a failure, never a pass
            print(f"[{PROVIDER_ERROR}] NBA game lines ({caller}) crashed: {exc!r}", flush=True)
            rc = EXIT_FAILED
        outcome = _fetch_outcome(base_dir, before, rc)
        if outcome != UPDATED and rc == 0:
            rc = EXIT_FAILED
        fetch_receipt = _read_json(fetch_receipt_path(base_dir)) or {}
        _write_publish_receipt(base_dir, {
            "caller": caller, "outcome": outcome, "exit_code": rc, "lock_path": str(path),
            "lock_waited_seconds": lock.waited_seconds, "fetch_run_id": fetch_receipt.get("run_id"),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        print(f"[{outcome}] NBA game lines ({caller}) exit={rc}", flush=True)
        return rc
    finally:
        _ACTIVE_LOCK = None
        lock.release()
