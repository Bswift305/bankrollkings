"""
THE single NBA player-props publisher (2026-11, NBA v4 owner update: props get their OWN lock + cadence).
=========================================================================================================

Every NBA player-props publish -- bk-daily's NBA refresh (refresh_nba_daily -> fetch_player_props.py), any
future props timer, and any manual `fetch_player_props.py --sport basketball_nba` -- enters through publish().
fetch_player_props.run_fetch() refuses an NBA props fetch unless this module holds the props lock.

Its OWN lock, separate from the lines lock (services/nba_lines_publisher.py), with the same kernel-lock design
(services/process_lock.py: fcntl.flock on Linux / msvcrt on Windows dev; contained under the runtime root;
no symlink escape; dir 0700 / file 0600; released by the kernel on exit or crash):
  $BK_RUNTIME_DIR/locks/nba_player_props.lock   (POSIX default /opt/bankrollkings-runtime/locks/...)
  $BK_NBA_PROPS_LOCK_PATH  QC override, honoured only inside the runtime root or a qc_* temp dir.
Props NEVER take the lines lock (no lock-ordering / deadlock surface). They depend on the lines EVENT LIST
(fetch_player_props validates NBA props against NBA_Odds.csv, SPORT_EVENT_MANIFESTS), so instead of
locking, the props publisher verifies -- under its own lock and before any paid request -- that the lines
file on disk is a receipt-verified game_lines_event_v1 publish no older than LINES_PREREQ_MAX_AGE_MINUTES
(fetch receipt UPDATED / exit 0 / contract / UTC time / sha256 of NBA_Odds.csv equal to the receipt's).
Lines are atomically replaced, so a concurrent lines publish can only make that sha check fail (props then
skip honestly), never let props validate against a half-written manifest.

State machine (every state is decided BEFORE or UNDER the props lock; no paid request without ownership):
  S0  lock location rejected / unopenable                 -> LOCK_UNAVAILABLE         exit 76  alerting  no request
  S1  props lock held by another process after the wait   -> SKIPPED_LOCKED           exit 75  alerting  no request
                                                              (NEVER "OK" just because another process held it)
  S2  acquired; `contended` = we waited for another holder; with allow_reuse, re-read the props fetch receipt
      + the props file sha256 UNDER the lock:
      S2a valid fresh publish, not contended              -> REUSED_FRESH             exit 0   benign    no request
      S2b valid fresh publish, contended                  -> REUSED_FRESH_AFTER_LOCK  exit 0   benign    no request
      S2b' none, contended, --no-fetch-after-lock         -> NO_FRESH_AFTER_LOCK      exit 1   alerting  no request
      otherwise                                           -> S3
  S3  lines prerequisite (above) not met                  -> SKIPPED_BLOCKED_BY_LINES exit 1   alerting  no request
  S4  fetch (the existing fetch + slate-aware validation + atomic publish, unchanged)
        published                                         -> UPDATED                  exit 0   benign
        not published                                     -> receipt-classified (run_outcomes.classify_props_child):
                                                             NO_MARKETS_POSTED / NO_ACTIVE_EVENTS (benign) or
                                                             VALIDATION_FAILED / PROVIDER_ERROR / STALE (alerting),
                                                             exit = the fetcher's exit (non-zero)
  S5  receipts (only the holder writes): data/tracking/_last_nba_props_fetch.json (every S4 attempt: outcome,
      sha256 of the props file after, lines run it validated against) and data/tracking/_last_nba_props_publish.json
      (every S2-S4 outcome). Release (also released by the kernel on exit/crash).

REUSE_WINDOW_MINUTES = 90 is DUPLICATE-FETCH SUPPRESSION ONLY. Customer surfaces keep the 6h CLOCK-A rule on
the provider LastUpdated (app._executable_props_frame); a reused file ages exactly like a fetched one.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import nba_lines_publisher as lines_pub
from services.process_lock import ExclusiveLock, LockUnavailable
from services.run_outcomes import (
    NO_FRESH_AFTER_LOCK, REUSED_FRESH, REUSED_FRESH_AFTER_LOCK, SKIPPED_BLOCKED_BY_LINES, SKIPPED_LOCKED,
    UPDATED, VALIDATION_FAILED, classify_props_child, load_shape_receipt,
)

SPORT = "basketball_nba"
CONTRACT = "nba_props_slate_v1"
LOCK_FILENAME = "nba_player_props.lock"
LOCK_OVERRIDE_ENV = "BK_NBA_PROPS_LOCK_PATH"
REUSE_WINDOW_MINUTES = 90
# Props validate against the lines event list; the lines publish they rely on must be recent. 120 min covers
# bk-daily (props right after a lines fetch or a <= 90-min lines reuse) and the proposed props cadence
# (props 30 min after each lines run); older lines -> SKIPPED_BLOCKED_BY_LINES, no paid request.
LINES_PREREQ_MAX_AGE_MINUTES = 120
LOCK_UNAVAILABLE = lines_pub.LOCK_UNAVAILABLE

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOCKED = lines_pub.EXIT_LOCKED                 # 75
EXIT_LOCK_UNAVAILABLE = lines_pub.EXIT_LOCK_UNAVAILABLE   # 76

_ACTIVE_LOCK: ExclusiveLock | None = None


def lock_spec():
    return lines_pub.runtime_lock_spec(LOCK_FILENAME, LOCK_OVERRIDE_ENV)


def lock_is_held() -> bool:
    """True only inside publish() while THIS process holds the props lock."""
    return _ACTIVE_LOCK is not None and _ACTIVE_LOCK.held


def fetch_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_props_fetch.json"


def publish_receipt_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "tracking" / "_last_nba_props_publish.json"


def lines_odds_path(base_dir) -> Path:
    return Path(base_dir) / "data" / "odds" / "NBA_Odds.csv"


def _write_json(path: Path, payload: dict) -> None:
    # Atomic temp + replace; the replace retries a Windows sharing violation and every receipt carries this
    # stage run's token (services/receipt_io.py -- v5 race fix).
    from services.receipt_io import current_stage_run_id, write_stage_run_copy, write_text_atomic
    text = json.dumps({**payload, "stage_run_id": current_stage_run_id()}, indent=2, default=str)
    if Path(path).name == "_last_nba_props_publish.json":   # publisher receipt: also this run's own copy
        try:
            write_stage_run_copy(path, "props", text)
        except OSError as exc:
            print(f"[WARN] could not write this run's NBA props publisher receipt copy: {exc}")
    try:
        write_text_atomic(path, text)
    except OSError as exc:
        print(f"[WARN] could not write {path.name}: {exc}")


def reuse_check(base_dir, output: Path, now: datetime | None = None,
                window_minutes: int = REUSE_WINDOW_MINUTES) -> tuple[bool, str]:
    """Is the props file on disk exactly a verified UPDATED publish from inside the window?"""
    now = now or datetime.now(timezone.utc)
    r = lines_pub._read_json(fetch_receipt_path(base_dir))
    if not r:
        return False, "no NBA props fetch receipt"
    if r.get("outcome") != UPDATED or r.get("exit_code") != 0 or r.get("published") is not True:
        return False, f"last NBA props attempt is not a publish (outcome={r.get('outcome')})"
    if r.get("contract") != CONTRACT:
        return False, f"last props publish not on {CONTRACT}"
    at = lines_pub._parse_utc(r.get("at"))
    if at is None:
        return False, "props receipt time missing / not timezone-aware"
    age = now - at
    if age < timedelta(0):
        return False, "props receipt time is in the future"
    if age > timedelta(minutes=window_minutes):
        return False, f"last props publish {age.total_seconds() / 60:.0f} min ago (> {window_minutes} min reuse window)"
    want = (r.get("outputs") or {}).get("props", {}).get("sha256_after")
    if not want or lines_pub._sha256(output) != want:
        return False, "props file on disk does not match the verified publish (sha mismatch)"
    return True, (f"reusing the NBA props published {age.total_seconds() / 60:.0f} min ago "
                  f"(within the {window_minutes}-min window)")


def lines_prerequisite(base_dir, now: datetime | None = None) -> tuple[bool, str, str | None]:
    """(ok, detail, lines_run_id): the event list props validate against is a receipt-verified lines publish."""
    ok, detail = lines_pub.reuse_check(base_dir, {"odds": lines_odds_path(base_dir)}, now=now,
                                       window_minutes=LINES_PREREQ_MAX_AGE_MINUTES)
    run_id = (lines_pub._read_json(lines_pub.fetch_receipt_path(base_dir)) or {}).get("run_id")
    return ok, detail.replace("reusing the NBA lines", "NBA lines event list"), run_id


def publish(args, *, run_fetch, base_dir, output, caller: str = "unspecified", allow_reuse: bool = False,
            lock_wait_seconds: float = 0.0, fetch_after_contention: bool = True) -> int:
    """Run one governed NBA props publish. Returns the process exit code (module state machine)."""
    global _ACTIVE_LOCK
    output = Path(output)
    try:
        path, root, source = lock_spec()
        lock = ExclusiveLock(path, label=f"nba_player_props:{caller}", root=root)
        got = lock.acquire(wait_seconds=lock_wait_seconds)
    except LockUnavailable as exc:
        print(f"[{LOCK_UNAVAILABLE}] NBA player props ({caller}): {exc}. No paid request made, nothing written.",
              flush=True)
        return EXIT_LOCK_UNAVAILABLE
    if not got:
        print(f"[{SKIPPED_LOCKED}] NBA player props ({caller}): another process holds {path} "
              f"(waited {lock.waited_seconds:.1f}s). No paid request made, nothing written.", flush=True)
        return EXIT_LOCKED
    _ACTIVE_LOCK = lock
    started = datetime.now(timezone.utc)
    common = {"caller": caller, "lock_path": str(path), "lock_source": source,
              "lock_waited_seconds": lock.waited_seconds, "lock_contended": lock.contended,
              "at": started.isoformat(timespec="seconds")}
    pub_path = publish_receipt_path(base_dir)
    try:
        if allow_reuse:
            ok, detail = reuse_check(base_dir, output, now=started)
            if ok:
                outcome = REUSED_FRESH_AFTER_LOCK if lock.contended else REUSED_FRESH
                _write_json(pub_path, {**common, "outcome": outcome, "exit_code": EXIT_OK, "detail": detail,
                                       "paid_requests": 0, "reuse_window_minutes": REUSE_WINDOW_MINUTES})
                print(f"[{outcome}] NBA player props ({caller}): {detail}. No paid request made.", flush=True)
                return EXIT_OK
            if lock.contended and not fetch_after_contention:
                _write_json(pub_path, {**common, "outcome": NO_FRESH_AFTER_LOCK, "exit_code": EXIT_FAILED,
                                       "paid_requests": 0, "detail": detail})
                print(f"[{NO_FRESH_AFTER_LOCK}] NBA player props ({caller}): waited for another publisher but "
                      f"found no valid fresh publish ({detail}). No paid request made.", flush=True)
                return EXIT_FAILED
            print(f"[INFO] NBA player props ({caller}): not reusing -- {detail}.", flush=True)
        lines_ok, lines_detail, lines_run = lines_prerequisite(base_dir, now=started)
        if not lines_ok:
            _write_json(pub_path, {**common, "outcome": SKIPPED_BLOCKED_BY_LINES, "exit_code": EXIT_FAILED,
                                   "paid_requests": 0, "detail": lines_detail})
            print(f"[{SKIPPED_BLOCKED_BY_LINES}] NBA player props ({caller}): the lines event list is not a "
                  f"verified recent publish ({lines_detail}). No paid request made, nothing written.", flush=True)
            return EXIT_FAILED
        sha_before = lines_pub._sha256(output)
        try:
            mtime_before = output.stat().st_mtime
        except OSError:
            mtime_before = 0.0
        try:
            rc = int(run_fetch(args))
        except Exception as exc:   # a crash is a failure, never a pass
            print(f"[PROVIDER_ERROR] NBA player props ({caller}) crashed: {exc!r}", flush=True)
            rc = EXIT_FAILED
        sha_after = lines_pub._sha256(output)
        try:
            advanced = output.stat().st_mtime > mtime_before
        except OSError:
            advanced = False
        if rc == 0 and sha_after:
            outcome, detail = UPDATED, "published"
        else:
            outcome, detail = classify_props_child(rc if rc else 1, advanced, load_shape_receipt(base_dir, SPORT))
            if rc == 0:   # exit 0 without a published file is never a success
                rc, outcome = EXIT_FAILED, VALIDATION_FAILED
        _write_json(fetch_receipt_path(base_dir), {
            **common, "outcome": outcome, "exit_code": rc, "published": outcome == UPDATED, "contract": CONTRACT,
            "detail": detail, "lines_run_id": lines_run,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outputs": {"props": {"path": str(output), "sha256_before": sha_before, "sha256_after": sha_after}},
        })
        _write_json(pub_path, {**common, "outcome": outcome, "exit_code": rc, "detail": detail,
                               "lines_run_id": lines_run,
                               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        print(f"[{outcome}] NBA player props ({caller}) exit={rc}", flush=True)
        return rc
    finally:
        _ACTIVE_LOCK = None
        lock.release()
