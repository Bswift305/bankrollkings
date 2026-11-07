"""QC: runner exit semantics (Safeguard A) + the OFF-SEASON / NO-GAME owner decision of 2026-11-04.

Portable runner contract (owner decision): exit 0 = success; exit 1 = ONLY the benign "no new rows /
last-known-good preserved" outcome AND (2026-11-04) only when that benign cause is GOVERNED; exit >=2 = hard
failure. Systemd is modelled from the production units (read-only SSM): bk-linemove.service
SuccessExitStatus=1 => {0, 1} read SUCCESS; bk-daily.service default => {0}. A hard failure must NEVER exit
0 or 1 from a runner.

Owner decision 2026-11-04 (this QC's matrix):
  governed off-season   SKIPPED_OFF_SEASON only from a calendar in run_outcomes.GOVERNED_SEASON_CALENDARS,
                        decided BEFORE any provider call -> skip with ZERO provider calls (proven by a
                        TRIPWIRE child that records any invocation and exits 99)
  authoritative no-game NO_GAMES_SCHEDULED only from a contract in GOVERNED_SCHEDULE_CONTRACTS -> governed
                        benign result (the registry is EMPTY on this branch; the QC injects a synthetic one)
  UNCONFIGURED_SPORT    hard failure (exit 2) in and out of season, with and without --continue-on-error
  empty rows / provider error / unclassified non-zero / ungoverned claim -> FAILURE (degraded), never SKIP
                        or OK, even when the sport's props file is empty ("off-season" by the old heuristic)

Surfaces driven for real (real subprocess children; the exit-2 children include the REAL fetch_game_lines /
fetch_player_props refusing basketball_ncaab before any request or write):
  L. bk-linemove  refresh_line_movement_snapshots.main()
  D. bk-daily     run_daily.main() (temp BASE_DIR/LOG_DIR; network QCs + run status mapped to stubs), with and
                  without --continue-on-error; Last_Operator_Summary failed_steps / governed_skips
  S. run status   generate_run_status._operator_signals / build_run_status / _odds_family_signals
  P. props        services.run_outcomes.classify_props_child + refresh_football_props parent
  R. chain        refresh_football_line_movement / refresh_nba_daily / refresh_mlb_daily / refresh_wnba_daily,
                  runner_exit_for_child; run_bk_edge_engine_pipeline; run_all_scorecards
Run via qc_offline.py; no provider request, no write outside temp dirs.
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import contextlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import generate_run_status as grs  # noqa: E402
import refresh_football_line_movement as rflm  # noqa: E402
import refresh_football_props as rfp  # noqa: E402
import refresh_line_movement_snapshots as rlm  # noqa: E402
import refresh_mlb_daily as rmlb  # noqa: E402
import refresh_nba_daily as rnba  # noqa: E402
import refresh_wnba_daily as rwnba  # noqa: E402
import run_all_scorecards as rsc  # noqa: E402
import run_bk_edge_engine_pipeline as redge  # noqa: E402
import run_daily as rd  # noqa: E402
import season_utils  # noqa: E402
from services import run_outcomes as ro  # noqa: E402

PY = sys.executable
# Production systemd success sets (read-only SSM, 2026-11-04). Units only propagate the runner's code.
LINEMOVE_SYSTEMD_SUCCESS = frozenset({0, 1})   # bk-linemove.service: SuccessExitStatus=1 (+ the default 0)
BK_DAILY_SYSTEMD_SUCCESS = frozenset({0})      # bk-daily.service: default; OnFailure=bk-daily-alert

QC_CONTRACT = "qc.synthetic_schedule_contract"   # injected ONLY inside this QC; never governed in code
GOV_CAL = season_utils.NFL_PRESEASON_CALENDAR_ID

_OK = 0
_FAIL = 0
MATRIX: list[str] = []


def systemd(code, success):
    return "SUCCESS" if code in success else "FAILED"


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


def tripwire(root: Path, name: str) -> tuple[list[str], Path]:
    """A child that stands in for a PROVIDER CALL: any invocation is recorded in a sentinel file and exits 99.
    A governed pre-run skip must leave the sentinel absent (zero provider calls, zero credits)."""
    sentinel = root / f"{name}.CALLED"
    p = root / f"{name}.py"
    p.write_text("import sys, pathlib\n"
                 f"pathlib.Path({str(sentinel)!r}).write_text('provider call made')\n"
                 "print('TRIPWIRE: provider call made')\nsys.exit(99)\n", encoding="utf-8")
    return [PY, str(p)], sentinel


def real_refusal(fetcher: str) -> list[str]:
    return [PY, str(REPO / fetcher), "--sport", "basketball_ncaab", "--api-key", "qc-offline-dummy"]


@contextlib.contextmanager
def patched(mod, **kw):
    saved = {k: getattr(mod, k) for k in kw if hasattr(mod, k)}
    missing = [k for k in kw if not hasattr(mod, k)]
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        for k in missing:
            delattr(mod, k)


@contextlib.contextmanager
def governed_contract():
    """Inject a synthetic governed schedule contract for the duration of a case (the real registry is empty)."""
    with patched(ro, GOVERNED_SCHEDULE_CONTRACTS={QC_CONTRACT: "QC-only synthetic authoritative schedule"}):
        yield


def quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(*a, **k)
    return rc, out.getvalue()


# (key, exit code, child text, needs injected governed contract, expected class)
#   class: PASS | GOV (governed benign) | FAIL
CHILD_SPECS = [
    ("exit 0 (updated)", 0, "Saved 3 rows", False, "PASS"),
    ("exit 1 empty rows (no claim)", 1,
     "No new game-line rows were fetched. Preserving existing CSV files", False, "FAIL"),
    ("exit 1 provider error (no claim)", 1,
     "ERROR: 500 Server Error\nNo new game-line rows were fetched. Preserving existing CSV files", False, "FAIL"),
    ("exit 1 governed NO_GAMES_SCHEDULED", 1,
     f"OUTCOME: NO_GAMES_SCHEDULED contract={QC_CONTRACT}", True, "GOV"),
    ("exit 1 UNGOVERNED NO_GAMES_SCHEDULED claim", 1,
     "OUTCOME: NO_GAMES_SCHEDULED contract=odds_api_events_empty", False, "FAIL"),
    ("exit 1 governed SKIPPED_OFF_SEASON (0 calls)", 1,
     f"OUTCOME: SKIPPED_OFF_SEASON calendar={GOV_CAL} provider_calls=0", False, "GOV"),
    ("exit 1 SKIPPED_OFF_SEASON after a provider call", 1,
     f"OUTCOME: SKIPPED_OFF_SEASON calendar={GOV_CAL} provider_calls=1", False, "FAIL"),
    ("exit 1 SKIPPED_OFF_SEASON ungoverned calendar", 1,
     "OUTCOME: SKIPPED_OFF_SEASON calendar=active_sports provider_calls=0", False, "FAIL"),
    ("exit 2 UNCONFIGURED_SPORT (stub)", 2,
     "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT sport=basketball_ncaab", False, "FAIL"),
    ("exit 3 (other failure, no marker)", 3, "Traceback: synthetic hard failure", False, "FAIL"),
    ("exit 3 + governed claim (cannot launder)", 3,
     f"OUTCOME: NO_GAMES_SCHEDULED contract={QC_CONTRACT}", True, "FAIL"),
    # frozen 2026-11-07: typed hard failures, never a skip
    ("exit 2 CONFIG_MISSING (missing API key)", 2,
     "OUTCOME: CONFIG_MISSING reason_code=CONFIG_MISSING key=ODDS_API_KEY network_requests=0", False, "FAIL"),
    ("exit 3 BLOCKED_QUOTA (latched, no request)", 3,
     "OUTCOME: BLOCKED_QUOTA reason_code=BLOCKED_QUOTA provider=cfbd network_requests=0 latched=1", False, "FAIL"),
    ("exit 3 legacy PROVIDER_QUOTA_EXHAUSTED text", 3,
     "CFB refresh halted: PROVIDER_QUOTA_EXHAUSTED (CFBD).", False, "FAIL"),
]


def children(root: Path) -> list[tuple[str, int, list[str], bool, str]]:
    out = []
    for i, (key, code, text, inject, want) in enumerate(CHILD_SPECS):
        out.append((key, code, stub(root, f"c{i}", code, text), inject, want))
    out.append(("exit 2 UNCONFIGURED_SPORT (real fetch_game_lines)", 2, real_refusal("fetch_game_lines.py"), False, "FAIL"))
    return out


def ctx(inject: bool):
    return governed_contract() if inject else contextlib.nullcontext()


# ---- C. the one classifier ------------------------------------------------------------------------------
def check_classifier():
    print("--- C. services.run_outcomes.classify_step_exit / governed registries ---")
    ok(ro.GOVERNED_SCHEDULE_CONTRACTS == {}, "no schedule contract is governed on this branch (registry empty)")
    ok(set(ro.GOVERNED_SEASON_CALENDARS) == {GOV_CAL},
       f"only the NFL preseason calendar is governed ({sorted(ro.GOVERNED_SEASON_CALENDARS)})")
    for key, code, text, inject, want in CHILD_SPECS:
        with ctx(inject):
            status, reason = ro.classify_step_exit(code, text)
        got = "PASS" if status == ro.STEP_PASS else ("FAIL" if status == ro.STEP_FAIL else "GOV")
        ok(got == want and (got != "GOV" or ro.is_governed_benign_status(status)),
           f"classify_step_exit {key} -> {status} {reason!r} (expected {want})")
        MATRIX.append(f"classify   | {key:52s} | {status} {reason}")
    # the empty-rows-off-season regression: no "SKIP (off-season)" exists in the vocabulary
    ok(not any("off-season" in s.lower() for s in (ro.STEP_PASS, ro.STEP_FAIL)) and ro.SKIPPED_OFF_SEASON in ro.BENIGN,
       "vocabulary: SKIPPED_OFF_SEASON is the only off-season state; no generic 'SKIP (off-season)'")
    ok(ro.NO_ACTIVE_EVENTS in ro.ALERTING and ro.is_alerting(ro.NO_ACTIVE_EVENTS),
       "NO_ACTIVE_EVENTS (provider listed zero events) is ALERTING, not a governed no-game result")
    ok(ro.is_alerting("SOME_UNCLASSIFIED_WORD"), "is_alerting fails closed on an unknown outcome word")


# ---- L. bk-linemove -------------------------------------------------------------------------------------
def check_linemove():
    print("--- L. bk-linemove: refresh_line_movement_snapshots.main() ---")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for key, code, cmd, inject, want in children(root):
            with ctx(inject), patched(rlm, STEPS=[("WNBA game lines", cmd, 120)]):
                rc, out = quiet(rlm.main)
            failed = "FAILED" in out
            want_fail = want == "FAIL"
            sd = systemd(rc, LINEMOVE_SYSTEMD_SUCCESS)
            MATRIX.append(f"linemove   | {key:52s} | step={'FAILED' if failed else 'OK':6s} runner_exit={rc} "
                          f"systemd(SuccessExitStatus=1)={sd}")
            ok(failed == want_fail and rc == (2 if want_fail else 0),
               f"linemove {key}: step {'FAILED' if failed else 'OK'}, runner exit {rc} "
               f"(expected {'FAILED/2' if want_fail else 'OK/0'})")
            if want_fail:
                ok(rc >= 2 and sd == "FAILED" and "All line-movement snapshots captured" not in out,
                   f"linemove {key}: hard failure exit {rc} is NOT 0/1 -> bk-linemove reads FAILED, never 'captured'")
            else:
                ok(sd == "SUCCESS", f"linemove {key}: systemd reads SUCCESS")


# ---- D + S. bk-daily + run status ------------------------------------------------------------------------
def run_daily_case(root: Path, steps_fn, continue_on_error: bool, preseason_open: bool = True):
    tmp = Path(tempfile.mkdtemp(dir=root))
    ok_stub = stub(tmp, "okstep", 0, "ok")

    def fake_python(script, *args):   # network QCs + run status -> a passing stub; nothing else is called
        return ok_stub

    steps = steps_fn(ok_stub)
    argv = ["run_daily.py", "--sports", "wnba", "--skip-edge", "--skip-scorecards"]
    if continue_on_error:
        argv.append("--continue-on-error")
    saved_argv = sys.argv[:]
    sys.argv = argv
    # Worst case for the OLD heuristic: every sport reads "off-season" (empty props). Patched on season_utils
    # and -- if a regression re-imports it -- on run_daily too.
    no_props = {"active_sports": lambda: set()}
    try:
        with patched(season_utils, **no_props), patched(rd, **(no_props if hasattr(rd, "active_sports") else {})), \
                patched(rd, BASE_DIR=tmp, LOG_DIR=tmp / "logs", _python=fake_python,
                        _active_refresh_steps=lambda sports: list(steps),
                        nfl_preseason_active=lambda: preseason_open):
            rc, out = quiet(rd.main)
    finally:
        sys.argv = saved_argv
    summary = json.loads((tmp / "data" / "tracking" / "Last_Operator_Summary.json").read_text(encoding="utf-8"))
    # Isolate the operator signal: every artifact row reads FRESH and the odds-family rows are neutral, so
    # `overall` moves ONLY with the operator summary (GREEN unless the summary carries a failure).
    with patched(grs, OPERATOR_SUMMARY_PATH=tmp / "data" / "tracking" / "Last_Operator_Summary.json",
                 _classify=lambda *a, **k: "FRESH", _odds_family_signals=lambda: ([], [])):
        reasons, _info = grs._operator_signals()
        overall = grs.build_run_status()["overall"]
    return rc, summary, reasons, overall, out


def check_run_daily():
    print("--- D/S. bk-daily: run_daily.main() step mapping + Last_Operator_Summary + run status ---")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for key, code, cmd, inject, want in children(root):
            for step_label, season in (("WNBA game lines", "WNBA props empty (old 'off-season')"),
                                       ("MLB daily refresh", "MLB props empty (old 'off-season')"),
                                       ("Football line movement", "cross-sport")):
                for coe in (False, True):
                    with ctx(inject):
                        rc, summary, reasons, overall, _out = run_daily_case(
                            root, lambda okc, c=cmd, lbl=step_label: [(lbl, c, 120), ("Power ratings", okc, 60)], coe)
                    entry = next((s for s in summary["steps"] if s["label"] == step_label), {})
                    status = entry.get("status")
                    tag = f"run_daily [{step_label} | {season}{' | --continue-on-error' if coe else ''}] {key}"
                    MATRIX.append(f"run_daily  | {key:52s} | {step_label}{' coe' if coe else ''}: step={status} "
                                  f"reason={entry.get('reason', '')!s:28s} runner_exit={rc} "
                                  f"systemd(bk-daily)={systemd(rc, BK_DAILY_SYSTEMD_SUCCESS)} run_status={overall}")
                    ok(status is not None and "off-season" not in str(status).lower(),
                       f"{tag}: never 'SKIP (off-season)' (got {status!r})")
                    if want == "PASS":
                        ok(status == "PASS" and rc == 0 and overall == "GREEN",
                           f"{tag}: PASS, exit 0, run status GREEN ({status}, {rc}, {overall})")
                    elif want == "GOV":
                        ok(ro.is_governed_benign_status(status) and rc == 0 and overall == "GREEN"
                           and any(g["label"] == step_label for g in summary.get("governed_skips", []))
                           and step_label not in summary["failed_steps"],
                           f"{tag}: governed {status}, exit 0, GREEN, listed in governed_skips "
                           f"({rc}, {overall}, {summary.get('governed_skips')})")
                    else:
                        ok(status == "FAIL" and rc == 2 and systemd(rc, BK_DAILY_SYSTEMD_SUCCESS) == "FAILED",
                           f"{tag}: FAIL, runner exit {rc} (hard failure 2, never 0/1)")
                        ok(summary["blocking_failure"] is True and step_label in summary["failed_steps"],
                           f"{tag}: Last_Operator_Summary blocking_failure + failed_steps={summary['failed_steps']}")
                        ok(any(step_label in r for r in reasons) and overall == "DEGRADED",
                           f"{tag}: run status degraded reason names the step; overall {overall}")
                        ran_after = any(s["label"] == "Power ratings" for s in summary["steps"])
                        ok(ran_after == coe, f"{tag}: later steps {'continue' if coe else 'abort'} "
                                             f"(Power ratings ran={ran_after})")
                        if "UNCONFIGURED" in key:
                            ok(entry.get("reason") == "UNCONFIGURED_SPORT",
                               f"{tag}: reason UNCONFIGURED_SPORT ({entry.get('reason')})")
                        for word in ("CONFIG_MISSING", "BLOCKED_QUOTA"):
                            if word in key or (word == "BLOCKED_QUOTA" and "QUOTA" in key):
                                ok(entry.get("reason") == word, f"{tag}: reason {word} ({entry.get('reason')})")
                        if "QUOTA" in key:
                            ok(step_label in summary.get("provider_exhausted_steps", []),
                               f"{tag}: listed in provider_exhausted_steps ({summary.get('provider_exhausted_steps')})")

        # Governed PRE-RUN calendar skip: zero provider calls, proven by a tripwire child.
        for coe in (False, True):
            trip, sentinel = tripwire(Path(tempfile.mkdtemp(dir=root)), "preseason_provider")
            rc, summary, reasons, overall, _ = run_daily_case(
                root, lambda okc: [("NFL preseason lines", trip, 60), ("Power ratings", okc, 60)], coe,
                preseason_open=False)
            entry = next((s for s in summary["steps"] if s["label"] == "NFL preseason lines"), {})
            tag = f"run_daily [NFL preseason lines | governed calendar CLOSED{' | coe' if coe else ''}]"
            MATRIX.append(f"run_daily  | {'governed calendar closed (pre-run)':52s} | NFL preseason lines: "
                          f"step={entry.get('status')} outcome={entry.get('outcome')} provider_calls="
                          f"{entry.get('provider_calls')} tripwire_called={sentinel.exists()} runner_exit={rc} "
                          f"run_status={overall}")
            ok(not sentinel.exists(), f"{tag}: tripwire NOT invoked -> zero provider calls / zero credits")
            ok(entry.get("outcome") == ro.SKIPPED_OFF_SEASON and entry.get("calendar") == GOV_CAL
               and entry.get("provider_calls") == 0,
               f"{tag}: outcome SKIPPED_OFF_SEASON calendar={entry.get('calendar')} provider_calls=0")
            ok(rc == 0 and overall == "GREEN" and not summary["failed_steps"]
               and any(g["outcome"] == ro.SKIPPED_OFF_SEASON for g in summary.get("governed_skips", [])),
               f"{tag}: exit {rc}, run status {overall}, governed_skips recorded")
        # Control: the tripwire really detects a call -- window OPEN -> it runs (and its exit 99 is a FAIL).
        trip, sentinel = tripwire(Path(tempfile.mkdtemp(dir=root)), "preseason_open")
        rc, summary, reasons, overall, _ = run_daily_case(
            root, lambda okc: [("NFL preseason lines", trip, 60)], False, preseason_open=True)
        ok(sentinel.exists() and rc == 2 and "NFL preseason lines" in summary["failed_steps"] and overall == "DEGRADED",
           f"control: preseason window OPEN -> tripwire called ({sentinel.exists()}), exit 99 -> FAIL, rc {rc}, {overall}")


def check_run_status_direct():
    print("--- S. run status: legacy/ungoverned summaries + both-feeds-stale odds family ---")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        sp = base / "Last_Operator_Summary.json"
        cases = [
            ("legacy 'SKIP (off-season)' step", {"blocking_failure": False, "failed_steps": [],
             "steps": [{"label": "WNBA game lines", "status": "SKIP (off-season)"}]}, True),
            ("SKIPPED_OFF_SEASON w/ ungoverned calendar", {"failed_steps": [], "steps": [
                {"label": "MLB daily refresh", "status": "SKIP (x)", "outcome": ro.SKIPPED_OFF_SEASON,
                 "calendar": "active_sports"}]}, True),
            ("governed preseason skip", {"failed_steps": [], "steps": [
                {"label": "NFL preseason lines", "status": "SKIP (out of preseason window)",
                 "outcome": ro.SKIPPED_OFF_SEASON, "calendar": GOV_CAL, "provider_calls": 0}]}, False),
            ("NO_GAMES_SCHEDULED w/ ungoverned contract", {"failed_steps": [], "steps": [
                {"label": "WNBA game lines", "status": ro.NO_GAMES_SCHEDULED, "outcome": ro.NO_GAMES_SCHEDULED,
                 "reason": "contract=odds_api_events_empty"}]}, True),
            ("failed step without blocking flag", {"blocking_failure": False, "failed_steps": ["MLB daily refresh"],
             "steps": [{"label": "MLB daily refresh", "status": "FAIL"}]}, True),
        ]
        for name, payload, want_degraded in cases:
            sp.write_text(json.dumps(payload), encoding="utf-8")
            with patched(grs, OPERATOR_SUMMARY_PATH=sp, _classify=lambda *a, **k: "FRESH",
                         _odds_family_signals=lambda: ([], [])):
                reasons, _ = grs._operator_signals()
                overall = grs.build_run_status()["overall"]
            MATRIX.append(f"run_status | {name:52s} | overall={overall} reasons={reasons}")
            ok((overall == "DEGRADED") == want_degraded and bool(reasons) == want_degraded,
               f"run status {name}: {overall} (expected {'DEGRADED' if want_degraded else 'GREEN'})")

        # Odds family: BOTH lines and props REFRESH_MISSED used to be read as "off-season" and dropped.
        for sport in grs.GAME_LINE_FEEDS:
            for rel in (grs.GAME_LINE_FEEDS[sport], grs.PROPS_FEEDS[sport]):
                p = base / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("LastUpdated,Player\n2026-01-01,P\n", encoding="utf-8")
                age = 200 if sport == "MLB" else 1
                ts = datetime.now().timestamp() - age * 3600
                os.utime(p, (ts, ts))
        fut = base / grs.FUTURES_FEED
        fut.parent.mkdir(parents=True, exist_ok=True)
        fut.write_text("a\n1\n", encoding="utf-8")
        with patched(grs, BASE_DIR=base):
            _rows, reasons = grs._odds_family_signals()
        MATRIX.append(f"run_status | {'MLB lines+props both REFRESH_MISSED':52s} | reasons={reasons}")
        ok(any("MLB" in r and "NOT assumed off-season" in r for r in reasons),
           f"odds family: MLB lines AND props REFRESH_MISSED -> DEGRADED reason, not off-season ({reasons})")
        ok(not any(s in r for r in reasons for s in ("NFL", "NBA", "WNBA", "NCAAF")),
           "odds family: fresh sports add no reason")


# ---- P. props classification + parents -------------------------------------------------------------------
def check_props_parents():
    print("--- P. props child classification + football parents ---")
    zero_events = {"events_found": 0, "rows_fetched": 0, "provider_error_count": 0,
                   "shape_proves_no_markets_posted": False}
    proven = {"events_found": 3, "rows_fetched": 0, "provider_error_count": 0,
              "shape_proves_no_markets_posted": True}
    for receipt, name in ((None, "no receipt"), (zero_events, "stale zero-events receipt"),
                          (proven, "stale NO_MARKETS_POSTED receipt")):
        for adv in (False, True):
            o, d = ro.classify_props_child(2, adv, receipt)
            ok(o == ro.VALIDATION_FAILED and ro.is_alerting(o) and "UNCONFIGURED_SPORT" in d,
               f"classify_props_child(exit 2, advanced={adv}, {name}) -> {o} (alerting)")
            MATRIX.append(f"props-cls  | exit 2, {name}, advanced={adv} -> {o}")
    for args, want, alerting in (
            ((0, True, None), ro.UPDATED, False),
            ((0, False, None), ro.STALE, True),
            ((1, False, None), ro.VALIDATION_FAILED, True),
            ((1, False, zero_events), ro.NO_ACTIVE_EVENTS, True),          # empty rows: ALERTING (2026-11-04)
            ((1, False, {"events_found": 4, "rows_fetched": 0, "provider_error_count": 4}), ro.PROVIDER_ERROR, True),
            ((1, False, proven), ro.NO_MARKETS_POSTED, False),
            ((0, True, {"events_found": 2, "rows_fetched": 9}), ro.UPDATED, False)):
        o, _ = ro.classify_props_child(*args)
        ok(o == want and ro.is_alerting(o) == alerting,
           f"classify_props_child{args[:2]} receipt={'yes' if args[2] else 'none'} -> {o} "
           f"({'ALERTING' if ro.is_alerting(o) else 'benign'}; expected {want}/{'ALERTING' if alerting else 'benign'})")
        MATRIX.append(f"props-cls  | exit {args[0]}, advanced={args[1]}, receipt={args[2]} -> {o} "
                      f"{'ALERTING' if ro.is_alerting(o) else 'benign'}")

    saved_key = os.environ.get("ODDS_API_KEY")
    os.environ["ODDS_API_KEY"] = "qc-offline-dummy"
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data" / "tracking").mkdir(parents=True)
            (root / "data" / "props").mkdir(parents=True)
            for slug in ("americanfootball_nfl", "americanfootball_ncaaf"):
                (root / "data" / "tracking" / f"_last_props_fetch_{slug}.json").write_text(json.dumps(zero_events))
            # (a) exit-2 refusals with stale zero-event receipts on disk -> VALIDATION_FAILED
            steps = [("nfl_player_props", real_refusal("fetch_player_props.py"), 120, "americanfootball_nfl",
                      root / "data" / "props" / "NFL_Props.csv"),
                     ("ncaaf_player_props", stub(root, "p2", 2, "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT"),
                      120, "americanfootball_ncaaf", root / "data" / "props" / "NCAAF_Props.csv")]
            with patched(rfp, BASE_DIR=root, STEPS=steps):
                rc, _out = quiet(rfp.main)
            sidecar = json.loads((root / "data" / "tracking" / "_child_outcomes_football_props.json").read_text())
            ok(rc == 2 and set(sidecar["outcomes"].values()) == {ro.VALIDATION_FAILED} and sidecar["degraded"],
               f"refresh_football_props: exit-2 children -> {sidecar['outcomes']}, DEGRADED, exit {rc}")
            MATRIX.append(f"fb-props   | exit 2 (real + stub) -> {sorted(set(sidecar['outcomes'].values()))} parent_exit={rc}")
            # (b) EMPTY: both children exit 1 with zero-event receipts -> NO_ACTIVE_EVENTS -> DEGRADED, exit 2
            steps = [(lbl, stub(root, f"e{i}", 1, "zero events; preserving last-known-good"), 120, slug,
                      root / "data" / "props" / f"{lbl}.csv")
                     for i, (lbl, slug) in enumerate((("nfl_player_props", "americanfootball_nfl"),
                                                      ("ncaaf_player_props", "americanfootball_ncaaf")))]
            with patched(rfp, BASE_DIR=root, STEPS=steps):
                rc, _out = quiet(rfp.main)
            sidecar = json.loads((root / "data" / "tracking" / "_child_outcomes_football_props.json").read_text())
            ok(rc == 2 and set(sidecar["outcomes"].values()) == {ro.NO_ACTIVE_EVENTS} and sidecar["degraded"],
               f"refresh_football_props: EMPTY (zero events) children -> {sidecar['outcomes']}, DEGRADED, exit {rc} "
               "(never a clean off-season pass)")
            MATRIX.append(f"fb-props   | exit 1 zero-events receipts -> {sorted(set(sidecar['outcomes'].values()))} "
                          f"degraded={sidecar['degraded']} parent_exit={rc}")
    finally:
        if saved_key is None:
            os.environ.pop("ODDS_API_KEY", None)
        else:
            os.environ["ODDS_API_KEY"] = saved_key

    with patched(rflm, STEPS=[("nfl_game_lines", real_refusal("fetch_game_lines.py"), 120)]):
        rc, out = quiet(rflm.main)
    ok(rc == 2 and "[FAIL] nfl_game_lines exited with code 2" in out,
       f"refresh_football_line_movement: real exit-2 child propagates as [FAIL] (parent exit {rc})")


# ---- R. the other chain runners in the bk-daily path ------------------------------------------------------
def check_chain_runners():
    print("--- R. chain runners: child exit -> runner exit (1 only when governed; hard failure >=2) ---")
    gov_out = f"OUTCOME: SKIPPED_OFF_SEASON calendar={GOV_CAL} provider_calls=0"
    for code, output, want in ((-15, None, 2), (-9, None, 2), (1, None, 2), (1, "No new rows", 2),
                               (1, gov_out, 1), (1, "OUTCOME: NO_GAMES_SCHEDULED contract=x", 2),
                               (2, gov_out, 2), (3, None, 3), (124, None, 124), (241, None, 241)):
        got = ro.runner_exit_for_child(code, output)
        ok(got == want, f"runner_exit_for_child({code}, {output!r}) -> {got} (expected {want})")
        MATRIX.append(f"chain-map  | child {code:>4} output={str(output)[:44]!s:44s} -> runner_exit={got}")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for key, code, cmd, inject, _want in children(root):
            want = 0 if code == 0 else max(2, code)   # streamed children: no governed claim is visible
            for name, mod, patch in (
                    ("refresh_football_line_movement", rflm, {"STEPS": [("nfl_game_lines", cmd, 120)]}),
                    ("refresh_nba_daily", rnba, {"STEPS": [("game_lines", cmd, 120)]}),
                    ("refresh_mlb_daily", rmlb, {"_build_steps": lambda c=cmd: [("game_lines", c, 120)]}),
                    ("refresh_wnba_daily", rwnba, {"STEPS": [("game_lines", cmd, 120)]})):
                with ctx(inject), patched(mod, **patch):
                    rc, _out = quiet(mod.main)
                # NBA v6 receipt identity: bk-daily's NBA lines stage is classified ONLY by THIS run's own receipt.
                # These stubs write none, so even an exit-0 child is RUN_RECEIPT_MISSING -> hard failure 2.
                w = 2 if (name == "refresh_nba_daily" and code == 0) else want
                MATRIX.append(f"chain      | {key:52s} | {name}: runner_exit={rc}")
                ok(rc == w, f"{name} {key}: runner exit {rc} (expected {w}; unclassified 1 -> 2, never 0/1"
                            f"{'; NBA lines without its own receipt -> RUN_RECEIPT_MISSING' if w != want else ''})")
        two = stub(root, "two", 2, "OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT")
        empty = stub(root, "empty", 1, "zero events")
        for child, label in ((two, "exit-2 props child"), (empty, "EMPTY props child (zero-event receipt)")):
            for name, mod, slug, patch in (
                    ("refresh_nba_daily", rnba, "basketball_nba", {"STEPS": [("player_props", child, 120)]}),
                    ("refresh_mlb_daily", rmlb, "baseball_mlb", {"_build_steps": lambda c=child: [("player_props", c, 120)]})):
                base = Path(tempfile.mkdtemp(dir=root))
                (base / "data" / "tracking").mkdir(parents=True)
                (base / "data" / "tracking" / f"_last_props_fetch_{slug}.json").write_text(
                    json.dumps({"events_found": 0, "rows_fetched": 0}))
                with patched(mod, BASE_DIR=base, PROPS_ARTIFACT=base / "data" / "props" / "X_Props.csv", **patch):
                    rc, out = quiet(mod.main)
                ok(rc == 2 and "ALERT" in out, f"{name}: {label} -> alerting props outcome, DEGRADED, runner exit {rc}")
                MATRIX.append(f"chain      | {label:52s} | {name}: DEGRADED runner_exit={rc}")

        # Edge Engine pipeline + scorecard runner: a failing sport step is FAIL even with every props file empty.
        tmp = Path(tempfile.mkdtemp(dir=root))
        (tmp / "fail_step.py").write_text("import sys\nprint('no history file')\nsys.exit(1)\n", encoding="utf-8")
        (tmp / "generate_run_status.py").write_text("print('rs')\n", encoding="utf-8")
        (tmp / "crash_card.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        (tmp / "fail_card.py").write_text("import sys\nprint('PASS: 3  WATCH: 1  FAIL: 2')\nsys.exit(1)\n", encoding="utf-8")
        (tmp / "watch_card.py").write_text("import sys\nprint('PASS: 3  WATCH: 4  FAIL: 0')\nsys.exit(1)\n", encoding="utf-8")
        no_props = {"active_sports": lambda: set()}
        with patched(season_utils, **no_props), \
                patched(redge, **(no_props if hasattr(redge, "active_sports") else {})), \
                patched(redge, BASE_DIR=tmp, LOG_DIR=tmp / "logs", STEPS=[("MLB game context", "fail_step.py")]):
            rc, out = quiet(redge.main)
        ok(rc == 2 and "[FAIL] MLB game context" in out and "off-season" not in out,
           f"run_bk_edge_engine_pipeline: failing MLB step with empty props -> FAIL, exit {rc} (never SKIP off-season)")
        MATRIX.append(f"edge       | failing MLB step, props empty -> exit {rc}")
        for script, want_status, want_rc in (("crash_card.py", "FAIL", 2), ("fail_card.py", "FAIL", 2),
                                             ("watch_card.py", "WATCH (not blocking)", 0)):
            with patched(season_utils, **no_props), \
                    patched(rsc, **(no_props if hasattr(rsc, "active_sports") else {})), \
                    patched(rsc, BASE_DIR=tmp, LOG_DIR=tmp / "logs", SCORECARDS=[("MLB 99 Scorecard", script, 60)]):
                rc, out = quiet(rsc.main)
            ok(rc == want_rc and f"[{want_status}] MLB 99 Scorecard" in out and "off-season" not in out,
               f"run_all_scorecards: MLB scorecard {script} with empty props -> {want_status}, exit {rc}")
            MATRIX.append(f"scorecards | MLB {script:18s} props empty -> {want_status} exit {rc}")


def main() -> int:
    print("=" * 80)
    print("QC: runner exit semantics + governed off-season / no-game (Safeguard A, owner decision 2026-11-04)")
    print("=" * 80)
    check_classifier()
    # bk-linemove: receipt-based since NBA v6 -> proven end to end by qc_runner_exit_matrix.py
    check_run_daily()
    check_run_status_direct()
    check_props_parents()
    check_chain_runners()
    print("--- exit-code matrix ---")
    for row in MATRIX:
        print("  " + row)
    print("=" * 80)
    print(f"RESULT: {_OK} ok, {_FAIL} FAIL")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
