#!/usr/bin/env python3
"""Backtest: when a CFB team ENTERS a game on an N-game ATS cover streak, how often does it cover
the NEXT one? Out-of-sample, real closing lines. Writes data/scenarios/cfb_ats_streak_forward_rates.json
so the ATS Streaks tool can show each live wave WITH what history says happens next -- the honest
"track & learn" number behind "a streak is a trend the market already prices."

Source: data/tracking/NCAAF_GameLineResults.csv (graded SPREAD rows, Team/Season/Week/Line + scores),
written by the CFB refresh. Uses only seasons with enough graded games to be representative, so the
current (partial) season never biases the rate; it folds in automatically once it completes.

Honest framing baked into the output: the deeper the cover streak, the LESS teams have covered next
(the market moves to catch a hot team). This is priced-in CONTEXT -- who is overbought -- NOT a bet
signal, and emphatically not a "fade = edge" claim (thin sub-samples reverse out-of-sample).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SRC = BASE_DIR / "data" / "tracking" / "NCAAF_GameLineResults.csv"
OUT = BASE_DIR / "data" / "scenarios" / "cfb_ats_streak_forward_rates.json"
MIN_SEASON_GAMES = 1000   # a season needs at least this many graded team-games to count
BREAKEVEN = 52.38         # -110 flat


def _rate(c: int, n: int) -> tuple[float | None, float | None]:
    dec = c + n
    if not dec:
        return None, None
    pct = round(100 * c / dec, 1)
    roi = round(100 * ((c * (100 / 110)) - n) / dec, 1)   # -110 flat stake
    return pct, roi


def build() -> dict:
    df = pd.read_csv(SRC, low_memory=False)
    df = df[df["MarketType"] == "SPREAD"].copy()
    for col in ("Season", "Week", "Line", "TeamScore", "OpponentScore"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Team", "Season", "Week", "Line", "TeamScore", "OpponentScore"])
    df = df.drop_duplicates(subset=["Season", "Team", "Week", "Opponent"], keep="last")

    # Keep only representative (near-complete) seasons so a partial current season can't skew it.
    counts = df.groupby("Season").size()
    seasons = sorted(int(s) for s, n in counts.items() if n >= MIN_SEASON_GAMES)
    df = df[df["Season"].isin(seasons)]

    # cover = margin + the team's own spread: >0 cover, <0 no-cover, ~0 push (breaks the streak).
    cov = df["TeamScore"] - df["OpponentScore"] + df["Line"]
    df = df.assign(res=[("P" if abs(x) < 1e-9 else ("C" if x > 0 else "N")) for x in cov])

    records: list[tuple[int, str]] = []   # (entering_streak, this_game_result)
    for _, g in df.sort_values("Week").groupby(["Season", "Team"]):
        streak = 0
        for res in g["res"].tolist():
            records.append((streak, res))
            streak = streak + 1 if res == "C" else 0
    rec = pd.DataFrame(records, columns=["enter", "res"])

    def bucket(mask) -> dict:
        s = rec[mask]
        c = int((s["res"] == "C").sum()); n = int((s["res"] == "N").sum()); p = int((s["res"] == "P").sum())
        pct, roi = _rate(c, n)
        return {"games": c + n, "cover_pct": pct, "roi": roi, "pushes": p}

    by_depth = {str(k): bucket(rec["enter"] == k) for k in (1, 2, 3, 4, 5)}
    cumulative = {str(k): bucket(rec["enter"] >= k) for k in (3, 4, 5, 6)}

    return {
        "season_range": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
        "seasons": seasons,
        "breakeven_pct": BREAKEVEN,
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "baseline": bucket(rec["enter"] >= 0),
        "by_depth": by_depth,         # entering streak of EXACTLY k
        "cumulative": cumulative,     # entering streak of k OR MORE (what a live wave of depth>=k maps to)
        "note": ("The deeper the cover streak, the less teams have covered next -- the market moves to "
                 "catch a hot team. Priced-in context (who is overbought), not a bet signal."),
    }


def main() -> int:
    if not SRC.exists():
        print(f"[cfb_ats_streak_backtest] source missing: {SRC}")
        return 1
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    cum = data["cumulative"]
    print(f"[cfb_ats_streak_backtest] seasons {data['season_range']} | baseline "
          f"{data['baseline']['cover_pct']}% | 4+ {cum['4']['cover_pct']}% | 5+ {cum['5']['cover_pct']}% "
          f"-> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
