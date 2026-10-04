"""
build_nfl_defense_by_state.py  -- Averaging Audit shortlist A2

De-collapse game-state from DEFENSIVE ranks.

Claim under test: a defense's "pass yards allowed per game" is inflated when the defense
is LEADING, because a trailing opponent throws to catch up. So "soft pass D" ranks may be
a VOLUME artifact of game-script, not a statement about how good the defense actually is.

This measures, from 2019-2025 nflverse PBP (garbage-time removed via win prob):
  1. the mechanism  -- pass rate / volume faced by the defense's own game-state;
  2. efficiency vs volume -- pass yards allowed PER DROPBACK by state (is the D worse, or
     just facing more throws?);
  3. the rank reshuffle -- rank 2025 defenses by the current-style per-GAME number vs a
     neutral-script PER-PLAY number, and show who moves.

Doctrine: de-averages, does not predict. See docs/averaging_audit.md (A2).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PBP_PATH = BASE / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
OUT_PATH = BASE / "data" / "tracking" / "NFL_Defense_By_State.csv"

GARBAGE_WP_LOW, GARBAGE_WP_HIGH = 0.05, 0.95
NEUTRAL_MARGIN = 8          # |score diff| <= one score == competitive/neutral script
RECENT_SEASON = 2025        # the reshuffle demo season


def load() -> pd.DataFrame:
    df = pd.read_parquet(PBP_PATH, columns=[
        "season", "week", "game_id", "posteam", "defteam", "score_differential", "wp",
        "pass_attempt", "rush_attempt", "yards_gained"])
    df = df[(df["posteam"].fillna("") != "") & (df["defteam"].fillna("") != "")].copy()
    wp = pd.to_numeric(df["wp"], errors="coerce")
    df = df[wp.between(GARBAGE_WP_LOW, GARBAGE_WP_HIGH)].copy()
    sd = pd.to_numeric(df["score_differential"], errors="coerce")  # posteam (offense) perspective
    # defense state = opposite of offense: offense trailing -> defense leading
    df["def_state"] = np.where(sd < 0, "def_leading", np.where(sd > 0, "def_trailing", "tied"))
    df["neutral"] = sd.abs() <= NEUTRAL_MARGIN
    df["is_pass"] = pd.to_numeric(df["pass_attempt"], errors="coerce").fillna(0) == 1
    df["is_rush"] = pd.to_numeric(df["rush_attempt"], errors="coerce").fillna(0) == 1
    df["yg"] = pd.to_numeric(df["yards_gained"], errors="coerce").fillna(0.0)
    return df


def mechanism(df: pd.DataFrame) -> None:
    print("1) MECHANISM -- what the offense does by the DEFENSE's game-state (2019-25 pooled)")
    print(f"   {'def state':<14}{'pass rate':>10}{'pass yds/att allowed':>22}")
    for st in ["def_leading", "tied", "def_trailing"]:
        sub = df[df["def_state"] == st]
        plays = sub["is_pass"].sum() + sub["is_rush"].sum()
        pass_rate = sub["is_pass"].sum() / plays if plays else float("nan")
        pa = sub[sub["is_pass"]]
        ypa = pa["yg"].sum() / len(pa) if len(pa) else float("nan")
        print(f"   {st:<14}{pass_rate:>9.1%}{ypa:>21.2f}")
    print("   -> if pass rate jumps when the defense LEADS, the per-game pass-yds-allowed")
    print("      number is inflated by volume the defense's own lead created.\n")


def reshuffle(df: pd.DataFrame) -> pd.DataFrame:
    s = df[df["season"] == RECENT_SEASON].copy()
    games = s.groupby("defteam")["game_id"].nunique().rename("games")
    pa = s[s["is_pass"]]
    # current-style: pass yards allowed per GAME (all situations)
    all_ypg = pa.groupby("defteam")["yg"].sum().div(games).rename("all_pass_ypg")
    # de-stated: pass yards allowed per DROPBACK in neutral script
    pan = pa[pa["neutral"]]
    neut_ypp = (pan.groupby("defteam")["yg"].sum() / pan.groupby("defteam").size()).rename("neutral_pass_ypp")
    out = pd.concat([games, all_ypg, neut_ypp], axis=1).dropna()
    out["all_ypg_rank"] = out["all_pass_ypg"].rank(method="min").astype(int)          # 1 = fewest allowed (best)
    out["neutral_ypp_rank"] = out["neutral_pass_ypp"].rank(method="min").astype(int)
    out["rank_delta"] = out["all_ypg_rank"] - out["neutral_ypp_rank"]  # +ve: looks softer than it is
    return out.sort_values("rank_delta", ascending=False)


def main() -> None:
    df = load()
    mechanism(df)
    rs = reshuffle(df)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rs.round(3).to_csv(OUT_PATH)
    print(f"Wrote {OUT_PATH}\n")

    print(f"2+3) RANK RESHUFFLE, {RECENT_SEASON} pass defense:")
    print("   current-style per-GAME rank  vs  neutral-script per-DROPBACK rank")
    print("   (rank 1 = best / fewest allowed; +delta = looks SOFTER than it really is)\n")
    print(f"   {'team':<5}{'allYPG':>8}{'ypgRk':>7}{'neutYPP':>9}{'neutRk':>8}{'delta':>7}")
    show = pd.concat([rs.head(6), rs.tail(6)])
    for tm, r in show.iterrows():
        print(f"   {tm:<5}{r['all_pass_ypg']:>8.1f}{int(r['all_ypg_rank']):>7}"
              f"{r['neutral_pass_ypp']:>9.2f}{int(r['neutral_ypp_rank']):>8}{int(r['rank_delta']):>+7}")
    moved = (rs["rank_delta"].abs() >= 6).mean()
    big = (rs["rank_delta"].abs() >= 10).sum()
    print(f"\n   {moved:.0%} of defenses move >=6 rank spots; {big} move >=10, when you strip")
    print(f"   game-state. Mean |rank move| = {rs['rank_delta'].abs().mean():.1f} of 32.\n")


if __name__ == "__main__":
    main()
