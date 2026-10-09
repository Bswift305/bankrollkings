"""
CFB Mechanism Audit #1 -- Opponent-Adjusted Team Strength (read-only research)

Question: does a point-in-time opponent-adjusted team-strength rating (SRS: margin of
victory adjusted for strength of schedule, solved by least squares) predict ATS outcomes
well enough to beat the market baseline? Or is team strength already in the spread?

Governance rules baked in (CFB evidence-base audit + the Director's corrections):
- POINT-IN-TIME: a game in (season, week W) is predicted using ONLY games with week < W in
  the SAME season. No full-season aggregates, no next-week leakage.
- INDEPENDENT UNIT = GAME. One row per game (the history already is); n counts games, never
  book-rows or snapshots.
- HONEST BASELINE: the market. The spread already encodes team strength, so the null is
  ~50% ATS (break-even ~52.4% at -110). A mechanism "works" only if it clears that, out of
  sample, with a CI that doesn't straddle it.

Self-contained, reads data/historical/NCAAF_GameLines_History.csv, writes nothing.
Run: py -3 research/cfb_mechanism/audit_opponent_adjusted_strength.py
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[2]
HIST = BASE / "data" / "historical" / "NCAAF_GameLines_History.csv"
MIN_PRIOR_GAMES = 3     # each team needs >=3 prior games this season to be rated
MIN_WEEK = 4            # don't predict before enough schedule exists
RIDGE = 1e-3            # gauge-fixing / regularization weight


def _wilson(k: int, n: int):
    """95% Wilson interval for a binomial proportion."""
    if n == 0:
        return (None, None)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - h) / d * 100, 1), round((c + h) / d * 100, 1)


def _load() -> pd.DataFrame:
    df = pd.read_csv(HIST)
    df = df.drop_duplicates(["Season", "Week", "Away", "Home"])      # unit = game
    for c in ("AwayScore", "HomeScore", "HomeSpread", "Spread", "Week", "Season"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # home-perspective spread: prefer explicit HomeSpread, fall back to Spread
    df["HSpread"] = df["HomeSpread"].where(df["HomeSpread"].notna(), df["Spread"])
    df = df.dropna(subset=["AwayScore", "HomeScore", "HSpread", "Week", "Season"])
    df["margin"] = df["HomeScore"] - df["AwayScore"]          # home perspective
    # ATS result, home perspective: cover if margin + HomeSpread > 0; push if == 0
    df["ats_home"] = np.sign(df["margin"] + df["HSpread"]).astype(int)   # +1 home cover, -1 away, 0 push
    return df.sort_values(["Season", "Week"]).reset_index(drop=True)


def _srs(prior: pd.DataFrame):
    """Least-squares SRS from prior games: margin = r_home - r_away + HFA. Gauge-fixed by a
    soft sum-to-zero constraint. Returns {team: rating}, HFA, set of rated teams."""
    teams = pd.Index(sorted(set(prior["Home"]) | set(prior["Away"])))
    idx = {t: i for i, t in enumerate(teams)}
    nt = len(teams)
    rows = len(prior)
    A = np.zeros((rows + 1, nt + 1))     # +1 col = HFA, +1 row = sum-to-zero constraint
    b = np.zeros(rows + 1)
    for r, (_, g) in enumerate(prior.iterrows()):
        A[r, idx[g["Home"]]] = 1.0
        A[r, idx[g["Away"]]] = -1.0
        A[r, nt] = 1.0                   # home-field advantage
        b[r] = g["margin"]
    A[rows, :nt] = RIDGE                 # soft sum(ratings)=0
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    ratings = {t: float(sol[idx[t]]) for t in teams}
    hfa = float(sol[nt])
    # count prior games per team for the min-sample gate
    gc = pd.concat([prior["Home"], prior["Away"]]).value_counts()
    rated = {t for t in teams if gc.get(t, 0) >= MIN_PRIOR_GAMES}
    return ratings, hfa, rated


def main() -> int:
    df = _load()
    picks = []   # (edge_abs, model_side, ats_result)  -- one per predicted game
    for season, sdf in df.groupby("Season"):
        for week in sorted(sdf["Week"].unique()):
            if week < MIN_WEEK:
                continue
            prior = sdf[sdf["Week"] < week]
            if len(prior) < 20:
                continue
            ratings, hfa, rated = _srs(prior)
            wk = sdf[sdf["Week"] == week]
            for _, g in wk.iterrows():
                h, a = g["Home"], g["Away"]
                if h not in rated or a not in rated:
                    continue
                pred_margin = ratings[h] - ratings[a] + hfa
                model_edge = pred_margin + g["HSpread"]      # >0 => model likes HOME ats
                if g["ats_home"] == 0:                        # push -- no action
                    continue
                side = 1 if model_edge > 0 else -1
                hit = 1 if side == g["ats_home"] else 0
                picks.append((season, abs(model_edge), side, hit))

    p = pd.DataFrame(picks, columns=["season", "edge", "side", "hit"])
    n = len(p)
    print("CFB Mechanism Audit #1 -- Opponent-Adjusted Team Strength (point-in-time SRS)\n")
    print(f"independent unit = GAME | predicted games (n) = {n} | seasons 2021-2026, week >= {MIN_WEEK}\n")
    if n == 0:
        print("no gradeable predictions -- data-gated"); return 0

    def line(label, sub):
        k = int(sub["hit"].sum()); m = len(sub)
        if m == 0:
            print(f"  {label:<22} n={m:>5}  --"); return
        lo, hi = _wilson(k, m)
        print(f"  {label:<22} n={m:>5}  cover={k/m*100:5.1f}%  95%CI[{lo}, {hi}]")

    print("ATS cover rate of the model-selected side (baseline 50%, break-even ~52.4%):")
    line("ALL picks", p)
    print("\n  by model/market disagreement (points):")
    for lo, hi, lbl in [(0, 3, "0-3"), (3, 7, "3-7"), (7, 14, "7-14"), (14, 999, "14+")]:
        line(lbl, p[(p["edge"] >= lo) & (p["edge"] < hi)])
    print("\n  by season (out-of-sample across years):")
    for s in sorted(p["season"].unique()):
        line(str(int(s)), p[p["season"] == s])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
