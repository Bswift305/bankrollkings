#!/usr/bin/env python3
"""
Grade a week of NFL plays against real results and append to a persistent
live-results log. Fetches nflverse weekly player stats (the canonical actuals)
so the graded record is real, not in-sample backtest data.

Purpose: build the LIVE track record the 99 scorecard needs (it wants >=50 live
resolved before it will call calibration proven; today it has 0). Run this every
week after games finish.

Usage:
  # grade this week's live PropScore board (run right after the games):
  python grade_nfl_week.py --from-board --season 2026 --week 1
  # grade a plays CSV (Player,Stat,Side,Line[,PropScore]):
  python grade_nfl_week.py --plays week1_plays.csv --season 2026 --week 1
  # summarize the running log only:
  python grade_nfl_week.py --summary

Output: data/tracking/NFL_Weekly_Grade_Log.csv  (append-only, de-duped)
"""
from __future__ import annotations
import argparse
import sys
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "data" / "tracking" / "NFL_Weekly_Grade_Log.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"

# our board stat label -> nflverse weekly-stats column
STAT_COL = {
    "Rec Yds": "receiving_yards", "Receptions": "receptions", "Rush Yds": "rushing_yards",
    "Rush Att": "carries", "Pass TDs": "passing_tds", "Pass Yds": "passing_yards",
    "Pass Completions": "completions", "Pass Comp": "completions", "Rush TDs": "rushing_tds",
    "Rec TDs": "receiving_tds", "Pass INT": "passing_interceptions", "Pass Att": "attempts",
}
LOG_COLUMNS = ["Season", "Week", "Player", "Stat", "Side", "Line", "PropScore",
               "Actual", "Result", "GradedAt"]


SNAP_DIR = BASE_DIR / "data" / "tracking" / "nfl_grade_snapshots"


def _season_df(season: int) -> pd.DataFrame:
    """Download the season's weekly player stats once and return the full frame."""
    url = STATS_URL.format(season=season)
    tmp = BASE_DIR / "data" / "tracking" / f"_nflverse_stats_{season}.parquet"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, tmp)
    return pd.read_parquet(tmp)


def fetch_actuals(season: int, week: int) -> pd.DataFrame:
    print(f"Fetching actuals: {STATS_URL.format(season=season)}")
    df = _season_df(season)
    df = df[df["week"] == week].copy()
    if df.empty:
        raise SystemExit(f"No player rows for {season} week {week} yet (games may not be graded).")
    print(f"  {len(df)} player rows for {season} week {week}")
    return df


def snapshot(season: int, week: int) -> int:
    """Capture the current PropScore board as this week's featured set, so it can be
    graded once games finish. Overwrites the week's snapshot (board firms up)."""
    plays = plays_from_board()
    if plays.empty:
        print("No board plays to snapshot."); return 0
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAP_DIR / f"{season}_wk{week}.csv"
    plays.to_csv(out, index=False)
    print(f"Snapshotted {len(plays)} board plays -> {out}")
    return len(plays)


def resolve_all() -> None:
    """Grade every snapshot whose week has actuals yet, appending to the log. Safe to
    run daily: dedupe keeps the latest grade, so NODATA rows resolve as games finish."""
    import re
    if not SNAP_DIR.exists():
        print("No snapshots to resolve."); return
    cache: dict[int, pd.DataFrame] = {}
    combined = None
    for f in sorted(SNAP_DIR.glob("*_wk*.csv")):
        m = re.match(r"(\d{4})_wk(\d+)\.csv", f.name)
        if not m:
            continue
        season, week = int(m.group(1)), int(m.group(2))
        if season not in cache:
            try:
                cache[season] = _season_df(season)
            except Exception as exc:
                print(f"  actuals fetch failed for {season}: {exc}"); continue
        wk = cache[season][cache[season]["week"] == week]
        if wk.empty:
            print(f"  wk{week}: no actuals yet — skipping"); continue
        graded = grade_plays(pd.read_csv(f), wk, season, week)
        combined = append_log(graded)
        print(f"  wk{week}: graded {len(graded)} plays")
    if combined is not None:
        summarize(combined)


def _actual(actuals: pd.DataFrame, player: str, stat: str):
    col = STAT_COL.get(stat)
    if not col or col not in actuals.columns:
        return None
    m = actuals[actuals["player_display_name"].astype(str).str.lower() == player.lower()]
    if m.empty:  # last-word fuzzy fallback
        m = actuals[actuals["player_display_name"].astype(str).str.contains(
            player.split()[-1], case=False, na=False, regex=False)]
    return None if m.empty else float(m.iloc[0][col])


