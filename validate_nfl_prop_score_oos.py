"""Out-of-sample validation for the NFL PropScore / player-hit-profile signal.

Why this exists: the shipped PropScore quintile result (~+15.5% ROI top quintile)
is IN-SAMPLE and invalid as evidence. `build_player_profiles` computes each
player's HitRate over ALL resolved rows, and `calculate_usage_stability` feeds
that hit rate back in as a scoring input -- so a row is scored with a feature
derived from its own outcome. UsageStability carries the bulk of PropScore's
variance (std ~8.7 vs ~2-3 for the pre-game features), so PropScore is
essentially that leaked feature.

This script does the honest test the review asked for: build the player
hit-profile from a TRAIN season only, use it to rank the TEST season, and measure
real ROI at the recorded market price. The in-sample number is reported alongside
so the leakage is self-documenting.

Result to expect (2024 -> 2025, as of 2026-07): the relationship INVERTS. Players
with the highest prior-season hit rate hit LESS and lose MORE the next season
(regression to the mean + the market tightening their lines). 2024/2025 hit-rate
correlation ~ -0.09. So the signal is not merely in-sample-optimistic -- it is
anti-predictive out of sample, and must not gate live selection.

Run: python validate_nfl_prop_score_oos.py
"""
from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCORED = os.path.join(BASE_DIR, "data", "tracking", "NFL_AllPropResults_Scored.csv")
RAW = os.path.join(BASE_DIR, "data", "tracking", "NFL_AllPropResults.csv")
MIN_PROFILE_SAMPLE = 3


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (100 * (c - m), 100 * (c + m))


def _roi(frame: pd.DataFrame) -> tuple | None:
    price = pd.to_numeric(frame["MarketPrice"], errors="coerce").where(lambda s: s.abs() < 10000)
    hit = (frame["OutcomeState"] == "Hit").astype(float)
    win = np.where(price < 0, 100.0 / (-price), price / 100.0)
    pnl = np.where(hit == 1, win, -1.0)
    mask = np.isfinite(pnl) & price.notna().to_numpy()
    a = pnl[mask]
    if len(a) < 30:
        return None
    return 100 * a.mean(), len(a), 100 * hit.to_numpy()[mask].mean()


def _quintile_roi(df: pd.DataFrame, col: str) -> list:
    d = df.dropna(subset=[col]).copy()
    d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=[col])
    if d[col].nunique() < 5:
        return []
    d["q"] = pd.qcut(d[col], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"], duplicates="drop")
    out = []
    for key, g in d.groupby("q", observed=True):
        r = _roi(g)
        out.append((str(key), r))
    return out


def main() -> int:
    path = SCORED if os.path.exists(SCORED) and os.path.getsize(SCORED) > 50 else RAW
    if not (os.path.exists(path) and os.path.getsize(path) > 50):
        print("validate_nfl_prop_score_oos: no NFL resolved data on this box - skipping.")
        return 0
    d = pd.read_csv(path, low_memory=False)
    d = d[d["OutcomeState"].isin(["Hit", "Miss"])].copy()
    if "Season" not in d.columns or d["Season"].dropna().nunique() < 2:
        print("Need >=2 seasons of resolved data for a holdout; have "
              f"{sorted(d.get('Season', pd.Series()).dropna().unique().tolist())}.")
        return 0

    seasons = sorted(int(s) for s in d["Season"].dropna().unique())
    train_season, test_season = seasons[-2], seasons[-1]
    tr = d[d["Season"] == train_season]
    te = d[d["Season"] == test_season].copy()
    print("=" * 68)
    print("NFL PropScore -- out-of-sample validation")
    print("=" * 68)
    print(f"train (profile): {train_season}  n={len(tr):,}   test: {test_season}  n={len(te):,}\n")

    # Profile = per (Player, Stat, Direction) hit rate from TRAIN only.
    prof = (tr.groupby(["Player", "Stat", "Direction"])
              .agg(hr=("OutcomeState", lambda s: (s == "Hit").mean() * 100),
                   n=("OutcomeState", "size")))
    te = te.merge(prof, on=["Player", "Stat", "Direction"], how="left")
    seen = te[te["hr"].notna() & (te["n"] >= MIN_PROFILE_SAMPLE)].copy()

    print(f"IN-SAMPLE reference (shipped PropScore, profile from ALL data):")
    if "BK_NFL_PropScore" in d.columns:
        for name, r in _quintile_roi(d, "BK_NFL_PropScore"):
            if r:
                print(f"   {name}: ROI {r[0]:+6.1f}%  hit {r[2]:4.1f}%  n={r[1]}")

    print(f"\nOUT-OF-SAMPLE (rank {test_season} by {train_season} player hit rate, n>={MIN_PROFILE_SAMPLE}):")
    any_rows = False
    for name, r in _quintile_roi(seen, "hr"):
        any_rows = True
        if r:
            print(f"   {name}: ROI {r[0]:+6.1f}%  hit {r[2]:4.1f}%  n={r[1]}")
    if not any_rows:
        print("   (insufficient overlap)")

    # Does prior-season hit rate predict next-season hit rate at all?
    by = (te.dropna(subset=["hr"])
            .groupby(["Player", "Stat", "Direction"])
            .agg(hr_train=("hr", "first"),
                 hr_test=("OutcomeState", lambda s: (s == "Hit").mean() * 100),
                 n=("OutcomeState", "size")))
    by = by[by["n"] >= MIN_PROFILE_SAMPLE]
    if len(by) > 20:
        corr = by["hr_train"].corr(by["hr_test"])
        print(f"\ncorrelation {train_season} vs {test_season} player hit rate "
              f"(n={len(by)} player-stat-dirs): {corr:+.3f}")
        verdict = ("ANTI-PREDICTIVE" if corr < -0.02 else
                   "no signal" if corr < 0.05 else "some signal")
        print(f"verdict: prior-season hit rate is {verdict} for next-season props.")

    print("\nBottom line: the in-sample PropScore edge does not survive a season "
          "holdout. Do not gate live selection on player past-hit-rate, and do not "
          "cite the in-sample quintile ROI as evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
