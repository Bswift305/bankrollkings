"""
build_nfl_coaching.py  -- Wisdomism lens: COACHING / STRUCTURE

The question none of the player lenses ask: WHY does it keep happening? Coaching tendencies
are structural -- they survive roster changes, and the market prices the star QB, not the
offensive coordinator's habits. This is the least-priced thing the audit surfaced.

Team-level, from 2019-25 nflverse PBP (competitive snaps only):
  - 4th-down aggression -- go-for-it rate in goable spots (4th & <=4, midfield);
  - tempo -- no-huddle rate;
  - early-down pass identity -- 1st/2nd-down neutral pass rate (pass-first vs run-first);
  - red-zone run/pass tendency.
Emits data/scenarios/nfl_coaching.json (committed) keyed by team -> the Coaching lens.

CAVEAT (honest, like the QB-form caveat): tendencies are the team's RECENT regime. A new
coordinator breaks them -- coaching lens is roster-stable, NOT staff-stable.

Doctrine: de-averages, does not predict. See docs/wisdomism_lens_families.md (Coaching).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PBP_PATH = BASE / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
OUT_CSV = BASE / "data" / "tracking" / "NFL_Coaching.csv"
FLAGS_PATH = BASE / "data" / "scenarios" / "nfl_coaching.json"

RECENT_SEASONS = [2023, 2024, 2025]
GARBAGE_WP_LOW, GARBAGE_WP_HIGH = 0.05, 0.95


def load() -> pd.DataFrame:
    df = pd.read_parquet(PBP_PATH, columns=[
        "season", "posteam", "wp", "down", "ydstogo", "yardline_100", "play_type",
        "pass_attempt", "rush_attempt", "no_huddle", "score_differential", "half_seconds_remaining"])
    df = df[df["season"].isin(RECENT_SEASONS) & df["posteam"].notna()].copy()
    wp = pd.to_numeric(df["wp"], errors="coerce")
    df = df[wp.between(GARBAGE_WP_LOW, GARBAGE_WP_HIGH)].copy()
    for c in ("down", "ydstogo", "yardline_100", "pass_attempt", "rush_attempt",
              "no_huddle", "score_differential", "half_seconds_remaining"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["is_pass"] = df["pass_attempt"] == 1
    df["is_rush"] = df["rush_attempt"] == 1
    df["scrim"] = df["is_pass"] | df["is_rush"]           # a run/pass snap (not FG/punt/no-play)
    return df


def build() -> pd.DataFrame:
    df = load()
    rows = []
    for T, g in df.groupby("posteam"):
        scrim = g[g["scrim"]]
        # 4th-down aggression: in goable spots (4th & <=4, between the 35s), did they go?
        goable = g[(g["down"] == 4) & (g["ydstogo"] <= 4) & g["yardline_100"].between(35, 65)]
        go = goable[goable["scrim"]]              # ran a play (vs FG/punt)
        fourth_go = (len(go) / len(goable)) if len(goable) else None
        # tempo: no-huddle rate
        no_huddle = scrim["no_huddle"].fillna(0).mean() if len(scrim) else None
        # early-down pass identity: 1st/2nd down, neutral score & time
        early = scrim[(scrim["down"].isin([1, 2])) & (scrim["score_differential"].abs() <= 8)
                      & (scrim["half_seconds_remaining"] > 120)]
        early_pass = (early["is_pass"].sum() / len(early)) if len(early) else None
        # red-zone tendency: inside-20 pass rate
        rz = scrim[scrim["yardline_100"] <= 20]
        rz_pass = (rz["is_pass"].sum() / len(rz)) if len(rz) else None
        rows.append({"team": T, "plays": int(len(scrim)),
                     "fourth_go": fourth_go, "fourth_n": int(len(goable)),
                     "no_huddle": no_huddle, "early_pass": early_pass, "rz_pass": rz_pass})
    out = pd.DataFrame(rows)
    for c in ("fourth_go", "no_huddle", "early_pass", "rz_pass"):
        out[c + "_rank"] = out[c].rank(ascending=False, method="min")   # 1 = most aggressive/fastest/pass-heavy
    return out.sort_values("early_pass", ascending=False).reset_index(drop=True)


def compute_flags(out: pd.DataFrame) -> dict:
    """Per-team coaching identity note -- the tendencies that stand out from league norm."""
    lg = {c: out[c].mean() for c in ("fourth_go", "no_huddle", "early_pass", "rz_pass")}
    flags = {}
    for _, r in out.iterrows():
        notes = []
        if r["fourth_go"] is not None and r["fourth_go"] >= 0.55:
            notes.append(f"aggressive on 4th down ({round(r['fourth_go']*100)}% go in goable spots)")
        elif r["fourth_go"] is not None and r["fourth_go"] <= 0.30 and r["fourth_n"] >= 8:
            notes.append("conservative on 4th down")
        if r["no_huddle"] is not None and r["no_huddle"] >= lg["no_huddle"] * 1.6:
            notes.append(f"up-tempo ({round(r['no_huddle']*100)}% no-huddle)")
        if r["early_pass"] is not None and r["early_pass"] >= 0.60:
            notes.append(f"pass-first on early downs ({round(r['early_pass']*100)}%)")
        elif r["early_pass"] is not None and r["early_pass"] <= 0.48:
            notes.append(f"run-first on early downs ({round(r['early_pass']*100)}% pass)")
        if r["rz_pass"] is not None and r["rz_pass"] >= 0.60:
            notes.append("throws in the red zone")
        elif r["rz_pass"] is not None and r["rz_pass"] <= 0.42:
            notes.append("runs it in the red zone")
        if notes:
            flags[str(r["team"])] = {
                "note": "; ".join(notes),
                "fourth_go": round(r["fourth_go"], 3) if r["fourth_go"] is not None else None,
                "early_pass": round(r["early_pass"], 3) if r["early_pass"] is not None else None,
                "rz_pass": round(r["rz_pass"], 3) if r["rz_pass"] is not None else None,
                "no_huddle": round(r["no_huddle"], 3) if r["no_huddle"] is not None else None,
            }
    return flags


def main() -> None:
    out = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.round(3).to_csv(OUT_CSV, index=False)
    flags = compute_flags(out)
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAGS_PATH.write_text(json.dumps(flags, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_CSV} ({len(out)} teams)")
    print(f"Wrote {FLAGS_PATH} ({len(flags)} teams with a standout tendency)\n")
    print("Most pass-first early downs:")
    for _, r in out.head(6).iterrows():
        print(f"   {r['team']:<4} early-down pass {r['early_pass']:.0%}  4th-go {r['fourth_go']:.0%}  RZ pass {r['rz_pass']:.0%}")
    print("Most run-first early downs:")
    for _, r in out.tail(6).iterrows():
        print(f"   {r['team']:<4} early-down pass {r['early_pass']:.0%}  4th-go {r['fourth_go']:.0%}  RZ pass {r['rz_pass']:.0%}")
    print("\nMost aggressive on 4th down (goable spots):")
    for _, r in out.sort_values('fourth_go', ascending=False).head(6).iterrows():
        print(f"   {r['team']:<4} {r['fourth_go']:.0%} go  (n={int(r['fourth_n'])})")


if __name__ == "__main__":
    main()
