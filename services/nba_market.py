"""
Shared NBA market ENSURE API (v5 owner decisions 1-4): ensure_nba_lines() / ensure_nba_props().
=================================================================================================

ONE way to get a current NBA lines or props publish, used by BOTH callers:
  * bk-daily        refresh_nba_daily.py  game_lines / player_props steps   (caller "nba_daily")
  * the orchestrator refresh_nba_market.py (ops/bk-nba-market-refresh.*)     (caller "nba_market_4h")

Each ensure call runs ONE stage child -- the existing publisher entry (`fetch_game_lines.py` /
`fetch_player_props.py` -> services.nba_lines_publisher / nba_props_publisher.publish) -- with the SAME
canonical command (stage_command) and the SAME timeout (services/nba_market_budget.stage_timeout), then
classifies the result from the exit code AND the receipts that child wrote THIS run. Nothing here makes a
provider request itself; the publishers keep every lock/reuse/validation guarantee:

  lock before ANY request -> reuse decided UNDER the lock (receipt + sha256 re-verified) -> else fetch +
  validate + atomic publish -> receipts written only by the lock holder.

Canonical stage policy (both callers): `--allow-reuse --lock-wait-seconds <LOCK_WAIT> --no-fetch-after-lock`.
  * A receipt-verified publish inside REUSE_WINDOW_MINUTES (90) is reused: REUSED_FRESH (zero requests).
  * Lock held by the other caller -> bounded wait -> re-read under the lock:
      valid fresh publish  -> REUSED_FRESH_AFTER_LOCK (zero requests)
      none (holder failed) -> NO_FRESH_AFTER_LOCK, exit 1, zero requests  (never OK; no immediate re-spend)
      still held after wait -> SKIPPED_LOCKED, exit 75, zero requests
  So bk-daily and the orchestrator can overlap without a duplicate paid call or a duplicate write.

Props stage only after verified lines: ensure_nba_props() is called by the orchestrator only when the lines
stage outcome is in LINES_READY, and the props publisher independently re-verifies the lines receipt + sha of
NBA_Odds.csv under its own lock (SKIPPED_BLOCKED_BY_LINES otherwise), so a lines failure spends zero props
credits even if a caller forgot the check.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services import nba_market_budget as budget
from services.nba_lines_publisher import EXIT_LOCK_UNAVAILABLE, EXIT_LOCKED, LOCK_UNAVAILABLE
from services.run_outcomes import (
    LINES_READY, NO_ACTIVE_EVENTS, NO_FRESH_AFTER_LOCK, PROVIDER_ERROR, REUSED_FRESH, REUSED_FRESH_AFTER_LOCK,
    SCHEDULE_UNAVAILABLE, SKIPPED_BLOCKED_BY_LINES, SKIPPED_LOCKED, UPDATED, VALIDATION_FAILED, is_alerting,
    props_step_outcome,
)

SPORT = "basketball_nba"
BOOKMAKERS = "draftkings,caesars,fanduel,betmgm"
DAYS = "5"
STAGES = ("lines", "props")
STAGE_SCRIPTS = {"lines": "fetch_game_lines.py", "props": "fetch_player_props.py"}
ORCHESTRATOR_CALLER = "nba_market_4h"
RECEIPT_SCHEMA = "nba_market_refresh_v1"
RECEIPT_DIRNAME = "nba_market"
RECEIPT_FILENAME = "last_nba_market_refresh.json"
RUN_LOCK_FILENAME = "nba_market_refresh.lock"
RUN_LOCK_OVERRIDE_ENV = "BK_NBA_MARKET_LOCK_PATH"   # QC only; honoured only inside the runtime root / qc_* temp
LEDGER_REL = Path("data") / "tracking" / "odds_quota_ledger.jsonl"   # services/odds_quota.LEDGER_REL

# Receipt outcomes passed through verbatim for a FAILED lines step; anything else is VALIDATION_FAILED.
_LINES_FAILURE_OUTCOMES = frozenset({PROVIDER_ERROR, VALIDATION_FAILED, SCHEDULE_UNAVAILABLE, NO_FRESH_AFTER_LOCK})


# ------------------------------------------------------------------------------------------------ paths
def lines_fetch_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / f"_last_game_lines_fetch_{SPORT}.json"


def lines_publish_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_lines_publish.json"


def props_fetch_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_props_fetch.json"


def props_publish_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_props_publish.json"


def props_artifact_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "props" / "NBA_Props.csv"


def market_receipt_path() -> Path:
    """The ONE orchestrator receipt, in the runtime dir (outside the checkout on prod; gitignored on dev)."""
    from services.nba_lines_publisher import runtime_root
    return Path(runtime_root()) / RECEIPT_DIRNAME / RECEIPT_FILENAME


def _mtime(path: Path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha256(path: Path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------------------------------ command
def stage_command(stage: str, caller: str, python: str | None = None) -> list[str]:
    """The canonical stage child command -- identical for bk-daily and the orchestrator (only `caller`
    differs). Relative script path: both callers run with the checkout as the working directory."""
    if stage not in STAGE_SCRIPTS:
        raise ValueError(f"unknown NBA market stage {stage!r}")
    return [python or sys.executable, STAGE_SCRIPTS[stage], "--sport", SPORT, "--bookmakers", BOOKMAKERS,
            "--days", DAYS, "--caller", caller, "--allow-reuse",
            "--lock-wait-seconds", str(budget.LOCK_WAIT_SECONDS), "--no-fetch-after-lock"]


# ------------------------------------------------------------------------------------------------ classify
def _foreign_receipt(receipt, stage_run_id) -> bool:
    """True only when PROVABLY another stage run's receipt: this stage has a token and the receipt carries a
    DIFFERENT one. (A receipt with no token is legacy/unknown and keeps the legacy mtime rule.)"""
    return (stage_run_id is not None and isinstance(receipt, dict) and bool(receipt.get("stage_run_id"))
            and receipt.get("stage_run_id") != stage_run_id)


def _own_publisher_receipt(shared_path: Path, stage_run_id, kind: str):
    """This stage run's OWN copy of its publisher receipt (services/receipt_io per-run file), or None."""
    if not stage_run_id:
        return None
    from services.receipt_io import stage_run_receipt_path
    own = _read_json(stage_run_receipt_path(shared_path, stage_run_id, kind))
    return own if isinstance(own, dict) and own.get("stage_run_id") == stage_run_id else None


