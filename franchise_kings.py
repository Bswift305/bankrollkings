"""Franchise Kings - GM career simulator engine (football / fictional BRK League).

Pure-Python, JSON-serializable game state. No Flask dependency so it can be unit
-tested from the command line. The web layer (app.py) only calls into here and
renders the returned dicts.

Solo career mode: 1 human GM + 31 AI teams in a 32-team league (2 conferences x
4 divisions x 4). Core loop: create GM -> take a job -> build the roster -> sim
season -> owner evaluation -> retained / extended / fired / poached -> career.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "data" / "franchise"

LEAGUE_SIZE = 32
REG_GAMES = 17
CONF_PLAYOFF_SEEDS = 7   # per conference -> 14-team playoff (NFL-style)
CAP_TOTAL = 350.0        # millions (sized for 53-man rosters; expensive teams run tight)
DRAFT_ROUNDS = 7
DRAFT_CLASS = 240        # prospects (>= rounds * teams)
ROSTER_CAP = 53          # final active roster (the 53-man); camp trims down to it

CONFERENCES = ["American", "National"]
DIVISIONS = ["East", "North", "South", "West"]

# 32 teams in the REAL NFL cities with FICTIONAL mascots (no real team names /
# logos -> no licensing exposure), aligned to the real conference/division map.
# (conference, division, city, mascot, market)  market drives the business layer.
NFL_TEAMS = [
    ("American", "East",  "Buffalo",       "Blizzard",     "Small"),
    ("American", "East",  "Miami",         "Tarpons",      "Large"),
    ("American", "East",  "New England",   "Minutemen",    "Large"),
    ("American", "East",  "New York",      "Empire",       "Large"),
    ("American", "North", "Baltimore",     "Privateers",   "Mid"),
    ("American", "North", "Cincinnati",    "Crimson",      "Small"),
    ("American", "North", "Cleveland",     "Ironworks",    "Mid"),
    ("American", "North", "Pittsburgh",    "Forge",        "Mid"),
    ("American", "South", "Houston",       "Wildcatters",  "Large"),
    ("American", "South", "Indianapolis",  "Racers",       "Mid"),
    ("American", "South", "Jacksonville",  "Surge",        "Small"),
    ("American", "South", "Tennessee",     "Stampede",     "Mid"),
    ("American", "West",  "Denver",        "Summit",       "Mid"),
    ("American", "West",  "Kansas City",   "Drovers",      "Small"),
    ("American", "West",  "Las Vegas",     "Neon",         "Mid"),
    ("American", "West",  "Los Angeles",   "Voltage",      "Large"),
    ("National", "East",  "Dallas",        "Wranglers",    "Large"),
    ("National", "East",  "New York",      "Sentinels",    "Large"),
    ("National", "East",  "Philadelphia",  "Liberty",      "Large"),
    ("National", "East",  "Washington",    "Statesmen",    "Large"),
    ("National", "North", "Chicago",       "Grizzlies",    "Large"),
    ("National", "North", "Detroit",       "Motors",       "Mid"),
    ("National", "North", "Green Bay",     "Lumberjacks",  "Small"),
    ("National", "North", "Minnesota",     "Norse",        "Mid"),
    ("National", "South", "Atlanta",       "Black Hawks",  "Large"),
    ("National", "South", "Carolina",      "Cougars",      "Mid"),
    ("National", "South", "New Orleans",   "Krewe",        "Small"),
    ("National", "South", "Tampa Bay",     "Mariners",     "Mid"),
    ("National", "West",  "Arizona",       "Scorpions",    "Mid"),
    ("National", "West",  "Los Angeles",   "Lights",       "Large"),
    ("National", "West",  "San Francisco", "Fog",          "Large"),
    ("National", "West",  "Seattle",       "Waterbirds",   "Mid"),
]
# A (primary, secondary) colour scheme per club, in NFL_TEAMS order - each evokes
# the real team that plays in that city (no marks used, just colours).
TEAM_COLORS = [
    ("#00338D", "#C60C30"), ("#008E97", "#FC4C02"), ("#002244", "#C60C30"), ("#125740", "#FFFFFF"),
    ("#241773", "#9E7C0C"), ("#FB4F14", "#000000"), ("#311D00", "#FF3C00"), ("#101820", "#FFB612"),
    ("#03202F", "#A71930"), ("#002C5F", "#A2AAAD"), ("#006778", "#D7A22A"), ("#0C2340", "#4B92DB"),
    ("#FB4F14", "#002244"), ("#E31837", "#FFB81C"), ("#0A0A0A", "#A5ACAF"), ("#0080C6", "#FFC20E"),
    ("#003594", "#869397"), ("#0B2265", "#A71930"), ("#004C54", "#A5ACAF"), ("#5A1414", "#FFB612"),
    ("#0B162A", "#C83803"), ("#0076B6", "#B0B7BC"), ("#203731", "#FFB612"), ("#4F2683", "#FFC62F"),
    ("#A71930", "#000000"), ("#0085CA", "#101820"), ("#101820", "#D3BC8D"), ("#D50A0A", "#34302B"),
    ("#97233F", "#000000"), ("#003594", "#FFA300"), ("#AA0000", "#B3995D"), ("#002244", "#69BE28"),
]
_TEAM_META = {f"{c} {m}": {"mascot": m, "primary": pri, "secondary": sec}
              for (cf, dv, c, m, mk), (pri, sec) in zip(NFL_TEAMS, TEAM_COLORS)}


def team_colors(full):
    meta = _TEAM_META.get(full)
    if meta:
        return {"primary": meta["primary"], "secondary": meta["secondary"]}
    h = abs(hash(full))
    return {"primary": f"#{h % 0xFFFFFF:06x}", "secondary": "#cfd8dc"}


def _contrast(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#0a0a0a" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def team_crest_svg(full, size=36):
    """A simple shield crest in the club's colours with the mascot's initial."""
    meta = _TEAM_META.get(full)
    pri = meta["primary"] if meta else "#1b2a36"
    sec = meta["secondary"] if meta else "#4ad4f0"
    initial = (meta["mascot"][0] if meta else (full or "?")[:1]).upper()
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" '
            f'class="fk-crest" style="vertical-align:middle">'
            f'<path d="M20 2L36 8V21C36 30 29 36 20 39C11 36 4 30 4 21V8Z" fill="{pri}" '
            f'stroke="{sec}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<text x="20" y="27" text-anchor="middle" font-size="19" font-weight="800" '
            f'fill="{_contrast(pri)}" font-family="Arial,Helvetica,sans-serif">{initial}</text></svg>')


FIRST_NAMES = [
    "Marcus", "DeShawn", "Tyrell", "Cole", "Brock", "Xavier", "Jaylen", "Trey",
    "Dominic", "Isaiah", "Hunter", "Malik", "Cooper", "Diego", "Andre", "Kade",
    "Roman", "Silas", "Tobias", "Quinton", "Rashad", "Beau", "Khalil", "Jaxon",
    "Emmett", "Darius", "Carter", "Nasir", "Bryce", "Gio", "Lincoln", "Zane",
]
LAST_NAMES = [
    "Reed", "Locke", "Vance", "Mercer", "Hollis", "Bishop", "Cross", "Rhodes",
    "Kane", "Sloan", "Boone", "Hayes", "Dawson", "Foster", "Mata", "Okafor",
    "Vega", "Prince", "Steele", "Calloway", "Drummond", "Fontaine", "Ash", "Roy",
    "Barlow", "Quint", "Vasquez", "Nash", "Wexler", "Pryor", "Salas", "Trent",
]

# Starter slots per position (the depth chart auto-starts the best by position).
ROSTER = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "OL": 5, "DL": 4, "LB": 3, "CB": 3, "S": 2, "K": 1}
# Camp-roster depth per position (~54 players) so the offseason has a real cut to 53.
ROSTER_DEPTH = {"QB": 3, "RB": 5, "WR": 7, "TE": 3, "OL": 10, "DL": 8, "LB": 6, "CB": 6, "S": 4, "K": 2}
# Position weight for the Power Rating (football = QB-heavy, OL/DL count a lot).
POS_WEIGHT = {"QB": 5.0, "WR": 1.5, "OL": 1.3, "DL": 1.4, "CB": 1.3, "LB": 1.1,
              "S": 1.0, "RB": 1.0, "TE": 0.9, "K": 0.4}
# Jersey-number ranges by position (loose NFL convention) for flavor + avatars.
POS_NUM = {"QB": (1, 19), "RB": (20, 49), "WR": (10, 19), "TE": (80, 89), "OL": (50, 79),
           "DL": (90, 99), "LB": (40, 59), "CB": (20, 39), "S": (20, 49), "K": (1, 9)}

BACKGROUNDS = {
    "scout":        {"label": "Scout",            "blurb": "Better draft grades, weaker contracts.",
                     "tilt": {"drafting": +10, "cap": -6}},
    "analytics":    {"label": "Analytics Nerd",   "blurb": "Better projections, players warm slower.",
                     "tilt": {"free_agency": +8, "media": -6}},
    "former_player":{"label": "Former Player",    "blurb": "Locker-room respect, weaker cap skill.",
                     "tilt": {"media": +10, "cap": -8}},
    "cap_expert":   {"label": "Cap Expert",       "blurb": "Better payroll control, weaker scouting.",
                     "tilt": {"cap": +12, "drafting": -6}},
    "coach_gm":     {"label": "Coach-turned-GM",  "blurb": "Better staff hiring, owner eyes the books.",
                     "tilt": {"staff": +10, "owner": -5}},
}
OWNER_TYPES = ["Impatient", "Cheap", "Hands-Off", "Meddling", "Legacy", "Billionaire"]

# Free-agent agents: personality sets how far over market they demand and how
# they counter. "Loyal" gives a hometown discount when your fanbase is happy.
AGENTS = {
    "Reasonable": {"markup": 1.07, "counter": 0.99, "blurb": "Fair - signs at market."},
    "Shrewd":     {"markup": 1.20, "counter": 0.97, "blurb": "Plays hardball, counters high."},
    "Greedy":     {"markup": 1.32, "counter": 0.96, "blurb": "Money over everything."},
    "Loyal":      {"markup": 1.04, "counter": 0.98, "blurb": "Takes a discount for a winner."},
}


def _rng(seed):
    return random.Random(seed)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _gen_name(rng):
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _gen_player(rng, pos, base=None):
    age = rng.randint(21, 34)
    overall = base if base is not None else int(rng.triangular(58, 92, 74))
    overall = max(48, min(99, overall))
    pot_gap = max(0, int(rng.triangular(0, 22, 6)) - (age - 24))
    potential = max(overall, min(99, overall + pot_gap))
    aav = round(max(0.7, max(0, overall - 55) ** 1.7 / 22.0), 1)
    return {
        "id": f"p{rng.randint(100000, 999999)}",
        "name": _gen_name(rng),
        "pos": pos,
        "number": rng.randint(*POS_NUM.get(pos, (1, 99))),
        "age": age,
        "overall": overall,
        "potential": potential,
        "dev": rng.choice(["Normal", "Star", "Slow", "Late Bloomer"]),
        "contract": {"years": rng.randint(1, 4), "aav": aav, "guaranteed": round(aav * rng.uniform(0.3, 0.8), 1)},
        "morale": rng.randint(55, 90),
        "injury_risk": rng.choice(["Low", "Low", "Medium", "High"]),
    }


def _gen_roster(rng, strength):
    """strength 0..1 nudges the talent floor so weak teams feel weak. Builds a full
    ~54-man camp roster: starters are strong, depth tapers off (cuttable bodies)."""
    roster = []
    for pos, count in ROSTER_DEPTH.items():
        starters = ROSTER.get(pos, 1)
        for i in range(count):
            if i < starters:                       # starters: real talent
                base = int(rng.triangular(54, 90, 66 + strength * 14))
            else:                                  # depth tapers down the chart
                taper = 10 + (i - starters) * 4
                base = int(rng.triangular(50, 78, max(52, 70 + strength * 10 - taper)))
            roster.append(_gen_player(rng, pos, base))
    return roster


# Each team opens with a believable mix - 1-3 marquee players at impact spots -
# so rosters feel like a real league at kickoff (the 'based on current players'
# feel), using GENERATED names. All future rookies are fully generated.
_STAR_POS = ["QB", "WR", "DL", "CB", "OL", "LB", "RB"]


def _inject_stars(rng, roster):
    pool = [p for p in roster if p["pos"] in _STAR_POS]
    for p in rng.sample(pool, min(rng.randint(1, 3), len(pool))):
        ov = rng.randint(86, 95)
        p["overall"] = ov
        p["potential"] = min(99, max(ov, p["potential"]))
        p["age"] = rng.randint(24, 30)
        p["contract"]["aav"] = round(max(0.7, max(0, ov - 55) ** 1.7 / 22.0), 1)
        p["contract"]["years"] = rng.randint(2, 5)


def _gen_team(rng, idx, entry):
    conf, div, city, mascot, market = entry
    strength = rng.random()
    roster = _gen_roster(rng, strength)
    _inject_stars(rng, roster)
    return {
        "id": f"t{idx}",
        "city": city,
        "name": mascot,
        "full": f"{city} {mascot}",
        "conference": conf,
        "division": div,
        "market": market,
        "owner": {"type": rng.choice(OWNER_TYPES)},
        "roster": roster,
        "record": {"w": 0, "l": 0},
    }


def _attach_agent(rng, p):
    pers = rng.choice(list(AGENTS))
    p["agent"] = {"name": _gen_name(rng), "personality": pers}
    p["demand"] = {"years": rng.randint(2, 5),
                   "aav": round(p["contract"]["aav"] * AGENTS[pers]["markup"], 1)}
    return p


def _gen_fa_pool(rng, n=40):
    pool = [_gen_player(rng, rng.choice(list(ROSTER)), int(rng.triangular(60, 88, 70))) for _ in range(n)]
    for p in pool:
        _attach_agent(rng, p)
    return pool


def new_league(seed):
    rng = _rng(seed)
    teams = [_gen_team(rng, i, NFL_TEAMS[i]) for i in range(LEAGUE_SIZE)]
    return teams, _gen_fa_pool(rng)


def make_schedule(seed, team_ids):
    rng = _rng(seed + 7)
    games = []
    for week in range(REG_GAMES):
        order = team_ids[:]
        rng.shuffle(order)
        for i in range(0, len(order) - 1, 2):
            games.append({"week": week + 1, "home": order[i], "away": order[i + 1]})
    return games


# --------------------------------------------------------------------------- #
# Ratings + sim
# --------------------------------------------------------------------------- #
def power_rating(team):
    """Weighted average of the BEST starters per position (auto depth chart)."""
    by_pos = {}
    for p in team["roster"]:
        by_pos.setdefault(p["pos"], []).append(p)
    num = den = 0.0
    for pos, slots in ROSTER.items():
        best = sorted(by_pos.get(pos, []), key=lambda x: -x["overall"])[:slots]
        if not best:
            continue
        w = POS_WEIGHT.get(pos, 1.0)
        num += w * (sum(x["overall"] for x in best) / len(best)) * slots
        den += w * slots
    return round(num / den, 1) if den else 60.0


def cap_used(team):
    return round(sum(p["contract"]["aav"] for p in team["roster"]), 1)


def _starters(team):
    by_pos = {}
    for p in team["roster"]:
        by_pos.setdefault(p["pos"], []).append(p)
    out = []
    for pos, slots in ROSTER.items():
        out += sorted(by_pos.get(pos, []), key=lambda x: -x["overall"])[:slots]
    return out


# Dev-trait curves: when a player grows, how fast, and when he declines.
_PEAK = {"Star": 28, "Late Bloomer": 30, "Slow": 27, "Normal": 28}
_RATE = {"Star": 3, "Late Bloomer": 2, "Slow": 1, "Normal": 2}
_DECLINE = {"Star": 31, "Late Bloomer": 32, "Slow": 30, "Normal": 31}


def _develop(p, rng, bonus):
    tr, age = p.get("dev", "Normal"), p["age"]
    if age <= _PEAK.get(tr, 28) and p["overall"] < p["potential"]:
        gain = rng.randint(0, _RATE.get(tr, 2)) + bonus
        if tr == "Late Bloomer" and age >= 25:
            gain += 1
        p["overall"] = min(p["potential"], p["overall"] + gain)
    if age >= _DECLINE.get(tr, 31):
        p["overall"] = max(45, p["overall"] - rng.randint(1, 3))


def _roll_injuries(save, rng):
    """Season injuries for the user team's starters. Medical staff cuts them down."""
    team = current_team(save)
    medical = staff_bonus(save)["medical"]
    med_factor = max(0.4, 1.0 - (medical - 50) / 180.0)   # good medical -> fewer/shorter
    base = {"Low": 0.06, "Medium": 0.12, "High": 0.20}
    out = []
    for p in _starters(team):
        chance = base.get(p.get("injury_risk", "Low"), 0.1) * med_factor + max(0, p["age"] - 29) * 0.01
        if rng.random() < chance:
            weeks = max(2, int(rng.randint(2, 11) * (0.7 + med_factor * 0.3)))
            out.append({"name": p["name"], "pos": p["pos"], "ovr": p["overall"], "weeks": min(weeks, REG_GAMES)})
    return out


