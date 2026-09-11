"""Build the NFL usage-distribution profile used by the prop scorer.

Reads per-game player stats (from build_nfl_player_stats_from_pbp.py) and writes
one row per skill player describing their team's backfield / receiver-room scheme
and their role + in-season trend within it.

  input :  data/historical/NFL_PlayerStats_2025.csv
  output:  data/tracking/NFL_Usage_Distribution.csv

Season totals drive classification; the last `RECENT_WEEKS` weeks drive the
development trend. Missing input is not an error — the scorer treats an absent
profile as "no usage signal" and everything else keeps working.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.nfl_usage_distribution import build_team_usage

BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "historical" / "NFL_PlayerStats_2025.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_Usage_Distribution.csv"
RECENT_WEEKS = 4


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def build_rows(df: pd.DataFrame) -> list[dict]:
    name_col = "player_name" if "player_name" in df.columns else "player_display_name"
    df = df.copy()
    for col in ("carries", "targets", "receptions", "week"):
        if col not in df.columns:
            df[col] = 0
        df[col] = _num(df[col])

    # recent window = last RECENT_WEEKS weeks that appear in the data
    max_week = df["week"].max() if not df.empty else 0
    recent_cutoff = max_week - (RECENT_WEEKS - 1)

    rows: list[dict] = []
    grouped = df.groupby([name_col, "team"], dropna=False)
    for (player, team), g in grouped:
        if not str(player).strip() or not str(team).strip():
            continue
        recent = g[g["week"] >= recent_cutoff]
        rows.append({
            "player": str(player).strip(),
            "team": str(team).strip(),
            "position": str(g.get("position", pd.Series([""])).iloc[0] or "").strip(),
            "carries": float(g["carries"].sum()),
            "targets": float(g["targets"].sum()),
            "receptions": float(g["receptions"].sum()),
            "recent_carries": float(recent["carries"].sum()),
            "recent_targets": float(recent["targets"].sum()),
        })
    return rows


def to_profile_frame(rows: list[dict]) -> pd.DataFrame:
    teams = build_team_usage(rows)
    out = []
    for team_usage in teams.values():
        for p in team_usage.players:
            scheme = team_usage.rb_scheme if p.position == "RB" else team_usage.wr_scheme
            out.append({
                "Player": p.player,
                "Team": p.team,
                "Position": p.position,
                "Rank": p.rank,
                "Role": p.role,
                "Scheme": scheme,
                "CarryShare": p.carry_share,
                "TargetShare": p.target_share,
                "Trend": p.trend,
            })
    return pd.DataFrame(out)


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"No player-stats input at {INPUT_PATH} — skipping usage distribution (scorer degrades to no signal).")
        return 0
    df = pd.read_csv(INPUT_PATH, low_memory=False)
    if df.empty:
        print(f"Player-stats input is empty: {INPUT_PATH} — nothing to build.")
        return 0

    profile = to_profile_frame(build_rows(df))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    profile.to_csv(OUTPUT_PATH, index=False)

    print(f"Usage distribution rows: {len(profile):,}")
    if not profile.empty:
        schemes = profile.groupby(["Position", "Scheme"]).size().reset_index(name="players")
        for _, r in schemes.iterrows():
            print(f"  {r['Position']:<3} {r['Scheme']:<14} {r['players']:>4} players")
    print(f"Saved: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
