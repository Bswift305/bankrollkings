"""
QC: end-to-end runner exit matrix (frozen semantics, owner 2026-11-07) -- NBA v6 + Safeguard A combined.

Every row is driven end to end through the REAL code:

    child (exit code + THIS run's receipt + output)
      -> runner classification          (refresh_line_movement_snapshots.classify_step / run_daily)
      -> runner process exit             (main() return value)
      -> systemd result                  (modelled from the prod units: bk-linemove SuccessExitStatus=1 => {0,1};
                                          bk-daily default => {0}; plus the hardened {0} for bk-linemove)
      -> Run Status                      (generate_run_status: _linemove_signals / _operator_signals -> overall)

Frozen semantics proven here:
  * UPDATED + integer exit 0 -> success (a bool / float / string exit_code is NOT 0);
  * a governed, independently sourced NO_GAMES_SCHEDULED -> the approved benign status (exit 0, GREEN);
  * NO_ACTIVE_EVENTS without governed schedule proof -> degraded failure;
  * unconfigured sport -> UNCONFIGURED_SPORT, child exit 2;
  * missing API key -> CONFIG_MISSING, child exit 2 (REAL fetch_game_lines, BASE_DIR redirected to a temp dir);
  * quota exhaustion -> BLOCKED_QUOTA, degraded failure (never a skip);
  * missing, blank, unknown or contradictory receipt outcome -> hard failure;
  * INVARIANT: no internal failure is ever reported as SUCCESS by systemd -- the line-movement runner exits only
    0 or 2, so SuccessExitStatus=1 cannot mask anything, and Run Status reads the runner's own summary.
Mutations (in-process monkeypatches, restored after) each re-run the matrix and must be CAUGHT.

Offline: no network, no production paths (every write is under a TemporaryDirectory). Run via
    py -3 qc_offline.py qc_runner_exit_matrix.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import generate_run_status as grs  # noqa: E402
import refresh_line_movement_snapshots as rlm  # noqa: E402
import run_daily as rd  # noqa: E402
from services import run_outcomes as ro  # noqa: E402
from services.run_receipts import STAGE_RUN_ENV  # noqa: E402

PY = sys.executable
SPORT = "basketball_wnba"
LINEMOVE_PROD = frozenset({0, 1})   # bk-linemove.service: SuccessExitStatus=1 (+ default 0)
LINEMOVE_HARDENED = frozenset({0})  # the same unit without SuccessExitStatus=1
BK_DAILY = frozenset({0})           # bk-daily.service default
QC_CONTRACT = "qc.matrix_schedule_contract"   # injected only inside this QC; the real registry is empty

_OK = 0
_FAIL = 0
ROWS: list[str] = []


def ok(cond, label, sink=None):
    global _OK, _FAIL
    if sink is not None:
        sink.append(bool(cond))
        return
    if cond:
        _OK += 1
        print(f"  [ok] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def systemd(code, success):
    return "SUCCESS" if code in success else "FAILED"


@contextlib.contextmanager
def patched(mod, **kw):
    saved = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


# ---- children ------------------------------------------------------------------------------------------
def receipt_child(root: Path, name: str, code: int, receipt, text: str = "") -> list[str]:
    """A child that writes `receipt` (with TOKEN -> this run's token, OTHER -> another token) to the runner's
    receipt path for SPORT, prints `text`, and exits `code`. receipt=None writes nothing; a str is written raw."""
    rp = root / "data" / "tracking" / f"_last_game_lines_fetch_{SPORT}.json"
    p = root / f"{name}.py"
    p.write_text(
        "import json, os, sys, pathlib\n"
        f"rp = pathlib.Path({str(rp)!r}); rp.parent.mkdir(parents=True, exist_ok=True)\n"
        f"spec = {json.dumps(receipt)!r}\n"
        f"tok = os.environ.get({STAGE_RUN_ENV!r})\n"
        "if spec != 'null':\n"
        "    obj = json.loads(spec)\n"
        "    if isinstance(obj, dict):\n"
        "        if obj.get('stage_run_id') == 'TOKEN': obj['stage_run_id'] = tok\n"
        "        elif obj.get('stage_run_id') == 'OTHER': obj['stage_run_id'] = 'f' * 32\n"
        "        rp.write_text(json.dumps(obj), encoding='utf-8')\n"
        "    else:\n"
        "        rp.write_text(obj, encoding='utf-8')\n"
        f"print({text!r})\n"
        f"sys.exit({code})\n", encoding="utf-8")
    return [PY, str(p)]


def real_fetcher_child(root: Path, name: str, argv: list[str], drop_key: bool) -> list[str]:
    """The REAL fetch_game_lines.main(), its BASE_DIR redirected to `root` (no repo / production writes)."""
    p = root / f"{name}.py"
    p.write_text(
        "import os, sys, pathlib\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        + ("for k in ('ODDS_API_KEY', 'THE_ODDS_API_KEY'): os.environ.pop(k, None)\n" if drop_key else "")
        + "import fetch_game_lines as fg\n"
        f"fg.BASE_DIR = pathlib.Path({str(root)!r})\n"
        f"sys.exit(fg.main({argv!r}))\n", encoding="utf-8")
    return [PY, str(p)]


U = {"stage_run_id": "TOKEN", "outcome": "UPDATED", "exit_code": 0}
# (key, child exit, receipt, output, governed contract injected?, expected runner status prefix, want success?)
LINEMOVE_CASES = [
    ("UPDATED + int exit 0", 0, U, "Saved 3 rows", False, "OK", True),
    ("UPDATED, exit_code missing", 0, {"stage_run_id": "TOKEN", "outcome": "UPDATED"}, "", False, "FAILED", False),
    ("UPDATED, exit_code True (bool)", 0, {**U, "exit_code": True}, "", False, "FAILED", False),
    ("UPDATED, exit_code 0.0 (float)", 0, {**U, "exit_code": 0.0}, "", False, "FAILED", False),
    ("UPDATED, exit_code '0' (string)", 0, {**U, "exit_code": "0"}, "", False, "FAILED", False),
    ("outcome MISSING", 0, {"stage_run_id": "TOKEN", "exit_code": 0}, "", False, "FAILED", False),
    ("outcome BLANK ''", 0, {**U, "outcome": ""}, "", False, "FAILED", False),
    ("outcome None", 0, {**U, "outcome": None}, "", False, "FAILED", False),
    ("outcome UNKNOWN word", 0, {**U, "outcome": "SOME_NEW_OUTCOME"}, "", False, "FAILED", False),
    ("contradictory: exit 0, receipt exit_code 1", 0, {**U, "exit_code": 1}, "", False, "FAILED", False),
    ("contradictory: exit 1, receipt UPDATED", 1, {**U, "exit_code": 1}, "", False, "FAILED", False),
    ("contradictory: exit 1, receipt NGS exit_code 0", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_GAMES_SCHEDULED", "exit_code": 0, "schedule_contract": QC_CONTRACT},
     "", True, "FAILED", False),
    ("NO_ACTIVE_EVENTS (zero provider events)", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_ACTIVE_EVENTS", "exit_code": 1}, "", False, "FAILED", False),
    ("NO_ACTIVE_EVENTS naming a governed contract", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_ACTIVE_EVENTS", "exit_code": 1, "schedule_contract": QC_CONTRACT},
     "", True, "FAILED", False),
    ("NO_GAMES_SCHEDULED, no contract", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1}, "", False, "FAILED", False),
    ("NO_GAMES_SCHEDULED, ungoverned contract", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1, "schedule_contract": "odds_api_empty"},
     "", False, "FAILED", False),
    ("NO_GAMES_SCHEDULED, GOVERNED contract", 1,
     {"stage_run_id": "TOKEN", "outcome": "NO_GAMES_SCHEDULED", "exit_code": 1, "schedule_contract": QC_CONTRACT},
     "", True, "SKIPPED_NO_GAMES_SCHEDULED", True),
    ("governed NGS but child exit 2 (no laundering)", 2,
     {"stage_run_id": "TOKEN", "outcome": "NO_GAMES_SCHEDULED", "exit_code": 2, "schedule_contract": QC_CONTRACT},
     "", True, "FAILED", False),
    ("SCHEDULE_UNAVAILABLE", 1, {"stage_run_id": "TOKEN", "outcome": "SCHEDULE_UNAVAILABLE", "exit_code": 1},
     "", False, "FAILED", False),
    ("PROVIDER_ERROR", 1, {"stage_run_id": "TOKEN", "outcome": "PROVIDER_ERROR", "exit_code": 1}, "", False, "FAILED", False),
    ("receipt MISSING, exit 0", 0, None, "Saved 3 rows", False, "RUN_RECEIPT_MISSING", False),
    ("receipt torn (not JSON)", 0, '{"stage_run_id": "TOK', "", False, "RUN_RECEIPT_MISSING", False),
    ("receipt not an object", 0, "[1, 2]", "", False, "RUN_RECEIPT_MISSING", False),
    ("another run's token", 0, {**U, "stage_run_id": "OTHER"}, "", False, "RUN_RECEIPT_MISMATCH", False),
    ("tokenless receipt", 0, {"outcome": "UPDATED", "exit_code": 0}, "", False, "RUN_RECEIPT_MISMATCH", False),
    ("UNCONFIGURED_SPORT marker at exit 0 (contradictory)", 0, U,
     "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT", False, "UNCONFIGURED_SPORT", False),
    ("CONFIG_MISSING marker at exit 0 (contradictory)", 0, U,
     "OUTCOME: CONFIG_MISSING reason_code=CONFIG_MISSING", False, "CONFIG_MISSING", False),
    ("BLOCKED_QUOTA (latched, no request)", 3, None,
     "OUTCOME: BLOCKED_QUOTA reason_code=BLOCKED_QUOTA provider=odds_api latched=1", False, "BLOCKED_QUOTA", False),
    ("BLOCKED_QUOTA marker at exit 1", 1, {"stage_run_id": "TOKEN", "outcome": "PROVIDER_ERROR", "exit_code": 1},
     "OUTCOME: BLOCKED_QUOTA reason_code=BLOCKED_QUOTA", False, "BLOCKED_QUOTA", False),
    ("hard exit 137 (signal-like)", 137, {**U, "exit_code": 137}, "", False, "FAILED", False),
]


def run_linemove(root: Path, cmd: list[str], inject: bool, timeout: int = 60):
    tracking = root / "data" / "tracking"
    for f in (tracking / f"_last_game_lines_fetch_{SPORT}.json", tracking / rlm.SUMMARY_NAME):
        if f.exists():
            f.unlink()
    ctx = patched(ro, GOVERNED_SCHEDULE_CONTRACTS={QC_CONTRACT: "QC-only"}) if inject else contextlib.nullcontext()
    with ctx, patched(rlm, BASE_DIR=root, STEPS=[("WNBA game lines", cmd, timeout, SPORT)]):
        rc, out = quiet(rlm.main)
    summary_path = tracking / rlm.SUMMARY_NAME
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    with patched(grs, LINEMOVE_SUMMARY_PATH=summary_path, _classify=lambda *a, **k: "FRESH",
                 _odds_family_signals=lambda: ([], []), _operator_signals=lambda: ([], {})):
        reasons, _info = grs._linemove_signals()
        overall = grs.build_run_status()["overall"]
    step = (summary.get("steps") or [{}])[0]
    return rc, out, summary, step, reasons, overall


def linemove_matrix(sink=None):
    """Drive every bk-linemove row; with `sink` collect pass/fail booleans silently (mutation mode)."""
    with tempfile.TemporaryDirectory(prefix="qc_runner_matrix_") as td:
        root = Path(td)
        cases = [(k, c, receipt_child(root, f"c{i}", c, r, t), inj, want, succ)
                 for i, (k, c, r, t, inj, want, succ) in enumerate(LINEMOVE_CASES)]
        cases.append(("REAL fetch_game_lines: unconfigured sport", 2,
                      real_fetcher_child(root, "real_unconf", ["--sport", "basketball_ncaab", "--api-key", "qc-x"], False),
                      False, "UNCONFIGURED_SPORT", False))
        cases.append(("REAL fetch_game_lines: missing API key", 2,
                      real_fetcher_child(root, "real_nokey", ["--sport", SPORT], True),
                      False, "CONFIG_MISSING", False))
        sleeper = root / "sleeper.py"
        sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        timeouts = [("child timeout", None, [PY, str(sleeper)], False, "FAILED", False)]
        for key, child_exit, cmd, inject, want, want_success in cases + timeouts:
            rc, out, summary, step, reasons, overall = run_linemove(
                root, cmd, inject, timeout=2 if key == "child timeout" else 60)
            status = step.get("status", "")
            sd_prod, sd_hard = systemd(rc, LINEMOVE_PROD), systemd(rc, LINEMOVE_HARDENED)
            if sink is None:
                ROWS.append(f"linemove | {key:46s} | child={child_exit!s:>4} status={status:28s} runner_exit={rc} "
                            f"systemd(prod)={sd_prod:7s} systemd(hardened)={sd_hard:7s} run_status={overall}")
            tag = f"linemove [{key}]"
            ok(status.startswith(want), f"{tag}: runner status {status!r} (expected {want})", sink)
            ok(rc in (0, 2), f"{tag}: runner exit {rc} is 0 or 2 -- never 1", sink)
            if want_success:
                ok(rc == 0 and sd_prod == "SUCCESS" and sd_hard == "SUCCESS" and overall == "GREEN" and not reasons,
                   f"{tag}: exit 0 -> systemd SUCCESS, Run Status GREEN ({rc}, {overall}, {reasons})", sink)
            else:
                ok(rc == 2 and sd_prod == "FAILED" and sd_hard == "FAILED",
                   f"{tag}: exit {rc} -> systemd FAILED under SuccessExitStatus=1 too (never a hidden failure)", sink)
                ok(overall == "DEGRADED" and any("line-movement" in r for r in reasons),
                   f"{tag}: Run Status DEGRADED with a line-movement reason ({overall}, {reasons})", sink)
                ok("All line-movement snapshots captured" not in out, f"{tag}: never prints 'captured'", sink)
            if key == "REAL fetch_game_lines: missing API key":
                rp = root / "data" / "tracking" / f"_last_game_lines_fetch_{SPORT}.json"
                rec = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
                ok(rec.get("outcome") == "CONFIG_MISSING" and rec.get("exit_code") == 2 and rec.get("published") is False
                   and "network_requests=0" in out,
                   f"{tag}: REAL child exits 2 with its own CONFIG_MISSING receipt, zero requests ({rec})", sink)
            # global invariant: systemd(prod) SUCCESS implies the runner saw no failure
            ok(not (sd_prod == "SUCCESS" and not (status == "OK" or status.startswith("SKIPPED_"))),
               f"{tag}: INVARIANT no failure reads SUCCESS under SuccessExitStatus=1", sink)


def bk_daily_matrix(sink=None):
    """bk-daily: run_daily step -> exit -> systemd {0} -> Run Status, for the frozen typed failures."""
    import qc_fetch_exit_semantics as fes   # reuse Safeguard A's run_daily harness (no main() on import)
    specs = [
        ("CONFIG_MISSING child exit 2", 2, "OUTCOME: CONFIG_MISSING reason_code=CONFIG_MISSING key=ODDS_API_KEY",
         "FAIL", "CONFIG_MISSING"),
        ("CONFIG_MISSING marker at exit 0 (contradictory)", 0, "OUTCOME: CONFIG_MISSING reason_code=CONFIG_MISSING",
         "FAIL", "CONFIG_MISSING"),
        ("BLOCKED_QUOTA latched exit 3", 3, "OUTCOME: BLOCKED_QUOTA reason_code=BLOCKED_QUOTA provider=cfbd latched=1",
         "FAIL", "BLOCKED_QUOTA"),
        ("legacy PROVIDER_QUOTA_EXHAUSTED exit 3", 3, "CFB refresh halted: PROVIDER_QUOTA_EXHAUSTED (CFBD).",
         "FAIL", "BLOCKED_QUOTA"),
        ("UNCONFIGURED_SPORT exit 2", 2, "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT", "FAIL",
         "UNCONFIGURED_SPORT"),
        ("plain success exit 0", 0, "ok", "PASS", ""),
    ]
    with tempfile.TemporaryDirectory(prefix="qc_runner_matrix_daily_") as td:
        root = Path(td)
        for i, (key, code, text, want, reason) in enumerate(specs):
            cmd = fes.stub(root, f"d{i}", code, text)
            for coe in (False, True):
                rc, summary, reasons, overall, _out = fes.run_daily_case(
                    root, lambda okc, c=cmd: [("CFB refresh", c, 60), ("Power ratings", okc, 60)], coe)
                entry = next((s for s in summary["steps"] if s["label"] == "CFB refresh"), {})
                tag = f"bk-daily [{key}{' | coe' if coe else ''}]"
                if sink is None:
                    ROWS.append(f"bk-daily | {key:46s}{' coe' if coe else '    '} | step={entry.get('status')} "
                                f"reason={entry.get('reason', '')!s:20s} runner_exit={rc} "
                                f"systemd(bk-daily)={systemd(rc, BK_DAILY)} run_status={overall}")
                ok(entry.get("status") == want and entry.get("reason", "") == reason,
                   f"{tag}: step {entry.get('status')} reason {entry.get('reason')} (expected {want} {reason})", sink)
                ok("SKIP" not in str(entry.get("status")), f"{tag}: never a SKIP", sink)
                if want == "PASS":
                    ok(rc == 0 and overall == "GREEN", f"{tag}: exit 0, GREEN ({rc}, {overall})", sink)
                else:
                    ok(rc == 2 and systemd(rc, BK_DAILY) == "FAILED" and overall == "DEGRADED",
                       f"{tag}: exit 2 -> systemd FAILED, Run Status DEGRADED ({rc}, {overall})", sink)
                if reason == "BLOCKED_QUOTA":
                    ok("CFB refresh" in summary.get("provider_exhausted_steps", [])
                       and "CFB refresh" in summary.get("failed_steps", []),
                       f"{tag}: listed as provider-exhausted AND failed", sink)


def mutation_caught(name, **patches_by_target) -> None:
    sink: list[bool] = []
    stacks = contextlib.ExitStack()
    with stacks:
        for target, kw in patches_by_target.items():
            stacks.enter_context(patched(target if not isinstance(target, str) else globals()[target], **kw))
        with contextlib.redirect_stdout(io.StringIO()):
            linemove_matrix(sink)
            bk_daily_matrix(sink)
    caught = not all(sink)
    ROWS.append(f"mutation | {name:46s} | {'CAUGHT' if caught else 'MISSED'} ({sink.count(False)} assertion(s) failed)")
    ok(caught, f"mutation {name}: CAUGHT ({sink.count(False)} failing assertions)")


def check_mutations():
    print("--- M. mutations (each must make the matrix fail) ---")
    lenient_int = lambda v, n: v == n  # noqa: E731  (True == 1, 0.0 == 0, ...)
    mutation_caught("M1 lenient exit_code (== instead of exact int)", **{"rlm": {"is_exact_int": lenient_int}})
    mutation_caught("M2 runner returns 1 on failure", **{"rlm": {"EXIT_HARD_FAILURE": 1}})
    mutation_caught("M3 typed markers ignored by the runner", **{"rlm": {"typed_hard_failure": lambda o: None}})
    mutation_caught("M4 any receipt claim governed", **{"rlm": {"governed_lines_nonpublish": lambda r: True}})
    mutation_caught("M5 NO_ACTIVE_EVENTS benign for lines",
                    **{"ro": {"BENIGN_LINES_NONPUBLISH": frozenset({"NO_ACTIVE_EVENTS", "NO_GAMES_SCHEDULED"}),
                              "GOVERNED_SCHEDULE_CONTRACTS": {"": "everything"}}})
    mutation_caught("M6 Run Status ignores the line-movement summary",
                    **{"grs": {"_linemove_signals": lambda now=None: ([], {})}})
    mutation_caught("M7 run_daily typed markers ignored",
                    **{"rd": {"typed_hard_failure": lambda o: None, "classify_step_exit":
                              lambda c, o: (ro.STEP_PASS, "") if c == 0 else (ro.STEP_FAIL, "HARD_FAILURE")}})
    mutation_caught("M8 run_daily exits 1 on failure", **{"rd": {"EXIT_HARD_FAILURE": 1}})


def main() -> int:
    print("=" * 96)
    print("QC: end-to-end runner exit matrix -- child receipt -> runner -> exit -> systemd -> Run Status")
    print("=" * 96)
    print(f"--- invariants: registry empty={ro.GOVERNED_SCHEDULE_CONTRACTS == {}}, "
          f"benign lines={sorted(ro.BENIGN_LINES_NONPUBLISH)} ---")
    ok(ro.GOVERNED_SCHEDULE_CONTRACTS == {}, "no schedule contract is governed in code (registry empty)")
    ok(ro.BENIGN_LINES_NONPUBLISH == frozenset({ro.NO_GAMES_SCHEDULED}), "benign lines non-publish = NO_GAMES_SCHEDULED only")
    ok(ro.NO_ACTIVE_EVENTS in ro.ALERTING and {ro.CONFIG_MISSING, ro.BLOCKED_QUOTA} <= ro.ALERTING,
       "NO_ACTIVE_EVENTS, CONFIG_MISSING, BLOCKED_QUOTA are ALERTING")
    print("--- L. bk-linemove ---")
    linemove_matrix()
    print("--- D. bk-daily ---")
    bk_daily_matrix()
    check_mutations()
    print("--- matrix ---")
    for r in ROWS:
        print("  " + r)
    print("=" * 96)
    print(f"RESULT: {_OK} ok, {_FAIL} FAIL")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
