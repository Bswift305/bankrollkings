"""
build_nfl_role_stability.py  -- Wisdomism lens: ROLE STABILITY

The first genuinely new lens since the original families. Every other lens measures a MEAN
(how much opportunity, how good the matchup). This measures a VARIANCE: how PREDICTABLE a
player's role is week to week. Two backs at 60% carry share aren't the same bet if one ranges
58-62% and the other swings 35-85% on game script.

Mechanism (what makes it independent, per the doctrine's Question 2): coaching + personnel
TRUST produce stable deployment. Not opportunity (the level), not matchup, not market -- its
own cause. And it's the missing half of a FLOOR: a floor is high opportunity *and* a stable
role. A high-share player with a chaotic role has no floor; the share is an average hiding the
swing.

Built from the current-season weekly stats (share per game). WR/TE: target share. RB: carry
share (player carries / team carries). Emits data/scenarios/nfl_role_stability.json (committed),
keyed by player name. Describes consistency; predicts nothing. See BANKROLL_KINGS_DOCTRINE.md S10.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
STATS = BASE / "data" / "tracking" / "_nflverse_stats_2026.parquet"
OUT_CSV = BASE / "data" / "tracking" / "NFL_Role_Stability.csv"
FLAGS_PATH = BASE / "data" / "scenarios" / "nfl_role_stability.json"

MIN_GAMES = 3
# a role has to be real before its stability means anything
MIN_TGT_SHARE = 0.12       # WR/TE: ~a rotational+ target share
MIN_RUSH_SHARE = 0.25      # RB: at least a committee share
# coefficient of variation bands (std / mean of the per-game share)
LOCKED_CV = 0.22
STEADY_CV = 0.45


def _label(cv: float) -> str:
    if cv <= LOCKED_CV:
        return "Locked"
    if cv <= STEADY_CV:
        return "Steady"
    return "Volatile"


def build() -> pd.DataFrame:
    df = pd.read_parquet(STATS)
    df["carries"] = pd.to_numeric(df.get("carries"), errors="coerce").fillna(0)
    df["targets"] = pd.to_numeric(df.get("targets"), errors="coerce").fillna(0)
    df["target_share"] = pd.to_numeric(df.get("target_share"), errors="coerce")
    # team carries per week -> each back's per-game carry share
    team_car = df.groupby(["team", "week"])["carries"].sum().rename("team_car").reset_index()
    df = df.merge(team_car, on=["team", "week"], how="left")
    df["carry_share"] = np.where(df["team_car"] > 0, df["carries"] / df["team_car"], np.nan)

    rows = []
    for name, g in df.groupby("player_display_name"):
        pos = str(g["position"].mode().iloc[0]) if len(g["position"].mode()) else ""
        if pos in ("RB", "FB", "HB"):
            series = g[g["carries"] > 0]["carry_share"].dropna()
            role_type, floor_share = "rush", MIN_RUSH_SHARE
        elif pos in ("WR", "TE"):
            series = g[g["targets"] > 0]["target_share"].dropna()
            role_type, floor_share = "target", MIN_TGT_SHARE
        else:
            continue
        n = int(len(series))
        if n < MIN_GAMES:
            continue
        mean = float(series.mean())
        if mean < floor_share:
            continue
        sd = float(series.std(ddof=0))
        cv = round(sd / mean, 3) if mean else None
        rows.append({
            "player": str(name), "team": str(g["team"].mode().iloc[0]), "pos": pos,
            "role_type": role_type, "games": n,
            "mean_share": round(mean * 100, 1), "cv": cv,
            "min_share": round(float(series.min()) * 100), "max_share": round(float(series.max()) * 100),
            "stability": _label(cv) if cv is not None else "",
        })
    return pd.DataFrame(rows).sort_values(["stability", "mean_share"], ascending=[True, False])


def main() -> None:
    out = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    flags = {r["player"]: {k: r[k] for k in ("role_type", "games", "mean_share", "cv",
                                             "min_share", "max_share", "stability")}
             for _, r in out.iterrows()}
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAGS_PATH.write_text(json.dumps(flags, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_CSV} ({len(out)} players) + {FLAGS_PATH.name}\n")

    print("LOCKED roles (a real floor -- share barely moves):")
    for _, r in out[out["stability"] == "Locked"].sort_values("mean_share", ascending=False).head(8).iterrows():
        print(f"   {r['player']:<20} {r['pos']:<3} {r['mean_share']:.0f}% {r['role_type']} share  (cv {r['cv']}, range {r['min_share']}-{r['max_share']}%)")
    print("\nVOLATILE roles (same average, no floor -- swings on script):")
    for _, r in out[out["stability"] == "Volatile"].sort_values("mean_share", ascending=False).head(8).iterrows():
        print(f"   {r['player']:<20} {r['pos']:<3} {r['mean_share']:.0f}% {r['role_type']} share  (cv {r['cv']}, range {r['min_share']}-{r['max_share']}%)")


if __name__ == "__main__":
    main()
