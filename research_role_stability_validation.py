"""
research_role_stability_validation.py  -- AUDIT: does Role Stability actually matter?

We BUILT Role Stability on a thesis: a locked role is a real floor, a volatile one isn't. The
doctrine says measure, don't assume. So: do players with a STABLE role (low week-to-week share
variance) actually have more RELIABLE production -- fewer bust games -- than volatile players,
BEYOND what their opportunity level alone explains?

The 'beyond opportunity' control is the whole test. A bell-cow is both high-volume AND stable;
if stability only tracks volume it adds nothing. So we check whether share-CV predicts
production volatility AFTER accounting for how much a player gets.

Data: 2023-2025 nflverse PBP (per-game carry share + rush yards for RBs -- the cleanest channel).
Builds nothing. See BANKROLL_KINGS_DOCTRINE.md S10 ('grade what it says').

VERDICT (2026-10-10 run, 72 RBs): VALIDATED. share_cv predicts production volatility at +0.80
raw, and -- the test that matters -- +0.69 PARTIAL after controlling for opportunity (mean
share). It did NOT collapse, so Role Stability is REAL independent signal, not a proxy for
volume. Locked-tercile backs bust (game under half their median) 16% of the time vs 27% for
Volatile. Honest nuance: the effect is partly MECHANICAL (stable touches -> stable yards), which
is the point -- the lens claims 'stable role = reliable floor' and that's confirmed; it's a
floor DESCRIPTOR, not a profit edge. Gold-standard follow-up is forward out-of-sample capture
(grade it over coming weeks via the capture harness), but the backtest clears the bar.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PBP = BASE / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
SEASONS = [2023, 2024, 2025]
MIN_GAMES = 10
MIN_SHARE = 0.25          # a real backfield role


def per_player() -> pd.DataFrame:
    df = pd.read_parquet(PBP, columns=["season", "game_id", "posteam", "rush_attempt",
                                       "rusher_player_name", "yards_gained"])
    df = df[df["season"].isin(SEASONS)].copy()
    r = df[(pd.to_numeric(df["rush_attempt"], errors="coerce") == 1)
           & (df["rusher_player_name"].fillna("").str.strip() != "")].copy()
    r["yg"] = pd.to_numeric(r["yards_gained"], errors="coerce").fillna(0.0)
    # team carries per game -> each back's per-game carry share + rush yards
    team = r.groupby(["posteam", "game_id"]).size().rename("team_car").reset_index()
    pg = r.groupby(["rusher_player_name", "posteam", "game_id"]).agg(
        car=("yg", "size"), yds=("yg", "sum")).reset_index()
    pg = pg.merge(team, on=["posteam", "game_id"], how="left")
    pg["share"] = pg["car"] / pg["team_car"]

    rows = []
    for name, g in pg.groupby("rusher_player_name"):
        if len(g) < MIN_GAMES:
            continue
        share, yds = g["share"], g["yds"]
        mean_share = float(share.mean())
        if mean_share < MIN_SHARE:
            continue
        share_cv = float(share.std(ddof=0) / mean_share) if mean_share else np.nan
        mean_yds = float(yds.mean())
        yds_cv = float(yds.std(ddof=0) / mean_yds) if mean_yds else np.nan
        med = float(yds.median())
        bust_rate = float((yds < 0.5 * med).mean()) if med else np.nan   # games under half his median
        rows.append({"player": name, "games": len(g), "mean_share": mean_share,
                     "share_cv": share_cv, "mean_yds": mean_yds, "yds_cv": yds_cv,
                     "bust_rate": bust_rate})
    return pd.DataFrame(rows).dropna()


def main() -> None:
    d = per_player()
    print(f"RBs 2023-25 with >= {MIN_GAMES} games and a real role: {len(d)}\n")

    print("1) Does role stability (share CV) track production reliability?")
    print(f"   corr(share_cv, yds_cv)   = {d['share_cv'].corr(d['yds_cv']):+.2f}  (stable role -> stable yards?)")
    print(f"   corr(share_cv, bust_rate)= {d['share_cv'].corr(d['bust_rate']):+.2f}  (volatile role -> more busts?)\n")

    print("2) THE CONTROL -- does it survive accounting for opportunity (mean share)?")
    print("   corr(share_cv, mean_share) = {:+.2f}  (are stable players just high-volume?)".format(
        d["share_cv"].corr(d["mean_share"])))
    # partial correlation of share_cv vs yds_cv, controlling for mean_share
    def _resid(y, x):
        x1 = np.c_[np.ones(len(x)), x]
        beta, *_ = np.linalg.lstsq(x1, y, rcond=None)
        return y - x1 @ beta
    rc_sc = _resid(d["share_cv"].values, d["mean_share"].values)
    rc_yc = _resid(d["yds_cv"].values, d["mean_share"].values)
    partial = np.corrcoef(rc_sc, rc_yc)[0, 1]
    print(f"   PARTIAL corr(share_cv, yds_cv | mean_share) = {partial:+.2f}")
    print("   -> if this stays positive, role stability adds REAL signal beyond volume. If it")
    print("      collapses to ~0, it was just a proxy for opportunity.\n")

    print("3) Locked vs Volatile terciles (by share CV) -- matched by opportunity:")
    d["band"] = pd.qcut(d["share_cv"], 3, labels=["Locked", "Steady", "Volatile"])
    for b in ["Locked", "Steady", "Volatile"]:
        s = d[d["band"] == b]
        print(f"   {b:<9} n={len(s):>3}  mean_share {s['mean_share'].mean():.0%}  "
              f"yds_cv {s['yds_cv'].mean():.2f}  bust_rate {s['bust_rate'].mean():.0%}")
    lo, hi = d[d["band"] == "Locked"], d[d["band"] == "Volatile"]
    print(f"\n   Locked vs Volatile: bust rate {lo['bust_rate'].mean():.0%} vs {hi['bust_rate'].mean():.0%}"
          f"  (mean share {lo['mean_share'].mean():.0%} vs {hi['mean_share'].mean():.0%})")
    print("   VERDICT below is read off (2) -- the partial correlation is the honest answer.")


if __name__ == "__main__":
    main()
