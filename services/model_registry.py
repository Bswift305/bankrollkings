"""Governed Sport × Market × Angle registry.

Registry metadata is explanatory. Only entries with status ``Qualified`` and an attached,
passing validation record can receive decision authority; callers must use ``has_authority``
rather than interpreting status strings themselves.
"""
from __future__ import annotations

from copy import deepcopy


STATUSES = {"Discovery", "Under Review", "Qualified", "Failed", "Retired"}

_ENTRIES = {
    "nfl_qb_rushing_yards": {
        "model_id": "nfl_qb_rushing_yards",
        "version": "0.1.0",
        "sport": "nfl",
        "market": "rushing_yards",
        "angle": "QB rushing profile × opponent QB-rushing allowance",
        "eligible_positions": ["QB"],
        "status": "Discovery",
        "output": "contextual alignment only",
        "explanation": (
            "Tests whether an established QB rushing profile meets a defense that specifically "
            "allows QB rushing production. Generic RB rushing-defense numbers are not substitutes."
        ),
        "required_inputs": [
            "QB designed-run, scramble, and rushing-attempt profile",
            "opponent QB-rushing allowance",
            "game-state context",
            "market line and price",
        ],
        "validation": {
            "historical": "not complete",
            "holdout": "not complete",
            "prospective": "not complete",
        },
        "abstention": "Required angle-specific inputs are not yet verified together.",
    },
}


def _validated(entry):
    validation = entry.get("validation") or {}
    return all(validation.get(stage) == "passed" for stage in ("historical", "holdout", "prospective"))


def has_authority(entry):
    """Single governance firewall for ordering, selection, confidence, or recommendation."""
    return bool(entry and entry.get("status") == "Qualified" and _validated(entry))


def registry_entries():
    entries = []
    for value in _ENTRIES.values():
        if value.get("status") not in STATUSES:
            raise ValueError(f"invalid registry status: {value.get('status')}")
        row = deepcopy(value)
        row["has_authority"] = has_authority(row)
        entries.append(row)
    return entries


def research_for_market(sport, stat_key, position=None):
    """Return applicable research metadata; this function never sorts or scores candidates."""
    sport = str(sport or "").lower()
    stat_key = str(stat_key or "").lower()
    position = str(position or "").upper()
    out = []
    for entry in registry_entries():
        positions = entry.get("eligible_positions") or []
        if entry["sport"] != sport or entry["market"] != stat_key:
            continue
        if positions and position not in positions:
            continue
        out.append(entry)
    return out
