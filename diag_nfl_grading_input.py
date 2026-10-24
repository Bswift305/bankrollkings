"""
Read-only UPSTREAM-INPUT probe for the NFL prop-grading lane (incident 2026-10-24, Item-5 P0).

`diag_nfl_grading_receipt.py` characterizes the OUTPUT (NFL_AllPropResults.csv); it proved the file is
FRESH by mtime yet holds ZERO current-season rows. This probe answers WHY, by inspecting the INPUT the
output is derived from, and names the branch:

  write_all_prop_results_snapshot_for_sport('NFL')  ==  archive[Sport=='NFL'] -> grade -> REPLACE file.

So the output's rows come ENTIRELY from the candidate archive (NBA_CandidateArchive.csv). Grading only
labels Hit/Miss/Push vs pending; it never invents rows. Therefore:

  * GUARD_TRIPPED  : NFL gamelog does not reach the current season -> the grader SKIPS the NFL write and
                     PRESERVES the prior file. (Then a fresh output mtime is itself a contradiction:
                     something else rewrote it. Flagged, exit 3.)
  * INPUT_STARVED  : guard passed + writer ran, but the archive holds NO current-season NFL candidates
                     (latest NFL SnapshotDate is a prior season) -> the output cannot contain current-
                     season rows. The regression is UPSTREAM: 2026 NFL candidates are not being archived
                     (archive_football_method_candidates / its run_daily caller). Board correctly fails
                     closed. THIS is the active P0 branch the Item-5 receipt pointed to.
  * WRITER_DROP    : archive HAS current-season NFL candidates but the output has none and the guard is
                     not stale -> grading/resolution drops them (a grader bug, different fix). (exit 3)
  * HEALTHY        : archive + output both carry current-season NFL rows.

LITERAL read-only: no network/provider call; only reads local CSVs + the in-memory cache; calls only the
PURE helpers `load_candidate_archive` / `load_nfl_gamelogs` / `_nfl_gamelog_stale` /
`_nfl_expected_completed_week` (never `write_*`/`replace_*`/`grade_candidate_archive_rows`, which write or
are heavy); `append_qc_run_log` is monkeypatched to a no-op. Every touched artifact is sha256+mtime+size
fingerprinted BEFORE and AFTER; the run FAILS (exit 4) if anything changed. Current season comes from
`_nfl_expected_completed_week` -- never a global max(Season)/max(Week).

Exit codes: 0 coherent (incl. INPUT_STARVED, which is a true read of a real upstream gap); 2 a needed
artifact is absent/unreadable; 3 contradictory/malformed (GUARD_TRIPPED-with-fresh-output, WRITER_DROP,
or resolver None); 4 the diagnostic mutated an artifact (should never happen).

Run on the box with the data (prod/owner), venv python. No fetch, no paid call, no writes:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_grading_input.py
"""
from __future__ import annotations

import glob
import hashlib
import os
from datetime import datetime, timezone

import pandas as pd

import app

# Belt-and-suspenders: no QC-log write can happen through this diagnostic.
app.append_qc_run_log = lambda *a, **k: None

ARCHIVE = app.CANDIDATE_ARCHIVE_PATH
OUTPUT = app.DATA_DIR / "tracking" / "NFL_AllPropResults.csv"
GAMELOG = app.DATA_DIR / "NFL_GameLogs.csv"
_ARCHIVE_DATE_COLS = ("SnapshotDate", "GameDay", "SavedAt")


def _et(ts_epoch: float) -> str:
    try:
        iso = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts_epoch)


def _relevant_artifacts() -> list[str]:
    files = {str(ARCHIVE), str(OUTPUT), str(GAMELOG),
             str(app.DATA_DIR / "tracking" / "QC_Run_Log.csv")}
    for base in (app.DATA_DIR, app.DATA_DIR / "tracking", app.DATA_DIR / "cache"):
        for pat in ("*CandidateArchive*", "*NFL_AllPropResults*", "*NFL_GameLogs*",
                    "*nflverse_stats*", "*candidate*archive*"):
            files.update(glob.glob(str(base / pat)))
    return sorted(files)


