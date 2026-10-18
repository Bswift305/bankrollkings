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

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "data")
HIST = os.path.join(DATA, "historical")
OUT = os.path.join(DATA, "gamelogs", "NFL_GameLogs.csv")

SKILL = {"QB", "RB", "WR", "TE", "FB"}
# Defensive position groups. Books now price tackles, sacks and defensive
# interceptions, so those players need per-game rows or every defensive prop
# sits Pending forever with nothing to grade it against.
DEFENSE = {"DB", "DL", "LB"}
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
    # No offensive usage at all but defensive production: a defender. "LB" is a
    # deliberate catch-all here, not a real position read -- it only has to land
    # inside DEFENSE so the row survives the filter and can grade a prop.
    solo = float(row.get("def_tackles_solo", 0) or 0)
    ast = float(row.get("def_tackle_assists", 0) or 0)
    sacks = float(row.get("def_sacks", 0) or 0)
    ints = float(row.get("def_interceptions", 0) or 0)
    if solo + ast + sacks + ints > 0:
        return "LB"
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
    # The static historical CSVs (2023-25 on prod) do NOT carry the current season, so the grader
    # that resolves prop candidates against these logs was stuck one season behind (NFL_AllPropResults
    # frozen at 2025 while 2026 props couldn't resolve). Fold in the routinely-refreshed in-season
    # nflverse weekly parquet(s) -- SAME schema -- for any season a CSV doesn't already cover (avoid
    # double-count), with jw26.parquet as the 2026 fallback. Mirrors _nfl_player_log_sources() in app.
    csv_seasons = {int(os.path.basename(f).split("_")[-1].split(".")[0]) for f in files}
    parquet_src = {}
    for pf in sorted(glob.glob(os.path.join(DATA, "tracking", "_nflverse_stats_20*.parquet"))):
        digits = "".join(ch for ch in os.path.basename(pf) if ch.isdigit())[:4]
        if digits:
            parquet_src[int(digits)] = pf
    legacy = os.path.join(BASE, "jw26.parquet")
    if 2026 not in parquet_src and 2026 not in csv_seasons and os.path.exists(legacy):
        parquet_src[2026] = legacy
    parquet_src = {s: p for s, p in parquet_src.items() if s not in csv_seasons}
    if not files and not parquet_src:
        print("build_nfl_gamelogs: no NFL_PlayerStats_*.csv / weekly parquet source — skipping.")
        return

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

    keep_seasons = sorted(csv_seasons | set(parquet_src))[-SEASONS_KEPT:]

    frames = []
    for f in files:
        season = int(os.path.basename(f).split("_")[-1].split(".")[0])
        if season in keep_seasons:
            frames.append(pd.read_csv(f))
    for season, pf in sorted(parquet_src.items()):
        if season in keep_seasons:
            try:
                frames.append(pd.read_parquet(pf))
            except Exception as exc:
                print(f"build_nfl_gamelogs: could not read {pf}: {exc}")
    if not frames:
        print("build_nfl_gamelogs: no source frames in the kept seasons — skipping.")
        return
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

    # Defensive stat columns, for grading defensive props. "Tackles" is the
    # combined figure books price (solo + assists), kept alongside solo so both
    # markets can grade. Sacks carry halves in the source, which is what makes a
    # 0.5 line gradeable at all, so they stay float.
    out["Tackles"] = num("def_tackles_solo") + num("def_tackle_assists")
    out["SoloTackles"] = num("def_tackles_solo")
    out["Sacks"] = num("def_sacks")
    out["DefInt"] = num("def_interceptions")

    out["Date"] = [_week_to_date(s, w) for s, w in zip(out["Season"], out["Week"])]

    # Keep a player if he did something in one of the two lanes: skill position
    # with offensive usage, or defensive position with defensive production.
    # Judging defenders by offensive usage (the old single filter) dropped every
    # one of them.
    offense = out["Position"].isin(SKILL) & (
        out[["PassYd", "RushYd", "RecYd", "Rec", "Targets"]].abs().sum(axis=1) > 0
    )
    defense = out["Position"].isin(DEFENSE) & (
        out[["Tackles", "Sacks", "DefInt"]].abs().sum(axis=1) > 0
    )
    out = out[(offense | defense) & out["Date"].astype(bool)]
    out = out.sort_values(["Date", "Player"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False)
    seasons = ", ".join(str(int(s)) for s in sorted(out["Season"].dropna().unique()))
    print(f"Wrote {OUT}: {len(out):,} game rows | seasons {seasons} | "
          f"{out['Player'].nunique():,} players | positions {out['Position'].value_counts().to_dict()}")


if __name__ == "__main__":
    build()
