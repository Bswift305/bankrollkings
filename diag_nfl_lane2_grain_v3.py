"""
Read-only v3 receipt for Lane 2 (NFL_PropLines_Graded.csv) under the FROZEN pregame-only contract
(incident 2026-10-24, defect #2). NO code change, NO write, NO network.

The all-snapshot median is REJECTED: it used 876 observations captured at/after kickoff, which cannot
describe a PREGAME market. Lane-2 SnapshotDate is DATE-ONLY (no clock, no tz), so a same-day capture
CANNOT be proven to precede kickoff -> it is TEMPORALLY_INDETERMINATE, not pregame.

Frozen reference rule: weekly PREGAME consensus median = median of consensus snapshots with
SnapshotDate.date() STRICTLY BEFORE GameDate.date(); labeled as a derived value, not an exact quote.

Frozen streak definition (the Wave): consecutive COMPLETED player appearances with a valid pregame
consensus-market observation.
  * completed appearance + valid pregame quote -> OVER/UNDER/PUSH (PUSH breaks the run);
  * documented missed game (no gamelog appearance) -> PAUSES continuity (no market result), does not break;
  * completed appearance with NO valid pregame observation -> INDETERMINATE_MISSING_MARKET_OBSERVATION
    (the run may not silently bridge it);
  * a missing prop row is NOT evidence the player missed the game -> appearance comes from the GAMELOG;
  * future/unresolved weeks do not contribute.

Reports (required v3 return): timestamp classification + the date-only precision caveat; pregame-only
observation counts + exclusions by terminal reason; pregame-only synthetic-median rate; UNAVAILABLE_NO_
PREGAME_QUOTE groups; membership/render impact vs the (now-void) all-snapshot baseline; continuity-gap
analysis; ATL-GB Week-3 classification; corrected coverage statement; identity_quality; proposed UI wording.

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_lane2_grain_v3.py
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


def _nk(n):
    t = str(n or "").replace(".", " ").split()
    return (t[0][:1] + "." + t[-1]).lower() if len(t) >= 2 else str(n or "").lower()


def _sign(a, l):
    if pd.isna(a) or pd.isna(l):
        return np.nan
    return 1 if a > l else (-1 if a < l else 0)


def main() -> int:
    print("=" * 94)
    print("NFL Lane-2 v3 RECEIPT -- PREGAME-ONLY median + continuity contract (read-only)")
    print("=" * 94)
    paths = [str(LANE2), str(GAMELOG)]
    fp0 = _fp(paths)
    try:
        _, exp_season = app._nfl_expected_completed_week()
        exp_week, _ = app._nfl_expected_completed_week()
    except Exception:
        exp_week = exp_season = None
    cur = int(exp_season) if exp_season else None
    comp = int(exp_week) if exp_week else None
    print(f"resolver_current_season={cur}  resolver_completed_week={comp}")
    print("identity_quality: COMPOSITE_NAME_EVENT (name-based; Lane 2 has NO PlayerId/EventId)")
    if not LANE2.exists():
        print("Lane 2 ABSENT."); return 2
    d = pd.read_csv(LANE2, low_memory=False)
    for c in ("Season", "Week", "Line", "Actual"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d["__snap"] = pd.to_datetime(d.get("SnapshotDate"), errors="coerce")
    d["__gday"] = pd.to_datetime(d.get("GameDate"), errors="coerce")
    d["__nk"] = d["Player"].map(_nk)
    d["__snorm"] = d["Stat"].astype(str).str.strip().str.upper()
    if cur is not None:
        d = d[d["Season"] == cur]

    # ---- timestamp classification (date-only precision caveat) -------------------------------------
    print("-" * 94); print("[A] TIMESTAMP CLASSIFICATION (SnapshotDate is DATE-ONLY -> same-day = indeterminate)")
    unknown = d["__snap"].isna() | d["__gday"].isna()
    sd = d["__snap"].dt.normalize()
    gd = d["__gday"].dt.normalize()
    provably_pre = (~unknown) & (sd < gd)
    indeterminate = (~unknown) & (sd == gd)
    post_start = (~unknown) & (sd > gd)
    print(f"  total rows={len(d)}")
    print(f"  TIMESTAMP_UNKNOWN (no SnapshotDate/GameDate): {int(unknown.sum())}")
    print(f"  PROVABLY_PREGAME (snap day < game day)      : {int(provably_pre.sum())}")
    print(f"  TEMPORALLY_INDETERMINATE (same day)         : {int(indeterminate.sum())}")
    print(f"  POST_START (snap day > game day)            : {int(post_start.sum())}")
    print("  NOTE: only PROVABLY_PREGAME rows may set the reference line; the rest are excluded with the "
          "reason shown. (No intraday clock in the source -> same-day cannot be proven pre-kickoff.)")

    pre = d[provably_pre].copy()

    # ---- gamelog appearances (authoritative continuity) --------------------------------------------
    gl = app.load_nfl_gamelogs()
    gl = gl.copy()
    if "Season" in gl.columns:
        gl = gl[pd.to_numeric(gl["Season"], errors="coerce") == cur]
    gl["__nk"] = gl.get("Player", pd.Series(dtype=str)).map(_nk)
    gl["__wk"] = pd.to_numeric(gl.get("Week"), errors="coerce")
    appearances = set(zip(gl["__nk"], gl["__wk"].astype("Int64")))

    # ---- per (nk, stat, week) pregame reference ----------------------------------------------------
    recs = {}
    synth = 0
    groups_total = 0
    for (nk, sn, wk), g in pre.groupby(["__nk", "__snorm", "Week"], dropna=True):
        groups_total += 1
        lines = g["Line"].dropna()
        actual = g["Actual"].dropna()
        if lines.empty or actual.empty:
            continue
        med = lines.median()
        is_syn = med not in set(lines.values)
        synth += int(is_syn)
        recs[(nk, sn, int(wk))] = {"line": med, "actual": actual.iloc[0], "sign": _sign(actual.iloc[0], med),
                                   "synthetic": is_syn, "n": len(g),
                                   "earliest": g["__snap"].min(), "latest": g["__snap"].max(),
                                   "lmin": float(lines.min()), "lmax": float(lines.max())}
    print("-" * 94); print("[B] PREGAME-ONLY REFERENCE")
    print(f"  (nk,stat,week) groups with a valid pregame reference: {len(recs)}")
    print(f"  synthetic-median groups (median never actually quoted): {synth} "
          f"({100*synth/max(len(recs),1):.1f}%)")

    # groups that EXIST in the data for a completed week but have NO pregame reference
    allcw = d[(d["Week"].notna()) & (d["Week"] <= comp)] if comp else d[d["Week"].notna()]
    no_pre = 0
    for (nk, sn, wk), g in allcw.groupby(["__nk", "__snorm", "Week"], dropna=True):
        if (nk, sn, int(wk)) not in recs:
            no_pre += 1
    print(f"  completed-week (<=Wk{comp}) player-stat-weeks with observations but NO pregame reference "
          f"-> UNAVAILABLE_NO_PREGAME_QUOTE: {no_pre}")

    # ---- membership: strict pregame+continuity vs void all-snapshot baseline -----------------------
    print("-" * 94); print("[C] MEMBERSHIP IMPACT (strict pregame+continuity vs void all-snapshot baseline)")

    # void baseline: all-snapshot median, trailing run, no continuity (reproduces v2's method)
    def _baseline():
        out = {}
        base = d[(d["Week"].notna()) & (d["Week"] <= comp)] if comp else d[d["Week"].notna()]
        g = (base.groupby(["__nk", "__snorm", "Week"])
             .agg(line=("Line", "median"), res=("Actual", "first")).reset_index())
        g["sign"] = g.apply(lambda r: _sign(r["res"], r["line"]), axis=1)
        for (nk, sn), grp in g.groupby(["__nk", "__snorm"]):
            signs = [s for s in grp.sort_values("Week")["sign"].tolist() if not pd.isna(s)]
            if not signs or signs[-1] == 0:
                continue
            run = 0
            for s in reversed(signs):
                if s == signs[-1]:
                    run += 1
                else:
                    break
            if run >= _WAVE_MIN:
                out[(nk, sn)] = (run, "Over" if signs[-1] > 0 else "Under")
        return out

    # strict: pregame-only sign per week; continuity over completed weeks using GAMELOG appearances
    def _strict():
        out = {}
        indeterminate_runs = 0
        keys = {(nk, sn) for (nk, sn, wk) in recs}
        weeks_order = sorted({w for (_, _, w) in recs})
        for (nk, sn) in keys:
            # walk completed weeks descending from comp; build the trailing run per the contract
            run = 0
            direction = None
            broke = indet = False
            for wk in range(comp, 2, -1):  # Wk comp .. Wk3
                appeared = (nk, wk) in appearances
                rec = recs.get((nk, sn, wk))
                if not appeared and rec is None:
                    continue  # player not in this week at all (bye/not on slate) -> pause, skip
                if appeared and rec is None:
                    # completed appearance, no pregame quote -> indeterminate gap, cannot bridge
                    indet = True
                    break
                if rec is None:
                    continue
                s = rec["sign"]
                if pd.isna(s):
                    continue
                if s == 0:  # push breaks
                    break
                if direction is None:
                    direction = s
                    run = 1
                elif s == direction:
                    run += 1
                else:
                    break
            if indet and run < _WAVE_MIN:
                indeterminate_runs += 1
            if (not indet) and run >= _WAVE_MIN and direction is not None:
                out[(nk, sn)] = (run, "Over" if direction > 0 else "Under")
        return out, indeterminate_runs

    base = _baseline()
    strict, indet_runs = _strict()
    removed = sorted(set(base) - set(strict))
    added = sorted(set(strict) - set(base))
    shared = set(base) & set(strict)
    len_chg = [(k, base[k], strict[k]) for k in shared if base[k][0] != strict[k][0]]
    side_chg = [(k, base[k], strict[k]) for k in shared if base[k][1] != strict[k][1]]
    print(f"  void all-snapshot baseline qualifying streaks : {len(base)}")
    print(f"  strict pregame+continuity qualifying streaks  : {len(strict)}")
    print(f"  runs blocked as INDETERMINATE_MISSING_MARKET_OBSERVATION: {indet_runs}")
    print(f"  REMOVED by strict contract: {len(removed)}   ADDED: {len(added)}")
    print(f"  among shared: run-length changed={len(len_chg)}  side flipped={len(side_chg)}")
    for k in removed[:8]:
        print(f"    REMOVED: {k[0]}/{k[1]}  (baseline {base[k]})")
    for k, b, s in len_chg[:6]:
        print(f"    RUN-LENGTH: {k[0]}/{k[1]}  baseline={b} strict={s}")

    # ---- ATL-GB Week-3 classification --------------------------------------------------------------
    print("-" * 94); print("[D] WEEK-3 ATL-GB CLASSIFICATION")
    atlgb_lane = d[(d["Week"] == 3) & d["Team"].astype(str).str.upper().str.contains("ATL|GREEN BAY|GB|ATLANTA", na=False)]
    atlgb_gl = gl[(gl["__wk"] == 3) & gl.get("Team", pd.Series(dtype=str)).astype(str).str.upper().str.contains("ATL|GB|GREEN|ATLANTA", na=False)]
    print(f"  Lane-2 Wk3 ATL/GB prop rows: {len(atlgb_lane)}   gamelog Wk3 ATL/GB appearances: {len(atlgb_gl)}")
    if len(atlgb_gl) and not len(atlgb_lane):
        print("  => game COMPLETED (players appear in gamelog) but NO Lane-2 prop observations. From persistent "
              "stores alone, 'no markets posted' vs 'capture failure' are INDISTINGUISHABLE -> classify "
              "UNCLASSIFIED_EVIDENCE_UNAVAILABLE. Disclose: 'Week 3 coverage partial: one completed game "
              "(ATL-GB) unclassified.' Do NOT call Weeks 3-6 complete.")
    else:
        print("  => inspect manually; gamelog team tokens may differ.")

    # ---- corrected coverage + UI wording -----------------------------------------------------------
    print("-" * 94); print("[E] CORRECTED COVERAGE + PROPOSED UI WORDING")
    print(f"  coverage_begins = Week 3 (PARTIAL: ATL-GB unclassified)")
    print(f"  graded_through  = Week {comp}  (capped at completed week; Week 7 = current/pending)")
    print("  proposed UI: \"Graded from Week 3 (partial) through Week {c} · Week {n} in progress. "
          "Reference: weekly PREGAME consensus median across N books (a derived value, not one quote); "
          "weeks without a pre-kickoff quote are shown as indeterminate, not counted.\"".format(c=comp, n=(comp or 0)+1))

    fp1 = _fp(paths)
    changed = sorted(p for p in paths if fp0.get(p) != fp1.get(p))
    print("=" * 94)
    print(f"READ-ONLY PROOF: {len(paths)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    return 4 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
