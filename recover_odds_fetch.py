"""One-command recovery receipt for a single narrow Odds fetch (incident 2026-10-23).

Wraps ONE narrow fetch so the operator never assembles the receipt by hand. It records the authoritative
artifact BEFORE and AFTER the fetch (content-free: hashes, sizes, row counts, schema fingerprint,
data-through), runs the fetch command, surfaces the fetcher's own quota receipt, and verifies the
atomic-publish + last-known-good-on-failure outcome.

Usage:
  python recover_odds_fetch.py --artifact data/odds/NFL_Odds.csv -- \
      python fetch_game_lines.py --sport americanfootball_nfl --days 2 --expected-cost 12

Everything after `--` is the fetch command, run verbatim. Exits with the fetch's own exit code.
Prints NO row content, no keys, no URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCK_PATH = Path(os.environ.get("BK_RUNTIME_DIR") or tempfile.gettempdir()) / "bk_recover_odds.lock"
LOCK_STALE_SECONDS = 2 * 3600
# Process names that mean a refresh/fetch job is already touching the artifacts.
_BUSY_MARKERS = ("run_daily.py", "refresh_", "fetch_game_lines.py", "fetch_player_props.py",
                 "fetch_futures_odds.py", "fetch_football", "run_all_scorecards.py")
_KEY_RE = [
    (re.compile(r"(--api[-_]?key[=\s]+)\S+", re.I), r"\1<REDACTED>"),
    (re.compile(r"(apiKey=)[^&\s\"']+", re.I), r"\1<REDACTED>"),
    (re.compile(r"([?&](?:api[_-]?key|apikey|key|token)=)[^&\s\"']+", re.I), r"\1<REDACTED>"),
]


def _redact(text):
    out = text or ""
    for pat, repl in _KEY_RE:
        out = pat.sub(repl, out)
    return out


def _acquire_lock():
    """Refuse concurrent execution: O_EXCL lock in the runtime dir. A stale lock (> LOCK_STALE_SECONDS) is
    reclaimed. Returns True on success, False if another recovery holds a fresh lock."""
    try:
        if LOCK_PATH.exists() and (time.time() - LOCK_PATH.stat().st_mtime) > LOCK_STALE_SECONDS:
            LOCK_PATH.unlink()  # stale -> reclaim
    except OSError:
        pass
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {int(time.time())}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return True  # cannot create a lock (read-only fs) -> do not block the operator


def _release_lock():
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def _running_refresh_cmdlines():
    """Best-effort list of OTHER running refresh/fetch process command lines (sanitized). Uses /proc on
    Linux (prod), psutil if present, else returns []. Detects a concurrent daily timer/job."""
    me = os.getpid()
    hits = []
    proc_dir = Path("/proc")
    if proc_dir.is_dir():
        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit() or int(pid_dir.name) == me:
                continue
            try:
                raw = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if "python" in raw.lower() and any(m in raw for m in _BUSY_MARKERS) and "recover_odds_fetch" not in raw:
                hits.append(_redact(raw.strip())[:160])
        return hits
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            if p.info["pid"] == me:
                continue
            raw = " ".join(p.info.get("cmdline") or [])
            if "python" in raw.lower() and any(m in raw for m in _BUSY_MARKERS) and "recover_odds_fetch" not in raw:
                hits.append(_redact(raw.strip())[:160])
    except Exception:
        pass
    return hits


def _stat(path: Path):
    """Content-free fingerprint of an artifact: exists, sha256, size, rows, schema fingerprint, data-through."""
    out = {"exists": path.exists(), "sha256": None, "size": None, "rows": None,
           "schema_fp": None, "data_through": None}
    if not path.exists():
        return out
    data = path.read_bytes()
    out["size"] = len(data)
    out["sha256"] = hashlib.sha256(data).hexdigest()[:16]
    try:
        import pandas as pd
        df = pd.read_csv(path)
        out["rows"] = int(len(df))
        cols = list(df.columns)
        out["schema_fp"] = hashlib.sha256(",".join(map(str, cols)).encode()).hexdigest()[:12]
        for tc in ("LastUpdated", "last_update", "SnapshotAt"):
            if tc in cols:
                ts = pd.to_datetime(df[tc], errors="coerce", utc=True, format="mixed").max()
                out["data_through"] = None if ts is None or ts is pd.NaT else str(ts)
                break
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="One-command recovery receipt for a narrow Odds fetch.")
    ap.add_argument("--artifact", required=True, help="Authoritative CSV the fetch publishes.")
    ap.add_argument("--ignore-running", action="store_true",
                    help="Override the active-refresh-job guard (only if you are certain no job is touching the data).")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- then the fetch command to run verbatim.")
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("No fetch command given (expected: ... -- python fetch_game_lines.py ...)")
        return 2

    artifact = Path(args.artifact)
    if not artifact.is_absolute():
        artifact = BASE_DIR / artifact

    print("=" * 78)
    print("ODDS NARROW-FETCH RECOVERY RECEIPT")
    print("=" * 78)

    # Preflight guards (never spend a credit while a daily job runs or another recovery is active).
    busy = _running_refresh_cmdlines()
    if busy and not args.ignore_running:
        print("REFUSED: a refresh/fetch job is already running -- do not fetch concurrently:")
        for b in busy:
            print(f"  - {b}")
        print("(stop the daily timer/job, or pass --ignore-running only if you are certain it is safe.)")
        return 3
    if not _acquire_lock():
        print(f"REFUSED: another recovery fetch holds the lock ({LOCK_PATH}). Concurrent recovery blocked.")
        return 3

    try:
        pre = _stat(artifact)
        print(f"artifact: {artifact.relative_to(BASE_DIR) if str(artifact).startswith(str(BASE_DIR)) else artifact}")
        print(f"PRE : exists={pre['exists']} sha={pre['sha256']} size={pre['size']} rows={pre['rows']} "
              f"schema={pre['schema_fp']} data_through={pre['data_through']}")
        print(f"command: {_redact(' '.join(cmd))}")   # keys never printed

        proc = subprocess.run(cmd, cwd=str(BASE_DIR))
        exit_code = proc.returncode   # the fetcher prints its own QUOTA RECEIPT to stdout above
    finally:
        _release_lock()

    post = _stat(artifact)
    print(f"POST: exists={post['exists']} sha={post['sha256']} size={post['size']} rows={post['rows']} "
          f"schema={post['schema_fp']} data_through={post['data_through']}")
    print(f"fetch exit code: {exit_code}")

    changed = pre["sha256"] != post["sha256"]
    if exit_code == 0:
        if changed:
            print("atomic publish  : PUBLISHED (artifact advanced)")
        else:
            print("atomic publish  : no change (exit 0 but artifact unchanged -- e.g. no new lines)")
        if post["data_through"] and pre["data_through"] and post["data_through"] < pre["data_through"]:
            print("WARNING: data_through REGRESSED despite exit 0 -- investigate before accepting.")
    else:
        if changed:
            print("last-known-good : *** VIOLATED *** artifact changed on a FAILED fetch -- investigate.")
        else:
            print("last-known-good : PRESERVED (failed fetch left the prior artifact byte-for-byte)")
    print("=" * 78)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