def _sim_game(rng, pa, pb):
    diff = (pa + 2.2) - pb  # home edge baked into pa
    p = 1.0 / (1.0 + math.exp(-diff / 6.0))
    return rng.random() < p  # True => home wins


def _run_playoffs(rng, seeds, powers):
    """Single-elim bracket from a seeded list (best first). Top seed gets a bye
    when the field is odd; reseed by original seed each round. Returns winner."""
    teams = seeds[:]
    while len(teams) > 1:
        teams.sort(key=lambda t: seeds.index(t))
        byes, active = [], teams[:]
        if len(active) % 2 == 1:
            byes, active = [active[0]], active[1:]
        winners, i, j = [], 0, len(active) - 1
        while i < j:
            a, b = active[i], active[j]
            winners.append(a if _sim_game(rng, powers[a], powers[b]) else b)
            i += 1
            j -= 1
        teams = byes + winners
    return teams[0]


def sim_season(save):
    """Play the schedule -> conference standings -> 7-seed conference playoffs ->
    title game. Then advance the league a year and evaluate the GM."""
    rng = _rng(save["seed"] + save["season"] * 1000)
    teams = {t["id"]: t for t in save["teams"]}
    for t in save["teams"]:
        t["record"] = {"w": 0, "l": 0}
    powers = {tid: power_rating(t) for tid, t in teams.items()}
    _sb = staff_bonus(save)
    powers[save["current_team_id"]] += _sb["power"] + _sb["scheme"]   # coaching + scheme fit

    injuries = _roll_injuries(save, rng)
    inj_pen = round(sum((i["weeks"] / REG_GAMES) * POS_WEIGHT.get(i["pos"], 1.0) * 1.4 for i in injuries), 1)
    powers[save["current_team_id"]] -= inj_pen   # starters missing time hurts your record
    save["last_injuries"] = injuries
    save["last_injury_pen"] = inj_pen

    for g in save["schedule"]:
        home_win = _sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win]["record"]["w"] += 1
        teams[lose]["record"]["l"] += 1

    assign_season_stats(save["teams"], {tid: tm["record"]["w"] for tid, tm in teams.items()},
                        save["seed"] + save["season"])
    save["leaders"] = stat_leaders(save["teams"])
    save["season_mvp"] = stat_mvp(save["teams"])

    standings = sorted(save["teams"], key=lambda t: (t["record"]["w"], powers[t["id"]]), reverse=True)

    conf_champs, playoff_ids = [], set()
    for conf in CONFERENCES:
        seeds = [t["id"] for t in standings if t["conference"] == conf][:CONF_PLAYOFF_SEEDS]
        playoff_ids.update(seeds)
        conf_champs.append(_run_playoffs(rng, seeds, powers))
    champion = (conf_champs[0] if _sim_game(rng, powers[conf_champs[0]], powers[conf_champs[1]])
                else conf_champs[1])

    user_id = save["current_team_id"]
    rec = dict(teams[user_id]["record"])
    made_playoffs = user_id in playoff_ids
    won_title = champion == user_id
    outcome = _evaluate_gm(save, rec, made_playoffs, won_title, teams[champion]["full"])

    _apply_finance(save, rec, won_title)   # season revenue -> cash, fan happiness update
    _advance_year(save)
    save["season"] += 1
    save["schedule"] = make_schedule(save["seed"], [t["id"] for t in save["teams"]])
    save["standings_cache"] = [
        {"id": t["id"], "full": t["full"], "conf": t["conference"], "div": t["division"],
         "w": t["record"]["w"], "l": t["record"]["l"], "power": powers[t["id"]],
         "playoff": t["id"] in playoff_ids} for t in standings
    ]
    save["last_champion"] = teams[champion]["full"]
    save["last_outcome"] = outcome
    save["unemployed"] = outcome["status"] == "fired"
    _set_expectation(save)
    write_save(save)
    if outcome["status"] == "retained":
        start_draft(save)   # offseason draft opens immediately when you keep your job
    return save, outcome


