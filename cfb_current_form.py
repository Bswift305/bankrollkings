#!/usr/bin/env python3
"""
CFB current-season form + common-opponent read.

Makes the CFB tools reason about how teams have ACTUALLY played this year, and
compares them through shared opponents (the sharpest cheap signal in early CFB):
if A beat X by 13 at home and B beat X by 11 on the road, they are close, so a
long line between them is suspect.

Data: data/scenarios/cfb_2026_results.json (build_cfb_2026_results.py). Degrades
to empty reads if missing. HOME_EDGE ~2.5 pts is the standard neutral adjustment.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "data" / "scenarios" / "cfb_2026_results.json"
HOME_EDGE = 2.5


@lru_cache(maxsize=1)
def _games() -> tuple:
    if not RESULTS_PATH.exists():
        return tuple()
    try:
        return tuple(json.loads(RESULTS_PATH.read_text(encoding="utf-8")).get("games", []))
    except Exception:
        return tuple()


def clear_cache():
    _games.cache_clear()


def _norm(t) -> str:
    return str(t or "").strip().lower()


@lru_cache(maxsize=1)
def _cfbd_names() -> tuple:
    s = set()
    for g in _games():
        s.add(_norm(g["home"])); s.add(_norm(g["away"]))
    # longest first so "texas tech" beats "texas" on a prefix match
    return tuple(sorted(s, key=len, reverse=True))


def _resolve(team: str) -> str:
    """Map an odds-feed name ('Texas Tech Red Raiders') to the CFBD school name
    ('texas tech'). Exact match wins; else the longest CFBD name the query starts
    with (mascot stripped). Falls back to the normalized query."""
    q = _norm(team)
    names = _cfbd_names()
    if q in names:
        return q
    for c in names:  # longest-first
        if q.startswith(c + " ") or q == c:
            return c
    return q


def team_games(team: str) -> list:
    """This team's completed 2026 games, each as a normalized result from the
    team's perspective (opponent, points for/against, margin, home/away/neutral)."""
    tl = _resolve(team)
    out = []
    for g in _games():
        home, away = _norm(g["home"]), _norm(g["away"])
        if tl not in (home, away):
            continue
        is_home = tl == home
        pf = g["home_pts"] if is_home else g["away_pts"]
        pa = g["away_pts"] if is_home else g["home_pts"]
        out.append({
            "week": g["week"],
            "opp": g["away"] if is_home else g["home"],
            "site": "N" if g.get("neutral") else ("H" if is_home else "A"),
            "pf": pf, "pa": pa, "margin": pf - pa,
        })
    return sorted(out, key=lambda x: x["week"])


def team_form(team: str) -> dict:
    gs = team_games(team)
    if not gs:
        return {"team": team, "games": 0}
    w = sum(1 for g in gs if g["margin"] > 0)
    return {
        "team": team, "games": len(gs), "record": f"{w}-{len(gs) - w}",
        "avg_margin": round(sum(g["margin"] for g in gs) / len(gs), 1),
        "ppg": round(sum(g["pf"] for g in gs) / len(gs), 1),
        "papg": round(sum(g["pa"] for g in gs) / len(gs), 1),
        "log": gs,
    }


def common_opponents(team_a: str, team_b: str) -> list:
    """Shared 2026 opponents with each team's margin, home/neutral adjusted, and the
    implied gap between A and B (positive = A looks better)."""
    a_by_opp = {_norm(g["opp"]): g for g in team_games(team_a)}
    b_by_opp = {_norm(g["opp"]): g for g in team_games(team_b)}
    out = []
    for opp in set(a_by_opp) & set(b_by_opp):
        ga, gb = a_by_opp[opp], b_by_opp[opp]

        def adj(g):  # margin adjusted to a neutral field
            return g["margin"] - (HOME_EDGE if g["site"] == "H" else (-HOME_EDGE if g["site"] == "A" else 0))
        gap = round(adj(ga) - adj(gb), 1)
        out.append({
            "opp": ga["opp"],
            "a_margin": ga["margin"], "a_site": ga["site"],
            "b_margin": gb["margin"], "b_site": gb["site"],
            "neutral_gap": gap,  # +ve => team_a looks better vs the shared opponent
        })
    return out


def matchup_read(away: str, home: str, spread_home=None) -> dict:
    """Current-form + common-opponent read for a game. spread_home is the HOME
    team's spread (negative = home favored). Returns a projected home margin from
    common opponents (when available) and a plain-English note."""
    fa, fh = team_form(away), team_form(home)
    commons = common_opponents(home, away)  # positive gap => home looks better
    read = {"away": away, "home": home, "away_form": fa, "home_form": fh,
            "commons": commons, "proj_home_margin": None, "note": None, "lean": None}
    if commons:
        gap = sum(c["neutral_gap"] for c in commons) / len(commons)  # home minus away, neutral
        proj = round(gap + HOME_EDGE, 1)  # add home field for tonight
        read["proj_home_margin"] = proj
        if spread_home is not None:
            edge = round(proj - (-spread_home), 1)  # proj margin vs the number the home team must cover
            if abs(edge) >= 3:
                side = home if edge > 0 else away
                read["lean"] = f"{side} (common-opp projects {proj:+.0f}, line asks {-spread_home:+.0f})"
            else:
                read["lean"] = f"line ~fair (common-opp projects home {proj:+.0f} vs {-spread_home:+.0f} needed)"
        via = ", ".join(f"both played {c['opp']}" for c in commons[:2])
        read["note"] = f"Common opponents ({via}) project {home} by ~{proj:+.0f} on a neutral-adjusted basis."
    else:
        read["note"] = "No shared 2026 opponents yet — read off form only."
    return read


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        r = matchup_read(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
        print(json.dumps({k: r[k] for k in ("proj_home_margin", "lean", "note")}, indent=2))
        for c in r["commons"]:
            print("  common:", c)
