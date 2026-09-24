#!/usr/bin/env python3
"""
Receiver-archetype gate for NFL prop plays.

PropScore rewards target volume/usage but not receiver ARCHETYPE. A deep threat (high
average depth of target) catches few balls on downfield targets, so his RECEPTION count
is volatile and often sits right on a low line -- a coin flip the model ranks as a top
play off "line value". Jameson Williams (aDOT 13.6, averaging 3.0 catches) was the #1
board play at OVER 3.5 receptions three weeks running and went 4, then 2: his edge is
YARDS, not catches.

This flags receptions props on deep-threat archetypes (and can down-weight them). Like
the early-season usage gate, it is a CONFIDENCE flag, not a pick reversal -- it says
"this player's catch count is volatile, look at his yards instead."

Data: data/rosters/NFL_ReceiverProfile.csv (build_nfl_receiver_profile.py). No-ops if
missing. DEEP_ADOT ~13.5 yds/target separates downfield receivers from possession types.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "data" / "rosters" / "NFL_ReceiverProfile.csv"

DEEP_ADOT = 13.5          # air yards per target above this = downfield / deep threat
LOW_VOLUME_RECEPTIONS = 5.0  # only flag when catch count is low enough to be line-sensitive
RECEPTIONS_SCORE_MULT = 0.8  # optional down-weight for a flagged receptions play


def _norm(name) -> str:
    return str(name or "").strip().lower()


@lru_cache(maxsize=1)
def _profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    try:
        df = pd.read_csv(PROFILE_PATH)
    except Exception:
        return {}
    return {_norm(r["Player"]): {"aDOT": r.get("aDOT"), "avg_rec": r.get("avg_rec"),
                                 "target_share": r.get("target_share")}
            for _, r in df.iterrows()}


def clear_cache():
    _profile.cache_clear()


def deep_threat(player: str):
    """Return the player's profile if they're a deep-threat archetype (high aDOT,
    low-ish catch volume), else None."""
    p = _profile().get(_norm(player))
    if not p:
        return None
    try:
        adot = float(p["aDOT"]); avg = float(p["avg_rec"])
    except (TypeError, ValueError):
        return None
    if adot >= DEEP_ADOT and avg <= LOW_VOLUME_RECEPTIONS:
        return {"aDOT": adot, "avg_rec": avg}
    return None


def archetype_flag(player: str, stat) -> dict | None:
    """Flag a receptions prop on a deep-threat archetype. Returns None otherwise."""
    if str(stat).strip().lower() != "receptions":
        return None
    dt = deep_threat(player)
    if not dt:
        return None
    return {
        "flag": "deep_threat",
        "note": (f"Deep threat (aDOT {dt['aDOT']:.0f}, avg {dt['avg_rec']:.0f} catches) — "
                 f"his catch count is volatile; the edge is his yards, not receptions."),
        "score_mult": RECEPTIONS_SCORE_MULT,
    }


def annotate_plays(plays: list, apply_penalty: bool = False) -> list:
    """Add archetype_flag / archetype_note to receptions plays on deep threats, in place.
    Non-destructive on prop_score unless apply_penalty=True (original kept in prop_score_raw)."""
    for p in plays:
        f = archetype_flag(p.get("player"), p.get("stat"))
        if not f:
            continue
        p["archetype_flag"] = f["flag"]
        p["archetype_note"] = f["note"]
        if apply_penalty:
            try:
                raw = float(p.get("prop_score"))
                p.setdefault("prop_score_raw", raw)
                p["prop_score"] = round(raw * f["score_mult"], 1)
            except (TypeError, ValueError):
                pass
    return plays


if __name__ == "__main__":
    for who in ("Jameson Williams", "DJ Moore", "Davante Adams", "CeeDee Lamb"):
        dt = deep_threat(who)
        print(f"  {who:<20} deep_threat={bool(dt)} {dt or ''}  receptions_flag={bool(archetype_flag(who, 'Receptions'))}")