def _publisher_receipt_for_stage(shared_path: Path, mtime_before, stage_run_id, kind: str):
    """(receipt | None, foreign: bool). Own per-run copy first (immune to the single shared slot being replaced by
    another publisher before we classify); else the shared receipt if it advanced during the stage -- unless it
    provably belongs to another stage run."""
    own = _own_publisher_receipt(shared_path, stage_run_id, kind)
    if own is not None:
        return own, False
    if mtime_before is None or _mtime(shared_path) <= mtime_before:
        return None, False
    shared = _read_json(shared_path)
    if _foreign_receipt(shared, stage_run_id):
        return None, True
    return shared, False


def classify_lines(base_dir, returncode, timed_out: bool, fetch_mtime_before: float,
                   publish_mtime_before: float | None = None, stage_run_id: str | None = None) -> tuple[str, str]:
    """(outcome, detail) for the lines stage, from the exit code AND the receipts THIS run wrote.

    An exit code alone never proves a benign non-publish, and an old receipt can never excuse a new failure
    (only a receipt whose mtime advanced during the stage is read). 75 = SKIPPED_LOCKED, 76 =
    LOCK_UNAVAILABLE; REUSED_FRESH / REUSED_FRESH_AFTER_LOCK (benign, LINES_READY) and NO_FRESH_AFTER_LOCK
    (alerting) are read from the publisher receipt written this run.

    `stage_run_id` (set by ensure_stage): the publisher's per-run copy of its receipt is authoritative for this
    stage. The shared single-slot receipt is never adopted when it carries another stage run's token (e.g. the
    lock waiter we released overwrote it before we classified, or the holder we waited for when our own write
    failed); and since another publisher demonstrably ran inside our window, the fetch receipt cannot be
    attributed either: fail closed (VALIDATION_FAILED)."""
    if timed_out:
        return PROVIDER_ERROR, "game-lines stage timed out (child killed; kernel released the lock)"
    if returncode == EXIT_LOCKED:
        return SKIPPED_LOCKED, "another NBA lines publisher held the shared lock; no paid request, nothing written"
    if returncode == EXIT_LOCK_UNAVAILABLE:
        return LOCK_UNAVAILABLE, "the shared NBA lines lock could not be opened; no paid request, nothing written"
    pub_path = lines_publish_receipt_path(base_dir)
    pub, foreign = _publisher_receipt_for_stage(pub_path, publish_mtime_before, stage_run_id, "lines")
    if foreign:
        return VALIDATION_FAILED, (f"exit {returncode}: this run's publisher receipt is missing; the newest "
                                   "receipt belongs to another publisher run and is not adopted")
    if pub:
        got = str(pub.get("outcome") or "")
        if returncode == 0 and got in LINES_READY:
            return got, str(pub.get("detail") or ("published" if got == UPDATED else "reused"))
        if returncode == 0:
            return VALIDATION_FAILED, f"exit 0 but this run's publisher receipt says outcome={got}"
        if got in _LINES_FAILURE_OUTCOMES:
            return got, str(pub.get("detail") or f"exit {returncode}, publisher receipt outcome={got}")
    receipt = None
    path = lines_fetch_receipt_path(base_dir)
    if _mtime(path) > fetch_mtime_before:
        receipt = _read_json(path)
    got = str((receipt or {}).get("outcome") or "")
    if returncode == 0:
        if receipt is not None and got and got != UPDATED:
            return VALIDATION_FAILED, f"exit 0 but this run's receipt says outcome={got}"
        return UPDATED, "published" if receipt is not None else "published (no fresh receipt)"
    if receipt is None:
        return VALIDATION_FAILED, f"exit {returncode} and no receipt from this run proving a cause"
    if got == NO_ACTIVE_EVENTS:
        return SCHEDULE_UNAVAILABLE, "provider returned zero events; no authoritative schedule confirms a no-game day"
    if got in _LINES_FAILURE_OUTCOMES:
        return got, f"exit {returncode}, receipt outcome={got}"
    return VALIDATION_FAILED, f"exit {returncode}, receipt outcome={got or 'missing'}"


