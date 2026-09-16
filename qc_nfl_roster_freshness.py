#!/usr/bin/env python3
"""
NFL roster freshness / coverage QC.

A guardrail against the roster feed going stale or empty (e.g. the ESPN-UA ban
that once emptied NFL_CurrentRoster.csv in Week 1). It checks the roster file is
present, recent, covers all 32 teams, and has a sane player count.

IMPORTANT scope note: a FRESH roster is necessary but NOT sufficient for good
early-season prop plays. The roster carries each player's current *team*, but
PropScore projects *usage/volume* from prior-season stats, so a player who
changed teams and role (e.g. a back who became a new team's workhorse) is
projected on a stale role for the first few weeks regardless of this check.
That is an early-season confidence-gating problem, tracked separately via the
weekly live grader (grade_nfl_week.py). See docs / memory.

Returns the standard QC shape: {failure_count, warning_count, notes}.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
ROSTER_PATH = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"

MAX_AGE_HOURS = 240        # ~10 days: rosters churn weekly in-season
MIN_TEAMS = 32
MIN_PLAYERS = 1600         # 32 teams x ~50+ on an expanded roster


def run_qc() -> dict:
    if not ROSTER_PATH.exists():
        return {"failure_count": 1, "warning_count": 0,
                "notes": f"Missing roster file: {ROSTER_PATH.name}"}
    try:
        df = pd.read_csv(ROSTER_PATH)
    except Exception as exc:  # empty/header-only file etc.
        return {"failure_count": 1, "warning_count": 0,
                "notes": f"Roster file unreadable ({type(exc).__name__}) - likely emptied by a failed fetch."}

    fails, warns, notes = [], [], []
    team_col = next((c for c in ("CurrentTeam", "TeamName", "Team") if c in df.columns), None)
    teams = df[team_col].nunique() if team_col else 0
    players = len(df)

    # age -- prefer the LastUpdated column, fall back to file mtime
    age_hours = None
    if "LastUpdated" in df.columns and df["LastUpdated"].notna().any():
        ts = pd.to_datetime(df["LastUpdated"], errors="coerce", utc=True).max()
        if pd.notna(ts):
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if age_hours is None:
        mtime = datetime.fromtimestamp(ROSTER_PATH.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600

    if players < MIN_PLAYERS:
        fails.append(f"only {players} players (< {MIN_PLAYERS}) - roster looks truncated/emptied")
    if teams < MIN_TEAMS:
        fails.append(f"only {teams}/{MIN_TEAMS} teams present")
    if age_hours > MAX_AGE_HOURS:
        fails.append(f"stale: {age_hours:.0f}h old (> {MAX_AGE_HOURS}h)")
    elif age_hours > MAX_AGE_HOURS * 0.6:
        warns.append(f"aging: {age_hours:.0f}h old")

    notes.append(f"Players: {players} | Teams: {teams} | AgeHours: {age_hours:.1f}")
    if fails:
        notes.append("FAIL: " + "; ".join(fails))
    return {"failure_count": len(fails), "warning_count": len(warns),
            "notes": " | ".join(notes)}


if __name__ == "__main__":
    r = run_qc()
    print("NFL ROSTER FRESHNESS QC")
    print(f"  FAIL: {r['failure_count']} | WARN: {r['warning_count']}")
    print(f"  {r['notes']}")
