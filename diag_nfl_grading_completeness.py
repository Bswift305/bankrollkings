"""
Read-only COMPLETENESS reconciliation for the NFL in-season grader (incident 2026-10-24, Item-5).

The clobber is proven (diag_nfl_grading_input.py). But the dry-run grade resolved only 86 current-season
rows, which must be reconciled against the earlier production claim of "~16,753 graded through Week 6"
BEFORE declaring the grader healthy -- otherwise we fix the clobber and miss a second grading-COVERAGE
defect (e.g. the grader rebuilds NFL_AllPropResults.csv from the CURRENT archive by replace, so if the
archive is pruned to recent snapshots the live file can never hold Weeks 1-6, regardless of the clobber).

This probe characterizes, for the resolved current season, WHAT the live grader can actually produce from
the archive NOW, broken down so the 86-vs-16,753 gap is explained with evidence (not asserted):

  * archive current-season NFL candidates by GameDay-week (does the archive even HOLD Weeks 1-6?);
  * completed-game vs future-game candidates by week (completed = GameDay <= gamelog data-through);
  * of the COMPLETED-game candidates, how many the dry-run grade RESOLVES vs leaves unresolved
    (a completed-game candidate that does not resolve is a real resolution defect; a future-game
    candidate that is Pending is correct);
  * graded Hit/Miss/Push by week; Pending by week split into future-game (expected) vs
    completed-but-unresolved (DEFECT);
  * gamelog data-through (max date / max week) and the resolver's expected completed week;
  * SnapshotDate spread (is the archive retaining history, or only recent slates?);
  * duplicates / identity collisions in the current-season candidates;
  * a reconciliation line: resolvable completed-game candidates vs the 16,753 claim, with the most
    likely grain explanation.

A completed-game candidate is NEVER labeled "future". The 16,753 figure, if it came from a different
grain (repeated daily snapshots, the Scored file, or the historical backfill), is flagged as such.

LITERAL read-only: no network; reads local CSVs + in-memory cache; calls only PURE helpers
(`load_candidate_archive`, `load_nfl_gamelogs`, `grade_candidate_archive_rows` -- returns a DataFrame,
writes nothing; `_nfl_expected_completed_week`); NEVER a `write_*`/`replace_*`. `append_qc_run_log` is a
no-op here. Every touched artifact is sha256+mtime+size fingerprinted BEFORE and AFTER; exit 4 if changed.
Current season via `_nfl_expected_completed_week` -- never a global max(Season)/max(Week).

Exit codes: 0 reconciled (gap explained, no completed-but-unresolved rows); 2 artifact absent/unreadable;
3 a coverage/resolution defect (completed-game candidates that do not resolve) OR mutation; always prints
the full breakdown first.

Run on the box (prod/owner), venv python, no writes:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_grading_completeness.py
"""
from __future__ import annotations

import glob
import hashlib
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None

ARCHIVE = app.CANDIDATE_ARCHIVE_PATH
OUTPUT = app.DATA_DIR / "tracking" / "NFL_AllPropResults.csv"
GAMELOG = app.DATA_DIR / "gamelogs" / "NFL_GameLogs.csv"
_ARCHIVE_DATE_COLS = ("GameDay", "SnapshotDate", "SavedAt")


def _et(ts: float) -> str:
    try:
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts)


def _artifacts() -> list[str]:
    files = {str(ARCHIVE), str(OUTPUT), str(GAMELOG)}
    for base in (app.DATA_DIR, app.DATA_DIR / "tracking", app.DATA_DIR / "cache", app.DATA_DIR / "gamelogs"):
        for pat in ("*CandidateArchive*", "*NFL_AllPropResults*", "*NFL_GameLogs*", "*nflverse_stats*"):
            files.update(glob.glob(str(base / pat)))
    return sorted(files)


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


def _season_of(s: pd.Series) -> pd.Series:
    dts = pd.to_datetime(s, errors="coerce")
    return dts.dt.year.where(dts.dt.month >= 8, dts.dt.year - 1)


