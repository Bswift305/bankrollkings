# -*- coding: utf-8 -*-
"""
Precompute the BK Power player leaderboard -> data/scenarios/bk_power_players.json.

Descriptive, not predictive: for each player, how often their actual result CLEARED
the posted line (over-rate), from real graded props. Ranks the players who consistently
beat their number and the ones who rarely do -- the two angles. Baselines vary by sport
(MLB props skew heavily under). Over-direction rows only, so the metric is directional
and meaningful (the raw hit/miss file is a mechanical 50/50).

    python research/build_bk_power_export.py
"""
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRACK = ROOT / "data" / "tracking"
OUT = ROOT / "data" / "scenarios" / "bk_power_players.json"
SPORTS = ["NFL", "NBA", "MLB", "WNBA"]
MIN_OVERALL = 20   # decided over-props to appear on the board
MIN_STAT = 8       # decided over-props for a per-stat row
MAX_PER_SPORT = 220


def _hit_series(df, flag):
    if flag == "Hit_Binary":
        s = pd.to_numeric(df[flag], errors="coerce")
        return df.assign(_h=s).dropna(subset=["_h"])
    # OutcomeState style
    d = df[df[flag].isin(["Hit", "Miss"])].copy()
    d["_h"] = (d[flag] == "Hit").astype(float)
    return d


def build_sport(sport):
    path = TRACK / f"{sport}_AllPropResults.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return []
    flag = next((c for c in ["Hit_Binary", "OutcomeState", "Result"] if c in df.columns), None)
    if not flag or not {"Player", "Stat", "Direction"}.issubset(df.columns):
        return []
    df = df[df["Direction"].astype(str).str.upper() == "OVER"]
    df = _hit_series(df, flag)
    if df.empty:
        return []
    team_col = "Team" if "Team" in df.columns else None
    rows = []
    for player, g in df.groupby("Player"):
        n = int(len(g))
        if n < MIN_OVERALL:
            continue
        over = float(g["_h"].mean())
        team = ""
        if team_col:
            teams = g[team_col].dropna().astype(str)
            team = teams.iloc[-1] if not teams.empty else ""
        stats = []
        for stat, sg in g.groupby("Stat"):
            if len(sg) >= MIN_STAT:
                stats.append({"stat": str(stat), "n": int(len(sg)), "over": round(float(sg["_h"].mean()), 3)})
        stats.sort(key=lambda x: -x["over"])
        rows.append({
            "player": str(player), "team": str(team), "n": n,
            "over": round(over, 3), "stats": stats[:5],
        })
    rows.sort(key=lambda x: (-x["over"], -x["n"]))
    return rows[:MAX_PER_SPORT]


def main():
    players = {}
    for sport in SPORTS:
        rows = build_sport(sport)
        if rows:
            players[sport] = rows
        print(f"{sport}: {len(rows)} players")
    out = {
        "meta": {
            "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d"),
            "sports": [s for s in SPORTS if s in players],
            "min_props": MIN_OVERALL,
        },
        "players": players,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
