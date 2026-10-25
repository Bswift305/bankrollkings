"""
Read-only GRAIN + COVERAGE audit of Lane 2 (NFL_PropLines_Graded.csv) before any repoint of the NFL
streak boards (incident 2026-10-24, defect #2). NO code change, NO write, NO network.

Context: build_nfl_prop_streaks (Wave) and build_nfl_prop_hot_start (Heating Up) BOTH already collapse
multiple rows per (Player, Stat, Week) to one canonical observation via line=MEDIAN(Line), res=first(actual),
then RECOMPUTE sign = actual vs median line (they never trust a source Result column). So moving them to
Lane 2 keeps that method; the open contract question is whether the canonical weekly reference should be the
MEDIAN line across the week's daily snapshots or the CLOSING line (latest snapshot). This audit quantifies:

  * grain: rows, unique (Player,Stat,Week) groups, snapshots per group, distinct lines per group, line
    movement, whether Actual is constant within a group (it must be -- one game result);
  * the decision that actually matters: in how many groups does MEDIAN-line sign differ from CLOSING-line
    sign (i.e. the canonical rule would change OVER/UNDER) -- with examples;
  * source-Result conflicts across snapshots (informational only -- the board recomputes, so these do not
    affect the streak, but they are reported as the user requested);
  * integrity: exact duplicates, conflicting duplicates, missing Player/Week/Game, groups spanning >1 Game;
  * coverage conservation: distinct games represented per week vs the gamelog's completed games per week,
    missing completed events, coverage start + data-through.

Identity note: Lane 2 has NO EventId / PlayerId columns -- identity is (Player name, Game string, Week).
This is reported, not worked around.

LITERAL read-only: fingerprints Lane 2 + the gamelog before/after (exit 4 on change); current season via
_nfl_expected_completed_week (never global max).

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_lane2_grain.py
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
LANE2 = app.DATA_DIR / "tracking" / "NFL_PropLines_Graded.csv"
GAMELOG = app.DATA_DIR / "gamelogs" / "NFL_GameLogs.csv"


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


def _sign(actual, line):
    if pd.isna(actual) or pd.isna(line):
        return np.nan
    return 1 if actual > line else (-1 if actual < line else 0)


def main() -> int:
    print("=" * 92)
    print("NFL Lane-2 (NFL_PropLines_Graded.csv) GRAIN + COVERAGE AUDIT (read-only)")
    print("=" * 92)
    paths = [str(LANE2), str(GAMELOG)]
    fp0 = _fp(paths)

    try:
        exp_week, exp_season = app._nfl_expected_completed_week()
    except Exception:
        exp_week, exp_season = None, None
    cur = int(exp_season) if exp_season else None
    print(f"resolver_current_season={exp_season}  resolver_completed_week={exp_week}")
    if not LANE2.exists():
        print("Lane 2 ABSENT -> cannot audit."); return 2
    d = pd.read_csv(LANE2, low_memory=False)
    print(f"columns: {', '.join(map(str, d.columns))}")
    print(f"has EventId={'EventId' in d.columns}  has PlayerId={'PlayerId' in d.columns}  "
          f"(identity = Player name + Game + Week)")
    for c in ("Season", "Week", "Line", "Actual"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["__snap"] = pd.to_datetime(d.get("SnapshotDate"), errors="coerce")
    d["__gday"] = pd.to_datetime(d.get("GameDate"), errors="coerce")
    if cur is not None and "Season" in d.columns:
        d = d[d["Season"] == cur]
    print(f"current-season({cur}) rows: {len(d)}")
    if d.empty:
        print("no current-season rows -> nothing to audit."); return 0

    # ---- integrity -------------------------------------------------------------------------------
    print("-" * 92)
    miss_player = int(d["Player"].astype(str).str.strip().eq("").sum()) if "Player" in d.columns else len(d)
    miss_week = int(d["Week"].isna().sum()) if "Week" in d.columns else len(d)
    miss_game = int(d["Game"].astype(str).str.strip().eq("").sum()) if "Game" in d.columns else len(d)
    print(f"missing Player={miss_player}  missing/invalid Week={miss_week}  missing Game={miss_game}")
    exact_key = [c for c in ("Player", "Stat", "Week", "SnapshotDate", "Line") if c in d.columns]
    exact_dups = int(d.duplicated(subset=exact_key, keep=False).sum()) if exact_key else 0
    # conflicting duplicate = same (Player,Stat,Week,SnapshotDate,Line) but differing Actual/Result
    conflicting = 0
    if exact_key:
        for _, grp in d[d.duplicated(subset=exact_key, keep=False)].groupby(exact_key, dropna=False):
            av = pd.to_numeric(grp.get("Actual"), errors="coerce").dropna().nunique()
            rv = grp.get("Result", pd.Series(dtype=str)).astype(str).nunique()
            if av > 1 or rv > 1:
                conflicting += 1
    print(f"exact duplicate rows (key {exact_key}): {exact_dups}   conflicting duplicates: {conflicting}")

    # ---- grain per (Player, Stat, Week) ----------------------------------------------------------
    print("-" * 92)
    gkey = ["Player", "Stat", "Week"]
    groups = d.groupby(gkey, dropna=False)
    n_groups = groups.ngroups
    multi_snap = 0
    multi_line = 0
    multi_game = 0
    actual_varies = 0
    choice_matters = 0  # median-line sign != closing-line sign
    result_conflict = 0  # source Result disagrees across snapshots (informational)
    line_moves = []
    examples = []
    for keyvals, grp in groups:
        snaps = grp["__snap"].nunique()
        lines = grp["Line"].dropna()
        nlines = lines.nunique()
        if len(grp) > 1:
            multi_snap += 1
        if nlines > 1:
            multi_line += 1
            line_moves.append(float(lines.max() - lines.min()))
        if "Game" in grp.columns and grp["Game"].astype(str).nunique() > 1:
            multi_game += 1
        actual_vals = pd.to_numeric(grp["Actual"], errors="coerce").dropna()
        if actual_vals.nunique() > 1:
            actual_varies += 1
        actual = actual_vals.iloc[0] if not actual_vals.empty else np.nan
        median_line = lines.median() if not lines.empty else np.nan
        # closing = line at the latest snapshot
        closing_line = np.nan
        if not grp["__snap"].isna().all():
            closing_line = grp.sort_values("__snap")["Line"].dropna().iloc[-1] if grp["Line"].notna().any() else np.nan
        sm, sc = _sign(actual, median_line), _sign(actual, closing_line)
        if not pd.isna(sm) and not pd.isna(sc) and sm != sc:
            choice_matters += 1
            if len(examples) < 10:
                examples.append((keyvals, float(actual), float(median_line), int(sm),
                                 float(closing_line), int(sc), sorted({round(float(x),1) for x in lines})))
        res = grp.get("Result", pd.Series(dtype=str)).astype(str).str.upper()
        res = res[res.isin(["OVER", "UNDER", "PUSH"])]
        if res.nunique() > 1:
            result_conflict += 1

    print(f"(Player,Stat,Week) groups: {n_groups}")
    print(f"  groups with >1 snapshot row : {multi_snap}  ({100*multi_snap/max(n_groups,1):.1f}%)")
    print(f"  groups with >1 distinct line: {multi_line}  ({100*multi_line/max(n_groups,1):.1f}%)")
    if line_moves:
        lm = pd.Series(line_moves)
        print(f"    line movement within week (max-min): median={lm.median():.1f} p90={lm.quantile(.9):.1f} max={lm.max():.1f}")
    print(f"  groups spanning >1 Game (identity bug?) : {multi_game}")
    print(f"  groups where Actual varies (integrity)  : {actual_varies}")
    print(f"  >>> groups where MEDIAN-line sign != CLOSING-line sign (CANONICAL RULE MATTERS): "
          f"{choice_matters}  ({100*choice_matters/max(n_groups,1):.1f}%)")
    print(f"  groups with source-Result conflict across snapshots (informational): {result_conflict}")
    if examples:
        print("  examples where the canonical rule flips OVER/UNDER:")
        for kv, a, ml, sm, cl, sc, ls in examples:
            print(f"    {kv}: actual={a}  median_line={ml}->{'OVER' if sm>0 else 'UNDER' if sm<0 else 'PUSH'}  "
                  f"closing_line={cl}->{'OVER' if sc>0 else 'UNDER' if sc<0 else 'PUSH'}  lines={ls}")

    # ---- coverage conservation vs gamelog --------------------------------------------------------
    print("-" * 92)
    print("COVERAGE vs gamelog (completed games per week):")
    try:
        gl = app.load_nfl_gamelogs()
        gl = gl[pd.to_numeric(gl.get("Season"), errors="coerce") == cur] if "Season" in gl.columns else gl
        gl_games = gl.groupby(pd.to_numeric(gl["Week"], errors="coerce").astype("Int64"))["Team"].nunique() if {"Week","Team"}.issubset(gl.columns) else None
    except Exception as exc:
        gl_games = None
        print(f"  gamelog unavailable: {exc}")
    lane_games = d.groupby(d["Week"].astype("Int64"))["Game"].nunique() if "Game" in d.columns else None
    weeks = sorted(set(d["Week"].dropna().astype(int)))
    print(f"  Lane-2 weeks present: {weeks}  (coverage_start=Wk{min(weeks) if weeks else 'n/a'}, data_through=Wk{max(weeks) if weeks else 'n/a'})")
    if lane_games is not None:
        print("  per week -> Lane2 distinct Games | gamelog teams/2 (approx games):")
        for w in weeks:
            lg = int(lane_games.get(w, 0))
            gg = (int(gl_games.get(w, 0)) // 2) if gl_games is not None and w in gl_games.index else "?"
            print(f"      Wk{w}: lane2_games={lg}  gamelog_games~={gg}")
    print("  NOTE: Weeks below the coverage start are genuinely absent (capture began mid-season); the board "
          "must disclose 'graded from Wk<start>' and NOT imply a complete season.")

    fp1 = _fp(paths)
    changed = sorted(p for p in paths if fp0.get(p) != fp1.get(p))
    print("=" * 92)
    print(f"READ-ONLY PROOF: {len(paths)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    return 4 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
