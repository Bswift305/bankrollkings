#!/usr/bin/env python3
"""
NFL current-season form read.

Turns the 2026 team-form JSON (build_nfl_team_form.py) into a plain-English read of how
each side is playing NOW -- run defense, pass defense, and pressure, each with its league
rank -- and a matchup note that says what the current form implies for the run game, the
passing game, and the total. The NFL sibling of cfb_current_form.matchup_read.

Small-sample honest: early in the season this is 2-3 games. The read always carries the
game count so a two-game rank never masquerades as settled fact. Degrades to empty reads
if the form file is missing.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FORM_PATH = BASE_DIR / "data" / "scenarios" / "nfl_2026_form.json"

# Full team name (odds/props feeds) -> nflverse/feed abbreviation.
NAME_TO_ABBR = {
    "arizona cardinals": "ARI", "atlanta falcons": "ATL", "baltimore ravens": "BAL",
    "buffalo bills": "BUF", "carolina panthers": "CAR", "chicago bears": "CHI",
    "cincinnati bengals": "CIN", "cleveland browns": "CLE", "dallas cowboys": "DAL",
    "denver broncos": "DEN", "detroit lions": "DET", "green bay packers": "GB",
    "houston texans": "HOU", "indianapolis colts": "IND", "jacksonville jaguars": "JAX",
    "kansas city chiefs": "KC", "las vegas raiders": "LV", "los angeles chargers": "LAC",
    "los angeles rams": "LAR", "miami dolphins": "MIA", "minnesota vikings": "MIN",
    "new england patriots": "NE", "new orleans saints": "NO", "new york giants": "NYG",
    "new york jets": "NYJ", "philadelphia eagles": "PHI", "pittsburgh steelers": "PIT",
    "san francisco 49ers": "SF", "seattle seahawks": "SEA", "tampa bay buccaneers": "TB",
    "tennessee titans": "TEN", "washington commanders": "WAS",
}
ABBR_ALIAS = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}


@lru_cache(maxsize=1)
def _data() -> dict:
    if not FORM_PATH.exists():
        return {}
    try:
        return json.loads(FORM_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clear_cache():
    _data.cache_clear()


def resolve(team: str) -> str:
    """Map a full name ('Atlanta Falcons') or a code ('ATL'/'LA') to the form key."""
    q = str(team or "").strip()
    if not q:
        return ""
    if q.lower() in NAME_TO_ABBR:
        return NAME_TO_ABBR[q.lower()]
    up = q.upper()
    up = ABBR_ALIAS.get(up, up)
    return up


def _ord(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def team_form(team: str) -> dict:
    d = _data()
    key = resolve(team)
    t = d.get("teams", {}).get(key)
    if not t:
        return {"team": team, "abbr": key, "games": 0}
    out = dict(t)
    out["team"] = team
    out["abbr"] = key
    return out


def _tier(rank: int) -> str:
    if rank <= 8:
        return "strong"
    if rank <= 16:
        return "above-average"
    if rank <= 24:
        return "below-average"
    return "soft"


def _adj_run_rank(t: dict) -> int:
    return int(t.get("rush_ypg_adj_rank") or t.get("rush_ypg_rank") or 16)


def _adj_pass_rank(t: dict) -> int:
    return int(t.get("pass_ypg_adj_rank") or t.get("pass_ypg_rank") or 16)


def _sched_tag(t: dict) -> str:
    """Short label for the strength of offenses this team has faced."""
    r = int(t.get("sos_rank") or 16)
    if r <= 8:
        return "tough slate"
    if r >= 25:
        return "soft slate"
    return "avg slate"


def _rawtag(raw_rank: int, adj_rank: int) -> str:
    """Note the raw rank only when the schedule adjustment moves it materially."""
    if abs(int(raw_rank) - int(adj_rank)) >= 4:
        return f", raw {_ord(raw_rank)}"
    return ""


def defense_note(team: str) -> str | None:
    """One-line read of a team's current-season defense, opponent-adjusted: run, pass,
    pressure. Leads with the SoS-adjusted rank (raw shown when the schedule moved it)."""
    t = team_form(team)
    if not t.get("games"):
        return None
    ab = t["abbr"]
    rr, pr = _adj_run_rank(t), _adj_pass_rank(t)
    run_adj = t.get("rush_ypg_allowed_adj", t["rush_ypg_allowed"])
    pass_adj = t.get("pass_ypg_allowed_adj", t["pass_ypg_allowed"])
    return (
        f"{ab} D ({t['games']}g, {_sched_tag(t)}): run {run_adj}/gm adj "
        f"({_ord(rr)}{_rawtag(t['rush_ypg_rank'], rr)}) — {_tier(rr)} vs run; "
        f"pass {pass_adj}/gm adj ({_ord(pr)}{_rawtag(t['pass_ypg_rank'], pr)}) — {_tier(pr)}; "
        f"pressure {int(t['def_sacks'])} sacks ({_ord(t['sack_rank'])})."
    )


def passer_note(team: str) -> str | None:
    """Flag whose passing the current-season form is actually built on -- so a
    returning downfield starter is a visible caveat, not a hidden one."""
    t = team_form(team)
    if not t.get("games") or not t.get("qb1"):
        return None
    adot = t.get("qb1_adot")
    lo = adot is not None and adot <= 6.5  # checkdown-level average depth of target
    tail = " — short-area passer; form understates the offense if a downfield starter returns." if lo else ""
    return (f"{t['abbr']} passing form built on {t['qb1']} "
            f"({t['qb1_att']} att" + (f", {adot} aDOT" if adot is not None else "") + ")" + tail)


def matchup_read(away: str, home: str, spread_home=None, total=None) -> dict:
    """Current-season form read for a game. Returns each side's defense note plus a
    plain-English read of what the form implies for the run games, passing games, and
    total. Small-sample honest: carries the game count and never over-claims."""
    fa, fh = team_form(away), team_form(home)
    read = {
        "away": away, "home": home, "away_form": fa, "home_form": fh,
        "away_def_note": defense_note(away), "home_def_note": defense_note(home),
        "away_qb_note": passer_note(away), "home_qb_note": passer_note(home),
        "note": None, "total_lean": None, "run_reads": [], "pass_reads": [],
    }
    if not fa.get("games") or not fh.get("games"):
        read["note"] = "No 2026 form yet for one side — read off the board."
        return read

    ga, gh = int(fa["games"]), int(fh["games"])
    ha_rr, ha_pr = _adj_run_rank(fa), _adj_pass_rank(fa)
    hh_rr, hh_pr = _adj_run_rank(fh), _adj_pass_rank(fh)
    # run reads: away rushing attack vs home run D, and vice versa (opponent-adjusted)
    read["run_reads"] = [
        f"{fa['abbr']} run game meets {fh['abbr']}'s run D "
        f"({fh.get('rush_ypg_allowed_adj', fh['rush_ypg_allowed'])}/gm adj, {_ord(hh_rr)})",
        f"{fh['abbr']} run game meets {fa['abbr']}'s run D "
        f"({fa.get('rush_ypg_allowed_adj', fa['rush_ypg_allowed'])}/gm adj, {_ord(ha_rr)})",
    ]
    read["pass_reads"] = [
        f"{fa['abbr']} passing vs {fh['abbr']} pass D "
        f"({fh.get('pass_ypg_allowed_adj', fh['pass_ypg_allowed'])}/gm adj, {_ord(hh_pr)})",
        f"{fh['abbr']} passing vs {fa['abbr']} pass D "
        f"({fa.get('pass_ypg_allowed_adj', fa['pass_ypg_allowed'])}/gm adj, {_ord(ha_pr)})",
    ]

    # total lean from where both defenses are strong/soft (opponent-adjusted ranks)
    both_run_strong = ha_rr <= 10 and hh_rr <= 10
    both_pass_soft = ha_pr >= 22 and hh_pr >= 22
    if both_run_strong and not both_pass_soft:
        read["total_lean"] = ("Both run defenses rank top-10 on current form — the ground "
                              "games project to get stuffed, so points have to come through the "
                              "air. Leans the rushing props under; the total rides on passing.")
    elif both_pass_soft and not both_run_strong:
        read["total_lean"] = ("Both pass defenses rank bottom-11 on current form — supports "
                              "the passing markets and the over.")
    elif both_run_strong and both_pass_soft:
        read["total_lean"] = ("Both defenses stuff the run but get thrown on — form points to "
                              "air yards over ground yards, total near coin-flip.")

    read["note"] = (f"2026 form ({fa['abbr']} {ga}g, {fh['abbr']} {gh}g): "
                    + read["away_def_note"] + " || " + read["home_def_note"])
    return read


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        sh = float(sys.argv[3]) if len(sys.argv) > 3 else None
        r = matchup_read(sys.argv[1], sys.argv[2], sh)
        print(json.dumps({k: r[k] for k in ("note", "total_lean", "run_reads", "pass_reads")}, indent=2))