def _advance_year(save):
    rng = _rng(save["seed"] + save["season"] * 31 + 5)
    dev = staff_bonus(save)["development"] + (1 if _business(save)["facility"] >= 3 else 0)
    uid = save["current_team_id"]
    for t in save["teams"]:
        bonus = dev if t["id"] == uid else 0
        for p in t["roster"]:
            p["age"] += 1
            _develop(p, rng, bonus)   # trait-driven growth / decline
            p["contract"]["years"] = max(0, p["contract"]["years"] - 1)
    save["free_agents"] = _gen_fa_pool(rng)


# --------------------------------------------------------------------------- #
# Owner expectations + career outcomes
# --------------------------------------------------------------------------- #
def _league_rank(save, team_id):
    ranked = sorted(save["teams"], key=lambda t: -power_rating(t))
    return [t["id"] for t in ranked].index(team_id)  # 0 = best


def _set_expectation(save):
    rank = _league_rank(save, save["current_team_id"])
    if rank <= 8:
        save["expectation"] = {"wins": 12, "text": "Win the title - anything less disappoints."}
    elif rank <= 20:
        save["expectation"] = {"wins": 10, "text": "Make the playoffs (10+ wins)."}
    else:
        save["expectation"] = {"wins": 7, "text": "Show progress - 7+ wins."}


def _evaluate_gm(save, rec, made_playoffs, won_title, champion_name):
    gm = save["gm"]
    exp = save["expectation"]["wins"]
    margin = rec["w"] - exp
    delta = 6 + margin * 2 if margin >= 0 else -8 + margin * 2
    if won_title:
        delta += 25
    elif made_playoffs:
        delta += 8
    gm["owner_trust"] = max(0, min(100, gm["owner_trust"] + delta))
    gm["fan_support"] = max(0, min(100, gm["fan_support"] + (rec["w"] - rec["l"]) * 2 + (15 if won_title else 0)))
    gm["reputation"] = max(0, min(100, gm["reputation"] + margin * 2 + (12 if won_title else 0)))

    team = next(t for t in save["teams"] if t["id"] == save["current_team_id"])
    record = {"season": save["season"], "team": team["full"],
              "record": f"{rec['w']}-{rec['l']}", "expectation": exp}

    status, headline, offers = "retained", "", []
    if gm["owner_trust"] < 25:
        status = "fired"
        headline = f"You've been FIRED by the {team['full']} after a {rec['w']}-{rec['l']} season."
        offers = _job_openings(save, want="bad")
    elif won_title or margin >= 3:
        status = "courted"
        headline = (f"Champions! You won the title with the {team['full']}."
                    if won_title else
                    f"Big overachievement ({rec['w']}-{rec['l']}). Rival clubs are calling.")
        offers = _job_openings(save, want="good")
    else:
        status = "retained"
        headline = f"The {team['full']} retain you after a {rec['w']}-{rec['l']} season."

    record["outcome"] = status
    gm.setdefault("career", []).append(record)
    if won_title:
        gm["titles"] = gm.get("titles", 0) + 1
    return {"status": status, "headline": headline, "record": rec,
            "won_title": won_title, "made_playoffs": made_playoffs,
            "champion": champion_name, "offers": offers, "owner_trust": gm["owner_trust"]}


def _job_openings(save, want):
    ranked = sorted(save["teams"], key=lambda t: power_rating(t))
    pool = ranked[:8] if want == "bad" else ranked[-8:]
    pool = [t for t in pool if t["id"] != save["current_team_id"]]
    return [{"id": t["id"], "full": t["full"], "power": power_rating(t), "market": t["market"],
             "owner": t["owner"]["type"]} for t in pool[:3]]


