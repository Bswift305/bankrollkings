"""
build_nfl_usage_by_state.py  -- Averaging Audit shortlist A1

De-collapse the biggest hidden dimension on the site: GAME-STATE.

The usage board's target_share / rush_share are season per-game means that bake in
game-script (trailing teams throw, leading teams run) -- so "opportunity" is partly a
game-state measurement in disguise. This splits each player's usage by game-state
(leading / tied / trailing), garbage-time removed via win probability, built from the
2019-2025 nflverse play-by-play so the TENDENCY is stable (not a 3-game 2026 sample).

Output: data/tracking/NFL_Usage_By_State.csv  -- one row per (player, team, state).

It also prints:
  (a) the biggest role-FLIPS (players whose share changes most between leading and
      trailing) -- the payoff, made visible; and
  (b) the lens-independence re-test: how much state-conditioned usage diverges from raw
      usage across the league. If it diverges, we genuinely separated a lens.

Doctrine: this de-averages, it does not predict. See docs/averaging_audit.md (A1).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PBP_PATH = BASE / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
OUT_PATH = BASE / "data" / "tracking" / "NFL_Usage_By_State.csv"

# --- knobs (kept explicit; the audit's bias-variance guardrail lives here) ---
RECENT_SEASONS = [2023, 2024, 2025]   # role-relevant window; stable sample, not stale
GARBAGE_WP_LOW = 0.05                 # drop blowout garbage-time (starters sit, D softens)
GARBAGE_WP_HIGH = 0.95
MIN_STATE_PLAYS = 20                  # don't report a player-state share under this sample

STATES = ["leading", "tied", "trailing"]


def _state(score_diff: pd.Series) -> pd.Series:
    """Possession team's game-state from its score differential (nflfastR convention)."""
    s = pd.to_numeric(score_diff, errors="coerce")
    return np.where(s > 0, "leading", np.where(s < 0, "trailing", "tied"))


def load_pbp() -> pd.DataFrame:
    if not PBP_PATH.exists():
        sys.exit(f"PBP not found: {PBP_PATH}")
    df = pd.read_parquet(PBP_PATH)
    df = df[df["season"].isin(RECENT_SEASONS)].copy()
    wp = pd.to_numeric(df["wp"], errors="coerce")
    # keep competitive snaps only; garbage-time is the extreme tail of win prob
    df = df[wp.between(GARBAGE_WP_LOW, GARBAGE_WP_HIGH)].copy()
    df["state"] = _state(df["score_differential"])
    return df


def _share(part: pd.DataFrame, team: pd.DataFrame, key: str, val: str, out: str) -> pd.DataFrame:
    """player count/sum over team count/sum within (posteam, state)."""
    p = part.groupby([key, "posteam", "state"], dropna=True)[val].sum().reset_index()
    p = p.rename(columns={key: "player", val: f"{out}_n"})
    t = team.groupby(["posteam", "state"])[val].sum().reset_index().rename(columns={val: f"{out}_team"})
    m = p.merge(t, on=["posteam", "state"], how="left")
    m[f"{out}_share"] = (m[f"{out}_n"] / m[f"{out}_team"]).round(4)
    return m


def build() -> pd.DataFrame:
    df = load_pbp()

    # targets: pass attempts with an identified receiver
    tgt = df[(pd.to_numeric(df["pass_attempt"], errors="coerce") == 1)
             & (df["receiver_player_name"].fillna("").str.strip() != "")].copy()
    tgt["one"] = 1
    tgt["ay"] = pd.to_numeric(tgt["air_yards"], errors="coerce").fillna(0.0)
    tgt_share = _share(tgt, tgt, "receiver_player_name", "one", "tgt")
    air_share = _share(tgt, tgt, "receiver_player_name", "ay", "air")

    # carries: rush attempts with an identified rusher
    car = df[(pd.to_numeric(df["rush_attempt"], errors="coerce") == 1)
             & (df["rusher_player_name"].fillna("").str.strip() != "")].copy()
    car["one"] = 1
    rush_share = _share(car, car, "rusher_player_name", "one", "rush")

    # merge the three onto (player, team, state)
    out = tgt_share.merge(air_share, on=["player", "posteam", "state"], how="outer")
    out = out.merge(rush_share, on=["player", "posteam", "state"], how="outer")
    out = out.rename(columns={"posteam": "team"})

    # a single "plays involved" sample so thin cells are visible
    out["plays"] = out[["tgt_n", "rush_n"]].fillna(0).sum(axis=1).astype(int)
    for c in ["tgt_share", "air_share", "rush_share", "tgt_n", "rush_n", "air_n"]:
        if c in out:
            out[c] = out[c].fillna(0)
    out = out[out["plays"] >= MIN_STATE_PLAYS].copy()
    out = out.sort_values(["player", "team", "state"]).reset_index(drop=True)
    return out


