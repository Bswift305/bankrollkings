"""QC: refresh_cfb_data halts on CFBD provider quota (429) instead of hammering every sub-step.

Incident 2026-10-23: CFBD returned HTTP 429 'Monthly call quota exceeded' and the CFB refresh attempted
all ~14 sub-steps, each 429-ing. It must detect the quota exhaustion, stop, and report
PROVIDER_QUOTA_EXHAUSTED (exit 3), preserving last-known-good. Pure: subprocess.run is monkeypatched so
no network/CFBD calls happen. Exits 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import io
import os
import contextlib
import types

import refresh_cfb_data as r


class _FakeResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run_qc():
    issues, notes = [], []

    # Helper classifier
    pos = ["HTTP 429: Monthly call quota exceeded", "429 Too Many Requests",
           "error: quota exceeded for this month", "OUT_OF_USAGE_CREDITS"]
    neg = ["HTTP 401 Unauthorized", "connection timed out", "schema validation failed", "exit 1"]
    for s in pos:
        if not r._is_provider_quota_exhausted(s):
            issues.append(f"quota classifier missed: {s!r}")
    for s in neg:
        if r._is_provider_quota_exhausted(s):
            issues.append(f"quota classifier false-positive: {s!r}")
    if not issues:
        notes.append("_is_provider_quota_exhausted classifies 429/quota vs auth/timeout/schema correctly")

    # Simulate: first CFBD sub-step returns 429 -> must stop after ONE call, print the marker, exit 3.
    calls = {"n": 0}

    def fake_run(command, **kwargs):
        calls["n"] += 1
        return _FakeResult(1, stdout="CFBD responded HTTP 429: Monthly call quota exceeded")

    orig_run = r.subprocess.run
    orig_env = os.environ.get("CFBD_API_KEY")
    os.environ["CFBD_API_KEY"] = "qc-fake-key"
    r.subprocess.run = fake_run
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = r.main()
        out = buf.getvalue()
    finally:
        r.subprocess.run = orig_run
        if orig_env is None:
            os.environ.pop("CFBD_API_KEY", None)
        else:
            os.environ["CFBD_API_KEY"] = orig_env

    if rc != 3:
        issues.append(f"expected exit 3 (PROVIDER_QUOTA_EXHAUSTED), got {rc}")
    else:
        notes.append("exit 3 (PROVIDER_QUOTA_EXHAUSTED) on CFBD 429")
    if "PROVIDER_QUOTA_EXHAUSTED" not in out:
        issues.append("did not print PROVIDER_QUOTA_EXHAUSTED")
    else:
        notes.append("printed PROVIDER_QUOTA_EXHAUSTED")
    if calls["n"] != 1:
        issues.append(f"did not short-circuit: ran {calls['n']} CFBD sub-steps (want 1)")
    else:
        notes.append("short-circuited after the first 429 (1 sub-step attempted, not ~14)")

    if not issues:
        notes.append("CFBD quota short-circuit verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS CFBD QUOTA SHORT-CIRCUIT QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("CFBD quota short-circuit verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