# --------------------------------------------------------------------------- #
# Staff / coaching (user-team) - feeds the sim, draft, and development
# --------------------------------------------------------------------------- #
# You are the GM AND the Head Coach -> no Head Coach hire. You pick your own
# philosophy, then hire coordinators who each carry a philosophy + a scheme.
STAFF_ROLES = [
    ("off_coord", "Offensive Coordinator", "Runs your offense - rating + scheme + philosophy."),
    ("def_coord", "Defensive Coordinator", "Runs your defense - rating + scheme + philosophy."),
    ("head_scout", "Head Scout", "Tightens draft scouting - fewer busts."),
    ("head_medical", "Head of Medical", "Keeps players healthier."),
    ("head_analytics", "Head of Analytics", "Sharper value reads."),
]
_STAFF_BASE = 48  # an unhired slot runs at replacement level

PHILOSOPHIES = {
    "Analytics":  {"label": "Analytics-Driven", "blurb": "Wins the margins - 4th downs, matchups, in-game math."},
    "Old School": {"label": "Old-School",       "blurb": "Toughness, the run game, situational grit."},
    "Balanced":   {"label": "Balanced",         "blurb": "No strong lean - steady and adaptable."},
}
# scheme -> the positions it leans on (roster strength there = scheme fit bonus)
OFF_SCHEMES = {"Air Raid": ["QB", "WR"], "West Coast": ["QB", "WR", "TE"],
               "Power Run": ["OL", "RB"], "Spread": ["QB", "WR", "RB"]}
DEF_SCHEMES = {"4-3 Front": ["DL", "LB"], "3-4 Front": ["LB", "DL"],
               "Cover 3 Zone": ["CB", "S"], "Blitz Heavy": ["DL", "LB", "CB"]}
# A scheme RE-WEIGHTS which positions drive your team. Match the scheme to your
# roster's strengths and you outplay your raw power; mismatch and you waste talent.
OFF_SCHEME_W = {
    "Air Raid":   {"QB": 1.55, "WR": 1.45, "TE": 0.95, "OL": 0.95, "RB": 0.65},
    "West Coast": {"QB": 1.30, "WR": 1.20, "TE": 1.30, "OL": 1.05, "RB": 0.90},
    "Power Run":  {"QB": 0.80, "WR": 0.80, "TE": 1.15, "OL": 1.45, "RB": 1.45},
    "Spread":     {"QB": 1.25, "WR": 1.20, "TE": 0.95, "OL": 1.00, "RB": 1.05},
}
DEF_SCHEME_W = {
    "4-3 Front":    {"DL": 1.45, "LB": 1.15, "CB": 0.95, "S": 0.95},
    "3-4 Front":    {"DL": 1.05, "LB": 1.45, "CB": 0.95, "S": 1.00},
    "Cover 3 Zone": {"DL": 0.90, "LB": 1.00, "CB": 1.45, "S": 1.30},
    "Blitz Heavy":  {"DL": 1.40, "LB": 1.25, "CB": 1.15, "S": 0.85},
}


def _opposed(a, b):
    return {a, b} == {"Analytics", "Old School"}


def _gen_staff(rng, role):
    s = {"id": f"s{rng.randint(100000, 999999)}", "name": _gen_name(rng),
         "role": role, "rating": int(rng.triangular(42, 86, 60))}
    if role in ("off_coord", "def_coord"):
        s["philosophy"] = rng.choice(["Analytics", "Old School", "Balanced"])
        s["system"] = rng.choice(list(OFF_SCHEMES if role == "off_coord" else DEF_SCHEMES))
    return s


def generate_staff_market(rng):
    return {role: [_gen_staff(rng, role) for _ in range(4)] for role, _, _ in STAFF_ROLES}


def _sr(staff, role):
    return staff.get(role, {}).get("rating", _STAFF_BASE)


def scheme_effect(save):
    """How much your OC/DC schemes amplify (or waste) your roster: re-weight every
    position by the scheme, compare to neutral power. Loaded at the scheme's
    positions -> bonus; mismatched roster -> penalty. This is the real lever."""
    s = save.get("staff", {})
    mult = {}
    oc, dc = s.get("off_coord"), s.get("def_coord")
    if oc and oc.get("system") in OFF_SCHEME_W:
        mult.update(OFF_SCHEME_W[oc["system"]])
    if dc and dc.get("system") in DEF_SCHEME_W:
        mult.update(DEF_SCHEME_W[dc["system"]])
    if not mult:
        return 0.0
    team = current_team(save)
    by_pos = {}
    for p in team["roster"]:
        by_pos.setdefault(p["pos"], []).append(p)
    num = den = 0.0
    for pos, slots in ROSTER.items():
        best = sorted(by_pos.get(pos, []), key=lambda x: -x["overall"])[:slots]
        if not best:
            continue
        w = POS_WEIGHT.get(pos, 1.0) * mult.get(pos, 1.0)
        num += w * (sum(x["overall"] for x in best) / len(best)) * slots
        den += w * slots
    schemed = num / den if den else 0.0
    return round((schemed - power_rating(team)) * 1.1, 2)


def coaching_power(save):
    """Coordinator quality + philosophy synergy/friction with your HC philosophy."""
    s = save.get("staff", {})
    hc = save["gm"].get("philosophy", "Balanced")
    base = ((_sr(s, "off_coord") + _sr(s, "def_coord")) / 2.0 - 50) * 0.10
    syn = 0.0
    for role in ("off_coord", "def_coord"):
        c = s.get(role)
        if not c:
            continue
        cp = c.get("philosophy", "Balanced")
        if cp == hc and hc != "Balanced":
            syn += 1.2
        elif _opposed(cp, hc):
            syn -= 1.5
    edge = 0.8 if hc in ("Analytics", "Old School") else 0.0
    return round(base + syn + edge, 2)


def staff_bonus(save):
    s = save.get("staff", {})
    coord_avg = (_sr(s, "off_coord") + _sr(s, "def_coord")) / 2.0
    return {
        "power": coaching_power(save),
        "scheme": scheme_effect(save),
        "scouting": round((_sr(s, "head_scout") - 50) * 0.6, 1),
        "development": 1 if coord_avg >= 65 else 0,
        "medical": _sr(s, "head_medical"),
        "analytics": _sr(s, "head_analytics"),
    }


def hire_staff(save, role, candidate_id):
    market = save.setdefault("staff_market", {})
    cand = next((c for c in market.get(role, []) if c["id"] == candidate_id), None)
    if not cand:
        return False, "That candidate is no longer available."
    cost = staff_cost(cand["rating"])
    b = _business(save)
    if b["cash"] < cost:
        return False, f"Hiring {cand['name']} costs ${cost}M - you have ${b['cash']}M."
    b["cash"] = round(b["cash"] - cost, 1)
    entry = {"name": cand["name"], "rating": cand["rating"]}
    if "philosophy" in cand:
        entry["philosophy"] = cand["philosophy"]
    if "system" in cand:
        entry["system"] = cand["system"]
    save.setdefault("staff", {})[role] = entry
    market[role] = [c for c in market.get(role, []) if c["id"] != candidate_id]
    write_save(save)
    return True, f"Hired {cand['name']} ({cand['rating']} OVR) for ${cost}M."


def fire_staff(save, role):
    save.get("staff", {}).pop(role, None)
    write_save(save)
    return True


# --------------------------------------------------------------------------- #
# Rookie draft + scouting
# --------------------------------------------------------------------------- #
def _gen_prospect(rng, pos):
    true_ovr = max(50, min(90, int(rng.triangular(52, 86, 64))))
    true_pot = min(99, true_ovr + int(rng.triangular(2, 26, 12)))
    return {"id": f"d{rng.randint(100000, 999999)}", "name": _gen_name(rng), "pos": pos,
            "age": rng.randint(21, 23), "true_ovr": true_ovr, "true_pot": true_pot,
            "dev": rng.choice(["Normal", "Normal", "Star", "Slow", "Late Bloomer"])}


def generate_draft_class(rng):
    weighted = []
    for pos, cnt in ROSTER.items():
        weighted += [pos] * (cnt + 1)
    return [_gen_prospect(rng, rng.choice(weighted)) for _ in range(DRAFT_CLASS)]


def _scout(rng, p, accuracy):
    # accuracy 20..90 (GM drafting rating; staff scouts feed this later). Higher
    # accuracy -> the displayed grade sits closer to the hidden true rating.
    sd = max(1.0, (100 - accuracy) / 8.5)
    p["grade"] = max(40, min(99, int(round(p["true_ovr"] + rng.gauss(0, sd)))))
    p["pot_grade"] = max(p["grade"], min(99, int(round(p["true_pot"] + rng.gauss(0, sd)))))
    return p


