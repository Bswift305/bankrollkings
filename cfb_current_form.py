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
    _srs.cache_clear()
    _srs_observed.cache_clear()
    _priors.cache_clear()
    _fbs_teams.cache_clear()
    _cfbd_names.cache_clear()


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


MOV_CAP = 24.0     # cap blowout margins so a 60-point win over a cupcake can't dominate the rating
FCS_ANCHOR = -26.0  # a non-FBS opponent is worth this (neutral) -- beating one by the cap ~= average
PRIOR_GAMES = 5.0   # SP+ preseason prior worth this many games; decays as real games accumulate
POWER_PATH = BASE_DIR / "data" / "scenarios" / "cfb_power.json"
FBS_CONFS = {
    "big ten", "acc", "big 12", "sec", "american athletic", "sun belt",
    "mid-american", "conference usa", "mountain west", "pac-12", "pac-12 conference",
    "fbs independents", "independent",
}


@lru_cache(maxsize=1)
def _fbs_teams() -> frozenset:
    """FBS team set: anyone whose conference is an FBS league, plus independents
    (Notre Dame et al., no FBS conf label) caught by having played >=3 FBS teams."""
    from collections import defaultdict
    confs = defaultdict(set)
    for g in _games():
        confs[_norm(g["home"])].add(str(g.get("home_conf") or "").strip().lower())
        confs[_norm(g["away"])].add(str(g.get("away_conf") or "").strip().lower())
    base = {t for t, cs in confs.items() if cs & FBS_CONFS}
    played = defaultdict(int)
    for g in _games():
        h, a = _norm(g["home"]), _norm(g["away"])
        if a in base:
            played[h] += 1
        if h in base:
            played[a] += 1
    indep = {t for t, n in played.items() if n >= 3}
    return frozenset(base | indep)


@lru_cache(maxsize=1)
def _priors() -> dict:
    """Preseason SP+ rating per team (points vs an average FBS team) -- the prior that
    keeps early-season ratings sane before schedules connect. From cfb_power.json."""
    if not POWER_PATH.exists():
        return {}
    try:
        board = json.loads(POWER_PATH.read_text(encoding="utf-8")).get("board", {})
        cols = [c["label"] for c in board.get("columns", [])]
        si = cols.index("SP+") if "SP+" in cols else 2
        return {_norm(r[0]): float(r[si]) for r in board.get("rows", []) if r and r[si] is not None}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _srs() -> dict:
    """Opponent-adjusted power rating (Simple Rating System), FBS only, with a decaying
    SP+ preseason prior. Each team's rating is the average of its neutral, MOV-capped
    margins PLUS each opponent's rating, blended with PRIOR_GAMES virtual games at its
    SP+ prior. Non-FBS opponents are pinned at FCS_ANCHOR so a cupcake blowout can't
    inflate a rating (the strength-of-schedule fix). Early season the prior dominates;
    it fades as real games accumulate. Ratings are points vs an average FBS team.
    """
    from collections import defaultdict
    fbs = _fbs_teams()
    if not fbs:
        return {}
    priors = _priors()
    sched = defaultdict(list)  # fbs team -> [(opp_or_None, neutral capped margin)]
    for g in _games():
        hp, ap = g.get("home_pts"), g.get("away_pts")
        if hp is None or ap is None:
            continue
        h, a = _norm(g["home"]), _norm(g["away"])
        if h not in fbs and a not in fbs:
            continue
        m = hp - ap
        if not g.get("neutral"):
            m -= HOME_EDGE
        m = max(-MOV_CAP, min(MOV_CAP, m))
        if h in fbs:
            sched[h].append((a if a in fbs else None, m))
        if a in fbs:
            sched[a].append((h if h in fbs else None, -m))
    rating = {t: priors.get(t, 0.0) for t in sched}
    for _ in range(40):
        nxt = {}
        for t, gs in sched.items():
            obs = sum(mar + (rating.get(opp, 0.0) if opp else FCS_ANCHOR) for opp, mar in gs)
            p = priors.get(t, 0.0)
            nxt[t] = (obs + PRIOR_GAMES * p) / (len(gs) + PRIOR_GAMES)  # prior as virtual games
        mean = sum(nxt.values()) / len(nxt)
        rating = {t: round(nxt[t] - mean, 2) for t in nxt}  # recenter to FBS average = 0
    return rating


def srs_rating(team: str):
    return _srs().get(_resolve(team))


@lru_cache(maxsize=1)
def _srs_observed() -> dict:
    """Each FBS team's PRIOR-FREE observed rating: avg(neutral capped margin + opponent's
    blended rating), with no SP+ prior in the numerator. Comparing this to the prior shows
    whether a team is playing ABOVE or BELOW preseason expectation -- the signal that the
    blended projection may be leaning on a stale prior (Oklahoma collapsed; Georgia surged)."""
    from collections import defaultdict
    fbs = _fbs_teams()
    rating = _srs()  # converged blended ratings, used for opponents
    if not fbs or not rating:
        return {}
    sched = defaultdict(list)
    for g in _games():
        hp, ap = g.get("home_pts"), g.get("away_pts")
        if hp is None or ap is None:
            continue
        h, a = _norm(g["home"]), _norm(g["away"])
        if h not in fbs and a not in fbs:
            continue
        m = hp - ap
        if not g.get("neutral"):
            m -= HOME_EDGE
        m = max(-MOV_CAP, min(MOV_CAP, m))
        if h in fbs:
            sched[h].append((a if a in fbs else None, m))
        if a in fbs:
            sched[a].append((h if h in fbs else None, -m))
    return {t: round(sum(mar + (rating.get(opp, 0.0) if opp else FCS_ANCHOR) for opp, mar in gs) / len(gs), 2)
            for t, gs in sched.items()}


