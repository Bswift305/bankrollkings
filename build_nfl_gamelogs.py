"""Build data/gamelogs/NFL_GameLogs.csv for the fantasy engine.

The fantasy projection path (get_fantasy_projection_rows -> _build_fantasy_
projection_rows) reads a per-game gamelog with a Player/Date/Team/Opp/Position
row per game plus the football stat columns. Nothing produced that file; the raw
per-game player stats live in data/historical/NFL_PlayerStats_<year>.csv (built
from play-by-play). This script maps those into the gamelog schema.

Preseason behavior: it includes the last two completed seasons (plus the current
season if that file exists). The fantasy sim recency-weights games, so before the
new season starts it baselines on last year's logs and converges as the season
plays out — exactly the approach in PROJECT_MAP §8.

Run: python build_nfl_gamelogs.py
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "data")
HIST = os.path.join(DATA, "historical")
OUT = os.path.join(DATA, "gamelogs", "NFL_GameLogs.csv")

SKILL = {"QB", "RB", "WR", "TE", "FB"}
SEASONS_KEPT = 3          # most recent completed/current seasons to include


def _infer_position(row):
    """Fallback when a player's position group is missing (e.g. the 2025 extract):
    read it off his stat profile."""
    att = float(row.get("attempts", 0) or 0)
    car = float(row.get("carries", 0) or 0)
    tgt = float(row.get("targets", 0) or 0)
    if att >= 3:
        return "QB"
    if car >= tgt and car > 0:
        return "RB"
    if tgt > 0:
        return "WR"
    return ""


def _week_to_date(season, week):
    """A synthetic, monotonic game date so the fantasy engine can sort/recency-
    weight. NFL week 1 ~ early September; postseason weeks roll into next year."""
    try:
        base = pd.Timestamp(int(season), 9, 4)
        return (base + pd.Timedelta(days=(int(week) - 1) * 7)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def build():
    files = sorted(glob.glob(os.path.join(HIST, "NFL_PlayerStats_*.csv")))
    if not files:
        raise SystemExit("No NFL_PlayerStats_*.csv found in data/historical/")

    # Position map from EVERY year that carries positions (older files do; the
    # 2025 extract does not) — player -> most-common position group.
    pos_map = {}
    for f in files:
        df = pd.read_csv(f, usecols=lambda c: c in ("player_display_name", "position_group"))
        if "position_group" not in df.columns:
            continue
        df = df.dropna(subset=["position_group"])
        for name, grp in df.groupby("player_display_name"):
            top = grp["position_group"].mode()
            if len(top):
                pos_map.setdefault(str(name).strip(), str(top.iloc[0]).strip())

    keep_seasons = sorted({int(os.path.basename(f).split("_")[-1].split(".")[0]) for f in files})[-SEASONS_KEPT:]

    frames = []
    for f in files:
        season = int(os.path.basename(f).split("_")[-1].split(".")[0])
        if season not in keep_seasons:
            continue
        frames.append(pd.read_csv(f))
    raw = pd.concat(frames, ignore_index=True)

    # Name normalization: some extracts use full names ("Patrick Mahomes"), the
    # 2025 one uses abbreviated ("P.Mahomes"), which both splits a player's recent
    # season from his history AND collides distinct players. Build (abbrev, team) ->
    # full-name from the clean full-name rows, then map abbreviated rows back.
    raw = raw.copy()
    raw["_name"] = raw["player_display_name"].astype(str).str.strip()
    raw["_team"] = raw.get("team", "").astype(str).str.strip()

    def _abbrev(full):
        parts = full.split()
        return (parts[0][0] + "." + parts[-1]) if len(parts) >= 2 else full

    canon, ambig = {}, set()
    full_rows = raw[raw["_name"].str.contains(" ", regex=False)]
    for full, team in zip(full_rows["_name"], full_rows["_team"]):
        key = (_abbrev(full), team)
        if key in canon and canon[key] != full:
            ambig.add(key)
        canon[key] = full

    def _resolve(name, team):
        if " " in name:                        # already a full name
            return name
        key = (name, team)                     # abbreviated -> full via team
        if key in canon and key not in ambig:
            return canon[key]
        return None                            # unmappable/ambiguous -> drop

    raw["_resolved"] = [_resolve(n, t) for n, t in zip(raw["_name"], raw["_team"])]
    raw = raw[raw["_resolved"].notna()].reset_index(drop=True)

    out = pd.DataFrame()
    out["Player"] = raw["_resolved"].astype(str).str.strip()
    out["Season"] = pd.to_numeric(raw["season"], errors="coerce")
    out["Week"] = pd.to_numeric(raw["week"], errors="coerce")
    out["Team"] = raw.get("team", "").astype(str).str.strip()
    out["Opp"] = raw.get("opponent_team", "").astype(str).str.strip()

    # Position: file's own group, else the cross-year map, else stat inference.
    file_pos = raw.get("position_group")
    out["Position"] = [
        (str(fp).strip() if pd.notna(fp) and str(fp).strip()
         else pos_map.get(str(nm).strip()) or _infer_position(row))
        for fp, nm, (_, row) in zip(file_pos, out["Player"], raw.iterrows())
    ]

    # Fantasy stat columns (names the scoring weights key off).
    num = lambda c: pd.to_numeric(raw.get(c, 0), errors="coerce").fillna(0)
    out["PassYd"] = num("passing_yards")
    out["PassTD"] = num("passing_tds")
    out["PassInt"] = num("passing_interceptions")
    out["RushYd"] = num("rushing_yards")
    out["RushTD"] = num("rushing_tds")
    out["Rec"] = num("receptions")
    out["RecYd"] = num("receiving_yards")
    out["RecTD"] = num("receiving_tds")
    out["Targets"] = num("targets")
    out["Date"] = [_week_to_date(s, w) for s, w in zip(out["Season"], out["Week"])]

    # Fantasy-relevant players only: skill positions, and games with real usage.
    out = out[out["Position"].isin(SKILL)]
    usage = out[["PassYd", "RushYd", "RecYd", "Rec", "Targets"]].abs().sum(axis=1)
    out = out[(usage > 0) & out["Date"].astype(bool)]
    out = out.sort_values(["Date", "Player"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False)
    seasons = ", ".join(str(int(s)) for s in sorted(out["Season"].dropna().unique()))
    print(f"Wrote {OUT}: {len(out):,} game rows | seasons {seasons} | "
          f"{out['Player'].nunique():,} players | positions {out['Position'].value_counts().to_dict()}")


if __name__ == "__main__":
    build()
