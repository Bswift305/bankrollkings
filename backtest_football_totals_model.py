"""
Bankroll Kings - Backtest the football totals projection vs the closing line
============================================================================

Answers the only question that makes the "Our Model vs Vegas" comparison
trustworthy: does our scoring-environment total projection actually beat the
market's closing total, OUT OF SAMPLE?

Method: walk forward through every regular-season game in date order. Before a
game is graded, each team's offense/defense averages use ONLY its prior games
(a trailing window) -- no lookahead. Project the total, compare its side to the
closing `total_line`, grade against the actual combined score. Report win% vs the
-110 break-even (52.38%) and ROI, overall and by edge threshold.

Verdict (NFL_Games_nfldata.csv, 1999-2025, 6,750 graded games, 2026-07-26):
    line RMSE 13.53 < model RMSE 13.81  -> the market is MORE accurate than us.
    win% is 50-51% at every meaningful edge band -> below break-even, negative ROI.
    An opponent-adjusted additive variant did no better (worse, in fact).
    => The NFL totals market is efficient; this projection is NOT an edge. It is
       shown in-product as scoring CONTEXT only, never as a bet signal. This mirrors
       the broader market-efficiency finding (see memory).

Run:  python backtest_football_totals_model.py
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
GAMES = BASE_DIR / "data" / "historical" / "NFL_Games_nfldata.csv"

WINDOW = 17       # trailing games per team (~one season)
MIN_PRIOR = 6     # need this many prior games before projecting
BREAK_EVEN = 0.5238  # -110


def _load() -> pd.DataFrame:
    df = pd.read_csv(GAMES, low_memory=False)
    df["gameday"] = pd.to_datetime(df["gameday"], errors="coerce")
    for col in ("season", "away_score", "home_score", "total_line"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["game_type"].astype(str).str.upper() == "REG"]
    df = df.dropna(subset=["gameday", "away_score", "home_score", "total_line"])
    df = df.sort_values("gameday").reset_index(drop=True)
    df["actual"] = df["away_score"] + df["home_score"]
    return df


def backtest() -> pd.DataFrame:
    df = _load()
    points_for = defaultdict(lambda: deque(maxlen=WINDOW))
    points_against = defaultdict(lambda: deque(maxlen=WINDOW))
    rows = []
    for _, g in df.iterrows():
        away, home = g["away_team"], g["home_team"]
        if len(points_for[away]) >= MIN_PRIOR and len(points_for[home]) >= MIN_PRIOR:
            a_off = sum(points_for[away]) / len(points_for[away])
            a_def = sum(points_against[away]) / len(points_against[away])
            h_off = sum(points_for[home]) / len(points_for[home])
            h_def = sum(points_against[home]) / len(points_against[home])
            proj = (a_off + h_def) / 2 + (h_off + a_def) / 2
            line, actual = g["total_line"], g["actual"]
            if actual != line:  # skip pushes
                rows.append({
                    "season": int(g["season"]),
                    "abs_edge": abs(proj - line),
                    "won": (proj > line) == (actual > line),
                    "proj": proj,
                    "line": line,
                    "actual": actual,
                })
        # update AFTER grading -- no lookahead
        points_for[away].append(g["away_score"]); points_against[away].append(g["home_score"])
        points_for[home].append(g["home_score"]); points_against[home].append(g["away_score"])
    return pd.DataFrame(rows)


def _summary(sub: pd.DataFrame, label: str) -> None:
    n = len(sub)
    wins = int(sub["won"].sum())
    win_pct = (wins / n * 100) if n else 0.0
    roi = ((wins * 0.909 - (n - wins)) / n * 100) if n else 0.0
    print(f"  {label:16s} n={n:5d}  win%={win_pct:5.1f}  ROI@-110={roi:+5.1f}%")


def main() -> int:
    r = backtest()
    if r.empty:
        print("No gradeable games (missing closing total_line?).")
        return 1
    model_rmse = ((r["proj"] - r["actual"]) ** 2).mean() ** 0.5
    line_rmse = ((r["line"] - r["actual"]) ** 2).mean() ** 0.5
    print(f"RMSE  model={model_rmse:.2f}  closing_line={line_rmse:.2f}  "
          f"({'model better' if model_rmse < line_rmse else 'MARKET better'})")
    print(f"Break-even at -110 = {BREAK_EVEN * 100:.1f}%. Walk-forward, no lookahead.")
    _summary(r, "ALL")
    for threshold in (1, 2, 3, 4, 6, 8):
        _summary(r[r["abs_edge"] >= threshold], f"edge>={threshold}")
    beats = (r["won"].mean() > BREAK_EVEN)
    print(f"\nVERDICT: model {'BEATS' if beats else 'does NOT beat'} the closing total out of sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
