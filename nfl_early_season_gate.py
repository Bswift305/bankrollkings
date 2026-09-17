#!/usr/bin/env python3
"""
Early-season usage gate for NFL prop plays.

The Week-1 2026 retro found the PropScore board's worst misses came from players
who changed teams: the roster carries the correct current TEAM, but the model
projects usage/volume from prior-season stats, so a back who became a new team's
workhorse (Kenneth Walker III: SEA -> KC, projected UNDER, ran 23/173) is scored
on a stale role. There is no current-season snap/target/carry data to correct it
in the first few weeks.

This gate flags (and can down-weight) prop plays whose player changed teams while
the season is still young. It is a CONFIDENCE flag, not a pick reversal -- it says
"the projection for this player is on shaky ground right now," which is exactly the
honesty the board is built on.

Data: data/rosters/NFL_PriorSeasonTeams.csv (build_nfl_prior_team_map.py) +
data/rosters/NFL_CurrentRoster.csv. Both team codes normalized to roster convention.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
PRIOR_PATH = BASE_DIR / "data" / "rosters" / "NFL_PriorSeasonTeams.csv"
ROSTER_PATH = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"

# Flag movers only while the season is young; by ~week 4 there is enough
# current-season usage for the projection to self-correct.
EARLY_SEASON_LAST_WEEK = 3
# How hard to down-weight a flagged play's PropScore (multiplier). Kept modest;
# a flag is informational first. Enable the penalty via annotate_plays(apply_penalty=True).
NEW_TEAM_SCORE_MULT = 0.75


def _norm(name) -> str:
    return str(name or "").strip().lower()


@lru_cache(maxsize=1)
def _movers() -> frozenset:
    """Players (lowercased) whose current team differs from their most-played
    prior-season team. Cached; call clear_cache() after rebuilding the inputs."""
    if not PRIOR_PATH.exists() or not ROSTER_PATH.exists():
        return frozenset()
    try:
        prior = pd.read_csv(PRIOR_PATH)
        roster = pd.read_csv(ROSTER_PATH)
    except Exception:
        return frozenset()
    pm = {_norm(r["Player"]): str(r["PriorTeam"]).strip()
          for _, r in prior.iterrows() if pd.notna(r.get("PriorTeam"))}
    movers = set()
    for _, r in roster.iterrows():
        p = _norm(r.get("Player"))
        ct = r.get("CurrentTeam")
        if p and p in pm and pd.notna(ct) and pm[p] != str(ct).strip():
            movers.add(p)
    return frozenset(movers)


def clear_cache():
    _movers.cache_clear()


def current_week(today=None):
    """Estimate the NFL week from the date. Week 1 kicks off the Thursday after
    Labor Day (first Monday of September); weeks run Thu-Wed. Returns None in the
    offseason (before kickoff), so the gate is a no-op then."""
    from datetime import date, timedelta
    d = today or date.today()
    year = d.year if d.month >= 3 else d.year - 1  # a Jan/Feb date belongs to the prior season
    sep1 = date(year, 9, 1)
    labor_day = sep1 + timedelta(days=(7 - sep1.weekday()) % 7)  # first Monday of September
    week1_thu = labor_day + timedelta(days=3)
    if d < week1_thu:
        return None
    return min(((d - week1_thu).days // 7) + 1, 22)


def is_mover(player: str) -> bool:
    return _norm(player) in _movers()


def usage_flag(player: str, week) -> dict | None:
    """Return a flag dict for a play, or None if the play is not gated.
    Only movers, and only through EARLY_SEASON_LAST_WEEK."""
    try:
        wk = int(week)
    except (TypeError, ValueError):
        return None
    if wk > EARLY_SEASON_LAST_WEEK:
        return None
    if not is_mover(player):
        return None
    return {
        "flag": "new_team",
        "note": "New team this year — early-season usage unproven (projected on last year's role).",
        "score_mult": NEW_TEAM_SCORE_MULT,
    }


def annotate_plays(plays: list, week, apply_penalty: bool = False) -> list:
    """Add usage_flag / usage_note (and optionally a down-weighted score) to each
    play dict in place. Non-destructive on prop_score unless apply_penalty=True,
    in which case the original is preserved in 'prop_score_raw'."""
    for p in plays:
        f = usage_flag(p.get("player"), week)
        if not f:
            continue
        p["usage_flag"] = f["flag"]
        p["usage_note"] = f["note"]
        if apply_penalty:
            try:
                raw = float(p.get("prop_score"))
                p["prop_score_raw"] = raw
                p["prop_score"] = round(raw * f["score_mult"], 1)
            except (TypeError, ValueError):
                pass
    return plays


if __name__ == "__main__":
    ms = _movers()
    print(f"Team-changers loaded: {len(ms)}")
    for who in ("Kenneth Walker III", "David Montgomery", "CeeDee Lamb", "Puka Nacua"):
        print(f"  {who:<22} mover={is_mover(who)}  wk1_flag={bool(usage_flag(who, 1))}  wk5_flag={bool(usage_flag(who, 5))}")