def _make_rookie(p):
    aav = round(max(0.7, max(0, p["true_ovr"] - 55) ** 1.6 / 26.0), 1)
    return {"id": "p" + p["id"][1:], "name": p["name"], "pos": p["pos"], "age": p["age"],
            "number": random.randint(*POS_NUM.get(p["pos"], (1, 99))),
            "overall": p["true_ovr"], "potential": p["true_pot"], "dev": p["dev"],
            "contract": {"years": 4, "aav": aav, "guaranteed": round(aav * 0.6, 1)},
            "morale": 75, "injury_risk": "Low"}


def start_draft(save):
    if save.get("draft_pending"):
        return
    rng = _rng(save["seed"] + save["season"] * 77 + 13)
    cls = generate_draft_class(rng)
    acc = max(20, min(92, save["gm"]["ratings"].get("drafting", 50) + staff_bonus(save)["scouting"]))
    for p in cls:
        _scout(rng, p, acc)
    save["staff_market"] = generate_staff_market(rng)   # fresh candidates each offseason
    order = [s["id"] for s in reversed(save.get("standings_cache", []))] or [t["id"] for t in save["teams"]]
    save["draft"] = {"class": cls, "order": order, "rounds": DRAFT_ROUNDS, "ptr": 0, "user_log": []}
    save["draft_pending"] = True
    _draft_advance(save)
    write_save(save)


def _draft_on_clock(draft):
    if draft["ptr"] >= draft["rounds"] * len(draft["order"]):
        return None
    return draft["order"][draft["ptr"] % len(draft["order"])]


def _draft_round_pick(draft):
    n = len(draft["order"])
    return draft["ptr"] // n + 1, draft["ptr"] % n + 1


def _available(draft):
    return sorted(draft["class"], key=lambda p: -p["grade"])


def _ai_pick(save, draft):
    tid = _draft_on_clock(draft)
    team = next(t for t in save["teams"] if t["id"] == tid)
    avail = _available(draft)
    if avail:
        pick = avail[0]
        team["roster"].append(_make_rookie(pick))
        draft["class"] = [p for p in draft["class"] if p["id"] != pick["id"]]
    draft["ptr"] += 1


def _draft_advance(save):
    draft = save["draft"]
    while True:
        oc = _draft_on_clock(draft)
        if oc is None:
            _finalize_draft(save)
            return
        if oc == save["current_team_id"]:
            return
        _ai_pick(save, draft)


def draft_make_pick(save, prospect_id):
    draft = save.get("draft")
    if not draft or _draft_on_clock(draft) != save["current_team_id"]:
        return False, "Not on the clock."
    pick = next((p for p in draft["class"] if p["id"] == prospect_id), None)
    if not pick:
        return False, "That prospect is already gone."
    rnd, _ = _draft_round_pick(draft)
    current_team(save)["roster"].append(_make_rookie(pick))
    draft["class"] = [p for p in draft["class"] if p["id"] != pick["id"]]
    draft["user_log"].append({"round": rnd, "name": pick["name"], "pos": pick["pos"],
                              "grade": pick["grade"], "ovr": pick["true_ovr"]})
    draft["ptr"] += 1
    _draft_advance(save)
    write_save(save)
    return True, f"Drafted {pick['name']} ({pick['pos']})."


def _finalize_draft(save):
    # During the staged offseason the Cuts stage trims to 53 - don't auto-cut here.
    if not save.get("offseason"):
        for t in save["teams"]:
            t["roster"].sort(key=lambda p: -p["overall"])
            del t["roster"][ROSTER_CAP:]
    save["draft_pending"] = False
    save["last_draft_log"] = save.get("draft", {}).get("user_log", [])
    save.pop("draft", None)


def draft_state(save):
    draft = save.get("draft")
    if not draft:
        return None
    rnd, pk = _draft_round_pick(draft)
    return {"round": rnd, "pick": pk, "rounds": draft["rounds"],
            "on_clock": _draft_on_clock(draft) == save["current_team_id"],
            "available": _available(draft)[:60], "log": draft["user_log"]}


# --------------------------------------------------------------------------- #
# Save state + actions
# --------------------------------------------------------------------------- #
def _save_path(user_id):
    return SAVE_DIR / f"{user_id}.json"


def has_save(user_id):
    return _save_path(user_id).exists()


