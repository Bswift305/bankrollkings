"""
THE single NBA game-lines publisher (2026-11, Gap 3 of the NBA game-lines v3 correction).
=========================================================================================

Every NBA game-lines publish -- bk-daily's NBA refresh (refresh_nba_daily -> fetch_game_lines.py), the
4-hourly NBA lines job, and any manual `fetch_game_lines.py --sport basketball_nba` -- enters through
publish(). There is no other path: fetch_game_lines.run_fetch() refuses an event-aware (NBA) fetch unless
this module holds the lock.

State machine (v4, owner decision 2). Every state is decided BEFORE or UNDER the lock; no paid request is
ever made without lock ownership:

  S0  resolve + enforce the lock location (lock_spec / process_lock.open_validated_lock_file):
        rejected (outside the runtime root, symlink, loose perms not ours) or unopenable
        -> LOCK_UNAVAILABLE                exit 76   alerting   no request, no write
  S1  try the lock, waiting at most --lock-wait-seconds:
        still held by another process     -> SKIPPED_LOCKED      exit 75   alerting   no request, no write
                                             (NEVER "OK" just because another process held the lock)
  S2  lock acquired. `contended` = the first attempt found another holder (we waited for it).
      S2a allow_reuse and NOT contended: verify the receipt + every output sha256 (reuse_check)
            valid fresh publish            -> REUSED_FRESH        exit 0    benign     no request
      S2b allow_reuse and contended: RE-READ the receipt + hashes UNDER the lock (the holder we waited
          for may just have published -- or may have failed)
            valid fresh publish            -> REUSED_FRESH_AFTER_LOCK exit 0 benign   no request
            none, fetch_after_contention   -> fall through to S3 (fetch normally, under the lock)
            none, not fetch_after_contention -> NO_FRESH_AFTER_LOCK exit 1 alerting   no request, no write
                                             (CLI --no-fetch-after-lock; bk-daily keeps the default and fetches)
      S2c not allow_reuse (the 4-hourly job, manual runs): it IS the refresh -> S3 (contended or not)
      S3  fetch (the ONE shared fetch + event validation + atomic 3-file publish, fetch_game_lines.run_fetch,
          contract game_lines_event_v1) -> UPDATED exit 0 / PROVIDER_ERROR / VALIDATION_FAILED /
          SCHEDULE_UNAVAILABLE exit 1
  S4  publisher receipt (data/tracking/_last_nba_lines_publish.json) -- only ever by the lock holder --
      then release (also released by the kernel on exit/crash).
  REUSED_FRESH vs REUSED_FRESH_AFTER_LOCK: both are a receipt+hash-verified reuse under the lock; the
  latter means this process had to WAIT for another holder first, so the operator can see the two jobs
  collided and were serialized. There is no pre-lock reuse path: reuse is only ever decided under the lock.

Lock location (one explicit path, OUTSIDE the checkout on prod), see lock_spec():
  $BK_RUNTIME_DIR/locks/nba_game_lines.lock       when BK_RUNTIME_DIR is set (repo convention, bk_runtime)
  /opt/bankrollkings-runtime/locks/nba_game_lines.lock   POSIX default (prod)
  <repo>/.runtime/generated/locks/nba_game_lines.lock    Windows dev only (gitignored)
  $BK_NBA_LINES_LOCK_PATH  QC override -- honoured ONLY when it resolves inside the runtime root or inside a
                           `qc_*` directory directly under the system temp dir; anything else is
                           LOCK_UNAVAILABLE (exit 76). Never set it on prod.
  Containment, symlink and POSIX-permission (dir 0700 / file 0600) enforcement: services/process_lock.py.

Reuse window: REUSE_WINDOW_MINUTES = 90 is DUPLICATE-FETCH SUPPRESSION ONLY. It decides whether paying for
another fetch is pointless; it is NOT a freshness boundary. The executable-price boundary stays the 6h
rule (LIVE_LINES_MAX_AGE_HOURS, CLOCK A) enforced on customer surfaces from the provider LastUpdated -- a
reused file ages exactly like a fetched one. 90 min leaves >= 4.5h of customer-executable life after a
reuse, and covers the proposed orchestrator's last tick before 13:00 UTC being reused by bk-daily's NBA step
(v5: both callers enter through services/nba_market.ensure_nba_lines; the tick time lives in
ops/bk-nba-market-refresh.timer).
Reuse requires ALL of: fetch receipt outcome UPDATED, exit_code 0, published True, contract
game_lines_event_v1, receipt time parseable, timezone-aware, not in the future, and within the window, and
every output's current sha256 equal to the receipt's sha256_after (the file on disk is exactly what that
verified publish wrote).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.process_lock import ExclusiveLock, LockPathRejected, LockUnavailable, is_within, real
from services.run_outcomes import (
    NO_ACTIVE_EVENTS, NO_FRESH_AFTER_LOCK, PROVIDER_ERROR, REUSED_FRESH, REUSED_FRESH_AFTER_LOCK,
    SCHEDULE_UNAVAILABLE, SKIPPED_LOCKED, UPDATED, VALIDATION_FAILED,
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


def runtime_root() -> Path:
    """The containment root for the lock: $BK_RUNTIME_DIR, else the POSIX prod default, else (Windows dev)
    the gitignored in-repo runtime dir."""
    runtime = (os.environ.get("BK_RUNTIME_DIR") or "").strip()
    if runtime:
        return Path(runtime)
    if os.name != "nt":
        return Path(POSIX_DEFAULT_RUNTIME_DIR)
    import bk_runtime   # Windows dev: the gitignored in-repo runtime dir
    return bk_runtime.runtime_dir()


def lock_path() -> Path:
    """The CANDIDATE lock path (unvalidated; lock_spec() enforces it)."""
    env = (os.environ.get("BK_NBA_LINES_LOCK_PATH") or "").strip()
    if env:
        return Path(env)
    return runtime_root() / "locks" / LOCK_FILENAME


def _qc_temp_root(path: Path):
    """The `qc_*` directory directly under the system temp dir that contains `path`, else None."""
    import tempfile
    tmp = real(tempfile.gettempdir())
    target = real(path)
    if not is_within(target, tmp) or target == tmp:
        return None
    first = os.path.relpath(target, tmp).split(os.sep)[0]
    return Path(tmp) / first if first.lower().startswith("qc_") else None


def runtime_lock_spec(filename: str, override_env: str) -> tuple[Path, Path, str]:
    """Shared by every governed publisher lock (NBA lines, NBA props): (lock file path, containment root,
    source). Canonical = <runtime root>/locks/<filename>. The `override_env` QC override is honoured only
    inside the runtime root or a qc_* temp dir; anything else raises LockPathRejected."""
    root = runtime_root()
    env = (os.environ.get(override_env) or "").strip()
    if not env:
        return root / "locks" / filename, root, "canonical"
    p = Path(env)
    if is_within(p.parent, root):
        return p, root, "override:runtime"
    qc_root = _qc_temp_root(p.parent)
    if qc_root is not None:
        return p, qc_root, "override:qc_temp"
    raise LockPathRejected(f"{override_env}={env} is outside the runtime root {real(root)} and is not "
                           "inside a qc_* temp directory (refused)")


def lock_spec() -> tuple[Path, Path, str]:
    """(lock file path, containment root, source) for the NBA LINES lock."""
    return runtime_lock_spec(LOCK_FILENAME, "BK_NBA_LINES_LOCK_PATH")


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
            allow_reuse: bool = False, lock_wait_seconds: float = 0.0,
            fetch_after_contention: bool = True) -> int:
    """Run one governed NBA lines publish. Returns the process exit code (see the module state machine)."""
    global _ACTIVE_LOCK
    try:
        path, root, source = lock_spec()
        lock = ExclusiveLock(path, label=f"nba_game_lines:{caller}", root=root)
        receipt_before_wait = (_read_json(fetch_receipt_path(base_dir)) or {}).get("run_id")
        got = lock.acquire(wait_seconds=lock_wait_seconds)
    except LockUnavailable as exc:   # incl. LockPathRejected (containment / symlink / permissions)
        print(f"[{LOCK_UNAVAILABLE}] NBA game lines ({caller}): {exc}. No paid request made, nothing written.",
              flush=True)
        return EXIT_LOCK_UNAVAILABLE
    if not got:
        print(f"[{SKIPPED_LOCKED}] NBA game lines ({caller}): another process holds {path} "
              f"(waited {lock.waited_seconds:.1f}s). No paid request made, nothing written.", flush=True)
        return EXIT_LOCKED
    _ACTIVE_LOCK = lock
    started = datetime.now(timezone.utc)
    common = {"caller": caller, "lock_path": str(path), "lock_source": source,
              "lock_waited_seconds": lock.waited_seconds, "lock_contended": lock.contended}
    try:
        if allow_reuse:
            # Decided UNDER the lock, from a fresh re-read of the receipt and the files on disk -- never from
            # the mere fact that another process held the lock.
            ok, detail = reuse_check(base_dir, outputs, now=started)
            if ok:
                outcome = REUSED_FRESH_AFTER_LOCK if lock.contended else REUSED_FRESH
                published_while_waiting = (lock.contended and
                                           (_read_json(fetch_receipt_path(base_dir)) or {}).get("run_id")
                                           != receipt_before_wait)
                _write_publish_receipt(base_dir, {
                    **common, "outcome": outcome, "exit_code": EXIT_OK, "detail": detail, "paid_requests": 0,
                    "published_while_waiting": bool(published_while_waiting),
                    "reuse_window_minutes": REUSE_WINDOW_MINUTES, "at": started.isoformat(timespec="seconds"),
                })
                print(f"[{outcome}] NBA game lines ({caller}): {detail}. No paid request made.", flush=True)
                return EXIT_OK
            if lock.contended and not fetch_after_contention:
                _write_publish_receipt(base_dir, {
                    **common, "outcome": NO_FRESH_AFTER_LOCK, "exit_code": EXIT_FAILED, "paid_requests": 0,
                    "detail": f"waited for another publisher, but no valid fresh publish exists: {detail}",
                    "at": started.isoformat(timespec="seconds"),
                })
                print(f"[{NO_FRESH_AFTER_LOCK}] NBA game lines ({caller}): waited for another publisher but "
                      f"found no valid fresh publish ({detail}). No paid request made, nothing published.",
                      flush=True)
                return EXIT_FAILED
            print(f"[INFO] NBA game lines ({caller}): not reusing -- {detail}"
                  + ("; fetching under the lock after waiting" if lock.contended else "") + ".", flush=True)
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
            **common, "outcome": outcome, "exit_code": rc, "fetch_run_id": fetch_receipt.get("run_id"),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        print(f"[{outcome}] NBA game lines ({caller}) exit={rc}", flush=True)
        return rc
    finally:
        _ACTIVE_LOCK = None
        lock.release()
