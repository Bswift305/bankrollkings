"""QC: recover_odds_fetch.py safety guards (Oct 23 recovery, directive item 5).

Proves the receipt wrapper: redacts keys in the printed command, refuses concurrent execution, refuses
when a refresh/fetch job is already running, and leaves the authoritative bytes unchanged on a failed
fetch. Pure: the fetch command is a harmless local python -c; process detection is monkeypatched.
Exits 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

import recover_odds_fetch as w


def _run_main(argv):
    old = sys.argv
    sys.argv = argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = w.main()
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def run_qc():
    issues, notes = [], []
    d = Path(tempfile.mkdtemp(prefix="qc_recover_"))
    art = d / "NFL_Odds.csv"
    art.write_text("Away,Home,LastUpdated\nA,B,2026-10-26T12:00:00Z\n", encoding="utf-8")
    before = art.read_bytes()
    w.LOCK_PATH = d / "lock"

    # (1) key redaction in the printed command
    if "<REDACTED>" not in w._redact("python fetch_game_lines.py --api-key SECRETKEY123 --sport nfl"):
        issues.append("command redaction did not hide --api-key value")
    elif "SECRETKEY123" in w._redact("x --api-key SECRETKEY123"):
        issues.append("redacted command still contains the key")
    else:
        notes.append("key redaction in printed command works")

    # (2) concurrency lock
    orig_running = w._running_refresh_cmdlines
    w._running_refresh_cmdlines = lambda: []
    try:
        if not w._acquire_lock():
            issues.append("could not acquire a fresh lock")
        elif w._acquire_lock():
            issues.append("second acquire did not refuse (concurrency not blocked)")
        else:
            notes.append("concurrent execution refused (lock held)")
        w._release_lock()

        # (3) active refresh job -> REFUSED (exit 3), fetch NOT run
        ran_marker = d / "ran"
        w._running_refresh_cmdlines = lambda: ["python run_daily.py --sports nfl"]
        rc, out = _run_main(["prog", "--artifact", str(art), "--",
                             sys.executable, "-c", f"open(r'{ran_marker}','w').close()"])
        if rc != 3 or "REFUSED" not in out:
            issues.append(f"active-job guard did not refuse (rc={rc})")
        elif ran_marker.exists():
            issues.append("fetch RAN despite an active refresh job")
        else:
            notes.append("active refresh job -> REFUSED, fetch not run")

        # (4) failed fetch leaves authoritative bytes unchanged + exit propagated
        w._running_refresh_cmdlines = lambda: []
        rc, out = _run_main(["prog", "--artifact", str(art), "--", sys.executable, "-c", "import sys; sys.exit(1)"])
        if rc != 1:
            issues.append(f"failed fetch did not propagate exit 1 (rc={rc})")
        elif art.read_bytes() != before:
            issues.append("failed fetch CHANGED the authoritative bytes")
        elif "PRESERVED" not in out:
            issues.append("failure path did not report last-known-good PRESERVED")
        else:
            notes.append("failed fetch -> exit 1, bytes unchanged, last-known-good PRESERVED")
    finally:
        w._running_refresh_cmdlines = orig_running
        try:
            w._release_lock()
        except Exception:
            pass
        for f in d.glob("*"):
            with contextlib.suppress(OSError):
                f.unlink()
        with contextlib.suppress(OSError):
            os.rmdir(d)

    if not issues:
        notes.append("recover_odds_fetch safety guards verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS RECOVER-ODDS WRAPPER QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("recover_odds_fetch safety guards verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