def classify_props_publisher(base_dir, returncode, timed_out: bool, publish_mtime_before: float,
                             stage_run_id: str | None = None):
    """Publisher-level props outcomes the response-shape receipt cannot express (the fetch never ran):
    75 SKIPPED_LOCKED, 76 LOCK_UNAVAILABLE, and -- from a props publisher receipt written THIS run --
    REUSED_FRESH / REUSED_FRESH_AFTER_LOCK (benign) or NO_FRESH_AFTER_LOCK / SKIPPED_BLOCKED_BY_LINES
    (alerting). Returns (outcome, detail) or None to fall through to the shape-receipt classifier."""
    if timed_out or returncode is None:
        return None
    if returncode == EXIT_LOCKED:
        return SKIPPED_LOCKED, "another NBA props publisher held the props lock; no paid request, nothing written"
    if returncode == EXIT_LOCK_UNAVAILABLE:
        return LOCK_UNAVAILABLE, "the NBA props lock could not be opened/validated; no paid request, nothing written"
    path = props_publish_receipt_path(base_dir)
    pub, foreign = _publisher_receipt_for_stage(path, publish_mtime_before, stage_run_id, "props")
    if foreign:   # see classify_lines: never adopt another run's receipt
        return VALIDATION_FAILED, (f"exit {returncode}: this run's props publisher receipt is missing; the "
                                   "newest receipt belongs to another publisher run and is not adopted")
    if pub is not None:
        got = str(pub.get("outcome") or "")
        if got in (REUSED_FRESH, REUSED_FRESH_AFTER_LOCK):
            if returncode == 0:
                return got, str(pub.get("detail") or "reused")
            return VALIDATION_FAILED, f"exit {returncode} but this run's props receipt says {got}"
        if got in (NO_FRESH_AFTER_LOCK, SKIPPED_BLOCKED_BY_LINES):
            return got, str(pub.get("detail") or got)
    return None


# ------------------------------------------------------------------------------------------------ credits
ACCOUNT_REMAINING_LABEL = ("ACCOUNT-GLOBAL snapshot: x-requests-remaining on this operation's last attributed "
                           "response. It is the whole account's balance at that moment (other processes spend "
                           "from it too) and is NOT this operation's cost.")


def _new_attribution_id() -> str:
    return uuid.uuid4().hex


def _account_remaining(value) -> dict:
    return {"value": value if isinstance(value, int) and not isinstance(value, bool) else None,
            "scope": "ACCOUNT_GLOBAL", "label": ACCOUNT_REMAINING_LABEL}


