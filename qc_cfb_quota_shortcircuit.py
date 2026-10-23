"""QC: refresh_cfb_data halts on CFBD provider quota (429) instead of hammering every sub-step.

Incident 2026-10-23: CFBD returned HTTP 429 'Monthly call quota exceeded' and the CFB refresh attempted
all ~14 sub-steps, each 429-ing. It must detect the quota exhaustion, stop, and report
PROVIDER_QUOTA_EXHAUSTED (exit 3), preserving last-known-good. Pure: subprocess.run is monkeypatched so
no network/CFBD calls happen. Exits 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import io
import os
import sys
import contextlib

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

    import tempfile
    calls = {"n": 0}
    mode = {"rc": 1, "out": "CFBD responded HTTP 429: Monthly call quota exceeded"}

    def fake_run(command, **kwargs):
        calls["n"] += 1
        return _FakeResult(mode["rc"], stdout=mode["out"])

    def _run_main():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = r.main()
        return rc, buf.getvalue()

    saved = {k: os.environ.get(k) for k in ("CFBD_API_KEY", "BK_RUNTIME_DIR", "BK_CFBD_FORCE")}
    tmp = tempfile.mkdtemp(prefix="qc_cfbd_")
    os.environ["CFBD_API_KEY"] = "qc-fake-key"
    os.environ["BK_RUNTIME_DIR"] = tmp
    os.environ.pop("BK_CFBD_FORCE", None)
    orig_run = r.subprocess.run
    r.subprocess.run = fake_run
    try:
        r._clear_cfbd_state()

        # (a) first 429 run: stop after ONE call, exit 3, persist exhausted state
        calls["n"] = 0
        rc, out = _run_main()
        if rc != 3 or "PROVIDER_QUOTA_EXHAUSTED" not in out:
            issues.append(f"429 run: expected exit 3 + PROVIDER_QUOTA_EXHAUSTED (got rc={rc})")
        elif calls["n"] != 1:
            issues.append(f"429 run did not short-circuit: {calls['n']} sub-steps (want 1)")
        else:
            notes.append("429 run -> exit 3, PROVIDER_QUOTA_EXHAUSTED, 1 sub-step (not ~14)")
        st = r._read_cfbd_state()
        if not st.get("exhausted"):
            issues.append("exhausted state was not persisted after the 429")
        else:
            notes.append("quota-exhausted state persisted (detected_at/reason recorded)")

        # (b) next scheduled run: BLOCKED -> SKIP, makes NO CFBD request (0 calls), exit 3
        calls["n"] = 0
        rc, out = _run_main()
        if rc != 3 or "[SKIP]" not in out:
            issues.append(f"blocked run did not SKIP (rc={rc})")
        elif calls["n"] != 0:
            issues.append(f"blocked run STILL made {calls['n']} CFBD request(s) (want 0)")
        else:
            notes.append("persisted-exhausted -> next run SKIPs with ZERO CFBD requests")

        # (c) operator override (BK_CFBD_FORCE=1) ignores the backoff and attempts again
        os.environ["BK_CFBD_FORCE"] = "1"
        calls["n"] = 0
        rc, out = _run_main()
        if calls["n"] == 0:
            issues.append("BK_CFBD_FORCE=1 did not override the backoff")
        else:
            notes.append("BK_CFBD_FORCE=1 overrides the backoff (attempts again)")
        os.environ.pop("BK_CFBD_FORCE", None)

        # (d) a clean run (override so it is not blocked) clears the persisted state
        mode["rc"], mode["out"] = 0, "ok"
        r._write_cfbd_state({"exhausted": True, "provider": "cfbd", "detected_at": "x", "reset_at": None,
                             "reason": "test"})
        os.environ["BK_CFBD_FORCE"] = "1"   # override the block so the clean run actually executes
        calls["n"] = 0
        rc, out = _run_main()
        os.environ.pop("BK_CFBD_FORCE", None)
        if r._read_cfbd_state().get("exhausted"):
            issues.append("a clean CFB run did NOT clear the persisted exhausted state")
        elif rc != 0:
            issues.append(f"clean run did not exit 0 (rc={rc})")
        else:
            notes.append("a clean run (post-reset/override) clears the persisted exhausted state")
    finally:
        r.subprocess.run = orig_run
        r._clear_cfbd_state()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            os.rmdir(tmp)
        except OSError:
            pass

    # (e) CROSS-PROCESS: a FRESH interpreter (simulating a service restart) honors the persisted state
    # and makes NO CFBD call. Write state in one process; a separate python process must SKIP (exit 3).
    import subprocess as _sp
    tmp2 = tempfile.mkdtemp(prefix="qc_cfbd_xp_")
    env = dict(os.environ)
    env["BK_RUNTIME_DIR"] = tmp2
    env["CFBD_API_KEY"] = "qc-fake-key"
    env.pop("BK_CFBD_FORCE", None)
    try:
        # process 1: persist the exhausted state
        p1 = _sp.run([sys.executable, "-c",
                      "import refresh_cfb_data as r; r._write_cfbd_state({'exhausted':True,'provider':'cfbd',"
                      "'detected_at':'t','reset_at':None,'reason':'xp test'})"],
                     cwd=str(r.BASE_DIR), env=env, capture_output=True, text=True)
        # process 2: fresh interpreter -> must SKIP without any CFBD request
        p2 = _sp.run([sys.executable, "-c", "import refresh_cfb_data as r; raise SystemExit(r.main())"],
                     cwd=str(r.BASE_DIR), env=env, capture_output=True, text=True)
        if p2.returncode != 3 or "[SKIP]" not in (p2.stdout + p2.stderr):
            issues.append(f"cross-process: fresh interpreter did not SKIP persisted state (rc={p2.returncode})")
        else:
            notes.append("cross-process/restart: a fresh interpreter honors persisted backoff (SKIP, exit 3, no call)")
    finally:
        with contextlib.suppress(Exception):
            import shutil
            shutil.rmtree(tmp2, ignore_errors=True)

    if not issues:
        notes.append("CFBD quota short-circuit + persistent backoff (incl. cross-process) verified")
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