def grade_plays(plays: pd.DataFrame, actuals: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    from datetime import datetime
    rows = []
    for _, p in plays.iterrows():
        player = str(p["Player"]).strip()
        stat = str(p["Stat"]).strip()
        side = str(p["Side"]).strip().upper()
        line = pd.to_numeric(p.get("Line"), errors="coerce")
        a = _actual(actuals, player, stat)
        if a is None or pd.isna(line):
            result = "NODATA"
        elif a == line:
            result = "PUSH"
        else:
            hit = (a > line) if side == "OVER" else (a < line)
            result = "WIN" if hit else "LOSS"
        rows.append({"Season": season, "Week": week, "Player": player, "Stat": stat,
                     "Side": side, "Line": line, "PropScore": p.get("PropScore"),
                     "Actual": a, "Result": result, "GradedAt": datetime.now().isoformat(timespec="seconds")})
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def plays_from_board(limit: int = 500) -> pd.DataFrame:
    sys.path.insert(0, str(BASE_DIR))
    import app as A
    sp = A.build_nfl_spots_context(limit=limit)
    out = [{"Player": r.get("player"), "Stat": r.get("stat"), "Side": r.get("direction"),
            "Line": r.get("line"), "PropScore": r.get("prop_score")}
           for r in (sp.get("sp_top") or [])]
    return pd.DataFrame(out)


def append_log(graded: pd.DataFrame) -> pd.DataFrame:
    if LOG_PATH.exists():
        old = pd.read_csv(LOG_PATH)
        combined = pd.concat([old, graded], ignore_index=True)
    else:
        combined = graded.copy()
    # de-dupe: one row per (Season, Week, Player, Stat, Side, Line) -- keep latest grade
    combined = combined.drop_duplicates(subset=["Season", "Week", "Player", "Stat", "Side", "Line"], keep="last")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(LOG_PATH, index=False)
    return combined


def summarize(df: pd.DataFrame):
    graded = df[df["Result"].isin(["WIN", "LOSS"])]
    w = int((graded["Result"] == "WIN").sum()); l = len(graded) - w
    print("\n=== LIVE GRADE LOG ===")
    print(f"Resolved: {len(graded)} (need >= 50 for the scorecard) | Record: {w}-{l}"
          f"{f' | Hit {w/len(graded)*100:.0f}%' if len(graded) else ''}")
    ps = pd.to_numeric(df.get("PropScore"), errors="coerce")
    for label, mask in [("Premium (>=20)", ps >= 20), ("Floor (10-20)", (ps >= 10) & (ps < 20))]:
        sub = graded[mask.reindex(graded.index, fill_value=False)]
        if len(sub):
            ww = int((sub["Result"] == "WIN").sum())
            print(f"  {label}: {ww}-{len(sub)-ww} ({ww/len(sub)*100:.0f}%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int)
    ap.add_argument("--from-board", action="store_true", help="Grade the current live PropScore board")
    ap.add_argument("--plays", help="CSV of plays to grade (Player,Stat,Side,Line[,PropScore])")
    ap.add_argument("--summary", action="store_true", help="Only print the running log summary")
    ap.add_argument("--snapshot", action="store_true", help="Capture this week's board for later grading (weekly)")
    ap.add_argument("--resolve", action="store_true", help="Grade all snapshots that now have actuals (daily)")
    args = ap.parse_args()

    if args.summary:
        if not LOG_PATH.exists():
            print("No log yet."); return 0
        summarize(pd.read_csv(LOG_PATH)); return 0

    def _week():
        if args.week:
            return args.week
        try:
            from nfl_early_season_gate import current_week
            return current_week()
        except Exception:
            return None

    if args.snapshot:
        wk = _week()
        if not wk:
            print("No current NFL week (offseason) — nothing to snapshot."); return 0
        snapshot(args.season, wk); return 0

    if args.resolve:
        resolve_all(); return 0

    if not args.week:
        ap.error("--week is required unless --summary")
    if args.from_board:
        plays = plays_from_board()
    elif args.plays:
        plays = pd.read_csv(args.plays)
    else:
        ap.error("pass --from-board or --plays")
    if plays.empty:
        print("No plays to grade."); return 0

    actuals = fetch_actuals(args.season, args.week)
    graded = grade_plays(plays, actuals, args.season, args.week)
    print(graded[["Player", "Stat", "Side", "Line", "Actual", "Result"]].to_string(index=False))
    combined = append_log(graded)
    summarize(combined)
    print(f"\nLogged {len(graded)} plays -> {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
