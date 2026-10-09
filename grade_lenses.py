"""
grade_lenses.py  -- Lens Attribution harness (grade half), governance-grade

Grades captured Green Light recommendations and attributes each result to the LENSES that
fired on it. We're not grading bets -- we're grading EVIDENCE. The output answers the
question invention can't: when a lens appears on a real play, does the play actually hit,
and at what ROI? And does Opportunity + Role Stability beat Opportunity alone? That's the
next layer of the moat -- measuring which of lenses #1-#6 contribute value, forward and
out-of-sample.

Governance rules (per the governance brief):

- EXPLICIT RESOLUTION STATES. Every recommendation resolves to exactly one of:
  Pending, Win, Loss, Push, Void(DNP), PlayerUnmatched, SourceMissing, ManualReview.
  NOTHING is a silent failure -- an unresolved play says WHY it's unresolved and shows up
  in the audit, instead of sitting forever as a mute "pending".
- PUSH HANDLING. actual == line is a PUSH (stake returned), never counted as a win or a
  loss. Half-point lines can't push; whole-number lines can.
- INTENDED-GAME DISCIPLINE. A recommendation is graded against its INTENDED event (the
  slate right after the last completed week). If the player didn't play that week but
  played later, that's Void(DNP) -- we do NOT silently grade it against the wrong game.
- RECOMMENDATION vs SNAPSHOT. The archive holds daily snapshots; we collapse them to one
  recommendation (latest snapshot) by RecommendationID before resolving, so a play isn't
  counted N times.
- PRICE-AWARE. ROI uses the captured American odds; hit rate is over settled W/L only
  (pushes and voids return stake, excluded from both numerator and denominator).

Outputs data/tracking/Lens_Grades_Summary.json, including a PILOT-COHORT AUDIT of the
archive's reconstructability. Honest: a lens reads "too few to trust" until it clears the
sample floor; nothing is an edge claim until the sample is real. Idempotent full re-grade
each run so plays resolve as weeks fill in. See BANKROLL_KINGS_DOCTRINE.md S10.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
ARCHIVE = BASE / "data" / "tracking" / "GreenLight_Archive.csv"
STATS = BASE / "data" / "tracking" / "_nflverse_stats_2026.parquet"
OUT = BASE / "data" / "tracking" / "Lens_Grades_Summary.json"
MIN_SAMPLE = 25          # below this a lens reads "too few to trust"
LENSES = ["L_Opportunity", "L_Matchup", "L_GameIdentity", "L_Coaching", "L_Concentration"]
LENS_NAME = {"L_Opportunity": "Opportunity", "L_Matchup": "Matchup",
             "L_GameIdentity": "Game Identity", "L_Coaching": "Coaching",
             "L_Concentration": "Concentration (TD)"}
WL = ("Win", "Loss")          # the only states that count toward hit rate / ROI
RETURNED = ("Push", "Void(DNP)")  # stake returned -- settled but neutral


def _settle_over(actual: float, line: float, is_td: bool) -> str:
    """OVER settlement. Win if over the line, Push if exactly on it, Loss if under."""
    thresh = 0.5 if is_td else float(line)
    if is_td:
        return "Win" if actual >= 1 else "Loss"          # anytime-TD: no push
    if actual == thresh:
        return "Push"                                     # only whole-number lines reach this
    return "Win" if actual > thresh else "Loss"


def _resolve(df: pd.DataFrame) -> pd.DataFrame:
    try:
        s = pd.read_parquet(STATS)
    except Exception:
        df["State"] = "SourceMissing"
        df["Hit"] = np.nan
        return df
    for c in ("rushing_yards", "receiving_yards", "receptions", "passing_yards",
              "rushing_tds", "receiving_tds"):
        if c in s.columns:
            s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0)
    s["anytime_td"] = s.get("rushing_tds", 0) + s.get("receiving_tds", 0)
    s["week"] = pd.to_numeric(s["week"], errors="coerce")
    max_week = int(s["week"].max()) if s["week"].notna().any() else 0
    states, hits = [], []
    for _, r in df.iterrows():
        key = str(r.get("StatKey") or "")
        line = r.get("Line")
        aow = pd.to_numeric(r.get("AsOfWeek"), errors="coerce")
        target = (int(aow) + 1) if pd.notna(aow) else None
        is_td = (key == "anytime_td")
        if not key or key not in s.columns:
            states.append("SourceMissing"); hits.append(np.nan); continue
        if pd.isna(line):
            states.append("ManualReview"); hits.append(np.nan); continue
        # Resolve by the STABLE player_id we captured, not the display name -- two real
        # players can share a name, and a name-join would grade whichever row sorts first
        # (non-deterministic, silently wrong). Fall back to name only when no id was matched.
        pid = str(r.get("PlayerId") or "").strip()
        if pid and "player_id" in s.columns and (s["player_id"].astype(str) == pid).any():
            pg = s[s["player_id"].astype(str) == pid]
        else:
            pg = s[s["player_display_name"] == r.get("Player")]
        if pg.empty:
            states.append("PlayerUnmatched"); hits.append(np.nan); continue
        if target is None:
            states.append("ManualReview"); hits.append(np.nan); continue
        fut = pg[pg["week"] >= target].sort_values("week")
        if fut.empty:
            # no game at/after the intended week
            states.append("Pending" if target > max_week else "Void(DNP)")
            hits.append(np.nan); continue
        gw = int(fut.iloc[0]["week"])
        if gw != target:
            # player was inactive the intended week but played later -> don't grade the wrong game
            states.append("Void(DNP)"); hits.append(np.nan); continue
        actual = float(fut.iloc[0][key])
        st = _settle_over(actual, line, is_td)
        states.append(st)
        hits.append(1 if st == "Win" else (0 if st == "Loss" else np.nan))
    df["State"], df["Hit"] = states, hits
    return df


def _roi(sub: pd.DataFrame):
    """ROI% over settled W/L rows with a usable price. Win -> +payout, Loss -> -1u."""
    d = sub[sub["State"].isin(WL)].copy()
    price = pd.to_numeric(d.get("Odds"), errors="coerce")
    m = price.notna() & (price.abs() >= 100) & (price.abs() < 100000)
    if not bool(m.any()):
        return None, 0
    p = price[m].to_numpy(dtype=float)
    win = np.where(p < 0, 100.0 / np.abs(p), p / 100.0)
    hit = d.loc[m, "Hit"].to_numpy()
    return round(float(np.where(hit == 1, win, -1.0).mean()) * 100, 1), int(m.sum())


def _cell(sub: pd.DataFrame) -> dict:
    st = sub["State"]
    settled = sub[st.isin(WL)]
    n = int(len(settled)); hits = int((settled["State"] == "Win").sum()) if n else 0
    roi, priced = _roi(sub)
    return {"appearances": int(len(sub)),
            "settled": n, "wins": hits,
            "hit_rate": (round(hits / n * 100, 1) if n else None),
            "roi": roi, "priced": priced,
            "pending": int((st == "Pending").sum()),
            "void": int(st.isin(RETURNED).sum()),
            "unresolved": int(st.isin(["PlayerUnmatched", "SourceMissing", "ManualReview"]).sum()),
            "read": ("too few to trust" if n < MIN_SAMPLE else "out-of-sample")}


def _pilot_audit(df: pd.DataFrame) -> dict:
    """Can this cohort become governance data? Reconstructability, not edge."""
    n = len(df)
    st = df["State"] if "State" in df.columns else pd.Series([], dtype=object)
    has = lambda c: c in df.columns
    event_ok = int(df["EventID"].astype(str).str.len().gt(0).sum()) if has("EventID") else 0
    player_ok = int((st != "PlayerUnmatched").sum())
    intended_ok = int(pd.to_numeric(df["AsOfWeek"], errors="coerce").notna().sum()) if has("AsOfWeek") else 0
    quarantine = int(st.isin(["PlayerUnmatched", "SourceMissing", "ManualReview"]).sum())
    ok = (event_ok == n and player_ok == n and intended_ok == n and quarantine == 0)
    return {
        "cohort_size": int(n),
        "event_reconstructable": f"{event_ok}/{n}",
        "player_matched": f"{player_ok}/{n}",
        "intended_game_reconstructable": f"{intended_ok}/{n}",
        "pushes_gradeable": True,  # settlement logic handles push/void explicitly
        "quarantined": quarantine,
        "verdict": ("promote to governance data" if ok
                    else "pipeline testing only -- quarantined rows must be resolved first"),
    }


def main() -> int:
    if not ARCHIVE.exists():
        print("[grade_lenses] no GreenLight_Archive.csv yet -- run capture_green_light first")
        return 0
    df = pd.read_csv(ARCHIVE)
    if df.empty:
        print("[grade_lenses] archive empty"); return 0
    # RECOMMENDATION vs SNAPSHOT: collapse daily snapshots to one recommendation
    # (latest snapshot = closest to the game) so a play isn't counted N times.
    before = len(df)
    if "RecommendationID" in df.columns:
        subset = ["RecommendationID"]
    else:  # backward-compat with pre-governance archives
        subset = [c for c in ["Player", "Stat", "Season", "AsOfWeek"] if c in df.columns]
    sort_col = "Timestamp" if "Timestamp" in df.columns else "SnapshotDate"
    df = df.sort_values(sort_col).drop_duplicates(subset=subset, keep="last").reset_index(drop=True)
    if before != len(df):
        print(f"[grade_lenses] collapsed {before} snapshots -> {len(df)} recommendations")
    df = _resolve(df)

    def col(name, default=np.nan):
        return df[name] if name in df.columns else pd.Series([default] * len(df), index=df.index)

    lenses = {LENS_NAME[c]: _cell(df[df[c] == 1]) for c in LENSES if c in df.columns}
    # THE KILLER TABLE -- lens INTERACTION, not just each lens alone. Does Opportunity +
    # Stability beat Opportunity alone? Does the Fragile warning actually predict misses?
    opp = df["L_Opportunity"] == 1
    others = df[[c for c in LENSES if c != "L_Opportunity"]].sum(axis=1)
    combos = {
        "Opportunity ALONE": _cell(df[opp & (others == 0)]),
        "Opportunity + Stability(Locked)": _cell(df[opp & (col("RoleStability") == "Locked")]),
        "Opportunity + Stability + Matchup": _cell(df[opp & (col("RoleStability") == "Locked") & (df["L_Matchup"] == 1)]),
        "Dual-threat (multi-channel)": _cell(df[col("SingleChannel") == 0]),
        "Single-channel": _cell(df[col("SingleChannel") == 1]),
        "Fragile (single-ch x shaky script)": _cell(df[col("Fragile") == 1]),
    }
    confidence = {f"Script confidence = {c}": _cell(df[col("ScriptConfidence") == c])
                  for c in ["high", "medium"]}
    tiers = {t: _cell(df[df["Tier"] == t]) for t in df["Tier"].dropna().unique()}
    states = {s: int((df["State"] == s).sum()) for s in sorted(df["State"].dropna().unique())}

    summary = {
        "by_lens": lenses, "by_combo": combos, "by_confidence": confidence, "by_tier": tiers,
        "resolution_states": states,
        "pilot_audit": _pilot_audit(df),
        "totals": {"recommendations": int(len(df)),
                   "settled": int(df["State"].isin(WL).sum()),
                   "pending": int((df["State"] == "Pending").sum())},
        "versions": {k: sorted(map(str, df[k].dropna().unique()))
                     for k in ("LensDefinitionVersion", "CaptureSchemaVersion", "BoardVersion")
                     if k in df.columns},
        "min_sample": MIN_SAMPLE,
        "note": ("Grading evidence, not bets. Each lens's hit rate + ROI is over the plays it "
                 "appeared on; a lens reads 'too few' below the sample floor. Resolution states "
                 "are explicit -- no silent failures. Out-of-sample or it does not count."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    t = summary["totals"]
    print(f"[grade_lenses] {t['recommendations']} recommendations | "
          f"{t['settled']} settled, {t['pending']} pending")
    print(f"  states: {states}")
    pa = summary["pilot_audit"]
    print(f"  pilot audit: event {pa['event_reconstructable']}, player {pa['player_matched']}, "
          f"quarantined {pa['quarantined']} -> {pa['verdict']}\n")
    print(f"  {'LENS / COMBINATION':<36}{'appear':>7}{'settl':>6}{'hit%':>7}{'ROI%':>8}  read")
    for name, c in {**lenses, **combos, **confidence}.items():
        hr = f"{c['hit_rate']}" if c["hit_rate"] is not None else "--"
        roi = f"{c['roi']:+}" if c["roi"] is not None else "--"
        print(f"  {name:<34}{c['appearances']:>7}{c['settled']:>6}{hr:>7}{roi:>8}  [{c['read']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