def load_save(user_id):
    p = _save_path(user_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_save(save):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    _save_path(save["user_id"]).write_text(json.dumps(save), encoding="utf-8")


def create_save(user_id, gm_name, background, philosophy="Balanced", seed=None):
    background = background if background in BACKGROUNDS else "scout"
    philosophy = philosophy if philosophy in PHILOSOPHIES else "Balanced"
    seed = seed if seed is not None else random.randint(1, 10 ** 9)
    teams, free_agents = new_league(seed)
    weak = sorted(teams, key=lambda t: power_rating(t))[6]  # a bottom-third rebuild
    ratings = {k: 50 for k in ("drafting", "trading", "free_agency", "cap", "staff", "media", "owner")}
    for stat, d in BACKGROUNDS[background]["tilt"].items():
        ratings[stat] = max(20, min(90, ratings[stat] + d))
    save = {
        "version": "0.2",
        "user_id": user_id,
        "seed": seed,
        "season": 1,
        "current_team_id": weak["id"],
        "teams": teams,
        "free_agents": free_agents,
        "schedule": make_schedule(seed, [t["id"] for t in teams]),
        "gm": {
            "name": (gm_name or "GM").strip()[:40],
            "background": background,
            "philosophy": philosophy,
            "ratings": ratings,
            "owner_trust": 55, "fan_support": 50, "reputation": 50,
            "titles": 0, "career": [], "assist": "Full",
        },
        "standings_cache": [],
        "last_champion": "",
        "staff": {},
        "staff_market": generate_staff_market(_rng(seed + 999)),
        "business": {"cash": 40.0, "fan_happiness": 50, "stadium": 1, "facility": 1, "ticket": "normal"},
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    _set_expectation(save)
    write_save(save)
    return save


def current_team(save):
    return next(t for t in save["teams"] if t["id"] == save["current_team_id"])


def sign_free_agent(save, player_id):
    team = current_team(save)
    fa = next((p for p in save["free_agents"] if p["id"] == player_id), None)
    if not fa:
        return False, "That player is no longer available."
    if cap_used(team) + fa["contract"]["aav"] > CAP_TOTAL:
        return False, "Not enough cap space for that contract."
    team["roster"].append(fa)
    save["free_agents"] = [p for p in save["free_agents"] if p["id"] != player_id]
    write_save(save)
    return True, f"Signed {fa['name']} ({fa['pos']}, {fa['overall']} OVR)."


def negotiate(save, player_id, years, aav):
    """Make a contract offer to a free agent's agent. Returns accepted / countered
    / rejected with the agent's response. Loyal agents discount for a happy club."""
    team = current_team(save)
    fa = next((p for p in save.get("free_agents", []) if p["id"] == player_id), None)
    if not fa:
        res = {"ok": False, "msg": "That free agent already signed elsewhere."}
        save["last_nego"] = res
        write_save(save)
        return res
    pers = fa.get("agent", {}).get("personality", "Reasonable")
    agent_name = fa.get("agent", {}).get("name", "The agent")
    A = AGENTS.get(pers, AGENTS["Reasonable"])
    demand_aav = fa.get("demand", {}).get("aav", fa["contract"]["aav"])
    try:
        years = max(1, min(6, int(years)))
        aav = round(float(aav), 1)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Enter a valid offer."}

    eff = demand_aav
    if pers == "Loyal":
        eff = round(demand_aav * (1 - min(0.12, _business(save)["fan_happiness"] / 900.0)), 1)

    res = {"ok": True, "id": fa["id"], "player": fa["name"], "pos": fa["pos"], "ovr": fa["overall"],
           "agent": fa["agent"], "demand": demand_aav, "offer": {"years": years, "aav": aav}}
    if cap_used(team) + aav > CAP_TOTAL:
        res.update(status="rejected", msg=f"That ${aav}M deal puts you over the cap.")
    elif aav >= eff:
        fa["contract"] = {"years": years, "aav": aav, "guaranteed": round(aav * 0.5, 1)}
        fa.pop("agent", None)
        fa.pop("demand", None)
        team["roster"].append(fa)
        save["free_agents"] = [p for p in save["free_agents"] if p["id"] != player_id]
        res.update(status="accepted", msg=f"Done. {res['player']} signs {years}yr / ${aav}M.")
    elif aav >= eff * 0.90:
        counter = round(eff * A["counter"], 1)
        res.update(status="countered", counter={"years": years, "aav": counter},
                   msg=f"{agent_name}: \"{res['player']} signs {years}yr at ${counter}M - meet us there.\"")
    else:
        res.update(status="rejected", msg=f"{agent_name} scoffs - {res['player']} wants about ${eff}M/yr.")
    save["last_nego"] = res
    write_save(save)
    return res


def take_job(save, team_id):
    if team_id not in [t["id"] for t in save["teams"]]:
        return False
    save["current_team_id"] = team_id
    save["gm"]["owner_trust"] = 50
    save["unemployed"] = False
    save["last_outcome"] = None
    _set_expectation(save)
    write_save(save)
    start_draft(save)   # the offseason draft opens for your new club
    return True


def delete_save(user_id):
    p = _save_path(user_id)
    if p.exists():
        p.unlink()


# --------------------------------------------------------------------------- #
# Value Intelligence (the Bankroll Kings analytics layer)
# --------------------------------------------------------------------------- #
def expected_aav(overall):
    return round(max(0.7, max(0, overall - 55) ** 1.7 / 22.0), 1)


def contract_grade(p):
    """How good is this contract? Ratio = fair price / actual price. >1 = bargain."""
    exp, act = expected_aav(p["overall"]), p["contract"]["aav"]
    ratio = exp / act if act > 0 else 9.0
    g = ("A" if ratio >= 1.4 else "B" if ratio >= 1.12 else
         "C" if ratio >= 0.9 else "D" if ratio >= 0.7 else "F")
    return g, round(ratio, 2)


def player_roi(p):
    return round(trade_value(p) / max(0.5, p["contract"]["aav"]), 1)


def analytics(save):
    team = current_team(save)
    powers = [power_rating(t) for t in save["teams"]]
    avg = sum(powers) / len(powers)
    my = power_rating(team) + staff_bonus(save)["power"]
    wp = 1.0 / (1.0 + math.exp(-(my - avg) / 6.0))
    proj_wins = round(REG_GAMES * wp, 1)
    playoff_odds = max(2, min(98, round((proj_wins - 9.0) / 4.0 * 45 + 50)))
    cap = cap_used(team)
    starter_value = round(sum(trade_value(p) for p in _starters(team)), 1)

    rated = []
    for p in team["roster"]:
        g, ratio = contract_grade(p)
        rated.append({"name": p["name"], "pos": p["pos"], "ovr": p["overall"],
                      "aav": p["contract"]["aav"], "grade": g, "ratio": ratio, "roi": player_roi(p)})
    best = sorted([r for r in rated if r["ovr"] >= 68], key=lambda r: -r["roi"])[:6]
    overpays = sorted([r for r in rated if r["aav"] >= 3], key=lambda r: r["ratio"])[:6]
    return {"power": round(my, 1), "league_avg": round(avg, 1), "proj_wins": proj_wins,
            "playoff_odds": playoff_odds, "cap_used": cap, "cap_total": CAP_TOTAL,
            "starter_value": starter_value, "cap_eff": round(starter_value / max(1.0, cap), 2),
            "best": best, "overpays": overpays}


# --------------------------------------------------------------------------- #
# Business / stadium / budget - revenue funds staff + facility investment
# --------------------------------------------------------------------------- #
MARKET_MULT = {"Small": 0.85, "Mid": 1.0, "Large": 1.3}
# ticket level -> (attendance mult, fan-happiness delta/season, price-per-seat mult)
TICKET = {"low": (1.12, 1, 0.84), "normal": (1.0, 0, 1.0), "high": (0.9, -3, 1.18)}


def _business(save):
    b = save.setdefault("business", {})
    b.setdefault("cash", 40.0)
    b.setdefault("fan_happiness", 50)
    b.setdefault("stadium", 1)
    b.setdefault("facility", 1)
    b.setdefault("ticket", "normal")
    return b


def projected_revenue(save):
    b = _business(save)
    mm = MARKET_MULT.get(current_team(save)["market"], 1.0)
    attend = 0.55 + b["fan_happiness"] / 220.0
    am, _, pm = TICKET.get(b["ticket"], TICKET["normal"])
    return round((22 + b["stadium"] * 7) * mm * attend * am * pm, 1)


def stadium_cost(save):
    return round(_business(save)["stadium"] * 28.0, 1)


def facility_cost(save):
    return round(_business(save)["facility"] * 20.0, 1)


def staff_cost(rating):
    return round(rating * 0.12, 1)


def _apply_finance(save, rec, won_title):
    b = _business(save)
    rev = projected_revenue(save)
    b["cash"] = round(b["cash"] + rev, 1)
    _, hd, _ = TICKET.get(b["ticket"], TICKET["normal"])
    b["fan_happiness"] = max(0, min(100, b["fan_happiness"] + (rec["w"] - rec["l"]) * 1.5 + (10 if won_title else 0) + hd))
    b["last_revenue"] = rev


def upgrade_stadium(save):
    b = _business(save)
    if b["stadium"] >= 5:
        return False, "Stadium is already at the max level."
    c = stadium_cost(save)
    if b["cash"] < c:
        return False, f"A stadium upgrade costs ${c}M - you have ${b['cash']}M."
    b["cash"] = round(b["cash"] - c, 1)
    b["stadium"] += 1
    write_save(save)
    return True, f"Stadium upgraded to Level {b['stadium']} (more seats, more revenue)."


def upgrade_facility(save):
    b = _business(save)
    if b["facility"] >= 5:
        return False, "Training facility is already at the max level."
    c = facility_cost(save)
    if b["cash"] < c:
        return False, f"A facility upgrade costs ${c}M - you have ${b['cash']}M."
    b["cash"] = round(b["cash"] - c, 1)
    b["facility"] += 1
    write_save(save)
    return True, f"Training facility upgraded to Level {b['facility']} (faster development)."


def set_ticket(save, level):
    if level in TICKET:
        _business(save)["ticket"] = level
        write_save(save)
    return True


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def stadium_svg(business, team_full=""):
    """A parametric SVG stadium that GROWS with the stadium level: more decks, a
    fuller crowd (by fan happiness), light towers (L3+) and a roof canopy (L5)."""
    lvl = int(business.get("stadium", 1))
    happy = int(business.get("fan_happiness", 50))
    cap = 28 + lvl * 13                              # ~thousands of seats
    glow = max(0.28, min(1.0, happy / 100.0))        # crowd brightness
    decks = 1 + (1 if lvl >= 2 else 0) + (1 if lvl >= 4 else 0)
    p = ['<svg viewBox="0 0 400 210" xmlns="http://www.w3.org/2000/svg" class="fk-stadium" '
         'preserveAspectRatio="xMidYMid meet">',
         '<defs><linearGradient id="fksky" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" stop-color="#0a1a24"/><stop offset="1" stop-color="#050d13"/></linearGradient>'
         '<radialGradient id="fkfield" cx="0.5" cy="0.4" r="0.7">'
         '<stop offset="0" stop-color="#1f8a4c"/><stop offset="1" stop-color="#114f28"/></radialGradient></defs>',
         '<rect width="400" height="210" fill="url(#fksky)"/>']
    if lvl >= 5:
        p.append('<path d="M28 78 Q200 26 372 78" fill="none" stroke="#2a4250" stroke-width="9" opacity="0.9"/>')
    if lvl >= 3:
        for x in (38, 362):
            p.append(f'<rect x="{x-2}" y="44" width="4" height="66" fill="#37505c"/>'
                     f'<rect x="{x-13}" y="38" width="26" height="13" rx="2" fill="#16323d"/>')
            for i in range(3):
                p.append(f'<circle cx="{x-8+i*8}" cy="44" r="2.6" fill="#bdf0ff" opacity="{glow:.2f}"/>')
    base_y = 168
    for d in range(decks):
        top = base_y - 26 - d * 24
        bot = top + 22
        inset = 64 - d * 15
        p.append(f'<polygon points="{44+inset},{top} {356-inset},{top} {356-inset+9},{bot} {44+inset-9},{bot}" '
                 f'fill="#15303b" stroke="#264e5d" stroke-width="1"/>')
        cols = max(7, 20 - d * 3)
        x0, x1 = 54 + inset, 346 - inset
        for r in range(2):
            cy = top + 6 + r * 9
            for c in range(cols):
                cx = x0 + (x1 - x0) * c / (cols - 1)
                col = "#7fe8ff" if (c + r) % 3 == 0 else "#d4e6ee"
                p.append(f'<circle cx="{cx:.0f}" cy="{cy}" r="1.4" fill="{col}" opacity="{glow:.2f}"/>')
    p.append('<ellipse cx="200" cy="180" rx="120" ry="24" fill="url(#fkfield)"/>')
    for i in range(1, 6):
        lx = 122 + i * 26
        p.append(f'<line x1="{lx}" y1="164" x2="{lx}" y2="196" stroke="#fff" stroke-width="1" opacity="0.45"/>')
    p.append('<rect x="148" y="50" width="104" height="26" rx="4" fill="#02181f" stroke="#2a6072"/>')
    p.append(f'<text x="200" y="62" text-anchor="middle" fill="#7fe8ff" font-family="monospace" font-size="8.5">'
             f'{_xml((team_full or "BRK LEAGUE")[:20].upper())}</text>')
    p.append(f'<text x="200" y="72" text-anchor="middle" fill="#cfe8f0" font-family="monospace" font-size="7">'
             f'LVL {lvl}/5 · ~{cap}k SEATS</text>')
    p.append('</svg>')
    return "".join(p)


# --------------------------------------------------------------------------- #
# The GM's personal consultant: reads the roster/cap/contracts and suggests the
# highest-leverage moves. The GM can dial it Off / Light / Full - the brag is
# winning it all with it switched OFF.
# --------------------------------------------------------------------------- #
ASSIST_LEVELS = {"Off": 0, "Light": 2, "Full": 5}


def set_assist(save, level):
    if level in ASSIST_LEVELS:
        save["gm"]["assist"] = level
        write_save(save)
    return True


def _expected_aav(overall):
    return round(max(0.7, max(0, overall - 55) ** 1.7 / 22.0), 1)


def consultant_advice(save):
    """A prioritized list of suggestions (most urgent first), independent of the
    assist level (the level just controls how many the UI reveals)."""
    team = current_team(save)
    tips = []
    best_at = {}
    for p in team["roster"]:
        best_at[p["pos"]] = max(best_at.get(p["pos"], 0), p["overall"])
    weak = min(ROSTER, key=lambda pos: best_at.get(pos, 0))
    tips.append({"icon": "🎯", "title": f"Upgrade your {weak}",
                 "detail": f"Your best {weak} is {best_at.get(weak, 0)} OVR - the softest spot in your starting lineup. Target it in free agency or the draft.",
                 "u": 3})

    expiring = [p for p in team["roster"] if p["overall"] >= 80
                and p.get("contract", {}).get("years", 9) <= 1]
    if expiring:
        s = max(expiring, key=lambda p: p["overall"])
        tips.append({"icon": "✍", "title": f"Extend {s['pos']} {s['name']}",
                     "detail": f"An {s['overall']}-OVR starter on an expiring deal. Lock him up before he hits the market.",
                     "u": 3})

    overpaid = [p for p in team["roster"]
                if p.get("contract", {}).get("aav", 0) > _expected_aav(p["overall"]) * 1.6
                and p.get("contract", {}).get("aav", 0) >= 5]
    if overpaid:
        o = max(overpaid, key=lambda p: p["contract"]["aav"])
        tips.append({"icon": "📉", "title": f"{o['pos']} {o['name']} is overpaid",
                     "detail": f"${o['contract']['aav']:.0f}M for a {o['overall']} OVR. Shop him or move on to free up cap.",
                     "u": 2})

    room = round(CAP_TOTAL - cap_used(team), 1)
    if room > 40:
        tips.append({"icon": "💰", "title": "You're sitting on cap space",
                     "detail": f"~${room:.0f}M free. Aggressively pursue a free agent or extend your young core now.",
                     "u": 1})
    elif room < 5:
        tips.append({"icon": "⚠", "title": "Cap is nearly maxed",
                     "detail": f"Only ~${room:.0f}M of room. Clear a contract before you add anyone.",
                     "u": 2})

    young = [p for p in team["roster"] if p.get("age", 30) <= 23
             and p.get("potential", 0) - p["overall"] >= 8]
    if young:
        y = max(young, key=lambda p: p.get("potential", 0) - p["overall"])
        tips.append({"icon": "📈", "title": f"Develop {y['pos']} {y['name']}",
                     "detail": f"{y['overall']} OVR with {y.get('potential', 0)} upside. A better facility + snaps and he takes off.",
                     "u": 1})

    if save.get("last_injuries"):
        i = save["last_injuries"][0]
        tips.append({"icon": "🏥", "title": f"Cover for {i['pos']} {i['name']}",
                     "detail": f"Out ~{i['weeks']} weeks. Make sure you've got depth behind him.",
                     "u": 2})

    if save.get("draft_pending"):
        tips.append({"icon": "🎓", "title": "You're on the clock",
                     "detail": "Best player available beats reaching for need - the value compounds.",
                     "u": 3})

    tips.sort(key=lambda t: -t["u"])
    return tips


# --------------------------------------------------------------------------- #
# Player STATISTICS. The sim resolves games on power ratings, so we synthesize
# believable season stat lines from each starter's overall + role + how good his
# team's offense/defense was. Drives leaderboards, a stat-based MVP, and roster
# stat lines - turning ratings into a living league.
# --------------------------------------------------------------------------- #
def assign_season_stats(teams, wins_by_id, seed):
    rng = _rng(seed * 7 + 3)
    for t in teams:
        wins = wins_by_id.get(t["id"], REG_GAMES // 2)
        off = 0.78 + (wins / REG_GAMES) * 0.5
        deff = 0.85 + ((REG_GAMES - wins) / REG_GAMES) * 0.35
        by_pos = {}
        for p in t["roster"]:
            p["stats"] = {}
            by_pos.setdefault(p["pos"], []).append(p)
        for pos in by_pos:
            by_pos[pos].sort(key=lambda x: -x["overall"])

        for i, qb in enumerate(by_pos.get("QB", [])[:2]):
            share = 1.0 if i == 0 else 0.08
            if i and rng.random() > 0.3:
                continue
            o = qb["overall"]
            att = int((33 + (o - 70) * 0.25) * REG_GAMES * off * share)
            if att < 20:
                continue
            comp = int(att * min(0.72, 0.55 + (o - 55) * 0.0035))
            yd = int(comp * (7.2 + (o - 60) * 0.05) * off)
            qb["stats"] = {"g": REG_GAMES, "pass_cmp": comp, "pass_att": att, "pass_yd": yd,
                           "pass_td": max(1, int(yd / 140 * off)),
                           "int": max(2, int(att * 0.017 * (1.25 - (o - 60) * 0.005)))}

        for rb, sh in zip(by_pos.get("RB", [])[:3], (0.66, 0.24, 0.10)):
            o = rb["overall"]
            car = int((360 + (o - 70) * 3.5) * off * sh)
            if car < 15:
                continue
            yd = int(car * (4.4 + (o - 65) * 0.03))
            rec = int((35 + (o - 65) * 0.6) * sh * off)
            rb["stats"] = {"g": REG_GAMES, "rush_car": car, "rush_yd": yd,
                           "rush_td": max(0, int(yd / 108 * off)), "rec": rec,
                           "rec_yd": int(rec * 7.6), "rec_td": max(0, int(rec * 7.6 / 200))}

        catchers = sorted(by_pos.get("WR", [])[:4] + by_pos.get("TE", [])[:2],
                          key=lambda x: -x["overall"])
        rec_pool = int(400 * off)                       # team receptions split among WR/TE
        for c, sh in zip(catchers, (0.27, 0.20, 0.13, 0.09, 0.14, 0.07)):
            o = c["overall"]
            rec = int(rec_pool * sh * (0.8 + (o - 65) * 0.007))
            if rec < 8:
                continue
            yd = int(rec * (11.5 + (o - 65) * 0.12))
            c["stats"] = {"g": REG_GAMES, "rec": rec, "rec_yd": yd, "rec_td": max(0, int(yd / 145 * off))}

        for r in by_pos.get("DL", [])[:4] + by_pos.get("LB", [])[:2]:
            o = r["overall"]
            r["stats"] = {"g": REG_GAMES, "tackle": int((30 + (o - 60) * 1.3) * deff),
                          "sack": round(max(0.0, 2.5 + (o - 65) * 0.34) * deff * (0.8 + rng.random() * 0.5), 1)}
        for d in by_pos.get("LB", [])[:4] + by_pos.get("S", [])[:2]:
            if d.get("stats"):
                continue
            o = d["overall"]
            d["stats"] = {"g": REG_GAMES, "tackle": int((55 + (o - 60) * 1.4) * deff),
                          "def_int": max(0, int((o - 68) * 0.3))}
        for d in by_pos.get("CB", [])[:3]:
            o = d["overall"]
            d["stats"] = {"g": REG_GAMES, "tackle": int((40 + (o - 60) * 0.8) * deff),
                          "def_int": max(0, int((o - 66) * 0.32)), "pd": int(6 + (o - 65) * 0.2)}
        for k in by_pos.get("K", [])[:1]:
            o = k["overall"]
            fgm = int((20 + (o - 70) * 0.5) * off)
            k["stats"] = {"g": REG_GAMES, "fgm": fgm, "fga": fgm + rng.randint(2, 6),
                          "pts": fgm * 3 + int(30 * off)}


_LEADER_CATS = [
    ("Passing Yards", "pass_yd"), ("Passing TDs", "pass_td"),
    ("Rushing Yards", "rush_yd"), ("Rushing TDs", "rush_td"),
    ("Receiving Yards", "rec_yd"), ("Receptions", "rec"),
    ("Sacks", "sack"), ("Interceptions", "def_int"),
]


def stat_leaders(teams, n=5):
    pool = [(p, t["full"]) for t in teams for p in t["roster"] if p.get("stats")]
    out = []
    for label, key in _LEADER_CATS:
        items = sorted([(p, tm) for p, tm in pool if p["stats"].get(key)],
                       key=lambda x: -x[0]["stats"][key])[:n]
        out.append({"label": label, "key": key,
                    "rows": [{"name": p["name"], "pos": p["pos"], "team": tm,
                              "val": p["stats"][key]} for p, tm in items]})
    return [c for c in out if c["rows"]]


def stat_mvp(teams):
    best, score = None, -1
    for t in teams:
        for p in t["roster"]:
            s = p.get("stats") or {}
            v = (s.get("pass_yd", 0) * 0.04 + s.get("pass_td", 0) * 4 - s.get("int", 0) * 2
                 + s.get("rush_yd", 0) * 0.05 + s.get("rush_td", 0) * 6
                 + s.get("rec_yd", 0) * 0.05 + s.get("rec_td", 0) * 6)
            if v > score:
                best, score = {"name": p["name"], "pos": p["pos"], "team": t["full"],
                               "ovr": p["overall"], "line": stat_line(p)}, v
    return best


def stat_line(p):
    s = p.get("stats") or {}
    if s.get("pass_yd"):
        return f"{s['pass_yd']:,} yd, {s['pass_td']} TD, {s['int']} INT"
    if s.get("rush_yd"):
        return f"{s['rush_yd']:,} rush yd, {s['rush_td']} TD"
    if s.get("rec_yd"):
        return f"{s['rec']} rec, {s['rec_yd']:,} yd, {s['rec_td']} TD"
    if s.get("sack"):
        return f"{s['sack']} sacks, {s['tackle']} tkl"
    if s.get("def_int") is not None and (s.get("def_int") or s.get("pd")):
        return f"{s.get('def_int', 0)} INT, {s.get('tackle', 0)} tkl"
    if s.get("fgm"):
        return f"{s['fgm']}/{s['fga']} FG, {s['pts']} pts"
    return ""


def rename_player(save, player_id, new_name):
    nm = str(new_name or "").strip()[:40]
    if not nm:
        return False
    for pl in current_team(save)["roster"]:
        if pl["id"] == player_id:
            pl["name"] = nm
            write_save(save)
            return True
    return False


# --------------------------------------------------------------------------- #
# Trades (player-for-player) + the "is this fair?" grade
# --------------------------------------------------------------------------- #
def trade_value(p):
    """A single trade-value number: rewards overall + youth/upside, dings age and
    contract cost. This is the Bankroll Kings 'player value' lens."""
    ov, age, pot = p["overall"], p["age"], p["potential"]
    base = max(1, ov - 50) ** 2 / 10.0
    youth = max(0, 27 - age) * (max(0, pot - ov) * 0.12 + 0.8)
    cost = p["contract"]["aav"] * 0.4
    return round(max(0.5, base + youth - cost), 1)


def _grade(ratio):
    return ("A" if ratio >= 1.15 else "B" if ratio >= 1.05 else
            "C" if ratio >= 0.95 else "D" if ratio >= 0.85 else "F")


def propose_trade(save, give_id, get_id):
    user = current_team(save)
    give = next((p for p in user["roster"] if p["id"] == give_id), None)
    target = get = None
    for t in save["teams"]:
        if t["id"] == save["current_team_id"]:
            continue
        match = next((p for p in t["roster"] if p["id"] == get_id), None)
        if match:
            target, get = t, match
            break
    if not give or not get:
        result = {"ok": False, "msg": "Pick a player to give and a player to get."}
        save["last_trade"] = result
        write_save(save)
        return result

    vg, vr = trade_value(give), trade_value(get)
    ratio = vr / vg if vg > 0 else 99.0          # value you GET vs value you GIVE
    grade = _grade(ratio)
    # deterministic per pairing (no save-scum); AI accepts a fair-or-better deal
    seed = save["seed"] + sum(ord(c) for c in (give_id + get_id))
    tol = 0.90 - _rng(seed).uniform(0, 0.06)   # accept fair-or-slightly-light offers, reject steals
    accepts = vg >= vr * tol

    result = {"ok": True, "grade": grade, "team": target["full"],
              "give": {"name": give["name"], "pos": give["pos"], "ovr": give["overall"], "val": vg},
              "get": {"name": get["name"], "pos": get["pos"], "ovr": get["overall"], "val": vr}}
    if not accepts:
        result["accepted"] = False
        result["msg"] = f"{target['full']} said no - they value {get['name']} more than your offer."
    elif cap_used(user) - give["contract"]["aav"] + get["contract"]["aav"] > CAP_TOTAL:
        result["accepted"] = False
        result["msg"] = f"{target['full']} would do it, but {get['name']}'s contract puts you over the cap."
    else:
        user["roster"] = [p for p in user["roster"] if p["id"] != give_id] + [get]
        target["roster"] = [p for p in target["roster"] if p["id"] != get_id] + [give]
        result["accepted"] = True
        result["msg"] = f"Trade accepted! {give['name']} to {target['full']} for {get['name']}."
    save["last_trade"] = result
    write_save(save)
    return result


# --------------------------------------------------------------------------- #
# CLI self-test:  python franchise_kings.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    s = create_save("selftest_user", "Darrel Copper", "analytics", seed=42)
    print(f"League: {len(s['teams'])} teams, {len(CONFERENCES)} conferences x {len(DIVISIONS)} divisions")
    t = current_team(s)
    print(f"Team: {t['full']} ({t['conference']} {t['division']})  Power {power_rating(t)}  "
          f"Roster {len(t['roster'])}  Cap {cap_used(t)}/{CAP_TOTAL}")
    print("Expectation:", s["expectation"]["text"])
    for yr in range(5):
        s, out = sim_season(s)
        if out["offers"]:
            take_job(s, out["offers"][0]["id"])
        npicks = 0
        while s.get("draft_pending"):
            st = draft_state(s)
            if st and st["on_clock"] and st["available"]:
                draft_make_pick(s, st["available"][0]["id"])
                npicks += 1
            else:
                break
        t2 = current_team(s)
        print(f"  {out['record']['w']:>2}-{out['record']['l']:<2} {out['status']:>8} | "
              f"drafted {npicks} | roster {len(t2['roster'])} | champ {out['champion']}")
    print("Career seasons:", len(s["gm"]["career"]), "| titles:", s["gm"]["titles"])
    print("Last draft log:", json.dumps(s.get("last_draft_log", []), indent=0))
    delete_save("selftest_user")
    print("OK - 32-team engine + draft works")
