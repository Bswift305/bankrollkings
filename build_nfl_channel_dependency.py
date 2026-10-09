"""
build_nfl_channel_dependency.py  -- Wisdomism lens: MULTI-CHANNEL DEPENDENCY

How many independent PATHS does a player's production run through? A single-channel player
(Derrick Henry: carries or bust) and a dual-threat (Christian McCaffrey / Deebo / Achane: rush
AND receive) are fundamentally different betting profiles -- not in how MUCH (Opportunity) or
how STABLE week to week (Role Stability), but in how ROBUST the floor is to one channel being
taken away.

Mechanism (doctrine Q2, independent): production diversification -- the number of ways a player
can win. Distinct axis from level (Opportunity), time-variance (Role Stability), scoring-area
share (Concentration). It's the player-side complement to Script Certainty (the game side):
single-channel + a script that might not happen = the most fragile bet on the board.

SCOPE (doctrine Q3 -- market applicability is uneven, so we label it):
  - APPLIES to: anytime-TD, floor/ceiling, "will he produce at all", player-total markets --
    a dual-threat has fallbacks when one channel is stuffed.
  - DOES NOT apply to a single-channel YARDAGE prop (Henry's rush-yards floor doesn't care
    that he can't catch). Not a yardage-prop signal.

Built from current-season totals. RB: rush vs rec yards. WR/TE: rec vs rush (gadget). QB: pass
vs rush (dual-threat). Effective channels = 1 / HHI of the two yardage shares. Emits
data/scenarios/nfl_channel_dependency.json (committed). Describes robustness; predicts nothing.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
STATS = BASE / "data" / "tracking" / "_nflverse_stats_2026.parquet"
OUT_CSV = BASE / "data" / "tracking" / "NFL_Channel_Dependency.csv"
FLAGS_PATH = BASE / "data" / "scenarios" / "nfl_channel_dependency.json"

MIN_GAMES = 3
MIN_YARDS = 120         # enough total production for the split to mean something
MIN_SECONDARY_YDS = 50  # the second channel needs REAL volume, not just a balanced ratio
SINGLE_EFF = 1.25       # effective channels below this = one path (~>=88% in primary)


def _channels(pos: str):
    """(primary label, primary col, secondary label, secondary col, markets) by position."""
    if pos == "QB":
        return ("pass", "passing_yards", "rush", "rushing_yards", "QB rush / anytime-TD")
    if pos in ("WR", "TE"):
        return ("rec", "receiving_yards", "rush", "rushing_yards", "anytime-TD / gadget / floor")
    return ("rush", "rushing_yards", "rec", "receiving_yards", "anytime-TD / receptions / floor")


def build() -> pd.DataFrame:
    df = pd.read_parquet(STATS)
    for c in ("rushing_yards", "receiving_yards", "passing_yards", "rushing_tds", "receiving_tds"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else:
            df[c] = 0.0
    rows = []
    for name, g in df.groupby("player_display_name"):
        pos = str(g["position"].mode().iloc[0]) if len(g["position"].mode()) else ""
        if pos not in ("RB", "FB", "HB", "WR", "TE", "QB"):
            continue
        gp = int(g["week"].nunique())
        if gp < MIN_GAMES:
            continue
        p_lab, p_col, s_lab, s_col, markets = _channels(pos)
        p_yds = max(0.0, float(g[p_col].sum()))   # clamp: a lost-yardage reverse/kneel isn't a channel
        s_yds = max(0.0, float(g[s_col].sum()))
        total = p_yds + s_yds
        if total < MIN_YARDS:
            continue
        p_sh, s_sh = p_yds / total, s_yds / total
        hhi = p_sh ** 2 + s_sh ** 2
        eff = round(1.0 / hhi, 2) if hhi else 1.0
        # dual-threat needs a balanced split AND real volume in the 2nd channel -- not a
        # 50/50 ratio on a backup's 90 yards.
        dual = eff >= SINGLE_EFF and s_yds >= MIN_SECONDARY_YDS
        if not dual:
            dependency = f"Single-channel ({p_lab})"
        elif pos == "QB":
            dependency = "Dual-threat QB"
        else:
            dependency = "Dual-threat"
        scores_both = bool(g["rushing_tds"].sum() > 0 and g["receiving_tds"].sum() > 0)
        rows.append({
            "player": str(name), "team": str(g["team"].mode().iloc[0]), "pos": pos,
            "games": gp, "primary": p_lab, "secondary": s_lab,
            "primary_pct": round(p_sh * 100), "secondary_pct": round(s_sh * 100),
            "eff_channels": eff, "dependency": dependency, "total_yds": round(total),
            "scores_both": scores_both, "markets": markets,
        })
    return pd.DataFrame(rows).sort_values("total_yds", ascending=False)


def main() -> None:
    out = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    flags = {r["player"]: {k: r[k] for k in ("pos", "primary", "secondary", "primary_pct",
                                             "secondary_pct", "eff_channels", "dependency",
                                             "scores_both", "markets")}
             for _, r in out.iterrows()}
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAGS_PATH.write_text(json.dumps(flags, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_CSV} ({len(out)} players) + {FLAGS_PATH.name}\n")

    print("DUAL-THREAT (robust floor -- more than one way to win):")
    for _, r in out[out["dependency"].str.startswith("Dual")].head(10).iterrows():
        tdn = " +scores both ways" if r["scores_both"] else ""
        print(f"   {r['player']:<20} {r['pos']:<3} {r['primary_pct']}% {r['primary']} / {r['secondary_pct']}% {r['secondary']}  (eff {r['eff_channels']}){tdn}")
    print("\nSINGLE-CHANNEL (fragile -- one path, script/matchup-dependent):")
    for _, r in out[out["dependency"].str.startswith("Single")].head(10).iterrows():
        print(f"   {r['player']:<20} {r['pos']:<3} {r['primary_pct']}% {r['primary']} ({r['total_yds']} yds)  (eff {r['eff_channels']})")


if __name__ == "__main__":
    main()
