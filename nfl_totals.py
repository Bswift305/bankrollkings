#!/usr/bin/env python3
"""
NFL totals model with a starting-QB-out veto.

Opponent-adjusted offense/defense point ratings (iterative, blended with last season's
per-team scoring as a prior, points capped), internally re-centered to this season's
scoring average so it isn't a systematic over-machine. Then -- the piece that matters --
if a team's STARTING QB (its leading passer) is OUT, its offense is penalized and the
game is flagged, because a scoring model built on team history is otherwise blind to its
QB being done. That blindness is what would have shown a Giants OVER with Jaxson Dart out
for the season (and a Commanders over with Jayden Daniels out).

Data: data/scenarios/nfl_scores.json (build_nfl_scores.py) + data/injuries/NFL_Injuries.csv.
"""
from __future__ import annotations
import csv
import json
import re
import statistics
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCORES_PATH = BASE_DIR / "data" / "scenarios" / "nfl_scores.json"
INJ_PATH = BASE_DIR / "data" / "injuries" / "NFL_Injuries.csv"
CAP = 41.0            # cap a team's points in one game so a blowout can't warp the rating
PRIOR_GAMES = 6.0     # last-season prior worth this many games (heavy early, decays)
QB_OUT_PENALTY = 6.5  # points shaved off a team's offense when its starting QB is out
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.I)


def _nm(s):
    n = _SUFFIX.sub("", str(s or "").strip().lower()).strip()
    return re.sub(r"[^a-z ]", "", n).strip()


@lru_cache(maxsize=1)
def _scores() -> dict:
    if not SCORES_PATH.exists():
        return {}
    try:
        return json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


RECV_SCALE = 6.5   # points lost per full share of receiving production out
RUSH_SCALE = 3.5   # rushing is more replaceable
SKILL_CAP = 4.5    # cap the non-QB skill penalty


@lru_cache(maxsize=1)
def _out_qbs() -> frozenset:
    """Normalized names of players listed OUT/DOUBTFUL."""
    if not INJ_PATH.exists():
        return frozenset()
    out = set()
    try:
        with INJ_PATH.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("Status", "")).strip().upper() in ("OUT", "DOUBTFUL"):
                    out.add(_nm(r.get("Player")))
    except Exception:
        return frozenset()
    return frozenset(out)


def clear_cache():
    _scores.cache_clear()
    _out_qbs.cache_clear()
    _ratings.cache_clear()


_ABBR = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX", "LVR": "LV", "STL": "LAR"}


def _team(t):
    u = str(t or "").upper()
    return _ABBR.get(u, u)


def qb_out(team: str):
    """The team's starting QB (leading passer) name if he's OUT, else None."""
    s = _scores()
    q = s.get("qb1", {}).get(_team(team))
    if q and _nm(q.get("name")) in _out_qbs():
        return q.get("name")
    return None


def skill_out(team: str) -> dict | None:
    """Weight receiving/rushing injuries by the SHARE of production that's OUT -- so a
    star who's been hurt and non-productive (A.J. Brown, 26 yds) counts little, while a
    real chunk of the offense missing counts a lot. Returns the penalty + who's out."""
    s = _scores()
    tm = _team(team)
    recv = s.get("recv", {}).get(tm, [])
    rush = s.get("rush", {}).get(tm, [])
    out = _out_qbs()
    rt = sum(y for _, y in recv) or 1
    ct = sum(c for _, c in rush) or 1
    recv_out = [(n, y) for n, y in recv if _nm(n) in out]
    rush_out = [(n, c) for n, c in rush if _nm(n) in out]
    recv_share = sum(y for _, y in recv_out) / rt
    rush_share = sum(c for _, c in rush_out) / ct
    pen = min(recv_share * RECV_SCALE + rush_share * RUSH_SCALE, SKILL_CAP)
    if pen < 0.75:
        return None  # not enough production out to matter
    names = [n for n, _ in recv_out] + [n for n, _ in rush_out if n not in [x for x, _ in recv_out]]
    return {"penalty": round(pen, 1), "players": names,
            "recv_share": round(recv_share, 2), "rush_share": round(rush_share, 2)}


@lru_cache(maxsize=1)
def _ratings() -> tuple:
    """(off, deff, league_pts): opponent-adjusted, prior-blended, re-centered to LP."""
    from collections import defaultdict
    s = _scores()
    games = s.get("games", [])
    prior = {k: tuple(v) for k, v in s.get("prior", {}).items()}
    lp = s.get("league_pts") or 22.5
    if not games:
        return ({}, {}, lp)
    sched = defaultdict(list)
    for h, a, hs, as_ in games:
        sched[h].append((a, min(hs, CAP), min(as_, CAP)))
        sched[a].append((h, min(as_, CAP), min(hs, CAP)))
    off = {t: prior.get(t, (lp, lp))[0] for t in sched}
    deff = {t: prior.get(t, (lp, lp))[1] for t in sched}
    for _ in range(40):
        no, nd = {}, {}
        for t, gs in sched.items():
            o = sum(sc - (deff.get(op, lp) - lp) for op, sc, al in gs)
            dd = sum(al - (off.get(op, lp) - lp) for op, sc, al in gs)
            po, pd_ = prior.get(t, (lp, lp))
            no[t] = (o + PRIOR_GAMES * po) / (len(gs) + PRIOR_GAMES)
            nd[t] = (dd + PRIOR_GAMES * pd_) / (len(gs) + PRIOR_GAMES)
        off, deff = no, nd
    # internal de-bias: re-center so the average team's off/def == LP (kills the
    # "everything's an over" tilt from last season being a higher-scoring environment).
    mo = statistics.mean(off.values()); md = statistics.mean(deff.values())
    off = {t: off[t] + (lp - mo) for t in off}
    deff = {t: deff[t] + (lp - md) for t in deff}
    return (off, deff, lp)


