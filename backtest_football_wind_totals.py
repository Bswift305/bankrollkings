"""
Bankroll Kings - Does the market underprice WIND on football totals?
====================================================================

Unlike a scoring-environment total projection (which the market prices fully --
see backtest_football_totals_model.py), high wind at OUTDOOR stadiums is a timing
signal the market is slow to fully absorb. This tests it honestly against the
closing total, by wind bucket, including a recent-seasons out-of-sample check.

Source: NFL_Games_nfldata.csv (outdoor games only; dome/closed have no wind).
Grade: did the game go UNDER the closing total_line? Report UNDER hit% vs the
-110 break-even (52.4%) and ROI, by wind speed.

Finding (2026-07-26, 4,980 outdoor games 1999-2025):
    wind  0-5 : UNDER 50.0%   (no edge)
    wind 10-15: UNDER 53.9%  (+2.9%)
    wind 15-20: UNDER 56.3%  (+7.6%)
    wind 20+  : UNDER 55.9%  (+6.8%)
    >=15mph, 2020+ (out of sample): 54.9%  (+4.7%)  n=113
    => Monotonic dose-response that PERSISTS out of sample. The market underprices
       high wind on totals. A real (modest) edge and a legit timing signal, because
       game-week wind forecasts update. Lean UNDER on high-wind outdoor games.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
GAMES = BASE_DIR / "data" / "historical" / "NFL_Games_nfldata.csv"
BREAK_EVEN = 52.38


def _load() -> pd.DataFrame:
    df = pd.read_csv(GAMES, low_memory=False)
    for col in ("season", "away_score", "home_score", "total_line", "wind"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["game_type"].astype(str).str.upper() == "REG"].copy()
    df["actual"] = df["away_score"] + df["home_score"]
    outdoor = df[df["roof"].astype(str).str.lower().isin(["outdoors", "open"])]
    return outdoor.dropna(subset=["actual", "total_line", "wind"])


def _under_stats(sub: pd.DataFrame, label: str) -> None:
    sub = sub[sub["actual"] != sub["total_line"]]
    n = len(sub)
    unders = int((sub["actual"] < sub["total_line"]).sum())
    win_pct = (unders / n * 100) if n else 0.0
    roi = ((unders * 0.909 - (n - unders)) / n * 100) if n else 0.0
    avg_wind = sub["wind"].mean() if n else 0.0
    print(f"  {label:16s} n={n:5d}  UNDER%={win_pct:5.1f}  ROI@-110={roi:+5.1f}%  avgWind={avg_wind:4.1f}")


def main() -> int:
    outdoor = _load()
    if outdoor.empty:
        print("No outdoor games with wind + closing line.")
        return 1
    print(f"Outdoor games with wind+line: {len(outdoor)}  "
          f"({int(outdoor['season'].min())}-{int(outdoor['season'].max())})")
    print(f"Break-even at -110 = {BREAK_EVEN}%. Does the UNDER beat the closing total?")
    for lo, hi, label in [(0, 5, "wind 0-5"), (5, 10, "wind 5-10"), (10, 15, "wind 10-15"),
                          (15, 20, "wind 15-20"), (20, 999, "wind 20+")]:
        _under_stats(outdoor[(outdoor["wind"] >= lo) & (outdoor["wind"] < hi)], label)
    print("Out-of-sample (recent seasons), high wind >= 15 mph:")
    _under_stats(outdoor[(outdoor["wind"] >= 15) & (outdoor["season"] >= 2015)], ">=15, 2015+")
    _under_stats(outdoor[(outdoor["wind"] >= 15) & (outdoor["season"] >= 2020)], ">=15, 2020+")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