def _fingerprint(paths: list[str]) -> dict:
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()[:16]
            fp[p] = (h, st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None
    return fp


def _season_of(date_series: pd.Series) -> pd.Series:
    """NFL season a date belongs to: a date on/after ~Aug 1 counts as that calendar year's season;
    Jan-Jul belongs to the previous year's season (playoffs/offseason)."""
    dts = pd.to_datetime(date_series, errors="coerce")
    yr = dts.dt.year
    return yr.where(dts.dt.month >= 8, yr - 1)


def main() -> int:
    print("=" * 80)
    print("NFL PROP-GRADING LANE -- UPSTREAM INPUT PROBE (read-only, Item-5 P0)")
    print("=" * 80)

    artifacts = _relevant_artifacts()
    fp_before = _fingerprint(artifacts)

    try:
        expected_week, expected_season = app._nfl_expected_completed_week()
    except Exception as exc:
        expected_week, expected_season = None, None
        print(f"[WARN] season resolver error: {exc}")
    print(f"resolver_current_season : {expected_season}")
    print(f"resolver_completed_week : {expected_week}")

    # ---- 1. candidate archive: the ACTUAL input the output is derived from --------------------------
    print("-" * 80)
    print(f"ARCHIVE (input)  : {ARCHIVE}")
    if not ARCHIVE.exists():
        print("STATUS           : archive ABSENT -> output cannot contain NFL rows (input-starved).")
        archive_nfl_latest_season = None
        archive_nfl_rows = 0
    else:
        ast = ARCHIVE.stat()
        print(f"  mtime          : {_et(ast.st_mtime)}  size={ast.st_size}")
        try:
            arc = app.load_candidate_archive()
        except Exception as exc:
            print(f"STATUS           : archive UNREADABLE ({type(exc).__name__}: {exc}) -> fails closed.")
            return 2
        nfl = arc[arc["Sport"].astype(str).str.upper() == "NFL"].copy() if "Sport" in arc.columns else arc.iloc[0:0]
        archive_nfl_rows = len(nfl)
        print(f"  total_rows     : {len(arc)}   NFL_rows: {archive_nfl_rows}")
        date_col = next((c for c in _ARCHIVE_DATE_COLS if c in nfl.columns), None)
        archive_nfl_latest_season = None
        if archive_nfl_rows and date_col:
            seasons = _season_of(nfl[date_col]).dropna().astype(int)
            if not seasons.empty:
                archive_nfl_latest_season = int(seasons.max())
                print(f"  NFL seasons (by {date_col!r}):")
                for s, n in seasons.value_counts().sort_index().items():
                    mark = "  <- resolver current" if expected_season and int(s) == int(expected_season) else ""
                    print(f"      {int(s)}: {int(n)} rows{mark}")
                latest_dt = pd.to_datetime(nfl[date_col], errors="coerce").max()
                print(f"  latest NFL {date_col} : {latest_dt}")
            else:
                print(f"  NFL seasons    : (no parseable {date_col!r})")
        elif archive_nfl_rows:
            print(f"  NFL seasons    : (no date col among {_ARCHIVE_DATE_COLS})")

    # ---- 2. gamelog + guard state (Branch A vs B) --------------------------------------------------
    print("-" * 80)
    try:
        gl = app.load_nfl_gamelogs()
        gl_max_season = (int(pd.to_numeric(gl.get("Season"), errors="coerce").max())
                         if (gl is not None and not gl.empty and "Season" in gl.columns) else None)
        gl_max_week = None
        if gl is not None and not gl.empty and "Season" in gl.columns and "Week" in gl.columns and gl_max_season:
            cur_gl = gl[pd.to_numeric(gl["Season"], errors="coerce") == gl_max_season]
            wk = pd.to_numeric(cur_gl["Week"], errors="coerce").dropna()
            gl_max_week = int(wk.max()) if not wk.empty else None
    except Exception as exc:
        gl = None
        gl_max_season = gl_max_week = None
        print(f"[WARN] load_nfl_gamelogs error: {exc}")
    print(f"GAMELOG          : max_season={gl_max_season} max_week_in_season={gl_max_week}")
    try:
        from refresh_all_prop_results import _nfl_gamelog_stale
        guard_reason = _nfl_gamelog_stale(gl)
    except Exception as exc:
        guard_reason = f"(guard check error: {exc})"
    guard_tripped = bool(guard_reason)
    print(f"GUARD (stale?)   : {'TRIPPED -> grader SKIPS write' if guard_tripped else 'passed -> writer runs'}"
          f"{' :: ' + guard_reason if guard_reason else ''}")

    # ---- 3. output cross-check (so input->output is in ONE receipt) --------------------------------
    print("-" * 80)
    out_cur_rows = None
    out_fresh = None
    if not OUTPUT.exists():
        print(f"OUTPUT           : {OUTPUT}  ABSENT")
    else:
        ost = OUTPUT.stat()
        age_h = round((datetime.now().timestamp() - ost.st_mtime) / 3600, 2)
        out_fresh = age_h <= 54.0  # grading cadence budget (freshness_contract CLOCK B)
        print(f"OUTPUT           : {OUTPUT}")
        print(f"  mtime          : {_et(ost.st_mtime)}  ({age_h}h ago)  fresh_by_cadence={out_fresh}")
        try:
            od = pd.read_csv(OUTPUT, low_memory=False)
            if "Season" in od.columns and expected_season:
                out_cur_rows = int((pd.to_numeric(od["Season"], errors="coerce") == int(expected_season)).sum())
            print(f"  total_rows     : {len(od)}   current_season_rows: {out_cur_rows}")
        except Exception as exc:
            print(f"  UNREADABLE     : {type(exc).__name__}: {exc}")
            return 2

    # ---- verdict -----------------------------------------------------------------------------------
    fp_after = _fingerprint(artifacts)
    changed = sorted(p for p in artifacts if fp_before.get(p) != fp_after.get(p))
    print("-" * 80)
    print(f"READ-ONLY PROOF  : {len(artifacts)} artifact(s) fingerprinted (sha256+mtime_ns+size); "
          f"{'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")

    archive_has_current = bool(expected_season and archive_nfl_latest_season == int(expected_season)
                               and archive_nfl_rows)
    output_has_current = bool(out_cur_rows)

    problems = []
    if changed:
        problems.append(f"diagnostic mutated artifact(s): {changed}")
    if expected_season is None:
        problems.append("season resolver returned None (cannot characterize current season)")

    print("-" * 80)
    if guard_tripped and out_fresh:
        verdict = "GUARD_TRIPPED but output mtime is FRESH -- contradiction (writer was skipped, yet the " \
                  "file was rewritten by something else). Investigate the writer of NFL_AllPropResults.csv."
        problems.append(verdict)
    elif guard_tripped:
        verdict = "GUARD_TRIPPED: NFL gamelog does not reach the current season; grader skipped the NFL " \
                  "write and preserved the prior (prior-season) file. Rebuild NFL_GameLogs.csv (fold the " \
                  "weekly parquet), then the grader can advance."
    elif archive_has_current and not output_has_current:
        verdict = "WRITER_DROP: the archive HOLDS current-season NFL candidates but the graded output has " \
                  "none -- grading/resolution is dropping current-season rows (grader bug, not an input gap)."
        problems.append(verdict)
    elif not archive_has_current:
        verdict = ("INPUT_STARVED: the candidate archive holds NO current-season NFL candidates "
                   f"(latest NFL season in archive = {archive_nfl_latest_season}, resolver current = "
                   f"{expected_season}). The grader faithfully reproduces prior seasons; it cannot write "
                   "current-season rows that were never archived. ACTIVE P0 = upstream archiving "
                   "(archive_football_method_candidates / its run_daily caller) is not landing current NFL "
                   "candidates. Board correctly fails closed (current_season_ungraded).")
    else:
        verdict = "HEALTHY: archive and output both carry current-season NFL rows."

    print(f"VERDICT          : {verdict}")
    print("-" * 80)
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 4 if changed else 3
    print("[OK] coherent read; diagnostic changed nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
