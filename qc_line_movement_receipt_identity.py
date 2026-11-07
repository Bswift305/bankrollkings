"""QC: the line-movement runner identifies its child's receipt by RUN TOKEN, never by mtime (2026-11-04).

Defect (Linux gate on 479e8c4): refresh_line_movement_snapshots judged `_last_game_lines_fetch_<sport>.json`
"fresh" by `mtime > mtime_before`. On a coarse-timestamp filesystem two successive writes share an mtime, so a
receipt this run DID write read as stale (benign NO_ACTIVE_EVENTS / NO_GAMES_SCHEDULED misread as failures, a
VALIDATION_FAILED receipt with exit 0 misread as OK). Fix: the runner passes a per-invocation token
(services/run_receipts.STAGE_RUN_ENV); fetch_game_lines stamps it on the receipt; the runner accepts only a
matching token (missing -> RUN_RECEIPT_MISSING, other/no token -> RUN_RECEIPT_MISMATCH, both failures).

Proves, offline (temp dirs; faked children; no network):
  I1 successive receipts with IDENTICAL mtimes (os.utime) classify exactly by content + token: UPDATED -> OK,
     only a GOVERNED NO_GAMES_SCHEDULED (exit 1) -> benign skip; NO_ACTIVE_EVENTS -> FAILED; exit 0 OK only on
     outcome UPDATED + exit_code 0; exit 0 + VALIDATION_FAILED -> FAILED,
     SCHEDULE_UNAVAILABLE -> FAILED.
  I2 the child wrote nothing (an older receipt from a previous run is still there) -> RUN_RECEIPT_MISMATCH;
     no receipt at all -> RUN_RECEIPT_MISSING; a receipt carrying another writer's token -> MISMATCH; a
     tokenless legacy receipt -> MISMATCH. None of them is ever OK or a benign skip.
  I3 fetch_game_lines stamps the caller's token on its receipt (none / unsafe token -> null).
  I4 static: the runner's code no longer reads any mtime.
  M  mutation: the previous mtime classifier, fed the same identical-mtime sequence, MISCLASSIFIES (so this QC
     would have caught the defect).
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILS: list[str] = []
NOTES: list[str] = []
FIXED_MTIME = 1_700_000_000   # every receipt write gets this exact mtime


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


class _R:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout = ""   # the line-movement runner captures child output (Safeguard A markers)
        self.stderr = ""


def _write(path: Path, payload: dict):
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (FIXED_MTIME, FIXED_MTIME))     # identical mtime for EVERY write


def _drive(lm, base: Path, plan: dict):
    """plan[sport] = (rc, outcome | None, token_mode) with token_mode in {'own', 'other', 'none'}."""
    from services.run_receipts import STAGE_RUN_ENV

    def fake_run(command, cwd=None, timeout=None, env=None, **kw):
        joined = " ".join(map(str, command))
        sport = "baseball_mlb" if "mlb" in joined else "basketball_wnba"
        rc, outcome, mode = plan[sport]
        if outcome:
            tok = {"own": (env or {}).get(STAGE_RUN_ENV), "other": "f" * 32, "none": None}[mode]
            payload = {"outcome": outcome, "exit_code": rc}
            if mode != "none":
                payload["stage_run_id"] = tok
            _write(base / "data/tracking" / f"_last_game_lines_fetch_{sport}.json", payload)
        return _R(rc)
    saved = (lm.BASE_DIR, lm.subprocess.run)
    lm.BASE_DIR, lm.subprocess.run = base, fake_run
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = lm.main()
    finally:
        lm.BASE_DIR, lm.subprocess.run = saved
    out = buf.getvalue()
    mlb = out.split("[MLB game lines]")[1].split("[WNBA")[0] if "[MLB game lines]" in out else ""
    return rc, mlb, out


def old_mtime_classify(returncode, path: Path, mtime_before: float):
    """VERBATIM logic of the pre-fix classifier (mutation reference)."""
    try:
        fresh = path.stat().st_mtime > mtime_before
    except OSError:
        fresh = False
    receipt = json.loads(path.read_text(encoding="utf-8")) if fresh else None
    if returncode == 0:
        if receipt is not None and receipt.get("outcome") not in (None, "UPDATED"):
            return "FAILED"
        return "OK"
    if returncode == 1 and receipt and receipt.get("exit_code") == 1 \
            and receipt.get("outcome") in ("NO_ACTIVE_EVENTS", "NO_GAMES_SCHEDULED"):
        return f"SKIPPED_{receipt.get('outcome')}"
    return "FAILED"


def main() -> int:
    import refresh_line_movement_snapshots as lm
    with tempfile.TemporaryDirectory(prefix="qc_linemove_identity_") as td:
        base = Path(td)
        (base / "data/tracking").mkdir(parents=True)
        W = ("basketball_wnba", (0, "UPDATED", "own"))
        # I1 -- one directory, successive drives, identical mtimes on every write
        seq = [
            ((0, "UPDATED", "own"), 0, "OK"),
            # governed-only rule: a zero-event provider answer / an ungoverned no-game claim is a FAILURE
            ((1, "NO_ACTIVE_EVENTS", "own"), 2, "FAILED"),
            ((1, "NO_GAMES_SCHEDULED", "own"), 2, "FAILED"),
            ((0, "VALIDATION_FAILED", "own"), 2, "FAILED"),
            ((1, "SCHEDULE_UNAVAILABLE", "own"), 2, "FAILED"),
            ((1, "NO_ACTIVE_EVENTS", "own"), 2, "FAILED"),
            ((0, "UPDATED", "own"), 0, "OK"),
        ]
        for step, want_rc, want in seq:
            rc, mlb, _ = _drive(lm, base, {"baseball_mlb": step, W[0]: W[1]})
            check(rc == want_rc and want in mlb,
                  f"I1 identical-mtime receipt {step[1]} exit {step[0]} -> {want} (rc={rc})")
        mt = (base / "data/tracking/_last_game_lines_fetch_baseball_mlb.json").stat().st_mtime
        check(mt == FIXED_MTIME, "I1 every MLB receipt write had the SAME mtime (the old freshness test is blind)")
        # I2
        rc, mlb, _ = _drive(lm, base, {"baseball_mlb": (1, None, "own"), W[0]: W[1]})
        check(rc == 2 and "RUN_RECEIPT_MISMATCH" in mlb and "SKIPPED" not in mlb,
              "I2 child wrote nothing, an older receipt (previous token) remains -> RUN_RECEIPT_MISMATCH, failure")
        (base / "data/tracking/_last_game_lines_fetch_baseball_mlb.json").unlink()
        rc, mlb, _ = _drive(lm, base, {"baseball_mlb": (0, None, "own"), W[0]: W[1]})
        check(rc == 2 and "RUN_RECEIPT_MISSING" in mlb, "I2 no receipt at all, even with exit 0 -> RUN_RECEIPT_MISSING")
        rc, mlb, _ = _drive(lm, base, {"baseball_mlb": (1, "NO_ACTIVE_EVENTS", "other"), W[0]: W[1]})
        check(rc == 2 and "RUN_RECEIPT_MISMATCH" in mlb, "I2 another writer's benign receipt is never adopted")
        rc, mlb, _ = _drive(lm, base, {"baseball_mlb": (0, "UPDATED", "none"), W[0]: W[1]})
        check(rc == 2 and "RUN_RECEIPT_MISMATCH" in mlb, "I2 a tokenless legacy receipt never decides the outcome")

        # M -- the old mtime classifier on the same identical-mtime sequence misclassifies
        p = base / "data/tracking/_last_game_lines_fetch_baseball_mlb.json"
        _write(p, {"outcome": "UPDATED", "exit_code": 0})
        wrong = 0
        for rc_, outcome, want in ((1, "NO_ACTIVE_EVENTS", "SKIPPED_NO_ACTIVE_EVENTS"),
                                   (1, "NO_GAMES_SCHEDULED", "SKIPPED_NO_GAMES_SCHEDULED"),
                                   (0, "VALIDATION_FAILED", "FAILED")):
            before = p.stat().st_mtime
            _write(p, {"outcome": outcome, "exit_code": rc_})
            if old_mtime_classify(rc_, p, before) != want:
                wrong += 1
        check(wrong == 3, f"M the previous mtime classifier misclassifies all 3 identical-mtime receipts ({wrong}/3) "
                          "-- this QC fails against it")

    # I5 -- receipt-outcome contract (gate #2 finding #14) + governed-only no-game rule, classify_step direct
    from services import run_outcomes as ro
    check(ro.GOVERNED_SCHEDULE_CONTRACTS == {}, "I5 no schedule contract is governed on this branch (registry empty)")
    check(ro.BENIGN_LINES_NONPUBLISH == frozenset({ro.NO_GAMES_SCHEDULED}),
          "I5 benign lines non-publish = {NO_GAMES_SCHEDULED} only (NO_ACTIVE_EVENTS excluded)")
    with tempfile.TemporaryDirectory(prefix="qc_linemove_outcome_") as td:
        rp = Path(td) / "r.json"
        saved_rp = lm._receipt_path
        lm._receipt_path = lambda sport: rp
        T = "t" * 32
        try:
            cases = [
                ("exit 0, own receipt, outcome MISSING", 0, {"stage_run_id": T, "exit_code": 0}, "FAILED"),
                ("exit 0, own receipt, outcome None", 0, {"stage_run_id": T, "outcome": None, "exit_code": 0}, "FAILED"),
                ("exit 0, own receipt, UPDATED but exit_code MISSING", 0, {"stage_run_id": T, "outcome": "UPDATED"}, "FAILED"),
                ("exit 0, own receipt, UPDATED but exit_code 1", 0, {"stage_run_id": T, "outcome": "UPDATED", "exit_code": 1}, "FAILED"),
                ("exit 0, own receipt, UPDATED + exit_code 0", 0, {"stage_run_id": T, "outcome": "UPDATED", "exit_code": 0}, "OK"),
                ("exit 1, own NO_ACTIVE_EVENTS", 1, {"stage_run_id": T, "outcome": "NO_ACTIVE_EVENTS", "exit_code": 1}, "FAILED"),
                ("exit 1, own NO_GAMES_SCHEDULED, no contract", 1, {"stage_run_id": T, "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1}, "FAILED"),
                ("exit 1, own NO_GAMES_SCHEDULED, ungoverned contract", 1,
                 {"stage_run_id": T, "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1, "schedule_contract": "qc.fixture"}, "FAILED"),
            ]
            for name, rc_, rec, want in cases:
                rp.write_text(json.dumps(rec), encoding="utf-8")
                got = lm.classify_step(rc_, "baseball_mlb", T)[0]
                check(got == want, f"I5 {name} -> {want} (got {got})")
            # positive control: a GOVERNED contract (fixture-only registration) is the ONLY benign path
            ro.GOVERNED_SCHEDULE_CONTRACTS["qc.fixture"] = "QC fixture only"
            try:
                rp.write_text(json.dumps({"stage_run_id": T, "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1,
                                          "schedule_contract": "qc.fixture"}), encoding="utf-8")
                got = lm.classify_step(1, "baseball_mlb", T)[0]
                check(got == "SKIPPED_NO_GAMES_SCHEDULED", f"I5 governed NO_GAMES_SCHEDULED -> benign skip (got {got})")
                rp.write_text(json.dumps({"stage_run_id": T, "outcome": "NO_ACTIVE_EVENTS", "exit_code": 1,
                                          "schedule_contract": "qc.fixture"}), encoding="utf-8")
                got = lm.classify_step(1, "baseball_mlb", T)[0]
                check(got == "FAILED", f"I5 NO_ACTIVE_EVENTS is never benign, even naming a governed contract (got {got})")
                rp.write_text(json.dumps({"stage_run_id": T, "outcome": "NO_GAMES_SCHEDULED", "exit_code": 2,
                                          "schedule_contract": "qc.fixture"}), encoding="utf-8")
                got = lm.classify_step(2, "baseball_mlb", T)[0]
                check(got == "FAILED", f"I5 a governed claim never launders exit 2 (got {got})")
            finally:
                ro.GOVERNED_SCHEDULE_CONTRACTS.pop("qc.fixture", None)
        finally:
            lm._receipt_path = saved_rp

    # I3 -- fetch_game_lines stamps the caller's token
    import fetch_game_lines as fg
    from services import run_receipts as rr
    with tempfile.TemporaryDirectory(prefix="qc_linemove_stamp_") as td:
        saved_base, saved_env = fg.BASE_DIR, os.environ.get(rr.STAGE_RUN_ENV)
        fg.BASE_DIR = Path(td)
        try:
            for val, want in (("a" * 32, "a" * 32), (None, None), ("NOT-SAFE", None)):
                if val is None:
                    os.environ.pop(rr.STAGE_RUN_ENV, None)
                else:
                    os.environ[rr.STAGE_RUN_ENV] = val
                with contextlib.redirect_stdout(io.StringIO()):
                    fg._write_lines_receipt("baseball_mlb", {"outcome": "UPDATED", "exit_code": 0})
                got = json.loads(fg.lines_receipt_path("baseball_mlb").read_text(encoding="utf-8")).get("stage_run_id", "ABSENT")
                check(got == want, f"I3 fetch_game_lines receipt stage_run_id for env {val!r} -> {want!r} (got {got!r})")
        finally:
            fg.BASE_DIR = saved_base
            if saved_env is None:
                os.environ.pop(rr.STAGE_RUN_ENV, None)
            else:
                os.environ[rr.STAGE_RUN_ENV] = saved_env

    # I4
    src = (HERE / "refresh_line_movement_snapshots.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    check(not ({"st_mtime", "_mtime", "getmtime"} & names), "I4 the line-movement runner reads no mtime")

    print("=" * 64)
    print("QC: LINE-MOVEMENT RECEIPT IDENTITY (run token, never mtime)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
