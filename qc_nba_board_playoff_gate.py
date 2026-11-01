"""QC: NBA board QC gates the playoff-data freshness checks to the postseason phase.

Regression guard for the prod `bk-daily` failure where `qc_nba_board.py` (the `board_qc` step of
`refresh_nba_daily.py`) demanded playoff player logs / playoff results during the REGULAR season
and exited 1 every day. The phase comes from the app's configured-official-window resolver
(`app._nba_default_postseason` / `app._resolve_nba_postseason`), never a second calendar.

Fully synthetic: every loader qc_nba_board uses is replaced with an in-memory fixture, the QC run
log writer is stubbed (nothing is written under data/), no network, no prod data. Boundary dates
use a SYNTHETIC complete window (the real 2027 end is intentionally None).
Exits 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import io
from datetime import datetime

import pandas as pd

import app
import qc_nba_board as board

D = lambda y, m, d: datetime(y, m, d).date()
COMPLETE = {2099: {"start": D(2099, 4, 13), "end": D(2099, 6, 30)}}

PAST = "2000-01-02"
FUTURE = "2200-01-01"  # within pandas ns bounds

LOG_MISSING = "Playoff player logs are missing."
RES_MISSING = "Playoff results are missing."


def _phase(day) -> bool:
    return app._resolve_nba_postseason(day, 2099, COMPLETE)


def _fixtures(with_playoff_files: bool, missing_team_rows: int):
    if with_playoff_files:
        playoff_logs = pd.DataFrame({"Date": [PAST], "Player": ["A"], "Team": ["BOS"]})
        playoff_results = pd.DataFrame({"Date": [PAST], "Away": ["BOS"], "Home": ["NYK"]})
    else:
        playoff_logs = pd.DataFrame()
        playoff_results = pd.DataFrame()
    # Schedule: one completed game on PAST (so the stale-results rule has nothing to flag when
    # results run through PAST) and one upcoming game so the schedule check passes.
    schedule = pd.DataFrame({"Date": [PAST, FUTURE], "Away": ["BOS", "BOS"], "Home": ["NYK", "NYK"]})
    teams = ["BOS"] * 2 + [""] * missing_team_rows
    props = pd.DataFrame({
        "Player": [f"P{i}" for i in range(len(teams))],
        "Stat": ["PTS"] * len(teams),
        "Team": teams,
    })
    return playoff_logs, playoff_results, schedule, props


@contextlib.contextmanager
def patched(is_postseason: bool, with_playoff_files: bool, missing_team_rows: int = 0):
    playoff_logs, playoff_results, schedule, props = _fixtures(with_playoff_files, missing_team_rows)
    replacements = {
        "load_playoff_gamelogs": lambda: playoff_logs.copy(),
        "load_playoff_results": lambda: playoff_results.copy(),
        "load_gamelogs": lambda: pd.DataFrame(),
        "load_schedule": lambda: schedule.copy(),
        "load_props": lambda: props.copy(),
        "_load_live_props": lambda: [],
        "apply_current_team_context": lambda df, *a, **k: df.copy(),
        "load_canonical_live_props": lambda *a, **k: pd.DataFrame(),
        "load_player_snapshot": lambda: pd.DataFrame(),
        "load_current_team_overrides": lambda: {},
        "append_qc_run_log": lambda *a, **k: None,
        "_nba_is_postseason": lambda: is_postseason,
    }
    saved = {name: getattr(board, name) for name in replacements}
    try:
        for name, fn in replacements.items():
            setattr(board, name, fn)
        yield
    finally:
        for name, fn in saved.items():
            setattr(board, name, fn)


def _run(is_postseason, with_files, missing_team_rows=0):
    with patched(is_postseason, with_files, missing_team_rows):
        report = board.run_qc()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = board.main()
    return report, code, buf.getvalue()


def _msgs(report, severity=None):
    return [i["message"] for i in report["issues"] if severity is None or i["severity"] == severity]


def run():
    results: list[tuple[bool, str]] = []

    def expect(cond, msg):
        results.append((bool(cond), msg))

    # 1. Regular-season date, playoff files missing -> no playoff HIGHs, explicit skip, exit 0.
    day = D(2099, 11, 1)
    expect(_phase(day) is False, "regular-season date resolves to regular phase")
    rep, code, out = _run(_phase(day), with_files=False)
    expect(LOG_MISSING not in _msgs(rep), "regular season: no 'playoff logs missing' issue")
    expect(RES_MISSING not in _msgs(rep), "regular season: no 'playoff results missing' issue")
    expect(not _msgs(rep, "high"), "regular season: zero HIGH issues")
    expect(len(rep["skipped_checks"]) == 2, "regular season: both playoff checks reported as skipped")
    expect(out.count("[SKIP]") == 2, "regular season: skip reasons printed")
    expect(rep["nba_phase"] == "regular", "regular season: report records phase=regular")
    expect(code == 0, "regular season, nothing else wrong: board_qc exits 0")

    # 2. Postseason date, playoff files missing -> both HIGHs fire, exit 1.
    day = D(2099, 5, 10)
    expect(_phase(day) is True, "in-window date resolves to postseason")
    rep, code, out = _run(_phase(day), with_files=False)
    highs = _msgs(rep, "high")
    expect(LOG_MISSING in highs, "postseason: 'playoff logs missing' is HIGH")
    expect(RES_MISSING in highs, "postseason: 'playoff results missing' is HIGH")
    expect(not rep["skipped_checks"], "postseason: nothing skipped")
    expect("[HIGH] data_freshness: Playoff player logs are missing." in out, "postseason: HIGH line printed")
    expect(code == 1, "postseason, files missing: board_qc exits 1")

    # 3. Postseason with files present and current -> pass.
    rep, code, _ = _run(True, with_files=True)
    expect(not rep["issues"], "postseason with current playoff files: no issues")
    expect(code == 0, "postseason with current playoff files: exits 0")

    # 4. Phase boundaries from the existing helper (inclusive start/end).
    for day, want in [(D(2099, 4, 12), False), (D(2099, 4, 13), True),
                      (D(2099, 6, 30), True), (D(2099, 7, 1), False)]:
        rep, code, _ = _run(_phase(day), with_files=False)
        fired = LOG_MISSING in _msgs(rep, "high") and RES_MISSING in _msgs(rep, "high")
        absent = LOG_MISSING not in _msgs(rep) and RES_MISSING not in _msgs(rep)
        if want:
            expect(fired and code == 1, f"boundary {day}: postseason -> both HIGH fire, exit 1")
        else:
            expect(absent and code == 0, f"boundary {day}: regular -> skipped, exit 0")

    # 5. Stale-in-postseason rules unchanged (HIGH stale logs / MEDIUM stale results).
    iss, skipped = board.playoff_freshness_issues(
        True, pd.Timestamp("2099-05-01"), pd.Timestamp("2099-05-03"),
        pd.Timestamp("2099-05-02"), pd.Timestamp("2099-05-04"))
    sev = sorted(i["severity"] for i in iss)
    expect(sev == ["high", "medium"] and not skipped, "postseason stale logs HIGH + stale results MEDIUM unchanged")
    iss, skipped = board.playoff_freshness_issues(
        False, pd.Timestamp("2099-05-01"), pd.Timestamp("2099-05-03"),
        pd.Timestamp("2099-05-02"), pd.Timestamp("2099-05-04"))
    expect(not iss and len(skipped) == 2, "regular season: stale playoff rules also skipped")

    # 6. MEDIUM team-mapping check unchanged in BOTH phases.
    for phase in (False, True):
        rep, code, _ = _run(phase, with_files=True, missing_team_rows=3)
        meds = _msgs(rep, "medium")
        expect("3 resolved prop rows are still missing team mapping." in meds,
               f"team-mapping MEDIUM unchanged (postseason={phase})")
        expect(code == 1, f"team-mapping MEDIUM still fails the QC (postseason={phase})")

    # 7. Phase source = the app's resolver; failure fails CLOSED (checks fire).
    expect(board._nba_is_postseason() == bool(app._nba_default_postseason()),
           "_nba_is_postseason delegates to app._nba_default_postseason")
    saved = board._nba_default_postseason
    try:
        def _boom():
            raise RuntimeError("synthetic")
        board._nba_default_postseason = _boom
        expect(board._nba_is_postseason() is True, "phase resolver error fails closed to postseason")
    finally:
        board._nba_default_postseason = saved

    # 8. The skip reason carries the owner config warning while the window is incomplete.
    _, skipped = board.playoff_freshness_issues(False, None, None, None, None)
    warning = app.nba_postseason_config_warning()
    if warning:
        expect(all(warning in s for s in skipped), "skip reason includes the incomplete-config warning")
    else:
        expect(all("not in the configured postseason window" in s for s in skipped), "skip reason is explicit")

    return results


def main() -> int:
    results = run()
    print("=" * 60)
    print("NBA BOARD QC — PLAYOFF FRESHNESS PHASE GATE")
    print("=" * 60)
    failed = 0
    for ok, msg in results:
        print(f"[{'ok' if ok else 'FAIL'}] {msg}")
        failed += 0 if ok else 1
    print()
    print(f"{len(results) - failed} ok, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