def projected_total(away: str, home: str, apply_qb_veto: bool = True) -> dict | None:
    """Projected total for away@home (team ABBREVs). Applies the QB-out penalty to any
    side whose starting QB is out. Returns the total plus which sides are vetoed."""
    off, deff, lp = _ratings()
    a, h = _team(away), _team(home)
    if a not in off or h not in off:
        return None
    a_off, h_off = off[a], off[h]
    a_out, h_out = qb_out(a), qb_out(h)

    def _qb_penalty(team):
        try:
            import nfl_backup
            im = nfl_backup.impact(team)
            if im:
                return im["total_penalty"]  # backup-weighted (gunslinger < game-manager)
        except Exception:
            pass
        return QB_OUT_PENALTY
    a_skill = skill_out(a) if apply_qb_veto else None
    h_skill = skill_out(h) if apply_qb_veto else None
    if apply_qb_veto and a_out:
        a_off -= _qb_penalty(a)
    elif a_skill:                       # QB-out already downgrades the offense; don't stack
        a_off -= a_skill["penalty"]
    if apply_qb_veto and h_out:
        h_off -= _qb_penalty(h)
    elif h_skill:
        h_off -= h_skill["penalty"]
    a_pts = a_off + deff[h] - lp
    h_pts = h_off + deff[a] - lp
    return {"total": round(a_pts + h_pts, 1),
            "away_qb_out": a_out, "home_qb_out": h_out,
            "away_skill_out": a_skill, "home_skill_out": h_skill}


HFA = 1.6  # NFL home-field, in points of margin


def projected_margin(away: str, home: str) -> float | None:
    """Projected HOME margin from the off/def ratings (positive = home wins by), with a
    QB-out/skill penalty applied. Reuses the totals engine's ratings for an ATS read."""
    p = projected_total(away, home)  # applies QB/skill penalties to off
    if p is None:
        return None
    off, deff, lp = _ratings()
    a, h = _team(away), _team(home)
    a_off, h_off = off[a], off[h]
    if p.get("away_qb_out"):
        try:
            import nfl_backup
            im = nfl_backup.impact(a)
            a_off -= (im["total_penalty"] if im else QB_OUT_PENALTY)
        except Exception:
            a_off -= QB_OUT_PENALTY
    elif p.get("away_skill_out"):
        a_off -= p["away_skill_out"]["penalty"]
    if p.get("home_qb_out"):
        try:
            import nfl_backup
            im = nfl_backup.impact(h)
            h_off -= (im["total_penalty"] if im else QB_OUT_PENALTY)
        except Exception:
            h_off -= QB_OUT_PENALTY
    elif p.get("home_skill_out"):
        h_off -= p["home_skill_out"]["penalty"]
    h_pts = h_off + deff[a] - lp
    a_pts = a_off + deff[h] - lp
    m = h_pts - a_pts + HFA
    return round(max(-20.0, min(20.0, m)), 1)  # clamp: a 2-game margin model shouldn't project blowouts


def total_read(away: str, home: str, line=None) -> dict | None:
    p = projected_total(away, home)
    if p is None:
        return None
    read = {"proj_total": p["total"], "away_qb_out": p["away_qb_out"],
            "home_qb_out": p["home_qb_out"], "away_skill_out": p.get("away_skill_out"),
            "home_skill_out": p.get("home_skill_out"), "line": None, "edge": None, "lean": None}
    if line is not None:
        try:
            line = float(line)
            edge = round(p["total"] - line, 1)
            read.update(line=line, edge=edge,
                        lean=("OVER" if edge >= 2.5 else ("UNDER" if edge <= -2.5 else "line ~fair")))
        except (TypeError, ValueError):
            pass
    # a QB-out always leans the total down and vetoes an over, whatever the number says
    if read["away_qb_out"] or read["home_qb_out"]:
        who = " & ".join(x for x in (read["away_qb_out"], read["home_qb_out"]) if x)
        read["qb_note"] = f"{who} (starting QB) OUT — offense downgraded, leans UNDER"
        if read["edge"] is not None and read["edge"] < 2.5:
            read["lean"] = "UNDER (QB out)"
    else:
        sk = []
        for side in ("away_skill_out", "home_skill_out"):
            s = read.get(side)
            if s:
                sk.append(f"{', '.join(s['players'][:2])} OUT (-{s['penalty']})")
        if sk:
            read["skill_note"] = "Production out: " + "; ".join(sk)
    return read


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        print(json.dumps(total_read(sys.argv[1], sys.argv[2],
                                    float(sys.argv[3]) if len(sys.argv) > 3 else None), indent=2))
