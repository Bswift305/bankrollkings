#!/usr/bin/env python3
"""
Per-QB passing profile (recent seasons) so a QB-out can be weighted by WHO the backup is.

A blanket "QB out -> fade the receivers" is wrong for a high-volume gunslinger backup
(Jameis Winston keeps WR volume up, just turnover-prone) vs a game-manager (Marcus
Mariota, the textbook downgrade). This records each QB's attempts/game, yards/attempt,
INT rate and rush attempts/game from nflverse weekly stats, so nfl_backup can classify a
backup's style and scale the prop / total impact instead of a flat rule.

Output: data/scenarios/nfl_qb_profiles.json  { qbs: {name: {att_pg, ypa, int_rate, rush_pg, games, team}} }
Seasons: 2024-2026 (career-ish recency; a backup often last started a year or two ago).
"""
from __future__ import annotations
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_qb_profiles.json"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"


def build(seasons) -> dict:
    frames = []
    for s in seasons:
        tmp = BASE_DIR / "data" / "scenarios" / f"_qbp_{s}.parquet"
        try:
            urllib.request.urlretrieve(STATS_URL.format(season=s), tmp)
            frames.append(pd.read_parquet(tmp))
        except Exception as e:
            print(f"  season {s} skipped: {e}")
        finally:
            tmp.unlink(missing_ok=True)
    if not frames:
        raise SystemExit("no QB data pulled")
    df = pd.concat(frames, ignore_index=True)
    for c in ("attempts", "passing_yards", "passing_interceptions", "carries"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df = df[df["attempts"] > 0]  # QB games
    g = df.groupby("player_display_name").agg(
        games=("week", "count"),
        att=("attempts", "sum"),
        yds=("passing_yards", "sum"),
        ints=("passing_interceptions", "sum"),
        rush=("carries", "sum"),
        team=("team", "last"),
    ).reset_index()
    g = g[g["games"] >= 2]  # need a small sample to profile
    qbs = {}
    for r in g.itertuples():
        qbs[str(r.player_display_name)] = {
            "att_pg": round(r.att / r.games, 1),
            "ypa": round(r.yds / r.att, 2) if r.att else 0,
            "int_rate": round(100 * r.ints / r.att, 1) if r.att else 0,
            "rush_pg": round(r.rush / r.games, 1),
            "games": int(r.games), "team": str(r.team),
        }
    return {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "seasons": list(seasons), "n": len(qbs), "qbs": qbs}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2024,2025,2026")
    args = ap.parse_args()
    data = build([int(s) for s in args.seasons.split(",")])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {data['n']} QB profiles -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
