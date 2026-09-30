#!/usr/bin/env python3
"""Append a daily snapshot of NFL player-prop lines to a persistent archive, so we build
a real 2026 line history (open -> close) to grade "tickets we could have hit" against over
time. The Odds API only serves CURRENT lines, so if we don't capture them daily they're
gone. Idempotent: one row per (SnapshotDate, Player, Stat) -- re-running the same day
updates that day's snapshot rather than duplicating it.

data/tracking/ is gitignored, so PROD accumulates its own running record (like the game
line-open ledger). Wire into run_daily.py so it runs every day in season.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from app import load_nfl_schedule

BASE_DIR = Path(__file__).resolve().parent
PROPS_PATH = BASE_DIR / "data" / "props" / "NFL_Props.csv"
OUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_PropLines_Archive.csv"

# Only the stats we actually model / grade (skip Anytime TD, tackles-for-props we don't line-grade)
KEEP_STATS = {"Pass Yds", "Pass Completions", "Pass TDs", "Rush Yds", "Rush Att",
              "Rec Yds", "Receptions", "Solo Tackles", "Tackles + Assists", "Sacks"}


def _eastern_today() -> str:
    try:
        from services.timeutils import to_eastern_date_str  # noqa
        return to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _game_dates() -> dict:
    """Map 'AwayFull@HomeFull' -> game Date from the schedule, so each captured line
    carries the game date (for grading and open->close week bucketing)."""
    out = {}
    try:
        sch = load_nfl_schedule()
        for _, r in sch.iterrows():
            a = str(r.get("AwayFull") or r.get("Away") or "").strip()
            h = str(r.get("HomeFull") or r.get("Home") or "").strip()
            if a and h:
                out[f"{a}@{h}"] = str(r.get("Date") or "")
    except Exception:
        pass
    return out


def main() -> int:
    if not PROPS_PATH.exists():
        print("[capture_nfl_prop_lines] no props feed; nothing to capture")
        return 0
    try:
        df = pd.read_csv(PROPS_PATH)
    except Exception as exc:
        print(f"[capture_nfl_prop_lines] could not read props: {exc}")
        return 1
    if df.empty or not {"Player", "Stat", "Line"}.issubset(df.columns):
        print("[capture_nfl_prop_lines] props feed empty / missing columns")
        return 0
    df = df[df["Stat"].isin(KEEP_STATS)].copy()
    df["Line"] = pd.to_numeric(df["Line"], errors="coerce")
    for c in ("OverOdds", "UnderOdds"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df.dropna(subset=["Line"])
    if df.empty:
        print("[capture_nfl_prop_lines] no gradeable prop rows")
        return 0

    snap = _eastern_today()
    gdates = _game_dates()
    rows = []
    for (player, stat), g in df.groupby(["Player", "Stat"]):
        # the MAIN line = most common across books; consensus odds AT that line
        main_line = g["Line"].mode()
        main_line = float(main_line.iloc[0]) if len(main_line) else float(g["Line"].median())
        at = g[g["Line"] == main_line]
        over = at["OverOdds"][at["OverOdds"].abs() >= 100]
        under = at["UnderOdds"][at["UnderOdds"].abs() >= 100]
        game = str(g["Game"].iloc[0]) if "Game" in g.columns else ""
        rows.append({
            "SnapshotDate": snap,
            "Season": 2026,
            "Player": str(player),
            "Team": str(g["Team"].iloc[0]) if "Team" in g.columns and pd.notna(g["Team"].iloc[0]) else "",
            "Stat": str(stat),
            "Line": main_line,
            "OverOdds": int(round(over.median())) if len(over) else "",
            "UnderOdds": int(round(under.median())) if len(under) else "",
            "BookCount": int(g["Book"].nunique()) if "Book" in g.columns else int(len(g)),
            "Game": game,
            "GameDate": gdates.get(game, ""),
        })
    fresh = pd.DataFrame(rows)

    cols = ["SnapshotDate", "Season", "Player", "Team", "Stat", "Line", "OverOdds",
            "UnderOdds", "BookCount", "Game", "GameDate"]
    if OUT_PATH.exists():
        try:
            prior = pd.read_csv(OUT_PATH)
        except Exception:
            prior = pd.DataFrame(columns=cols)
        # drop any existing rows for this same snapshot day + player + stat, then append
        if not prior.empty and {"SnapshotDate", "Player", "Stat"}.issubset(prior.columns):
            key = prior["SnapshotDate"].astype(str) + "|" + prior["Player"].astype(str) + "|" + prior["Stat"].astype(str)
            newkey = set(fresh["SnapshotDate"].astype(str) + "|" + fresh["Player"].astype(str) + "|" + fresh["Stat"].astype(str))
            prior = prior[~key.isin(newkey)]
        combined = pd.concat([prior, fresh], ignore_index=True)
    else:
        combined = fresh
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for c in cols:
        if c not in combined.columns:
            combined[c] = ""
    combined[cols].to_csv(OUT_PATH, index=False)
    print(f"[capture_nfl_prop_lines] snapshot {snap}: {len(fresh)} player-stat lines -> "
          f"{OUT_PATH.name} ({len(combined)} total rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