@lru_cache(maxsize=1)
def _divergence_ranks() -> dict:
    """Rank each FBS team by observed play and by SP+ prior; the gap between the two
    ranks is the stale-prior signal. Rank comparison (not raw points) because the
    MOV-capped observed ratings sit on a compressed early-season scale vs SP+."""
    obs = _srs_observed()
    priors = _priors()
    common = [t for t in obs if t in priors]
    if not common:
        return {}
    obs_rank = {t: i + 1 for i, t in enumerate(sorted(common, key=lambda x: -obs[x]))}
    pri_rank = {t: i + 1 for i, t in enumerate(sorted(common, key=lambda x: -priors[x]))}
    return {t: {"obs_rank": obs_rank[t], "prior_rank": pri_rank[t],
                "obs": obs[t], "prior": round(priors[t], 1)} for t in common}


def prior_divergence(team: str) -> dict | None:
    """Whether a team is playing well above or below its preseason standing, by how far
    it has moved in the pecking order (observed rank vs SP+ prior rank). A big DROP means
    the blended projection is leaning on a prior the team's play contradicts (Oklahoma:
    #10 preseason, playing far worse); a big RISE means the prior under-rates them."""
    d = _divergence_ranks().get(_resolve(team))
    if not d:
        return None
    drop = d["obs_rank"] - d["prior_rank"]  # +ve = fell in the order (playing worse)
    # "surging" only when they've actually climbed into a good tier (not just less-bad);
    # "regressed" when a preseason-decent team has slid out of the top tier.
    if drop <= -15 and d["obs_rank"] <= 40:
        label = "surging"
    elif drop >= 15 and d["prior_rank"] <= 40:
        label = "regressed"
    else:
        label = "as expected"
    return {"obs_rank": d["obs_rank"], "prior_rank": d["prior_rank"],
            "drop": drop, "label": label}


def team_form(team: str) -> dict:
    gs = team_games(team)
    if not gs:
        return {"team": team, "games": 0}
    w = sum(1 for g in gs if g["margin"] > 0)
    return {
        "team": team, "games": len(gs), "record": f"{w}-{len(gs) - w}",
        "avg_margin": round(sum(g["margin"] for g in gs) / len(gs), 1),
        "srs": srs_rating(team),  # opponent-adjusted power rating (points vs an avg team)
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
    """Opponent-adjusted read for a game. spread_home is the HOME team's spread
    (negative = home favored). The projection now comes from the SRS power ratings
    (strength-of-schedule adjusted), with common opponents as corroboration when they
    exist. Returns a projected home margin, a lean vs the line, and a plain-English note."""
    fa, fh = team_form(away), team_form(home)
    commons = common_opponents(home, away)  # positive gap => home looks better
    read = {"away": away, "home": home, "away_form": fa, "home_form": fh,
            "commons": commons, "proj_home_margin": None, "proj_source": None,
            "note": None, "lean": None}
    rh, ra = srs_rating(home), srs_rating(away)
    proj = None
    if rh is not None and ra is not None:
        proj = round(rh - ra + HOME_EDGE, 1)  # SRS gap + home field
        read["proj_source"] = "SRS (opponent-adjusted)"
    elif commons:
        gap = sum(c["neutral_gap"] for c in commons) / len(commons)
        proj = round(gap + HOME_EDGE, 1)
        read["proj_source"] = "common opponents"

    if proj is not None:
        read["proj_home_margin"] = proj
        if spread_home is not None:
            edge = round(proj - (-spread_home), 1)  # proj margin vs what the home team must cover
            if abs(edge) >= 3:
                side = home if edge > 0 else away
                read["lean"] = f"{side} (form projects home {proj:+.0f}, line asks {-spread_home:+.0f} — edge {edge:+.0f})"
            else:
                read["lean"] = f"line ~fair (form projects home {proj:+.0f} vs {-spread_home:+.0f} needed)"
        srs_bit = ""
        if rh is not None and ra is not None:
            srs_bit = f" Power ratings: {home} {rh:+.0f} vs {away} {ra:+.0f} (points vs an average team)."
        common_bit = ""
        if commons:
            via = ", ".join(f"both played {c['opp']}" for c in commons[:2])
            common_bit = f" Corroborated by common opponents ({via})."
        read["note"] = (f"Opponent-adjusted form projects {home} by ~{proj:+.0f}.{srs_bit}{common_bit}").strip()
    else:
        read["note"] = "No 2026 rating yet for one side — read off the board."
    return read


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        r = matchup_read(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
        print(json.dumps({k: r[k] for k in ("proj_home_margin", "lean", "note")}, indent=2))
        for c in r["commons"]:
            print("  common:", c)
