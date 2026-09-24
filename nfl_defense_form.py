#!/usr/bin/env python3
"""
NFL defensive tackle-volume read.

Reads current-season defender form (build_nfl_defense_form.py) and reads a tackle prop
against real 2026 volume: solo tackles vs solo/gm pace, "Tackles + Assists" vs combined/gm.
Tackle counts are role-driven and stable enough to project off pace; the read is an honest
VOLUME comparison, not a backtested edge, and it always carries the game count.

Sacks are intentionally NOT given a lean here -- they're a low-base-rate coin flip. The
board can still show a rusher's sack/QB-hit pace as context, but never as an edge.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEF_PATH = BASE_DIR / "data" / "scenarios" / "nfl_2026_defense.json"

CUSHION = 0.75          # tackles of daylight before it's a lean, not a coin flip
STRONG_EDGE = 1.5       # pace this far past the line = the firmer volume signal
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.I)


@lru_cache(maxsize=1)
def _data() -> dict:
    if not DEF_PATH.exists():
        return {}
    try:
        return json.loads(DEF_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _norm(name: str) -> str:
    n = str(name or "").strip().lower()
    n = _SUFFIX.sub("", n).strip()
    return re.sub(r"[^a-z ]", "", n).strip()


@lru_cache(maxsize=1)
def _index() -> dict:
    """Normalized-name -> player form (suffix/punctuation-insensitive)."""
    out = {}
    for name, rec in _data().get("players", {}).items():
        out[_norm(name)] = dict(rec, _name=name)
    return out


def clear_cache():
    _data.cache_clear()
    _index.cache_clear()


def player_form(name: str) -> dict | None:
    return _index().get(_norm(name))


def _pace_for(stat: str, f: dict):
    s = str(stat or "").lower()
    if "solo" in s:
        return f.get("solo_pg"), "solo"
    if "tackle" in s or "assist" in s:
        return f.get("comb_pg"), "combined"
    return None, None


def tackle_lean(name: str, stat: str, line) -> dict | None:
    """Read one tackle prop against the player's 2026 pace. Returns pace, edge, a
    lean (OVER/UNDER/COIN FLIP) and a short note. None if not a tackle prop or no form."""
    f = player_form(name)
    if not f:
        return None
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    pace, kind = _pace_for(stat, f)
    if pace is None:
        return None
    edge = round(pace - line, 1)
    if edge >= CUSHION:
        lean = "OVER"
    elif edge <= -CUSHION:
        lean = "UNDER"
    else:
        lean = "COIN FLIP"
    strong = abs(edge) >= STRONG_EDGE and lean != "COIN FLIP"
    gms = int(f.get("games") or 0)
    note = (f"{f.get('_name', name)} ({f.get('pos', '?')}, {f.get('team', '?')}): "
            f"{pace}/gm {kind} vs {line:g} line — {edge:+g} ({gms}g)")
    return {
        "player": name, "stat": stat, "line": line, "pace": pace, "kind": kind,
        "edge": edge, "lean": lean, "strong": strong, "games": gms,
        "pos": f.get("pos", ""), "team": f.get("team", ""), "note": note,
    }


def sack_context(name: str) -> dict | None:
    """Sack/QB-hit pace as CONTEXT only -- explicitly not a lean."""
    f = player_form(name)
    if not f:
        return None
    return {"player": name, "team": f.get("team", ""), "pos": f.get("pos", ""),
            "sacks": f.get("sacks", 0), "qb_hits": f.get("qb_hits", 0), "games": int(f.get("games") or 0)}


def game_tackle_reads(props_rows, limit: int = 8) -> list:
    """Annotate a game's tackle props with the volume read, strongest edge first.
    props_rows: iterable of dicts with keys player, stat, line."""
    out = []
    for r in props_rows:
        rd = tackle_lean(r.get("player"), r.get("stat"), r.get("line"))
        if rd:
            out.append(rd)
    out.sort(key=lambda x: (x["lean"] == "COIN FLIP", -abs(x["edge"])))
    return out[:limit]


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        print(json.dumps(tackle_lean(sys.argv[1], sys.argv[2], sys.argv[3]), indent=2))
    else:
        for nm, st, ln in [("Evan Williams", "Tackles + Assists", 6.5),
                           ("Evan Williams", "Solo Tackles", 3.5),
                           ("Divine Deablo", "Tackles + Assists", 6.5),
                           ("Xavier McKinney", "Tackles + Assists", 5.5)]:
            print(tackle_lean(nm, st, ln)["note"], "->", tackle_lean(nm, st, ln)["lean"])