def main() -> int:
    print("=" * 88)
    print("NFL IN-SEASON GRADER -- COMPLETENESS RECONCILIATION (read-only, Item-5; 86 vs 16,753)")
    print("=" * 88)
    arts = _artifacts()
    fp0 = _fp(arts)

    try:
        exp_week, exp_season = app._nfl_expected_completed_week()
    except Exception as exc:
        exp_week, exp_season = None, None
        print(f"[WARN] resolver: {exc}")
    cur = int(exp_season) if exp_season else None
    print(f"resolver_current_season={exp_season}  resolver_completed_week={exp_week}")
    if cur is None:
        print("[FAIL] resolver returned no current season; cannot reconcile.")
        return 3

    # ---- gamelog: data-through + a date->week map (to bucket candidates by week) -------------------
    try:
        gl = app.load_nfl_gamelogs()
    except Exception as exc:
        print(f"[FAIL] load_nfl_gamelogs: {exc}")
        return 2
    if gl is None or gl.empty or "Date" not in gl.columns:
        print("[FAIL] gamelog empty / no Date column.")
        return 2
    gl = gl.copy()
    gl["Date"] = pd.to_datetime(gl["Date"], errors="coerce")
    gl_cur = gl[pd.to_numeric(gl.get("Season"), errors="coerce") == cur] if "Season" in gl.columns else gl
    gl_through_date = gl_cur["Date"].max()
    gl_through_week = int(pd.to_numeric(gl_cur.get("Week"), errors="coerce").dropna().max()) if "Week" in gl_cur.columns and not gl_cur.empty else None
    print(f"gamelog_data_through: date={gl_through_date}  week={gl_through_week}  (current-season rows={len(gl_cur)})")
    # date -> week map for the current season
    date_week = {}
    if "Week" in gl_cur.columns:
        for d, w in zip(gl_cur["Date"], pd.to_numeric(gl_cur["Week"], errors="coerce")):
            if pd.notna(d) and pd.notna(w):
                date_week[pd.Timestamp(d).normalize()] = int(w)

    def _week_of(game_day):
        d = pd.to_datetime(game_day, errors="coerce")
        if pd.isna(d):
            return None
        d0 = pd.Timestamp(d).normalize()
        if d0 in date_week:
            return date_week[d0]
        # nearest game date within 3 days (Thu-Mon slate tolerance)
        for off in (1, -1, 2, -2, 3, -3):
            cand = d0 + pd.Timedelta(days=off)
            if cand in date_week:
                return date_week[cand]
        return None

    # ---- archive current-season NFL candidates -----------------------------------------------------
    try:
        arc = app.load_candidate_archive()
    except Exception as exc:
        print(f"[FAIL] load_candidate_archive: {exc}")
        return 2
    nfl = arc[arc["Sport"].astype(str).str.upper() == "NFL"].copy() if "Sport" in arc.columns else arc.iloc[0:0]
    gd_col = next((c for c in _ARCHIVE_DATE_COLS if c in nfl.columns), None)
    if gd_col is None or nfl.empty:
        print("[FAIL] no NFL archive rows / no date column.")
        return 3
    nfl["__game_day"] = pd.to_datetime(nfl[gd_col], errors="coerce")
    nfl["__pick_season"] = _season_of(nfl[gd_col])
    cur_arc = nfl[nfl["__pick_season"] == cur].copy()
    print("-" * 88)
    print(f"ARCHIVE current-season({cur}) NFL candidates: {len(cur_arc)}   (date col: {gd_col!r})")
    sd = pd.to_datetime(cur_arc.get("SnapshotDate"), errors="coerce") if "SnapshotDate" in cur_arc.columns else pd.Series([], dtype="datetime64[ns]")
    if not sd.dropna().empty:
        print(f"  SnapshotDate spread: {sd.min()} .. {sd.max()}  (distinct days={sd.dt.normalize().nunique()})")
    cur_arc["__week"] = cur_arc["__game_day"].map(_week_of)
    if pd.notna(gl_through_date):
        completed_mask = cur_arc["__game_day"].notna() & (cur_arc["__game_day"] <= gl_through_date)
    else:
        completed_mask = pd.Series(False, index=cur_arc.index)
    future_mask = cur_arc["__game_day"].notna() & (cur_arc["__game_day"] > gl_through_date) if pd.notna(gl_through_date) else cur_arc["__game_day"].notna()
    no_gd = cur_arc["__game_day"].isna()
    print(f"  by GameDay: completed(<= data-through)={int(completed_mask.sum())}  "
          f"future(> data-through)={int(future_mask.sum())}  no_game_day={int(no_gd.sum())}")
    wk_counts = cur_arc["__week"].value_counts(dropna=True).sort_index()
    print(f"  candidates by mapped week: {{" + ", ".join(f'{int(w)}:{int(n)}' for w, n in wk_counts.items()) + "}")
    print(f"  (unmapped to any week: {int(cur_arc['__week'].isna().sum())})")

    # identity collisions
    idkey = [c for c in ("Player", "Stat", "Direction", "Line", "GameDay") if c in cur_arc.columns]
    dups = int(cur_arc.duplicated(subset=idkey, keep=False).sum()) if idkey else 0
    print(f"  duplicate candidate rows (key {idkey}): {dups}")

    # ---- dry-run grade (read-only) -----------------------------------------------------------------
    print("-" * 88)
    print("DRY-RUN GRADE (read-only, in memory) of current-season archive vs current gamelog:")
    graded = app.grade_candidate_archive_rows(cur_arc.drop(columns=["__game_day", "__pick_season", "__week"], errors="ignore"),
                                              gamelog_map={"NFL": gl})
    completed_unresolved_defect = 0
    if graded is None or graded.empty:
        print("  grader returned EMPTY")
    else:
        g = graded.copy()
        g["__game_day"] = pd.to_datetime(g.get("GameDay"), errors="coerce")
        g["__resolved"] = pd.to_numeric(g.get("Season"), errors="coerce").notna()
        res = g[g["__resolved"]]
        print(f"  total current-season picks graded: {len(g)}   RESOLVED={int(g['__resolved'].sum())}   "
              f"unresolved={int((~g['__resolved']).sum())}")
        if "Week" in res.columns and not res.empty:
            byw = res.groupby(pd.to_numeric(res["Week"], errors="coerce").astype("Int64"))
            print("  RESOLVED by week (Hit/Miss/Push/Pending):")
            for w, grp in byw:
                oc = grp["OutcomeState"].astype(str).value_counts() if "OutcomeState" in grp.columns else {}
                print(f"      wk {w}: n={len(grp)}  " + " ".join(f"{k}={int(v)}" for k, v in dict(oc).items()))
        # unresolved split: future (correct) vs completed-but-unresolved (DEFECT)
        un = g[~g["__resolved"]]
        if pd.notna(gl_through_date):
            comp_un = un[un["__game_day"].notna() & (un["__game_day"] <= gl_through_date)]
            fut_un = un[un["__game_day"].isna() | (un["__game_day"] > gl_through_date)]
            completed_unresolved_defect = int(len(comp_un))
            print(f"  unresolved split: future/no-gameday(correct Pending)={int(len(fut_un))}  "
                  f"COMPLETED-but-unresolved(DEFECT)={completed_unresolved_defect}")
            if completed_unresolved_defect:
                cols = [c for c in ("Player", "Stat", "Direction", "Line", "GameDay", "Team") if c in comp_un.columns]
                print("  sample completed-but-unresolved (should have graded):")
                print(comp_un[cols].head(10).to_string(index=False))

    # ---- reconciliation vs 16,753 ------------------------------------------------------------------
    resolvable = int(completed_mask.sum())
    resolved_now = int(g["__resolved"].sum()) if (graded is not None and not graded.empty) else 0
    print("-" * 88)
    print("RECONCILIATION (86 vs 16,753):")
    print(f"  archive completed-game current-season candidates (resolvable) : {resolvable}")
    print(f"  dry-run resolved current-season rows                          : {resolved_now}")
    print(f"  earlier production claim                                      : ~16,753 graded through Wk6")
    if resolvable <= 500:
        print("  => the archive holds few completed-game current-season candidates, so the live grader can "
              "produce only a small current-season population NOW. If 16,753 was real, it came from a "
              "DIFFERENT grain (accumulated daily snapshots / the Scored file / the historical backfill) "
              "or the archive has since been pruned -- a RETENTION/accumulation concern distinct from the "
              "clobber. Confirm the grain of the 16,753 receipt.")
    elif completed_unresolved_defect == 0 and abs(resolvable - resolved_now) <= max(5, int(0.02 * resolvable)):
        print("  => the grader resolves essentially all resolvable completed-game candidates; 86 was a "
              "point-in-time count. If 16,753 differs, it is a grain difference, not a grader defect.")
    else:
        print("  => resolvable completed-game candidates exist that the grader did NOT resolve -- a real "
              "resolution/coverage defect to fix alongside the clobber (see sample above).")

    fp1 = _fp(arts)
    changed = sorted(p for p in arts if fp0.get(p) != fp1.get(p))
    print("-" * 88)
    print(f"READ-ONLY PROOF : {len(arts)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        print(f"[FAIL] diagnostic mutated: {changed}")
        return 3
    if completed_unresolved_defect:
        print(f"[FAIL] {completed_unresolved_defect} completed-game current-season candidates did not resolve "
              "(coverage/resolution defect).")
        return 3
    print("[OK] read-only; breakdown above reconciles the current-season population.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