def _pivot(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    p = df.pivot_table(index=["player", "team"], columns="state", values=metric, aggfunc="first")
    for s in STATES:
        if s not in p:
            p[s] = np.nan
    return p


def report(df: pd.DataFrame) -> None:
    print(f"\nRows: {len(df)}  players: {df['player'].nunique()}  "
          f"(seasons {RECENT_SEASONS}, garbage-time wp outside "
          f"[{GARBAGE_WP_LOW},{GARBAGE_WP_HIGH}] dropped)\n")

    # (a) biggest role flips: target share trailing vs leading
    tp = _pivot(df, "tgt_share")
    tp = tp[(tp["leading"].notna()) & (tp["trailing"].notna())]
    tp["flip"] = (tp["trailing"] - tp["leading"]).round(3)
    big_up = tp.sort_values("flip", ascending=False).head(8)
    big_dn = tp.sort_values("flip").head(8)
    print("TARGET-SHARE role flips (trailing minus leading):")
    print("  Pass-catchers who LIGHT UP when trailing:")
    for (pl, tm), r in big_up.iterrows():
        print(f"    {pl:<20} {tm:<4} lead {r['leading']:.0%}  tie {r['tied'] if pd.notna(r['tied']) else float('nan'):.0%}  trail {r['trailing']:.0%}   (+{r['flip']:.0%})")
    print("  Pass-catchers who FADE when trailing:")
    for (pl, tm), r in big_dn.iterrows():
        print(f"    {pl:<20} {tm:<4} lead {r['leading']:.0%}  trail {r['trailing']:.0%}   ({r['flip']:.0%})")

    # rush-share flips: carries leading vs trailing (game-script runners)
    rp = _pivot(df, "rush_share")
    rp = rp[(rp["leading"].notna()) & (rp["trailing"].notna())]
    rp["flip"] = (rp["leading"] - rp["trailing"]).round(3)
    print("\nRUSH-SHARE role flips (leading minus trailing) -- the 'bell-cow when ahead' backs:")
    for (pl, tm), r in rp.sort_values("flip", ascending=False).head(8).iterrows():
        print(f"    {pl:<20} {tm:<4} lead {r['leading']:.0%}  trail {r['trailing']:.0%}   (+{r['flip']:.0%})")

    # (b) lens-independence re-test
    print("\n--- LENS-INDEPENDENCE RE-TEST (did we actually separate a lens?) ---")
    for metric, label in [("tgt_share", "target share"), ("rush_share", "rush share")]:
        p = _pivot(df, metric)
        p = p[(p["leading"].notna()) & (p["trailing"].notna())]
        corr = p["leading"].corr(p["trailing"])
        diff = (p["trailing"] - p["leading"]).abs()
        moved = (diff >= 0.05).mean()
        print(f"  {label:<13}: corr(lead,trail)={corr:.2f}  |  "
              f"{moved:.0%} of players move >=5 share pts between states  "
              f"(median move {diff.median():.1%})")
    print("  Low corr / high move = game-state is a real, separable lens (not one already")
    print("  captured by raw usage). High corr / low move = it was the same signal.\n")


def main() -> None:
    df = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}  ({len(df)} player-state rows)")
    report(df)


if __name__ == "__main__":
    main()
