"""
Read-only UPSTREAM-INPUT probe for the NFL prop-grading lane (incident 2026-10-24, Item-5 P0).

`diag_nfl_grading_receipt.py` characterized the OUTPUT (NFL_AllPropResults.csv): fresh by mtime, yet
ZERO current-season rows. This probe answers WHY, skew-free.

WHY SKEW MATTERS (a flaw in the first cut of this probe, now fixed): the on-disk output is written at one
time; the candidate archive is rebuilt on its own cadence. Comparing a freshly-read archive against an
older output cannot tell you whether the grader drops rows -- the two reflect different moments. And the
on-disk NFL_AllPropResults.csv carries one-off-BACKFILL columns (IsBackfill / GameDate / WindMph /
ModelVersion) that the in-season grader (grade_candidate_archive_rows + the load_candidate_archive
projection) CANNOT emit -- so a prior-season on-disk file may simply be the untouched one-off backfill,
not a dropped grade.

So this probe measures three skew-free things and never infers from mtime alone:
  (1) ON-DISK OUTPUT IDENTITY -- the output rows' own SnapshotDate season, IsBackfill, SnapshotWrittenAt,
      ModelVersion, Method. If the rows carry prior-season SnapshotDate / IsBackfill=1, the file ON DISK
      is the one-off backfill, independent of the grader.
  (2) LAST all_prop_results QC-LOG ENTRY -- did the in-season grader actually run, and what did it report
      (wrote N / SKIPPED stale gamelog)?
  (3) READ-ONLY DRY-RUN GRADE -- grade the CURRENT archive[Sport=='NFL'] against the CURRENT gamelog
      IN MEMORY (exactly as write_all_prop_results_snapshot_for_sport would, minus the write) and report
      how many current-season rows RESOLVE (get a Season) vs stay unresolved, with sample unresolved
      names + a gamelog name-form cross-check. This is what the grader would publish NOW.

VERDICT separates the two very different fixes:
  * GRADER_RESOLUTION_GAP : the current archive has current-season NFL candidates, the gamelog reaches the
      current season, yet the dry-run resolves ~none of them -> the grader's gamelog join is failing
      (almost certainly the full-name vs short-form identity mismatch, the Nico Collins bug in the
      MARKET-LINE grader). Fix = identity resolution in grade_candidate_archive_rows. DATA/CODE bug.
  * GRADER_OK_NOT_PUBLISHED : the dry-run DOES resolve current-season rows, but the on-disk file is still
      the prior-season backfill -> the grader's write is not landing (not running in run_daily, or the
      backfill clobbers it). OPS/pipeline bug, not a resolver bug.
  * STALE_BACKFILL_ONLY : on-disk file is the one-off backfill AND the archive currently has no current-
      season NFL candidates -> nothing to grade yet (input timing).
  * HEALTHY : dry-run resolves current-season rows and the on-disk file reflects them.

LITERAL read-only: no network/provider call; reads local CSVs + the in-memory cache; calls only PURE
helpers (`load_candidate_archive`, `load_nfl_gamelogs`, `grade_candidate_archive_rows` -- which returns a
DataFrame and writes nothing; verified app.py 12693-12840 -- `_nfl_gamelog_stale`,
`_nfl_expected_completed_week`); NEVER a `write_*`/`replace_*`. `append_qc_run_log` is monkeypatched to a
no-op. Every touched artifact is sha256+mtime+size fingerprinted BEFORE and AFTER; exit 4 if anything
changed. Current season via `_nfl_expected_completed_week` -- never a global max(Season)/max(Week).

Exit codes: 0 coherent read; 2 a needed artifact absent/unreadable; 3 a diagnosed defect
(GRADER_RESOLUTION_GAP / GRADER_OK_NOT_PUBLISHED) or internal contradiction; 4 the diagnostic mutated an
artifact (should never happen).

Run on the box with the data (prod/owner), venv python. No fetch, no paid call, no writes:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_grading_input.py
"""
from __future__ import annotations

import glob
import hashlib
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import app

# Belt-and-suspenders: no QC-log write can happen through this diagnostic.
app.append_qc_run_log = lambda *a, **k: None

ARCHIVE = app.CANDIDATE_ARCHIVE_PATH
OUTPUT = app.DATA_DIR / "tracking" / "NFL_AllPropResults.csv"
GAMELOG = app.DATA_DIR / "gamelogs" / "NFL_GameLogs.csv"
QCLOG = app.DATA_DIR / "tracking" / "QC_Run_Log.csv"
_ARCHIVE_DATE_COLS = ("SnapshotDate", "GameDay", "SavedAt")


def _et(ts_epoch: float) -> str:
    try:
        iso = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts_epoch)


