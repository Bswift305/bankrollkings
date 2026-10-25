"""
Read-only DEEP grain/identity/temporal/coverage audit of Lane 2 (NFL_PropLines_Graded.csv), v2
(incident 2026-10-24, defect #2). NO code change, NO write, NO network. Answers the 9 required-return
items before any streak-board repoint is frozen:

  1. collision-free COMPOSITE identity (Season + normalized Game + GameDate + normalized Player + Stat;
     Week as attribute) -- prove the board key (Season,Player,Stat,Week) never merges two games; report
     ambiguous player identities.
  2. disposition of EVERY invalid-week row (why, GameDate-recoverable?, completed?, terminal reason code).
  3. the Week-3 missing game -- name it; classify what can be classified read-only.
  4. corrected data-through semantics: coverage_begins / graded_through (capped at resolver completed
     week) / current-pending weeks -- Wk7 rows must NOT read as graded-through.
  5. temporal validity: pregame vs at/after-start snapshots, groups with NO valid pregame observation,
     synthetic-median rate (median never actually quoted), earliest/latest capture per group.
  6. classify source-Result conflicts: different-line (expected) vs SAME-line (DEFECT, must fail) vs
     actual-inconsistent vs pending-involved.
  7. membership impact of the MEDIAN-vs-CLOSING choice: how many streaks change length / inclusion /
     ordering through the graded week, with affected players (pre-injury-gate approximation).

LITERAL read-only: fingerprints Lane 2 + gamelog before/after (exit 4 on change); current season via
_nfl_expected_completed_week (never global max). Same-line Result conflicts -> exit 3.

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_lane2_grain_v2.py
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
LANE2 = app.DATA_DIR / "tracking" / "NFL_PropLines_Graded.csv"
GAMELOG = app.DATA_DIR / "gamelogs" / "NFL_GameLogs.csv"
_WAVE_MIN = 3


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


def _pnorm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _sign(a, l):
    if pd.isna(a) or pd.isna(l):
        return np.nan
    return 1 if a > l else (-1 if a < l else 0)


def _trailing_run(signs):
    if not signs:
        return 0, 0
    last = signs[-1]
    if last == 0:
        return 0, 0
    run = 0
    for s in reversed(signs):
        if s == last:
            run += 1
        else:
            break
    return run, last


def main() -> int:
    print("=" * 94)
    print("NFL Lane-2 DEEP GRAIN / IDENTITY / TEMPORAL / COVERAGE AUDIT v2 (read-only)")
    print("=" * 94)
    paths = [str(LANE2), str(GAMELOG)]
    fp0 = _fp(paths)
    try:
        exp_week, exp_season = app._nfl_expected_completed_week()
    except Exception:
        exp_week, exp_season = None, None
    cur = int(exp_season) if exp_season else None
    comp_week = int(exp_week) if exp_week else None
    print(f"resolver_current_season={cur}  resolver_completed_week={comp_week}")
    if not LANE2.exists():
        print("Lane 2 ABSENT."); return 2
    d = pd.read_csv(LANE2, low_memory=False)
    for c in ("Season", "Week", "Line", "Actual"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["__snap"] = pd.to_datetime(d.get("SnapshotDate"), errors="coerce")
    d["__gday"] = pd.to_datetime(d.get("GameDate"), errors="coerce")
    d["__pnorm"] = d["Player"].map(_pnorm)
    d["__gnorm"] = d["Game"].astype(str).str.strip().str.upper()
    d["__snorm"] = d["Stat"].astype(str).str.strip().str.upper()
    if cur is not None:
        d = d[d["Season"] == cur]
    print(f"current-season rows: {len(d)}")

    # gamelog date->week + games/week
    gl = app.load_nfl_gamelogs()
    gl = gl.copy()
    gl["Date"] = pd.to_datetime(gl.get("Date"), errors="coerce")
    if "Season" in gl.columns:
        gl = gl[pd.to_numeric(gl["Season"], errors="coerce") == cur]
    date_week = {}
    if {"Date", "Week"}.issubset(gl.columns):
        for dt, wk in zip(gl["Date"], pd.to_numeric(gl["Week"], errors="coerce")):
            if pd.notna(dt) and pd.notna(wk):
                date_week[pd.Timestamp(dt).normalize()] = int(wk)

    def _wk_from_date(x):
        x = pd.to_datetime(x, errors="coerce")
        if pd.isna(x):
            return None
        d0 = pd.Timestamp(x).normalize()
        for off in (0, 1, -1, 2, -2, 3, -3):
            if (d0 + pd.Timedelta(days=off)) in date_week:
                return date_week[d0 + pd.Timedelta(days=off)]
        return None

    # ---- (1) composite identity --------------------------------------------------------------------
    print("-" * 94); print("[1] COMPOSITE IDENTITY")
    valid = d[d["Week"].notna()].copy()
    bkey = ["Season", "__pnorm", "__snorm", "Week"]
    merged_games = 0
    for _, g in valid.groupby(bkey, dropna=False):
        if g[["__gnorm", "__gday"]].drop_duplicates().shape[0] > 1:
            merged_games += 1
    print(f"  board key (Season,Player,Stat,Week) groups: {valid.groupby(bkey).ngroups}")
    print(f"  groups mapping to >1 (Game,GameDate)  : {merged_games}  "
          f"{'<-- COLLISION (key would merge distinct games)' if merged_games else '(collision-free)'}")
    amb = {}
    for pn, grp in d.groupby("__pnorm"):
        raws = sorted(set(grp["Player"].astype(str)))
        if len(raws) > 1:
            amb[pn] = raws
    print(f"  ambiguous player identities (one norm -> many raw): {len(amb)}")
    for pn, raws in list(amb.items())[:6]:
        print(f"      {pn}: {raws}")

    # ---- (2) invalid-week rows ---------------------------------------------------------------------
    print("-" * 94); print("[2] INVALID-WEEK ROW DISPOSITION")
    inv = d[d["Week"].isna()]
    print(f"  rows with missing/invalid Week: {len(inv)}")
    if len(inv):
        rec = inv["__gday"].map(_wk_from_date)
        recoverable = int(rec.notna().sum())
        completed = int(rec.dropna().le(comp_week).sum()) if comp_week else 0
        has_gameday = int(inv["__gday"].notna().sum())
        print(f"    have GameDate: {has_gameday}   GameDate->week recoverable: {recoverable}   "
              f"of those completed (<= Wk{comp_week}): {completed}")
        print(f"    reason codes: NO_GAMEDATE={len(inv)-has_gameday}  "
              f"RECOVERABLE_VIA_GAMEDATE={recoverable}  UNRECOVERABLE_WITH_GAMEDATE={has_gameday-recoverable}")
        print(f"    terminal disposition: EXCLUDED_INVALID_WEEK (reported, not silently dropped); "
              f"{recoverable} are RECOVERABLE and should be week-assigned before exclusion")
        ex = inv.head(4)[["Player", "Stat", "Game", "GameDate", "Result"]]
        print(ex.to_string(index=False))

    # ---- (3) Week-3 missing game -------------------------------------------------------------------
    print("-" * 94); print("[3] WEEK-3 MISSING GAME")
    gl_games_by_week = {}
    if {"Date", "Week", "Team", "Opponent"}.issubset(gl.columns):
        for wk, grp in gl.groupby(pd.to_numeric(gl["Week"], errors="coerce")):
            pairs = set()
            for t, o in zip(grp["Team"].astype(str), grp["Opponent"].astype(str)):
                pairs.add(tuple(sorted([t.upper(), o.upper()])))
            gl_games_by_week[int(wk)] = pairs
    lane_wk3 = set(d[d["Week"] == 3]["__gnorm"])
    print(f"  Lane-2 Wk3 games ({len(lane_wk3)}): {sorted(lane_wk3)}")
    if 3 in gl_games_by_week:
        print(f"  gamelog Wk3 matchups ({len(gl_games_by_week[3])}): {sorted(gl_games_by_week[3])}")
        print("  (match Lane-2 Game strings against gamelog matchups to name the missing game; "
              "classify via whether its players had posted prop markets)")

    # ---- (4) data-through --------------------------------------------------------------------------
    print("-" * 94); print("[4] DATA-THROUGH SEMANTICS")
    weeks = sorted(set(d["Week"].dropna().astype(int)))
    max_week = max(weeks) if weeks else None
    graded_through = min(max_week, comp_week) if (max_week and comp_week) else None
    pending_weeks = [w for w in weeks if comp_week and w > comp_week]
    print(f"  coverage_begins = Wk{min(weeks) if weeks else 'n/a'}")
    print(f"  max week with rows = Wk{max_week}")
    print(f"  resolver completed week = Wk{comp_week}")
    print(f"  => graded_through = Wk{graded_through}  (MUST cap at completed week)")
    print(f"  => current/pending (rows exist, not graded-through) = {pending_weeks or 'none'}")
    print("  The board MUST NOT present a pending week as graded-through merely because rows exist.")

    # ---- (5) temporal validity ---------------------------------------------------------------------
    print("-" * 94); print("[5] TEMPORAL VALIDITY")
    gkey = ["Season", "__gnorm", "__gday", "__pnorm", "__snorm"]
    no_pregame = synthetic_median = n_comp = 0
    for _, g in valid.groupby(gkey, dropna=False):
        n_comp += 1
        pre = g[g["__snap"].notna() & g["__gday"].notna() & (g["__snap"] <= g["__gday"])]
        if pre.empty:
            no_pregame += 1
        lines = g["Line"].dropna()
        if not lines.empty:
            med = lines.median()
            if med not in set(lines.values):
                synthetic_median += 1
    print(f"  composite observation groups: {n_comp}")
    print(f"  groups with NO valid pregame snapshot (closing invalid for them): {no_pregame} "
          f"({100*no_pregame/max(n_comp,1):.1f}%)")
    print(f"  groups whose MEDIAN line was never actually quoted (synthetic median): {synthetic_median} "
          f"({100*synthetic_median/max(n_comp,1):.1f}%)")
    pre_all = d[d["__snap"].notna() & d["__gday"].notna()]
    if len(pre_all):
        after = int((pre_all["__snap"] > pre_all["__gday"]).sum())
        print(f"  snapshot timing over all rows: pregame={len(pre_all)-after}  at/after-start={after}")

    # ---- (6) source-Result conflicts ---------------------------------------------------------------
    print("-" * 94); print("[6] SOURCE-RESULT CONFLICT CLASSIFICATION")
    same_line_conflict = diff_line = actual_inconsistent = pending_involved = 0
    examples = []
    for kv, g in valid.groupby(["Season", "__pnorm", "__snorm", "Week"], dropna=False):
        res = g["Result"].astype(str).str.upper()
        graded = res[res.isin(["OVER", "UNDER", "PUSH"])]
        if graded.nunique() <= 1:
            continue
        if pd.to_numeric(g["Actual"], errors="coerce").dropna().nunique() > 1:
            actual_inconsistent += 1
            continue
        # same-line conflict: one Line value with >1 distinct graded Result
        sl = False
        for ln, lg in g.groupby("Line"):
            r = lg["Result"].astype(str).str.upper()
            r = r[r.isin(["OVER", "UNDER", "PUSH"])]
            if r.nunique() > 1:
                sl = True
                break
        if sl:
            same_line_conflict += 1
            if len(examples) < 6:
                examples.append(kv)
        else:
            diff_line += 1
        if (res == "PENDING").any():
            pending_involved += 1
    print(f"  groups with >1 graded Result: different-line(expected)={diff_line}  "
          f"SAME-line(DEFECT)={same_line_conflict}  actual-inconsistent={actual_inconsistent}  "
          f"pending-also-present={pending_involved}")
    for kv in examples:
        print(f"    SAME-LINE CONFLICT: {kv}")

    # ---- (7) median-vs-closing membership impact (through graded week) -----------------------------
    print("-" * 94); print("[7] MEDIAN-vs-CLOSING STREAK MEMBERSHIP IMPACT (pre-injury-gate)")

    def _streaks(reference):
        d2 = valid[valid["Week"] <= comp_week] if comp_week else valid
        rows = {}
        for (pn, sn), grp in d2.groupby(["__pnorm", "__snorm"]):
            per_week = {}
            for wk, wg in grp.groupby("Week"):
                lines = wg["Line"].dropna()
                actual = pd.to_numeric(wg["Actual"], errors="coerce").dropna()
                if lines.empty or actual.empty:
                    continue
                if reference == "median":
                    ref = lines.median()
                else:
                    pre = wg[wg["__snap"].notna() & wg["__gday"].notna() & (wg["__snap"] <= wg["__gday"])]
                    src = pre if not pre.empty else wg
                    src = src.sort_values("__snap")
                    rl = src["Line"].dropna()
                    ref = rl.iloc[-1] if not rl.empty else lines.median()
                per_week[int(wk)] = _sign(actual.iloc[0], ref)
            if not per_week:
                continue
            signs = [per_week[w] for w in sorted(per_week)]
            run, direction = _trailing_run([s for s in signs if not pd.isna(s)])
            if run >= _WAVE_MIN and direction != 0:
                rows[(pn, sn)] = (run, 'Over' if direction > 0 else 'Under')
        return rows

    med = _streaks("median")
    clo = _streaks("closing")
    only_med = set(med) - set(clo)
    only_clo = set(clo) - set(med)
    both = set(med) & set(clo)
    len_changed = [(k, med[k], clo[k]) for k in both if med[k][0] != clo[k][0]]
    side_changed = [(k, med[k], clo[k]) for k in both if med[k][1] != clo[k][1]]
    print(f"  qualifying streaks (run>={_WAVE_MIN}) under MEDIAN: {len(med)}   under CLOSING: {len(clo)}")
    print(f"  inclusion changes: only-median={len(only_med)}  only-closing={len(only_clo)}")
    print(f"  among shared: run-length changed={len(len_changed)}  side flipped={len(side_changed)}")
    for k in list(only_med)[:5]:
        print(f"    MEDIAN-only streak: {k[0]}/{k[1]} = {med[k]}")
    for k in list(only_clo)[:5]:
        print(f"    CLOSING-only streak: {k[0]}/{k[1]} = {clo[k]}")
    for k, m, c in len_changed[:5]:
        print(f"    run-length: {k[0]}/{k[1]} median={m} closing={c}")

    fp1 = _fp(paths)
    changed = sorted(p for p in paths if fp0.get(p) != fp1.get(p))
    print("=" * 94)
    print(f"READ-ONLY PROOF: {len(paths)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        print(f"[FAIL] probe mutated: {changed}"); return 4
    if same_line_conflict:
        print(f"[FAIL] {same_line_conflict} SAME-line Result conflicts (one line, conflicting outcomes) -- must resolve before repoint.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
