# -*- coding: utf-8 -*-
"""
Kings NFL Edge Boards — generate the three validated, honest NFL surfaces from the
scored player-prop data:

  1) TOP PLAYS   — the model's high-conviction leans (BK_NFL_PropScore >= threshold)
  2) USAGE       — high, stable-usage plays (UsageStability top quartile)  [the weekly hook]
  3) WIND REPORT — passing/receiving UNDERS in 15+ mph wind  [the specialist play]

All three were validated on REAL graded props (2024 scout / 2025 out-of-sample); see
FINDINGS.md. This module reads the same scored schema, so in-season you point INPUT at
the live scored-props file (today's slate) and it prints that week's boards.

Usage:
  python nfl_edge_board.py verify     # reproduce the ROI proof on 2024-25 backfill
  python nfl_edge_board.py board 2025 # print sample boards from a season
"""
import sys, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
INPUT = ROOT / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"   # graded history (verify)
LIVE_INPUT = ROOT / "data" / "tracking" / "NFL_LiveProps_Scored.csv"   # this week's slate (board)
PASS = {"Pass Yds", "Pass Comp", "Pass Att", "Rec Yds", "Receptions"}

TOP_SCORE_MIN = 10        # PropScore floor for the Top Plays board (>=20 = premium tier)
USAGE_Q = 0.75            # top-quartile usage
WIND_MIN = 15             # mph

def _num(s):
    return pd.to_numeric(s, errors="coerce")

def load(path=INPUT, graded_only=False):
    df = pd.read_csv(path, dtype=str, low_memory=False)
    if graded_only and "OutcomeState" in df.columns:
        df = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    for c in ["BetPrice", "Confidence", "BK_NFL_PropScore", "UsageStability", "WindMph", "Line"]:
        if c in df.columns:
            df[c] = _num(df[c])
    return df

def model_leans(df):
    """One row per prop = the model's lean side (Confidence > 50). Avoids the both-sides tautology."""
    return df[df["Confidence"] > 50].copy()

# ------------------------------------------------------------------ the three boards
COLS = ["Season", "Week", "Player", "Team", "Opponent", "Stat", "Direction", "Line",
        "BetPrice", "BK_NFL_PropScore", "UsageStability", "WindMph"]

def _view(sub):
    cols = [c for c in COLS if c in sub.columns]
    return sub[cols]

def top_plays(df, min_score=TOP_SCORE_MIN):
    lean = model_leans(df)
    out = lean[lean["BK_NFL_PropScore"] >= min_score].sort_values("BK_NFL_PropScore", ascending=False)
    return _view(out)

def usage_plays(df, q=USAGE_Q):
    lean = model_leans(df)
    thr = lean["UsageStability"].quantile(q)
    out = lean[lean["UsageStability"] >= thr].sort_values("UsageStability", ascending=False)
    return _view(out)

def wind_report(df, wind_min=WIND_MIN):
    # the value side is the UNDER on passing/rec props in high wind
    out = df[(df["Stat"].isin(PASS)) & (df["WindMph"] >= wind_min) &
             (df["Direction"].str.upper() == "UNDER")].sort_values("WindMph", ascending=False)
    return _view(out)

# --------------------------------------------------------------------------- verify
def _ret(price, win):
    dec = 1 + (price / 100 if price > 0 else 100 / abs(price))
    return (dec - 1) if win else -1.0

def _roi(sub):
    if len(sub) < 30:
        return f"n={len(sub)} (small)"
    win = sub["OutcomeState"] == "Hit"
    r = np.mean([_ret(p, w) for p, w in zip(sub["BetPrice"], win)])
    return f"{r*100:+5.1f}% ROI (hit {win.mean():.0%}, n={len(sub):,})"

def verify():
    df = load(graded_only=True)
    df = df[df["BetPrice"].between(-1000, 1000)]
    print("VERIFY — real ROI at BetPrice, 2024 scout / 2025 out-of-sample")
    print("=" * 66)
    boards = {
        "TOP PLAYS  PropScore>=10": top_plays(df, 10),
        "TOP PLAYS  PropScore>=20": top_plays(df, 20),
        "USAGE      top quartile ": usage_plays(df),
        "WIND       15+ pass UNDER": wind_report(df),
    }
    idx = df.set_index(df.index)  # keep OutcomeState/BetPrice alignment
    for name, view in boards.items():
        sub = df.loc[view.index]
        s24, s25 = sub[sub["Season"] == "2024"], sub[sub["Season"] == "2025"]
        print(f"  {name}   2024: {_roi(s24)}   2025: {_roi(s25)}")
    print("\n  (Boards = the exact filters proven in FINDINGS.md. In-season, feed live")
    print("   scored props to top_plays()/usage_plays()/wind_report() for that week's slate.)")

def board(season=None):
    # In-season this reads THIS WEEK's scored props, produced by
    # score_live_nfl_props.py -- the "live scored-props file" the module docstring
    # and FINDINGS.md both refer to, which did not exist until now. Asking for a
    # specific season still reads the graded history, so `board 2025` keeps
    # printing backtest samples and `verify` is untouched.
    path = LIVE_INPUT if (LIVE_INPUT.exists() and not season) else INPUT
    print(f"source: {path.name}")
    df = load(path)
    if season:
        df = df[df["Season"].astype(str) == str(season)]
    for name, fn in [("TOP PLAYS (PropScore>=20)", lambda d: top_plays(d, 20)),
                     ("USAGE / VOLUME", usage_plays), ("WIND REPORT", wind_report)]:
        v = fn(df)
        print(f"\n===== {name} =====  ({len(v):,} plays)")
        print(v.head(10).to_string(index=False))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        verify()
    elif cmd == "board":
        board(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
