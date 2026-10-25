"""
Read-only FORENSIC lineage probe for the NFL graded-prop records (incident 2026-10-24, defect #2).

Preserves evidence (sha256/size/mtime/perms, before+after; exit 4 on any change) and characterizes EVERY
candidate/line/graded/calibration store so the two open questions are answered with data, not assertion:

  (1) Where does the earlier "~16,753 graded through Week 6" receipt actually come from? Prints row counts
      + season/week grain for every store so the 16,753 file is identified by inspection (hypothesis:
      NFL_PropLines_Graded.csv, the append-only Lane-2 record, NOT NFL_AllPropResults.csv).
  (2) Is there a PERSISTENT store that already holds completed-week 2026 candidates/grades? Lane 2
      (capture_nfl_prop_lines -> NFL_PropLines_Archive.csv [append-only] -> grade_nfl_prop_lines ->
      NFL_PropLines_Graded.csv) is wired into run_daily and called "the streak/heat-map record" there, yet
      build_nfl_prop_streaks reads Lane 1 (NFL_AllPropResults.csv). This probe reports whether Lane 2 holds
      2026 graded rows through ~the completed week, and whether its SCHEMA can feed build_nfl_prop_streaks
      (needs Player, Stat, Direction, Line, ResultValue, Season, Week).

Two lanes:
  Lane 1 (transient candidate pool): NBA_CandidateArchive.csv -> refresh_all_prop_results -> NFL_AllPropResults.csv  [Wave/Heating-Up read this]
  Lane 2 (persistent line history)  : capture_nfl_prop_lines -> NFL_PropLines_Archive.csv (append-only) -> grade_nfl_prop_lines -> NFL_PropLines_Graded.csv

LITERAL read-only: no network, no writes, only reads local CSVs; fingerprints before/after. Current season
via _nfl_expected_completed_week (never global max). No artifact is replaced or regenerated.

Exit: 0 reported cleanly; 2 nothing readable; 4 the probe mutated a file (should never happen).

Run on the box (prod/owner), venv python, no writes:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_graded_lineage.py
"""
from __future__ import annotations

import hashlib
import os
import stat as statmod
from datetime import datetime, timezone

import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
T = app.DATA_DIR / "tracking"
H = app.DATA_DIR / "historical"

# (label, path, lane/role)
STORES = [
    ("candidate archive (Lane 1 pool)", app.CANDIDATE_ARCHIVE_PATH, "transient candidate pool"),
    ("NFL_AllPropResults (Lane 1 graded; Wave reads)", T / "NFL_AllPropResults.csv", "Lane 1 graded"),
    ("NFL_AllPropResults_Backfill (historical calib)", T / "NFL_AllPropResults_Backfill.csv", "historical backfill"),
    ("NFL_AllPropResults_Scored (edge-scored)", T / "NFL_AllPropResults_Scored.csv", "edge-scored"),
    ("NFL_PropLines_Archive (Lane 2 captures)", T / "NFL_PropLines_Archive.csv", "append-only line history"),
    ("NFL_PropLines_Graded (Lane 2 graded)", T / "NFL_PropLines_Graded.csv", "Lane 2 graded (streak/scoreboard)"),
    ("NFL_Weekly_Grade_Log (board grade log)", T / "NFL_Weekly_Grade_Log.csv", "weekly board grade log"),
    ("NFL_Props_History (backfill input)", H / "NFL_Props_History.csv", "historical props input"),
]
BOARD_REQUIRED = ["Player", "Stat", "Direction", "Line", "ResultValue", "Season", "Week"]
_RESULT_COLS = ("OutcomeState", "Result", "Grade", "Outcome", "Status")
_SIDE_COLS = ("Direction", "Side", "OverUnder", "Bet")
_VALUE_COLS = ("ResultValue", "Actual", "ActualValue", "Value", "StatValue")


def _et(ts):
    try:
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts)


