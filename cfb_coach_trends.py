#!/usr/bin/env python3
"""
CFB coach / favorite ATS trends for the matchup read.

Our research found the COACH is a sharper ATS signal than the team, and that big
favorites cover only ~48% (a coin flip) -- with some programs far worse (Georgia is
0-14 ATS as a 40+ favorite). This surfaces that for the favorite in a game: the current
coach (CFBD), the team's ATS record as a favorite, and -- when it's a big favorite --
the team's record at that threshold, plus the league band as the baseline.

Reads (all committable, built in the CFB refresh lane):
  cfb_coaches_2026.json (team -> current coach), cfb_ats.json (coach + team ATS history),
  cfb_bigfav_records.json (per-team record as a 20/30/40+ favorite),
  cfb_favorites.json (league cover% by favorite band).

Honest: these are DESCRIPTIVE ATS histories, not a promised edge -- but "don't lay a big
number with a team that historically doesn't cover big" is a real, research-backed lean.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCEN = BASE_DIR / "data" / "scenarios"


@lru_cache(maxsize=1)
def _load():
    def _j(name):
        p = SCEN / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            return {}
    return {
        "coaches": _j("cfb_coaches_2026.json").get("coaches", {}),
        "ats": _j("cfb_ats.json"),
        "bigfav": _j("cfb_bigfav_records.json"),
        "favmeta": _j("cfb_favorites.json").get("meta", {}),
    }


def clear_cache():
    _load.cache_clear()


def _resolve(team):
    try:
        import cfb_current_form as cff
        # reuse the odds-name -> CFBD-school resolver, then title-case for the JSON keys
        return cff._resolve(team)
    except Exception:
        return str(team or "").strip().lower()


def _school_key(team, keys):
    """Match a resolved (lowercased) team to the JSON's proper-cased school key."""
    r = _resolve(team)
    for k in keys:
        if k.lower() == r:
            return k
    # fall back: longest proper key the query starts with
    q = str(team or "").strip().lower()
    for k in sorted(keys, key=len, reverse=True):
        if q.startswith(k.lower() + " ") or q == k.lower():
            return k
    return None


def favorite_trend(fav_team, spread_mag) -> dict | None:
    """ATS trend for the FAVORITE in a game. spread_mag = points they're laying (>0)."""
    d = _load()
    ats = d["ats"]
    team_seasons = ats.get("team_seasons", {})
    key = _school_key(fav_team, list(team_seasons.keys()))
    if not key:
        return None
    out = {"team": key, "coach": d["coaches"].get(key), "note": None}

    # team ATS as a favorite (all seasons)
    fw = fl = 0
    for yr in team_seasons.get(key, {}).get("s", {}).values():
        f = yr.get("fav")
        if f:
            fw += f[0]; fl += f[1]
    out["fav_ats"] = f"{fw}-{fl}" if (fw + fl) else None
    out["fav_cover"] = round(100 * fw / (fw + fl)) if (fw + fl) else None

    # coach career ATS (coach-specific)
    coach = out["coach"]
    cs = ats.get("coach_seasons", {}).get(coach or "", {})
    cw = sum(v.get("ats", [0, 0, 0])[0] for v in cs.values())
    cl = sum(v.get("ats", [0, 0, 0])[1] for v in cs.values())
    out["coach_ats"] = f"{cw}-{cl}" if (cw + cl) >= 20 else None
    out["coach_cover"] = round(100 * cw / (cw + cl)) if (cw + cl) >= 20 else None

    # big-favorite record at the highest threshold this spread meets
    big = None
    for th in (40, 30, 20):
        if spread_mag is not None and abs(spread_mag) >= th:
            rec = d["bigfav"].get("thresholds", {}).get(str(th), {}).get("teams", {}).get(key)
            if rec:
                big = {"threshold": th, "cover": round(100 * rec[0]), "record": rec[1], "avg": rec[2]}
            break
    out["bigfav"] = big

    # league baseline for a big favorite
    band = None
    fm = d["favmeta"]
    if spread_mag is not None and abs(spread_mag) >= 20:
        band = fm.get("band40" if abs(spread_mag) >= 40 else "band30", {}).get("cover")

    # plain-English note
    bits = []
    if out["coach"]:
        lead = f"{key} ({out['coach']})"
    else:
        lead = key
    if big:
        bits.append(f"as a {big['threshold']}+ favorite: {big['record']} ATS ({big['cover']}%), {big['avg']:+.1f} vs the line")
    elif out["fav_ats"]:
        bits.append(f"as a favorite: {out['fav_ats']} ATS ({out['fav_cover']}%)")
    if out["coach_ats"]:
        bits.append(f"{out['coach']} career {out['coach_ats']} ATS ({out['coach_cover']}%)")
    if band:
        bits.append(f"big favorites cover ~{round(band*100)}% league-wide")
    out["note"] = f"{lead} " + "; ".join(bits) + "." if bits else None
    return out if out["note"] else None


if __name__ == "__main__":
    import sys
    fav = sys.argv[1] if len(sys.argv) > 1 else "Georgia Bulldogs"
    mag = float(sys.argv[2]) if len(sys.argv) > 2 else 13.5
    r = favorite_trend(fav, mag)
    print(r["note"] if r else "no trend")