def _ledger_credits(base_dir, attribution_id: str) -> dict:
    """Credits THIS operation cost: the sum of x-requests-last over the quota-ledger rows stamped with THIS
    stage's attribution token (services/odds_quota.write_ledger stamps BK_ODDS_ATTRIBUTION_ID). The whole ledger
    is scanned and only token-matching rows count, so rows from any other writer (other sports, a manual NBA
    fetch, the other caller, rows written before/after, rows with no token) can never inflate it, and a rotated
    or truncated ledger cannot shift a positional slice. Never guessed: an attributed row without an integer
    x-requests-last makes the sum UNAVAILABLE. Remaining quota is reported SEPARATELY as an account-global
    snapshot and is never added to the credits."""
    rows = []
    try:
        with open(Path(base_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and attribution_id and row.get("attribution_id") == attribution_id:
                    rows.append(row)
    except OSError:
        pass
    base = {"source": "odds_quota_ledger", "attribution": "per_operation_token",
            "attribution_id": attribution_id, "ledger_entries": len(rows)}
    if not rows:
        return {**base, "x_requests_last_sum": 0, "account_remaining_snapshot": _account_remaining(None),
                "status": "NO_ATTRIBUTED_ENTRIES (no ledger row carries this operation's attribution id: "
                          "no provider response was recorded for it)"}
    lasts = [r.get("last") for r in rows]
    known = all(isinstance(v, int) and not isinstance(v, bool) for v in lasts)
    sports = sorted({str(r.get("sport")) for r in rows})
    return {**base, "sports": sports,
            "x_requests_last_sum": sum(lasts) if known else None,
            "account_remaining_snapshot": _account_remaining(rows[-1].get("remaining")),
            "status": "RECORDED" if known else
                      "UNAVAILABLE (an attributed response lacked x-requests-last; cost is never guessed)"}


# ------------------------------------------------------------------------------------------------ ensure
def _receipt_ref(path: Path, mtime_before: float, base_dir, stage_run_id: str | None = None,
                 kind: str | None = None) -> dict | None:
    """Path + sha256 of a receipt only if THIS stage wrote it; None otherwise. With a stage-run token + kind, the
    publisher's per-run copy is referenced (it is never overwritten by another run); otherwise the shared file
    if its mtime advanced and it is not provably another run's."""
    if stage_run_id and kind:
        from services.receipt_io import stage_run_receipt_path
        own = stage_run_receipt_path(path, stage_run_id, kind)
        if _own_publisher_receipt(path, stage_run_id, kind) is not None:
            path = own
            mtime_before = -1.0
        elif _foreign_receipt(_read_json(path), stage_run_id):
            return None
    if _mtime(path) <= mtime_before:
        return None
    try:
        rel = str(Path(path).relative_to(Path(base_dir)))
    except ValueError:
        rel = str(path)
    return {"path": rel.replace("\\", "/"), "sha256": _sha256(path)}


def ensure_stage(stage: str, caller: str, *, base_dir, command=None, timeout=None, props_artifact=None) -> dict:
    """Run one NBA market stage child (lines or props) and classify it. Returns the stage record used both
    by bk-daily (outcome/detail/exit) and by the orchestrator receipt."""
    if stage not in STAGES:
        raise ValueError(f"unknown NBA market stage {stage!r}")
    command = list(command) if command is not None else stage_command(stage, caller)
    timeout = budget.stage_timeout(stage) if timeout is None else timeout
    if stage == "lines":
        fetch_path, pub_path = lines_fetch_receipt_path(base_dir), lines_publish_receipt_path(base_dir)
    else:
        fetch_path, pub_path = props_fetch_receipt_path(base_dir), props_publish_receipt_path(base_dir)
    artifact = Path(props_artifact) if props_artifact is not None else props_artifact_path(base_dir)
    fetch_before, pub_before = _mtime(fetch_path), _mtime(pub_path)
    artifact_before = _mtime(artifact) if stage == "props" else 0.0
    from services.odds_quota import ATTRIBUTION_ENV
    from services.receipt_io import STAGE_RUN_ENV
    attribution_id = _new_attribution_id()
    child_env = dict(os.environ)
    child_env[ATTRIBUTION_ENV] = attribution_id   # child only; the parent's environment is never modified
    child_env[STAGE_RUN_ENV] = attribution_id     # stamped on the publisher receipts this child writes
    started, t0 = _utc_now(), time.monotonic()
    try:
        result = subprocess.run(command, timeout=timeout, env=child_env)
        rc, timed_out = result.returncode, False
    except subprocess.TimeoutExpired:
        rc, timed_out = None, True
    seconds = round(time.monotonic() - t0, 3)
    try:   # housekeeping: per-run receipt copies older than STAGE_RUN_KEEP_DAYS
        from services.receipt_io import prune_stage_run_receipts
        prune_stage_run_receipts(pub_path)
    except Exception:
        pass
    if stage == "lines":
        outcome, detail = classify_lines(base_dir, rc, timed_out, fetch_before, pub_before,
                                         stage_run_id=attribution_id)
        ok = outcome in LINES_READY
    else:
        special = classify_props_publisher(base_dir, rc, timed_out, pub_before, stage_run_id=attribution_id)
        if special:
            outcome, detail = special
        else:
            outcome, detail, _ = props_step_outcome(base_dir, SPORT, artifact, artifact_before,
                                                    1 if timed_out else rc, timed_out)
        ok = not is_alerting(outcome)
    exit_code = 124 if timed_out else int(rc)
    return {
        "stage": stage, "ran": True, "caller": caller, "stage_run_id": attribution_id,
        "outcome": outcome, "detail": detail,
        "ok": bool(ok), "alerting": is_alerting(outcome), "exit_code": exit_code, "timed_out": timed_out,
        "started_at_utc": started.isoformat(timespec="seconds"),
        "ended_at_utc": _utc_now().isoformat(timespec="seconds"), "seconds": seconds,
        "timeout_seconds": timeout, "lock_wait_seconds": budget.LOCK_WAIT_SECONDS,
        "credits": _ledger_credits(base_dir, attribution_id),
        "publisher_receipt": _receipt_ref(pub_path, pub_before, base_dir, stage_run_id=attribution_id,
                                          kind=stage),
        "fetch_receipt": _receipt_ref(fetch_path, fetch_before, base_dir),
    }


def ensure_nba_lines(caller: str, *, base_dir, command=None, timeout=None) -> dict:
    """Acquire-and-execute, or reuse, a validated NBA lines publish (see module docstring)."""
    return ensure_stage("lines", caller, base_dir=base_dir, command=command, timeout=timeout)


def ensure_nba_props(caller: str, *, base_dir, command=None, timeout=None, props_artifact=None) -> dict:
    """Acquire-and-execute, or reuse, a validated NBA props publish. The props publisher re-verifies the
    lines prerequisite under its own lock before any request."""
    return ensure_stage("props", caller, base_dir=base_dir, command=command, timeout=timeout,
                        props_artifact=props_artifact)


def props_not_attempted(lines: dict) -> dict:
    return {"stage": "props", "ran": False, "caller": lines.get("caller"), "outcome": SKIPPED_BLOCKED_BY_LINES,
            "detail": f"lines stage ended {lines.get('outcome')}: props NOT attempted, zero props requests",
            "ok": False, "alerting": True, "exit_code": None, "timed_out": False, "started_at_utc": None,
            "ended_at_utc": None, "seconds": 0.0, "timeout_seconds": budget.stage_timeout("props"),
            "lock_wait_seconds": budget.LOCK_WAIT_SECONDS,
            "credits": {"source": "not_run", "attribution": "per_operation_token", "attribution_id": None,
                        "ledger_entries": 0, "x_requests_last_sum": 0,
                        "account_remaining_snapshot": _account_remaining(None), "status": "NOT_RUN"},
            "publisher_receipt": None, "fetch_receipt": None}


# ------------------------------------------------------------------------------------------------ orchestrator
def write_receipt_atomic(path: Path, payload: dict) -> Path:
    """temp file in the same directory + fsync + os.replace (readers see the old or the new receipt, never
    a torn one). The directory is created 0700."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def run_market_refresh(*, base_dir, caller: str = ORCHESTRATOR_CALLER, command_for=None,
                       receipt_path: Path | None = None) -> tuple[int, dict]:
    """The orchestrator state machine (sequential; never two stages at once):

      L  ensure_nba_lines  -> outcome in LINES_READY (UPDATED / REUSED_FRESH / REUSED_FRESH_AFTER_LOCK)?
           no  -> props NOT attempted (SKIPPED_BLOCKED_BY_LINES, zero props requests); exit = lines exit
           yes -> P
      P  ensure_nba_props  -> benign (UPDATED / REUSED_* / NO_MARKETS_POSTED / NO_ACTIVE_EVENTS)? exit 0
                              else exit = props exit (non-zero)
      R  ONE receipt covering both stages, written atomically to the runtime dir, on every path.

    `command_for(stage) -> argv` overrides the stage child (QC stub provider only); production uses
    stage_command().

    Run lock (no wait): a second orchestrator started while one is running (a manual start during a timer
    run) exits SKIPPED_LOCKED (75) at once -- no stage, no request, and it does NOT touch the shared receipt
    (only the run-lock holder writes it). bk-daily does not take this lock; it is serialized against the
    orchestrator by the per-stage publisher locks + reuse-under-lock."""
    from services.nba_lines_publisher import runtime_lock_spec
    from services.process_lock import ExclusiveLock, LockUnavailable
    try:
        lpath, lroot, _src = runtime_lock_spec(RUN_LOCK_FILENAME, RUN_LOCK_OVERRIDE_ENV)
        run_lock = ExclusiveLock(lpath, label=f"nba_market_refresh:{caller}", root=lroot)
        got = run_lock.acquire(wait_seconds=0)
    except LockUnavailable as exc:
        print(f"[{LOCK_UNAVAILABLE}] NBA market refresh ({caller}): {exc}. No stage run, no request.", flush=True)
        return EXIT_LOCK_UNAVAILABLE, {"result": LOCK_UNAVAILABLE, "exit_code": EXIT_LOCK_UNAVAILABLE,
                                       "stages": [], "receipt_path": "not written (run lock unavailable)"}
    if not got:
        print(f"[{SKIPPED_LOCKED}] NBA market refresh ({caller}): another orchestrator run holds {lpath}. "
              "No stage run, no request, receipt untouched.", flush=True)
        return EXIT_LOCKED, {"result": SKIPPED_LOCKED, "exit_code": EXIT_LOCKED, "stages": [],
                             "receipt_path": "not written (another run holds the run lock)"}
    try:
        return _run_market_refresh_locked(base_dir=base_dir, caller=caller, command_for=command_for,
                                          receipt_path=receipt_path)
    finally:
        run_lock.release()


def _run_market_refresh_locked(*, base_dir, caller, command_for, receipt_path) -> tuple[int, dict]:
    run_id = uuid.uuid4().hex
    started, t0 = _utc_now(), time.monotonic()
    cmd = (lambda s: command_for(s)) if command_for else (lambda s: None)
    lines = ensure_nba_lines(caller, base_dir=base_dir, command=cmd("lines"))
    if lines["outcome"] in LINES_READY:
        props = ensure_nba_props(caller, base_dir=base_dir, command=cmd("props"))
    else:
        props = props_not_attempted(lines)
    if lines["outcome"] not in LINES_READY:
        exit_code, result = (lines["exit_code"] or 1), "FAILED_AT_LINES"
    elif props["alerting"]:
        exit_code, result = (props["exit_code"] or 1), "FAILED_AT_PROPS"
    else:
        exit_code, result = 0, "COMPLETE"
    receipt = {
        "schema": RECEIPT_SCHEMA, "run_id": run_id, "caller": caller, "pid": os.getpid(),
        "started_at_utc": started.isoformat(timespec="seconds"),
        "ended_at_utc": _utc_now().isoformat(timespec="seconds"),
        "seconds": round(time.monotonic() - t0, 3),
        "result": result, "exit_code": exit_code,
        "stages": [lines, props],
        "paid_request_evidence": "per-stage `credits` from the Odds API quota ledger; zero ledger entries for a "
                                 "reused / skipped / not-run stage",
        "timeouts": budget.as_receipt(),
    }
    path = Path(receipt_path) if receipt_path is not None else market_receipt_path()
    try:
        write_receipt_atomic(path, receipt)
        receipt_note = str(path)
    except OSError as exc:   # the receipt is evidence, not the publish; a write failure is loud, never OK
        receipt_note = f"RECEIPT WRITE FAILED: {exc}"
        if exit_code == 0:
            exit_code = 1
            receipt["exit_code"], receipt["result"] = 1, "RECEIPT_WRITE_FAILED"
    receipt["receipt_path"] = receipt_note
    return exit_code, receipt