def _fp(paths):
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                fp[p] = (hashlib.sha256(fh.read()).hexdigest()[:16], st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None
    return fp


def _counts(s, n=10):
    try:
        vc = s.dropna().astype(int).value_counts().sort_index()
        return ", ".join(f"{int(k)}:{int(v)}" for k, v in vc.head(n).items())
    except Exception:
        try:
            vc = s.astype(str).str.strip().replace("", "(blank)").value_counts().head(n)
            return ", ".join(f"{k}={int(v)}" for k, v in vc.items())
        except Exception:
            return "(n/a)"


def main() -> int:
    print("=" * 92)
    print("NFL GRADED-PROP LINEAGE FORENSICS (read-only; evidence preserved)")
    print("=" * 92)
    paths = [str(p) for _, p, _ in STORES]
    fp0 = _fp(paths)

    try:
        exp_week, exp_season = app._nfl_expected_completed_week()
    except Exception:
        exp_week, exp_season = None, None
    cur = int(exp_season) if exp_season else None
    print(f"resolver_current_season={exp_season}  resolver_completed_week={exp_week}")

    near_16753 = []
    lane2_graded = None
    for label, path, role in STORES:
        print("-" * 92)
        print(f"{label}")
        print(f"  role : {role}")
        print(f"  path : {path}")
        if not os.path.exists(path):
            print("  ABSENT")
            continue
        st = os.stat(path)
        with open(path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()[:16]
        print(f"  evidence: sha={sha} size={st.st_size} mtime={_et(st.st_mtime)} perms={statmod.filemode(st.st_mode)} ({oct(st.st_mode)[-3:]})")
        try:
            d = pd.read_csv(path, low_memory=False)
        except Exception as exc:
            print(f"  UNREADABLE: {type(exc).__name__}: {exc}")
            continue
        # NFL subset for the cross-sport candidate archive
        if "Sport" in d.columns and d["Sport"].astype(str).str.upper().nunique() > 1:
            nfl = d[d["Sport"].astype(str).str.upper() == "NFL"]
            print(f"  rows: total={len(d)}  NFL={len(nfl)}")
            d = nfl
        else:
            print(f"  rows: {len(d)}")
        if 14000 <= len(d) <= 20000:
            near_16753.append((label, len(d)))
        print(f"  columns({len(d.columns)}): {', '.join(map(str, list(d.columns)[:34]))}{' ...' if len(d.columns) > 34 else ''}")
        if "Season" in d.columns:
            print(f"  Season: {_counts(pd.to_numeric(d['Season'], errors='coerce'))}")
        if "Week" in d.columns:
            cur_d = d[pd.to_numeric(d.get('Season'), errors='coerce') == cur] if (cur and 'Season' in d.columns) else d
            print(f"  Week (current season): {_counts(pd.to_numeric(cur_d['Week'], errors='coerce'))}")
        sidec = next((c for c in _SIDE_COLS if c in d.columns), None)
        resc = next((c for c in _RESULT_COLS if c in d.columns), None)
        valc = next((c for c in _VALUE_COLS if c in d.columns), None)
        if resc:
            print(f"  {resc} (current season): {_counts(d[pd.to_numeric(d.get('Season'), errors='coerce') == cur][resc] if cur and 'Season' in d.columns else d[resc])}")
        for dc in ("SnapshotDate", "GameDay", "GameDate", "Date"):
            if dc in d.columns:
                dts = pd.to_datetime(d[dc], errors="coerce").dropna()
                if not dts.empty:
                    print(f"  {dc} span: {dts.min()} .. {dts.max()}  (distinct days={dts.dt.normalize().nunique()})")
                break
        # Lane 2 graded: capture its board-schema fitness
        if path.name == "NFL_PropLines_Graded.csv":
            present = [c for c in BOARD_REQUIRED if c in d.columns]
            missing = [c for c in BOARD_REQUIRED if c not in d.columns]
            cur_rows = int((pd.to_numeric(d.get('Season'), errors='coerce') == cur).sum()) if (cur and 'Season' in d.columns) else 0
            graded_mask = None
            if resc:
                graded_mask = d[resc].astype(str).str.upper().isin(["OVER", "UNDER", "HIT", "MISS", "PUSH", "WIN", "LOSS"])
            lane2_graded = {
                "rows": len(d), "current_season_rows": cur_rows,
                "board_cols_present": present, "board_cols_missing": missing,
                "side_col": sidec, "result_col": resc, "value_col": valc,
                "graded_rows_est": int(graded_mask.sum()) if graded_mask is not None else None,
            }

    print("=" * 92)
    print("LINEAGE / 16,753 RECONCILIATION")
    print(f"  stores with 14k-20k rows (16,753 candidates): {near_16753 or 'none'}")
    if lane2_graded:
        print(f"  NFL_PropLines_Graded (Lane 2): rows={lane2_graded['rows']} current_season_rows={lane2_graded['current_season_rows']} "
              f"est_graded={lane2_graded['graded_rows_est']}")
        print(f"    side_col={lane2_graded['side_col']!r} result_col={lane2_graded['result_col']!r} value_col={lane2_graded['value_col']!r}")
        print(f"    board-required columns present: {lane2_graded['board_cols_present']}")
        print(f"    board-required columns MISSING : {lane2_graded['board_cols_missing']}")
        if lane2_graded["current_season_rows"] > 0:
            print("  => Lane 2 HOLDS current-season graded rows. If it also reaches the completed week, the "
                  "durable fix is to feed build_nfl_prop_streaks from NFL_PropLines_Graded (persistent, "
                  "run_daily's stated streak source) with a schema map for the MISSING columns above, "
                  "instead of the transient NFL_AllPropResults. No archive backfill / network needed.")
        else:
            print("  => Lane 2 has NO current-season graded rows -- confirm capture+grade are running on prod "
                  "and the archive is accruing; recovery may need the capture lane advanced, not a code swap.")
    else:
        print("  NFL_PropLines_Graded.csv ABSENT -- Lane 2 not materialized on this box.")

    fp1 = _fp(paths)
    changed = sorted(p for p in paths if fp0.get(p) != fp1.get(p))
    print("=" * 92)
    print(f"READ-ONLY PROOF: {len(paths)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        print(f"[FAIL] probe mutated: {changed}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
