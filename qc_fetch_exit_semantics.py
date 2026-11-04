"""QC: an UNCONFIGURED_SPORT refusal (fetcher exit 2, `OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT`)
is a HARD failure on every reporting surface, and configured exit semantics are unchanged (safeguard A).

Drives the REAL step runners with real subprocess children (stub children for exit 0 / 1, and the REAL
fetch_game_lines.py / fetch_player_props.py refusing basketball_ncaab for exit 2 -- it refuses before any
request or write):
  L. bk-linemove  refresh_line_movement_snapshots.main(): exit 0 -> OK, exit 1 -> OK ("no new rows", the
     existing contract), exit 2 -> FAILED + runner exit 1.
  D. bk-daily     run_daily.main() (temp BASE_DIR/LOG_DIR; network QCs + run status mapped to stubs): exit 0
     -> PASS; exit 1 in season -> FAIL, off-season -> SKIP (off-season) (existing); exit 2 UNCONFIGURED_SPORT
     -> FAIL in AND out of season, with and without --continue-on-error; runner exit 1; the structured
     Last_Operator_Summary lists the step in failed_steps with blocking_failure=true.
  S. run status   generate_run_status._operator_signals / build_run_status over that summary -> a degraded
     reason naming the step; overall is never GREEN/WATCH.
  P. props parents services.run_outcomes.classify_props_child / props_step_outcome: exit 2 is
     VALIDATION_FAILED (alerting) even when a STALE benign receipt (events_found=0) sits on disk; exit 0/1
     classification unchanged. refresh_football_props.main() with an exit-2 child -> VALIDATION_FAILED,
     DEGRADED, exit 1. refresh_football_line_movement.main() propagates exit 2.
Run via qc_offline.py; no provider request (the exit-2 children refuse before the network).
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
import refresh_football_line_movement as rflm  # noqa: E402
import refresh_football_props as rfp  # noqa: E402
import refresh_line_movement_snapshots as rlm  # noqa: E402
import run_daily as rd  # noqa: E402
from services import run_outcomes as ro  # noqa: E402

PY = sys.executable
_OK = 0
_FAIL = 0
MATRIX: list[str] = []


def ok(cond, label):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print(f"  [ok] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def stub(root: Path, name: str, code: int, text: str = "") -> list[str]:
    p = root / f"{name}.py"
    p.write_text(f"import sys\nprint({text!r})\nsys.exit({code})\n", encoding="utf-8")
    return [PY, str(p)]


def real_refusal(fetcher: str) -> list[str]:
    return [PY, str(REPO / fetcher), "--sport", "basketball_ncaab", "--api-key", "qc-offline-dummy"]


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
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(*a, **k)
    return rc, out.getvalue()


def children(root: Path) -> dict:
    return {
        "exit 0 (updated)": stub(root, "c0", 0, "Saved 3 rows"),
        "exit 1 (no new rows)": stub(root, "c1", 1, "No new game-line rows were fetched. Preserving existing CSV files"),
        "exit 2 UNCONFIGURED_SPORT (stub)": stub(
            root, "c2", 2, "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT sport=basketball_ncaab"),
        "exit 2 UNCONFIGURED_SPORT (real fetch_game_lines)": real_refusal("fetch_game_lines.py"),
    }


# ---- L. bk-linemove -------------------------------------------------------------------------------------
def check_linemove():
    print("--- L. bk-linemove: refresh_line_movement_snapshots.main() ---")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for label, cmd in children(root).items():
            with patched(rlm, STEPS=[("MLB game lines", cmd, 120)]):
                rc, out = quiet(rlm.main)
            failed = "FAILED" in out
            want_fail = label.startswith("exit 2")
            MATRIX.append(f"linemove   | {label:52s} | step={'FAILED' if failed else 'OK':6s} runner_exit={rc}")
            ok(failed == want_fail and rc == (1 if want_fail else 0),
               f"linemove {label}: step {'FAILED' if failed else 'OK'}, runner exit {rc} "
               f"(expected {'FAILED/1' if want_fail else 'OK/0'})")
            if want_fail:
                ok("exit 2" in out and "All line-movement snapshots captured" not in out,
                   f"linemove {label}: reported as a failure (never 'captured' / 'no new rows')")


# ---- D + S. bk-daily + run status ------------------------------------------------------------------------
def run_daily_case(root: Path, label: str, cmd: list[str], active: set, continue_on_error: bool):
    tmp = Path(tempfile.mkdtemp(dir=root))
    ok_stub = stub(tmp, "okstep", 0, "ok")

    def fake_python(script, *args):   # network QCs + run status -> a passing stub; nothing else is called
        return ok_stub

    steps = [(label, cmd, 120), ("Power ratings", ok_stub, 60)]
    argv = ["run_daily.py", "--sports", "wnba", "--skip-edge", "--skip-scorecards"]
    if continue_on_error:
        argv.append("--continue-on-error")
    saved_argv = sys.argv[:]
    sys.argv = argv
    try:
        with patched(rd, BASE_DIR=tmp, LOG_DIR=tmp / "logs", _python=fake_python,
                     _active_refresh_steps=lambda sports: list(steps), active_sports=lambda: set(active),
                     nfl_preseason_active=lambda: True):
            rc, out = quiet(rd.main)
    finally:
        sys.argv = saved_argv
    summary = json.loads((tmp / "data" / "tracking" / "Last_Operator_Summary.json").read_text(encoding="utf-8"))
    status = next((s["status"] for s in summary["steps"] if s["label"] == label), None)
    # Isolate the operator signal: every artifact row reads FRESH and the odds-family rows are neutral, so
    # `overall` moves ONLY with the operator summary (GREEN unless the summary carries a failure).
    with patched(grs, OPERATOR_SUMMARY_PATH=tmp / "data" / "tracking" / "Last_Operator_Summary.json",
                 _classify=lambda *a, **k: "FRESH", _odds_family_signals=lambda: ([], [])):
        reasons, _info = grs._operator_signals()
        overall = grs.build_run_status()["overall"]
    return rc, status, summary, reasons, overall


def check_run_daily():
    print("--- D/S. bk-daily: run_daily.main() step mapping + Last_Operator_Summary + run status ---")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for child, cmd in children(root).items():
            for step_label, active, season in (("WNBA game lines", {"WNBA"}, "in-season"),
                                               ("WNBA game lines", set(), "off-season"),
                                               ("NFL preseason lines", set(), "off-season (window open)"),
                                               ("Football line movement", set(), "cross-sport")):
                for coe in (False, True):
                    rc, status, summary, reasons, overall = run_daily_case(root, step_label, cmd, active, coe)
                    code = int(child.split()[1])
                    if code == 0:
                        want = "PASS"
                    elif code == 2:
                        want = "FAIL"
                    else:   # exit 1: existing season-gate contract
                        want = "SKIP (off-season)" if step_label != "Football line movement" and not active else "FAIL"
                    tag = f"run_daily [{step_label} | {season}{' | --continue-on-error' if coe else ''}] {child}"
                    MATRIX.append(f"run_daily  | {child:52s} | {step_label} {season}{' coe' if coe else ''}: "
                                  f"step={status} runner_exit={rc} run_status={overall}")
                    ok(status == want, f"{tag}: step {status!r} (expected {want!r})")
                    ok(rc == (1 if want == "FAIL" else 0), f"{tag}: runner exit {rc}")
                    if want == "FAIL":
                        ok(summary["blocking_failure"] is True and step_label in summary["failed_steps"],
                           f"{tag}: Last_Operator_Summary blocking_failure + failed_steps={summary['failed_steps']}")
                        ok(any(step_label in r for r in reasons) and overall == "DEGRADED",
                           f"{tag}: run status degraded reason names the step; overall {overall} (never GREEN/WATCH)")
                    else:
                        ok(overall == "GREEN" and not reasons,
                           f"{tag}: run status unchanged by this step ({overall}, reasons={reasons})")
                    if code == 2:
                        ok(status not in ("PASS",) and not status.startswith("SKIP") and not status.startswith("WARN"),
                           f"{tag}: never PASS / SKIP / WARN")


# ---- P. props classification + parents -------------------------------------------------------------------
def check_props_parents():
    print("--- P. props child classification + football parents ---")
    stale_benign = {"events_found": 0, "rows_fetched": 0, "provider_error_count": 0,
                    "shape_proves_no_markets_posted": False}
    proven = {"events_found": 3, "rows_fetched": 0, "provider_error_count": 0,
              "shape_proves_no_markets_posted": True}
    for receipt, name in ((None, "no receipt"), (stale_benign, "stale NO_ACTIVE_EVENTS receipt"),
                          (proven, "stale NO_MARKETS_POSTED receipt")):
        for adv in (False, True):
            o, d = ro.classify_props_child(2, adv, receipt)
            ok(o == ro.VALIDATION_FAILED and ro.is_alerting(o) and "UNCONFIGURED_SPORT" in d,
               f"classify_props_child(exit 2, advanced={adv}, {name}) -> {o} (alerting)")
            MATRIX.append(f"props-cls  | exit 2, {name}, advanced={adv} -> {o}")
    # exit 0 / 1 unchanged (the pre-change contract)
    for args, want in (((0, True, None), ro.UPDATED), ((0, False, None), ro.STALE), ((1, False, None), ro.VALIDATION_FAILED),
                       ((1, False, stale_benign), ro.NO_ACTIVE_EVENTS), ((1, False, proven), ro.NO_MARKETS_POSTED),
                       ((0, True, {"events_found": 2, "rows_fetched": 9}), ro.UPDATED)):
        o, _ = ro.classify_props_child(*args)
        ok(o == want, f"classify_props_child{args[:2]} receipt={'yes' if args[2] else 'none'} -> {o} (unchanged {want})")
        MATRIX.append(f"props-cls  | exit {args[0]}, advanced={args[1]}, receipt={'yes' if args[2] else 'none'} -> {o}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "data" / "tracking").mkdir(parents=True)
        (root / "data" / "props").mkdir(parents=True)
        for slug in ("americanfootball_nfl", "americanfootball_ncaaf"):   # stale BENIGN receipts on disk
            (root / "data" / "tracking" / f"_last_props_fetch_{slug}.json").write_text(json.dumps(stale_benign))
        steps = [("nfl_player_props", real_refusal("fetch_player_props.py"), 120, "americanfootball_nfl",
                  root / "data" / "props" / "NFL_Props.csv"),
                 ("ncaaf_player_props", stub(root, "p2", 2, "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT"),
                  120, "americanfootball_ncaaf", root / "data" / "props" / "NCAAF_Props.csv")]
        saved_key = os.environ.get("ODDS_API_KEY")
        os.environ["ODDS_API_KEY"] = "qc-offline-dummy"
        try:
            with patched(rfp, BASE_DIR=root, STEPS=steps):
                rc, out = quiet(rfp.main)
        finally:
            if saved_key is None:
                os.environ.pop("ODDS_API_KEY", None)
            else:
                os.environ["ODDS_API_KEY"] = saved_key
        sidecar = json.loads((root / "data" / "tracking" / "_child_outcomes_football_props.json").read_text())
        ok(rc == 1 and set(sidecar["outcomes"].values()) == {ro.VALIDATION_FAILED} and sidecar["degraded"],
           f"refresh_football_props: exit-2 children with STALE benign receipts -> {sidecar['outcomes']}, DEGRADED, exit {rc}")
        MATRIX.append(f"fb-props   | exit 2 (real + stub) w/ stale benign receipts -> {sorted(set(sidecar['outcomes'].values()))} parent_exit={rc}")

        with patched(rflm, STEPS=[("nfl_game_lines", real_refusal("fetch_game_lines.py"), 120)]):
            rc, out = quiet(rflm.main)
        ok(rc == 2 and "[FAIL] nfl_game_lines exited with code 2" in out,
           f"refresh_football_line_movement: real exit-2 child propagates as [FAIL] (parent exit {rc})")
        MATRIX.append(f"fb-lines   | exit 2 (real fetch_game_lines) -> parent_exit={rc}")


def main() -> int:
    print("=" * 80)
    print("QC: UNCONFIGURED_SPORT exit 2 is a hard failure on every runner/report surface (safeguard A)")
    print("=" * 80)
    check_linemove()
    check_run_daily()
    check_props_parents()
    print("--- exit-code matrix ---")
    for row in MATRIX:
        print("  " + row)
    print("=" * 80)
    print(f"RESULT: {_OK} ok, {_FAIL} FAIL")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
