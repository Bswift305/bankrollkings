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


def _luma(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _vivify(hexcolor, target=232):
    """Brighten a colour while keeping its hue/saturation - scale RGB so the
    dominant channel reaches `target`. Turns a dark crimson into a vivid red, not
    a washed-out pink (which is what mixing toward white does)."""
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = max(r, g, b, 1)
    f = target / m
    r, g, b = (min(255, int(c * f)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def team_accent(full):
    """A guaranteed-legible team accent for dark UI: the club's secondary if it's
    bright enough, else its primary, else a vivified primary (stays on-brand even
    when a club's colours are black/navy)."""
    c = team_colors(full)
    pri, sec = c["primary"], c["secondary"]
    if _luma(sec) >= 110:
        return sec
    if _luma(pri) >= 120:
        return pri
    return _vivify(pri)


def team_crest_svg(full, size=36):
    """A two-tone shield emblem in the club's colours: a concentric secondary
    keyline, side-shading for depth, a top sheen, and the mascot's initial. No
    SVG gradient ids (so any number can share a page), and a hairline outer edge
    so even a near-black crest reads on a dark card. Reads from ~20px to the hero."""
    meta = _TEAM_META.get(full)
    pri = meta["primary"] if meta else "#1b2a36"
    sec = meta["secondary"] if meta else "#4ad4f0"
    initial = (meta["mascot"][0] if meta else (full or "?")[:1]).upper()
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 48 48" class="fk-crest" '
        f'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">'
        # outer shield + hairline edge to ground it on any background
        f'<path d="M24 3 L43 9 V25 C43 35.5 35 42.5 24 46 C13 42.5 5 35.5 5 25 V9 Z" '
        f'fill="{pri}" stroke="#ffffff" stroke-opacity="0.4" stroke-width="1.4" stroke-linejoin="round"/>'
        # right-side shade for dimensionality
        f'<path d="M24 4 L42 9.6 V25 C42 35 34.4 41.8 24 45.2 Z" fill="#000000" opacity="0.13"/>'
        # concentric secondary keyline (the two-tone crest frame)
        f'<path d="M24 8 L38.5 12.6 V24.7 C38.5 32.8 31.8 38.8 24 41.4 C16.2 38.8 9.5 32.8 9.5 24.7 V12.6 Z" '
        f'fill="none" stroke="{sec}" stroke-width="2" stroke-linejoin="round"/>'
        # top sheen
        f'<path d="M9.5 12.6 L24 8 L38.5 12.6 L38.5 15.4 L24 11 L9.5 15.4 Z" fill="#ffffff" opacity="0.10"/>'
        f'<text x="24" y="33" text-anchor="middle" font-size="21" font-weight="900" '
        f'fill="{_contrast(pri)}" font-family="Arial,Helvetica,sans-serif">{initial}</text>'
        f'</svg>')


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


# --------------------------------------------------------------------------- #
# Player personality + background. Personalities add character (and a light
# development nudge); colleges use real college PLACES with FICTIONAL mascots
# (same no-licensing approach as the NFL clubs - UGA -> "Georgia Bullies"); high
# schools + hometowns are generated.
# --------------------------------------------------------------------------- #
PERSONALITIES = {
    "Field General": {"blurb": "Vocal leader - lifts the whole locker room.", "dev": 0},
    "Film Junkie":   {"blurb": "First one in, last one out. Always studying.", "dev": 1},
    "Gym Rat":       {"blurb": "Relentless worker - outworks everybody.", "dev": 1},
    "Freak Athlete": {"blurb": "Jaw-dropping raw tools. Sky-high ceiling.", "dev": 1},
    "Quiet Pro":     {"blurb": "Lets his play do the talking. Rock steady.", "dev": 0},
    "Clutch Gene":   {"blurb": "Lives for the big moment.", "dev": 0},
    "Underdog":      {"blurb": "Massive chip on his shoulder.", "dev": 1},
    "Mentor":        {"blurb": "Makes the young guys around him better.", "dev": 0},
    "Showman":       {"blurb": "Loves the spotlight and the headlines.", "dev": 0},
    "Hothead":       {"blurb": "Plays angry - can boil over.", "dev": 0},
    "Free Spirit":   {"blurb": "Marches to the beat of his own drum.", "dev": 0},
    "Throwback":     {"blurb": "Old-school, tough, no-nonsense.", "dev": 0},
}
# Real college places, FICTIONAL mascots (no marks - same play as the NFL cities).
COLLEGES = [
    "Georgia Bullies", "Alabama Crimson", "Ohio Scarlet", "Texas Steers", "Oklahoma Drifters",
    "Louisiana Bayou Cats", "Michigan Maize", "South Bend Shamrocks", "Clemson Paws",
    "Oregon Mallards", "Florida Swamp", "Tallahassee Spears", "Southern Cal Centurions",
    "Penn State Mountain Cats", "Wisconsin Diggers", "Tennessee Rivermen", "Auburn War Cats",
    "Miami Storm", "Nebraska Plowmen", "College Station Cadets", "Washington Sled Dogs",
    "Utah Beehives", "Iowa Hawks", "Oxford Magnolias", "Arkansas Tuskers",
    "Lexington Thoroughbreds", "Missouri Mules", "Waco Grizzlies", "Fort Worth Frogs",
    "Blacksburg Gobblers", "Pittsburgh Steel Cats", "Louisville Sluggers", "Raleigh Wolves",
    "Chapel Hill Rams", "Durham Blue Devils", "Boston Minutemen", "Syracuse Citrus",
    "Morgantown Climbers", "Cincinnati Queen City", "Houston Pumas", "Orlando Knights",
    "Memphis Blues", "Boise Blue Turf", "San Diego Conquistadors", "Boulder Bison",
    "Manhattan Wildcats", "Lawrence Jays", "East Lansing Spartans", "Champaign Plainsmen",
]
HOMETOWNS = [
    ("Houston", "TX"), ("Dallas", "TX"), ("Miami", "FL"), ("Tampa", "FL"), ("Atlanta", "GA"),
    ("Savannah", "GA"), ("Los Angeles", "CA"), ("Long Beach", "CA"), ("New Orleans", "LA"),
    ("Baton Rouge", "LA"), ("Mobile", "AL"), ("Birmingham", "AL"), ("Cleveland", "OH"),
    ("Columbus", "OH"), ("Detroit", "MI"), ("Chicago", "IL"), ("Philadelphia", "PA"),
    ("Newark", "NJ"), ("Memphis", "TN"), ("Nashville", "TN"), ("Charlotte", "NC"),
    ("Richmond", "VA"), ("St. Louis", "MO"), ("Kansas City", "MO"), ("Phoenix", "AZ"),
    ("Las Vegas", "NV"), ("Seattle", "WA"), ("Oakland", "CA"), ("Jacksonville", "FL"),
    ("Orlando", "FL"), ("San Diego", "CA"), ("Fresno", "CA"),
]
_HS_NAMES = ["Lincoln", "Washington", "Jackson", "Lakeview", "Riverside", "Oakwood",
             "St. Augustine", "St. Thomas", "Hillcrest", "Northgate", "Pinecrest",
             "Westfield", "Eastside", "Manvel", "DeSoto", "Central"]


def _gen_background(rng):
    city, st = rng.choice(HOMETOWNS)
    hs = (f"{city} {rng.choice(['High', 'Prep', 'Central', 'Catholic', 'Memorial'])}"
          if rng.random() < 0.5 else f"{rng.choice(_HS_NAMES)} {rng.choice(['High', 'Prep', 'Academy'])}")
    return {"personality": rng.choice(list(PERSONALITIES)), "hometown": f"{city}, {st}",
            "high_school": hs, "college": rng.choice(COLLEGES)}


def _rng(seed):
    return random.Random(seed)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _gen_name(rng):
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _roll_true_pot(rng, overall, potential, age):
    """The HIDDEN true ceiling. Scouting (the visible `potential`) is just a read -
    young, unproven players can quietly be more (a hidden gem / UDFA gem) or less
    (a bust). Established players are known quantities. Revealed only as he develops."""
    if age >= 27 or potential - overall < 3:
        return potential                                   # known quantity, no surprise
    r = rng.random()
    if r < 0.12:
        return min(99, potential + int(rng.triangular(3, 19, 6)))   # hidden gem (rare big jumps)
    if r < 0.22:
        return max(overall, potential - int(rng.triangular(2, 9, 3)))  # bust risk
    return potential


# Within a position every player has a STYLE - the archetype a scheme covets.
# Two equally-rated WRs can fit your offense very differently. This is the
# per-player layer that sits UNDER the coordinator's scheme (which re-weights
# whole position groups). See SCHEME_STYLE_FIT + tactical_fit() below.
POS_STYLES = {
    "QB": ["Pocket Passer", "Dual Threat", "Game Manager", "RPO Specialist"],
    "RB": ["Power Back", "Scat Back", "Every-Down"],
    "WR": ["Deep Threat", "Possession", "Slot"],
    "TE": ["Move TE", "In-Line Blocker"],
    "OL": ["Power", "Zone"],
    "DL": ["Run Stuffer", "Pass Rusher"],
    "LB": ["Coverage", "Thumper"],
    "CB": ["Press Man", "Zone"],
    "S":  ["Box", "Center Field"],
    "K":  ["Big Leg", "Accurate"],
}

MOTIVATIONS = ["Prove Them Wrong", "Family Security", "Legacy", "Team-First", "Spotlight", "Craft"]
LEARNING_STYLES = ["Film Learner", "Repetition", "Instinctive", "Structure", "Confidence"]
COACH_PREFS = ["Technician", "Teacher", "Motivator", "Players' Coach", "Hard-Driver"]


def _style_for(rng, pos):
    return rng.choice(POS_STYLES.get(pos, ["Balanced"]))


def _gen_human_profile(rng):
    return {
        "motivation": rng.choice(MOTIVATIONS),
        "learning": rng.choice(LEARNING_STYLES),
        "coach_pref": rng.choice(COACH_PREFS),
        "confidence": rng.randint(42, 88),
        "work_ethic": rng.randint(42, 92),
    }


def ensure_human_profile(p, rng=None):
    """Backfill human-development fields for older saves and generated prospects."""
    rng = rng or _rng(abs(hash(p.get("id", p.get("name", "player")))) % 999983)
    for k, v in _gen_human_profile(rng).items():
        p.setdefault(k, v)
    return p


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
        "true_pot": _roll_true_pot(rng, overall, potential, age),
        "dev": rng.choice(["Normal", "Star", "Slow", "Late Bloomer"]),
        "style": _style_for(rng, pos),
        "contract": {"years": rng.randint(1, 4), "aav": aav, "guaranteed": round(aav * rng.uniform(0.3, 0.8), 1)},
        "morale": rng.randint(55, 90),
        "injury_risk": rng.choice(["Low", "Low", "Medium", "High"]),
        **_gen_background(rng),
        **_gen_human_profile(rng),
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
    generate_team_histories(teams, rng)
    ensure_owner_names(teams, rng)
    return teams, _gen_fa_pool(rng)


def ensure_owner_names(teams, rng):
    """Every club gets its own owner NAME (the type profile only supplies the
    title/style) — 32 clubs, 32 different people. Returns True if changed."""
    seen = {(t.get("owner") or {}).get("name") for t in teams}
    seen.discard(None)
    changed = False
    for t in teams:
        owner = t.setdefault("owner", {"type": "Hands-Off"})
        if owner.get("name"):
            continue
        name = _gen_name(rng)
        while name in seen:
            name = _gen_name(rng)
        owner["name"] = name
        seen.add(name)
        changed = True
    return changed


# --------------------------------------------------------------------------- #
# Franchise histories — every club carries a past: when it was founded, the
# trophies (or the drought), a franchise legend, a division rival, and an
# identity blurb. Pure flavor with teeth: it makes picking a job mean something.
# --------------------------------------------------------------------------- #
_LEGEND_POS = ["QB", "RB", "WR", "OL", "DL", "LB", "CB", "S"]


def _gen_team_history(rng, team, rival_name):
    founded = rng.choice(
        [rng.randint(1921, 1935)] * 3 + [rng.randint(1946, 1969)] * 4 + [rng.randint(1970, 1999)] * 3)
    era_span = max(1, (2025 - founded) // 12)          # older clubs had more swings
    titles = max(0, int(rng.triangular(-1.2, min(6, era_span), 0.8)))
    last_title = rng.randint(founded + 5, 2025) if titles else None
    if titles and rng.random() < 0.45:                  # dynasties cluster; droughts are real
        last_title = rng.randint(founded + 5, min(2025, founded + 35))
    drought = (2026 - last_title) if last_title else (2026 - founded)
    legend_era = rng.randint(max(founded + 3, 1950), 2018)
    legend = {"name": _gen_name(rng), "pos": rng.choice(_LEGEND_POS),
              "era": f"{legend_era}-{legend_era + rng.randint(7, 14)}"}
    mascot = team.get("name") or team["full"].split()[-1]
    city = team.get("city") or team["full"].replace(mascot, "").strip()
    if titles >= 3 and drought <= 12:
        blurb = f"A modern power — the {mascot} hang banners, and {city} expects another."
    elif titles >= 3:
        blurb = f"A faded flagship: {titles} trophies in the case, all of them dusty. {city} aches for the old days."
    elif titles and drought <= 12:
        blurb = f"Recent champions still hungry — {city} tasted it and wants more."
    elif titles:
        blurb = f"One glorious run in {last_title}, and {city} has retold it every season since."
    elif founded < 1970:
        blurb = f"The league's longest ache — since {founded} the {mascot} have never won it all. {city} would build a statue of the GM who ends it."
    else:
        blurb = f"A young club still writing its identity — no banners yet, no ghosts either. {city} is all upside."
    return {"founded": founded, "titles": titles, "last_title": last_title,
            "drought": drought, "legend": legend, "rival": rival_name, "blurb": blurb}


def generate_team_histories(teams, rng):
    for t in teams:
        if t.get("history"):
            continue
        divmates = [x["full"] for x in teams
                    if x["id"] != t["id"] and x.get("division") == t.get("division")
                    and x.get("conference") == t.get("conference")]
        rival = rng.choice(divmates) if divmates else (rng.choice(
            [x["full"] for x in teams if x["id"] != t["id"]]) if len(teams) > 1 else "")
        t["history"] = _gen_team_history(rng, t, rival)


def ensure_team_histories(save):
    """Backfill histories and per-team owner names into older saves,
    deterministically. Returns True if anything changed so the caller can
    persist once."""
    teams = save.get("teams") or []
    if not teams:
        return False
    seed = int(save.get("seed", 1) or 1)
    changed = False
    if not all(t.get("history") for t in teams):
        generate_team_histories(teams, _rng(seed + 4242))
        changed = True
    if ensure_owner_names(teams, _rng(seed + 515)):
        changed = True
    return changed


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
def pos_depth(team, pos):
    """Position depth order: the GM's saved chart first (self-healing as the
    roster churns), everyone else by overall. Clubs with no saved chart —
    every AI team — field best-OVR lineups exactly as before."""
    players = [p for p in team["roster"] if p["pos"] == pos]
    order = (team.get("depth") or {}).get(pos) or []
    idx = {pid: i for i, pid in enumerate(order)}
    return sorted(players, key=lambda p: (idx.get(p["id"], 999), -p["overall"]))


def move_up_depth(save, pid):
    """Bump a player one slot up his position's depth chart."""
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False, "He's not on your roster."
    pos = p["pos"]
    cur = [x["id"] for x in pos_depth(team, pos)]
    i = cur.index(pid)
    if i == 0:
        return False, f"{p['name']} already tops the {pos} depth chart."
    cur[i - 1], cur[i] = cur[i], cur[i - 1]
    team.setdefault("depth", {})[pos] = cur
    write_save(save)
    return True, f"{p['name']} moves up the {pos} depth chart."


def reset_depth(save):
    current_team(save).pop("depth", None)
    write_save(save)
    return True, "Depth chart reset — best man plays at every spot."


def power_rating(team, ignore_depth=False):
    """Weighted average of the STARTERS per position — the GM's depth chart if
    he set one (benching a stud costs real power), best-OVR otherwise."""
    num = den = 0.0
    for pos, slots in ROSTER.items():
        if ignore_depth:
            best = sorted([p for p in team["roster"] if p["pos"] == pos],
                          key=lambda x: -x["overall"])[:slots]
        else:
            best = pos_depth(team, pos)[:slots]
        if not best:
            continue
        w = POS_WEIGHT.get(pos, 1.0)
        num += w * (sum(x["overall"] for x in best) / len(best)) * slots
        den += w * slots
    return round(num / den, 1) if den else 60.0


def team_dead_cap(team):
    return round(sum(e.get("amount", 0) for e in team.get("dead_cap_entries", [])), 1)


def charge_dead_money(team, p):
    """Cutting a man doesn't erase his guarantees — the shell hits this year's
    cap as dead money (cleared when the season closes)."""
    amt = cut_penalty(p)
    if amt >= 0.3:
        team.setdefault("dead_cap_entries", []).append(
            {"name": p["name"], "pos": p["pos"], "amount": amt, "seasons_left": 1})
    return amt


def restructure_contract(save, pid):
    """Convert salary into guaranteed bonus: ~40% of his AAV becomes cap room
    for every remaining year — but the money is now guaranteed, so the
    dead-money cost of ever cutting him balloons. Flexibility today,
    handcuffs tomorrow. Once per player per season."""
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False, "He's not on your roster."
    c = p.get("contract") or {}
    if int(c.get("years", 0) or 0) < 2:
        return False, f"{p['name']} is in his final year — nothing left to restructure."
    if float(c.get("aav", 0) or 0) < 6:
        return False, f"{p['name']}'s deal is too small to move money around."
    if c.get("restructured_season") == save.get("season"):
        return False, f"You already restructured {p['name']} this year."
    relief = round(c["aav"] * 0.4, 1)
    c["aav"] = round(c["aav"] - relief, 1)
    c["guaranteed"] = round((c.get("guaranteed", 0) or 0) + relief * c["years"], 1)
    c["restructured_season"] = save.get("season")
    write_save(save)
    return True, (f"Restructured — ${relief}M/yr of cap room opened for the rest of his deal. "
                  f"That money is guaranteed now: cutting {p['name']} would cost "
                  f"${cut_penalty(p)}M dead against the cap.")


def cap_used(team):
    return round(sum(p["contract"]["aav"] for p in team["roster"]) + team_dead_cap(team), 1)


def _starters(team):
    out = []
    for pos, slots in ROSTER.items():
        out += pos_depth(team, pos)[:slots]
    return out


# Dev-trait curves: when a player grows, how fast, and when he declines.
_PEAK = {"Star": 28, "Late Bloomer": 30, "Slow": 27, "Normal": 28}
_RATE = {"Star": 3, "Late Bloomer": 2, "Slow": 1, "Normal": 2}
_DECLINE = {"Star": 31, "Late Bloomer": 32, "Slow": 30, "Normal": 31}


def _develop(p, rng, bonus):
    tr, age = p.get("dev", "Normal"), p["age"]
    cap = p.get("true_pot", p["potential"])        # the HIDDEN real ceiling
    if age <= _PEAK.get(tr, 28) and p["overall"] < cap:
        gain = rng.randint(0, _RATE.get(tr, 2)) + bonus + PERSONALITIES.get(p.get("personality"), {}).get("dev", 0)
        if tr == "Late Bloomer" and age >= 25:
            gain += 1
        gain = max(0, gain)
        p["overall"] = min(cap, p["overall"] + gain)
        # a hidden gem reveals himself: scouts revise the VISIBLE ceiling up as he proves it
        if cap > p["potential"] and p["overall"] >= p["potential"] - 2:
            p["potential"] = min(cap, p["potential"] + rng.randint(1, 4))
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
            weeks = min(weeks, REG_GAMES)
            p["inj_history"] = p.get("inj_history", 0) + 1          # career injuries (scouts care)
            p["inj_weeks"] = p.get("inj_weeks", 0) + weeks          # career games missed
            out.append({"name": p["name"], "pos": p["pos"], "ovr": p["overall"], "weeks": weeks})
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


TRADE_DEADLINE_SOLO = 9


def _add_stats(p, d):
    s = p.setdefault("stats", {})
    for k, v in d.items():
        s[k] = round(s.get(k, 0) + v, 1) if isinstance(v, float) else s.get(k, 0) + v


def _game_perf(team, won, rng, out_ids=()):
    """Generate ONE game's box-score lines for a team's contributors, add them to
    running season totals, and return the skill/defense standouts (for game stars)."""
    by_pos = {}
    for p in team["roster"]:
        if p["id"] not in out_ids:
            by_pos.setdefault(p["pos"], []).append(p)
    for k in by_pos:
        by_pos[k].sort(key=lambda x: -x["overall"])
    wb = 1.1 if won else 0.92
    perf = []

    for qb in by_pos.get("QB", [])[:1]:
        o = qb["overall"]
        att = rng.randint(26, 40)
        comp = int(att * min(0.74, 0.55 + (o - 55) * 0.0035))
        yd = int(comp * rng.uniform(6.4, 9.2) * wb)
        td = max(0, int(yd / 150 * wb + rng.random()))
        intc = rng.randint(0, 2) if rng.random() < 0.5 else 0
        _add_stats(qb, {"g": 1, "pass_att": att, "pass_cmp": comp, "pass_yd": yd, "pass_td": td, "int": intc})
        perf.append({"name": qb["name"], "pos": "QB", "pid": qb["id"],
                     "line": f"{comp}/{att}, {yd} yd, {td} TD" + (f", {intc} INT" if intc else ""),
                     "score": yd * 0.04 + td * 4 - intc * 2})
    for i, rb in enumerate(by_pos.get("RB", [])[:2]):
        o = rb["overall"]
        car = int(rng.randint(8, 22) * (1.0 if i == 0 else 0.5) * (1 + (o - 65) * 0.004))
        yd = int(car * rng.uniform(3.2, 6.2) * wb)
        td = max(0, int(yd / 60 * wb + rng.random() * 0.5))
        catches = int(rng.randint(1, 5) * (1.0 if i == 0 else 0.6))
        _add_stats(rb, {"g": 1, "rush_car": car, "rush_yd": yd, "rush_td": td, "rec": catches, "rec_yd": catches * 8})
        perf.append({"name": rb["name"], "pos": "RB", "pid": rb["id"],
                     "line": f"{car} car, {yd} yd, {td} TD", "score": yd * 0.06 + td * 6})
    for c in by_pos.get("WR", [])[:3] + by_pos.get("TE", [])[:1]:
        o = c["overall"]
        catches = rng.randint(2, 9)
        yd = int(catches * rng.uniform(9, 17) * (1 + (o - 65) * 0.004) * wb)
        td = max(0, int(yd / 70 * wb))
        _add_stats(c, {"g": 1, "rec": catches, "rec_yd": yd, "rec_td": td})
        perf.append({"name": c["name"], "pos": c["pos"], "pid": c["id"],
                     "line": f"{catches} rec, {yd} yd, {td} TD", "score": yd * 0.06 + td * 6 + catches * 0.4})
    for d in by_pos.get("DL", [])[:4] + by_pos.get("LB", [])[:3]:
        o = d["overall"]
        sk = round(max(0.0, (o - 66) * 0.02) + (rng.random() * 1.2 if rng.random() < 0.4 else 0.0), 1)
        tk = rng.randint(1, 6)
        _add_stats(d, {"g": 1, "sack": sk, "tackle": tk})
        if sk >= 1.5:
            perf.append({"name": d["name"], "pos": d["pos"], "pid": d["id"],
                         "line": f"{sk} sacks, {tk} tkl", "score": sk * 5 + tk * 0.3})
    for d in by_pos.get("CB", [])[:3] + by_pos.get("S", [])[:2]:
        o = d["overall"]
        di = 1 if rng.random() < max(0, (o - 72) * 0.02) else 0
        _add_stats(d, {"g": 1, "tackle": rng.randint(1, 6), "def_int": di, "pd": 1 if rng.random() < 0.3 else 0})
    for k in by_pos.get("K", [])[:1]:
        fgm = rng.randint(0, 4) if rng.random() < 0.6 else rng.randint(0, 2)
        _add_stats(k, {"g": 1, "fgm": fgm, "fga": fgm + (1 if rng.random() < 0.3 else 0), "pts": fgm * 3 + rng.randint(0, 4)})
    return perf


# --------------------------------------------------------------------------- #
# Weekly Command Center — the GM's STANDING weekly plan. These choices persist
# and actually bend the season: practice intensity (sharpness vs injuries), the
# focus, how aggressive medical is, the game plan, and what your scouts work on.
# --------------------------------------------------------------------------- #
PRACTICE_INTENSITY = {
    "Recovery":   {"edge": -0.3, "inj": 0.70, "blurb": "Fresh legs, fewer injuries — but a softer edge on Sunday."},
    "Balanced":   {"edge": 0.0,  "inj": 1.00, "blurb": "A normal week of work."},
    "Physical":   {"edge": 0.6,  "inj": 1.35, "blurb": "A tougher, sharper team — at a real injury cost."},
    "High Tempo": {"edge": 0.4,  "inj": 1.18, "blurb": "Conditioning and speed, moderate wear."},
}
PRACTICE_FOCUS = ["Scheme Install", "Red Zone", "Pass Game", "Run Game", "Pass Rush",
                  "Coverage", "Ball Security", "Rookie Development"]
MEDICAL_POLICY = {
    "Cautious":    {"inj": 0.80, "ret": 1,  "blurb": "Rest guys fully — healthiest roster, but you're shorthanded longer."},
    "Balanced":    {"inj": 1.00, "ret": 0,  "blurb": "Standard medical calls."},
    "Aggressive":  {"inj": 1.20, "ret": -1, "blurb": "Play 'em hurt — bodies back faster, aggravation risk climbs."},
}
GAME_PLANS = {
    "Balanced":         {"edge": 0.0, "blurb": "No strong lean."},
    "Aggressive":       {"edge": 0.7, "blurb": "Push the tempo and take your shots."},
    "Conservative":     {"edge": 0.2, "blurb": "Protect the ball, win the margins."},
    "Attack Weakness":  {"edge": 0.6, "blurb": "Game-planned to your opponent's soft spot."},
    "Protect the Unit": {"edge": 0.1, "blurb": "Scheme around your banged-up group."},
}
SCOUT_ASSIGNMENTS = ["Opponent", "Draft Class", "Free Agents", "Internal Development"]


def init_weekly_ops(save):
    save["weekly_ops"] = {"intensity": "Balanced", "focus": "Scheme Install",
                          "medical": "Balanced", "game_plan": "Balanced", "scout": "Opponent"}
    return save["weekly_ops"]


def set_weekly_plan(save, **fields):
    wo = save.setdefault("weekly_ops", {})
    for key, table in (("intensity", PRACTICE_INTENSITY), ("focus", PRACTICE_FOCUS),
                       ("medical", MEDICAL_POLICY), ("game_plan", GAME_PLANS), ("scout", SCOUT_ASSIGNMENTS)):
        v = fields.get(key)
        if v is not None and v in table:
            wo[key] = v
    write_save(save)
    return wo


def weekly_edge(save):
    """The standing weekly plan's net power edge this Sunday."""
    wo = save.get("weekly_ops", {})
    e = PRACTICE_INTENSITY.get(wo.get("intensity", "Balanced"), {}).get("edge", 0.0)
    e += GAME_PLANS.get(wo.get("game_plan", "Balanced"), {}).get("edge", 0.0)
    if wo.get("scout") == "Opponent":
        e += 0.5
    return round(e, 2)


def weekly_injury_factor(save):
    wo = save.get("weekly_ops", {})
    return (PRACTICE_INTENSITY.get(wo.get("intensity", "Balanced"), {}).get("inj", 1.0)
            * MEDICAL_POLICY.get(wo.get("medical", "Balanced"), {}).get("inj", 1.0))


def _roll_week_injuries(save, week, rng):
    team = current_team(save)
    med = max(0.4, 1.0 - (staff_bonus(save)["medical"] - 50) / 180.0)
    plan_inj = weekly_injury_factor(save)                       # Command Center: intensity + medical
    ret = MEDICAL_POLICY.get(save.get("weekly_ops", {}).get("medical", "Balanced"), {}).get("ret", 0)
    base = {"Low": 0.012, "Medium": 0.025, "High": 0.045}
    new = []
    for p in _starters(team):
        if p.get("out_until", 0) >= week:
            continue
        ch = base.get(p.get("injury_risk", "Low"), 0.02) * med * plan_inj + max(0, p["age"] - 29) * 0.002
        if rng.random() < ch:
            dur = max(1, rng.randint(1, 6) + ret)              # aggressive medical = back sooner
            p["out_until"] = week + dur
            p["inj_history"] = p.get("inj_history", 0) + 1
            p["inj_weeks"] = p.get("inj_weeks", 0) + dur
            new.append({"name": p["name"], "pos": p["pos"], "weeks": dur})
    return new


def _user_inseason_power(save, week, base_power):
    sb = staff_bonus(save)
    p = (base_power + sb["power"] + sb["scheme"] + sb["playbook"]["edge"]
         + sb["special_teams"] + atmosphere(save)["home_edge"])
    p += weekly_edge(save)                                      # Command Center: practice + game plan
    p -= sum(2.5 for x in current_team(save)["roster"] if x.get("holdout"))
    out = [x for x in _starters(current_team(save)) if x.get("out_until", 0) >= week]
    p -= round(sum(POS_WEIGHT.get(x["pos"], 1.0) * 1.4 for x in out), 1)
    return round(p, 1), out


# --------------------------------------------------------------------------- #
# The living building — weekly agenda. Coaches and players bring you decisions:
# a buried rookie wants snaps, a vet wants clarity, your OC wants a promotion, a
# banged-up starter is questionable. Each is YOUR call, with morale / confidence /
# staff-trust fallout. Plus the locker-room pulse and your captains.
# --------------------------------------------------------------------------- #
def _nudge(save, pid, morale=0, conf=0):
    for t in save["teams"]:
        for p in t["roster"]:
            if p["id"] == pid:
                if morale:
                    p["morale"] = max(5, min(99, p.get("morale", 70) + morale))
                if conf:
                    p["confidence"] = max(5, min(99, p.get("confidence", 65) + conf))
                return p
    return None


def _starter_ids(team):
    return {p["id"] for p in _starters(team)}


def _ag_young_snaps(save, week, rng):
    team = current_team(save)
    starters = _starter_ids(team)
    pool = [p for p in team["roster"] if p.get("age", 30) <= 24 and p["overall"] >= 70
            and p["id"] not in starters]
    if not pool:
        return None
    p = max(pool, key=lambda x: x["overall"])
    return {"kind": "player", "topic": "young_snaps", "icon": "📈", "pid": p["id"],
            "who": f"{p['pos']} {p['name']}", "title": f"{p['pos']} {p['name']} wants more snaps",
            "detail": f"He's a {p['overall']}-OVR talent buried on the depth chart and he's pushing for a real role.",
            "options": [{"key": "promote", "label": "Promote him"},
                        {"key": "earn", "label": "Tell him to earn it"},
                        {"key": "defer", "label": "Stay noncommittal"}]}


def _ag_vet_clarity(save, week, rng):
    team = current_team(save)
    best = {}
    for p in team["roster"]:
        best[p["pos"]] = max(best.get(p["pos"], 0), p["overall"])
    pool = [p for p in team["roster"] if p.get("age", 25) >= 30 and p["overall"] < best.get(p["pos"], 0)]
    if not pool:
        return None
    p = min(pool, key=lambda x: x.get("morale", 70))
    return {"kind": "player", "topic": "vet_clarity", "icon": "🗣", "pid": p["id"],
            "who": f"{p['pos']} {p['name']}", "title": f"{p['pos']} {p['name']} wants role clarity",
            "detail": "He's lost snaps and wants to know where he stands before it festers.",
            "options": [{"key": "reassure", "label": "Reassure him"},
                        {"key": "honest", "label": "Be honest — he's depth now"},
                        {"key": "shop", "label": "Tell him you'll shop a trade"}]}


def _ag_coord_promote(save, week, rng):
    staff = save.get("staff", {})
    coord = staff.get("off_coord") or staff.get("def_coord")
    if not coord:
        return None
    team = current_team(save)
    starters = _starter_ids(team)
    side = OFFENSE_POS if staff.get("off_coord") else {"DL", "LB", "CB", "S"}
    pool = [p for p in team["roster"] if p["pos"] in side and p.get("age", 30) <= 25 and p["id"] not in starters and p["overall"] >= 68]
    if not pool:
        return None
    p = max(pool, key=lambda x: x["overall"])
    role = "OC" if staff.get("off_coord") else "DC"
    return {"kind": "staff", "topic": "coord_promote", "icon": "🧠", "pid": p["id"],
            "who": f"{role} {coord['name']}", "title": f"{role} wants {p['pos']} {p['name']} promoted",
            "detail": f"“The kid's earned first-team reps. Trust me on this one.”",
            "options": [{"key": "trust", "label": "Trust the coach"},
                        {"key": "override", "label": "Override — not yet"}]}


def _ag_questionable(save, week, rng):
    team = current_team(save)
    pool = [p for p in _starters(team) if 0 < p.get("out_until", 0) - week <= 1]
    if not pool:
        return None
    p = max(pool, key=lambda x: x["overall"])
    return {"kind": "medical", "topic": "questionable", "icon": "🏥", "pid": p["id"],
            "who": f"{p['pos']} {p['name']}", "title": f"{p['pos']} {p['name']} is questionable",
            "detail": "Medical lists him as a game-time decision. Your call on his participation.",
            "options": [{"key": "rest", "label": "Rest him"},
                        {"key": "limited", "label": "Limited package"},
                        {"key": "push", "label": "Push him to play"}]}


_AGENDA_GENS = [_ag_young_snaps, _ag_vet_clarity, _ag_coord_promote, _ag_questionable]


def generate_weekly_agenda(save, week, rng):
    agenda = [a for a in save.get("agenda", []) if week - a.get("week", week) <= 3]   # expire stale
    if len(agenda) < 5:
        gens = _AGENDA_GENS[:]
        rng.shuffle(gens)
        added = 0
        for g in gens:
            if added >= 2 or rng.random() > 0.5:
                continue
            item = g(save, week, rng)
            if item and not any(a.get("pid") == item.get("pid") for a in agenda):
                item["id"] = f"ag{rng.randint(100000, 999999)}"
                item["week"] = week
                agenda.insert(0, item)
                added += 1
    save["agenda"] = agenda[:6]
    return save["agenda"]


def resolve_agenda(save, item_id, choice):
    item = next((a for a in save.get("agenda", []) if a["id"] == item_id), None)
    if not item:
        return False, "That item is no longer on your desk."
    topic, pid = item.get("topic"), item.get("pid")
    trust = save.get("staff_trust", 60)
    week = (save.get("inseason") or {}).get("week", item.get("week", 1))
    if topic == "young_snaps":
        if choice == "promote":
            _nudge(save, pid, morale=6, conf=9); msg = f"You promoted {item['who']} — he's fired up."
        elif choice == "earn":
            _nudge(save, pid, conf=-4); msg = f"You told {item['who']} to earn it. Message sent."
        else:
            _nudge(save, pid, morale=-3); msg = f"You stayed noncommittal on {item['who']}."
    elif topic == "vet_clarity":
        if choice == "reassure":
            _nudge(save, pid, morale=7); msg = f"You reassured {item['who']} — he's bought back in."
        elif choice == "honest":
            _nudge(save, pid, morale=-5, conf=-3); msg = f"You leveled with {item['who']}. He respects it, but it stings."
        else:
            p = _nudge(save, pid, morale=-6)
            if p:
                p["trade_request"], p["trade_reason"] = True, "told he'd be shopped"
            msg = f"You told {item['who']} you'd shop him — he wants out now."
    elif topic == "coord_promote":
        if choice == "trust":
            save["staff_trust"] = min(99, trust + 5); _nudge(save, pid, conf=7)
            msg = f"You backed your coordinator. Staff trust up — and {item['who'].split(' ',1)[-1]} got his shot."
        else:
            save["staff_trust"] = max(10, trust - 7); msg = "You overrode your coordinator. He'll remember that."
    elif topic == "questionable":
        iz = save.get("inseason") or {}
        if choice == "rest":
            msg = f"You rested {item['who']} — health over Sunday."
        elif choice == "limited":
            p = _nudge(save, pid)
            if p and p.get("out_until", 0) > week:
                p["out_until"] = week
            msg = f"{item['who']} goes in a limited package."
        else:
            p = _nudge(save, pid, conf=4)
            if p:
                p["out_until"] = 0
                if random.random() < 0.30:
                    p["out_until"] = week + random.randint(2, 4)
                    msg = f"You pushed {item['who']} — and he aggravated it. Out again."
                else:
                    msg = f"You pushed {item['who']} to play. He answered the bell."
            else:
                msg = "Decision logged."
    else:
        msg = "Decision logged."
    save["agenda"] = [a for a in save.get("agenda", []) if a["id"] != item_id]
    save.setdefault("agenda_log", []).insert(0, {"week": item.get("week", week), "text": msg})
    save["agenda_log"] = save["agenda_log"][:8]
    write_save(save)
    return True, msg


def locker_room(save):
    """The locker-room pulse — chemistry, your leaders/captains, and volatility."""
    team = current_team(save)
    roster = team["roster"]
    if not roster:
        return {"chemistry": 60, "label": "Settling in", "morale": 70, "captains": [], "volatile": 0,
                "staff_trust": save.get("staff_trust", 60)}
    morale = round(sum(p.get("morale", 70) for p in roster) / len(roster))
    leaders = [p for p in roster if p.get("personality") in ("Field General", "Mentor", "Throwback", "Clutch Gene")
               and p["overall"] >= 74]
    captains = sorted(leaders, key=lambda p: -p["overall"])[:3]
    volatile = sum(1 for p in roster if p.get("personality") in ("Hothead", "Free Spirit"))
    chem = morale + len(captains) * 3 - volatile * 2 + (save.get("staff_trust", 60) - 60) * 0.1
    chem = max(20, min(99, round(chem)))
    label = "Tight-knit" if chem >= 78 else "Solid" if chem >= 62 else "Fraying" if chem >= 45 else "Toxic"
    return {"chemistry": chem, "label": label, "morale": morale, "volatile": volatile,
            "staff_trust": save.get("staff_trust", 60),
            "captains": [{"pos": c["pos"], "name": c["name"], "pid": c["id"], "per": c.get("personality")} for c in captains]}


def alerts(save):
    """The GM's inbox — everything needing your attention, pulled from across the
    franchise into one feed. The 'trigger' that brings you back: a decision on your
    desk, a trade feeler, a holdout, a player breaking out, the clock in the draft."""
    out = []
    iz = save.get("inseason") or {}

    if save.get("draft_pending"):
        ds = draft_state(save)
        if ds and ds.get("on_clock"):
            out.append({"icon": "🎓", "kind": "draft", "pri": 4, "text": "You're on the clock in the draft.", "tab": "draft"})

    off = iz.get("offer")
    if off:
        out.append({"icon": "🔁", "kind": "trade", "pri": 4,
                    "text": f"Trade feeler from {off.get('team', 'a rival')}: {off.get('give_pos', '')} {off.get('give', '')} on the table.",
                    "tab": "dashboard"})

    for a in (save.get("agenda") or [])[:4]:
        out.append({"icon": a.get("icon", "📋"), "kind": "decision", "pri": 3, "text": a["title"], "tab": "command"})

    for h in (save.get("holdouts") or [])[:2]:
        out.append({"icon": "✊", "kind": "holdout", "pri": 3,
                    "text": f"{h['pos']} {h['name']} is holding out — wants a new deal.", "tab": "front-office"})

    for fi in (save.get("front_office_issues") or [])[:3]:
        out.append({"icon": "⚠", "kind": "issue", "pri": 3,
                    "text": fi.get("summary") or fi.get("label", "A front-office issue needs you."), "tab": "front-office"})

    for inc in (save.get("incidents") or [])[:2]:
        out.append({"icon": "🚨", "kind": "wire", "pri": 2, "text": inc["text"] + ".", "tab": "gridiron", "pid": inc.get("pid")})

    for u in (save.get("ceiling_unlocks") or [])[:1]:
        out.append({"icon": "🔓", "kind": "dev", "pri": 1,
                    "text": f"{u['pos']} {u['name']} broke his ceiling ({u['from']}→{u['to']}).", "tab": "roster"})
    for b in (save.get("breakouts") or [])[:1]:
        out.append({"icon": "📈", "kind": "dev", "pri": 1, "text": f"{b['pos']} {b['name']} is breaking out.", "tab": "roster"})

    if not save.get("staff", {}).get("cond_coach"):
        out.append({"icon": "🏋", "kind": "staff", "pri": 2, "text": "No conditioning coach — your young players are stalling.", "tab": "staff"})

    room = round(CAP_TOTAL - cap_used(current_team(save)), 1)
    if room < 3:
        out.append({"icon": "💸", "kind": "cap", "pri": 2, "text": f"Cap nearly maxed — only ${room:.0f}M of room.", "tab": "front-office"})

    out.sort(key=lambda x: -x["pri"])
    return out[:9]


# --------------------------------------------------------------------------- #
# Off-field life: real NFL stuff happens away from the field. Personality drives
# who's at risk - a Hothead boils over, a Showman courts headlines. Incidents
# cost availability (suspensions reuse the injury out_until lane), morale, money,
# and the owner's trust, and they go on the player's permanent record.
# --------------------------------------------------------------------------- #
_OFFFIELD_RISK = {
    "Hothead": 2.4, "Showman": 1.9, "Free Spirit": 1.7, "Freak Athlete": 1.2,
    "Clutch Gene": 1.1, "Underdog": 0.9, "Field General": 0.8, "Throwback": 0.6,
    "Quiet Pro": 0.4, "Gym Rat": 0.4, "Film Junkie": 0.3, "Mentor": 0.3,
}
# key, weeks lo/hi, morale/trust/fan hit, fine $M, base weight, news verb ({n} = games)
_INCIDENTS = [
    {"key": "ped",     "wlo": 4, "whi": 6, "label": "PED suspension",     "morale": 16, "trust": 8,  "fan": 10, "fine": 0.0,  "weight": 0.8,
     "news": "is suspended {n} games for a banned substance"},
    {"key": "arrest",  "wlo": 1, "whi": 4, "label": "Legal trouble",      "morale": 16, "trust": 12, "fan": 14, "fine": 0.5,  "weight": 0.7,
     "news": "was arrested — a {n}-game suspension is expected"},
    {"key": "conduct", "wlo": 1, "whi": 3, "label": "Conduct suspension", "morale": 12, "trust": 6,  "fan": 8,  "fine": 0.25, "weight": 1.0,
     "news": "is suspended {n} games for conduct detrimental to the team"},
    {"key": "blowup",  "wlo": 0, "whi": 0, "label": "Sideline blowup",    "morale": 12, "trust": 4,  "fan": 4,  "fine": 0.3,  "weight": 1.3,
     "news": "was fined after a sideline blowup boiled over"},
    {"key": "rules",   "wlo": 0, "whi": 0, "label": "Team rules",         "morale": 6,  "trust": 0,  "fan": 2,  "fine": 0.1,  "weight": 1.6,
     "news": "was fined for a violation of team rules"},
]
_INCIDENT_FEED_MAX = 16


def _pick_incident(rng, personality):
    pool = _INCIDENTS
    w = [i["weight"] for i in pool]
    for i, inc in enumerate(pool):
        if personality == "Hothead" and inc["key"] in ("blowup", "conduct"):
            w[i] *= 2.2
        elif personality == "Showman" and inc["key"] in ("conduct", "rules"):
            w[i] *= 2.0
        elif personality in ("Freak Athlete", "Gym Rat") and inc["key"] == "ped":
            w[i] *= 2.5
    return rng.choices(pool, weights=w, k=1)[0]


def _roll_offfield(save, week, rng):
    """Roll the user roster for off-field incidents this week. At most one per
    player per season. Returns the new incidents (also logged to save+player)."""
    team = current_team(save)
    season = save.get("season", 1)
    base = 0.0018
    fired = []
    for p in team["roster"]:
        if p.get("out_until", 0) >= week or p.get("last_incident_season") == season:
            continue
        risk = _OFFFIELD_RISK.get(p.get("personality"), 1.0)
        if rng.random() >= base * risk:
            continue
        inc = _pick_incident(rng, p.get("personality"))
        weeks = rng.randint(inc["wlo"], inc["whi"]) if inc["whi"] else 0
        p["last_incident_season"] = season
        if weeks:
            p["out_until"] = week + weeks
            p["suspended_until"] = week + weeks
            p["susp_reason"] = inc["label"]
        p["morale"] = max(10, p.get("morale", 70) - inc["morale"])
        hist = p.setdefault("incidents", [])
        hist.append({"season": season, "week": week, "type": inc["label"], "weeks": weeks})
        p["incidents"] = hist[-8:]
        b = _business(save)
        b["cash"] = round(max(0.0, b["cash"] - inc["fine"]), 1)
        b["fan_happiness"] = max(0, b["fan_happiness"] - inc["fan"])
        save["gm"]["owner_trust"] = max(0, save["gm"]["owner_trust"] - inc["trust"])
        text = f"{p['pos']} {p['name']} {inc['news'].format(n=weeks)}"
        rec = {"season": season, "week": week, "key": inc["key"], "label": inc["label"],
               "pos": p["pos"], "name": p["name"], "pid": p["id"], "weeks": weeks, "text": text}
        save.setdefault("incidents", []).insert(0, rec)
        save["incidents"] = save["incidents"][:_INCIDENT_FEED_MAX]
        fired.append(rec)
        sev = "concern" if weeks else "neutral"
        owner_say(save, f"{p['pos']} {p['name']} — {inc['label'].lower()}? That reflects on all of us. Get it handled.", tone=sev)
    return fired


def _maybe_ai_offer(save, rng):
    uid = save["current_team_id"]
    myteam = current_team(save)
    mine = sorted([p for p in myteam["roster"] if not p.get("holdout")], key=lambda p: -trade_value(p))[:14]
    if not mine:
        return None
    # listed players are the ones rival GMs actually call about
    blocked = [p for p in myteam["roster"] if p.get("on_block") and not p.get("holdout")]
    want = rng.choice(blocked) if blocked and rng.random() < 0.75 else rng.choice(mine)
    ai = rng.choice([t for t in save["teams"] if t["id"] != uid])
    theirs = sorted(ai["roster"], key=lambda p: abs(trade_value(p) - trade_value(want)))[:6]
    if not theirs:
        return None
    give = rng.choice(theirs)
    vin, vout = trade_value(give), trade_value(want)
    ratio = vin / vout if vout else 1
    grade = ("A" if ratio >= 1.2 else "B" if ratio >= 1.03 else "C" if ratio >= 0.9 else "D" if ratio >= 0.78 else "F")
    return {"team_id": ai["id"], "team": ai["full"], "grade": grade,
            "want_id": want["id"], "want": want["name"], "want_pos": want["pos"], "want_ovr": want["overall"],
            "give_id": give["id"], "give": give["name"], "give_pos": give["pos"], "give_ovr": give["overall"]}


def accept_ai_offer(save):
    iz = save.get("inseason") or {}
    o = iz.get("offer")
    if not o:
        return False
    myteam = current_team(save)
    ai = next((t for t in save["teams"] if t["id"] == o["team_id"]), None)
    want = next((p for p in myteam["roster"] if p["id"] == o["want_id"]), None)
    give = next((p for p in ai["roster"] if p["id"] == o["give_id"]), None) if ai else None
    if not (ai and want and give):
        iz["offer"] = None
        write_save(save)
        return False
    myteam["roster"] = [p for p in myteam["roster"] if p["id"] != want["id"]] + [give]
    ai["roster"] = [p for p in ai["roster"] if p["id"] != give["id"]] + [want]
    save["last_trade"] = {"ok": True, "summary": f"Acquired {give['pos']} {give['name']} from the {o['team']} for {want['pos']} {want['name']}."}
    _trade_fallout(save, myteam, want, give)
    _owner_trade_react(save, give["pos"], give["name"], want["pos"], want["name"], o.get("grade", "C"))
    iz["offer"] = None
    write_save(save)
    return True


def decline_ai_offer(save):
    iz = save.get("inseason") or {}
    iz["offer"] = None
    write_save(save)
    return True


def start_inseason(save):
    """Kick off a turn-based, week-by-week regular season the GM plays through."""
    _expire_staff_poach(save)      # an unanswered rival offer costs you the coach
    me = current_team(save)
    for p in me["roster"]:
        p.pop("rep_starter", None)
    for p in _starters(me):
        p["rep_starter"] = True   # live reps all season -> young starters grow faster
    for t in save["teams"]:
        t["record"] = {"w": 0, "l": 0}
        for p in t["roster"]:
            p["stats"] = {}
            p.pop("out_until", None)
            p.pop("suspended_until", None)
            p.pop("susp_reason", None)
    save["incidents"] = []
    save["agenda"] = []
    if not save.get("weekly_ops"):                 # keep the GM's standing plan across seasons
        init_weekly_ops(save)
    save["season_schedule_weeks"] = REG_GAMES
    save["schedule"] = make_schedule(save["seed"] + save["season"], [t["id"] for t in save["teams"]])
    save["inseason"] = {"week": 1, "log": [], "offer": None, "injuries": []}
    save["last_outcome"] = None
    save["unemployed"] = False
    save["standings_cache"] = [{"id": t["id"], "full": t["full"], "conf": t["conference"],
                               "div": t["division"], "w": 0, "l": 0} for t in save["teams"]]
    owner_season_open(save)
    _update_power_rank(save)        # seed GridIron rankings for the new season
    write_save(save)
    return save


def sim_week(save):
    iz = save.get("inseason")
    if not iz:
        return save
    week = iz["week"]
    rng = _rng(save["seed"] + save["season"] * 1000 + week)
    teams = {t["id"]: t for t in save["teams"]}
    powers = {tid: power_rating(t) for tid, t in teams.items()}
    uid = save["current_team_id"]
    iz["injuries"] = _roll_week_injuries(save, week, rng)
    iz["incidents"] = _roll_offfield(save, week, rng)   # off-field drama (suspensions dock power below)
    powers[uid], out = _user_inseason_power(save, week, powers[uid])
    out_ids = {p["id"] for p in out}
    for g in save["schedule"]:
        if g["week"] != week:
            continue
        home_win = _sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win]["record"]["w"] += 1
        teams[lose]["record"]["l"] += 1
        ph = _game_perf(teams[g["home"]], win == g["home"], rng, out_ids if g["home"] == uid else ())
        pa = _game_perf(teams[g["away"]], win == g["away"], rng, out_ids if g["away"] == uid else ())
        if uid in (g["home"], g["away"]):
            opp = teams[g["away"] if g["home"] == uid else g["home"]]
            mine = ph if g["home"] == uid else pa
            st = max(mine, key=lambda x: x["score"]) if mine else None
            iz["log"].append({"week": week, "opp": opp["full"], "home": g["home"] == uid, "won": win == uid,
                              "star": {k: st[k] for k in ("name", "pos", "line", "pid")} if st else None,
                              "_score": st["score"] if st else 0})
    standings = sorted(save["teams"], key=lambda t: (t["record"]["w"], powers.get(t["id"], 0)), reverse=True)
    save["standings_cache"] = [{"id": t["id"], "full": t["full"], "conf": t["conference"],
                               "div": t["division"], "w": t["record"]["w"], "l": t["record"]["l"]} for t in standings]
    _update_power_rank(save)        # GridIron Network week-over-week movement
    offer_chance = 0.75 if any(p.get("on_block") for p in current_team(save)["roster"]) else 0.4
    if week <= TRADE_DEADLINE_SOLO and not iz.get("offer") and rng.random() < offer_chance:
        iz["offer"] = _maybe_ai_offer(save, rng)
    owner_weekly(save, week, rng)      # the owner reacts to the week just played
    generate_weekly_agenda(save, week + 1, rng)   # next week's staff/player decisions land
    iz["week"] = week + 1
    if iz["week"] > REG_GAMES:
        _finalize_season(save)
    else:
        write_save(save)
    return save


def _archive_season(teams, season):
    for t in teams:
        tname = t.get("name", t["full"])
        for p in t["roster"]:
            if p.get("stats"):
                car = p.setdefault("career", [])
                if not car or car[-1].get("season") != season:
                    car.append({"season": season, "team": tname, **p["stats"]})
                    del car[:-24]


# --------------------------------------------------------------------------- #
# Dynamic Career Timeline — your franchise's story, threaded from the milestones
# the engine already produces (titles, owner verdicts, breakouts, ceiling
# unlocks, Hall-of-Famers, hot-seat survivals). Persisted so you can scroll back
# through a whole tenure. The thing a GM won't walk away from.
# --------------------------------------------------------------------------- #
def _tl(save, season, kind, icon, head, sub="", pid=None):
    tl = save.setdefault("timeline", [])
    entry = {"season": season, "kind": kind, "icon": icon, "head": head, "sub": sub}
    if pid:
        entry["pid"] = pid
    tl.insert(0, entry)
    save["timeline"] = tl[:80]


def career_timeline(save):
    return save.get("timeline", [])


def _log_season_milestones(save, outcome):
    s = outcome.get("season", save.get("season", 1) - 1)
    team = current_team(save)
    tn, tname = team["full"], team.get("name", team["full"])
    rec = outcome.get("record", {})
    w, l = rec.get("w", 0), rec.get("l", 0)
    exp = outcome.get("expectation", save.get("expectation", {}).get("wins", 0))

    if outcome.get("won_title"):
        _tl(save, s, "title", "🏆", f"CHAMPIONS — {tn} win it all", f"{w}-{l}. You're a champion GM.")
    elif outcome.get("status") == "fired":
        _tl(save, s, "fired", "🌋", f"Fired by {tn}", f"{w}-{l} against a {exp}-win mandate. Ownership moved on.")
    else:
        sub = outcome.get("headline") or (f"Beat the {exp}-win mandate." if w > exp else
                                          f"Fell {exp - w} short of the mandate." if w < exp else "Met the mandate.")
        if save["gm"]["owner_trust"] < 30 and w >= exp:
            _tl(save, s, "hotseat", "🔥", f"{tn} go {w}-{l} — you survive the hot seat", sub)
        else:
            _tl(save, s, "season", "📅", f"{tn} finish {w}-{l}", sub)

    mvp = save.get("season_mvp")
    if mvp and mvp.get("team") == tname:
        _tl(save, s, "mvp", "⭐", f"{mvp['pos']} {mvp['name']} wins MVP", f"{mvp.get('line', '')} — your guy.", mvp.get("pid"))
    for u in (save.get("ceiling_unlocks") or [])[:1]:
        _tl(save, s, "unlock", "🔓", f"{u['pos']} {u['name']} breaks his ceiling",
            f"{u['from']} → {u['to']} — development you coached into him.")
    for b in (save.get("breakouts") or [])[:1]:
        _tl(save, s, "breakout", "📈", f"{b['pos']} {b['name']} breaks out", f"Ceiling revised up to {b['pot']}.")
    for r in (save.get("retirements") or []):
        if r.get("hof"):
            _tl(save, s, "hof", "🎖", f"{r['pos']} {r['name']} retires — Hall of Fame bound",
                r.get("summary", "A legend hangs them up."))


def _finalize_season(save):
    rng = _rng(save["seed"] + save["season"] * 1000 + 991)
    teams = {t["id"]: t for t in save["teams"]}
    powers = {tid: power_rating(t) for tid, t in teams.items()}
    save["leaders"] = stat_leaders(save["teams"])          # from the season actually played
    save["season_mvp"] = stat_mvp(save["teams"])
    save["all_pro"] = all_pro_team(save["teams"])
    update_records(save, save["teams"], save["season"])
    _archive_season(save["teams"], save["season"])

    standings = sorted(save["teams"], key=lambda t: (t["record"]["w"], powers[t["id"]]), reverse=True)
    conf_champs, playoff_ids = [], set()
    for conf in CONFERENCES:
        seeds = [t["id"] for t in standings if t["conference"] == conf][:CONF_PLAYOFF_SEEDS]
        playoff_ids.update(seeds)
        conf_champs.append(_run_playoffs(rng, seeds, powers))
    champion = (conf_champs[0] if _sim_game(rng, powers[conf_champs[0]], powers[conf_champs[1]])
                else conf_champs[1])

    uid = save["current_team_id"]
    rec = dict(teams[uid]["record"])
    made_playoffs, won_title = uid in playoff_ids, champion == uid
    outcome = _evaluate_gm(save, rec, made_playoffs, won_title, teams[champion]["full"])
    outcome["season"] = save["season"]
    _apply_finance(save, rec, won_title)

    gl = (save.get("inseason") or {}).get("log", [])
    if gl:
        best = max(gl, key=lambda x: x.get("_score", 0))
        for g in gl:
            g["best"] = g is best
            g.pop("_score", None)
    save["game_log"] = gl

    # League Almanac ledger — the season goes into the book forever.
    runner_up = conf_champs[1] if champion == conf_champs[0] else conf_champs[0]
    save.setdefault("league_history", []).insert(0, {
        "season": save["season"],
        "champion": teams[champion]["full"],
        "runner_up": teams[runner_up]["full"],
        "mvp": save.get("season_mvp"),
        "user_team": teams[uid]["full"],
        "user_w": rec["w"], "user_l": rec["l"],
        "user_result": ("Champions 🏆" if won_title else
                        "Lost the title game" if uid == runner_up else
                        "Made the playoffs" if made_playoffs else "Missed the playoffs"),
    })
    save["league_history"] = save["league_history"][:60]

    _advance_year(save)
    save["season"] += 1
    save["schedule"] = make_schedule(save["seed"] + save["season"], [t["id"] for t in save["teams"]])
    save["standings_cache"] = [
        {"id": t["id"], "full": t["full"], "conf": t["conference"], "div": t["division"],
         "w": t["record"]["w"], "l": t["record"]["l"], "power": powers[t["id"]],
         "playoff": t["id"] in playoff_ids} for t in standings]
    save["last_champion"] = teams[champion]["full"]
    save["last_outcome"] = outcome
    save["unemployed"] = outcome["status"] == "fired"
    _set_expectation(save)
    owner_statement(save, outcome)
    owner_meeting(save, outcome)
    _log_season_milestones(save, outcome)          # thread the season into the career timeline
    _check_holdouts(save)
    generate_news(save)
    save.pop("inseason", None)
    for t in save["teams"]:
        for p in t["roster"]:
            p.pop("out_until", None)
            p.pop("suspended_until", None)
            p.pop("susp_reason", None)
    write_save(save)
    if outcome["status"] == "retained" and not save.get("offseason_mode"):
        start_draft(save)
    return outcome


def sim_season(save):
    """Play the whole season at once (kept for compatibility / sim-to-end)."""
    if not save.get("inseason"):
        start_inseason(save)
    guard = 0
    while save.get("inseason") and guard < REG_GAMES + 2:
        sim_week(save)
        guard += 1
    return save, save.get("last_outcome")


# --------------------------------------------------------------------------- #
# Live franchise clock — the season runs in REAL TIME. Game-weeks sim on a
# schedule while you're away (lazily, on your next visit), so the league keeps
# moving and there's always something waiting. The hook: a ticking countdown to
# the next game + a "while you were away" recap of everything you missed.
# --------------------------------------------------------------------------- #
LIVE_WEEK_SECONDS = 4 * 3600       # one game-week sims every 4 real hours (default)
LIVE_CATCHUP_CAP = 8               # most weeks auto-played in a single visit


def set_live(save, on):
    save.setdefault("live", {})["on"] = bool(on)
    write_save(save)
    return on


def _ensure_live(save, now):
    lv = save.setdefault("live", {})
    lv.setdefault("on", True)
    lv.setdefault("interval", LIVE_WEEK_SECONDS)
    if "next_week_at" not in lv:
        lv["next_week_at"] = now + lv["interval"]
    return lv


def reset_live_clock(save, now):
    """Restart the countdown (after a manual sim or kickoff)."""
    lv = _ensure_live(save, now)
    lv["next_week_at"] = now + lv["interval"]
    lv["last_seen"] = now


def pending_decision(save):
    """The decision currently awaiting the GM's sign-off. The live clock STOPS
    here — it never auto-resolves a call that's the GM's to make. Returns a short
    descriptor or None. (Trades are the in-season approval; the whole offseason is
    already hands-on.)"""
    iz = save.get("inseason") or {}
    off = iz.get("offer")
    if off:
        return {"kind": "trade", "title": "A trade offer needs your call",
                "detail": (f"{off.get('team', 'A rival')} wants {off.get('want_pos', '')} {off.get('want', '')} — "
                           f"you'd get {off.get('give_pos', '')} {off.get('give', '')}."),
                "grade": off.get("grade")}
    return None


def live_status(save, now):
    lv = save.get("live") or {}
    nxt = lv.get("next_week_at")
    on = lv.get("on", True)
    pend = pending_decision(save) if save.get("inseason") else None
    return {"on": on, "interval": lv.get("interval", LIVE_WEEK_SECONDS),
            "live_season": bool(save.get("inseason")), "paused": bool(pend), "pending": pend,
            "next_in": (max(0, int(nxt - now)) if (on and nxt and save.get("inseason") and not pend) else None)}


def live_tick(save, now):
    """Lazy real-time advance: auto-sim the game-weeks that came due while the GM
    was away and bank a 'while you were away' recap. Safe to call every load."""
    if not save.get("inseason"):
        if save.get("live"):
            save["live"]["last_seen"] = now
        return None
    lv = _ensure_live(save, now)
    if not lv.get("on", True):
        lv["last_seen"] = now
        return None
    if pending_decision(save):                     # already waiting on the GM — freeze the clock
        lv["next_week_at"] = now + lv["interval"]   # don't bank weeks while he deliberates
        lv["last_seen"] = now
        write_save(save)
        return None
    from_week = save["inseason"]["week"]
    results, injuries, played, paused = [], [], 0, False
    while save.get("inseason") and now >= lv["next_week_at"] and played < LIVE_CATCHUP_CAP:
        wk = save["inseason"]["week"]
        sim_week(save)
        played += 1
        lv["next_week_at"] += lv["interval"]
        if save.get("inseason") and pending_decision(save):   # a call popped up — stop for approval
            lv["next_week_at"] = now + lv["interval"]
            paused = True
            iz = save.get("inseason")
            if iz and iz.get("log"):
                g = iz["log"][-1]
                results.append({"week": g["week"], "opp": g["opp"], "won": g["won"], "star": g.get("star")})
            break
        iz = save.get("inseason")
        if iz:
            if iz.get("log"):
                g = iz["log"][-1]
                results.append({"week": g["week"], "opp": g["opp"], "won": g["won"], "star": g.get("star")})
            for inj in iz.get("injuries", []):
                injuries.append({**inj, "week": wk})
        else:                                     # the season finished mid-stretch
            gl = save.get("game_log") or []
            if gl:
                g = gl[-1]
                results.append({"week": g.get("week"), "opp": g.get("opp"), "won": g.get("won"), "star": g.get("star")})
            break
    if lv["next_week_at"] < now:                  # never bank weeks across a long absence
        lv["next_week_at"] = now + lv["interval"]
    lv["last_seen"] = now
    if not played:
        write_save(save)
        return None
    w = sum(1 for r in results if r.get("won"))
    pend = pending_decision(save)
    recap = {"played": played, "results": results, "injuries": injuries[:6],
             "incidents": [i for i in (save.get("incidents") or []) if i.get("week", 0) >= from_week][:5],
             "record": f"{w}-{len(results) - w}", "finalized": not save.get("inseason"),
             "paused": bool(pend), "pending": pend}
    save["away_recap"] = recap
    write_save(save)
    return recap


def _advance_year(save):
    rng = _rng(save["seed"] + save["season"] * 31 + 5)
    sb = staff_bonus(save)
    dev = sb["development"] + (1 if _business(save)["facility"] >= 3 else 0)
    cond = sb["conditioning"]
    uid = save["current_team_id"]
    _apply_role_friction(save)   # Loop 4: paid-but-benched players sour over the year
    for t in save["teams"]:      # dead money ages off as the season closes
        entries = [dict(e, seasons_left=int(e.get("seasons_left", 1)) - 1)
                   for e in t.get("dead_cap_entries", [])]
        t["dead_cap_entries"] = [e for e in entries if e["seasons_left"] > 0]
    breakouts, unlocks, evolution = [], [], []
    for t in save["teams"]:
        my = t["id"] == uid
        for p in t["roster"]:
            pre_ovr = p["overall"]
            pre_pot = p["potential"]
            bonus = (dev + position_coach_dev(save, p["pos"])) if my else 0   # position coaches
            if my and save.get("weekly_ops", {}).get("focus") == "Rookie Development" and p.get("age", 30) <= 24:
                bonus += 1                                                    # a season of rookie reps
            started = p.pop("rep_starter", False) if my else False
            if started and p.get("age", 30) <= 25:
                bonus += 1                                                    # live starter reps develop the young
            hfit = human_development_fit(save, p) if my else None
            if hfit:
                if hfit["score"] >= 82:
                    bonus += 1
                elif hfit["score"] <= 38:
                    bonus -= 1
            if my and cond["gain"]:                          # conditioning coach -> faster growth
                bonus += int(cond["gain"]) + (1 if rng.random() < (cond["gain"] - int(cond["gain"])) else 0)
            p["age"] += 1
            # CONDITIONING UNLOCK: a strong conditioning coach pushes a young player who is
            # bumping his ceiling PAST it - raising the hidden true_pot so he keeps climbing.
            if my and cond["unlock"] > 0 and p.get("age", 30) <= 25:
                cap = p.get("true_pot", p["potential"])
                unlock_chance = cond["unlock"] * (0.60 if hfit and hfit["score"] >= 82 else 0.45)
                if p["overall"] >= cap - 4 and rng.random() < unlock_chance:
                    ncap = min(99, cap + rng.randint(2, 5))
                    if ncap > cap:
                        p["true_pot"] = ncap
                        unlocks.append({"name": p["name"], "pos": p["pos"], "from": cap, "to": ncap,
                                        "why": hfit["label"] if hfit else "development staff"})
            if my and hfit and p.get("age", 30) <= 25 and hfit["score"] >= 88 and rng.random() < 0.12:
                cap = p.get("true_pot", p["potential"])
                ncap = min(99, cap + rng.randint(1, 3))
                if ncap > cap:
                    p["true_pot"] = ncap
                    unlocks.append({"name": p["name"], "pos": p["pos"], "from": cap, "to": ncap,
                                    "why": "perfect staff/system fit"})
            _develop(p, rng, bonus)   # trait-driven growth / decline
            if my and hfit and p.get("age", 30) <= 26:
                if hfit["score"] >= 82 and p["overall"] > pre_ovr:
                    evolution.append({"pid": p["id"], "name": p["name"], "pos": p["pos"], "label": hfit["label"],
                                      "note": "; ".join(hfit["notes"][:2])})
                elif hfit["score"] <= 38:
                    evolution.append({"pid": p["id"], "name": p["name"], "pos": p["pos"], "label": "Miscast",
                                      "note": "; ".join(hfit["notes"][:2])})
            p["last_ovr"] = p["overall"]
            p["contract"]["years"] = max(0, p["contract"]["years"] - 1)
            if my and p["potential"] - pre_pot >= 2:        # a hidden gem revealed himself
                breakouts.append({"name": p["name"], "pos": p["pos"],
                                  "ovr": p["overall"], "pot": p["potential"]})
    save["breakouts"] = breakouts
    save["ceiling_unlocks"] = unlocks
    save["evolution_notes"] = evolution[:8]
    for p in current_team(save).get("practice_squad", []):    # PS develops too
        p["age"] += 1
        _develop(p, rng, dev)
        p.get("contract", {})["years"] = max(0, p.get("contract", {}).get("years", 2) - 1)
    save["retirements"] = process_retirements(save["teams"], save["season"],
                                              save.setdefault("hall_of_fame", []))
    save["hall_of_fame"] = save["hall_of_fame"][:40]
    develop_staff(save, rng)   # coaches age, sharpen/fade, and eventually retire
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


# --------------------------------------------------------------------------- #
# GM grade - "Great Managers" are graded on their whole résumé: wins, titles,
# playoff runs, money earned, and contract acumen.
# --------------------------------------------------------------------------- #
_GM_TIERS = [(88, "Legendary"), (74, "Elite"), (60, "Respected"),
             (46, "Solid"), (30, "Journeyman"), (0, "On the hot seat")]


def _rating_to_grade(r):
    return ("A+" if r >= 90 else "A" if r >= 83 else "A-" if r >= 77 else "B+" if r >= 71 else
            "B" if r >= 63 else "B-" if r >= 56 else "C+" if r >= 49 else "C" if r >= 41 else
            "C-" if r >= 34 else "D" if r >= 26 else "F")


def gm_grade(save):
    gm = save["gm"]
    career = gm.get("career", [])
    seasons = len(career)
    w, l = gm.get("career_w", 0), gm.get("career_l", 0)
    if not (w or l) and career:                       # fallback: parse old saves
        for c in career:
            try:
                cw, cl = str(c.get("record", "0-0")).split("-")
                w += int(cw)
                l += int(cl)
            except (ValueError, AttributeError):
                pass
    games = w + l
    winpct = round(w / games, 3) if games else 0.0
    titles, playoffs = gm.get("titles", 0), gm.get("playoffs", 0)
    money, negos = round(gm.get("money_earned", 0)), gm.get("nego_wins", 0)
    if seasons == 0:
        return {"rating": None, "grade": "—", "tier": "Unproven", "seasons": 0,
                "w": 0, "l": 0, "winpct": 0.0, "titles": 0, "playoffs": 0,
                "money": 0, "negos": 0}
    rating = (winpct * 48 + titles * 9 + playoffs * 2.2 + min(18, money / 140)
              + min(9, negos * 0.4) + gm.get("reputation", 50) * 0.08)
    rating = int(max(1, min(99, round(rating))))
    return {"rating": rating, "grade": _rating_to_grade(rating),
            "tier": next(t for thr, t in _GM_TIERS if rating >= thr), "seasons": seasons,
            "w": w, "l": l, "winpct": winpct, "titles": titles, "playoffs": playoffs,
            "money": money, "negos": negos}


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
    gm["career_w"] = gm.get("career_w", 0) + rec["w"]          # résumé tracking
    gm["career_l"] = gm.get("career_l", 0) + rec["l"]
    if made_playoffs:
        gm["playoffs"] = gm.get("playoffs", 0) + 1
    if won_title:
        gm["titles"] = gm.get("titles", 0) + 1
    return {"status": status, "headline": headline, "record": rec,
            "won_title": won_title, "made_playoffs": made_playoffs,
            "champion": champion_name, "offers": offers, "owner_trust": gm["owner_trust"],
            "expectation": exp}


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
    ("st_coord", "Special Teams Coordinator", "Field position + return/coverage units - a real edge."),
    ("cond_coach", "Conditioning Coach", "The development engine - faster growth, durability, and the man who unlocks a player's ceiling."),
    ("qb_coach", "QB Coach", "Develops your quarterbacks faster."),
    ("oline_coach", "O-Line Coach", "Develops your trenches (OL)."),
    ("db_coach", "DBs Coach", "Develops your secondary (CB/S)."),
    ("head_scout", "Head Scout", "Tightens draft scouting - fewer busts."),
    ("head_medical", "Head of Medical", "Keeps players healthier."),
    ("head_analytics", "Head of Analytics", "Sharper value reads."),
]
# Special-teams "scheme" -> its identity + the home-field edge it adds.
ST_SCHEMES = {"Field Position": 1.0, "Return Game": 0.7, "Coverage Units": 0.8, "Hidden Yardage": 1.1}
# Conditioning STYLE -> what the coach is built to deliver. dev = growth speed,
# dur = durability/health, unlock = how hard he pushes a player PAST his ceiling.
COND_STYLES = {
    "Sports Science":   {"blurb": "Modern load management + recovery. Unlocks raw upside others can't.", "dev": 1.0, "dur": 0.9, "unlock": 1.35},
    "Explosive Power":  {"blurb": "Speed and explosion gains - the fastest development.", "dev": 1.35, "dur": 0.6, "unlock": 1.0},
    "Durability First": {"blurb": "Built to last - your guys stay on the field.", "dev": 0.7, "dur": 1.45, "unlock": 0.7},
    "Old-School Grind": {"blurb": "Relentless, hard-nosed work. Steady growth and grit.", "dev": 1.0, "dur": 1.1, "unlock": 0.95},
}
# Position-coach styles (flavour + a tiny development edge from a great teacher).
COACH_STYLES = ["Technician", "Teacher", "Motivator", "Players' Coach", "Hard-Driver"]
# Coach IDEOLOGY — the development identity. What he's built to get out of people,
# who he's great with, and who he stalls. `vbias` nudges his versatility (Rigid ↔
# Adaptive): a rigid coach is elite for the right roster, shaky for a mixed one.
COACH_IDEOLOGIES = {
    "Teacher":         {"blurb": "Patient developer — turns raw tools into real technique.",
                        "best": "young, raw, high work ethic", "weak": "set-in-their-ways veterans", "vbias": 6},
    "Hard-Nosed":      {"blurb": "Demands toughness and accountability; no excuses.",
                        "best": "the trenches, discipline, low-maturity players", "weak": "fragile confidence", "vbias": -12},
    "Player's Coach":  {"blurb": "Builds trust and loyalty — they run through a wall for him.",
                        "best": "team-first guys, fragile confidence, locker-room risks", "weak": "players who need a firm hand", "vbias": 14},
    "Technician":      {"blurb": "Obsessed with detail and fundamentals.",
                        "best": "film learners, QBs, technique positions", "weak": "instinctive players who overthink", "vbias": -10},
    "Motivator":       {"blurb": "Squeezes the absolute most out of effort and emotion.",
                        "best": "prove-the-doubters, spotlight, streaky players", "weak": "already-driven pros who tune out hype", "vbias": 0},
    "Innovator":       {"blurb": "Scheme creativity — finds edges other staffs miss.",
                        "best": "versatile, high-football-IQ players", "weak": "rigid, system-dependent players", "vbias": 18},
    "Culture Builder": {"blurb": "Sets the standard; the whole room follows.",
                        "best": "young rosters and rebuilds, team-first", "weak": "win-now veteran rooms that want results", "vbias": 8},
}
COACH_TEMPERAMENTS = ["Demanding", "Calm", "Charismatic", "Old-school", "Analytical"]


def _gen_ideology(rng, rating):
    ideo = rng.choice(list(COACH_IDEOLOGIES))
    info = COACH_IDEOLOGIES[ideo]
    versatility = max(15, min(95, int(50 + info["vbias"] + rng.gauss(0, 13) + (rating - 60) * 0.18)))
    return {"ideology": ideo, "versatility": versatility,
            "temperament": rng.choice(COACH_TEMPERAMENTS),
            "specialties": info["best"], "struggles_with": info["weak"]}


# Coaching TREES — the lineages great franchises stay relevant through. A coach's
# branch + track record is a read on him beyond his raw rating. tier 1-3 prestige;
# spec hints what the tree produces (off / def / dev).
COACH_TREES = [
    {"name": "Shoreline tree", "spec": "off", "tier": 3, "blurb": "West-Coast timing and spacing — a quarterback-whisperer lineage."},
    {"name": "Foundry tree", "spec": "def", "tier": 3, "blurb": "Hard-nosed defensive architects — pressure, takeaways, toughness."},
    {"name": "Frostbelt tree", "spec": "off", "tier": 3, "blurb": "Cold-weather power football and roster continuity."},
    {"name": "Vanguard tree", "spec": "dev", "tier": 3, "blurb": "Sports-science pioneers — turning raw athletes into pros."},
    {"name": "Highland tree", "spec": "def", "tier": 2, "blurb": "Multiple fronts and disguised coverages."},
    {"name": "Sundial tree", "spec": "off", "tier": 2, "blurb": "Modern spread / RPO innovators."},
    {"name": "Ironworks tree", "spec": "dev", "tier": 2, "blurb": "Old-school strength and conditioning roots."},
    {"name": "no tree", "spec": "any", "tier": 1, "blurb": "A grinder who's bounced around, learning on the job."},
]
_LEGEND_COACHES = [
    "Hollis Crane", "Walt Boudreau", "Sax Delgado", "Marv Holloway", "Eddie Ransom",
    "Gus Whitfield", "Pell Hargrove", "Cy Lindquist", "Buck Tedesco", "Roman Falk",
    "Dale Mercer", "Vince Okoye", "Hap Sterling", "Lou Castellano", "Ned Vaughn", "Tate Kowalski",
]
# Position coaches -> the position group they develop (+1 dev when rated 60+).
COACH_GROUP = {"qb_coach": ["QB"], "oline_coach": ["OL"], "db_coach": ["CB", "S"]}
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


# Which player STYLES each scheme prizes, by position. A player whose style is
# listed here fits the system; same overall, different style = a worse fit. This
# is the per-player half of scheme (scheme_effect handles the group-power half).
OFFENSE_POS = {"QB", "RB", "WR", "TE", "OL"}
SCHEME_STYLE_FIT = {
    "Air Raid":     {"QB": ["Pocket Passer", "Dual Threat"], "WR": ["Deep Threat", "Slot"], "TE": ["Move TE"]},
    "West Coast":   {"QB": ["Game Manager", "Pocket Passer"], "WR": ["Possession", "Slot"], "TE": ["Move TE", "In-Line Blocker"]},
    "Power Run":    {"QB": ["Game Manager"], "RB": ["Power Back", "Every-Down"], "OL": ["Power"], "TE": ["In-Line Blocker"]},
    "Spread":       {"QB": ["Dual Threat", "RPO Specialist"], "WR": ["Slot", "Deep Threat"], "RB": ["Scat Back", "Every-Down"]},
    "4-3 Front":    {"DL": ["Pass Rusher", "Run Stuffer"], "LB": ["Thumper"]},
    "3-4 Front":    {"LB": ["Thumper", "Coverage"], "DL": ["Run Stuffer"]},
    "Cover 3 Zone": {"CB": ["Zone"], "S": ["Center Field"]},
    "Blitz Heavy":  {"DL": ["Pass Rusher"], "LB": ["Thumper"], "CB": ["Press Man"]},
}


# Playbook PACKAGES — the "how" inside a scheme. Every coordinator carries two
# signature packages; each one fully installs only when a starter matches the
# style it's built around, and an installed package is worth real power.
PLAYBOOK_PACKAGES = {
    "Air Raid": [
        {"name": "Four Verticals", "blurb": "Streaks — stretch the top off the coverage.", "pos": "WR", "styles": ["Deep Threat"]},
        {"name": "Mesh & Crossers", "blurb": "Shallow crossers that win against man.", "pos": "WR", "styles": ["Slot", "Possession"]},
        {"name": "Screen & Bubble Game", "blurb": "Bubbles and tunnel screens — free yards in space.", "pos": "RB", "styles": ["Scat Back"]},
    ],
    "West Coast": [
        {"name": "Quick Slants & Timing", "blurb": "Three-step rhythm throws.", "pos": "WR", "styles": ["Possession", "Slot"]},
        {"name": "Backfield Pass Game", "blurb": "Checkdowns, angles, swing passes to the back.", "pos": "RB", "styles": ["Scat Back", "Every-Down"]},
        {"name": "Play-Action Boot", "blurb": "Keepers off the run look.", "pos": "QB", "styles": ["Game Manager", "Pocket Passer"]},
    ],
    "Power Run": [
        {"name": "Duo & Gap Scheme", "blurb": "Downhill doubles — move the line of scrimmage.", "pos": "OL", "styles": ["Power"]},
        {"name": "Heavy Play-Action Shots", "blurb": "Punish the loaded box over the top.", "pos": "WR", "styles": ["Deep Threat"]},
        {"name": "Under-Center Grind", "blurb": "Clock control, downhill runs, third-and-short money.", "pos": "RB", "styles": ["Power Back", "Every-Down"]},
    ],
    "Spread": [
        {"name": "RPO Package", "blurb": "Read the conflict defender — run or throw.", "pos": "QB", "styles": ["RPO Specialist", "Dual Threat"]},
        {"name": "Jet Motion & Space", "blurb": "Horizontal stress, easy touches.", "pos": "WR", "styles": ["Slot"]},
        {"name": "Tempo Attack", "blurb": "No-huddle — tire the front, steal snaps.", "pos": "RB", "styles": ["Scat Back"]},
    ],
    "4-3 Front": [
        {"name": "Wide-9 Rush", "blurb": "Tee off from the edge.", "pos": "DL", "styles": ["Pass Rusher"]},
        {"name": "Spill & Kill Run Fits", "blurb": "Force it wide, rally and tackle.", "pos": "LB", "styles": ["Thumper"]},
    ],
    "3-4 Front": [
        {"name": "Two-Gap Wall", "blurb": "Occupy blockers, free the backers.", "pos": "DL", "styles": ["Run Stuffer"]},
        {"name": "Edge Pressure Package", "blurb": "Stand-up rushers off both edges.", "pos": "LB", "styles": ["Thumper"]},
    ],
    "Cover 3 Zone": [
        {"name": "Pattern-Match Carry", "blurb": "Zone eyes, man leverage on verticals.", "pos": "CB", "styles": ["Zone"]},
        {"name": "Single-High Robber", "blurb": "The free safety reads the QB's eyes.", "pos": "S", "styles": ["Center Field"]},
    ],
    "Blitz Heavy": [
        {"name": "Zero Pressure Looks", "blurb": "Send more than they can block.", "pos": "LB", "styles": ["Thumper"]},
        {"name": "Press-and-Pray Corners", "blurb": "Man coverage buys the rush its second.", "pos": "CB", "styles": ["Press Man"]},
    ],
}


def playbook_edge(save):
    """Each coordinator package installs when a starter matches its style —
    an installed package is +0.5 power. This is where 'we run RPOs' becomes
    'we run RPOs AND we have the quarterback for it'."""
    team = current_team(save)
    edge, packages = 0.0, []
    for role in ("off_coord", "def_coord"):
        coach = (save.get("staff") or {}).get(role) or {}
        for pk in coach.get("playbook") or []:
            starters = pos_depth(team, pk["pos"])[:ROSTER.get(pk["pos"], 1)]
            hit = next((p for p in starters if p.get("style") in pk["styles"]), None)
            if hit:
                edge += 0.5
                packages.append({"name": pk["name"], "blurb": pk["blurb"], "on": True,
                                 "who": f"{hit['pos']} {hit['name']} ({hit.get('style', '')})"})
            else:
                packages.append({"name": pk["name"], "blurb": pk["blurb"], "on": False,
                                 "who": f"needs a {pk['pos']}: {' / '.join(pk['styles'])}"})
    return {"edge": round(edge, 1), "packages": packages}


def _team_schemes(save):
    """(offensive scheme, defensive scheme) currently installed by your OC / DC."""
    s = save.get("staff", {})
    return s.get("off_coord", {}).get("system"), s.get("def_coord", {}).get("system")


def scheme_identity(save):
    """A readable summary of the system you run + the positions it leans on."""
    oc, dc = _team_schemes(save)
    return {
        "offense": oc, "defense": dc,
        "off_lean": OFF_SCHEMES.get(oc, []),
        "def_lean": DEF_SCHEMES.get(dc, []),
        "installed": bool(oc or dc),
    }


def tactical_fit(save, p):
    """How well one player fits YOUR scheme. Returns pct (None if no scheme is
    installed yet), a label, and which scheme judged him. A 'Square peg' is a
    featured-position player whose style fights the system; an 'Ideal fit' is the
    archetype the scheme was built for."""
    pos = p.get("pos")
    oc, dc = _team_schemes(save)
    scheme = oc if pos in OFFENSE_POS else dc
    style = p.get("style")
    if not scheme or not style:
        return {"pct": None, "label": "—", "scheme": scheme}
    pref = SCHEME_STYLE_FIT.get(scheme, {}).get(pos)
    lean = pos in (OFF_SCHEMES.get(scheme) or DEF_SCHEMES.get(scheme) or [])
    base = 62
    if pref is None:                       # scheme is indifferent to this spot
        pct, label = base, "Scheme-neutral"
    elif style in pref:
        pct = base + (30 if lean else 18)
        label = "Ideal fit" if lean else "Good fit"
    else:
        pct = base - (20 if lean else 8)
        label = "Square peg" if lean else "Off-scheme"
    return {"pct": max(25, min(99, pct)), "label": label, "scheme": scheme, "style": style}


def scheme_value(save, p):
    """A player's value SEEN THROUGH your scheme: raw trade value bent by fit.
    Drives the draft board / FA board so the system - not generic OVR - ranks who
    you should chase. Returns (adjusted_value, fit_dict)."""
    base = trade_value(p)
    fit = tactical_fit(save, p)
    if fit["pct"] is None:
        return base, fit
    factor = 0.82 + (fit["pct"] - 62) / 110.0     # ~0.5 square peg .. ~1.16 ideal
    return round(base * max(0.5, factor), 1), fit


def _opposed(a, b):
    return {a, b} == {"Analytics", "Old School"}


def _role_spec(role):
    if role in ("off_coord", "qb_coach", "oline_coach"):
        return "off"
    if role in ("def_coord", "db_coach", "st_coord"):
        return "def"
    if role in ("cond_coach", "head_medical"):
        return "dev"
    return "any"


def _coach_pedigree(rng, rating, role):
    """A coach's lineage + résumé — who he came up under, his stops, and his track
    record. Correlated with his rating (with noise) so it READS as a real signal:
    a prestigious tree + a strong record usually means a strong hire."""
    bias = max(0.0, min(1.0, (rating - 48) / 38.0))          # 0..1 implied quality
    implied = 1 + round(bias * 2)                            # 1..3 tree tier
    spec = _role_spec(role)
    weights = []
    for t in COACH_TREES:
        w = 1.0 / (1 + abs(t["tier"] - implied))
        if t["spec"] == spec:
            w *= 1.8                                         # lineages tend to match the craft
        if t["name"] == "no tree":
            w = (1.4 if rating < 56 else 0.25)
        weights.append(w)
    tree = rng.choices(COACH_TREES, weights=weights, k=1)[0]
    mentor = rng.choice(_LEGEND_COACHES)
    experience = max(3, int(4 + bias * 16 + rng.triangular(-3, 9, 2)))
    teams = [f"{c} {m}" for _, _, c, m, _ in NFL_TEAMS]
    rng.shuffle(teams)
    ladder = ["Assistant", "Position Coach", "Coordinator"]
    n = min(3, 1 + experience // 7)
    stops = [{"team": teams[i], "role": ladder[min(i, 2)], "years": rng.randint(2, 5)} for i in range(n)]
    pros = max(0, int(bias * 6 + rng.triangular(-1, 4, 1)))
    playoffs = max(0, int(bias * 5 + rng.triangular(-1, 3, 0)))
    rings = 1 + rng.randint(0, 1) if (rating >= 84 and rng.random() < 0.45) else (1 if rating >= 78 and rng.random() < 0.3 else 0)
    rep = max(10, min(99, round(rating * 0.72 + tree["tier"] * 8 + rng.gauss(0, 5))))
    label = ("Proven winner" if rep >= 82 else "Highly respected" if rep >= 70 else
             "Rising name" if (rep >= 55 and experience < 11) else "Solid hire" if rep >= 55 else
             "Journeyman" if experience >= 10 else "Unproven")
    return {"tree": tree["name"], "tree_blurb": tree["blurb"], "spec": tree["spec"],
            "mentor": mentor, "experience": experience, "stops": stops,
            "pros": pros, "playoffs": playoffs, "rings": rings, "rep": rep, "label": label}


def _gen_staff(rng, role):
    s = {"id": f"s{rng.randint(100000, 999999)}", "name": _gen_name(rng),
         "role": role, "rating": int(rng.triangular(42, 86, 60))}
    if role in ("off_coord", "def_coord"):
        s["philosophy"] = rng.choice(["Analytics", "Old School", "Balanced"])
        s["system"] = rng.choice(list(OFF_SCHEMES if role == "off_coord" else DEF_SCHEMES))
        pool = PLAYBOOK_PACKAGES.get(s["system"], [])
        s["playbook"] = rng.sample(pool, k=min(2, len(pool)))
    elif role == "st_coord":
        s["system"] = rng.choice(list(ST_SCHEMES))
    elif role == "cond_coach":
        s["system"] = rng.choice(list(COND_STYLES))     # his training philosophy
    elif role in COACH_GROUP:
        s["style"] = rng.choice(COACH_STYLES)
    s["ped"] = _coach_pedigree(rng, s["rating"], role)
    s.update(_gen_ideology(rng, s["rating"]))
    s["age"] = min(68, max(31, 26 + s["ped"]["experience"] + rng.randint(0, 5)))
    return s


def conditioning_dev(save):
    """The Conditioning Coach is the development engine. Quality (rating) × his
    training STYLE drives: extra growth, durability, and `unlock` — the chance he
    pushes a young player PAST his original ceiling. He is the reason a capped
    prospect can keep climbing."""
    c = save.get("staff", {}).get("cond_coach")
    if not c:
        return {"gain": 0.0, "durability": 0, "unlock": 0.0, "style": None, "rating": 0}
    r = c.get("rating", 50)
    st = COND_STYLES.get(c.get("system"), COND_STYLES["Old-School Grind"])
    q = max(0.0, (r - 48) / 52.0)                       # ~0..0.8 quality
    return {"gain": round(q * 1.3 * st["dev"], 2),
            "durability": round(q * 34 * st["dur"]),
            "unlock": round(q * st["unlock"], 3),
            "style": c.get("system"), "rating": r, "blurb": st["blurb"]}


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
    num = den = 0.0
    for pos, slots in ROSTER.items():
        best = pos_depth(team, pos)[:slots]
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


def special_teams(save):
    """Special Teams Coordinator -> a home-field-style power edge (rating + specialty)."""
    stc = save.get("staff", {}).get("st_coord")
    if not stc:
        return 0.0
    return round(max(-0.5, (stc.get("rating", 50) - 50) * 0.05)
                 + ST_SCHEMES.get(stc.get("system"), 0.5), 2)


def position_coach_dev(save, pos):
    """+1 development for a position group when its coach is hired and rated 60+."""
    s = save.get("staff", {})
    for role, group in COACH_GROUP.items():
        if pos in group and _sr(s, role) >= 60:
            return 1
    return 0


def _position_coach(save, pos):
    for role, group in COACH_GROUP.items():
        if pos in group:
            return save.get("staff", {}).get(role)
    if pos in OFFENSE_POS:
        return save.get("staff", {}).get("off_coord")
    return save.get("staff", {}).get("def_coord")


def human_development_fit(save, p):
    """How well this staff/system can turn this player into himself.
    High score means the environment fits his style, learning mode, and motivation."""
    ensure_human_profile(p)
    fit = tactical_fit(save, p)
    coach = _position_coach(save, p.get("pos"))
    cond = save.get("staff", {}).get("cond_coach")
    score = 50
    notes = []

    if fit.get("pct") is not None:
        score += round((fit["pct"] - 62) * 0.45)
        notes.append(f"{fit['label']} in {fit.get('scheme') or 'current system'}")

    pref = p.get("coach_pref")
    coach_style = (coach or {}).get("style") or (coach or {}).get("philosophy")
    if coach and (coach_style == pref or (pref == "Teacher" and coach_style == "Technician")):
        score += 14
        notes.append(f"responds to a {pref} coach")
    elif coach and coach_style:
        score -= 4
        notes.append(f"coach style is {coach_style}, not his preferred {pref}")
    else:
        score -= 8
        notes.append("no dedicated position coach shaping him")

    learning = p.get("learning")
    cond_style = (cond or {}).get("system")
    if learning == "Film Learner" and save.get("staff", {}).get("head_analytics"):
        score += 8
        notes.append("analytics staff feeds his film learning")
    if learning == "Repetition" and cond_style in ("Old-School Grind", "Explosive Power"):
        score += 8
        notes.append(f"{cond_style} matches his repetition-based growth")
    if learning == "Structure" and cond_style in ("Sports Science", "Durability First"):
        score += 8
        notes.append(f"{cond_style} gives him structure")
    if learning == "Confidence" and p.get("confidence", 60) < 58:
        score -= 7
        notes.append("confidence is fragile; early role clarity matters")

    motivation = p.get("motivation")
    if motivation == "Spotlight" and p.get("overall", 0) >= 76:
        score += 5
    elif motivation == "Team-First" and p.get("morale", 70) >= 70:
        score += 5
    elif motivation == "Prove Them Wrong" and p.get("overall", 0) < 72:
        score += 6

    # coach IDEOLOGY + versatility (Phase 2): an adaptive coach bends to fit more
    # players; a rigid one is great for the right guy and risky otherwise.
    if coach and coach.get("versatility") is not None:
        vers = coach.get("versatility", 50)
        score += round((vers - 50) * 0.12)
        if vers >= 72:
            notes.append("adaptive coach — bends to fit him")
        elif vers <= 35 and (coach_style != pref):
            notes.append("rigid coach — risky unless he fits the system")
        temp = coach.get("temperament")
        if temp == "Demanding" and p.get("confidence", 65) < 55:
            score -= 5
            notes.append("a demanding coach can rattle his fragile confidence")
        elif temp == "Charismatic" and p.get("work_ethic", 65) < 58:
            score += 5
            notes.append("a charismatic coach pulls more effort out of him")

    score += round((p.get("work_ethic", 65) - 65) * 0.18)
    score += round((p.get("confidence", 65) - 65) * 0.10)
    score = max(15, min(99, int(score)))
    label = "Perfect environment" if score >= 84 else "Strong fit" if score >= 70 else "Workable" if score >= 55 else "Miscast"
    return {"score": score, "label": label, "notes": notes[:4],
            "coach": (coach or {}).get("name", ""), "coach_style": coach_style or "",
            "motivation": motivation, "learning": learning, "coach_pref": pref}


def coach_roster_fit(save, coach):
    """How well a coach fits the ROSTER you already have — so you hire for who
    you've got, not a raw OVR. Returns a 0-100 score + readable notes."""
    team = current_team(save)
    role = coach.get("role")
    if role in COACH_GROUP:
        pool = [p for p in team["roster"] if p["pos"] in COACH_GROUP[role]]
        label = "/".join(COACH_GROUP[role])
    elif role == "off_coord":
        pool, label = [p for p in team["roster"] if p["pos"] in OFFENSE_POS], "offense"
    elif role == "def_coord":
        pool, label = [p for p in team["roster"] if p["pos"] not in OFFENSE_POS and p["pos"] != "K"], "defense"
    elif role in ("cond_coach", "head_medical"):
        pool, label = [p for p in team["roster"] if p.get("age", 30) <= 26], "young core"
    else:
        pool, label = team["roster"], "roster"
    pool = sorted(pool, key=lambda p: -p["overall"])[:14]
    if not pool:
        return {"score": 50, "notes": ["No relevant players to coach yet."]}

    ideo, vers = coach.get("ideology"), coach.get("versatility", 50)
    young = sum(1 for p in pool if p.get("age", 30) <= 24)
    fragile = sum(1 for p in pool if p.get("confidence", 65) < 55)
    grinders = sum(1 for p in pool if p.get("work_ethic", 65) >= 80)
    motivated = sum(1 for p in pool if p.get("motivation") in ("Prove Them Wrong", "Prove the doubters", "Spotlight"))
    score = 50 + (vers - 50) * 0.28
    notes = []
    if ideo in ("Teacher", "Culture Builder") and young >= max(2, len(pool) * 0.4):
        score += 14
        notes.append(f"ideal for your young {label} group")
    if ideo == "Player's Coach" and fragile >= 2:
        score += 12
        notes.append("your fragile-confidence guys will buy in")
    if ideo == "Hard-Nosed" and grinders >= 2:
        score += 8
        notes.append("your high-effort room responds to his edge")
    if ideo == "Hard-Nosed" and fragile >= 3:
        score -= 13
        notes.append("too many fragile players for his hard edge")
    if ideo == "Motivator" and motivated >= 2:
        score += 9
        notes.append("he lights up your chip-on-the-shoulder personalities")
    if vers >= 72:
        notes.append("adaptive — fits a mixed room")
    elif vers <= 35:
        notes.append("rigid — elite for the right roster, risky for a mix")
    return {"score": max(15, min(99, round(score))), "notes": notes[:3]}


def staff_bonus(save):
    s = save.get("staff", {})
    coord_avg = (_sr(s, "off_coord") + _sr(s, "def_coord")) / 2.0
    cond = conditioning_dev(save)
    return {
        "power": coaching_power(save),
        "scheme": scheme_effect(save),
        "playbook": playbook_edge(save),
        "special_teams": special_teams(save),
        "scouting": round((_sr(s, "head_scout") - 50) * 0.6, 1),
        "development": 1 if coord_avg >= 65 else 0,
        "medical": _sr(s, "head_medical") + cond["durability"],   # conditioning keeps them healthy
        "analytics": _sr(s, "head_analytics"),
        "conditioning": cond,
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
    for k in ("philosophy", "system", "style", "ped", "age", "former_player", "playbook",
              "ideology", "versatility", "temperament", "specialties", "struggles_with"):
        if k in cand:
            entry[k] = cand[k]
    save.setdefault("staff", {})[role] = entry
    market[role] = [c for c in market.get(role, []) if c["id"] != candidate_id]
    write_save(save)
    return True, f"Hired {cand['name']} ({cand['rating']} OVR) for ${cost}M."


def fire_staff(save, role):
    save.get("staff", {}).pop(role, None)
    write_save(save)
    return True


# --------------------------------------------------------------------------- #
# Staff lifecycle — coaches are people too. They age a year every offseason,
# the young sharpen, the old fade and eventually retire, and the market
# backfills with fresh names PLUS retired players who move into coaching.
# Old saves get missing profiles (pedigree/ideology/age) backfilled on load.
# --------------------------------------------------------------------------- #
_ROLE_LABELS = {role: label for role, label, _ in STAFF_ROLES}


def _staff_rng(save, *parts):
    """Deterministic rng per save + coach so backfill is stable across loads."""
    h = 0
    for part in parts:
        for ch in str(part):
            h = (h * 131 + ord(ch)) % 1000003
    return _rng(int(save.get("seed", 1) or 1) + h)


def _backfill_staff_entry(save, role, entry):
    """Give a pre-profile coach the fields hires generate today (pedigree,
    ideology, style/system, age). Never overwrites what he already has."""
    rng = _staff_rng(save, role, entry.get("name", ""))
    rating = int(entry.get("rating", 55) or 55)
    changed = False
    if role in ("off_coord", "def_coord"):
        if not entry.get("philosophy"):
            entry["philosophy"] = rng.choice(["Analytics", "Old School", "Balanced"]); changed = True
        if not entry.get("system"):
            entry["system"] = rng.choice(list(OFF_SCHEMES if role == "off_coord" else DEF_SCHEMES)); changed = True
        if not entry.get("playbook"):
            pool = PLAYBOOK_PACKAGES.get(entry["system"], [])
            entry["playbook"] = rng.sample(pool, k=min(2, len(pool))); changed = True
    elif role == "st_coord" and not entry.get("system"):
        entry["system"] = rng.choice(list(ST_SCHEMES)); changed = True
    elif role == "cond_coach" and not entry.get("system"):
        entry["system"] = rng.choice(list(COND_STYLES)); changed = True
    elif role in COACH_GROUP and not entry.get("style"):
        entry["style"] = rng.choice(COACH_STYLES); changed = True
    if not entry.get("ped"):
        entry["ped"] = _coach_pedigree(rng, rating, role); changed = True
    if not entry.get("ideology"):
        entry.update(_gen_ideology(rng, rating)); changed = True
    if not entry.get("age"):
        exp = int((entry.get("ped") or {}).get("experience", 8) or 8)
        entry["age"] = min(68, max(31, 26 + exp + rng.randint(0, 5))); changed = True
    return changed


def ensure_staff_profiles(save):
    """Backfill profiles for coaches hired (or generated) before pedigrees,
    ideologies, and ages existed. Returns True if anything changed so the
    caller can persist once."""
    changed = False
    for role, entry in (save.get("staff") or {}).items():
        if isinstance(entry, dict) and _backfill_staff_entry(save, role, entry):
            changed = True
    for role, cands in (save.get("staff_market") or {}).items():
        for cand in cands or []:
            if isinstance(cand, dict) and _backfill_staff_entry(save, role, cand):
                changed = True
    return changed


def develop_staff(save, rng):
    """One offseason of staff life: everyone ages a year, young coaches sharpen,
    veterans plateau, old coaches fade — winning buys everyone a bump — and the
    ones at the end of the road hang up the whistle."""
    ensure_staff_profiles(save)
    staff = save.get("staff") or {}
    winner = (current_team(save).get("record", {}).get("w", 0) or 0) >= 10
    retired = []
    for role, c in list(staff.items()):
        if not isinstance(c, dict):
            continue
        c["age"] = int(c.get("age", 48) or 48) + 1
        ped = c.get("ped")
        if isinstance(ped, dict):
            ped["experience"] = int(ped.get("experience", 5) or 5) + 1
        age = c["age"]
        drift = (rng.randint(0, 2) if age <= 42 else rng.randint(-1, 1) if age <= 55 else -rng.randint(0, 2))
        if winner and rng.random() < 0.5:
            drift += 1
        c["rating"] = max(40, min(95, int(c.get("rating", 55) or 55) + drift))
        if age >= 70 or (age >= 61 and rng.random() < (age - 58) * 0.055):
            retired.append((role, c))
    for role, c in retired:
        staff.pop(role, None)
        _tl(save, save.get("season", 1), "staff", "🎓",
            f"{_ROLE_LABELS.get(role, role)} {c.get('name', 'Coach')} retires at {c.get('age', '?')}",
            "Hangs up the whistle after "
            f"{int((c.get('ped') or {}).get('experience', 0) or 0)} years on the sidelines. "
            "New candidates are on the market.")
    save["staff_retirements"] = [
        {"role": role, "label": _ROLE_LABELS.get(role, role),
         "name": c.get("name", ""), "age": c.get("age")}
        for role, c in retired
    ]
    _maybe_poach_staff(save, rng, winner)


def _maybe_poach_staff(save, rng, winner):
    """Success gets your staff raided: after the season a rival can come for
    your hottest coach. Match the offer with a retention bonus or he walks at
    kickoff. At most one attempt a year, aimed at the best remaining name."""
    if save.get("staff_poach"):
        return                                     # one live offer at a time
    staff = save.get("staff") or {}
    hot = []
    for role, c in staff.items():
        if not isinstance(c, dict):
            continue
        rating = int(c.get("rating", 0) or 0)
        if rating < 72 or int(c.get("age", 48) or 48) >= 62:
            continue
        p = min(0.35, (rating - 70) * 0.03 + (0.10 if winner else 0.0))
        hot.append((rating, role, c, p))
    hot.sort(reverse=True, key=lambda x: x[0])
    for rating, role, c, p in hot[:2]:             # only the top names draw calls
        if rng.random() >= p:
            continue
        rivals = [t["full"] for t in save.get("teams", []) if t["id"] != save.get("current_team_id")]
        cost = round(staff_cost(rating) * 0.6, 1)
        save["staff_poach"] = {"role": role, "label": _ROLE_LABELS.get(role, role),
                               "name": c.get("name", ""), "rating": rating,
                               "rival": rng.choice(rivals) if rivals else "a rival club",
                               "cost": cost}
        _tl(save, save.get("season", 1), "staff", "📞",
            f"The {save['staff_poach']['rival']} want {c.get('name', 'your coach')}",
            f"Your {_ROLE_LABELS.get(role, role)} is their top target. Match with a ${cost}M retention bonus or he walks at kickoff.")
        return


def set_gm_philosophy(save, philosophy):
    """The GM/HC can reshape his coaching identity mid-career. Free to do —
    the price is real: coordinator synergy and clashes re-read immediately."""
    if philosophy not in PHILOSOPHIES:
        return False, "Pick a real philosophy."
    old = save["gm"].get("philosophy", "Balanced")
    if philosophy == old:
        return False, f"You already coach {PHILOSOPHIES[philosophy]['label']}."
    save["gm"]["philosophy"] = philosophy
    _tl(save, save.get("season", 1), "staff", "🧭",
        f"New identity: {PHILOSOPHIES[philosophy]['label']} football",
        f"You reshaped your head-coaching philosophy (was {PHILOSOPHIES[old]['label']}). "
        "Coordinator synergy and clashes re-read immediately.")
    write_save(save)
    return True, (f"You now coach {PHILOSOPHIES[philosophy]['label']} football. "
                  "Check your coordinators — synergy and friction just moved.")


def resolve_staff_poach(save, action):
    """GM answers the rival's offer: match (pay the retention bonus) or decline
    (he leaves now). Returns (ok, msg) like hire_staff."""
    poach = save.get("staff_poach")
    if not poach:
        return False, "There is no offer on the table."
    role, name = poach.get("role", ""), poach.get("name", "your coach")
    if action == "match":
        cost = float(poach.get("cost", 0) or 0)
        b = _business(save)
        if b["cash"] < cost:
            return False, f"Keeping {name} costs ${cost}M - you have ${b['cash']}M."
        b["cash"] = round(b["cash"] - cost, 1)
        save.pop("staff_poach", None)
        _tl(save, save.get("season", 1), "staff", "🤝",
            f"{name} stays — offer matched",
            f"You paid a ${cost}M retention bonus to keep your {poach.get('label', role)} in the building.")
        write_save(save)
        return True, f"{name} stays. The ${cost}M retention bonus is paid."
    staff = save.get("staff") or {}
    if staff.get(role, {}).get("name") == name:
        staff.pop(role, None)
    save.pop("staff_poach", None)
    _tl(save, save.get("season", 1), "staff", "👋",
        f"{name} leaves for the {poach.get('rival', 'rival')}",
        f"You let your {poach.get('label', role)} take the offer. The market has candidates below.")
    write_save(save)
    return True, f"{name} takes the {poach.get('rival', 'rival')} job. His seat is open."


def _expire_staff_poach(save):
    """Kickoff deadline: an unanswered offer means he's gone."""
    poach = save.pop("staff_poach", None)
    if not poach:
        return
    role, name = poach.get("role", ""), poach.get("name", "your coach")
    staff = save.get("staff") or {}
    if staff.get(role, {}).get("name") == name:
        staff.pop(role, None)
    _tl(save, save.get("season", 1), "staff", "👋",
        f"{name} left while you sat on the offer",
        f"The {poach.get('rival', 'rival')} hired your {poach.get('label', role)} away — the offer expired at kickoff.")


_PLAYER_COACH_ROLE = {"QB": "qb_coach", "OL": "oline_coach", "CB": "db_coach", "S": "db_coach",
                      "DL": "def_coord", "LB": "def_coord", "EDGE": "def_coord",
                      "WR": "off_coord", "TE": "off_coord", "RB": "off_coord",
                      "K": "st_coord", "P": "st_coord"}


def inject_player_coaches(save, rng):
    """Some of this offseason's retirees move straight into coaching: the best
    of them (peak 76+) can show up in the fresh staff market at a role that
    fits the position they played, carrying a Former Player profile."""
    market = save.get("staff_market") or {}
    pool = [r for r in (save.get("retirements") or []) if int(r.get("peak", 0) or 0) >= 76]
    pool.sort(key=lambda r: -(int(r.get("peak", 0) or 0) + int(r.get("all_pro", 0) or 0) * 2))
    added = 0
    for r in pool:
        if added >= 2:
            break
        if rng.random() > 0.6:
            continue
        role = _PLAYER_COACH_ROLE.get(str(r.get("pos", "")).upper(), "cond_coach")
        cand = _gen_staff(rng, role)
        peak = int(r.get("peak", 76) or 76)
        seasons = int(r.get("seasons", 0) or 0)
        cand["name"] = r.get("name", cand["name"])
        cand["rating"] = max(42, min(79, int(44 + (peak - 70) * 0.55
                                             + int(r.get("all_pro", 0) or 0) * 2.5
                                             + (5 if r.get("hof") else 0))))
        cand["age"] = min(46, 25 + max(4, seasons) + rng.randint(1, 3))
        ped = cand.get("ped") or {}
        ped.update({
            "experience": 0,
            "stops": [{"team": r.get("team", ""), "role": "Player", "years": seasons}],
            "pros": 0, "playoffs": 0, "rings": 0,
            "rep": max(35, min(90, 30 + peak // 2 + (12 if r.get("hof") else 0))),
            "label": "HOF player, rookie coach" if r.get("hof") else "Former player",
        })
        cand["ped"] = ped
        cand["former_player"] = {"pos": r.get("pos", ""), "peak": peak,
                                 "seasons": seasons, "hof": bool(r.get("hof"))}
        market.setdefault(role, []).append(cand)
        _tl(save, save.get("season", 1), "staff", "🎓",
            f"{r.get('pos', '')} {r.get('name', '')} moves into coaching",
            f"Joins the {_ROLE_LABELS.get(role, role)} market after {seasons} seasons on the field.")
        added += 1


# --------------------------------------------------------------------------- #
# Scout Recommendation layer — the scout stops being a grade machine. He compares
# a player's RAW (leaguewide) value to how he projects in YOUR building (scheme +
# human/dev fit) and returns a verdict + reason + risk. A weak head scout gives a
# fuzzier read, so the scout hire finally pays for itself.
# --------------------------------------------------------------------------- #
_SCOUT_TIER = {"Must Target": "hi", "Strong Fit": "hi", "System Bet": "mid",
               "Raw Talent Only": "mid", "Scout Disagreement": "mid", "Bad Fit Here": "lo"}


def scout_report(save, p):
    league_grade = int(p.get("grade", p.get("overall", 60)) or 60)
    pot = int(p.get("pot_grade", p.get("potential", league_grade)) or league_grade)
    tf = tactical_fit(save, p)
    hf = human_development_fit(save, p)
    cond = conditioning_dev(save)
    scheme_delta = ((tf["pct"] - 62) * 0.18) if tf.get("pct") is not None else 0.0
    human_delta = (hf["score"] - 50) * 0.14
    gap = max(0, pot - league_grade)
    project = gap >= 8 and league_grade <= 76
    project_delta = (cond["unlock"] * 6 - 2) if project else 0.0
    here = max(40, min(99, round(league_grade + scheme_delta + human_delta + project_delta)))
    edge = here - league_grade
    acc = max(20, min(95, save["gm"]["ratings"].get("drafting", 50) + staff_bonus(save)["scouting"]))

    bits = []
    if tf.get("pct") is not None and tf["label"] in ("Ideal fit", "Good fit"):
        bits.append(f"his {tf.get('style', 'game')} fits your {tf['scheme']}")
    if hf["score"] >= 62:
        bits.append("your staff coaches him the way he learns")
    if project and cond["unlock"] >= 0.6:
        bits.append("your conditioning staff can unlock his ceiling")
    reason = (("; ".join(bits[:2]) + ".") if bits
              else f"A {league_grade}-grade talent, but nothing in your building lifts him beyond that.")

    if tf.get("pct") is not None and tf["label"] == "Square peg":
        risk = "Square peg in your scheme — expect less than his rating."
    elif not scheme_identity(save)["installed"]:
        risk = "No scheme installed yet — fit is a guess until you hire coordinators."
    elif p.get("confidence", 65) < 55:
        risk = "Fragile confidence — bury him on the depth chart and he stalls."
    elif tf.get("pct") is not None and tf["pct"] >= 80:
        risk = "Scheme-dependent — his value drops if you change your OC/DC."
    elif project and not cond["style"]:
        risk = "He's a project and you have no conditioning coach to grow him."
    else:
        risk = "Standard development risk."

    if acc < 45 and abs(edge) >= 3:
        rec = "Scout Disagreement"
    elif edge >= 8 and here >= 75:
        rec = "Must Target"
    elif edge >= 4:
        rec = "Strong Fit"
    elif project and project_delta > 0 and edge >= 0:
        rec = "System Bet"
    elif edge <= -7:
        rec = "Bad Fit Here"
    elif league_grade >= 78 and edge < 2:
        rec = "Raw Talent Only"
    elif edge >= 2:
        rec = "Strong Fit"
    elif project and project_delta > 0:        # a project you can actually develop here
        rec = "System Bet"
    elif league_grade >= 70:
        rec = "Raw Talent Only"
    else:
        rec = "Bad Fit Here"

    age = p.get("age", 24)
    dev_path = ("Plug-and-play starter" if gap <= 3 and league_grade >= 75 else
                "Year-1 role, Year-2 starter push" if age <= 24 else
                "Rotational now, upside with reps")
    best_env = (f"a {p.get('coach_pref', 'hands-on')} coach, {(p.get('learning') or 'structured reps')}, "
                f"and a system built around a {p.get('style', 'player like him')}")
    return {"rec": rec, "tier": _SCOUT_TIER.get(rec, "mid"), "reason": reason, "risk": risk,
            "here": here, "league": league_grade, "edge": edge, "best_env": best_env,
            "dev_path": dev_path, "confident": acc >= 60}


# --------------------------------------------------------------------------- #
# Rookie draft + scouting
# --------------------------------------------------------------------------- #
# Combine baselines per position — the numbers scouts argue about. A prospect's
# athletic tilt is correlated with his hidden quality (with real noise), so the
# testing is a genuine but imperfect signal.
_COMBINE_40 = {"QB": 4.85, "RB": 4.52, "WR": 4.47, "TE": 4.72, "OL": 5.22,
               "DL": 4.95, "LB": 4.68, "CB": 4.45, "S": 4.52, "K": 5.05}
_COMBINE_BENCH = {"QB": 16, "RB": 20, "WR": 14, "TE": 20, "OL": 28,
                  "DL": 27, "LB": 23, "CB": 14, "S": 17, "K": 8}


def _gen_combine(rng, pos, true_ovr, true_pot):
    ath = ((true_ovr + true_pot) / 2 - 62) / 26.0 + rng.gauss(0, 0.45)
    base40 = _COMBINE_40.get(pos, 4.8)
    forty = round(base40 - 0.11 * ath + rng.gauss(0, 0.05), 2)
    bench = max(4, int(_COMBINE_BENCH.get(pos, 18) + 3.5 * ath + rng.gauss(0, 2.5)))
    vert = round(max(24.0, 33 + 3.2 * ath + rng.gauss(0, 1.6)), 1)
    cone = round(7.05 - 0.13 * ath + rng.gauss(0, 0.09), 2)
    traits = []
    if forty <= base40 - 0.10:
        traits.append("burner")
    elif forty >= base40 + 0.10:
        traits.append("slow feet")
    if bench >= _COMBINE_BENCH.get(pos, 18) + 4:
        traits.append("weight-room strong")
    if vert >= 36.5:
        traits.append("explosive")
    if cone <= 6.85:
        traits.append("bendy mover")
    if not traits:
        traits.append("solid tester")
    return {"forty": forty, "bench": bench, "vert": vert, "cone": cone, "traits": traits}


def _gen_prospect(rng, pos):
    true_ovr = max(50, min(90, int(rng.triangular(52, 86, 64))))
    true_pot = min(99, true_ovr + int(rng.triangular(2, 26, 12)))
    return {"id": f"d{rng.randint(100000, 999999)}", "name": _gen_name(rng), "pos": pos,
            "age": rng.randint(21, 23), "true_ovr": true_ovr, "true_pot": true_pot,
            "dev": rng.choice(["Normal", "Normal", "Star", "Slow", "Late Bloomer"]),
            "style": _style_for(rng, pos),
            "combine": _gen_combine(rng, pos, true_ovr, true_pot),
            **_gen_background(rng),
            **_gen_human_profile(rng)}


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
            "overall": p["true_ovr"], "potential": p["true_pot"],
            "true_pot": _roll_true_pot(random, p["true_ovr"], p["true_pot"], p["age"]),
            "dev": p["dev"],
            "style": p.get("style") or _style_for(random, p["pos"]),
            "contract": {"years": 4, "aav": aav, "guaranteed": round(aav * 0.6, 1)},
            "morale": 75, "injury_risk": "Low",
            "personality": p.get("personality"), "hometown": p.get("hometown"),
            "high_school": p.get("high_school"), "college": p.get("college"),
            "motivation": p.get("motivation"), "learning": p.get("learning"),
            "coach_pref": p.get("coach_pref"), "confidence": p.get("confidence", 65),
            "work_ethic": p.get("work_ethic", 65)}


# --------------------------------------------------------------------------- #
# Draft capital — the Jimmy Johnson trade-value chart (the real one NFL front
# offices used for decades). Round 1 is the exact chart; later rounds follow its
# halving decay. Picks are OWNABLE assets that can be traded — the "War Room"
# play: trade DOWN off a premium pick to stockpile a bigger pile of value.
# --------------------------------------------------------------------------- #
_PICK_VALUE_R1 = [3000, 2600, 2200, 1800, 1700, 1600, 1500, 1400, 1350, 1300,
                  1250, 1200, 1150, 1100, 1050, 1000, 950, 900, 875, 850,
                  800, 780, 760, 740, 720, 700, 680, 660, 640, 620, 600, 590]


def pick_value(overall):
    """Jimmy Johnson chart value for an overall draft slot."""
    if overall <= 32:
        return _PICK_VALUE_R1[overall - 1]
    return max(1, round(590 * 0.5 ** ((overall - 32) / 26.0)))


def future_pick_value(rnd, n=LEAGUE_SIZE):
    """A next-year pick, valued at a mid-round slot and discounted for the wait."""
    mid = (rnd - 1) * n + n // 2
    return max(1, round(pick_value(mid) * 0.72))


def _team_abbr(save, tid):
    t = next((x for x in save["teams"] if x["id"] == tid), None)
    return ((t.get("name") or t["full"])[:3].upper()) if t else "?"


def start_draft(save):
    if save.get("draft_pending"):
        return
    rng = _rng(save["seed"] + save["season"] * 77 + 13)
    cls = generate_draft_class(rng)
    scout_bonus = 9 if save.get("weekly_ops", {}).get("scout") == "Draft Class" else 0   # scouts worked the class
    acc = max(20, min(94, save["gm"]["ratings"].get("drafting", 50) + staff_bonus(save)["scouting"] + scout_bonus))
    for p in cls:
        _scout(rng, p, acc)
    save["staff_market"] = generate_staff_market(rng)   # fresh candidates each offseason
    inject_player_coaches(save, rng)   # this year's retired stars can enter the market
    order = [s["id"] for s in reversed(save.get("standings_cache", []))] or [t["id"] for t in save["teams"]]
    n = len(order)
    picks = []
    for r in range(1, DRAFT_ROUNDS + 1):
        for slot, tid in enumerate(order):
            ov = (r - 1) * n + slot + 1
            picks.append({"r": r, "pir": slot + 1, "ov": ov, "owner": tid, "orig": tid})
    season = save.get("season", 1)
    for sw in save.get("pick_swaps", []):          # apply trades made in earlier seasons
        if sw.get("season") != season:
            continue
        for pk in picks:
            if pk["r"] == sw["round"] and pk["orig"] == sw["orig"]:
                pk["owner"] = sw["to"]
                break
    save["pick_swaps"] = [sw for sw in save.get("pick_swaps", []) if sw.get("season") != season]
    save["draft"] = {"class": cls, "picks": picks, "order": order,
                     "rounds": DRAFT_ROUNDS, "ptr": 0, "user_log": [], "offers": [],
                     "pro_days": 3}   # private-workout visits your scouts can burn
    save["draft_pending"] = True
    _draft_advance(save)
    write_save(save)


def _draft_on_clock(draft):
    if draft["ptr"] >= len(draft["picks"]):
        return None
    return draft["picks"][draft["ptr"]]["owner"]


def _draft_round_pick(draft):
    if draft["ptr"] >= len(draft["picks"]):
        return draft["rounds"], len(draft.get("order", []))
    pk = draft["picks"][draft["ptr"]]
    return pk["r"], pk["pir"]


def _available(draft):
    return sorted(draft["class"], key=lambda p: -p["grade"])


def _ai_pick(save, draft):
    tid = _draft_on_clock(draft)
    team = next(t for t in save["teams"] if t["id"] == tid)
    avail = _available(draft)
    if avail:
        best = {}                                  # best-player-available, lightly nudged by need
        for p in team["roster"]:
            best[p["pos"]] = max(best.get(p["pos"], 0), p["overall"])
        need = lambda pr: max(0, 75 - best.get(pr["pos"], 60))
        pick = max(avail[:6], key=lambda pr: pr["grade"] + need(pr) * 0.12)
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
            draft["offers"] = draft_trade_offers(save)   # refresh trade-down offers on the clock
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
    draft["offers"] = []
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


def draft_capital(save):
    """Every pick the GM currently controls — remaining picks in this draft (with
    their chart value and where they came from) plus next year's picks. The asset
    sheet behind every trade-down decision."""
    draft = save.get("draft")
    uid = save["current_team_id"]
    now = []
    if draft:
        for i in range(draft["ptr"], len(draft["picks"])):
            pk = draft["picks"][i]
            if pk["owner"] == uid:
                now.append({"r": pk["r"], "pir": pk["pir"], "ov": pk["ov"],
                            "value": pick_value(pk["ov"]),
                            "from": None if pk["orig"] == uid else _team_abbr(save, pk["orig"])})
    nxt = save.get("season", 1) + 1
    future = []
    away = {sw["round"] for sw in save.get("pick_swaps", [])
            if sw.get("season") == nxt and sw["orig"] == uid and sw["to"] != uid}
    for r in range(1, DRAFT_ROUNDS + 1):
        if r not in away:
            future.append({"r": r, "value": future_pick_value(r), "from": None})
    for sw in save.get("pick_swaps", []):
        if sw.get("season") == nxt and sw["to"] == uid and sw["orig"] != uid:
            future.append({"r": sw["round"], "value": future_pick_value(sw["round"]),
                           "from": _team_abbr(save, sw["orig"])})
    future.sort(key=lambda x: (x["r"], x["from"] or ""))
    total = sum(p["value"] for p in now) + sum(p["value"] for p in future)
    return {"now": now, "future": future, "total": total}


def draft_trade_offers(save):
    """Trade-DOWN offers when the GM is on the clock: rival clubs call to move UP
    to your slot, and they OVERPAY to do it (a later pick + extra capital, often a
    future pick). Accept and you slide down the board with more total value — the
    Belichick move. Returns a list of one-click offers."""
    draft = save.get("draft")
    if not draft:
        return []
    uid = save["current_team_id"]
    ptr = draft["ptr"]
    if ptr >= len(draft["picks"]) or draft["picks"][ptr]["owner"] != uid:
        return []
    my = draft["picks"][ptr]
    my_val = pick_value(my["ov"])
    if my_val < 150:                               # only worth shopping a real premium pick
        return []
    rng = _rng(save["seed"] + save["season"] * 131 + my["ov"])
    # one base per team: the EARLIEST upcoming pick a rival would move up FROM, and
    # only rivals close enough that a believable 2-4 asset package covers the jump.
    earliest = {}
    for j in range(ptr + 1, len(draft["picks"])):
        pk = draft["picks"][j]
        if pk["owner"] == uid:
            continue
        if pk["owner"] not in earliest:
            earliest[pk["owner"]] = (j, pk)
    bases = [(ai, jpk) for ai, jpk in earliest.items()
             if my_val * 0.42 <= pick_value(jpk[1]["ov"]) < my_val]
    bases.sort(key=lambda b: -pick_value(b[1][1]["ov"]))
    rng.shuffle(bases)
    seen, offers = set(), []
    for ai, (bj, base) in bases:
        if ai in seen:
            continue
        their_val = pick_value(base["ov"])
        need = (my_val - their_val) * rng.uniform(1.05, 1.20)    # the move-up premium
        give = [{"kind": "pick", "idx": bj, "label": f"Rd {base['r']} (#{base['ov']})", "value": their_val}]
        acc = 0.0
        extra = sorted([(j, draft["picks"][j]) for j in range(ptr + 1, len(draft["picks"]))
                        if draft["picks"][j]["owner"] == ai and draft["picks"][j]["ov"] != base["ov"]],
                       key=lambda jp: -pick_value(jp[1]["ov"]))
        for j, p2 in extra[:3]:                     # at most 2 extra current-year picks
            if acc >= need or len(give) >= 3:
                break
            give.append({"kind": "pick", "idx": j, "label": f"Rd {p2['r']} (#{p2['ov']})", "value": pick_value(p2["ov"])})
            acc += pick_value(p2["ov"])
        if acc < need:                              # one future pick to close the gap
            fr = 2 if (need - acc) > 300 else 4
            fv = future_pick_value(fr)
            give.append({"kind": "future", "round": fr, "orig": ai,
                         "label": f"{_team_abbr(save, ai)} '{str(save['season'] + 1)[-2:]} Rd {fr}", "value": fv})
            acc += fv
        vin = sum(g["value"] for g in give)
        if vin <= my_val or len(give) > 4:          # must add value, in a believable package
            continue
        seen.add(ai)
        offers.append({
            "id": len(offers), "team": ai, "team_name": next(t["full"] for t in save["teams"] if t["id"] == ai),
            "give": give, "take_ov": my["ov"], "take_label": f"Rd {my['r']} (#{my['ov']})",
            "vin": round(vin), "vout": round(my_val),
            "summary": (f"Trade #{my['ov']} to {_team_abbr(save, ai)} for "
                        + " + ".join(g["label"] for g in give))})
        if len(offers) >= 3:
            break
    return offers


def accept_draft_trade(save, offer_id):
    draft = save.get("draft")
    if not draft:
        return False, "No draft in progress."
    uid = save["current_team_id"]
    ptr = draft["ptr"]
    if ptr >= len(draft["picks"]) or draft["picks"][ptr]["owner"] != uid:
        return False, "You're not on the clock."
    off = next((o for o in draft.get("offers", []) if o["id"] == int(offer_id)), None)
    if not off:
        return False, "That offer is no longer on the table."
    draft["picks"][ptr]["owner"] = off["team"]      # rival moves up into your slot
    for g in off["give"]:
        if g["kind"] == "pick":
            draft["picks"][g["idx"]]["owner"] = uid
        else:
            save.setdefault("pick_swaps", []).append(
                {"season": save["season"] + 1, "round": g["round"], "orig": g["orig"], "to": uid})
    draft["offers"] = []
    save["last_trade"] = {"ok": True, "summary": off["summary"]}
    owner_say(save, f"Traded down off #{off['take_ov']} — stacked the board with {len(off['give'])} more pick(s). That's how you build depth.",
              tone="praise" if len(off["give"]) >= 2 else "neutral")
    _draft_advance(save)                            # the club that moved up is now on the clock
    write_save(save)
    return True, off["summary"]


def run_pro_day(save, pid):
    """Send your scouts to one prospect's pro day (3 visits per class). His
    grade gets re-scouted with far tighter noise and his medical gets a read —
    the private-workout edge real war rooms pay for."""
    draft = save.get("draft")
    if not draft or not save.get("draft_pending"):
        return False, "No draft in progress."
    if draft.get("pro_days", 0) <= 0:
        return False, "Your scouts have no pro-day visits left this spring."
    p = next((x for x in draft["class"] if x["id"] == pid), None)
    if not p or p.get("drafted"):
        return False, "He's off the board."
    if p.get("pro_day"):
        return False, f"You already worked out {p['name']}."
    rng = _rng(save["seed"] + sum(ord(c) for c in str(pid)) + 5)
    acc = max(20, min(96, save["gm"]["ratings"].get("drafting", 50)
                      + staff_bonus(save)["scouting"] + 24))
    _scout(rng, p, acc)
    p["pro_day"] = True
    med = ("medical checks clean" if p.get("dev") != "Slow" and rng.random() < 0.8
           else "some medical flags in the file")
    c = p.get("combine") or {}
    p["pro_day_note"] = (f"Private workout: {c.get('forty', '?')}s forty confirmed, "
                         f"{med}. This grade is real.")
    draft["pro_days"] = draft.get("pro_days", 0) - 1
    write_save(save)
    return True, (f"Pro day done — {p['name']} re-scouted ({p['grade']} grade, "
                  f"{p['pot_grade']} ceiling). {draft['pro_days']} visit(s) left.")


def draft_state(save):
    draft = save.get("draft")
    if not draft:
        return None
    rnd, pk = _draft_round_pick(draft)
    avail = []
    for pr in _available(draft)[:60]:
        f = tactical_fit(save, pr)
        hf = human_development_fit(save, pr)
        sr = scout_report(save, pr)
        avail.append(dict(pr, fit=f["label"], fit_pct=f["pct"],
                          human_fit=hf["label"], human_fit_score=hf["score"],
                          scout=sr["rec"], scout_tier=sr["tier"]))
    on_clock = _draft_on_clock(draft) == save["current_team_id"]
    return {"round": rnd, "pick": pk, "rounds": draft["rounds"],
            "on_clock": on_clock, "available": avail, "log": draft["user_log"],
            "offers": draft.get("offers", []) if on_clock else [],
            "pro_days": draft.get("pro_days", 0),
            "on_clock_ov": draft["picks"][draft["ptr"]]["ov"] if draft["ptr"] < len(draft["picks"]) else None}


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
        save = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        # Older saves: staff hired before pedigrees/ideologies/ages existed get
        # their profile backfilled once, deterministically, and persisted —
        # same for teams created before franchise histories.
        if save:
            changed = ensure_staff_profiles(save)
            changed = ensure_team_histories(save) or changed
            if changed:
                write_save(save)
    except Exception:
        pass
    return save


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
        "business": {"cash": 95.0, "fan_happiness": 50, "stadium": 1, "facility": 1, "ticket": "normal"},
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    _set_expectation(save)
    generate_front_office_issues(save)
    write_save(save)
    return save


def current_team(save):
    return next(t for t in save["teams"] if t["id"] == save["current_team_id"])


def _player_market_context(save, p, kind="extension"):
    rng = _rng(save["seed"] + save.get("season", 1) * 707 + abs(hash(p["id"])) % 100000)
    market = _market_aav(p)
    reasons = []
    leverage = 1.0
    if p.get("holdout"):
        leverage += 0.12
        reasons.append(p.get("holdout_reason") or "he believes he has outplayed his current deal")
    if p.get("trade_request"):
        leverage += 0.08
        reasons.append(p.get("trade_reason") or "he wants a clearer role somewhere else")
    if p.get("tag_candidate"):
        leverage += 0.06
        reasons.append("his camp knows the franchise tag is on the table")
    if p.get("underperforming_contract"):
        leverage -= 0.08
        reasons.append("ownership sees him as overpaid for his production")
    if p.get("age", 27) >= 31:
        leverage -= 0.06
        reasons.append("age is working against a long guarantee")
    if p.get("overall", 0) >= 82 and kind == "free_agent":
        rival = round(market * rng.uniform(1.08, 1.28), 1)
        reasons.append(f"another club is believed to be near ${rival}M per year")
        return {"ask": round(max(market * leverage, rival), 1), "rival_offer": rival, "reasons": reasons}
    return {"ask": round(max(0.7, market * leverage), 1), "rival_offer": None, "reasons": reasons}


def _issue_player_row(p):
    return {"id": p["id"], "name": p["name"], "pos": p["pos"], "ovr": p["overall"],
            "age": p.get("age"), "aav": p.get("contract", {}).get("aav", 0),
            "years": p.get("contract", {}).get("years", 0)}


def generate_front_office_issues(save):
    """Create the mess a GM inherits: money, leverage, trade pressure, and tag calls."""
    team = current_team(save)
    rng = _rng(save["seed"] + save.get("season", 1) * 997 + abs(hash(team["id"])) % 100000)
    for p in team["roster"]:
        for key in ("holdout", "holdout_reason", "trade_request", "trade_reason",
                    "tag_candidate", "underperforming_contract"):
            p.pop(key, None)

    issues = []
    roster = sorted(team["roster"], key=lambda p: -p["overall"])

    dispute_pool = [p for p in roster if p["overall"] >= 78 and p.get("contract", {}).get("years", 1) <= 1]
    if not dispute_pool:
        dispute_pool = [p for p in roster if p["overall"] >= 80]
    if dispute_pool:
        p = dispute_pool[0]
        reason = rng.choice([
            "he wants security before risking another season on a short deal",
            "his camp says the last contract no longer matches his role",
            "he wants guarantees before reporting at full speed",
        ])
        p["holdout"] = True
        p["holdout_reason"] = reason
        issues.append({"type": "contract_dispute", "severity": "high", "label": "Contract dispute",
                       "player": _issue_player_row(p),
                       "summary": f"{p['pos']} {p['name']} may hold out: {reason}.",
                       "action": "Extend him, franchise him, trade him, or eat the power hit."})

    tag_pool = [p for p in roster if p.get("contract", {}).get("years", 1) <= 1 and p["overall"] >= 76]
    tag_pick = next((p for p in tag_pool if not p.get("holdout")), tag_pool[0] if tag_pool else None)
    if tag_pick:
        tag_pick["tag_candidate"] = True
        issues.append({"type": "franchise_tag", "severity": "medium", "label": "Franchise tag decision",
                       "player": _issue_player_row(tag_pick),
                       "summary": f"{tag_pick['pos']} {tag_pick['name']} is tag-eligible before he reaches the market.",
                       "action": "Tagging buys time, but it can sour the relationship."})

    trade_pool = [p for p in roster if p["overall"] >= 72 and not p.get("holdout")]
    trade_pool.sort(key=lambda p: (p.get("morale", 70), -p["overall"]))
    if trade_pool:
        p = trade_pool[0]
        reason = rng.choice([
            "he wants a bigger role in the offense",
            "he does not believe the club is close enough to contend",
            "his camp is tired of short-term promises from the front office",
        ])
        p["trade_request"] = True
        p["trade_reason"] = reason
        p["morale"] = max(20, p.get("morale", 70) - 10)
        issues.append({"type": "trade_request", "severity": "high", "label": "Trade request",
                       "player": _issue_player_row(p),
                       "summary": f"{p['pos']} {p['name']} has asked out: {reason}.",
                       "action": "Repair the relationship with a role/pay plan or shop him before value slips."})

    overpaid = [p for p in roster if p.get("contract", {}).get("aav", 0) >= 5
                and p.get("contract", {}).get("aav", 0) > expected_aav(p["overall"]) * 1.45]
    if not overpaid:
        overpaid = [p for p in roster if p.get("contract", {}).get("aav", 0) >= 8]
    if overpaid:
        p = max(overpaid, key=lambda x: x.get("contract", {}).get("aav", 0) / max(1, x["overall"]))
        p["underperforming_contract"] = True
        issues.append({"type": "overpaid", "severity": "medium", "label": "Overpaid veteran",
                       "player": _issue_player_row(p),
                       "summary": f"{p['pos']} {p['name']} is carrying a ${p['contract']['aav']:.1f}M AAV without matching value.",
                       "action": "Move the deal, restructure later, or accept the cap drag."})

    save["front_office_issues"] = issues[:4]
    _check_holdouts(save)
    write_save(save)
    return save["front_office_issues"]


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


FA_DAYS = 7


def fa_market_discount(save):
    """The market softens as free agency drags on: every day a man sits
    unsigned knocks ~4% off what his agent can hold out for."""
    off = save.get("offseason") or {}
    if off.get("stage") != "free_agency":
        return 1.0
    return round(0.96 ** (int(off.get("fa_day", 1) or 1) - 1), 3)


def advance_fa_day(save):
    """One day of the open market: asks soften (hungry agents fold fastest),
    and rival clubs sign players out from under you — wait for the bargain
    and you may lose the man. Loyal players tend to go home early."""
    off = save.get("offseason") or {}
    if off.get("stage") != "free_agency":
        return False, "The market only moves during the free-agency window."
    day = int(off.get("fa_day", 1) or 1)
    if day >= FA_DAYS:
        return False, "The market has gone quiet — only the bargain bin is left."
    rng = _rng(save["seed"] + save.get("season", 1) * 211 + day)
    log = off.setdefault("fa_log", [])
    uid = save["current_team_id"]
    decay = {"Reasonable": 0.06, "Shrewd": 0.035, "Greedy": 0.02, "Loyal": 0.045}
    signed_ids = []
    for p in sorted(save.get("free_agents", []), key=lambda x: -x["overall"]):
        pers = (p.get("agent") or {}).get("personality", "Reasonable")
        d = p.setdefault("demand", {"aav": p["contract"]["aav"], "years": 3})
        d.setdefault("ask0", d.get("aav", p["contract"]["aav"]))
        # rival clubs move on the best names first; loyal men go home early
        p_sign = max(0.0, 0.05 + (p["overall"] - 68) * 0.02) * (1.35 if pers == "Loyal" else 1.0)
        if rng.random() < min(0.45, p_sign):
            club = min([t for t in save["teams"] if t["id"] != uid],
                       key=lambda t: (sum(1 for x in t["roster"] if x["pos"] == p["pos"]),
                                      rng.random()))
            yrs = rng.randint(2, 4)
            aav = round(d["aav"], 1)
            p.pop("agent", None)
            deal = p.pop("demand", None) or {}
            p["contract"] = {"years": yrs, "aav": aav, "guaranteed": round(aav * 0.5, 1)}
            club["roster"].append(p)
            signed_ids.append(p["id"])
            log.insert(0, {"day": day, "kind": "signing",
                           "text": f"{p['pos']} {p['name']} signs with the {club['full']} — "
                                   f"{yrs}yr / ${aav}M"
                                   + (" (went home — loyalty won)" if pers == "Loyal" else "")})
            continue
        drop = round(d["aav"] * decay.get(pers, 0.04), 1)
        floor = round(max(1.0, d["ask0"] * 0.62), 1)
        if d["aav"] - drop >= floor:
            d["aav"] = round(d["aav"] - drop, 1)
            if p["overall"] >= 78:
                log.insert(0, {"day": day, "kind": "price",
                               "text": f"{p['pos']} {p['name']}'s camp is getting nervous — "
                                       f"ask down to ${d['aav']}M/yr (opened at ${d['ask0']}M)."})
    save["free_agents"] = [p for p in save.get("free_agents", []) if p["id"] not in signed_ids]
    off["fa_day"] = day + 1
    off["fa_log"] = log[:30]
    write_save(save)
    return True, f"Day {day} closes — {len(signed_ids)} signing(s) around the league. Asks are softening."


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
        save["last_nego"] = {"ok": False, "status": "rejected", "msg": "Enter a valid offer."}
        write_save(save)
        return save["last_nego"]

    context = _player_market_context(save, fa, kind="free_agent")
    eff = demand_aav
    if pers == "Loyal":
        eff = round(demand_aav * (1 - min(0.12, _business(save)["fan_happiness"] / 900.0)), 1)
    eff = max(eff, context["ask"])
    eff = round(eff * fa_market_discount(save), 1)   # a dragging market softens every ask
    # A counter is a commitment: if the agent named a number for THIS player last
    # round, meeting it closes the deal (otherwise his sub-ask counter loops forever).
    prev = save.get("last_nego") or {}
    accept_at = eff
    if (prev.get("ok") and prev.get("status") == "countered"
            and prev.get("id") == fa["id"] and prev.get("counter")):
        accept_at = min(eff, float(prev["counter"].get("aav", eff)))

    res = {"ok": True, "id": fa["id"], "player": fa["name"], "pos": fa["pos"], "ovr": fa["overall"],
           "agent": fa["agent"], "demand": eff, "offer": {"years": years, "aav": aav},
           "context": context}
    if cap_used(team) + aav > CAP_TOTAL:
        res.update(status="rejected", msg=f"That ${aav}M deal puts you over the cap.")
    elif aav >= accept_at:
        fa["contract"] = {"years": years, "aav": aav, "guaranteed": round(aav * 0.5, 1)}
        fa.pop("agent", None)
        fa.pop("demand", None)
        team["roster"].append(fa)
        save["free_agents"] = [p for p in save["free_agents"] if p["id"] != player_id]
        save["gm"]["nego_wins"] = save["gm"].get("nego_wins", 0) + (2 if aav <= demand_aav else 1)
        _owner_sign_react(save, fa["name"], fa["pos"], fa["overall"], aav)
        res.update(status="accepted", msg=f"Done. {res['player']} signs {years}yr / ${aav}M.")
    elif aav >= eff * 0.90:
        counter = round(eff * A["counter"], 1)
        why = (" " + context["reasons"][0]) if context["reasons"] else ""
        res.update(status="countered", counter={"years": years, "aav": counter},
                   msg=f"{agent_name}: \"{res['player']} signs {years}yr at ${counter}M - meet us there.\"{why}")
    else:
        why = " ".join(context["reasons"][:2])
        res.update(status="rejected",
                   msg=f"{agent_name} rejects it - {res['player']} wants about ${eff}M/yr. {why}".strip())
    save["last_nego"] = res
    write_save(save)
    return res


# --------------------------------------------------------------------------- #
# Contract extensions + holdouts
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Owner mood + statements - the owner reacts to results, and his patience (trust)
# tells the story of your tenure: honeymoon -> pressure -> hot seat.
# --------------------------------------------------------------------------- #
_OWNER_MOODS = [(80, "Thrilled", "🤩"), (60, "Pleased", "🙂"), (42, "Watching closely", "🧐"),
                (25, "Frustrated", "😤"), (0, "Out of patience", "🌋")]
_OWNER_TIER_LINE = {
    "title": "We're CHAMPIONS - this is everything I hoped for. ",
    "good": "You blew past what I expected. Impressive. ",
    "ok": "A solid, professional season. ",
    "bad": "That is not the standard I expect around here. ",
    "fired": "We're going in a different direction. ",
}
_OWNER_TYPE_LINE = {
    "Impatient": "I want more, and I want it now.",
    "Cheap": "Just keep an eye on what you're spending.",
    "Hands-Off": "Keep doing your thing - I trust you.",
    "Meddling": "Don't be surprised when I get involved.",
    "Legacy": "This franchise's history demands greatness.",
    "Billionaire": "Money is no object. Just win.",
}

_OWNER_PROFILES = {
    "Impatient": {"name": "Victor Cross", "title": "Chairman", "style": "demands quick proof"},
    "Cheap": {"name": "Milton Price", "title": "Managing Partner", "style": "protects margin first"},
    "Hands-Off": {"name": "Elliot Vale", "title": "Principal Owner", "style": "backs the football staff"},
    "Meddling": {"name": "Cassandra Knox", "title": "Governor", "style": "wants a voice in every big move"},
    "Legacy": {"name": "Arthur Bell", "title": "Family Owner", "style": "guards the franchise standard"},
    "Billionaire": {"name": "Nadia Sterling", "title": "Owner", "style": "expects premium results"},
}
# How each owner opens the interview — his voice, before he hands you the keys.
_OWNER_PITCH_OPEN = {
    "Impatient":   "I'll be blunt — I don't do patience.",
    "Cheap":       "Money's tight here, and it's staying tight.",
    "Hands-Off":   "I hire good people and let them work.",
    "Meddling":    "Fair warning: I like a voice in the big calls.",
    "Legacy":      "This franchise has a history, and I expect you to honor it.",
    "Billionaire": "Money is no object for the right plan.",
}
_TIER_LABEL = {"champion": "Defending Champions", "contender": "Win-Now Contender",
               "middle": "On the Bubble", "rebuild": "Full Rebuild"}
_TIER_MANDATE = {
    "champion":  "Run it back — another title, or it's a failed year.",
    "contender": "Push us over the top. This is a ring-or-bust window.",
    "middle":    "Break the cycle: make the playoffs and prove we're more than mediocre.",
    "rebuild":   "Build it right — draft well, develop, and show me real progress.",
}


def team_job_offer(save, t):
    """The owner's interview pitch for one club: who he is, what he's offering
    (cap, picks), the mandate, and an honest read of the roster he's handing you."""
    sc = (save.get("scenarios") or {}).get(t["id"], {})
    n = len(save["teams"])
    tier = sc.get("tier", "middle")
    otype = t["owner"]["type"]
    prof = _OWNER_PROFILES.get(otype, _OWNER_PROFILES["Hands-Off"])

    avg = {}
    for pos, slots in ROSTER.items():
        best = sorted((p["overall"] for p in t["roster"] if p["pos"] == pos), reverse=True)[:slots]
        if best:
            avg[pos] = sum(best) / len(best)
    ranked = sorted(avg.items(), key=lambda kv: -kv[1])
    strengths = [p for p, _ in ranked[:2]]
    needs = [p for p, _ in ranked[-2:][::-1]]
    stars = [{"pos": p["pos"], "name": p["name"], "ovr": p["overall"], "id": p["id"]}
             for p in sorted(t["roster"], key=lambda x: -x["overall"])[:3]]
    cap_room = round(CAP_TOTAL - cap_used(t) + sc.get("cap_bonus", 0))
    pick = sc.get("draft_slot", n // 2)
    comp = sc.get("comp_picks", 0)
    mandate = _TIER_MANDATE[tier]

    pitch = (f"{_OWNER_PITCH_OPEN.get(otype, '')} {mandate} You'll have about ${cap_room}M in cap room "
             f"and the #{pick} pick" + (f" plus {comp} comp pick{'s' if comp != 1 else ''}" if comp else "")
             + f". Our strength is {strengths[0] if strengths else 'a balanced roster'}, "
             f"but {needs[0] if needs else 'depth'} keeps me up at night.")
    return {"owner": {**prof, "type": otype, "name": t["owner"].get("name") or prof["name"]},
            "tier": tier, "label": _TIER_LABEL[tier],
            "pitch": pitch, "mandate": mandate, "power": power_rating(t), "pick": pick,
            "comp": comp, "cap_room": cap_room, "strengths": strengths, "needs": needs,
            "stars": stars, "age": round(sum(p["age"] for p in t["roster"]) / max(1, len(t["roster"])), 1)}


def owner_state(save):
    trust = save["gm"]["owner_trust"]
    mood, icon = next((m, i) for thr, m, i in _OWNER_MOODS if trust >= thr)
    owner = current_team(save)["owner"]
    otype = owner["type"]
    profile = _OWNER_PROFILES.get(otype, _OWNER_PROFILES["Hands-Off"])
    return {"type": otype, "trust": trust, "mood": mood, "icon": icon,
            **profile, "name": owner.get("name") or profile["name"]}


def _owner_tier(save, outcome):
    if outcome.get("status") == "fired":
        return "fired"
    if outcome.get("won_title"):
        return "title"
    rec = outcome.get("record", {})
    margin = rec.get("w", 0) - outcome.get("expectation", save["expectation"]["wins"])
    return "good" if margin >= 3 else "ok" if margin >= -1 else "bad"


def owner_statement(save, outcome):
    otype = current_team(save)["owner"]["type"]
    tier = _owner_tier(save, outcome)
    line = _OWNER_TIER_LINE[tier] + _OWNER_TYPE_LINE.get(otype, "")
    save["owner_message"] = {"type": otype, "text": line, "mood": owner_state(save)["mood"]}
    tone = {"title": "praise", "good": "praise", "ok": "neutral",
            "bad": "concern", "fired": "ultimatum"}.get(tier, "neutral")
    owner_say(save, line.strip(), tone=tone, tag="seasonend")
    return save["owner_message"]


# --------------------------------------------------------------------------- #
# In-season owner presence: the owner is around ALL year, not just at season's
# end. He reacts to streaks, the mandate pace, your trades and your spending -
# flavored by his archetype and current patience - and his messages stack into
# an Owner's Office feed on the dashboard. Small in-season trust drift makes his
# mood move week to week, so the relationship feels live.
# --------------------------------------------------------------------------- #
_OWNER_FEED_MAX = 14
_OWNER_VOICE = {
    "Impatient":   "I don't do patience.",
    "Cheap":       "And mind the budget.",
    "Hands-Off":   "You know your job - go do it.",
    "Meddling":    "Keep me in the loop.",
    "Legacy":      "This franchise has a standard.",
    "Billionaire": "Spare no expense - just deliver.",
}


def _owner_voice(otype):
    return _OWNER_VOICE.get(otype, "")


def owner_say(save, text, tone="neutral", tag=None, dedupe_window=3):
    """Push one message into the Owner's Office feed (newest first). When tag is
    set, won't repeat the same tag inside the recent window this season."""
    feed = save.setdefault("owner_feed", [])
    season = save.get("season", 1)
    if tag:
        for m in feed[:dedupe_window]:
            if m.get("tag") == tag and m.get("season") == season:
                return None
    owner = owner_state(save)
    msg = {"season": season, "week": (save.get("inseason") or {}).get("week", 0),
           "tone": tone, "tag": tag, "owner": owner["name"], "title": owner["title"],
           "icon": owner["icon"], "mood": owner["mood"], "text": text}
    feed.insert(0, msg)
    del feed[_OWNER_FEED_MAX:]
    return msg


def owner_season_open(save):
    """A start-of-season note that sets the tone and restates the mandate."""
    otype = current_team(save)["owner"]["type"]
    exp = save.get("expectation", {})
    voice = _owner_voice(otype)
    hot = otype in ("Impatient", "Legacy", "Billionaire")
    owner_say(save, f"New season. The bar is {exp.get('wins', '?')} wins - {exp.get('text', 'win.')} {voice}".strip(),
              tone="demand" if hot else "neutral", tag="seasonopen")


def owner_weekly(save, week, rng):
    """The owner reacts to the week just played: hot/cold streaks, the mid-season
    pace check, and late-season pressure if the mandate is slipping away."""
    team = current_team(save)
    iz = save.get("inseason") or {}
    log = iz.get("log", [])
    if not log:
        return
    otype = team["owner"]["type"]
    voice = _owner_voice(otype)
    won = log[-1]["won"]
    streak = 0
    for g in reversed(log):
        if g["won"] == won:
            streak += 1
        else:
            break
    if won and streak >= 3 and streak % 2 == 1:
        save["gm"]["owner_trust"] = min(100, save["gm"]["owner_trust"] + 1)
        owner_say(save, f"{streak} straight. The building feels it - keep it rolling. {voice}".strip(),
                  tone="praise", tag=f"wstreak{streak}")
    elif (not won) and streak >= 3 and streak % 2 == 1:
        hit = 2 if otype == "Impatient" else 1
        save["gm"]["owner_trust"] = max(0, save["gm"]["owner_trust"] - hit)
        tail = "This is exactly what I won't tolerate." if otype == "Impatient" else "Right the ship - fast."
        owner_say(save, f"{streak} losses in a row. {tail}", tone="concern", tag=f"lstreak{streak}")

    played = team["record"]["w"] + team["record"]["l"]
    mandate = save.get("expectation", {}).get("wins", 9)
    if week == REG_GAMES // 2 and played:
        proj = round(team["record"]["w"] / played * REG_GAMES)
        if proj >= mandate + 2:
            owner_say(save, f"Halfway and you're tracking for ~{proj} wins against a {mandate}-win bar. I like where this is going.",
                      tone="praise", tag="midcheck")
        elif proj >= mandate - 1:
            owner_say(save, f"Halfway home, projecting ~{proj} wins. You're on the number - now separate from the pack.",
                      tone="neutral", tag="midcheck")
        else:
            owner_say(save, f"We're halfway and this is tracking for ~{proj} wins. The mandate is {mandate}. I need a response.",
                      tone="demand", tag="midcheck")

    games_left = REG_GAMES - played
    if 0 < games_left <= 4 and save["gm"]["owner_trust"] < 35 and team["record"]["w"] + games_left < mandate:
        owner_say(save, f"Let me be blunt: {games_left} to play and the mandate is out of reach. Your seat is hot.",
                  tone="ultimatum", tag="ultimatum")


def _owner_trade_react(save, got_pos, got_name, gave_pos, gave_name, grade):
    """The owner weighs in on a completed trade - was it sharp or did you get fleeced?"""
    otype = current_team(save)["owner"]["type"]
    if grade in ("A", "B"):
        txt, tone = f"Bringing in {got_pos} {got_name} for {gave_pos} {gave_name} - sharp work.", "praise"
    elif grade in ("D", "F"):
        txt, tone = f"You moved {gave_pos} {gave_name} for {got_pos} {got_name}? We'd better not regret that.", "concern"
    else:
        txt, tone = f"Deal done - {got_pos} {got_name} in, {gave_pos} {gave_name} out. We'll see.", "neutral"
    if otype == "Meddling":
        txt += " Walk me through the next one that size first."
    elif otype == "Cheap":
        txt += " And mind what it does to the books."
    owner_say(save, txt, tone=tone)


def _owner_sign_react(save, name, pos, ovr, aav):
    """The owner reacts to the money you just committed in free agency / an extension."""
    otype = current_team(save)["owner"]["type"]
    if aav >= 14:
        if otype == "Cheap":
            txt, tone = f"${aav:.0f}M for {pos} {name}? At that price he had better be a difference-maker.", "concern"
        elif otype == "Billionaire":
            txt, tone = f"${aav:.0f}M for {name}? Good - pay for the best and go win.", "praise"
        else:
            txt, tone = f"That's real money on {pos} {name} - ${aav:.0f}M. Make it pay off.", "neutral"
    elif ovr >= 80 and aav <= expected_aav(ovr) * 0.9:
        txt, tone = f"{pos} {name} at ${aav:.1f}M is a bargain. That's how you build a winner.", "praise"
    else:
        txt, tone = f"{pos} {name} is in the building. Solid addition.", "neutral"
    owner_say(save, txt, tone=tone)


def owner_meeting(save, outcome):
    """Post-season owner/GM meeting with direct Q&A and next-year vision."""
    team = current_team(save)
    owner = owner_state(save)
    rec = outcome.get("record", {})
    wins, losses = int(rec.get("w", 0) or 0), int(rec.get("l", 0) or 0)
    exp = int(outcome.get("expectation", save.get("expectation", {}).get("wins", 0)) or 0)
    margin = wins - exp
    team_power = power_rating(team)
    cap_room = round(CAP_TOTAL - cap_used(team), 1)
    weak_pos = min(ROSTER, key=lambda pos: max([p["overall"] for p in team["roster"] if p["pos"] == pos] or [0]))

    if outcome.get("status") == "fired":
        verdict = "The meeting ends with ownership choosing a new direction."
        vision = "The next GM will be asked to reset standards and restore credibility immediately."
    elif outcome.get("won_title"):
        verdict = "Ownership credits the GM, but wants proof this was not a one-year spike."
        vision = "Keep the championship core intact, avoid sentimental contracts, and make another deep run."
    elif margin >= 3:
        verdict = "Ownership sees a real builder and wants the roster pushed harder."
        vision = "Convert the overachievement into a sustainable playoff team."
    elif margin >= -1:
        verdict = "Ownership accepts the season, but the patience meter did not move much."
        vision = "Raise the floor, clean up the weakest position group, and make the mandate feel routine."
    else:
        verdict = "Ownership is not buying process talk after missing the mandate."
        vision = "Fix the roster fast, show sharper cap discipline, and start winning earlier in the year."

    if margin > 0:
        mandate_line = f"You beat the number by {margin}."
    elif margin < 0:
        mandate_line = f"You were {abs(margin)} wins short."
    else:
        mandate_line = "You landed right on the number."

    qas = [
        {
            "q": "What do you see when you look at this season?",
            "a": f"{wins}-{losses} against a {exp}-win mandate. {mandate_line}",
        },
        {
            "q": "Where is this roster most exposed?",
            "a": f"The first pressure point is {weak_pos}. Team power sits at {team_power}, so one real starter there changes the whole conversation.",
        },
        {
            "q": "How aggressive should we be?",
            "a": (
                f"We have about ${cap_room:.0f}M of cap room. "
                + ("Spend into the window, but do not bury us in dead money." if cap_room >= 25 else
                   "Create flexibility before chasing names. The budget is not the problem; discipline is.")
            ),
        },
        {"q": "What is your vision for next season?", "a": vision},
    ]
    meeting = {
        "season": outcome.get("season", save.get("season", 1)),
        "team": team["full"],
        "owner": owner,
        "verdict": verdict,
        "vision": vision,
        "record": f"{wins}-{losses}",
        "mandate": exp,
        "trust": owner["trust"],
        "qas": qas,
    }
    save["owner_meeting"] = meeting
    return meeting


def _market_aav(p):
    o, age = p["overall"], p.get("age", 27)
    base = max(0.8, (max(0, o - 58) ** 1.7) / 16.0)
    if age >= 31:
        base *= 0.85
    if age >= 34:
        base *= 0.8
    return round(base, 1)


def extend_player(save, player_id, years, aav):
    """Extend / re-sign one of YOUR players early. Resolves a holdout if he was one."""
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == player_id), None)
    if not p:
        save["last_nego"] = {"ok": False, "status": "rejected", "msg": "Player not found."}
        write_save(save)
        return save["last_nego"]
    try:
        years = max(1, min(6, int(years)))
        aav = round(float(aav), 1)
    except (TypeError, ValueError):
        save["last_nego"] = {"ok": False, "status": "rejected", "msg": "Enter a valid offer."}
        write_save(save)
        return save["last_nego"]
    if "agent" not in p:
        p["agent"] = {"name": _gen_name(_rng(abs(hash(player_id)) % 999983)),
                      "personality": random.choice(list(AGENTS))}
    pers = p["agent"]["personality"]
    A = AGENTS[pers]
    context = _player_market_context(save, p, kind="extension")
    ask = round(max(_market_aav(p) * A["markup"], context["ask"]), 1)
    if pers == "Loyal":
        ask = round(ask * (1 - min(0.12, _business(save)["fan_happiness"] / 900.0)), 1)
    res = {"ok": True, "id": p["id"], "player": p["name"], "pos": p["pos"], "ovr": p["overall"],
           "agent": p["agent"], "demand": ask, "offer": {"years": years, "aav": aav},
           "context": context}
    room = CAP_TOTAL - cap_used(team) + p["contract"].get("aav", 0)   # his old deal frees up
    if aav > room:
        res.update(status="rejected", msg=f"That ${aav}M deal won't fit under the cap.")
    elif aav >= ask:
        p["contract"] = {"years": years, "aav": aav, "guaranteed": round(aav * 0.55, 1)}
        p.pop("agent", None)
        p.pop("holdout", None)
        p.pop("holdout_reason", None)
        p.pop("trade_request", None)
        p.pop("trade_reason", None)
        p["morale"] = min(99, p.get("morale", 75) + 12)
        save["gm"]["nego_wins"] = save["gm"].get("nego_wins", 0) + (2 if aav <= ask else 1)
        _owner_sign_react(save, p["name"], p["pos"], p["overall"], aav)
        res.update(status="accepted", msg=f"Extension done — {p['name']} for {years}yr / ${aav}M.")
    elif aav >= ask * 0.9:
        why = (" " + context["reasons"][0]) if context["reasons"] else ""
        res.update(status="countered", counter={"years": years, "aav": ask},
                   msg=f"{p['agent']['name']} counters: {years}yr at ${ask}M.{why}")
    else:
        why = " ".join(context["reasons"][:2])
        res.update(status="rejected",
                   msg=f"{p['agent']['name']} rejects ${aav}M - he wants about ${ask}M/yr. {why}".strip())
    save["last_nego"] = res
    write_save(save)
    return res


def _check_holdouts(save):
    """Underpaid stars on expiring deals hold out (morale + a power hit until paid)."""
    team = current_team(save)
    flagged = []
    for p in team["roster"]:
        market = _market_aav(p)
        if p.get("holdout_reason"):
            p["holdout"] = True
            flagged.append({"id": p["id"], "name": p["name"], "pos": p["pos"],
                            "ovr": p["overall"], "aav": p["contract"]["aav"],
                            "market": market, "reason": p.get("holdout_reason")})
        elif (p["overall"] >= 80 and p.get("contract", {}).get("years", 9) <= 1
                and p.get("contract", {}).get("aav", 99) < market * 0.6):
            p["holdout"] = True
            p["holdout_reason"] = "he believes he has outplayed his current deal"
            p["morale"] = max(20, p.get("morale", 75) - 15)
            flagged.append({"id": p["id"], "name": p["name"], "pos": p["pos"],
                            "ovr": p["overall"], "aav": p["contract"]["aav"],
                            "market": market, "reason": p.get("holdout_reason")})
        else:
            p.pop("holdout", None)
    save["holdouts"] = flagged
    return flagged


def take_job(save, team_id):
    if team_id not in [t["id"] for t in save["teams"]]:
        return False
    save["current_team_id"] = team_id
    save["gm"]["owner_trust"] = 50
    save["unemployed"] = False
    save["last_outcome"] = None
    _set_expectation(save)
    generate_front_office_issues(save)
    _tl(save, save.get("season", 1), "hired", "📝",
        f"Hired as GM of the {current_team(save)['full']}", "A new chapter begins.")
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


def cut_penalty(p):
    """Dead money if you release him now - the remaining guaranteed shell. The
    real cost of moving on, so cutting a liability isn't free."""
    c = p.get("contract", {})
    g = c.get("guaranteed", 0) or 0
    yrs = max(1, c.get("years", 1) or 1)
    return round(g * min(1.0, yrs / 3.0), 1)


def roster_value_report(save):
    """Loop 1 - the Value vs. Cap engine. Runs the roster and surfaces the two
    decisions that actually move the franchise: bargains to lock up before they
    walk, and liabilities to move/restructure (with the dead-cap cost of cutting).
    Production justifies pay or it doesn't."""
    team = current_team(save)
    extend, liabilities = [], []
    for p in team["roster"]:
        c = p.get("contract", {})
        aav = c.get("aav", 0) or 0
        yrs = c.get("years", 0) or 0
        g, ratio = contract_grade(p)
        fit = tactical_fit(save, p)
        row = {**_issue_player_row(p), "grade": g, "ratio": ratio, "fit": fit["label"]}
        if ratio >= 1.25 and p["overall"] >= 72 and yrs <= 2 and p.get("age", 27) <= 29:
            row["note"] = "Outplaying his deal - extend before he hits the market."
            extend.append(row)
        elif aav >= 5 and ratio <= 0.8:
            row["dead_cap"] = cut_penalty(p)
            row["note"] = f"${aav:.1f}M for {g}-grade value - cut costs ${row['dead_cap']:.1f}M dead."
            liabilities.append(row)
    extend.sort(key=lambda x: -x["ratio"])
    liabilities.sort(key=lambda x: x["ratio"])
    return {"extend": extend[:4], "liabilities": liabilities[:4]}


def role_friction_report(save):
    """Loop 4 (display) - who is paid like a starter but buried on the depth chart.
    Pure: tags p['role_friction'] and refreshes save['role_friction'] for the
    dashboard, WITHOUT touching morale, so it's safe to call on every page load."""
    team = current_team(save)
    starters = {p["id"] for p in _starters(team)}
    flagged = []
    for p in team["roster"]:
        aav = p.get("contract", {}).get("aav", 0) or 0
        if aav >= 7 and p["id"] not in starters:
            p["role_friction"] = True
            flagged.append({**_issue_player_row(p),
                            "note": f"${aav:.1f}M AAV and not in the starting lineup."})
        else:
            p.pop("role_friction", None)
    save["role_friction"] = flagged
    return flagged


def _apply_role_friction(save):
    """Loop 4 (yearly) - the buried, expensive players actually lose morale over a
    season. Called once from _advance_year so the penalty doesn't compound on
    every page view."""
    flagged = role_friction_report(save)
    by_id = {f["id"] for f in flagged}
    for p in current_team(save)["roster"]:
        if p["id"] in by_id:
            p["morale"] = max(15, p.get("morale", 70) - 8)
    return flagged


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
STADIUM_CAP = {1: 45, 2: 58, 3: 68, 4: 76, 5: 85}     # seats (thousands) by stadium level


def attendance(save):
    """How full the building gets - driven by winning, happy fans, ticket price and
    market. Winning fills seats."""
    b = _business(save)
    team = current_team(save)
    cap = STADIUM_CAP.get(b["stadium"], 50)
    last = (save.get("last_outcome") or {}).get("record", {}) or {}
    diff = last.get("w", 8) - last.get("l", 8)
    am, _, _ = TICKET.get(b["ticket"], TICKET["normal"])
    market_bump = {"Small": -4, "Mid": 0, "Large": 7}.get(team["market"], 0)
    fill = 58 + (b["fan_happiness"] - 50) * 0.55 + diff * 1.6 + market_bump + (am - 1.0) * 60
    fill = int(max(34, min(100, round(fill))))
    return {"fill": fill, "capacity": cap, "avg": round(cap * fill / 100.0, 1)}


def atmosphere(save):
    """A packed, happy house is your 12th man -> a home-field power edge in the sim."""
    b = _business(save)
    att = attendance(save)
    score = int(min(100, round(att["fill"] * 0.7 + b["fan_happiness"] * 0.3)))
    home_edge = max(0.0, round((score - 42) / 17.0, 1))    # 42->0, 100->~3.4
    return {"score": score, "home_edge": home_edge,
            "fill": att["fill"], "capacity": att["capacity"], "avg": att["avg"]}


def _business(save):
    b = save.setdefault("business", {})
    b.setdefault("cash", 95.0)
    b.setdefault("fan_happiness", 50)
    b.setdefault("stadium", 1)
    b.setdefault("facility", 1)
    b.setdefault("ticket", "normal")
    return b


def projected_revenue(save):
    b = _business(save)
    att = attendance(save)
    mm = MARKET_MULT.get(current_team(save)["market"], 1.0)
    _, _, pm = TICKET.get(b["ticket"], TICKET["normal"])
    # seats actually filled x price-per-seat x market (so winning -> fuller house -> more money)
    return round((16 + b["stadium"] * 5) * mm * (att["fill"] / 100.0 + 0.22) * pm, 1)


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
    save["gm"]["money_earned"] = round(save["gm"].get("money_earned", 0) + rev, 1)   # career revenue


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


def _starter_avg(team, pos):
    best = sorted((p["overall"] for p in team["roster"] if p["pos"] == pos), reverse=True)[:ROSTER[pos]]
    return sum(best) / len(best) if best else 50.0


def league_context(save):
    """Read the WHOLE league, not just your roster: your power rank, competitive
    window, where each of your position groups ranks against the field, which
    division rival is breathing down your neck, and how scarce real talent is at
    your weak spots. This is what a sharp consultant actually reasons from."""
    teams = save["teams"]
    uid = save["current_team_id"]
    me = current_team(save)
    n = len(teams)
    ranked = _power_rankings(save)
    rank_map = {r["id"]: i + 1 for i, r in enumerate(ranked)}
    my_rank = rank_map[uid]
    window = "contender" if my_rank <= max(1, round(n * 0.28)) else \
             "fringe" if my_rank <= round(n * 0.60) else "rebuild"

    pos_rank, my_avg, lg_avg, scarcity = {}, {}, {}, {}
    for pos in ROSTER:
        vals = [_starter_avg(t, pos) for t in teams]
        mine = _starter_avg(me, pos)
        my_avg[pos] = round(mine, 1)
        lg_avg[pos] = round(sum(vals) / len(vals), 1)
        pos_rank[pos] = 1 + sum(1 for v in vals if v > mine + 0.01)
        scarcity[pos] = sum(1 for t in teams for p in t["roster"] if p["pos"] == pos and p["overall"] >= 82)

    by_deficit = sorted(ROSTER, key=lambda pos: my_avg[pos] - lg_avg[pos])
    weakest, strongest = by_deficit[0], by_deficit[-1]
    rivals = sorted((t for t in teams if t["division"] == me["division"] and t["id"] != uid),
                    key=lambda t: rank_map[t["id"]])
    top_rival = rivals[0] if rivals else None
    return {"rank": my_rank, "n": n, "window": window,
            "pos_rank": pos_rank, "my_avg": my_avg, "lg_avg": lg_avg, "scarcity": scarcity,
            "weakest": weakest, "strongest": strongest,
            "rival": (top_rival["full"] if top_rival else None),
            "rival_rank": (rank_map[top_rival["id"]] if top_rival else None),
            "rival_ahead": bool(top_rival and rank_map[top_rival["id"]] < my_rank)}


def consultant_advice(save):
    """A prioritized list of suggestions (most urgent first), independent of the
    assist level (the level just controls how many the UI reveals). Reads the
    whole league, then your roster."""
    team = current_team(save)
    tips = []
    lc = league_context(save)
    wk, wr = lc["weakest"], lc["pos_rank"][lc["weakest"]]
    st, sr = lc["strongest"], lc["pos_rank"][lc["strongest"]]

    # 1) Strategic directive from your competitive window vs the league
    if lc["window"] == "contender":
        tips.append({"icon": "🏆", "title": f"You're #{lc['rank']} of {lc['n']} — contend NOW",
                     "detail": f"Your window is open. Spend draft capital and cap on a win-now upgrade at {wk} "
                               f"(ranks #{wr} leaguewide). Don't sit on picks — convert them into help.", "u": 3})
    elif lc["window"] == "rebuild":
        tips.append({"icon": "🧱", "title": f"You're #{lc['rank']} of {lc['n']} — build, don't buy",
                     "detail": f"Trade aging vets for picks, stockpile, and grow your young core. Your {wk} group is "
                               f"#{wr} in the league — address it through the draft, not expensive free agents.", "u": 3})
    else:
        tips.append({"icon": "⚖", "title": f"You're #{lc['rank']} of {lc['n']} — on the bubble",
                     "detail": f"One real addition swings your season. {wk} is your softest group (#{wr} leaguewide) — "
                               f"target it, but don't mortgage future picks chasing a fringe playoff run.", "u": 3})

    # 2) Position need framed against the league average
    tips.append({"icon": "🎯", "title": f"Your {wk} is below the league",
                 "detail": f"Your {wk} group grades {lc['my_avg'][wk]:.0f} vs a {lc['lg_avg'][wk]:.0f} league average "
                           f"(#{wr} of {lc['n']}). That's your real need — not just your weakest spot.", "u": 3})

    # 3) Use your league-elite group as the trade chip
    if sr <= max(2, round(lc["n"] * 0.15)):
        tips.append({"icon": "💎", "title": f"Your {st} is league-elite (#{sr})",
                     "detail": f"You're {lc['my_avg'][st]:.0f} at {st} vs {lc['lg_avg'][st]:.0f} leaguewide — depth you can "
                               f"trade FROM to fix {wk}. Package a surplus {st} for the need.", "u": 2})

    # 4) Scarcity read — draft it or shop for it
    sc = lc["scarcity"][wk]
    if sc <= 6:
        tips.append({"icon": "🔦", "title": f"Real {wk}s are scarce leaguewide",
                     "detail": f"Only {sc} starting-caliber {wk}s exist across the league — don't wait for free agency, "
                               f"draft one and develop him.", "u": 2})

    # 5) Division rival pressure
    if lc["rival_ahead"]:
        tips.append({"icon": "🤝", "title": f"{lc['rival']} is ahead of you",
                     "detail": f"Your division rival sits #{lc['rival_rank']} to your #{lc['rank']}. To win the division "
                               f"you have to close that gap — start at your {wk}.", "u": 2})

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

    if not save.get("staff", {}).get("cond_coach"):
        tips.append({"icon": "🏋", "title": "Hire a Conditioning Coach",
                     "detail": "You don't have one. He's your development engine — faster growth, fewer injuries, and "
                               "he's the reason a young player can break PAST his scouted ceiling. Hire one on the Staff tab.",
                     "u": 3})

    ident = scheme_identity(save)
    if not ident["installed"]:
        tips.append({"icon": "🧩", "title": "Install a scheme",
                     "detail": "Hire an OC and DC to set your system. Until then you can't grade players on fit - "
                               "you're scouting raw talent blind to how it plays in your offense/defense.",
                     "u": 2})
    else:
        pegs = [p for p in team["roster"]
                if (tactical_fit(save, p)["label"] == "Square peg") and p["overall"] >= 76]
        if pegs:
            sp = max(pegs, key=lambda p: p["overall"])
            tips.append({"icon": "🧩", "title": f"{sp['pos']} {sp['name']} doesn't fit your scheme",
                         "detail": f"A {sp['overall']}-OVR talent miscast as a {sp.get('style')} in your "
                                   f"{tactical_fit(save, sp)['scheme']}. Scheme around him, trade him, or expect less than his rating.",
                         "u": 2})

    tips.sort(key=lambda t: -t["u"])
    return tips


# --------------------------------------------------------------------------- #
# Player STATISTICS. The sim resolves games on power ratings, so we synthesize
# believable season stat lines from each starter's overall + role + how good his
# team's offense/defense was. Drives leaderboards, a stat-based MVP, and roster
# stat lines - turning ratings into a living league.
# --------------------------------------------------------------------------- #
def assign_season_stats(teams, wins_by_id, seed, season=0):
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

    for t in teams:                                 # archive the season into each player's career
        tname = t.get("name", t["full"])
        for p in t["roster"]:
            if p.get("stats"):
                car = p.setdefault("career", [])
                if not car or car[-1].get("season") != season:
                    car.append({"season": season, "team": tname, **p["stats"]})
                    del car[:-24]


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


# --------------------------------------------------------------------------- #
# GridIron Network - the in-game sports network. Turns franchise events into a
# SportsDesk news feed (champions, MVP, leaders, the draft, trades, retirements,
# records, owner buzz). Fictional - no real network/marks.
# --------------------------------------------------------------------------- #
NETWORK = "GridIron Network"


def generate_news(save):
    """A season-recap news feed from the season just played (solo)."""
    news = []
    team = current_team(save)
    tn = team["full"]
    season = max(1, save.get("season", 1) - 1)

    def add(tag, head, body=""):
        news.append({"tag": tag, "head": head, "body": body})

    champ = save.get("last_champion", "")
    out = save.get("last_outcome") or {}
    if champ:
        add("TITLE", f"{champ} are champions", f"{champ} close out Season {season} on top of the league.")
    mvp = save.get("season_mvp")
    if mvp:
        add("MVP", f"{mvp['pos']} {mvp['name']} wins MVP", f"A monster season — {mvp['line']} for the {mvp['team']}.")
    if out.get("headline"):
        rec = out.get("record", {})
        add("TEAM", f"{tn} finish {rec.get('w', '?')}-{rec.get('l', '?')}", out["headline"])
    om = save.get("owner_message")
    if om:
        add("OWNER", f"{tn} owner speaks out", om["text"])
    for inc in (save.get("incidents") or [])[:3]:
        add("WIRE", f"{inc['pos']} {inc['name']}: {inc['label']}",
            f"{inc['text']}." + (f" Missed {inc['weeks']} game{'s' if inc['weeks'] != 1 else ''}." if inc.get("weeks") else ""))
    for cat in (save.get("leaders") or [])[:3]:
        r = cat["rows"][0]
        v = ("%.1f" % r["val"]) if cat["key"] == "sack" else f"{r['val']:,}"
        add("STAT", f"{r['name']} leads the league in {cat['label']}", f"{v} for the {r['team']}.")
    for r in (save.get("retirements") or []):
        if r.get("hof"):
            add("LEGEND", f"{r['pos']} {r['name']} retires — Hall of Fame bound",
                f"{r['summary']} across {r['seasons']} seasons. A first-ballot lock.")
    log = save.get("last_draft_log") or []
    if log:
        d = log[0]
        add("DRAFT", f"{tn} take {d['pos']} {d['name']} in Round {d['round']}",
            f"Scouted at a {d.get('grade', '?')} grade — {d.get('ovr', '?')} OVR.")
    lt = save.get("last_trade")
    if lt and lt.get("ok"):
        add("TRADE", "Front office swings a trade", lt.get("summary", "A deal gets done."))
    ap = save.get("all_pro") or []
    if ap:
        names = ", ".join(f"{a['pos']} {a['name']}" for a in ap[:3])
        add("BUZZ", "All-League Team headlined by the league's elite", f"Leading the way: {names}.")
    for b in (save.get("breakouts") or [])[:2]:
        add("BREAKOUT", f"{b['pos']} {b['name']} is breaking out",
            f"Scouts have revised his ceiling up to {b['pot']} — he's outplaying his projection.")
    for u in (save.get("ceiling_unlocks") or [])[:2]:
        add("RISE", f"{u['pos']} {u['name']} breaks his ceiling",
            f"Your conditioning program pushed his ceiling from {u['from']} to {u['to']} — development you coached into him.")
    for h in (save.get("holdouts") or [])[:2]:
        add("HOLDOUT", f"{h['pos']} {h['name']} is holding out",
            f"Wants a new deal — he's at ${h['aav']}M, market is ~${h['market']}M.")
    save["news"] = news[:14]
    return save["news"]


# --------------------------------------------------------------------------- #
# GridIron Network — the league's broadcast. A living news desk assembled from
# current state: power rankings (with week-over-week movement), a top story, the
# wire (off-field incidents + owner drama + trades), hot takes from the studio,
# and league leaders. Runs in-season (this week) and through the offseason.
# --------------------------------------------------------------------------- #
_ANCHORS = ["Cris Marlowe", "Dana Fields", "Marcus Vinn", "Tory Lang", "Priya Anand", "Reggie Stone"]


def _power_rankings(save):
    """Order every club by a blend of record + power — early season power leads,
    late season record takes over."""
    def score(t):
        return t["record"]["w"] * 1.0 + power_rating(t) / 22.0
    ranked = sorted(save["teams"], key=score, reverse=True)
    return [{"id": t["id"], "full": t["full"], "name": t.get("name", t["full"]),
             "w": t["record"]["w"], "l": t["record"]["l"], "power": power_rating(t),
             "conf": t["conference"], "div": t["division"]} for t in ranked]


def _update_power_rank(save):
    """Snapshot rankings so the broadcast can show week-over-week movement."""
    ranked = _power_rankings(save)
    save["power_rank_prev"] = save.get("power_rank", {})
    save["power_rank"] = {r["id"]: i + 1 for i, r in enumerate(ranked)}


def _top_story(save, ranked, team, live, week, season):
    champ = save.get("last_champion")
    if not live and champ:
        return {"tag": "CHAMPIONS", "head": f"{champ} are champions",
                "sub": f"{champ} finish Season {max(1, season - 1)} on top of the league."}
    for m in (save.get("owner_feed") or [])[:3]:
        if m.get("tone") == "ultimatum":
            return {"tag": "HOT SEAT", "head": f"The heat is on in {team['city']}",
                    "sub": m["text"]}
    for inc in (save.get("incidents") or [])[:3]:
        if inc["key"] in ("ped", "arrest"):
            return {"tag": "BREAKING", "head": f"{inc['pos']} {inc['name']}: {inc['label']}",
                    "sub": inc["text"] + "."}
    if ranked:
        t1 = ranked[0]
        return {"tag": "POWER", "head": f"{t1['full']} are the team to beat",
                "sub": f"{t1['w']}-{t1['l']} with a {t1['power']} power rating — nobody's playing better."}
    return {"tag": "LIVE", "head": f"{NETWORK}", "sub": "Around the league."}


def _hot_takes(save, ranked, team):
    rng = _rng(save["seed"] + save.get("season", 1) * 13 + (save.get("inseason") or {}).get("week", 0))
    anchors = _ANCHORS[:]
    rng.shuffle(anchors)
    takes = []
    weak = next((n for n in team_needs(save) if n.get("need")), None)
    if weak:
        takes.append({"who": anchors[0], "take": f"Until {team['full']} fix {weak['pos']} — {weak['startavg']} OVR there — they've got a hard ceiling. That's their whole season in one number."})
    if ranked and ranked[0]["id"] != team["id"]:
        t1 = ranked[0]
        takes.append({"who": anchors[1 % len(anchors)], "take": f"I'm all in on {t1['full']}. {t1['w']}-{t1['l']}, a {t1['power']} rating — that's a contender, not a fluke."})
    inc = save.get("incidents") or []
    if inc:
        takes.append({"who": anchors[2 % len(anchors)], "take": f"{inc[0]['pos']} {inc[0]['name']}'s situation is the kind of distraction that quietly sinks a locker room. Watch the response."})
    elif save.get("gm", {}).get("owner_trust", 50) < 35:
        takes.append({"who": anchors[2 % len(anchors)], "take": f"Make no mistake — the seat is hot in {team['city']}. Ownership wants it fixed now."})
    elif save.get("gm", {}).get("owner_trust", 50) >= 75:
        takes.append({"who": anchors[2 % len(anchors)], "take": f"Whatever {team['full']}'s front office is doing, it's working. Ownership trusts the plan, and that buys you everything."})
    return takes[:3]


def broadcast(save):
    """Assemble the GridIron Network broadcast from current league state."""
    team = current_team(save)
    uid = save["current_team_id"]
    iz = save.get("inseason") or {}
    live = bool(iz)
    week = iz.get("week")
    season = save.get("season", 1)

    ranked = _power_rankings(save)
    prev = save.get("power_rank_prev", {})
    rankings = []
    for i, r in enumerate(ranked[:10]):
        pr = prev.get(r["id"])
        rankings.append({**r, "rank": i + 1, "move": (pr - (i + 1)) if pr else 0,
                         "mine": r["id"] == uid})
    cur = {r["id"]: i + 1 for i, r in enumerate(ranked)}

    wire = []
    for inc in (save.get("incidents") or [])[:4]:
        wire.append({"tag": inc["label"], "text": inc["text"], "kind": inc["key"], "pid": inc.get("pid")})
    for m in (save.get("owner_feed") or [])[:3]:
        wire.append({"tag": "OWNER", "text": m["text"], "kind": "owner"})
    lt = save.get("last_trade")
    if lt and lt.get("ok"):
        # AI-offer trades store a 'summary'; user-proposed trades store 'msg'
        text = lt.get("summary") or lt.get("msg")
        if text:
            wire.append({"tag": "TRADE", "text": text, "kind": "trade"})

    last = iz.get("log") or []
    lg = last[-1] if last else None
    capsule = {"team": team["full"], "rank": cur.get(uid), "rec": f"{team['record']['w']}-{team['record']['l']}",
               "power": power_rating(team),
               "last": (f"{'beat' if lg['won'] else 'fell to'} {lg['opp']}" if lg else None)}

    return {"network": NETWORK, "live": live, "week": week, "season": season,
            "headline_week": (f"WEEK {week}" if live and week else f"SEASON {season} · OFFSEASON"),
            "top": _top_story(save, ranked, team, live, week, season),
            "rankings": rankings, "wire": wire[:8], "capsule": capsule,
            "takes": _hot_takes(save, ranked, team), "leaders": (save.get("leaders") or [])[:3]}


def all_pro_team(teams):
    """The statistical best at each position this season -> a 1st-team All-Pro."""
    pool = [(p, t) for t in teams for p in t["roster"]]
    s = lambda p: p.get("stats") or {}

    def pick(pos, scorer, n=1):
        cand = [(p, t) for p, t in pool if p["pos"] == pos and (p.get("stats") or pos == "OL")]
        cand.sort(key=lambda x: -scorer(x[0]))
        chosen = cand[:n]
        for p, _t in chosen:
            p["all_pro"] = p.get("all_pro", 0) + 1       # career accolade (feeds the HoF)
        return [{"pos": pos, "name": p["name"], "team": t.get("name", t["full"]), "pid": p["id"],
                 "detail": stat_line(p) or f"{p['overall']} OVR"} for p, t in chosen]

    out = []
    out += pick("QB", lambda p: s(p).get("pass_yd", 0) + s(p).get("pass_td", 0) * 25 - s(p).get("int", 0) * 12)
    out += pick("RB", lambda p: s(p).get("rush_yd", 0) + s(p).get("rush_td", 0) * 15 + s(p).get("rec_yd", 0) * 0.5)
    out += pick("WR", lambda p: s(p).get("rec_yd", 0) + s(p).get("rec_td", 0) * 15, n=2)
    out += pick("TE", lambda p: s(p).get("rec_yd", 0) + s(p).get("rec_td", 0) * 15)
    out += pick("OL", lambda p: p["overall"])
    out += pick("DL", lambda p: s(p).get("sack", 0) * 10 + s(p).get("tackle", 0))
    out += pick("LB", lambda p: s(p).get("sack", 0) * 8 + s(p).get("tackle", 0) + s(p).get("def_int", 0) * 8)
    out += pick("CB", lambda p: s(p).get("def_int", 0) * 12 + s(p).get("pd", 0) * 2 + s(p).get("tackle", 0))
    out += pick("S", lambda p: s(p).get("def_int", 0) * 12 + s(p).get("tackle", 0))
    out += pick("K", lambda p: s(p).get("pts", 0))
    return out


_RECORD_CATS = [("Passing Yards", "pass_yd"), ("Passing TDs", "pass_td"), ("Rushing Yards", "rush_yd"),
                ("Rushing TDs", "rush_td"), ("Receiving Yards", "rec_yd"), ("Receptions", "rec"),
                ("Sacks", "sack"), ("Interceptions", "def_int")]


def almanac(save):
    """The league in one book: the season-by-season ledger, award winners,
    the records book, all-time career leaders, and the Hall of Fame."""
    cats = [("pass_yd", "Passing yards"), ("pass_td", "Passing TD"),
            ("rush_yd", "Rushing yards"), ("rush_td", "Rushing TD"),
            ("rec_yd", "Receiving yards"), ("rec_td", "Receiving TD"),
            ("sack", "Sacks"), ("def_int", "Interceptions")]
    totals = []
    for t in save.get("teams", []):
        for p in t["roster"]:
            cs = _career_sums(p)
            if cs:
                totals.append((p, t, cs))
    leaders = []
    for key, label in cats:
        rows = sorted(((cs.get(key, 0), p, t) for p, t, cs in totals if cs.get(key)),
                      reverse=True, key=lambda x: x[0])[:6]
        if rows:
            leaders.append({"label": label, "rows": [
                {"name": p["name"], "pos": p["pos"], "team": t.get("name", t["full"]),
                 "value": (round(v, 1) if key == "sack" else int(v))}
                for v, p, t in rows]})
    return {"history": save.get("league_history", []),
            "records": sorted((save.get("records") or {}).values(), key=lambda r: r["label"]),
            "career_records": sorted((save.get("career_records") or {}).values(), key=lambda r: r["label"]),
            "hall_of_fame": save.get("hall_of_fame", []),
            "leaders": leaders}


def update_records(store, teams, season):
    """Update single-season + career league records from this season's stats."""
    recs = store.setdefault("records", {})
    crecs = store.setdefault("career_records", {})
    for t in teams:
        tname = t.get("name", t["full"])
        for p in t["roster"]:
            sd = p.get("stats") or {}
            for label, key in _RECORD_CATS:
                v = sd.get(key, 0)
                if v and (key not in recs or v > recs[key]["value"]):
                    recs[key] = {"label": label, "value": v, "holder": p["name"],
                                 "pos": p["pos"], "team": tname, "season": season}
            csum = {}
            for r in p.get("career", []):
                for _, key in _RECORD_CATS:
                    csum[key] = csum.get(key, 0) + r.get(key, 0)
            for label, key in _RECORD_CATS:
                v = round(csum.get(key, 0), 1)
                if v and (key not in crecs or v > crecs[key]["value"]):
                    crecs[key] = {"label": label, "value": v, "holder": p["name"],
                                  "pos": p["pos"], "team": tname}


# --------------------------------------------------------------------------- #
# Retirement + Hall of Fame. Aging players retire (stars last longer); the truly
# great are inducted into the league's Hall of Fame.
# --------------------------------------------------------------------------- #
def _career_sums(p):
    cs = {}
    for r in p.get("career", []):
        for k in ("pass_yd", "pass_td", "rush_yd", "rush_td", "rec_yd", "rec_td", "sack", "def_int"):
            cs[k] = cs.get(k, 0) + r.get(k, 0)
    return cs


def _hof_summary(p):
    cs = _career_sums(p)
    if cs.get("pass_yd"):
        return f"{cs['pass_yd']:,} pass yd · {cs['pass_td']} TD"
    if cs.get("rush_yd"):
        return f"{cs['rush_yd']:,} rush yd · {cs['rush_td']} TD"
    if cs.get("rec_yd"):
        return f"{cs['rec_yd']:,} rec yd · {cs['rec_td']} TD"
    if cs.get("sack"):
        return f"{round(cs['sack'], 1)} career sacks"
    if cs.get("def_int"):
        return f"{cs['def_int']} career INT"
    return f"{len(p.get('career', []))} seasons"


def _hof_worthy(p):
    peak = p.get("peak_ovr", p["overall"])
    seasons = len(p.get("career", []))
    ap = p.get("all_pro", 0)
    if seasons < 3:
        return False
    return ap >= 3 or (ap >= 1 and peak >= 88) or (peak >= 90 and seasons >= 7)


def process_retirements(teams, season, hof_list):
    """Age players out (stars last longer); induct the greats into the HoF.
    Returns the list of this offseason's retirees (with an 'hof' flag)."""
    retired = []
    for t in teams:
        keep = []
        for p in t["roster"]:
            peak = max(p.get("peak_ovr", p["overall"]), p["overall"])
            p["peak_ovr"] = peak
            age = p.get("age", 27)
            retire_age = 34 + max(0, (peak - 75) // 5)        # 75->34, 90->37, 95->38
            # retire when washed up, ancient, or clearly past prime (declined 6+ and old)
            if p["overall"] < 50 or age >= 40 or (age >= retire_age and p["overall"] <= peak - 6):
                entry = {"name": p["name"], "pos": p["pos"], "team": t.get("name", t["full"]),
                         "peak": peak, "seasons": len(p.get("career", [])),
                         "all_pro": p.get("all_pro", 0), "summary": _hof_summary(p),
                         "retired": season, "hof": _hof_worthy(p)}
                retired.append(entry)
                if entry["hof"]:
                    hof_list.insert(0, entry)
            else:
                keep.append(p)
        t["roster"] = keep
    return retired


def game_starter(team, pos):
    cands = pos_depth(team, pos)
    return cands[0] if cands else None


def game_line(p, won, rng):
    """A single-game box-score line + a standout score, for a skill starter."""
    o = p["overall"]
    wb = 1.12 if won else 0.9
    if p["pos"] == "QB":
        att = rng.randint(24, 40)
        comp = int(att * min(0.74, 0.55 + (o - 55) * 0.0035))
        yd = int(comp * rng.uniform(6.6, 9.2) * wb)
        td = max(0, int(yd / 150 * wb + rng.random()))
        intc = rng.randint(0, 2) if rng.random() < 0.55 else 0
        line = f"{comp}/{att}, {yd} yd, {td} TD" + (f", {intc} INT" if intc else "")
        return line, yd * 0.04 + td * 4 - intc * 2
    if p["pos"] == "RB":
        car = rng.randint(10, 25)
        yd = int(car * rng.uniform(3.2, 6.2) * (1 + (o - 65) * 0.004) * wb)
        td = max(0, int(yd / 58 * wb + rng.random() * 0.5))
        return f"{car} car, {yd} yd, {td} TD", yd * 0.06 + td * 6
    car = rng.randint(3, 10)
    yd = int(car * rng.uniform(9, 18) * (1 + (o - 65) * 0.004) * wb)
    td = max(0, int(yd / 70 * wb))
    return f"{car} rec, {yd} yd, {td} TD", yd * 0.06 + td * 6 + car * 0.4


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


def stat_table(p):
    """Labeled (stat, value) rows for a player's season - shaped by position."""
    s = p.get("stats") or {}
    if s.get("pass_att"):
        return [("Comp / Att", f"{s['pass_cmp']}/{s['pass_att']}"), ("Pass Yards", f"{s['pass_yd']:,}"),
                ("Pass TD", str(s["pass_td"])), ("Interceptions", str(s["int"]))]
    if s.get("rush_car"):
        out = [("Carries", str(s["rush_car"])), ("Rush Yards", f"{s['rush_yd']:,}"),
               ("Rush TD", str(s["rush_td"]))]
        if s.get("rec"):
            out += [("Receptions", str(s["rec"])), ("Rec Yards", f"{s['rec_yd']:,}")]
        return out
    if s.get("rec"):
        return [("Receptions", str(s["rec"])), ("Rec Yards", f"{s['rec_yd']:,}"), ("Rec TD", str(s["rec_td"]))]
    if "sack" in s:
        return [("Tackles", str(s.get("tackle", 0))), ("Sacks", str(s["sack"]))]
    if "def_int" in s:
        out = [("Tackles", str(s.get("tackle", 0))), ("Interceptions", str(s["def_int"]))]
        if s.get("pd"):
            out.append(("Passes Defended", str(s["pd"])))
        return out
    if s.get("fgm"):
        return [("FG Made / Att", f"{s['fgm']}/{s['fga']}"), ("Points", str(s["pts"]))]
    return []


def career_table(p):
    """Year-by-year career rows shaped by position (or None if no history)."""
    car = p.get("career") or []
    if not car:
        return None
    if any(r.get("pass_yd") for r in car):
        cols = [("Cmp", "pass_cmp"), ("Att", "pass_att"), ("Yds", "pass_yd"), ("TD", "pass_td"), ("INT", "int")]
    elif any(r.get("rush_yd") for r in car):
        cols = [("Car", "rush_car"), ("Yds", "rush_yd"), ("TD", "rush_td"), ("Rec", "rec"), ("RecYd", "rec_yd")]
    elif any(r.get("rec") for r in car):
        cols = [("Rec", "rec"), ("Yds", "rec_yd"), ("TD", "rec_td")]
    elif any("sack" in r for r in car):
        cols = [("Tkl", "tackle"), ("Sacks", "sack")]
    elif any("def_int" in r for r in car):
        cols = [("Tkl", "tackle"), ("INT", "def_int"), ("PD", "pd")]
    elif any(r.get("fgm") for r in car):
        cols = [("FGM", "fgm"), ("FGA", "fga"), ("Pts", "pts")]
    else:
        return None
    rows = [{"season": r.get("season"), "team": r.get("team", ""),
             "vals": [r.get(k, 0) for _, k in cols]} for r in car]
    return {"headers": [c[0] for c in cols], "rows": list(reversed(rows))}


# --------------------------------------------------------------------------- #
# Practice squad: a developmental squad (off the 53, no cap hit) that develops and
# can be promoted to the active roster.
# --------------------------------------------------------------------------- #
PS_MAX = 12


def _gen_ps_player(rng):
    p = _gen_player(rng, rng.choice(list(ROSTER)), int(rng.triangular(55, 68, 60)))
    p["age"] = rng.randint(21, 23)
    p["contract"] = {"years": 2, "aav": 0.7, "guaranteed": 0.0}
    p["practice"] = True
    return p


def ensure_practice_squad(save):
    team = current_team(save)
    if "practice_squad" not in team:
        rng = _rng(save["seed"] + abs(hash(team["id"])) % 99999 + 71)
        team["practice_squad"] = [_gen_ps_player(rng) for _ in range(6)]
        write_save(save)
    return team["practice_squad"]


def promote_player(save, pid):
    team = current_team(save)
    p = next((x for x in team.get("practice_squad", []) if x["id"] == pid), None)
    if not p:
        return False
    team["practice_squad"] = [x for x in team["practice_squad"] if x["id"] != pid]
    p.pop("practice", None)
    team["roster"].append(p)
    write_save(save)
    return True


def demote_player(save, pid):
    team = current_team(save)
    if len(team.get("practice_squad", [])) >= PS_MAX:
        return False
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False
    team["roster"] = [x for x in team["roster"] if x["id"] != pid]
    p["practice"] = True
    team.setdefault("practice_squad", []).append(p)
    write_save(save)
    return True


def run_training_camp(save, final=53):
    """Training camp: every man gets evaluated before cut-day. Young players can
    out-play (or fall short of) their scouting report — camp is where hidden
    ceilings start to show — and the verdicts feed the cut / practice-squad
    calls. Runs once per offseason; re-entering the stage reuses the report."""
    season = save.get("season", 1)
    report = save.get("camp_report")
    if report and report.get("season") == season:
        return report
    team = current_team(save)
    ensure_practice_squad(save)
    rng = _rng(save["seed"] + season * 53 + 7)
    roster = sorted(team["roster"], key=lambda p: -p["overall"])
    keep_ids = {p["id"] for p in roster[:final]}
    rows = []
    for p in roster:
        pot = int(p.get("potential", p["overall"]) or p["overall"])
        true_pot = int(p.get("true_pot", pot) or pot)
        gap = true_pot - pot
        age = int(p.get("age", 27) or 27)
        rookie = age <= 23 and not p.get("career")
        young = age <= 25
        roll = rng.gauss(0, 1)
        traj, tag = "steady", "Steady"
        note = "Doing his job — no surprises either way."
        if young and gap >= 3 and rng.random() < 0.6:
            reveal = rng.randint(1, min(3, gap))
            p["potential"] = pot + reveal
            tag, traj = "Camp standout", "rising"
            note = f"Playing past his scouting report — ceiling re-graded {pot} → {p['potential']}."
        elif young and gap <= -3 and rng.random() < 0.45:
            drop = rng.randint(1, min(2, -gap))
            p["potential"] = max(p["overall"], pot - drop)
            tag, traj = "Looked ordinary", "declining"
            note = f"The tape isn't matching the grade — ceiling re-read {pot} → {p['potential']}."
        elif roll > 0.95:
            tag, traj = "Turning heads", "rising"
            note = "Winning his reps every day — pushing for a bigger role."
        elif roll < -1.15:
            tag, traj = "Struggling", "declining"
            note = "Losing his battles. If he's on the bubble, he's in trouble."
        if rookie:
            note = "Rookie camp: " + note
        rows.append({"id": p["id"], "name": p["name"], "pos": p["pos"],
                     "number": p.get("number"), "age": age, "overall": p["overall"],
                     "potential": int(p.get("potential", p["overall"]) or p["overall"]),
                     "rookie": rookie, "tag": tag, "traj": traj, "note": note,
                     "bubble": p["id"] not in keep_ids})
    save["camp_report"] = {"season": season, "rows": rows}
    write_save(save)
    return save["camp_report"]


def _preseason_perf(p, rng):
    """One preseason outing: a quality roll (talent-tilted, high variance — it's
    August football) and a position-true stat line rendered from it."""
    q = rng.gauss((p["overall"] - 60) / 18.0, 1.0)
    pos = p["pos"]
    if pos == "QB":
        att = rng.randint(10, 22)
        comp = int(att * max(0.3, min(0.8, 0.5 + 0.05 * q + rng.uniform(0, .08))))
        yd = int(comp * rng.uniform(6.0, 8.5))
        td = 1 if q > 0.8 and rng.random() < .6 else 0
        intc = 1 if q < -0.8 and rng.random() < .5 else 0
        line = f"{comp}/{att}, {yd} yd" + (", 1 TD" if td else "") + (", 1 INT" if intc else "")
    elif pos == "RB":
        car = rng.randint(6, 14)
        yd = max(4, int(car * (2.8 + 1.1 * max(-1.5, q))))
        line = f"{car} car, {yd} yd" + (", 1 TD" if q > 1.0 and rng.random() < .5 else "")
    elif pos in ("WR", "TE"):
        rec = max(0, int(2 + 1.3 * q + rng.uniform(0, 2)))
        yd = int(rec * rng.uniform(8, 14))
        line = f"{rec} rec, {yd} yd" + (", 1 TD" if q > 1.1 and rng.random() < .5 else "")
    elif pos == "OL":
        pr = max(0, int(2.2 - q + rng.uniform(0, 1.5)))
        line = ("clean sheet in pass pro" if pr == 0 else
                f"{pr} pressure{'s' if pr != 1 else ''} allowed")
    elif pos in ("DL", "LB"):
        tkl = max(1, int(3 + 1.4 * q + rng.uniform(0, 2)))
        line = f"{tkl} tkl" + (", 1 sack" if q > 0.9 and rng.random() < .55 else "")
    elif pos in ("CB", "S"):
        tkl = max(0, int(2 + q + rng.uniform(0, 2)))
        line = f"{tkl} tkl" + (", 1 PD" if q > 0.5 and rng.random() < .6 else "") \
               + (", 1 INT" if q > 1.3 and rng.random() < .4 else "")
    else:
        fga = rng.randint(1, 3)
        fgm = fga if q > 0 else max(0, fga - 1)
        line = f"{fgm}/{fga} FG"
    return line, q


def run_preseason(save, final=53):
    """Three preseason games: the bubble plays big minutes, rookies get live
    reps, and the stock report they produce is the LAST input before cut day.
    A bubble man who dominates all three forces his way up (+1 OVR). Runs once
    per offseason."""
    season = save.get("season", 1)
    rep = save.get("preseason_report")
    if rep and rep.get("season") == season:
        return rep
    team = current_team(save)
    rng = _rng(save["seed"] + season * 97 + 3)
    camp_rows = {r["id"]: r for r in (save.get("camp_report") or {}).get("rows", [])}
    roster = sorted(team["roster"], key=lambda p: -p["overall"])
    keep = {p["id"] for p in roster[:final]}
    focus = [p for p in roster
             if p["id"] not in keep or int(p.get("age", 27) or 27) <= 24
             or camp_rows.get(p["id"], {}).get("tag") in ("Camp standout", "Struggling", "Turning heads")]
    if len(focus) < 9:
        focus = roster[-max(9, len(roster) // 3):]
    rng.shuffle(focus)
    pool = [t["full"] for t in save["teams"] if t["id"] != team["id"]]
    opponents = rng.sample(pool, min(3, len(pool)))
    games, totals = [], {}
    for gi, opp in enumerate(opponents):
        us, them = rng.randint(9, 31), rng.randint(6, 30)
        if us == them:
            us += 3
        featured = focus[gi::3][:8] or roster[-6:]
        perfs = []
        for p in featured:
            line, q = _preseason_perf(p, rng)
            perfs.append({"id": p["id"], "name": p["name"], "pos": p["pos"],
                          "ovr": p["overall"], "line": line, "q": q,
                          "bubble": p["id"] not in keep, "star": False})
            totals[p["id"]] = totals.get(p["id"], 0.0) + q
        perfs.sort(key=lambda x: -x["q"])
        for x in perfs[:2]:
            x["star"] = True
        games.append({"opponent": opp, "us": us, "them": them,
                      "won": us > them, "perfs": perfs})
    verdicts = []
    for p in roster:
        if p["id"] not in totals:
            continue
        tq = totals[p["id"]]
        verdict = ("Stock way up" if tq >= 2.2 else "Stock up" if tq >= 1.0 else
                   "Stock down" if tq <= -1.6 else "Slipping" if tq <= -0.6 else "Held serve")
        bubble = p["id"] not in keep
        if bubble and tq >= 2.2:
            p["overall"] = min(99, p["overall"] + 1)   # forced his way into the conversation
        verdicts.append({"id": p["id"], "name": p["name"], "pos": p["pos"],
                         "ovr": p["overall"], "verdict": verdict,
                         "q": round(tq, 1), "bubble": bubble})
    verdicts.sort(key=lambda x: -x["q"])
    save["preseason_report"] = {"season": season, "games": games, "verdicts": verdicts}
    write_save(save)
    return save["preseason_report"]


def team_needs(save):
    """Positional snapshot - starter-average OVR per spot, graded, weakest first,
    so you can see at a glance what you have and what you still need."""
    team = current_team(save)
    by_pos = {}
    for p in team["roster"]:
        by_pos.setdefault(p["pos"], []).append(p)
    out = []
    for pos, starters in ROSTER.items():
        players = sorted(by_pos.get(pos, []), key=lambda x: -x["overall"])
        startavg = round(sum(p["overall"] for p in players[:starters]) / starters) if players else 0
        grade = ("Elite" if startavg >= 86 else "Strong" if startavg >= 79 else
                 "Solid" if startavg >= 72 else "Average" if startavg >= 64 else "NEED")
        count = len(players)
        ideal = ROSTER_DEPTH.get(pos, starters + 1)      # a safe camp room at the spot
        min_safe = min(ideal, starters + 1)              # starters + one backup, bare minimum
        delta = count - ideal
        depth_state = ("short" if count < min_safe else
                       "thin" if count < ideal else
                       "over" if count > ideal else "ok")
        out.append({"pos": pos, "count": count, "best": players[0]["overall"] if players else 0,
                    "startavg": int(startavg), "starters": starters, "grade": grade,
                    "need": startavg < 72,
                    "ideal": ideal, "min_safe": min_safe, "delta": delta,
                    "depth_state": depth_state})
    out.sort(key=lambda x: x["startavg"])      # weakest first
    return out


def offseason_advice(save, stage):
    """Stage-aware consultant tips for the offseason's critical decisions."""
    team = current_team(save)
    needs = team_needs(save)
    weak = [n for n in needs if n["need"]][:3]
    room = round(CAP_TOTAL - cap_used(team))
    tips = []
    if stage == "workouts" and weak:
        ws = ", ".join(f"{n['pos']} {n['startavg']}" for n in weak)
        tips.append({"icon": "🔎", "title": "Where you're thin", "u": 2,
                     "detail": f"Going in light at {ws}. Build your free agency + draft plan around these."})
    elif stage == "resign":
        exp = [p for p in team["roster"] if p.get("contract", {}).get("years", 9) <= 0 and p["overall"] >= 78]
        if exp:
            s = max(exp, key=lambda p: p["overall"])
            tips.append({"icon": "✍", "title": f"Re-sign {s['pos']} {s['name']} ({s['overall']})", "u": 3,
                         "detail": "A quality starter is set to walk - lock him up before the market opens."})
    elif stage == "free_agency" and weak:
        ws = ", ".join(f"{n['pos']} ({n['startavg']})" for n in weak)
        tips.append({"icon": "🎯", "title": f"Attack your biggest hole: {weak[0]['pos']}", "u": 3,
                     "detail": f"Weakest spots: {ws}. You have ${room}M in cap room - spend it where it hurts most."})
        fas = sorted([p for p in save.get("free_agents", []) if p["pos"] == weak[0]["pos"]],
                     key=lambda p: -p["overall"])
        if fas:
            f = fas[0]
            tips.append({"icon": "💰", "title": f"Target {f['pos']} {f['name']} ({f['overall']} OVR)", "u": 3,
                         "detail": f"Best {weak[0]['pos']} on the market - fills your top need."})
    elif stage == "draft":
        ws = ", ".join(n["pos"] for n in weak) if weak else "none glaring"
        tips.append({"icon": "🎓", "title": "Take the best player available", "u": 3,
                     "detail": f"Your needs: {ws}. Don't reach - draft BPA and break ties toward need."})
    elif stage == "cuts":
        tips.append({"icon": "✂", "title": "Keep your best 53", "u": 3,
                     "detail": "Cut camp bodies and low-value depth behind your starters - protect young upside."})
    return tips


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
    val = max(0.5, base + youth - cost)
    if p.get("role_friction"):        # unhappy, buried -> the market knows it
        val *= 0.9
    return round(val, 1)


def _grade(ratio):
    return ("A" if ratio >= 1.15 else "B" if ratio >= 1.05 else
            "C" if ratio >= 0.95 else "D" if ratio >= 0.85 else "F")


def solo_trades_open(save):
    """Trades run until the in-season deadline; open the rest of the time (offseason)."""
    iz = save.get("inseason")
    if iz:
        return iz.get("week", 1) <= TRADE_DEADLINE_SOLO
    return True


# --------------------------------------------------------------------------- #
# Trading block — flag a player as available and the league comes to YOU.
# Word gets out: being shopped stings (volatile personalities take it worst,
# shopping a locker-room leader rattles the whole room), listed players draw
# extra inbound offers until the deadline, and pulling a guy off the block
# heals some of the hurt — not all of it.
# --------------------------------------------------------------------------- #
_VOLATILE_PERSONALITIES = ("Hothead", "Free Spirit", "Showman")
_LEADER_PERSONALITIES = ("Field General", "Mentor", "Throwback", "Clutch Gene")


def _is_leader(p):
    return p.get("personality") in _LEADER_PERSONALITIES and p.get("overall", 0) >= 74


def blocked_players(save):
    return [p for p in current_team(save)["roster"] if p.get("on_block")]


def wants_out_players(save):
    return [p for p in current_team(save)["roster"]
            if p.get("trade_request") and not p.get("on_block")]


def block_player(save, pid):
    if not solo_trades_open(save):
        return False, "The trade market is closed — no listings until the offseason."
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False, "He's not on your roster."
    if p.get("on_block"):
        return False, f"{p['name']} is already listed."
    p["on_block"] = True
    volatile = p.get("personality") in _VOLATILE_PERSONALITIES
    hit = 8 if volatile else 4
    p["morale"] = max(5, min(99, p.get("morale", 70) - hit))
    note = "he's furious" if volatile else "he heard, and it stings"
    if _is_leader(p):
        for mate in team["roster"]:
            if mate["id"] != pid:
                mate["morale"] = max(5, min(99, mate.get("morale", 70) - 1))
        note += " — and the room noticed you'd shop a captain"
    if p.get("overall", 0) >= 80:
        _tl(save, save.get("season", 1), "trade", "📰",
            f"{p['pos']} {p['name']} is on the trading block",
            "League sources say you're listening on your star. Rival GMs are circling.")
    write_save(save)
    return True, f"{p['name']} is on the block — {note}. Listed players draw offers first."


def unblock_player(save, pid):
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p or not p.get("on_block"):
        return False, "He isn't on the block."
    p.pop("on_block", None)
    p["morale"] = max(5, min(99, p.get("morale", 70) + 3))
    write_save(save)
    return True, f"{p['name']} is off the block. Some of the sting fades — not all of it."


def _trade_fallout(save, team, departed, arrived=None):
    """The human cost of a completed deal: ship out a leader or a star and the
    room feels it for a stretch; the man coming in arrives on a clean slate."""
    if _is_leader(departed) or departed.get("overall", 0) >= 84:
        for mate in team["roster"]:
            mate["morale"] = max(5, min(99, mate.get("morale", 70) - 2))
        _tl(save, save.get("season", 1), "trade", "🚌",
            f"Locker room shaken by the {departed['name']} trade",
            "You moved a leader. The room takes a small morale dip while it re-forms.")
    if arrived is not None:
        for key in ("on_block", "trade_request", "trade_reason"):
            arrived.pop(key, None)
        arrived["morale"] = max(arrived.get("morale", 70), 68)   # fresh start in a new building


# --------------------------------------------------------------------------- #
# Shop a player for PICKS — the other half of the trade desk. Rival clubs
# answer with 1-3 picks in the upcoming (or next) draft; accept one and the
# picks convey through save['pick_swaps'] when that draft opens.
# --------------------------------------------------------------------------- #
# A pick's worth in PLAYER-value terms (trade_value lens, not chart points):
# roughly "the trade value of the player you'd expect to draft there".
_PICK_PLAYER_WORTH = {1: 120, 2: 72, 3: 42, 4: 24, 5: 13, 6: 7, 7: 4}


def _pick_trade_season(save):
    """Which draft incoming picks convey to: this offseason's draft if it has
    not opened yet, otherwise next year's."""
    if save.get("inseason") or save.get("draft_pending") or (save.get("offseason") or {}).get("drafted"):
        return save.get("season", 1) + 1
    return save.get("season", 1)


def shop_for_picks(save, pid):
    """Shop one of your players league-wide for pick packages. Up to three
    clubs answer; their packages are stored on save['pick_shop']."""
    if not solo_trades_open(save):
        return False, "The trade market is closed until the offseason."
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False, "He's not on your roster."
    v = trade_value(p)
    season_target = _pick_trade_season(save)
    rng = _rng(save["seed"] + save.get("season", 1) * 17 + sum(ord(c) for c in str(pid)))
    clubs = [t for t in save["teams"] if t["id"] != team["id"]]
    rng.shuffle(clubs)
    offers = []
    for idx, t in enumerate(clubs[:4]):
        budget = v * rng.uniform(0.78, 1.06)
        picks, total = [], 0.0
        for rnd in (1, 2, 3, 4, 5, 6, 7):
            worth = _PICK_PLAYER_WORTH[rnd]
            if total + worth <= budget and len(picks) < 3:
                picks.append({"round": rnd, "worth": worth})
                total += worth
            if total >= budget * 0.9:
                break
        if not picks or total < v * 0.55:
            continue                      # this club's package would insult you
        ratio = (total / v) if v else 0
        grade = ("A" if ratio >= 1.0 else "B" if ratio >= 0.88 else
                 "C" if ratio >= 0.75 else "D")
        offers.append({"id": idx + 1, "team_id": t["id"], "team": t["full"],
                       "picks": picks, "total": round(total, 1), "grade": grade,
                       "season": season_target})
    if not offers:
        return False, f"No club is offering real pick value for {p['name']} right now."
    offers.sort(key=lambda o: -o["total"])
    save["pick_shop"] = {"pid": pid, "player": p["name"], "pos": p["pos"],
                         "ovr": p["overall"], "value": v, "offers": offers[:3]}
    write_save(save)
    return True, f"{len(save['pick_shop']['offers'])} club(s) answered with pick packages for {p['name']}."


def accept_pick_offer(save, offer_id):
    shop = save.get("pick_shop") or {}
    team = current_team(save)
    off = next((o for o in shop.get("offers", []) if str(o.get("id")) == str(offer_id)), None)
    p = next((x for x in team["roster"] if x["id"] == shop.get("pid")), None)
    ai = next((t for t in save["teams"] if off and t["id"] == off["team_id"]), None)
    if not (off and p and ai):
        save.pop("pick_shop", None)
        write_save(save)
        return False, "That package is no longer on the table."
    team["roster"] = [x for x in team["roster"] if x["id"] != p["id"]]
    for key in ("on_block", "trade_request", "trade_reason"):
        p.pop(key, None)
    ai["roster"].append(p)
    uid = team["id"]
    for pk in off["picks"]:
        save.setdefault("pick_swaps", []).append(
            {"season": off["season"], "round": pk["round"], "orig": off["team_id"], "to": uid})
    picks_txt = " + ".join(f"R{pk['round']}" for pk in off["picks"])
    save["last_trade"] = {"ok": True, "summary":
                          f"Traded {p['pos']} {p['name']} to the {off['team']} for {picks_txt} (season {off['season']} draft)."}
    _tl(save, save.get("season", 1), "trade", "🎫",
        f"{p['pos']} {p['name']} traded for draft capital",
        f"To the {off['team']} for {picks_txt} in the season-{off['season']} draft.")
    _trade_fallout(save, team, p)
    save.pop("pick_shop", None)
    write_save(save)
    return True, save["last_trade"]["summary"]


def cancel_pick_shop(save):
    save.pop("pick_shop", None)
    write_save(save)
    return True, "You pulled him off the pick market."


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
        _trade_fallout(save, user, give, get)
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