def _relevant_artifacts() -> list[str]:
    files = {str(ARCHIVE), str(OUTPUT), str(GAMELOG), str(QCLOG)}
    for base in (app.DATA_DIR, app.DATA_DIR / "tracking", app.DATA_DIR / "cache", app.DATA_DIR / "gamelogs"):
        for pat in ("*CandidateArchive*", "*NFL_AllPropResults*", "*NFL_GameLogs*", "*nflverse_stats*"):
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
    """NFL season a date belongs to: on/after ~Aug 1 -> that calendar year; Jan-Jul -> previous year."""
    dts = pd.to_datetime(date_series, errors="coerce")
    yr = dts.dt.year
    return yr.where(dts.dt.month >= 8, yr - 1)


def _top_counts(series: pd.Series, n: int = 6) -> str:
    try:
        vc = series.astype(str).str.strip().replace("", "(blank)").value_counts().head(n)
        return ", ".join(f"{k}={int(v)}" for k, v in vc.items())
    except Exception:
        return "(n/a)"


def main() -> int:
    print("=" * 84)
    print("NFL PROP-GRADING LANE -- UPSTREAM INPUT PROBE v2 (read-only, skew-free, Item-5 P0)")
    print("=" * 84)

    artifacts = _relevant_artifacts()
    fp_before = _fingerprint(artifacts)

    try:
        expected_week, expected_season = app._nfl_expected_completed_week()
    except Exception as exc:
        expected_week, expected_season = None, None
        print(f"[WARN] season resolver error: {exc}")
    print(f"resolver_current_season : {expected_season}")
    print(f"resolver_completed_week : {expected_week}")
    cur_season = int(expected_season) if expected_season else None

    # ---- (1) ON-DISK OUTPUT IDENTITY (skew-free: what the file on disk actually IS) ----------------
    print("-" * 84)
    print(f"ON-DISK OUTPUT   : {OUTPUT}")
    output_is_backfill = None
    output_cur_resolved = None
    if not OUTPUT.exists():
        print("  ABSENT")
    else:
        ost = OUTPUT.stat()
        age_h = round((datetime.now().timestamp() - ost.st_mtime) / 3600, 2)
        print(f"  mtime          : {_et(ost.st_mtime)}  ({age_h}h ago)")
        try:
            od = pd.read_csv(OUTPUT, low_memory=False)
        except Exception as exc:
            print(f"  UNREADABLE     : {type(exc).__name__}: {exc}")
            return 2
        print(f"  total_rows     : {len(od)}")
        if "SnapshotDate" in od.columns:
            snap_season = _season_of(od["SnapshotDate"]).dropna().astype(int)
            print(f"  SnapshotDate season (what was PICKED): {_top_counts(snap_season)}")
        if "Season" in od.columns:
            res_season = pd.to_numeric(od["Season"], errors="coerce").dropna().astype(int)
            print(f"  Season (RESULT game)                : {_top_counts(res_season)}")
            if cur_season is not None:
                output_cur_resolved = int((pd.to_numeric(od["Season"], errors="coerce") == cur_season).sum())
        for col in ("IsBackfill", "ModelVersion", "Method", "OutcomeState", "SeasonType"):
            if col in od.columns:
                print(f"  {col:12} : {_top_counts(od[col])}")
        if "SnapshotWrittenAt" in od.columns:
            sw = od["SnapshotWrittenAt"].astype(str).str.strip()
            nonblank = sw[sw != ""]
            print(f"  SnapshotWrittenAt: blanks={int((sw == '').sum())} "
                  f"range={nonblank.min() if not nonblank.empty else 'n/a'}..{nonblank.max() if not nonblank.empty else 'n/a'}")
        # the file ON DISK is the one-off backfill when its picks are prior-season and/or flagged backfill
        bf_flag = False
        if "IsBackfill" in od.columns:
            bf_flag = bool((pd.to_numeric(od["IsBackfill"], errors="coerce").fillna(0) > 0).any())
        snap_is_prior = False
        if "SnapshotDate" in od.columns and cur_season is not None:
            ss = _season_of(od["SnapshotDate"]).dropna().astype(int)
            snap_is_prior = bool(not ss.empty and (ss == cur_season).sum() == 0)
        output_is_backfill = bool(bf_flag or snap_is_prior)
        print(f"  -> on-disk file is {'the one-off BACKFILL' if output_is_backfill else 'a GRADER snapshot'}"
              f" (IsBackfill_present={bf_flag}, picks_all_prior_season={snap_is_prior})")

    # ---- current archive + gamelog + guard ---------------------------------------------------------
    print("-" * 84)
    arc = None
    archive_cur_rows = 0
    if not ARCHIVE.exists():
        print(f"ARCHIVE (input)  : {ARCHIVE}  ABSENT")
    else:
        print(f"ARCHIVE (input)  : {ARCHIVE}  ({_et(ARCHIVE.stat().st_mtime)})")
        try:
            arc = app.load_candidate_archive()
        except Exception as exc:
            print(f"  UNREADABLE     : {type(exc).__name__}: {exc}")
            return 2
        nfl = arc[arc["Sport"].astype(str).str.upper() == "NFL"].copy() if "Sport" in arc.columns else arc.iloc[0:0]
        date_col = next((c for c in _ARCHIVE_DATE_COLS if c in nfl.columns), None)
        if len(nfl) and date_col and cur_season is not None:
            s = _season_of(nfl[date_col]).dropna().astype(int)
            archive_cur_rows = int((s == cur_season).sum())
            print(f"  NFL_rows={len(nfl)}  by season ({date_col}): {_top_counts(s)}   current({cur_season})={archive_cur_rows}")
        else:
            print(f"  NFL_rows={len(nfl)}  (no usable date col / season)")

    try:
        gl = app.load_nfl_gamelogs()
        gl_ok = gl is not None and not gl.empty
        gl_max_season = int(pd.to_numeric(gl.get("Season"), errors="coerce").max()) if gl_ok and "Season" in gl.columns else None
        gl_players = set(gl["Player"].astype(str)) if gl_ok and "Player" in gl.columns else set()
    except Exception as exc:
        gl, gl_ok, gl_max_season, gl_players = None, False, None, set()
        print(f"[WARN] load_nfl_gamelogs error: {exc}")
    print(f"GAMELOG          : {GAMELOG} exists={GAMELOG.exists()} max_season={gl_max_season} players={len(gl_players)}")
    try:
        from refresh_all_prop_results import _nfl_gamelog_stale
        guard_reason = _nfl_gamelog_stale(gl)
    except Exception as exc:
        guard_reason = f"(guard check error: {exc})"
    print(f"GUARD (stale?)   : {'TRIPPED -> grader skips write' if guard_reason else 'passed -> writer runs'}"
          f"{' :: ' + guard_reason if guard_reason else ''}")

    # ---- (2) last all_prop_results QC-log entry ----------------------------------------------------
    print("-" * 84)
    if QCLOG.exists():
        try:
            q = pd.read_csv(QCLOG, low_memory=False)
            name_col = next((c for c in q.columns if q[c].astype(str).str.contains("all_prop_results", na=False).any()), None)
            if name_col is not None:
                rows = q[q[name_col].astype(str).str.contains("all_prop_results", na=False)]
                last = rows.iloc[-1]
                shown = {k: last[k] for k in q.columns if str(last[k]).strip() and k != name_col}
                print("LAST all_prop_results QC entry:")
                for k, v in list(shown.items())[:8]:
                    print(f"    {k}: {str(v)[:140]}")
            else:
                print("LAST all_prop_results QC entry: (none found in QC_Run_Log.csv)")
        except Exception as exc:
            print(f"LAST all_prop_results QC entry: (unreadable: {exc})")
    else:
        print("LAST all_prop_results QC entry: (QC_Run_Log.csv absent)")

    # ---- (3) READ-ONLY DRY-RUN GRADE of the CURRENT archive (what the grader would publish NOW) -----
    print("-" * 84)
    print("DRY-RUN GRADE (read-only, in memory; no write) of current archive[NFL] vs current gamelog:")
    dry_cur_resolved = dry_cur_total = None
    sample_unresolved = []
    if arc is None or not gl_ok:
        print("  SKIPPED (archive or gamelog unavailable)")
    else:
        try:
            sport_archive = arc[arc["Sport"].astype(str).str.upper() == "NFL"].copy()
            graded = app.grade_candidate_archive_rows(sport_archive, gamelog_map={"NFL": gl})
            if graded is None or graded.empty:
                print("  grader returned EMPTY for NFL archive")
                dry_cur_total = dry_cur_resolved = 0
            else:
                g = graded.copy()
                g["__pick_season"] = _season_of(g["SnapshotDate"]) if "SnapshotDate" in g.columns else np.nan
                cur = g[g["__pick_season"] == cur_season] if cur_season is not None else g
                dry_cur_total = int(len(cur))
                res_mask = pd.to_numeric(cur.get("Season"), errors="coerce").notna()
                dry_cur_resolved = int(res_mask.sum())
                print(f"  current-season picks graded : total={dry_cur_total}  RESOLVED(Season set)={dry_cur_resolved}  "
                      f"unresolved={dry_cur_total - dry_cur_resolved}")
                if "Season" in cur.columns:
                    print(f"  resolved RESULT seasons     : {_top_counts(pd.to_numeric(cur['Season'], errors='coerce').dropna().astype(int))}")
                if "OutcomeState" in cur.columns:
                    print(f"  resolved OutcomeState       : {_top_counts(cur['OutcomeState'])}")
                # expose the identity mismatch: unresolved current-season players vs gamelog name forms
                if dry_cur_total - dry_cur_resolved > 0 and "Player" in cur.columns:
                    un = cur[~res_mask]
                    names = list(dict.fromkeys(un["Player"].astype(str).str.strip().tolist()))[:8]
                    for nm in names:
                        in_gl_exact = nm in gl_players
                        # short form: first-initial.last
                        parts = nm.replace(".", " ").split()
                        short = (parts[0][:1] + "." + parts[-1]) if len(parts) >= 2 else nm
                        in_gl_short = any(short.lower() == p.lower() for p in gl_players)
                        sample_unresolved.append((nm, in_gl_exact, in_gl_short))
                    print("  sample unresolved current-season picks (name | in_gamelog_exact | in_gamelog_shortform):")
                    for nm, ex, sh in sample_unresolved:
                        print(f"      {nm:28} exact={ex}  shortform={sh}")
        except Exception as exc:
            print(f"  DRY-RUN ERROR: {type(exc).__name__}: {exc}")

    # ---- read-only proof + verdict -----------------------------------------------------------------
    fp_after = _fingerprint(artifacts)
    changed = sorted(p for p in artifacts if fp_before.get(p) != fp_after.get(p))
    print("-" * 84)
    print(f"READ-ONLY PROOF  : {len(artifacts)} artifact(s) fingerprinted (sha256+mtime_ns+size); "
          f"{'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")

    problems = []
    if changed:
        problems.append(f"diagnostic mutated artifact(s): {changed}")
    if cur_season is None:
        problems.append("season resolver returned None (cannot characterize current season)")

    print("-" * 84)
    gamelog_reaches_current = bool(gl_max_season and cur_season and gl_max_season >= cur_season)
    dry_resolves = bool(dry_cur_resolved and dry_cur_resolved > 0)

    if guard_reason:
        verdict = f"GUARD_TRIPPED: {guard_reason}. The grader skips the NFL write; rebuild the gamelog first."
        problems.append(verdict)
    elif archive_cur_rows and gamelog_reaches_current and dry_cur_total and not dry_resolves:
        shortform_hits = sum(1 for _, ex, sh in sample_unresolved if (sh and not ex))
        verdict = ("GRADER_RESOLUTION_GAP: current archive has current-season NFL candidates and the "
                   f"gamelog reaches {gl_max_season}, but the DRY-RUN grade resolves 0 of {dry_cur_total} "
                   "current-season picks -- the grader's gamelog join is failing"
                   + (f"; {shortform_hits}/{len(sample_unresolved)} sampled unresolved players match the "
                      "gamelog ONLY in short form (full-name vs 'N.Collins' identity mismatch -- the "
                      "Nico Collins bug in the MARKET-LINE grader)." if shortform_hits else
                      " (see sample unresolved names above).")
                   + " Fix = identity resolution in grade_candidate_archive_rows. CODE bug.")
        problems.append(verdict)
    elif dry_resolves and output_is_backfill:
        verdict = ("GRADER_OK_NOT_PUBLISHED: the DRY-RUN grade DOES resolve current-season rows "
                   f"({dry_cur_resolved}/{dry_cur_total}), but the on-disk NFL_AllPropResults.csv is still "
                   "the one-off prior-season backfill -- the in-season grader's write is NOT landing "
                   "(refresh_all_prop_results not running in run_daily on prod, or a backfill clobbers it). "
                   "OPS/pipeline fix, not a resolver fix.")
        problems.append(verdict)
    elif not archive_cur_rows and output_is_backfill:
        verdict = ("STALE_BACKFILL_ONLY: on-disk file is the one-off backfill and the archive currently "
                   "has no current-season NFL candidates -- nothing to grade yet (input timing). Re-check "
                   "after the archive populates.")
    elif dry_resolves and output_cur_resolved:
        verdict = "HEALTHY: dry-run resolves current-season rows and the on-disk file reflects them."
    else:
        verdict = ("INCONCLUSIVE: state does not match a known branch -- see the blocks above "
                   f"(archive_cur={archive_cur_rows}, gamelog_reaches_current={gamelog_reaches_current}, "
                   f"dry_resolved={dry_cur_resolved}/{dry_cur_total}, on_disk_backfill={output_is_backfill}, "
                   f"on_disk_cur_resolved={output_cur_resolved}).")
        problems.append(verdict)

    print(f"VERDICT          : {verdict}")
    print("-" * 84)
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 4 if changed else 3
    print("[OK] coherent read; diagnostic changed nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
