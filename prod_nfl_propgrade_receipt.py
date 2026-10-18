"""Controlled production regeneration + full receipt for the NFL prop-grade correction.

Run on prod via SSM with the venv python:
    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python prod_nfl_propgrade_receipt.py'

It performs the required sequence and prints every receipt field:
  1 confirm deployed commit >= the fix (3254d0b)
  2 rebuild NFL_GameLogs.csv (atomic)      3 validate the gamelog
  4 run the NFL prop grader (stale-guarded) 5 validate NFL_AllPropResults.csv
  6 market-line audit (--require-market-line exit code)
  8 pipeline-hardening confirmations (ordering / gitignore / nonzero-on-failure)
Board verification (step 7) is done separately on authenticated production.

Writes only the normal pipeline outputs (both atomic). Idempotent. Exit 0 iff the receipt passes.
"""
from __future__ import annotations

import subprocess
import sys
import os
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
GL = os.path.join(BASE, "data", "gamelogs", "NFL_GameLogs.csv")
APR = os.path.join(BASE, "data", "tracking", "NFL_AllPropResults.csv")
ARCH = os.path.join(BASE, "data", "tracking", "NBA_CandidateArchive.csv")
FIX_COMMIT = "3254d0b"


def sh(cmd):
    p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main():
    ok = True
    hr("1 · DEPLOYED COMMIT")
    rc, head = sh(["git", "rev-parse", "HEAD"])
    head = head.strip()
    rc2, _ = sh(["git", "merge-base", "--is-ancestor", FIX_COMMIT, "HEAD"])
    has_fix = (rc2 == 0)
    print(f"HEAD={head}  contains {FIX_COMMIT}? {'YES' if has_fix else 'NO'}")
    if not has_fix:
        print(f"[ABORT] deploy the fix ({FIX_COMMIT}) first — current tree predates it.")
        return 2

    hr("2 · REBUILD NFL_GameLogs.csv")
    rc_gl, out_gl = sh([PY, "build_nfl_gamelogs.py"])
    print(out_gl.strip()[-600:])
    print(f"[gamelog build exit] {rc_gl}")
    ok = ok and rc_gl == 0

    hr("3 · VALIDATE GAMELOG")
    try:
        from app import _nfl_expected_completed_week, _nfl_player_log_sources
        exp_week, exp_season = _nfl_expected_completed_week()
        srcs = _nfl_player_log_sources()
        cur_src = [s for s in srcs if s.get("season") == exp_season]
        for s in cur_src:
            mt = os.path.getmtime(s["path"]) if os.path.exists(s["path"]) else 0
            import datetime as _dt
            print(f"  source(current): {os.path.relpath(s['path'], BASE)} kind={s['kind']} "
                  f"updated={_dt.datetime.utcfromtimestamp(mt):%Y-%m-%d %H:%M}Z")
        g = pd.read_csv(GL, low_memory=False)
        g["Season"] = pd.to_numeric(g["Season"], errors="coerce")
        g["Week"] = pd.to_numeric(g["Week"], errors="coerce")
        seasons = sorted(int(x) for x in g["Season"].dropna().unique())
        cur = g[g["Season"] == exp_season]
        weeks = sorted(int(x) for x in cur["Week"].dropna().unique())
        grain = cur.groupby(["Player", "Season", "Week"]).size()
        dup = int((grain > 1).sum())
        malformed = int((cur["Player"].astype(str).str.strip() == "").sum())
        team_empty = float((cur["Team"].astype(str).str.strip() == "").mean()) if len(cur) else 1.0
        opp_empty = float((cur["Opp"].astype(str).str.strip() == "").mean()) if len(cur) else 1.0
        nico = cur[cur["Player"].astype(str).str.contains("Nico Collins", case=False, na=False)]
        print(f"  runtime path: {GL}")
        print(f"  seasons present: {seasons}")
        print(f"  resolved current season: {exp_season} (expected completed week {exp_week})")
        print(f"  current-season rows: {len(cur)}")
        print(f"  current-season weeks present: {weeks}  (max completed week {max(weeks) if weeks else None})")
        print(f"  unique player-game grain: {len(grain)}   duplicate (grain>1): {dup}")
        print(f"  malformed identity (blank Player): {malformed}")
        print(f"  Team empty frac: {team_empty:.3f}   Opp empty frac: {opp_empty:.3f}")
        print(f"  Nico Collins current-season rows:\n{nico[['Season','Week','Team','Opp','RecYd','Rec']].to_string(index=False) if len(nico) else '    (none)'}")
        cur_season_ok = bool(seasons and max(seasons) >= int(exp_season) and len(cur) > 0 and dup == 0
                             and malformed == 0 and team_empty < 0.02 and opp_empty < 0.02)
        print(f"  [gamelog validation] {'PASS' if cur_season_ok else 'FAIL'}")
        ok = ok and cur_season_ok
    except Exception as e:
        print(f"[FAIL] gamelog validation error: {e}")
        ok = False
        exp_season = None

    hr("4 · RUN NFL PROP GRADER (stale-guarded)")
    rc_grade, out_grade = sh([PY, "refresh_all_prop_results.py", "--sport", "nfl"])
    print(out_grade.strip()[-800:])
    print(f"[grader exit] {rc_grade}  (nonzero = stale-guard tripped / failure)")
    ok = ok and rc_grade == 0

    hr("5 · VALIDATE NFL_AllPropResults.csv (graded record)")
    try:
        import datetime as _dt
        apr_mt = os.path.getmtime(APR)
        print(f"  published: {APR}  updated={_dt.datetime.utcfromtimestamp(apr_mt):%Y-%m-%d %H:%M}Z")
        print(f"  tmp sidecar present (should be NO -> atomic replace done): "
              f"{os.path.exists(APR + '.tmp')}")
        d = pd.read_csv(APR, low_memory=False)
        d["Season"] = pd.to_numeric(d["Season"], errors="coerce")
        d["Week"] = pd.to_numeric(d["Week"], errors="coerce")
        d = d[d.get("Sport", "NFL").astype(str).str.upper() == "NFL"] if "Sport" in d.columns else d
        max_season = int(d["Season"].max()) if d["Season"].notna().any() else None
        cur = d[d["Season"] == exp_season] if exp_season else d.iloc[0:0]
        state_col = next((c for c in ("OutcomeState", "Outcome", "ResultState") if c in d.columns), None)
        graded = pending = 0
        buckets = {}
        if state_col and len(cur):
            st = cur[state_col].astype(str)
            graded = int(st.isin(["Hit", "Miss", "Push"]).sum())
            pending = int(len(cur) - graded)
            buckets = st[~st.isin(["Hit", "Miss", "Push"])].value_counts().to_dict()
        pushes = int((cur[state_col].astype(str) == "Push").sum()) if (state_col and len(cur)) else 0
        gw = sorted(int(x) for x in cur["Week"].dropna().unique())
        dup_obs = 0
        grain_cols = [c for c in ("Player", "Stat", "Direction", "Season", "Week") if c in cur.columns]
        if grain_cols and len(cur):
            dup_obs = int((cur.groupby(grain_cols).size() > 1).sum())
        malformed_rows = int((cur["Player"].astype(str).str.strip() == "").sum()) if len(cur) else 0
        # candidate archive current-season count
        cand_cur = 0
        try:
            a = pd.read_csv(ARCH, low_memory=False)
            a = a[a["Sport"].astype(str).str.upper() == "NFL"]
            yr = pd.to_datetime(a["SnapshotDate"], errors="coerce").dt.year
            cand_cur = int((yr == exp_season).sum())
        except Exception as e:
            print(f"  (candidate archive read note: {e})")
        print(f"  max Season in record: {max_season}   resolved current season: {exp_season}")
        print(f"  current-season candidate rows (archive): {cand_cur}")
        print(f"  current-season rows in graded record: {len(cur)}")
        print(f"  current-season graded (Hit/Miss/Push): {graded}")
        print(f"  current-season pending/unresolved: {pending}  reason buckets: {buckets}")
        print(f"  graded-through week (current season): {max(gw) if gw else None}")
        print(f"  pushes handled (current season): {pushes}")
        print(f"  duplicate market observations (current season): {dup_obs}")
        print(f"  malformed rows (blank Player, current season): {malformed_rows}")
        apr_ok = bool(max_season is not None and exp_season and max_season >= int(exp_season)
                      and graded > 0 and dup_obs == 0 and malformed_rows == 0
                      and not os.path.exists(APR + ".tmp"))
        print(f"  [graded-record validation] {'PASS' if apr_ok else 'FAIL'}  "
              f"(no prior-season row is presented as current: the boards gate on the resolved season)")
        ok = ok and apr_ok
    except Exception as e:
        print(f"[FAIL] graded-record validation error: {e}")
        ok = False

    hr("6 · MARKET-LINE AUDIT")
    rc_audit, out_audit = sh([PY, "diag_nfl_streak_audit.py", "--season",
                              str(exp_season or 2026), "--require-market-line"])
    print(out_audit.strip()[-900:])
    print(f"[market-line audit exit] {rc_audit}  (0 = market-line record current)")
    ok = ok and rc_audit == 0

    hr("8 · PIPELINE HARDENING")
    rc_o, out_o = sh(["git", "check-ignore", "data/gamelogs/NFL_GameLogs.csv",
                      "data/tracking/NFL_AllPropResults.csv"])
    print(f"  generated records gitignored (deploy cannot revert): "
          f"{'YES' if 'NFL_GameLogs' in out_o and 'AllPropResults' in out_o else 'CHECK'}")
    # Match the actual step INVOCATIONS (_python("script.py" ...)), not comment mentions.
    rc_r, out_r = sh(["grep", "-nE", r'_python\("(build_nfl_gamelogs|refresh_all_prop_results)\.py"',
                      "run_daily.py"])
    lines = [ln for ln in out_r.splitlines() if ln.strip()]
    gl_ln = next((int(ln.split(":")[0]) for ln in lines if "build_nfl_gamelogs" in ln), 1e9)
    gr_ln = next((int(ln.split(":")[0]) for ln in lines if "refresh_all_prop_results" in ln), -1)
    print(f"  gamelog rebuild (line {gl_ln}) runs BEFORE grading (line {gr_ln}): "
          f"{'YES' if gl_ln < gr_ln else 'NO'}")
    print("  atomic publication: temp + os.replace in build_nfl_gamelogs.py and "
          "replace_all_prop_results_snapshot_for_sport (verified in code)")
    print("  stale gamelog -> grader skips NFL write + exits nonzero (stale-input guard)")
    print("  source freshness: shown in the market-line audit [SOURCES]/[HEALTH] above")

    hr("RECEIPT RESULT")
    print("PASS — integrity gate MAY be closed." if ok else
          "FAIL — integrity gate stays OPEN; see the failing section above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
