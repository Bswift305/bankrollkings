"""
grade_lenses.py  -- Lens Attribution harness (grade half)

Grades captured Green Light plays and attributes each result to the LENSES that fired on it.
We're not grading bets -- we're grading EVIDENCE. The output answers the question invention
can't: when a lens appears on a real play, does the play actually hit, and at what ROI? And
does Opportunity + Role Stability beat Opportunity alone? That's the next layer of the moat --
measuring which of lenses #1-#6 contribute value, forward and out-of-sample.

Resolves each captured play against the player's NEXT game (nflverse weekly stats), OVER vs the
captured line. Outputs data/tracking/Lens_Grades_Summary.json. Honest: a lens reads "too few"
until it clears the sample floor; nothing is an edge claim until the sample is real. Idempotent
full re-grade each run so plays resolve as weeks fill in. See BANKROLL_KINGS_DOCTRINE.md S10.
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


def _resolve(df: pd.DataFrame) -> pd.DataFrame:
    try:
        s = pd.read_parquet(STATS)
    except Exception:
        df["Resolved"], df["Hit"] = 0, np.nan
        return df
    for c in ("rushing_yards", "receiving_yards", "receptions", "passing_yards",
              "rushing_tds", "receiving_tds"):
        if c in s.columns:
            s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0)
    s["anytime_td"] = s.get("rushing_tds", 0) + s.get("receiving_tds", 0)
    s["week"] = pd.to_numeric(s["week"], errors="coerce")
    res_hit, res_flag = [], []
    for _, r in df.iterrows():
        key, line, aow = str(r.get("StatKey")), r.get("Line"), r.get("AsOfWeek")
        g = s[(s["player_display_name"] == r.get("Player")) & (s["week"] > pd.to_numeric(aow, errors="coerce"))]
        if g.empty or key not in s.columns or pd.isna(line):
            res_hit.append(np.nan); res_flag.append(0); continue
        g = g.sort_values("week")
        actual = float(g.iloc[0][key])
        thresh = 0.5 if key == "anytime_td" else float(line)
        res_hit.append(1 if actual >= thresh else 0); res_flag.append(1)
    df["Hit"], df["Resolved"] = res_hit, res_flag
    return df


def _roi(sub: pd.DataFrame):
    """ROI% over resolved rows with a usable price. Hit -> +payout, Miss -> -1u."""
    d = sub[sub["Resolved"] == 1].copy()
    price = pd.to_numeric(d.get("Odds"), errors="coerce")
    m = price.notna() & (price.abs() >= 100) & (price.abs() < 100000) & d["Hit"].notna()
    if not bool(m.any()):
        return None, 0
    p = price[m].to_numpy(dtype=float)
    win = np.where(p < 0, 100.0 / np.abs(p), p / 100.0)
    hit = d.loc[m, "Hit"].to_numpy()
    return round(float(np.where(hit == 1, win, -1.0).mean()) * 100, 1), int(m.sum())


def _cell(sub: pd.DataFrame) -> dict:
    dec = sub[sub["Resolved"] == 1]
    n = int(len(dec)); hits = int(dec["Hit"].sum()) if n else 0
    roi, priced = _roi(sub)
    return {"appearances": int(len(sub)), "resolved": n, "hits": hits,
            "hit_rate": (round(hits / n * 100, 1) if n else None),
            "roi": roi, "priced": priced,
            "read": ("too few to trust" if n < MIN_SAMPLE else "out-of-sample")}


def main() -> int:
    if not ARCHIVE.exists():
        print("[grade_lenses] no GreenLight_Archive.csv yet -- run capture_green_light first")
        return 0
    df = pd.read_csv(ARCHIVE)
    if df.empty:
        print("[grade_lenses] archive empty"); return 0
    df = _resolve(df)

    lenses = {LENS_NAME[c]: _cell(df[df[c] == 1]) for c in LENSES if c in df.columns}
    combos = {
        "Opportunity ALONE": _cell(df[(df["L_Opportunity"] == 1) & (df[[c for c in LENSES if c != "L_Opportunity"]].sum(axis=1) == 0)]),
        "Opportunity + Role Stability=Locked": _cell(df[(df["L_Opportunity"] == 1) & (df.get("RoleStability") == "Locked")]),
        "Fragile (single-channel x shaky script)": _cell(df[df.get("Fragile") == 1]),
    }
    tiers = {t: _cell(df[df["Tier"] == t]) for t in df["Tier"].dropna().unique()}

    summary = {
        "by_lens": lenses, "by_combo": combos, "by_tier": tiers,
        "totals": {"rows": int(len(df)), "resolved": int((df["Resolved"] == 1).sum()),
                   "pending": int((df["Resolved"] == 0).sum())},
        "min_sample": MIN_SAMPLE,
        "note": ("Grading evidence, not bets. Each lens's hit rate + ROI is over the plays it "
                 "appeared on; a lens reads 'too few' below the sample floor. Out-of-sample or "
                 "it does not count -- this is the forward record, it accrues as weeks resolve."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    t = summary["totals"]
    print(f"[grade_lenses] {t['rows']} captured | {t['resolved']} resolved, {t['pending']} pending\n")
    print(f"  {'LENS':<34}{'appear':>7}{'resolv':>7}{'hit%':>7}{'ROI%':>8}  read")
    for name, c in {**lenses, **combos}.items():
        hr = f"{c['hit_rate']}" if c["hit_rate"] is not None else "--"
        roi = f"{c['roi']:+}" if c["roi"] is not None else "--"
        print(f"  {name:<34}{c['appearances']:>7}{c['resolved']:>7}{hr:>7}{roi:>8}  [{c['read']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
