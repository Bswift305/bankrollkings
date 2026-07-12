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

import portrait_assets

BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "data" / "franchise"

LEAGUE_SIZE = 32
REG_GAMES = 17
CONF_PLAYOFF_SEEDS = 7   # per conference -> 14-team playoff (NFL-style)
CAP_TOTAL = 350.0        # millions (sized for 53-man rosters; expensive teams run tight)


def cap_total(save):
    """The league salary cap — the owners can vote it upward over the years."""
    try:
        return float((save or {}).get("cap_total") or CAP_TOTAL)
    except (TypeError, ValueError):
        return CAP_TOTAL


def playoff_seeds(save):
    try:
        return int((save or {}).get("playoff_seeds") or CONF_PLAYOFF_SEEDS)
    except (TypeError, ValueError):
        return CONF_PLAYOFF_SEEDS
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
    "Whitfield", "Ellison", "Marsh", "Coble", "Renner", "Stokes", "Padgett", "Irby",
    "Lattimore", "Winslow", "Granger", "Holliday", "Beckett", "Sutter", "Mabry", "Teague",
]

# --------------------------------------------------------------------------- #
# Player IDENTITY engine — names are a draft resource, not two random lists.
# Rarity tiers (common names dominate, rare ones surprise), regional pools tied
# to a player's hometown, era pools that drift as the decades roll, middle
# names for disambiguation, "football names" (William -> Will), nicknames, and
# a legal/preferred/jersey identity for every man.
# --------------------------------------------------------------------------- #
FIRST_TIERS = [
    (8, ["Marcus", "Michael", "Chris", "James", "John", "David", "Anthony", "Josh",
         "Jordan", "Justin", "Brandon", "William", "Robert", "Isaiah", "Carter", "Cole"]),
    (3, ["DeShawn", "Tyrell", "Xavier", "Malik", "Andre", "Darius", "Bryce", "Hunter",
         "Dominic", "Trey", "Cooper", "Quinton", "Rashad", "Khalil", "Jaxon", "Roman",
         "Emmett", "Nasir", "Zane", "Lincoln", "Silas", "Tobias", "Diego", "Gio",
         "Brock", "Kade", "Beau", "Jaylen", "Christopher", "Cassius"]),
    (1, ["Tavion", "Keisean", "Zamir", "Ozzie", "Bodie", "Maverick", "Kingston",
         "Baron", "Duke", "Ransom", "Colter", "Stellan", "Ivory", "Booker"]),
]
_FIRST_WEIGHTED = [n for w, names in FIRST_TIERS for n in names for _ in range(w)]

REGIONAL_FIRST = {
    "South":   ["DeAndre", "JaCorey", "Tyreek", "Quan", "Malik", "Trevon", "Tyjae",
                "Darius", "Jalen", "Ladarius", "Keshawn", "Montario", "Amari", "Devonta"],
    "Midwest": ["Erik", "Gunnar", "Mason", "Cole", "Wyatt", "Lars", "Soren",
                "Brecken", "Casey", "Dane", "Anders", "Holt"],
    "West":    ["Diego", "Santiago", "Kai", "Adrian", "Rocco", "Nico", "Dre",
                "Cruz", "Mateo", "Ezekiel"],
    "Islands": ["Keanu", "Kaimana", "Alika", "Tui", "Sione", "Tavita", "Penei",
                "Manti", "Talanoa", "Marist"],
    "Africa":  ["Chukwuemeka", "Oluwaseun", "Emeka", "Chidi", "Osa", "Efe",
                "Tunde", "Kelechi", "Uche", "Femi"],
}
REGIONAL_LAST = {
    "Islands": ["Tagovailoa", "Fangupo", "Sopoaga", "Tuipulotu", "Niumatalolo", "Amosa"],
    "Africa":  ["Okafor", "Adebayo", "Ekwonu", "Umeh", "Ogbah", "Nwosu"],
    "South":   ["Lattimore", "Holliday", "Boone", "Calloway", "Mabry", "Teague"],
}
STATE_REGION = {
    "TX": "South", "FL": "South", "GA": "South", "LA": "South", "AL": "South",
    "TN": "South", "NC": "South", "VA": "South", "MS": "South",
    "OH": "Midwest", "MI": "Midwest", "IL": "Midwest", "MO": "Midwest",
    "MN": "Midwest", "PA": "Midwest", "NJ": "Midwest",
    "CA": "West", "NV": "West", "AZ": "West", "WA": "West",
    "HI": "Islands", "AS": "Islands", "NGA": "Africa", "GHA": "Africa",
}
# Naming trends drift ~ every 8 seasons: a 30-year franchise SOUNDS like eras.
ERA_FIRST = {
    1: ["Zaiden", "Kylo", "Onyx", "Ace", "Wilder", "Creed", "Legend", "Maddox", "Ryker"],
    2: ["Neo", "Orion", "Zephyr", "Atlas", "Nova", "Kaius", "Jettson", "Halcyon", "Vega"],
}
SHORT_FORMS = {
    "William": ["Will", "Billy"], "Robert": ["Rob", "Bobby"], "James": ["Jim", "Jimmy"],
    "Anthony": ["Ant", "Tony"], "Christopher": ["Chris", "Topher"], "Michael": ["Mike"],
    "DeAndre": ["Dre"], "Joshua": ["Josh"], "Ezekiel": ["Zeke"], "Chukwuemeka": ["Emeka"],
    "Oluwaseun": ["Seun"], "Cassius": ["Cash"], "Santiago": ["Santi"],
}
NICKNAMES = ["Tank", "Jet", "Deuce", "Slim", "Bo", "Moose", "Ace", "Smoke", "Flash",
             "Truck", "Champ", "Sticks", "Bear", "Blue", "Scooter", "Pop", "Juice", "Bolt"]


def _pick_first(rng, region, season):
    if region and region in REGIONAL_FIRST and rng.random() < 0.40:
        return rng.choice(REGIONAL_FIRST[region])
    era = min(2, max(0, (int(season or 1) - 1) // 8))
    if era and rng.random() < 0.18:
        return rng.choice(ERA_FIRST[era])
    return rng.choice(_FIRST_WEIGHTED)


def _gen_identity(rng, hometown="", season=1, seen=None):
    """A complete identity: legal name (first middle last), preferred football
    name, jersey name, maybe a nickname — unique against `seen` display names."""
    st = hometown.rsplit(", ", 1)[-1] if hometown and ", " in hometown else ""
    region = STATE_REGION.get(st)
    first = last = ""
    for _ in range(12):
        first = _pick_first(rng, region, season)
        last = (rng.choice(REGIONAL_LAST[region])
                if region in REGIONAL_LAST and rng.random() < 0.35
                else rng.choice(LAST_NAMES))
        if seen is None or f"{first} {last}" not in seen:
            break
    middle = rng.choice(_FIRST_WEIGHTED)
    while middle == first:
        middle = rng.choice(_FIRST_WEIGHTED)
    preferred = (rng.choice(SHORT_FORMS[first])
                 if first in SHORT_FORMS and rng.random() < 0.6 else first)
    nickname = rng.choice(NICKNAMES) if rng.random() < 0.10 else ""
    if seen is not None:
        seen.add(f"{first} {last}")
        seen.add(f"{preferred} {last}")
    return {"name": f"{preferred} {last}", "first": first, "middle": middle, "last": last,
            "legal_name": f"{first} {middle} {last}", "nickname": nickname,
            "jersey_name": f"{preferred[0]}. {last}"}

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
    ("Orlando", "FL"), ("San Diego", "CA"), ("Fresno", "CA"), ("Minneapolis", "MN"),
    ("Honolulu", "HI"), ("Laie", "HI"), ("Pago Pago", "AS"), ("Lagos", "NGA"), ("Accra", "GHA"),
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


def _gen_player(rng, pos, base=None, season=1, seen=None):
    age = rng.randint(21, 34)
    overall = base if base is not None else int(rng.triangular(58, 92, 74))
    overall = max(48, min(99, overall))
    pot_gap = max(0, int(rng.triangular(0, 22, 6)) - (age - 24))
    potential = max(overall, min(99, overall + pot_gap))
    aav = round(max(0.7, max(0, overall - 55) ** 1.7 / 22.0), 1)
    bg = _gen_background(rng)
    ident = _gen_identity(rng, bg["hometown"], season, seen)
    return {
        "id": f"p{rng.randint(100000, 999999)}",
        **ident,
        **bg,
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
        **_gen_human_profile(rng),
    }


def _gen_roster(rng, strength, season=1, seen=None):
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
            roster.append(_gen_player(rng, pos, base, season=season, seen=seen))
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


def _gen_team(rng, idx, entry, season=1, seen=None):
    conf, div, city, mascot, market = entry
    strength = rng.random()
    roster = _gen_roster(rng, strength, season=season, seen=seen)
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


def _gen_fa_pool(rng, n=40, season=1, seen=None):
    pool = [_gen_player(rng, rng.choice(list(ROSTER)), int(rng.triangular(60, 88, 70)), season=season, seen=seen) for _ in range(n)]
    for p in pool:
        _attach_agent(rng, p)
    return pool


def _synth_season_stats(rng, p):
    """A believable prior-season line for a veteran free agent, scaled to his
    overall/age — so the market shows how he played last year. Returns None for
    positions with no natural box line (OL)."""
    o = int(p.get("overall", 70) or 70)
    pos, age = p.get("pos"), int(p.get("age", 27) or 27)
    d = max(0, o - 60)
    agef = 0.9 if age >= 32 else (1.05 if 25 <= age <= 29 else 1.0)
    j = lambda lo, hi: rng.uniform(lo, hi)
    g = rng.randint(13, 17)
    if pos == "QB":
        return {"g": g, "pass_yd": int((2600 + d * 95) * agef * j(0.9, 1.12)),
                "pass_td": max(6, int((12 + d * 1.05) * agef * j(0.85, 1.2))),
                "int": max(3, int((15 - d * 0.32) * j(0.7, 1.25))), "syn": 1}
    if pos == "RB":
        rec = int((18 + d * 1.1) * j(0.7, 1.2))
        return {"g": g, "rush_yd": int((520 + d * 42) * agef * j(0.8, 1.2)),
                "rush_td": max(1, int((3 + d * 0.34) * agef * j(0.7, 1.3))),
                "rec": rec, "rec_yd": rec * 8, "syn": 1}
    if pos in ("WR", "TE"):
        rec = max(8, int(((30 if pos == "WR" else 22) + d * 2.0) * agef * j(0.75, 1.2)))
        ypc = j(11, 15) if pos == "WR" else j(9, 12)
        return {"g": g, "rec": rec, "rec_yd": int(rec * ypc),
                "rec_td": max(1, int((2 + d * 0.32) * j(0.7, 1.35))), "syn": 1}
    if pos in ("DL", "LB"):
        return {"g": g, "sack": round(max(0.0, (1.5 + d * 0.30) * agef * j(0.6, 1.4)), 1),
                "tackle": int((32 + d * 1.6) * j(0.8, 1.2)), "syn": 1}
    if pos in ("CB", "S"):
        return {"g": g, "def_int": max(0, int((1 + d * 0.12) * j(0.5, 1.6))),
                "pd": max(1, int((5 + d * 0.45) * j(0.7, 1.3))),
                "tackle": int((38 + d * 1.3) * j(0.8, 1.2)), "syn": 1}
    if pos == "K":
        fgm = max(10, int((17 + d * 0.5) * j(0.8, 1.15)))
        return {"g": g, "fgm": fgm, "fga": fgm + rng.randint(2, 6),
                "pts": fgm * 3 + rng.randint(15, 45), "syn": 1}
    return None                                    # OL etc. — no natural box line


def ensure_fa_prior_stats(save):
    """Back-fill a prior-season line onto veteran free agents so you can see how
    they played last year. Idempotent — skips anyone who already has stats (a real
    line, e.g. a player you let walk) or is flagged unproven. Returns changed."""
    changed = False
    for p in save.get("free_agents", []):
        if not isinstance(p, dict) or p.get("stats") or p.get("_no_tape"):
            continue
        if int(p.get("age", 27) or 27) < 23:
            p["_no_tape"] = 1                       # too young for a real pro year
            changed = True
            continue
        rng = _rng(sum(ord(c) for c in str(p.get("id", ""))) + int(save.get("season", 1)))
        line = _synth_season_stats(rng, p)
        p["stats" if line else "_no_tape"] = line if line else 1
        changed = True
    return changed


def _all_generated_players(save):
    for team in save.get("teams", []):
        for p in team.get("roster", []):
            yield p
        for p in team.get("practice_squad", []):
            yield p
    for p in save.get("free_agents", []):
        yield p
    for p in (save.get("draft") or {}).get("class", []):
        yield p


def ensure_player_portraits(save):
    records = portrait_assets.load_records()
    if not records:
        return 0
    used = {p.get("portrait_id") for p in _all_generated_players(save) if p.get("portrait_id")}
    changed = 0
    for p in _all_generated_players(save):
        if not p.get("portrait_id"):
            pid = portrait_assets.assign_player(p, used_ids=used, records=records)
            if pid:
                used.add(pid)
                changed += 1
    return changed


def new_league(seed):
    rng = _rng(seed)
    seen = set()   # league-wide name uniqueness from day one
    teams = [_gen_team(rng, i, NFL_TEAMS[i], seen=seen) for i in range(LEAGUE_SIZE)]
    generate_team_histories(teams, rng)
    ensure_owner_names(teams, rng)
    return teams, _gen_fa_pool(rng, seen=seen)


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
SITUATIONAL_PACKAGES = {
    "nickel": {"label": "Nickel", "desc": "Passing downs with a fourth corner.",
               "slots": {"DL": 4, "LB": 2, "CB": 4, "S": 2}},
    "dime": {"label": "Dime", "desc": "Long-yardage coverage with five DBs.",
             "slots": {"DL": 3, "LB": 1, "CB": 5, "S": 2}},
    "red_zone": {"label": "Red Zone", "desc": "Condensed-field scoring package.",
                 "slots": {"QB": 1, "RB": 1, "WR": 2, "TE": 2, "OL": 5, "DL": 4, "LB": 3, "CB": 3, "S": 2}},
    "third_down": {"label": "3rd Down", "desc": "Money-down receivers and rushers.",
                   "slots": {"QB": 1, "RB": 1, "WR": 4, "TE": 1, "OL": 5, "DL": 4, "LB": 2, "CB": 3, "S": 2}},
    "goal_line": {"label": "Goal Line", "desc": "Heavy bodies for short yardage.",
                  "slots": {"QB": 1, "RB": 2, "WR": 1, "TE": 2, "OL": 5, "DL": 5, "LB": 4, "CB": 1, "S": 1}},
}


def pos_depth(team, pos):
    """Position depth order: the GM's saved chart first (self-healing as the
    roster churns), everyone else by overall. Clubs with no saved chart —
    every AI team — field best-OVR lineups exactly as before."""
    players = [p for p in team["roster"] if p["pos"] == pos]
    order = (team.get("depth") or {}).get(pos) or []
    idx = {pid: i for i, pid in enumerate(order)}
    return sorted(players, key=lambda p: (idx.get(p["id"], 999), -p["overall"]))


def package_depth(team, package, pos):
    players = [p for p in team["roster"] if p["pos"] == pos]
    order = (team.get("packages") or {}).get(package, {}).get(pos) or []
    if not order:
        return pos_depth(team, pos)
    idx = {pid: i for i, pid in enumerate(order)}
    return sorted(players, key=lambda p: (idx.get(p["id"], 999), -p["overall"]))


def package_power(team, package):
    spec = SITUATIONAL_PACKAGES.get(package)
    if not spec:
        return power_rating(team)
    num = den = 0.0
    for pos, slots in spec["slots"].items():
        best = package_depth(team, package, pos)[:slots]
        if not best:
            continue
        w = POS_WEIGHT.get(pos, 1.0)
        num += w * (sum(x["overall"] for x in best) / len(best)) * slots
        den += w * slots
    return round(num / den, 1) if den else power_rating(team)


def package_edge(save):
    team = current_team(save)
    wo = save.get("weekly_ops", {})
    focus = wo.get("focus", "")
    plan = wo.get("game_plan", "")
    wanted = set()
    if focus in ("Pass Game", "Pass Rush") or plan == "Aggressive":
        wanted.update(("third_down", "dime"))
    if focus == "Coverage" or wo.get("scout") == "Opponent":
        wanted.update(("nickel", "dime"))
    if focus == "Red Zone":
        wanted.add("red_zone")
    if focus == "Run Game" or plan in ("Conservative", "Protect the Unit"):
        wanted.add("goal_line")
    if not wanted:
        wanted = {"nickel", "third_down"}
    base = power_rating(team)
    edges = [max(-0.4, min(0.8, (package_power(team, p) - base) / 12.0)) for p in wanted]
    return round(sum(edges) / len(edges), 2) if edges else 0.0


def move_up_depth(save, pid, package="base"):
    """Bump a player one slot up his position's depth chart."""
    team = current_team(save)
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False, "He's not on your roster."
    pos = p["pos"]
    package = (package or "base").strip()
    if package != "base" and package not in SITUATIONAL_PACKAGES:
        return False, "That package does not exist."
    if package != "base" and pos not in SITUATIONAL_PACKAGES[package]["slots"]:
        return False, f"{p['name']} does not play in that package."
    cur = [x["id"] for x in (pos_depth(team, pos) if package == "base" else package_depth(team, package, pos))]
    i = cur.index(pid)
    if i == 0:
        label = "depth chart" if package == "base" else SITUATIONAL_PACKAGES[package]["label"]
        return False, f"{p['name']} already tops the {pos} {label}."
    cur[i - 1], cur[i] = cur[i], cur[i - 1]
    if package == "base":
        team.setdefault("depth", {})[pos] = cur
    else:
        team.setdefault("packages", {}).setdefault(package, {})[pos] = cur
    write_save(save)
    label = "depth chart" if package == "base" else SITUATIONAL_PACKAGES[package]["label"]
    return True, f"{p['name']} moves up the {pos} {label}."


def reset_depth(save, package="base"):
    team = current_team(save)
    package = (package or "base").strip()
    if package == "all":
        team.pop("depth", None)
        team.pop("packages", None)
        msg = "All depth charts reset - best man plays in every package."
    elif package == "base":
        team.pop("depth", None)
        msg = "Depth chart reset - best man plays at every spot."
    else:
        team.setdefault("packages", {}).pop(package, None)
        msg = f"{SITUATIONAL_PACKAGES.get(package, {}).get('label', 'Package')} reset - best fits play there."
    write_save(save)
    return True, msg


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


COLD_WEATHER_CITIES = {"Buffalo", "Chicago", "Cleveland", "Detroit", "Green Bay", "Minneapolis",
                       "New England", "New York", "Philadelphia", "Pittsburgh", "Denver",
                       "Cincinnati", "Indianapolis", "Kansas City", "Salt Lake City", "St. Louis"}
WARM_WEATHER_CITIES = {"Arizona", "Atlanta", "Carolina", "Dallas", "Houston", "Jacksonville",
                       "Las Vegas", "Los Angeles", "Miami", "New Orleans", "San Diego",
                       "San Francisco", "Tampa Bay", "Tennessee", "Orlando", "San Antonio",
                       "Oklahoma City", "Memphis"}
DOME_CITIES = {"Atlanta", "Dallas", "Detroit", "Houston", "Indianapolis", "Las Vegas",
               "Los Angeles", "Minnesota", "Minneapolis", "New Orleans", "Arizona"}
RAIN_CITIES = {"Seattle", "Portland", "Carolina", "Jacksonville", "Miami", "Tampa Bay",
               "New England", "New York", "Philadelphia", "Washington", "Baltimore"}


def game_weather(save, home_id, week):
    teams = {t["id"]: t for t in save.get("teams", [])}
    home = teams.get(home_id, {})
    city = home.get("city", "")
    if city in DOME_CITIES:
        return {"label": "Dome", "condition": "Indoor", "temp": 72, "wind": 0, "impact": 0.0}
    seed = int(save.get("seed", 1) or 1) + save.get("season", 1) * 503 + week * 37 + sum(ord(c) for c in city)
    rng = _rng(seed)
    late = week >= 12
    if city in COLD_WEATHER_CITIES:
        temp = rng.randint(18, 55) if late else rng.randint(42, 74)
    elif city in WARM_WEATHER_CITIES:
        temp = rng.randint(55, 88) if late else rng.randint(72, 98)
    else:
        temp = rng.randint(35, 68) if late else rng.randint(55, 82)
    wind = rng.randint(3, 24)
    wet_chance = 0.32 if city in RAIN_CITIES else 0.18
    condition = "Clear"
    if temp <= 32 and rng.random() < (0.28 if late else 0.08):
        condition = "Snow"
    elif rng.random() < wet_chance:
        condition = "Rain"
    elif wind >= 18:
        condition = "Wind"
    impact = 0.0
    if condition == "Snow":
        impact += 1.4
    elif condition == "Rain":
        impact += 0.9
    elif condition == "Wind":
        impact += 0.7
    if wind >= 18:
        impact += 0.4
    if temp <= 25:
        impact += 0.3
    label = f"{condition}, {temp}F" + (f", {wind} mph wind" if wind >= 12 else "")
    return {"label": label, "condition": condition, "temp": temp, "wind": wind, "impact": round(impact, 2)}


def weather_power_adjust(team, weather):
    impact = float(weather.get("impact", 0) or 0)
    if impact <= 0:
        return 0.0
    def avg(pos):
        vals = [p["overall"] for p in pos_depth(team, pos)[:ROSTER.get(pos, 1)]]
        return sum(vals) / len(vals) if vals else 65
    pass_core = (avg("QB") * 1.4 + avg("WR") + avg("TE") * 0.7) / 3.1
    run_core = (avg("RB") + avg("OL") * 1.3) / 2.3
    front = (avg("DL") + avg("LB")) / 2.0
    fit = ((run_core - pass_core) / 18.0) + ((front - 68) / 45.0)
    return round(max(-1.0, min(1.0, fit * impact)), 2)


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


def _conf_bracket(rng, seeds, powers, uid, run, names):
    """Run one conference's single-elim bracket, recording every game the user
    plays (round name, opponent, score, result). Returns the conference champ."""
    teams = seeds[:]
    while len(teams) > 1:
        teams.sort(key=lambda t: seeds.index(t))
        byes, active = [], teams[:]
        if len(active) % 2 == 1:
            byes, active = [active[0]], active[1:]
        pairs, i, j = [], 0, len(active) - 1
        while i < j:
            pairs.append((active[i], active[j])); i += 1; j -= 1
        remaining = len(byes) + len(pairs)
        rname = ("Conference Championship" if remaining == 1 else
                 "Divisional Round" if remaining == 2 else "Wild Card")
        winners = []
        for a, b in pairs:
            w = a if _sim_game(rng, powers[a], powers[b]) else b
            l = b if w == a else a
            winners.append(w)
            if uid in (a, b):
                opp = b if uid == a else a
                won = w == uid
                ws, ls = _score_line(rng, powers[w], powers[l])
                run["rounds"].append({"round": rname, "opp": names.get(opp, "?"), "opp_id": opp,
                                      "us": (ws if won else ls), "them": (ls if won else ws),
                                      "won": won})
        teams = byes + winners
    return teams[0]


def _run_postseason(save, rng, standings, powers):
    """Full postseason: two conference brackets + the BRK Championship. Records
    the user's path in `run`. Returns (champion, conf_champs, playoff_ids, run)."""
    uid = save["current_team_id"]
    names = {t["id"]: t["full"] for t in save["teams"]}
    playoff_ids, conf_champs = set(), []
    run = {"made": False, "seed": None, "conf": None, "rounds": []}
    for conf in CONFERENCES:
        seeds = [t["id"] for t in standings if t["conference"] == conf][:playoff_seeds(save)]
        playoff_ids.update(seeds)
        if uid in seeds:
            run.update(made=True, seed=seeds.index(uid) + 1, conf=conf)
        conf_champs.append(_conf_bracket(rng, seeds, powers, uid, run, names))
    a, b = conf_champs[0], conf_champs[1]
    champ = a if _sim_game(rng, powers[a], powers[b]) else b
    loser = b if champ == a else a
    if uid in (a, b):
        opp = b if uid == a else a
        won = champ == uid
        ws, ls = _score_line(rng, powers[champ], powers[loser])
        run["rounds"].append({"round": "BRK Championship", "opp": names.get(opp, "?"), "opp_id": opp,
                              "us": (ws if won else ls), "them": (ls if won else ws), "won": won})
    return champ, conf_champs, playoff_ids, run




TRADE_DEADLINE_SOLO = 9


def _add_stats(p, d):
    s = p.setdefault("stats", {})
    for k, v in d.items():
        s[k] = round(s.get(k, 0) + v, 1) if isinstance(v, float) else s.get(k, 0) + v


def _distribute(total, weights, rng):
    """Split an integer `total` across buckets in proportion to `weights`, with the
    result guaranteed to sum back to `total` (leftover from rounding goes to the
    biggest fractional shares). Used to make a QB's passing line add up exactly to
    his receivers' catches, yards and TDs."""
    n = len(weights)
    tw = sum(weights)
    if total <= 0 or tw <= 0 or n == 0:
        return [0] * n
    raw = [total * (w / tw) for w in weights]
    out = [int(x) for x in raw]
    order = sorted(range(n), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    for j in range(total - sum(out)):
        out[order[j % n]] += 1
    return out


def _assign_scores(n, caps, weights, rng):
    """Hand out `n` scores (TDs) one at a time to weighted buckets, never giving a
    bucket more than its `cap` (a man can't score more TDs than he had touches).
    Returns a per-bucket count; sums to n as long as the caps allow."""
    got = [0] * len(caps)
    for _ in range(n):
        elig = [i for i in range(len(caps)) if got[i] < caps[i]]
        if not elig:
            break
        wsum = sum(max(1, weights[i]) for i in elig)
        pick, acc = rng.random() * wsum, 0.0
        for i in elig:
            acc += max(1, weights[i])
            if pick <= acc:
                got[i] += 1
                break
    return got


def _score_breakdown(points, rng):
    """Reconstruct a plausible scoring summary that sums EXACTLY to `points`:
    touchdowns (6) + successful PATs (1) + two-point conversions (2) + field goals
    (3). This is what makes the box score add up to the final on the scoreboard."""
    if points <= 0:
        return {"td": 0, "fg": 0, "xp": 0, "two": 0}
    cands = []
    for td in range(0, points // 6 + 1):
        rem = points - 6 * td
        for fg in range(0, min(6, rem // 3) + 1):   # more than ~5 FGs in a game is unheard of
            E = rem - 3 * fg                        # extra points still to place on the TDs
            if 0 <= E <= 2 * td:
                two = max(0, E - td)                # TDs forced to a 2-pt conversion
                miss = max(0, td - E)               # TDs with no extra point (missed/none)
                # Prefer ~7 pts/TD, few FGs, and mostly ordinary PATs (2-pt tries and
                # missed extra points are both rare).
                w = (math.exp(-abs(td - points / 7.0)) * (0.45 ** max(0, fg - 2))
                     * (0.3 ** two) * (0.32 ** miss))
                if td == 0 and points >= 9:
                    w *= 0.1                        # all-field-goal games are rare
                cands.append((w, td, fg, E))
    if not cands:                                  # unreachable for realistic scores
        return {"td": 0, "fg": points // 3, "xp": 0, "two": 0}
    tot = sum(c[0] for c in cands)
    pick, acc, td, fg, E = rng.random() * tot, 0.0, 0, 0, 0
    for w, t, f, e in cands:
        acc += w
        if pick <= acc:
            td, fg, E = t, f, e
            break
    two = max(0, E - td)                            # 2-pt tries only when parity needs them
    return {"td": td, "fg": fg, "xp": max(0, E - 2 * two), "two": two}


def _game_perf(team, points, won, rng, out_ids=(), record=True):
    """Generate ONE game's box score for a team so it RECONSTRUCTS the final score:
    the touchdowns and field goals add up to `points`, the QB's passing equals his
    receivers' catches, and player archetypes (a dual-threat QB, a bell-cow back,
    the receiving corps) decide who produces. With record=True adds to season
    totals (playoff games pass record=False so they don't skew season leaders);
    returns (standouts-for-game-stars, team summary that the recap displays)."""
    by_pos = {pos: [p for p in pos_depth(team, pos) if p["id"] not in out_ids] for pos in ROSTER}
    wb = 1.08 if won else 0.94
    add = _add_stats if record else (lambda *a, **k: None)
    perf = []

    plan = _score_breakdown(points, rng)               # TDs + FGs + PATs that sum to `points`
    n_td, n_fg = plan["td"], plan["fg"]
    vol = 0.85 + 0.30 * (points / 24.0)                # a high-scoring day = more plays & yards

    qb = (by_pos.get("QB", []) or [None])[0]
    wrs = by_pos.get("WR", [])[:3]
    tes = by_pos.get("TE", [])[:1]
    rbs = by_pos.get("RB", [])[:2]
    qb_mobile = bool(qb and qb.get("style") in ("Dual Threat", "RPO Specialist"))
    rb_best = max([r["overall"] for r in rbs], default=62)

    # --- Split the offensive TDs into ground vs air by personnel & archetype ---
    rush_share = 0.33 + (0.15 if qb_mobile else 0.0) + max(-0.08, min(0.12, (rb_best - 72) * 0.006))
    n_rush_td = max(0, min(n_td, int(round(n_td * rush_share))))
    n_pass_td = n_td - n_rush_td

    # --- QB passing line: volume + yards scale with the scoring; comps cover the TDs ---
    att = comp = pass_yd = intc = 0
    if qb:
        o = qb["overall"]
        att = int(rng.randint(24, 40) * (0.92 + 0.14 * (points / 24.0)))
        comp = min(att, max(n_pass_td, int(att * min(0.72, 0.53 + (o - 55) * 0.0035))))
        pass_yd = int(comp * rng.uniform(6.6, 9.4) * vol * wb)
        intc = rng.randint(0, 2) if rng.random() < (0.4 if won else 0.6) else 0

    # --- QB rushing: a genuine dual-threat contribution ---
    qb_car = qb_rush_yd = 0
    if qb_mobile:
        qb_car = rng.randint(4, 10)
        qb_rush_yd = int(qb_car * rng.uniform(4.6, 7.8) * wb)
    elif qb and rng.random() < 0.5:
        qb_car = rng.randint(1, 4)
        qb_rush_yd = int(qb_car * rng.uniform(1.5, 4.5))

    # --- Distribute the QB's catches/yards/TDs across the receiving corps ---
    corps = []                                         # [player, target_weight, ypc_weight]
    for idx, w in enumerate(wrs):
        slot = (3.0, 2.1, 1.3)[idx] if idx < 3 else 1.0
        corps.append([w, slot * (1 + (w["overall"] - 65) * 0.005), 1.2])
    for t in tes:
        corps.append([t, 1.6 * (1 + (t["overall"] - 65) * 0.005), 1.0])
    for idx, r in enumerate(rbs):
        corps.append([r, (1.2 if idx == 0 else 0.5), 0.55])
    recs = _distribute(comp, [c[1] for c in corps], rng)
    ryds = _distribute(pass_yd, [recs[i] * corps[i][2] for i in range(len(corps))], rng)
    rec_td = _assign_scores(n_pass_td, recs, ryds, rng)     # capped at catches, weighted by yards
    recv = {corps[i][0]["id"]: (recs[i], ryds[i], rec_td[i]) for i in range(len(corps))}

    # --- Rushing yards, then the ground TDs across RBs (+ a mobile QB) ---
    rb_car, rb_yd = [], []
    for i, rb in enumerate(rbs):
        o = rb["overall"]
        car = max(1, int(rng.randint(9, 20) * (1.0 if i == 0 else 0.5) * (1 + (o - 65) * 0.005) * vol))
        rb_car.append(car)
        rb_yd.append(int(car * rng.uniform(3.4, 5.6) * wb))
    runners = [rb["id"] for rb in rbs] + ([qb["id"]] if (qb and qb_car) else [])
    run_caps = list(rb_car) + ([qb_car] if (qb and qb_car) else [])
    run_wts = [rb_yd[i] + 5 for i in range(len(rbs))] + \
              ([(qb_rush_yd + 8) * (1.5 if qb_mobile else 0.4)] if (qb and qb_car) else [])
    ground_td = _assign_scores(n_rush_td, run_caps, run_wts, rng)
    rush_td_by = {runners[k]: ground_td[k] for k in range(len(runners))}

    total_rush_yd = qb_rush_yd + sum(rb_yd)

    # ---- Emit QB ----
    if qb:
        qb_rush_td = rush_td_by.get(qb["id"], 0)
        stat = {"g": 1, "pass_att": att, "pass_cmp": comp, "pass_yd": pass_yd, "pass_td": n_pass_td, "int": intc}
        if qb_car:
            stat.update(rush_car=qb_car, rush_yd=qb_rush_yd, rush_td=qb_rush_td)
        add(qb, stat)
        line = f"{comp}/{att}, {pass_yd} yd, {n_pass_td} TD" + (f", {intc} INT" if intc else "")
        if qb_car:
            line += f" · {qb_car} car, {qb_rush_yd} yd" + (f", {qb_rush_td} TD" if qb_rush_td else "")
        perf.append({"name": qb["name"], "pos": "QB", "pid": qb["id"], "line": line,
                     "g": {"pass_yd": pass_yd, "pass_td": n_pass_td, "pass_cmp": comp, "pass_att": att,
                           "int": intc, "rush_yd": qb_rush_yd, "rush_td": qb_rush_td},
                     "score": pass_yd * 0.04 + n_pass_td * 4 - intc * 2 + qb_rush_yd * 0.06 + qb_rush_td * 6})

    # ---- Emit RBs ----
    for i, rb in enumerate(rbs):
        rc, rcy, rct = recv.get(rb["id"], (0, 0, 0))
        rtd = rush_td_by.get(rb["id"], 0)
        add(rb, {"g": 1, "rush_car": rb_car[i], "rush_yd": rb_yd[i], "rush_td": rtd,
                        "rec": rc, "rec_yd": rcy, "rec_td": rct})
        line = f"{rb_car[i]} car, {rb_yd[i]} yd, {rtd} TD"
        if rc:
            line += f" · {rc} rec, {rcy} yd" + (f", {rct} TD" if rct else "")
        perf.append({"name": rb["name"], "pos": "RB", "pid": rb["id"], "line": line,
                     "g": {"rush_yd": rb_yd[i], "rush_td": rtd, "rush_car": rb_car[i],
                           "rec": rc, "rec_yd": rcy, "rec_td": rct},
                     "score": rb_yd[i] * 0.06 + rtd * 6 + rcy * 0.06 + rct * 6})

    # ---- Emit WR / TE ----
    for c in wrs + tes:
        rc, rcy, rct = recv.get(c["id"], (0, 0, 0))
        add(c, {"g": 1, "rec": rc, "rec_yd": rcy, "rec_td": rct})
        perf.append({"name": c["name"], "pos": c["pos"], "pid": c["id"],
                     "g": {"rec": rc, "rec_yd": rcy, "rec_td": rct},
                     "line": f"{rc} rec, {rcy} yd, {rct} TD", "score": rcy * 0.06 + rct * 6 + rc * 0.4})

    # ---- Defense ----
    for d in by_pos.get("DL", [])[:4] + by_pos.get("LB", [])[:3]:
        o = d["overall"]
        sk = round(max(0.0, (o - 66) * 0.02) + (rng.random() * 1.2 if rng.random() < 0.4 else 0.0), 1)
        tk = rng.randint(1, 6)
        add(d, {"g": 1, "sack": sk, "tackle": tk})
        if sk >= 1.5:
            perf.append({"name": d["name"], "pos": d["pos"], "pid": d["id"],
                         "g": {"sack": sk, "tackle": tk},
                         "line": f"{sk} sacks, {tk} tkl", "score": sk * 5 + tk * 0.3})
    for d in by_pos.get("CB", [])[:3] + by_pos.get("S", [])[:2]:
        o = d["overall"]
        di = 1 if rng.random() < max(0, (o - 72) * 0.02) else 0
        add(d, {"g": 1, "tackle": rng.randint(1, 6), "def_int": di, "pd": 1 if rng.random() < 0.3 else 0})

    # ---- Kicker: field goals + PATs reconstruct the kicking points exactly ----
    for kx in by_pos.get("K", [])[:1]:
        add(kx, {"g": 1, "fgm": n_fg, "fga": n_fg + (1 if rng.random() < 0.18 else 0),
                 "xpm": plan["xp"], "pts": n_fg * 3 + plan["xp"]})

    summary = {"td": n_td, "fg": n_fg, "two": plan["two"], "pass_yd": pass_yd,
               "rush_yd": total_rush_yd, "total_yd": pass_yd + total_rush_yd, "points": points}
    return perf, summary


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
KEY_MOMENTS = {
    "Balanced": {"edge": 0.0, "blurb": "Default sideline calls in high-leverage spots."},
    "Trust the Math": {"edge": 0.45, "blurb": "Aggressive 4th downs and two-point math. More upside, more scrutiny."},
    "Field Position": {"edge": 0.18, "blurb": "Punt, pin, and protect the defense in swing moments."},
    "Red Zone Punch": {"edge": 0.32, "blurb": "Lean into heavy red-zone calls and finish drives."},
    "Two-Minute Heat": {"edge": 0.28, "blurb": "Tempo, sideline throws, and end-half pressure."},
}


def init_weekly_ops(save):
    save["weekly_ops"] = {"intensity": "Balanced", "focus": "Scheme Install",
                          "medical": "Balanced", "game_plan": "Balanced", "scout": "Opponent",
                          "key_moment": "Balanced"}
    return save["weekly_ops"]


def set_weekly_plan(save, **fields):
    wo = save.setdefault("weekly_ops", {})
    for key, table in (("intensity", PRACTICE_INTENSITY), ("focus", PRACTICE_FOCUS),
                       ("medical", MEDICAL_POLICY), ("game_plan", GAME_PLANS), ("scout", SCOUT_ASSIGNMENTS),
                       ("key_moment", KEY_MOMENTS)):
        v = fields.get(key)
        if v is not None and v in table:
            wo[key] = v
    if fields.get("plays") is not None:                # multi-select featured plays (capped)
        wo["plays"] = [k for k in fields["plays"] if k in FEATURED_PLAYS][:FEATURED_PLAYS_MAX]
    if fields.get("off_identity") in OFF_IDENTITIES:   # weekly offensive identity
        wo["off_identity"] = fields["off_identity"]
    if fields.get("def_identity") in DEF_IDENTITIES:   # weekly defensive identity
        wo["def_identity"] = fields["def_identity"]
    if fields.get("rb_usage") in SNAP_RB:              # snap plan
        wo["rb_usage"] = fields["rb_usage"]
    if fields.get("rookie_snaps") in SNAP_ROOKIE:
        wo["rookie_snaps"] = fields["rookie_snaps"]
    write_save(save)
    return wo


def key_moment_edge(save):
    wo = save.get("weekly_ops", {})
    call = wo.get("key_moment", "Balanced")
    edge = KEY_MOMENTS.get(call, KEY_MOMENTS["Balanced"]).get("edge", 0.0)
    focus = wo.get("focus", "")
    plan = wo.get("game_plan", "")
    if call == "Trust the Math" and plan == "Aggressive":
        edge += 0.18
    elif call == "Field Position" and plan in ("Conservative", "Protect the Unit"):
        edge += 0.15
    elif call == "Red Zone Punch" and focus == "Red Zone":
        edge += 0.2
    elif call == "Two-Minute Heat" and focus in ("Pass Game", "Ball Security"):
        edge += 0.14
    return round(edge, 2)


def key_moment_summary(save):
    call = (save.get("weekly_ops") or {}).get("key_moment", "Balanced")
    spec = KEY_MOMENTS.get(call, KEY_MOMENTS["Balanced"])
    return {"call": call, "edge": key_moment_edge(save), "blurb": spec.get("blurb", "")}


# --------------------------------------------------------------------------- #
# Featured plays — your PLAYBOOK for the week. Pick the concepts you'll lean on;
# each one rewards you when your PERSONNEL fits it (a real fit lever that sits on
# TOP of the coordinator's scheme) and lifts the featured player's morale (the
# ball is locker-room currency). Forcing a concept your roster doesn't fit is a
# small negative — square pegs don't run it well.
# --------------------------------------------------------------------------- #
FEATURED_PLAYS_MAX = 3
FEATURED_PLAYS = {
    "vertical":     {"label": "Vertical Shots", "pos": "WR", "n": 2, "styles": ("Deep Threat",),
                     "support": ("QB", ("Pocket Passer", "Dual Threat")),
                     "blurb": "Take the top off — deep threats and a QB who'll let it rip."},
    "quick_game":   {"label": "Quick Game", "pos": "WR", "n": 2, "styles": ("Slot", "Possession"),
                     "blurb": "Rhythm and timing — slot and possession targets."},
    "ground":       {"label": "Ground & Pound", "pos": "RB", "n": 1, "styles": ("Power Back", "Every-Down"),
                     "support": ("OL", ("Power",)),
                     "blurb": "Impose your will — a power back behind a mauling line."},
    "outside_zone": {"label": "Outside Zone", "pos": "RB", "n": 1, "styles": ("Scat Back", "Every-Down"),
                     "support": ("OL", ("Zone",)),
                     "blurb": "Get to the edge — a quick back on zone blocking."},
    "qb_runs":      {"label": "Designed QB Runs", "pos": "QB", "n": 1, "styles": ("Dual Threat", "RPO Specialist"),
                     "blurb": "Add a runner — put a mobile QB in the run game."},
    "feature_te":   {"label": "Feature the TE", "pos": "TE", "n": 1, "styles": ("Move TE",),
                     "blurb": "Hunt matchups — a receiving TE up the seam."},
    "back_pass":    {"label": "Back in the Pass Game", "pos": "RB", "n": 1, "styles": ("Scat Back",),
                     "blurb": "Get your back the ball — screens and check-downs."},
}


def play_fit(save, key):
    """How well the roster fits one featured play: a 0-100 personnel fit, a bounded
    power edge, and the players it showcases (whose morale it lifts)."""
    spec = FEATURED_PLAYS.get(key)
    if not spec:
        return None
    team = current_team(save)
    featured = pos_depth(team, spec["pos"])[:spec.get("n", 1)]
    if not featured:
        return {"key": key, "label": spec["label"], "blurb": spec["blurb"], "pos": spec["pos"],
                "pct": 0, "edge": 0.0, "strong": False, "featured": []}
    pct = sum(1 for p in featured if p.get("style") in spec["styles"]) / len(featured)
    sup = spec.get("support")                          # a supporting group (OL for a run, QB for shots)
    if sup:
        sp = pos_depth(team, sup[0])[:3]
        if sp:
            pct = pct * 0.75 + (sum(1 for p in sp if p.get("style") in sup[1]) / len(sp)) * 0.25
    reps = (save.get("familiarity") or {}).get(key, 0)
    fam = round(min(0.15, reps * 0.02), 2)             # a well-drilled concept gets more reliable
    edge = round(max(-0.25, min(0.6, pct - 0.4)) + fam, 2)
    return {"key": key, "label": spec["label"], "blurb": spec["blurb"], "pos": spec["pos"],
            "pct": int(round(pct * 100)), "edge": edge, "strong": pct >= 0.6, "reps": reps, "fam": fam,
            "featured": [{"id": p["id"], "name": p["name"], "pos": p["pos"],
                          "style": p.get("style", ""), "fits": p.get("style") in spec["styles"]}
                         for p in featured]}


def selected_plays(save):
    return [k for k in (save.get("weekly_ops", {}).get("plays") or []) if k in FEATURED_PLAYS]


def featured_plays_edge(save):
    """Net weekly power edge from your featured plays' personnel fit (bounded)."""
    tot = sum((play_fit(save, k) or {}).get("edge", 0.0) for k in selected_plays(save))
    return round(max(-0.5, min(1.2, tot)), 2)


def featured_plays_report(save):
    """Every featured play with its fit + selection state, for the Command Center."""
    sel = set(selected_plays(save))
    plays = []
    for k in FEATURED_PLAYS:
        f = play_fit(save, k)
        if f:
            f["on"] = k in sel
            plays.append(f)
    return {"plays": plays, "selected": list(sel), "max": FEATURED_PLAYS_MAX, "edge": featured_plays_edge(save)}


def apply_featured_play_morale(save):
    """Featuring a player in the game plan lifts his morale/confidence that week —
    more when he actually fits the concept. Bounded by the normal 99 cap."""
    for k in selected_plays(save):
        f = play_fit(save, k)
        for pl in (f or {}).get("featured", []):
            _nudge(save, pl["id"], morale=2 if pl["fits"] else 1, conf=1 if pl["fits"] else 0)


# --------------------------------------------------------------------------- #
# Weather ↔ game plan. The sky doesn't just shave a flat rating — it changes
# which CONCEPTS work. Wind kills deep shots and long field goals, rain and snow
# reward the run and punish the deep ball, heat wears everyone down. Your chosen
# featured plays + game plan meet the forecast, and the Command Center warns you
# before you lock it in.
# --------------------------------------------------------------------------- #
_PLAY_WX_CAT = {"vertical": "deep_pass", "quick_game": "short_pass", "back_pass": "short_pass",
                "feature_te": "short_pass", "ground": "run_power", "outside_zone": "run_finesse",
                "qb_runs": "qb_run"}


def _upcoming_game_weather(save):
    iz = save.get("inseason")
    if not iz:
        return None
    week, uid = iz["week"], save["current_team_id"]
    g = next((x for x in save.get("schedule", [])
              if x["week"] == week and uid in (x["home"], x["away"])), None)
    return game_weather(save, g["home"], week) if g else None


def _wx_play_delta(cond, windy, cat):
    d = 0.0
    if cat == "deep_pass":
        d -= 0.4 if windy else 0.0
        d -= 0.25 if cond == "Rain" else 0.35 if cond == "Snow" else 0.0
    elif cat == "short_pass":
        d -= 0.1 if windy else 0.0
        d -= 0.15 if cond == "Rain" else 0.2 if cond == "Snow" else 0.0
    elif cat == "run_power":
        d += 0.3 if cond == "Snow" else 0.15 if cond == "Rain" else 0.0
        d += 0.1 if windy else 0.0
    elif cat == "run_finesse":
        d += 0.1 if cond in ("Snow", "Rain") else 0.0
    elif cat == "qb_run":
        d -= 0.1 if cond == "Rain" else 0.15 if cond == "Snow" else 0.0
    return d


def weather_plan_edge(save):
    """Net power swing from how this week's forecast meets your plan (bounded)."""
    wx = _upcoming_game_weather(save)
    if not wx or wx["condition"] == "Indoor":
        return 0.0
    cond, wind, temp = wx["condition"], wx.get("wind", 0), wx.get("temp", 70)
    windy = wind >= 15
    e = sum(_wx_play_delta(cond, windy, _PLAY_WX_CAT.get(k, "")) for k in selected_plays(save))
    plan = save.get("weekly_ops", {}).get("game_plan", "Balanced")
    if windy or cond in ("Rain", "Snow"):
        e += -0.3 if plan == "Aggressive" else 0.15 if plan in ("Conservative", "Protect the Unit") else 0.0
    if temp >= 90:
        e -= 0.1                                                 # heat wears down the big guys
    return round(max(-1.0, min(0.6, e)), 2)


def weather_plan_report(save):
    """Forecast + how it meets your plan, with pre-lock warnings for the Command
    Center. None on a bye; a dome is flagged as a non-factor."""
    wx = _upcoming_game_weather(save)
    if not wx:
        return None
    cond, wind, temp = wx["condition"], wx.get("wind", 0), wx.get("temp", 70)
    if cond == "Indoor":
        return {"dome": True, "label": wx.get("label", "Dome"), "edge": 0.0, "notes": []}
    windy = wind >= 15
    sel = set(selected_plays(save))
    notes = []
    if windy:
        if "vertical" in sel:
            notes.append({"lvl": "warn", "text": f"{wind} mph wind — Vertical Shots lose their juice downfield."})
        else:
            notes.append({"lvl": "info", "text": f"{wind} mph wind favors the run and quick game; long field goals get dicey."})
    if cond == "Rain":
        notes.append({"lvl": "warn", "text": "Rain — expect fumbles and sloppy routes; ball security and the run matter."})
    if cond == "Snow":
        if "ground" in sel or "outside_zone" in sel:
            notes.append({"lvl": "good", "text": "Snow — power football weather. Your ground plan fits."})
        else:
            notes.append({"lvl": "warn", "text": "Snow — the deep ball dies; lean on the run."})
    if temp >= 90:
        notes.append({"lvl": "info", "text": f"{temp}°F — heat wears down the big men late; watch your fronts."})
    if save.get("weekly_ops", {}).get("game_plan") == "Aggressive" and (windy or cond in ("Rain", "Snow")):
        notes.append({"lvl": "warn", "text": "An Aggressive downfield plan is risky in this weather."})
    return {"dome": False, "label": wx.get("label", cond), "condition": cond, "wind": wind,
            "temp": temp, "edge": weather_plan_edge(save), "notes": notes}


# --------------------------------------------------------------------------- #
# Revenge & reunion games — the living history bites. Facing the team that ended
# your season, a club that blew you out, a division rival, or your own traded-away
# player fires the room up. The statistical nudge is small on purpose; the story
# is the point.
# --------------------------------------------------------------------------- #
def matchup_tags(save):
    """Narrative tags for your upcoming game, from the franchise's own history."""
    iz = save.get("inseason")
    if not iz:
        return None
    week, uid = iz["week"], save["current_team_id"]
    g = next((x for x in save.get("schedule", [])
              if x["week"] == week and uid in (x["home"], x["away"])), None)
    if not g:
        return None
    teams = {t["id"]: t for t in save["teams"]}
    opp_id = g["away"] if g["home"] == uid else g["home"]
    opp, my = teams[opp_id], teams[uid]
    opp_name, opp_short = opp["full"], opp.get("name", opp["full"])
    tags = []
    pr = save.get("playoff_run") or {}                          # last season's playoff path
    for r in pr.get("rounds", []):
        if r.get("opp_id") == opp_id:
            if not r.get("won"):
                tags.append({"icon": "🔥", "kind": "playoff_revenge", "edge": 0.4,
                             "head": "They ended your season",
                             "sub": f"{opp_short} knocked you out in the {r['round']} last year, {r['them']}–{r['us']}. Get it back."})
            else:
                tags.append({"icon": "🏆", "kind": "playoff_rematch", "edge": 0.1,
                             "head": "Playoff rematch",
                             "sub": f"You bounced {opp_short} in the {r['round']} last year — they remember."})
            break
    for entry in (save.get("game_log") or []):                  # last season, regular season
        if entry.get("opp") == opp_name and entry.get("us") is not None:
            if not entry.get("won"):
                marg = entry["them"] - entry["us"]
                if marg >= 14:
                    tags.append({"icon": "😤", "kind": "payback", "edge": 0.3, "head": "Payback game",
                                 "sub": f"{opp_short} hung {entry['them']}–{entry['us']} on you last season. Return the favor."})
                else:
                    tags.append({"icon": "🎯", "kind": "loss", "edge": 0.2, "head": "Unfinished business",
                                 "sub": f"{opp_short} beat you {entry['them']}–{entry['us']} last season."})
            break
    ex = [p for p in opp["roster"] if p.get("ex_team") == uid]  # your traded-away guy is back
    if ex:
        pl = max(ex, key=lambda p: p["overall"])
        tags.append({"icon": "🔄", "kind": "reunion", "edge": 0.15, "head": "Reunion game",
                     "sub": f"Your old {pl['pos']} {pl['name']} lines up for {opp_short} now."})
    if my["division"] == opp["division"] and my["conference"] == opp["conference"]:
        tags.append({"icon": "⚔️", "kind": "division", "edge": 0.1, "head": "Division rival",
                     "sub": f"{my['division']} pride — these swing the race."})
    if not tags:
        return None
    return {"tags": tags[:3], "edge": round(min(0.5, sum(t["edge"] for t in tags)), 2), "opp": opp_short}


def revenge_edge(save):
    return (matchup_tags(save) or {}).get("edge", 0.0)


# --------------------------------------------------------------------------- #
# THE WEEKLY GAME PLAN — the football chess match. We scout the opponent's
# tendencies, you pick an offensive and defensive IDENTITY for the week, and the
# plan pays off (or backfires) based on how it counters what they do. Your
# coordinators recommend; you can follow or override. Repeat the same identity
# too often and they start sitting on it.
# --------------------------------------------------------------------------- #
def _unit_ovr(team, pos, n):
    d = pos_depth(team, pos)[:n]
    return round(sum(p["overall"] for p in d) / len(d), 1) if d else 60.0


def opponent_tendencies(opp):
    """What this opponent does — offensive traits you must defend, defensive traits
    you can attack. Each carries a `tag` used by the counters matrix."""
    staff = opp.get("staff", {})
    off_sys = (staff.get("off_coord") or {}).get("system")
    def_sys = (staff.get("def_coord") or {}).get("system")
    qb = pos_depth(opp, "QB")[:1]
    qb_style = qb[0].get("style") if qb else None
    wr, ol, rb = _unit_ovr(opp, "WR", 3), _unit_ovr(opp, "OL", 5), _unit_ovr(opp, "RB", 2)
    dl, lb = _unit_ovr(opp, "DL", 4), _unit_ovr(opp, "LB", 3)
    sec = round((_unit_ovr(opp, "CB", 3) + _unit_ovr(opp, "S", 2)) / 2, 1)
    t = []
    if qb_style in ("Dual Threat", "RPO Specialist"):
        t.append({"side": "off", "tag": "mobile_qb", "text": "Mobile QB — he extends plays and scrambles."})
    if wr >= 76:
        t.append({"side": "off", "tag": "star_wr", "text": "Dangerous WR corps — their WR1 is a matchup problem."})
    if ol <= 70:
        t.append({"side": "off", "tag": "weak_ol", "text": "Shaky pass protection — pressure gets home."})
    if rb >= 75 and rb >= wr:
        t.append({"side": "off", "tag": "run_heavy", "text": "Run-first offense — they lean on the ground game."})
    if off_sys in ("Air Raid", "Spread"):
        t.append({"side": "off", "tag": "deep_pass", "text": "Vertical passing attack — they take deep shots."})
    elif off_sys == "West Coast":
        t.append({"side": "off", "tag": "quick_game", "text": "Quick rhythm passing — timing throws underneath."})
    if def_sys == "Blitz Heavy" or lb >= 77:
        t.append({"side": "def", "tag": "blitz_heavy", "text": "Heavy blitz looks, especially on third down."})
    if dl >= 77:
        t.append({"side": "def", "tag": "strong_pass_rush", "text": "Fearsome front — they win with four."})
    if dl >= 75 and lb >= 74:
        t.append({"side": "def", "tag": "strong_run_d", "text": "Stout run defense — hard to run on."})
    elif dl <= 70:
        t.append({"side": "def", "tag": "weak_run_d", "text": "Soft run front — the run is there."})
    if sec <= 71:
        t.append({"side": "def", "tag": "weak_secondary", "text": "Vulnerable secondary — the deep ball is open."})
    elif sec >= 77:
        t.append({"side": "def", "tag": "strong_pass_d", "text": "Lockdown secondary — tough to throw deep."})
    if def_sys == "Cover 3 Zone":
        t.append({"side": "def", "tag": "soft_zone", "text": "Zone-heavy — soft spots sit underneath."})
    return t


OFF_IDENTITIES = {
    "establish_run": {"label": "Establish the Run", "strong": ["blitz_heavy", "weak_run_d"], "weak": ["strong_run_d"],
                      "blurb": "Pound it, control the game, punish the blitz."},
    "quick_pass": {"label": "Quick Passing Attack", "strong": ["blitz_heavy", "strong_pass_rush"], "weak": ["soft_zone"],
                   "blurb": "Get it out fast — beat pressure before it arrives."},
    "attack_deep": {"label": "Attack Downfield", "strong": ["weak_secondary", "soft_zone"], "weak": ["strong_pass_d", "strong_pass_rush"],
                    "blurb": "Take your shots and stress the top of the coverage."},
    "control_clock": {"label": "Control the Clock", "strong": ["weak_run_d"], "weak": ["strong_run_d"],
                      "blurb": "Long drives, keep their offense on the bench."},
    "feature_star": {"label": "Feature the Star", "strong": ["soft_zone", "weak_secondary"], "weak": ["strong_pass_d"],
                     "blurb": "Force-feed your best weapon the ball."},
    "protect_qb": {"label": "Protect the Quarterback", "strong": ["blitz_heavy", "strong_pass_rush"], "weak": [],
                   "blurb": "Max protect and chip — keep him clean."},
    "spread": {"label": "Spread Them Out", "strong": ["strong_run_d", "blitz_heavy"], "weak": ["strong_pass_d"],
               "blurb": "Empty the box, create space, throw underneath."},
}
DEF_IDENTITIES = {
    "stop_run": {"label": "Stop the Run", "strong": ["run_heavy"], "weak": ["deep_pass", "star_wr"],
                 "blurb": "Load the box, make them one-dimensional."},
    "pressure_qb": {"label": "Pressure the Quarterback", "strong": ["weak_ol", "deep_pass"], "weak": ["quick_game", "mobile_qb"],
                    "blurb": "Send heat, force mistakes — but it's a gamble."},
    "keep_in_front": {"label": "Keep Everything in Front", "strong": ["deep_pass", "star_wr"], "weak": ["run_heavy", "quick_game"],
                      "blurb": "No big plays; make them earn every yard."},
    "takeaway_wr1": {"label": "Take Away Their WR1", "strong": ["star_wr"], "weak": ["run_heavy"],
                     "blurb": "Bracket their best guy, dare the others."},
    "disguise": {"label": "Disguise Coverage", "strong": ["quick_game", "deep_pass"], "weak": ["run_heavy"],
                 "blurb": "Confuse the read, bait the throw."},
    "force_outside": {"label": "Force Them Outside", "strong": ["run_heavy", "mobile_qb"], "weak": ["quick_game"],
                      "blurb": "Set hard edges, funnel everything to the sideline."},
    "contain_qb": {"label": "Contain the Mobile QB", "strong": ["mobile_qb"], "weak": ["star_wr"],
                   "blurb": "Rush lanes and a spy — make him a passer."},
}


def _identity_edge_for(idef, opp_tags):
    e = 0.0
    for tag in opp_tags:
        if tag in idef.get("strong", []):
            e += 0.35
        elif tag in idef.get("weak", []):
            e -= 0.35
    return e


def identity_edge(save):
    """Net power swing from your weekly identities vs the opponent's tendencies,
    minus a penalty for leaning on the same identity week after week."""
    iz = save.get("inseason")
    if not iz:
        return 0.0
    uid = save["current_team_id"]
    g = next((x for x in save.get("schedule", [])
              if x["week"] == iz["week"] and uid in (x["home"], x["away"])), None)
    if not g:
        return 0.0
    opp = next(t for t in save["teams"] if t["id"] == (g["away"] if g["home"] == uid else g["home"]))
    tends = opponent_tendencies(opp)
    def_tags = [x["tag"] for x in tends if x["side"] == "def"]
    off_tags = [x["tag"] for x in tends if x["side"] == "off"]
    wo = save.get("weekly_ops", {})
    e = 0.0
    oid = OFF_IDENTITIES.get(wo.get("off_identity"))
    did = DEF_IDENTITIES.get(wo.get("def_identity"))
    if oid:
        e += _identity_edge_for(oid, def_tags)
    if did:
        e += _identity_edge_for(did, off_tags)
    streak = save.get("identity_streak", {})
    for side in ("off", "def"):
        s = streak.get(side)
        if s and s.get("id") == wo.get(side + "_identity") and s.get("count", 0) >= 3:
            e -= 0.3                                            # they're sitting on your tell
    return round(max(-1.2, min(1.4, e)), 2)


def coordinator_reco(save, opp=None):
    """What your OC/DC would call: the identity that best counters the opponent."""
    iz = save.get("inseason")
    if not iz:
        return None
    uid = save["current_team_id"]
    if opp is None:
        g = next((x for x in save.get("schedule", [])
                  if x["week"] == iz["week"] and uid in (x["home"], x["away"])), None)
        if not g:
            return None
        opp = next(t for t in save["teams"] if t["id"] == (g["away"] if g["home"] == uid else g["home"]))
    tends = opponent_tendencies(opp)
    def_tags = [x["tag"] for x in tends if x["side"] == "def"]
    off_tags = [x["tag"] for x in tends if x["side"] == "off"]

    def best(cat, tags):
        scored = sorted(((_identity_edge_for(d, tags), k, d) for k, d in cat.items()), key=lambda x: -x[0])
        top = scored[0]
        reason = next((x["text"] for x in tends
                       if x["tag"] in top[2].get("strong", []) and x["side"] == ("def" if cat is OFF_IDENTITIES else "off")), "")
        return {"id": top[1], "label": top[2]["label"], "reason": reason}
    return {"off": best(OFF_IDENTITIES, def_tags), "def": best(DEF_IDENTITIES, off_tags)}


def game_plan_report(save):
    """Everything the Command Center needs: scouting report, identity pickers with
    live edges, the coordinators' picks, the plan's net edge, and a self-scout warning."""
    iz = save.get("inseason")
    if not iz:
        return None
    uid = save["current_team_id"]
    g = next((x for x in save.get("schedule", [])
              if x["week"] == iz["week"] and uid in (x["home"], x["away"])), None)
    if not g:
        return None
    opp = next(t for t in save["teams"] if t["id"] == (g["away"] if g["home"] == uid else g["home"]))
    tends = opponent_tendencies(opp)
    def_tags = [x["tag"] for x in tends if x["side"] == "def"]
    off_tags = [x["tag"] for x in tends if x["side"] == "off"]
    wo = save.get("weekly_ops", {})
    reco = coordinator_reco(save, opp)

    def opts(cat, tags, cur):
        out = []
        for k, d in cat.items():
            e = _identity_edge_for(d, tags)
            out.append({"key": k, "label": d["label"], "blurb": d["blurb"], "edge": round(e, 2),
                        "on": k == cur, "fit": "good" if e >= 0.3 else "bad" if e <= -0.3 else "neutral"})
        return sorted(out, key=lambda x: -x["edge"])
    warn = None
    streak = save.get("identity_streak", {})
    for side, label in (("off", "offensive"), ("def", "defensive")):
        s = streak.get(side)
        if s and s.get("id") == wo.get(side + "_identity") and s.get("count", 0) >= 3:
            nm = (OFF_IDENTITIES if side == "off" else DEF_IDENTITIES).get(s["id"], {}).get("label", "")
            warn = f"You've run {nm} {s['count']} weeks straight — opponents are sitting on it."
    return {"opp_short": opp.get("name", opp["full"]),
            "off_tendencies": [x for x in tends if x["side"] == "off"],
            "def_tendencies": [x for x in tends if x["side"] == "def"],
            "off_opts": opts(OFF_IDENTITIES, def_tags, wo.get("off_identity")),
            "def_opts": opts(DEF_IDENTITIES, off_tags, wo.get("def_identity")),
            "reco": reco, "edge": identity_edge(save), "warn": warn, "install": install_status(save),
            "friction": ("You keep overriding your coordinators — staff trust is slipping."
                         if max(save.get("coach_friction", {}).get("off", 0),
                                save.get("coach_friction", {}).get("def", 0)) >= 3 else None),
            "off_set": wo.get("off_identity"), "def_set": wo.get("def_identity")}


# --------------------------------------------------------------------------- #
# Halftime adjustments — the in-game decision. Big games (a rival, a coin-flip
# on the line) pause at the half: you see the score and what they're doing, then
# pick an adjustment. The right call (matched to their tendency and your
# personnel) swings the second half. Manual Sim Week only.
# --------------------------------------------------------------------------- #
HALFTIME_OPTIONS = {
    "deep_shots": {"label": "Take deep shots", "desc": "Attack the top of their coverage.", "need": "weak_secondary", "concept": "deep"},
    "pound_rock": {"label": "Pound the rock", "desc": "Lean on the run, shorten the game.", "need": "weak_run_d", "concept": "run"},
    "bring_pressure": {"label": "Dial up pressure", "desc": "Send heat, force a mistake.", "need": "weak_ol", "concept": "rush"},
    "spread_out": {"label": "Spread them out", "desc": "Empty sets, get your playmakers space.", "need": "blitz_heavy", "concept": "quick"},
    "ball_control": {"label": "Protect the ball", "desc": "Ball control and field position — don't beat yourself.", "need": None, "concept": "safe"},
}


def _halftime_option_edge(save, opp_tags, opt):
    e = 0.1                                             # any decisive halftime call is worth a little
    if opt["need"] and opt["need"] in opp_tags:
        e += 0.4                                        # it targets a real weakness
    team = current_team(save)
    c = opt["concept"]
    if c == "deep" and _unit_ovr(team, "WR", 2) >= 76:
        e += 0.2
    elif c == "run" and _unit_ovr(team, "RB", 1) >= 76:
        e += 0.2
    elif c == "rush" and _unit_ovr(team, "DL", 4) >= 76:
        e += 0.2
    elif c == "quick" and _unit_ovr(team, "QB", 1) >= 76:
        e += 0.15
    return round(min(0.7, e), 2)


def _is_important_game(save):
    if not save.get("inseason"):
        return False
    if matchup_tags(save):
        return True
    bl = betting_line(save)
    return bool(bl and abs(bl["spread"]) <= 5)


def build_halftime(save):
    """Freeze a plausible first half and the adjustment menu for an important game."""
    iz = save.get("inseason")
    week = iz["week"]
    mp = _matchup_powers(save, week)
    if not mp:
        return None
    ln = _line_from_powers(mp["home_power"], mp["away_power"], mp["user_home"], save["seed"] + week * 31 + 9)
    exp_us = (ln["total"] - ln["spread"]) / 2.0
    exp_them = (ln["total"] + ln["spread"]) / 2.0
    rng = _rng(save["seed"] + week * 7 + 31)
    hf_us = max(0, int(round(exp_us * 0.45 + rng.randint(-3, 4))))
    hf_them = max(0, int(round(exp_them * 0.45 + rng.randint(-3, 4))))
    opp = mp["opp"]
    tends = opponent_tendencies(opp)
    all_tags = [t["tag"] for t in tends]
    read = next((t["text"] for t in tends if t["side"] == "def"),
                next((t["text"] for t in tends), "They're playing you straight up."))
    options = sorted(({"key": k, "label": o["label"], "desc": o["desc"],
                       "edge": _halftime_option_edge(save, all_tags, o)}
                      for k, o in HALFTIME_OPTIONS.items()), key=lambda o: -o["edge"])[:4]
    save["halftime"] = {"opp_short": opp.get("name", opp["full"]), "hf_us": hf_us, "hf_them": hf_them,
                        "situation": ("trailing" if hf_us < hf_them else "leading" if hf_us > hf_them else "tied"),
                        "read": read, "options": options, "week": week}
    return save["halftime"]


def resolve_halftime(save, choice):
    hf = save.get("halftime")
    if not hf:
        return False
    opt = next((o for o in hf["options"] if o["key"] == choice), hf["options"][0])
    save["halftime_choice"] = {"key": opt["key"], "label": opt["label"], "edge": opt["edge"],
                               "hf_us": hf["hf_us"], "hf_them": hf["hf_them"]}
    save.pop("halftime", None)
    write_save(save)
    return True


def halftime_edge(save):
    return (save.get("halftime_choice") or {}).get("edge", 0.0)


def _evaluate_game_plan(save, opp, us, them):
    """Postgame verdict on how your weekly identities fared against their tendencies."""
    wo = save.get("weekly_ops", {})
    tends = opponent_tendencies(opp)
    def_tags = [x["tag"] for x in tends if x["side"] == "def"]
    off_tags = [x["tag"] for x in tends if x["side"] == "off"]
    out = {}
    oid = OFF_IDENTITIES.get(wo.get("off_identity"))
    if oid:
        e = _identity_edge_for(oid, def_tags)
        if e > 0 and us >= 27:
            v, txt = "worked", f"Your {oid['label']} plan hit — you found the matchup and put up {us}."
        elif e > 0:
            v, txt = "mixed", f"The {oid['label']} matchup was there, but {us} points says execution lagged."
        elif e < 0:
            v, txt = "backfired", f"{oid['label']} played into their strength — a grind for {us}."
        else:
            v, txt = "neutral", f"{oid['label']} was a wash against their looks ({us} points)."
        out["off"] = {"label": oid["label"], "verdict": v, "text": txt}
    did = DEF_IDENTITIES.get(wo.get("def_identity"))
    if did:
        e = _identity_edge_for(did, off_tags)
        if e > 0 and them <= 20:
            v, txt = "worked", f"Your {did['label']} plan smothered them — just {them} allowed."
        elif e > 0:
            v, txt = "mixed", f"{did['label']} was the right idea, but {them} still got through."
        elif e < 0:
            v, txt = "backfired", f"{did['label']} left you exposed — they hung {them}."
        else:
            v, txt = "neutral", f"{did['label']} traded blows ({them} allowed)."
        out["def"] = {"label": did["label"], "verdict": v, "text": txt}
    return out or None


def _bump_identity_streak(save):
    """Track how many weeks in a row each identity has been used (for self-scouting)."""
    wo = save.get("weekly_ops", {})
    st = save.setdefault("identity_streak", {})
    for side in ("off", "def"):
        cur = wo.get(side + "_identity")
        s = st.get(side)
        if cur and s and s.get("id") == cur:
            s["count"] = s.get("count", 1) + 1
        elif cur:
            st[side] = {"id": cur, "count": 1}


def _bump_familiarity(save):
    """Reps in the concepts you actually called this week (they get more reliable)."""
    fam = save.setdefault("familiarity", {})
    for k in selected_plays(save):
        fam[k] = min(8, fam.get(k, 0) + 1)


def _check_coach_friction(save):
    """Overriding the coordinators' recommended identity week after week wears on
    staff trust — a frustrated coordinator is likelier to walk in the carousel."""
    reco = coordinator_reco(save)
    if not reco:
        return
    wo = save.get("weekly_ops", {})
    fr = save.setdefault("coach_friction", {"off": 0, "def": 0})
    for side in ("off", "def"):
        chosen = wo.get(side + "_identity")
        if chosen and chosen != reco[side]["id"]:
            fr[side] += 1
            if fr[side] >= 3 and fr[side] % 3 == 0:
                save["staff_trust"] = max(10, save.get("staff_trust", 60) - 3)
        else:
            fr[side] = 0


# Concept/scheme installation — a new coordinator's system takes weeks to learn.
_SCHEME_INSTALL_WEEKS = 4


def _team_scheme_sides(save):
    s = save.get("staff", {})
    return {"off": (s.get("off_coord") or {}).get("system"),
            "def": (s.get("def_coord") or {}).get("system")}


def _advance_install(save):
    """Track scheme installation: a changed coordinator system runs an install
    countdown (shorter for offense with a savvy veteran QB) during which the plan
    is a step slow. Self-initializes to the current scheme with no penalty."""
    cur = _team_scheme_sides(save)
    inst = save.setdefault("installed_scheme", {})
    weeks = save.setdefault("install_weeks", {})
    for side in ("off", "def"):
        if side not in inst:                           # first run: learn current scheme, no penalty
            inst[side], weeks[side] = cur[side], 0
            continue
        if cur[side] != inst[side]:
            if weeks.get(side, 0) <= 0:                 # a new scheme just arrived — start install
                base = _SCHEME_INSTALL_WEEKS
                if side == "off":
                    qb = pos_depth(current_team(save), "QB")[:1]
                    if qb and qb[0].get("age", 25) >= 28 and qb[0]["overall"] >= 78:
                        base = 2                        # a veteran QB accelerates the install
                weeks[side] = base
            weeks[side] -= 1
            if weeks[side] <= 0:                        # install complete
                inst[side], weeks[side] = cur[side], 0


def install_edge(save):
    weeks = save.get("install_weeks", {})
    return round((-0.4 if weeks.get("off", 0) > 0 else 0.0) + (-0.3 if weeks.get("def", 0) > 0 else 0.0), 2)


def install_status(save):
    weeks = save.get("install_weeks", {})
    out = []
    if weeks.get("off", 0) > 0:
        out.append({"side": "offense", "weeks": weeks["off"]})
    if weeks.get("def", 0) > 0:
        out.append({"side": "defense", "weeks": weeks["def"]})
    return out


def weekly_edge(save):
    """The standing weekly plan's net power edge this Sunday."""
    wo = save.get("weekly_ops", {})
    e = PRACTICE_INTENSITY.get(wo.get("intensity", "Balanced"), {}).get("edge", 0.0)
    e += GAME_PLANS.get(wo.get("game_plan", "Balanced"), {}).get("edge", 0.0)
    e += key_moment_edge(save)
    e += featured_plays_edge(save)                              # featured plays that fit your personnel
    e += weather_plan_edge(save)                               # forecast vs your concepts
    e += revenge_edge(save)                                    # a revenge/rivalry game fires the room up
    e += identity_edge(save)                                   # weekly game plan vs opponent tendencies
    e += install_edge(save)                                    # a freshly-installed scheme is a step slow
    e += snap_edge(save)                                       # workhorse RB / rookie-vs-vet snaps
    e += halftime_edge(save)                                   # your halftime adjustment's second-half swing
    if wo.get("scout") == "Opponent":
        e += 0.5
    return round(e, 2)


# --------------------------------------------------------------------------- #
# Snap plan — broad usage decisions with real tradeoffs. Riding your bell-cow
# back squeezes out production but wears him down; a committee keeps the room
# fresh and happy. Giving rookies snaps develops them (and they love it) at a
# small cost on Sundays; playing the vets buys a little edge now.
# --------------------------------------------------------------------------- #
SNAP_RB = {
    "Workhorse": {"edge": 0.2, "inj": 1.12, "blurb": "Feed your bell-cow — more production, more wear."},
    "Committee": {"edge": 0.0, "inj": 0.95, "blurb": "Spread the carries — fresh legs, a happy room, less pop."},
}
SNAP_ROOKIE = {
    "Develop": {"edge": -0.15, "blurb": "Play the kids — they grow and love the snaps, at a small cost now."},
    "Win Now": {"edge": 0.15, "blurb": "Ride the veterans — a little sharper today, less growth for the young."},
}


def snap_plan(save):
    wo = save.get("weekly_ops", {})
    return {"rb_usage": wo.get("rb_usage", "Committee"), "rookie_snaps": wo.get("rookie_snaps", "Win Now"),
            "rb_opts": SNAP_RB, "rookie_opts": SNAP_ROOKIE}


def snap_edge(save):
    wo = save.get("weekly_ops", {})
    e = SNAP_ROOKIE.get(wo.get("rookie_snaps", "Win Now"), {}).get("edge", 0.0)
    if wo.get("rb_usage") == "Workhorse":
        rb = pos_depth(current_team(save), "RB")[:1]
        if rb and rb[0]["overall"] >= 75:                  # only worth it with a real bell-cow
            e += SNAP_RB["Workhorse"]["edge"]
    return round(e, 2)


def apply_snap_morale(save):
    """Weekly morale from usage: a fed bell-cow (and buried backup), and young guys
    who are getting developmental snaps."""
    wo = save.get("weekly_ops", {})
    team = current_team(save)
    if wo.get("rb_usage") == "Workhorse":
        rbs = pos_depth(team, "RB")
        if rbs:
            _nudge(save, rbs[0]["id"], morale=1, conf=1)
        if len(rbs) > 1:
            _nudge(save, rbs[1]["id"], morale=-1)
    elif wo.get("rb_usage") == "Committee":
        rbs = pos_depth(team, "RB")
        if len(rbs) > 1:
            _nudge(save, rbs[1]["id"], morale=1)
    if wo.get("rookie_snaps") == "Develop":
        for p in team["roster"]:
            if p.get("age", 30) <= 23:
                _nudge(save, p["id"], morale=1)


def weekly_injury_factor(save):
    wo = save.get("weekly_ops", {})
    return (PRACTICE_INTENSITY.get(wo.get("intensity", "Balanced"), {}).get("inj", 1.0)
            * MEDICAL_POLICY.get(wo.get("medical", "Balanced"), {}).get("inj", 1.0)
            * SNAP_RB.get(wo.get("rb_usage", "Committee"), {}).get("inj", 1.0))


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
         + sb["special_teams"] + atmosphere(save)["home_edge"] + attr_scheme_edge(save))
    p += weekly_edge(save)                                      # Command Center: practice + game plan
    p += package_edge(save)                                     # Situational packages matching the weekly plan
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

    room = round(cap_total(save) - cap_used(current_team(save)), 1)
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
    save.pop("ownership_change", None)   # last offseason's new-owner banner clears
    ensure_draft_preview(save)           # next spring's class becomes scoutable now
    me = current_team(save)
    for p in me["roster"]:
        p.pop("rep_starter", None)
    for p in _starters(me):
        p["rep_starter"] = True   # live reps all season -> young starters grow faster
    save.setdefault("season_flags", {})["young_starters"] = sum(
        1 for p in _starters(me) if int(p.get("age", 30) or 30) <= 25)
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


def _score_line(rng, win_power, lose_power):
    """A plausible final: the favorite pulls away, the underdog keeps it close."""
    margin = int(max(1, min(38, round(3 + (win_power - lose_power) * 0.35 + rng.triangular(0, 21, 7)))))
    base = rng.choice([10, 13, 14, 16, 17, 17, 20, 20, 21, 23, 24, 27])
    return base + margin, base


def _game_box(perf, n=5):
    """The top contributors from one team's game (skill + notable defense), best first."""
    return [{"name": x["name"], "pos": x["pos"], "pid": x.get("pid"), "line": x["line"], "g": x.get("g")}
            for x in sorted(perf, key=lambda x: -x.get("score", 0))[:n]]


# --------------------------------------------------------------------------- #
# The house line — Bankroll Kings IS a sportsbook, so every franchise game gets a
# real number. We Monte-Carlo the ACTUAL game model (the same _sim_game +
# _score_line the week runs on) so the line is honest: a spread, a total, and a
# moneyline that move with your power — including whatever your weekly game plan
# adds. The realized game can still beat or miss the number, exactly like Sunday.
# --------------------------------------------------------------------------- #
def _american_ml(p):
    p = max(0.03, min(0.97, p))
    if p >= 0.5:
        return -int(round((100 * p / (1 - p)) / 5.0) * 5)     # favorite lays juice
    return int(round((100 * (1 - p) / p) / 5.0) * 5)          # underdog plus-money


def _round_half(x):
    return round(x * 2) / 2.0


def _line_from_powers(home_power, away_power, user_home, seed, sims=600):
    """Expected spread (user perspective, negative = favored), total, and win
    probability from a Monte-Carlo of the real game model."""
    rng = _rng(seed)
    m_sum = t_sum = wins = 0.0
    for _ in range(sims):
        home_win = _sim_game(rng, home_power, away_power)
        wp, lp = (home_power, away_power) if home_win else (away_power, home_power)
        ws, ls = _score_line(rng, wp, lp)
        hp, ap = (ws, ls) if home_win else (ls, ws)
        up, op = (hp, ap) if user_home else (ap, hp)
        m_sum += up - op
        t_sum += up + op
        wins += 1 if up > op else 0
    win_pct = wins / sims
    spread = -_round_half(m_sum / sims)
    if spread == 0:
        spread = -0.5 if win_pct >= 0.5 else 0.5
    return {"spread": spread, "total": _round_half(t_sum / sims),
            "win_pct": round(win_pct, 3), "moneyline": _american_ml(win_pct)}


def _matchup_powers(save, week):
    """(home_power, away_power, meta) for the user's game this week, computed the
    same way sim_week does — so the line reflects your plan, injuries and weather."""
    uid = save["current_team_id"]
    g = next((x for x in save.get("schedule", [])
              if x["week"] == week and uid in (x["home"], x["away"])), None)
    if not g:
        return None
    teams = {t["id"]: t for t in save["teams"]}
    opp_id = g["away"] if g["home"] == uid else g["home"]
    weather = game_weather(save, g["home"], week)
    user_home = g["home"] == uid
    u_pow, _out = _user_inseason_power(save, week, power_rating(teams[uid]))
    o_pow = power_rating(teams[opp_id]) + ai_coach_edge(teams[opp_id])
    home_power = (u_pow if user_home else o_pow) + weather_power_adjust(teams[g["home"]], weather)
    away_power = (o_pow if user_home else u_pow) + weather_power_adjust(teams[g["away"]], weather)
    return {"home_power": home_power, "away_power": away_power, "user_home": user_home,
            "opp": teams[opp_id], "weather": weather}


def betting_line(save):
    """The sportsbook line on your upcoming game, for the Command Center."""
    iz = save.get("inseason")
    if not iz:
        return None
    week = iz["week"]
    mp = _matchup_powers(save, week)
    if not mp:
        return None                                          # bye week
    ln = _line_from_powers(mp["home_power"], mp["away_power"], mp["user_home"],
                           save["seed"] + week * 7919 + 4242)
    return {"week": week, "opp": mp["opp"]["full"], "opp_short": mp["opp"].get("name", mp["opp"]["full"]),
            "home": mp["user_home"], "spread": ln["spread"], "total": ln["total"],
            "moneyline": ln["moneyline"], "win_pct": ln["win_pct"], "favored": ln["spread"] < 0,
            "ats": save.get("ats", {})}


def _grade_line(save, week, home_power, away_power, user_home, us, them, won):
    """Grade the closing line against the result, update the season ATS ledger, and
    return the line result to hang on the recap."""
    ln = _line_from_powers(home_power, away_power, user_home, save["seed"] + week * 7919 + 4242)
    margin = us - them
    cover_margin = round(margin + ln["spread"], 1)             # >0 = covered
    cover = "push" if cover_margin == 0 else ("cover" if cover_margin > 0 else "no")
    total_actual = us + them
    ou = "push" if total_actual == ln["total"] else ("over" if total_actual > ln["total"] else "under")
    was_dog = ln["spread"] > 0
    upset = was_dog and won
    choke = ln["spread"] <= -6.5 and not won
    ats = save.setdefault("ats", {"cover": 0, "no": 0, "push": 0,
                                  "over": 0, "under": 0, "ou_push": 0, "dog_wins": 0, "fav_losses": 0})
    ats[cover] = ats.get(cover, 0) + 1
    ats["ou_push" if ou == "push" else ou] = ats.get("ou_push" if ou == "push" else ou, 0) + 1
    if upset:
        ats["dog_wins"] = ats.get("dog_wins", 0) + 1
        save["gm"]["fan_support"] = min(100, save["gm"].get("fan_support", 50) + 2)
    if choke:
        ats["fav_losses"] = ats.get("fav_losses", 0) + 1
        save["gm"]["fan_support"] = max(0, save["gm"].get("fan_support", 50) - 2)
    return {"spread": ln["spread"], "total": ln["total"], "moneyline": ln["moneyline"],
            "cover": cover, "cover_margin": cover_margin, "ou": ou, "total_actual": total_actual,
            "was_dog": was_dog, "upset": upset, "choke": choke}


# --------------------------------------------------------------------------- #
# Player props — O/U lines on YOUR guys, projected by Monte-Carlo-ing the same
# stat engine the game runs on (so the number is honest) and graded off the box
# score the game produced. Rounds out the book: game line, quant desk, props.
# --------------------------------------------------------------------------- #
PROP_DEFS = [
    {"key": "qb_pass_yd", "pos": "QB", "stat": "pass_yd", "unit": "pass yds", "step": 5},
    {"key": "qb_pass_td", "pos": "QB", "stat": "pass_td", "unit": "pass TD", "step": 0},
    {"key": "rb_rush_yd", "pos": "RB", "stat": "rush_yd", "unit": "rush yds", "step": 5},
    {"key": "wr_rec_yd", "pos": "WR", "stat": "rec_yd", "unit": "rec yds", "step": 5},
]


def _prop_line(mean, step):
    if step == 0:                                  # TD-type: half-point just under the mean
        return max(0.5, round(mean) - 0.5)
    return max(step - 0.5, round(mean / step) * step - 0.5)


def player_props(save, sims=120):
    """O/U lines for your key starters this week, from a Monte-Carlo of the stat
    engine at the game's expected pace."""
    iz = save.get("inseason")
    if not iz:
        return None
    week = iz["week"]
    mp = _matchup_powers(save, week)
    if not mp:
        return None                                # bye week
    team = current_team(save)
    targets = []                                   # (prop def, the starter it tracks)
    for pdef in PROP_DEFS:
        pl = pos_depth(team, pdef["pos"])
        if pl:
            targets.append((pdef, pl[0]))
    if not targets:
        return None
    samples = {pdef["key"]: [] for pdef, _ in targets}
    hp, ap, uh = mp["home_power"], mp["away_power"], mp["user_home"]
    rng = _rng(save["seed"] + week * 6151 + 88)
    for _ in range(sims):
        home_win = _sim_game(rng, hp, ap)
        wp, lp = (hp, ap) if home_win else (ap, hp)
        ws, ls = _score_line(rng, wp, lp)
        hpts, apts = (ws, ls) if home_win else (ls, ws)
        upts, opts = (hpts, apts) if uh else (apts, hpts)
        perf, _ = _game_perf(team, upts, upts > opts, rng, record=False)
        by_pid = {x["pid"]: (x.get("g") or {}) for x in perf}
        for pdef, pl in targets:
            samples[pdef["key"]].append(by_pid.get(pl["id"], {}).get(pdef["stat"], 0))
    props = []
    for pdef, pl in targets:
        vals = samples[pdef["key"]]
        mean = sum(vals) / len(vals) if vals else 0
        props.append({"key": pdef["key"], "pid": pl["id"], "name": pl["name"], "pos": pdef["pos"],
                      "stat": pdef["stat"], "unit": pdef["unit"], "line": _prop_line(mean, pdef["step"]),
                      "proj": round(mean, 1)})
    return {"props": props, "opp_short": mp["opp"].get("name", mp["opp"]["full"]), "week": week}


def grade_props(save, my_box):
    """Grade this week's props against the box score the game produced."""
    pp = player_props(save)
    if not pp:
        return None
    by_pid = {b["pid"]: (b.get("g") or {}) for b in (my_box or [])}
    out = []
    for pr in pp["props"]:
        actual = by_pid.get(pr["pid"], {}).get(pr["stat"], 0)
        out.append(dict(pr, actual=actual, result="over" if actual > pr["line"] else "under"))
    return out


def _signature_tags(box_entry, won, close):
    """The headline feats in one player's game, if it rises to a signature line."""
    g = box_entry.get("g") or {}
    pos = box_entry.get("pos")
    tags = []
    if pos == "QB":
        if g.get("pass_yd", 0) >= 350:
            tags.append(f"{g['pass_yd']} passing yards")
        if g.get("pass_td", 0) >= 4:
            tags.append(f"{g['pass_td']} passing TDs")
        if g.get("rush_yd", 0) >= 60 and g.get("pass_yd", 0) >= 220:
            tags.append(f"{g['pass_yd'] + g['rush_yd']} total yards")
    elif pos == "RB":
        if g.get("rush_yd", 0) >= 150:
            tags.append(f"{g['rush_yd']} rushing yards")
        if g.get("rush_td", 0) >= 3:
            tags.append(f"{g['rush_td']} rushing TDs")
    elif pos in ("WR", "TE"):
        if g.get("rec_yd", 0) >= 150:
            tags.append(f"{g['rec_yd']} receiving yards")
        if g.get("rec_td", 0) >= 3:
            tags.append(f"{g['rec_td']} receiving TDs")
    tds = g.get("pass_td", 0) + g.get("rush_td", 0) + g.get("rec_td", 0)
    if tds >= 4 and not tags:
        tags.append(f"{tds} total touchdowns")
    return tags


def _record_signatures(save, perf, week, won, margin):
    """Detect signature games from the box score and mint them into the career
    timeline (and a per-player counter that feeds the legacy/HOF case)."""
    close = won and margin <= 8
    sigs = []
    for b in sorted(perf, key=lambda x: -x.get("score", 0)):
        if b.get("pos") not in ("QB", "RB", "WR", "TE"):
            continue
        tags = _signature_tags(b, won, close)
        if tags:
            sigs.append({"pid": b.get("pid"), "name": b["name"], "pos": b["pos"],
                         "line": b["line"], "note": ", ".join(tags)})
    sigs = sigs[:2]
    ids = {s["pid"] for s in sigs}
    for t in save["teams"]:
        for p in t["roster"]:
            if p["id"] in ids:
                p["signature_games"] = p.get("signature_games", 0) + 1
    for s in sigs:
        _tl(save, save.get("season", 1), "signature", "⭐",
            f"{s['pos']} {s['name']}: a signature game",
            f"{s['note']} in Week {week}." + (" In a game they had to have." if close else ""),
            pid=s["pid"])
    return sigs


def _compose_game_story(rng, won, us, them, my_name, opp_name, star, key_call, weather, round_name=None):
    """A short SportsDesk writeup of one game: a headline, a dek, and a body that
    threads the result, the star line, the sideline call, and the weather. `weather`
    is the game_weather() dict (or None). `round_name` set = a playoff game."""
    margin = abs(us - them)
    close = margin <= 3
    blowout = margin >= 21
    cond = (weather or {}).get("condition", "")
    rough = cond in ("Snow", "Rain", "Wind")
    if round_name:                                     # playoff framing
        title = round_name == "BRK Championship"
        if won:
            head = (f"{my_name} are {'BRK CHAMPIONS' if title else 'moving on'} — {us}–{them} over {opp_name}"
                    if title else f"{my_name} advance past {opp_name}, {us}–{them}")
            dek = ("They lifted the trophy." if title else f"On to the next round of the playoffs.")
        else:
            head = f"{my_name} fall to {opp_name}, {them}–{us} — season over"
            dek = ("A title-game defeat ends it." if title
                   else f"The {round_name} is where the run ends.")
        body = f"In the {round_name}, {my_name} {'took down' if won else 'were eliminated by'} {opp_name}, {us}–{them}."
        if star:
            body += f" {star['pos']} {star['name']} led the way — {star['line']}."
        if key_call and key_call != "Balanced":
            body += f" The staff rode a “{key_call}” plan when it mattered."
        return {"headline": head, "dek": dek, "story": body}
    if won:
        verb = rng.choice(["hold off", "outlast", "handle", "grind past", "roll past", "take down"])
        head = f"{my_name} {verb} {opp_name}, {us}–{them}"
        lead = ("survived a one-score win" if close else "cruised in a lopsided win" if blowout
                else "picked up a win")
        dek = ("A win the film room will enjoy — they finished the close one." if close
               else "A statement afternoon." if blowout else "A win is a win; the ledger ticks up.")
    else:
        verb = rng.choice(["fall to", "drop one to", "get edged by", "come up short against", "lose to"])
        head = f"{my_name} {verb} {opp_name}, {them}–{us}"
        lead = ("dropped a heartbreaker" if close else "were run out in a lopsided loss" if blowout
                else "lost a tough one")
        dek = "A result the film room won't enjoy — the margins were the story."
    body = f"{my_name} {lead}, {us}–{them}."
    if star:
        body += f" {star['pos']} {star['name']} carried the load — {star['line']}."
    if key_call and key_call != "Balanced":
        body += f" The staff leaned on a “{key_call}” approach in the swing moments."
    if rough:
        body += f" {cond} framed the afternoon."
    return {"headline": head, "dek": dek, "story": body}


def sim_week(save):
    iz = save.get("inseason")
    if not iz:
        return save
    week = iz["week"]
    rng = _rng(save["seed"] + save["season"] * 1000 + week)
    teams = {t["id"]: t for t in save["teams"]}
    powers = {tid: power_rating(t)
              + (ai_coach_edge(t) if tid != save["current_team_id"] else 0.0)
              for tid, t in teams.items()}
    uid = save["current_team_id"]
    iz["injuries"] = _roll_week_injuries(save, week, rng)
    iz["incidents"] = _roll_offfield(save, week, rng)   # off-field drama (suspensions dock power below)
    iz["ps_poached"] = _roll_ps_poaching(save, week, rng)   # rivals raid your practice squad
    apply_featured_play_morale(save)                    # featuring your guys this week lifts their morale
    apply_snap_morale(save)                             # usage: bell-cow / committee / rookie snaps
    _bump_identity_streak(save)                         # self-scouting: track identity repetition
    _check_coach_friction(save)                         # overriding coordinators erodes staff trust
    _advance_install(save)                              # scheme installation countdown
    powers[uid], out = _user_inseason_power(save, week, powers[uid])
    out_ids = {p["id"] for p in out}
    for g in save["schedule"]:
        if g["week"] != week:
            continue
        weather = game_weather(save, g["home"], week)
        home_power = powers[g["home"]] + weather_power_adjust(teams[g["home"]], weather)
        away_power = powers[g["away"]] + weather_power_adjust(teams[g["away"]], weather)
        home_win = _sim_game(rng, home_power, away_power)
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win]["record"]["w"] += 1
        teams[lose]["record"]["l"] += 1
        # One score line drives BOTH the scoreboard and the box score, so they agree.
        ws, ls = _score_line(rng, powers.get(win, 60.0), powers.get(lose, 60.0))
        home_pts, away_pts = (ws, ls) if win == g["home"] else (ls, ws)
        ph, ph_sum = _game_perf(teams[g["home"]], home_pts, home_win, rng, out_ids if g["home"] == uid else ())
        pa, pa_sum = _game_perf(teams[g["away"]], away_pts, not home_win, rng, out_ids if g["away"] == uid else ())
        if uid in (g["home"], g["away"]):
            opp = teams[g["away"] if g["home"] == uid else g["home"]]
            mine = ph if g["home"] == uid else pa
            theirs = pa if g["home"] == uid else ph
            my_sum = ph_sum if g["home"] == uid else pa_sum
            opp_sum = pa_sum if g["home"] == uid else ph_sum
            st = max(mine, key=lambda x: x["score"]) if mine else None
            _us, _them = (home_pts, away_pts) if g["home"] == uid else (away_pts, home_pts)
            km = key_moment_summary(save)
            star = {k: st[k] for k in ("name", "pos", "line", "pid")} if st else None
            line_result = _grade_line(save, week, home_power, away_power, g["home"] == uid,
                                      _us, _them, win == uid)
            iz["log"].append({"week": week, "opp": opp["full"], "home": g["home"] == uid, "won": win == uid,
                              "us": _us, "them": _them, "weather": weather,
                              "key_moment": km,
                              "star": star,
                              "_score": st["score"] if st else 0})
            # Rich single-game recap for the post-game page (both box scores + a story).
            my_team = teams[uid]
            save["last_game"] = {
                "season": save.get("season", 1), "week": week,
                "won": win == uid, "us": _us, "them": _them,
                "home": g["home"] == uid, "opp": opp["full"], "opp_short": opp.get("name", opp["full"]),
                "my_team": my_team["full"], "my_short": my_team.get("name", my_team["full"]),
                "weather": weather, "key_moment": km,
                "my_box": _game_box(mine), "opp_box": _game_box(theirs),
                "my_summary": my_sum, "opp_summary": opp_sum, "line": line_result,
                "props": grade_props(save, mine),
                "injuries": list(iz.get("injuries", [])), "incidents": list(iz.get("incidents", [])),
                "ps_poached": list(iz.get("ps_poached", [])),
                "news": _compose_game_story(rng, win == uid, _us, _them,
                                            my_team.get("name", my_team["full"]),
                                            opp.get("name", opp["full"]), star,
                                            km.get("call", "Balanced"), weather),
            }
            _log_player_games(save, mine, week)     # feed the storyline/streak detector
            _bump_familiarity(save)                 # reps in the concepts you called
            save["last_game"]["signatures"] = _record_signatures(
                save, mine, week, win == uid, abs(_us - _them))
            save["last_game"]["plan_eval"] = _evaluate_game_plan(save, opp, _us, _them)
            hc = save.pop("halftime_choice", None)          # a halftime adjustment was made this game
            if hc:
                save["last_game"]["halftime"] = {
                    **hc, "final_us": _us, "final_them": _them,
                    "comeback": hc["hf_us"] < hc["hf_them"] and win == uid,
                    "collapse": hc["hf_us"] > hc["hf_them"] and win != uid}
    standings = sorted(save["teams"], key=lambda t: (t["record"]["w"], powers.get(t["id"], 0)), reverse=True)
    save["standings_cache"] = [{"id": t["id"], "full": t["full"], "conf": t["conference"],
                               "div": t["division"], "w": t["record"]["w"], "l": t["record"]["l"]} for t in standings]
    # Season context for the post-game page: record + where this result leaves you.
    if save.get("last_game"):
        mt = current_team(save)
        rec = mt.get("record", {"w": 0, "l": 0})
        div_rows = [s for s in save["standings_cache"]
                    if s["div"] == mt["division"] and s["conf"] == mt["conference"]]
        place = next((i + 1 for i, s in enumerate(div_rows) if s["id"] == uid), None)
        save["last_game"]["context"] = {
            "record": f"{rec.get('w', 0)}-{rec.get('l', 0)}",
            "division": mt["division"], "conference": mt["conference"],
            "div_place": place, "div_size": len(div_rows)}
    _update_power_rank(save)        # GridIron Network week-over-week movement
    offer_chance = 0.75 if any(p.get("on_block") for p in current_team(save)["roster"]) else 0.4
    deadline = int(save.get("league_rules", {}).get("trade_deadline_week", TRADE_DEADLINE_SOLO) or TRADE_DEADLINE_SOLO)
    if week <= deadline and not iz.get("offer") and rng.random() < offer_chance:
        iz["offer"] = _maybe_ai_offer(save, rng)
    owner_weekly(save, week, rng)      # the owner reacts to the week just played
    generate_weekly_agenda(save, week + 1, rng)   # next week's staff/player decisions land
    iz["week"] = week + 1
    if iz["week"] > REG_GAMES:
        _begin_postseason(save)     # into the playoffs — played round by round, not auto-resolved
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


# --------------------------------------------------------------------------- #
# Relationship web. This is deliberately passive for now: existing systems keep
# their proven math, while decisions leave a memory trail around the league.
# --------------------------------------------------------------------------- #
RELATIONSHIP_GROUPS = {
    "agents": {"label": "Agents", "high": "trusted negotiator", "low": "hard to deal with"},
    "rival_gms": {"label": "Rival GMs", "high": "respected trade partner", "low": "calls go cold"},
    "media": {"label": "Media", "high": "national darling", "low": "easy target"},
    "league_office": {"label": "League Office", "high": "serious operator", "low": "low influence"},
    "locker_room": {"label": "Locker Room", "high": "players believe the plan", "low": "thin trust"},
}


def _relationships(save):
    rel = save.setdefault("relationships", {})
    for key in RELATIONSHIP_GROUPS:
        rel.setdefault(key, 50)
        try:
            rel[key] = max(0, min(100, int(rel[key])))
        except (TypeError, ValueError):
            rel[key] = 50
    save.setdefault("relationship_log", [])
    return rel


def _rel_tier(score):
    return ("Excellent" if score >= 75 else "Good" if score >= 60 else
            "Neutral" if score >= 42 else "Strained" if score >= 25 else "Damaged")


def _rel_nudge(save, key, delta, reason):
    if key not in RELATIONSHIP_GROUPS or not delta:
        return
    rel = _relationships(save)
    before = rel[key]
    after = max(0, min(100, before + int(delta)))
    if after == before:
        return
    rel[key] = after
    save.setdefault("relationship_log", []).insert(0, {
        "season": save.get("season", 1),
        "group": RELATIONSHIP_GROUPS[key]["label"],
        "delta": after - before,
        "score": after,
        "reason": reason,
    })
    save["relationship_log"] = save["relationship_log"][:18]


def relationship_report(save):
    rel = _relationships(save)
    rows = []
    for key, meta in RELATIONSHIP_GROUPS.items():
        score = rel[key]
        rows.append({"key": key, "label": meta["label"], "score": score,
                     "tier": _rel_tier(score),
                     "note": meta["high"] if score >= 60 else meta["low"] if score < 42 else "steady"})
    return {"rows": rows, "log": save.get("relationship_log", [])[:8]}


CULTURE_ARCHETYPES = {
    "Stability": {"note": "patient, process-driven, slow to panic",
                  "traits": {"stability": 74, "discipline": 58, "ambition": 52, "tradition": 64, "player_trust": 58, "analytics": 48}},
    "Win Now": {"note": "aggressive, impatient, built around pressure",
                "traits": {"stability": 42, "discipline": 58, "ambition": 82, "tradition": 45, "player_trust": 46, "analytics": 54}},
    "Player Friendly": {"note": "loyal to the room, attractive to veterans",
                        "traits": {"stability": 60, "discipline": 45, "ambition": 56, "tradition": 48, "player_trust": 78, "analytics": 45}},
    "Old School": {"note": "physical, traditional, coach-led",
                   "traits": {"stability": 62, "discipline": 74, "ambition": 56, "tradition": 78, "player_trust": 52, "analytics": 34}},
    "Analytics Driven": {"note": "value-focused, experimental, edge-seeking",
                         "traits": {"stability": 52, "discipline": 56, "ambition": 64, "tradition": 30, "player_trust": 48, "analytics": 82}},
    "Showtime": {"note": "brand-first, star-driven, media-aware",
                 "traits": {"stability": 48, "discipline": 44, "ambition": 76, "tradition": 42, "player_trust": 54, "analytics": 58}},
}


def _new_culture(save, team):
    owner = (team.get("owner") or {}).get("type", "Hands-Off")
    if owner == "Legacy":
        name = "Old School"
    elif owner == "Impatient":
        name = "Win Now"
    elif owner == "Billionaire":
        name = "Showtime"
    elif owner == "Hands-Off":
        name = "Stability"
    elif owner == "Cheap":
        name = "Analytics Driven"
    else:
        name = "Player Friendly"
    base = CULTURE_ARCHETYPES[name]
    rng = _rng(_city_seed(save, team["id"]) + 909)
    traits = {k: max(10, min(95, v + rng.randint(-7, 7))) for k, v in base["traits"].items()}
    return {"identity": name, "note": base["note"], "traits": traits, "log": []}


def ensure_team_cultures(save):
    cultures = save.setdefault("team_cultures", {})
    changed = False
    for team in save.get("teams", []):
        if team["id"] not in cultures or not isinstance(cultures.get(team["id"]), dict):
            cultures[team["id"]] = _new_culture(save, team)
            changed = True
    return changed


def team_culture(save, team_id=None):
    ensure_team_cultures(save)
    tid = team_id or save.get("current_team_id")
    return save.get("team_cultures", {}).get(tid, {})


def _culture_nudge(save, trait, delta, reason, team_id=None):
    c = team_culture(save, team_id)
    traits = c.setdefault("traits", {})
    if trait not in traits:
        return
    before = int(traits.get(trait, 50) or 50)
    after = max(0, min(100, before + int(delta)))
    if after == before:
        return
    traits[trait] = after
    c.setdefault("log", []).insert(0, {"season": save.get("season", 1), "trait": trait,
                                       "delta": after - before, "reason": reason})
    c["log"] = c["log"][:10]


def culture_report(save):
    c = team_culture(save)
    traits = c.get("traits", {})
    rows = [{"key": k, "label": k.replace("_", " ").title(), "score": int(v)}
            for k, v in traits.items()]
    rows.sort(key=lambda r: -r["score"])
    return {"identity": c.get("identity", "Unknown"), "note": c.get("note", ""),
            "rows": rows, "log": c.get("log", [])[:5]}


# --------------------------------------------------------------------------- #
# World systems: owner succession, media personalities, fan segments, public
# funding, relocation pressure, expansion studies, and a light people pipeline.
# These are intentionally additive and informational; they do not change team
# count or core sim balance yet.
# --------------------------------------------------------------------------- #
MEDIA_ARCHETYPES = [
    ("Mara Voss", "National Insider", "transaction hawk"),
    ("Trey Halden", "Studio Host", "legacy debate machine"),
    ("Nico Cross", "Cap Analyst", "contract-value obsessive"),
    ("Sasha Bell", "Beat Writer", "locker-room pulse reader"),
    ("Damon Vale", "Podcast Host", "fan mood amplifier"),
]
FAN_SEGMENTS = {
    "diehards": {"label": "Diehards", "base": 64},
    "casuals": {"label": "Casuals", "base": 50},
    "tradition": {"label": "Tradition Fans", "base": 55},
    "stars": {"label": "Star Chasers", "base": 48},
    "families": {"label": "Families", "base": 52},
}
EXPANSION_CITIES = ["Portland", "San Antonio", "Salt Lake City", "Orlando", "Oklahoma City", "Memphis", "St. Louis", "San Diego"]
EXPANSION_MASCOTS = {
    "Portland": "Evergreens",
    "San Antonio": "Vaqueros",
    "Salt Lake City": "Summit",
    "Orlando": "Comets",
    "Oklahoma City": "Outlaws",
    "Memphis": "Kings",
    "St. Louis": "Archers",
    "San Diego": "Breakers",
}
EXPANSION_MARKETS = {
    "Portland": "Mid",
    "San Antonio": "Large",
    "Salt Lake City": "Mid",
    "Orlando": "Mid",
    "Oklahoma City": "Mid",
    "Memphis": "Mid",
    "St. Louis": "Mid",
    "San Diego": "Large",
}


def ensure_world_systems(save):
    changed = False
    rng = _rng(int(save.get("seed", 1) or 1) + 8128)
    for t in save.get("teams", []):
        owner = t.setdefault("owner", {"type": "Hands-Off"})
        if "age" not in owner:
            owner["age"] = rng.randint(42, 78); changed = True
        if "net_worth" not in owner:
            mult = {"Small": (1.8, 7.0), "Mid": (3.0, 12.0), "Large": (7.0, 32.0)}.get(t.get("market"), (3.0, 12.0))
            owner["net_worth"] = round(rng.uniform(*mult), 1); changed = True
        if "heir" not in owner:
            owner["heir"] = _gen_name(rng); changed = True
        if "industry" not in owner:
            owner["industry"] = rng.choice(["Real Estate", "Technology", "Finance", "Energy", "Media", "Retail", "Logistics"]); changed = True

    if "media_personalities" not in save:
        save["media_personalities"] = [
            {"name": n, "role": role, "angle": angle, "favor": rng.randint(38, 64)}
            for n, role, angle in MEDIA_ARCHETYPES
        ]
        changed = True
    if "fan_segments" not in save:
        save["fan_segments"] = {}
        changed = True
    fan_segments = save.setdefault("fan_segments", {})
    for t in save.get("teams", []):
        if t["id"] not in fan_segments:
            fan_segments[t["id"]] = {k: max(20, min(90, v["base"] + rng.randint(-8, 8)))
                                     for k, v in FAN_SEGMENTS.items()}
            changed = True
    save.setdefault("people_pipeline", [])
    save.setdefault("world_log", [])
    rules = save.setdefault("league_rules", {})
    rules.setdefault("international_games", False)
    rules.setdefault("trade_deadline_week", TRADE_DEADLINE_SOLO)
    rules.setdefault("practice_squad_slots", 12)
    rules.setdefault("expansion_study", False)
    rules.setdefault("expansion_awarded", False)
    save.setdefault("expansion_candidates", [{"city": c, "score": rng.randint(42, 88)} for c in EXPANSION_CITIES])
    return changed


def fan_segment_view(save, team_id=None):
    ensure_world_systems(save)
    tid = team_id or save.get("current_team_id")
    segs = save.get("fan_segments", {}).get(tid, {})
    return [{"key": k, "label": FAN_SEGMENTS[k]["label"], "score": int(segs.get(k, FAN_SEGMENTS[k]["base"]))}
            for k in FAN_SEGMENTS]


def world_report(save):
    ensure_world_systems(save)
    team = current_team(save)
    owner = team.get("owner", {})
    pressure = relocation_pressure(save)
    expansion_teams = [t for t in save.get("teams", []) if t.get("expansion")]
    return {
        "owner": {"name": owner.get("name"), "age": owner.get("age"), "heir": owner.get("heir"),
                  "net_worth": owner.get("net_worth"), "industry": owner.get("industry")},
        "media": save.get("media_personalities", []),
        "fans": fan_segment_view(save),
        "pipeline": save.get("people_pipeline", [])[:8],
        "world_log": save.get("world_log", [])[:8],
        "rules": save.get("league_rules", {}),
        "league_size": len(save.get("teams", [])),
        "expansion_teams": expansion_teams,
        "expansion": sorted(save.get("expansion_candidates", []), key=lambda x: -x.get("score", 0))[:4],
        "relocation": pressure,
    }


def _next_team_id(save):
    nums = []
    for t in save.get("teams", []):
        tid = str(t.get("id", ""))
        if tid.startswith("t") and tid[1:].isdigit():
            nums.append(int(tid[1:]))
    return (max(nums) + 1) if nums else len(save.get("teams", []))


def _least_loaded(items, teams, key, conf=None):
    counts = {x: 0 for x in items}
    for t in teams:
        if conf is not None and t.get("conference") != conf:
            continue
        if t.get(key) in counts:
            counts[t.get(key)] += 1
    return min(items, key=lambda x: (counts[x], items.index(x)))


def _expansion_team(save, rng, city, conf, div, idx, seen):
    mascot = EXPANSION_MASCOTS.get(city, "Founders")
    entry = (conf, div, city, mascot, EXPANSION_MARKETS.get(city, "Mid"))
    team = _gen_team(rng, idx, entry, season=save.get("season", 1), seen=seen)
    team["expansion"] = {"season": save.get("season", 1), "kind": "expansion"}
    team["record"] = {"w": 0, "l": 0}
    return team


def activate_expansion(save, count=2):
    """Award expansion franchises after the owners authorize the study.
    Kept out of active seasons/drafts so schedules, standings, and pick ledgers
    do not change underneath a proven in-progress flow."""
    ensure_world_systems(save)
    rules = save.setdefault("league_rules", {})
    if not rules.get("expansion_study"):
        return False, "Owners have not authorized the expansion study yet."
    if rules.get("expansion_awarded"):
        return False, "Expansion franchises have already been awarded."
    if save.get("inseason") or save.get("draft_pending") or save.get("draft"):
        return False, "Expansion can only be awarded outside an active season or draft."

    existing_cities = {t.get("city") for t in save.get("teams", [])}
    candidates = [c for c in sorted(save.get("expansion_candidates", []), key=lambda x: -x.get("score", 0))
                  if c.get("city") not in existing_cities]
    if len(candidates) < count:
        return False, "There are not enough expansion markets available."

    rng = _rng(int(save.get("seed", 1) or 1) + save.get("season", 1) * 1889)
    seen = league_names_seen(save)
    added = []
    teams = save.setdefault("teams", [])
    for cand in candidates[:count]:
        conf = _least_loaded(CONFERENCES, teams, "conference")
        div = _least_loaded(DIVISIONS, teams, "division", conf=conf)
        idx = _next_team_id(save)
        team = _expansion_team(save, rng, cand["city"], conf, div, idx, seen)
        teams.append(team)
        added.append(team)

    generate_team_histories(teams, _rng(int(save.get("seed", 1) or 1) + 9292 + len(teams)))
    ensure_owner_names(teams, rng)
    ensure_ai_staffs(save)
    ensure_city_economics(save)
    ensure_team_cultures(save)
    ensure_world_systems(save)
    rules["expansion_awarded"] = True
    rules["expansion_season"] = save.get("season", 1)
    save["schedule"] = make_schedule(save["seed"] + save.get("season", 1), [t["id"] for t in teams])
    save["standings_cache"] = [{"id": t["id"], "full": t["full"], "conf": t["conference"],
                                "div": t["division"], "w": t["record"]["w"], "l": t["record"]["l"]}
                               for t in teams]
    names = ", ".join(t["full"] for t in added)
    msg = f"Expansion awarded: {names} join the league."
    save.setdefault("world_log", []).insert(0, {"season": save.get("season", 1), "kind": "expansion", "text": msg})
    save["world_log"] = save["world_log"][:20]
    write_save(save)
    return True, msg


def relocation_pressure(save):
    team = current_team(save)
    b = _business(save)
    c = city_economy(save)
    owner_type = (team.get("owner") or {}).get("type", "Hands-Off")
    base = 18
    base += max(0, 4 - int(b.get("stadium", 1) or 1)) * 9
    base += max(0, 48 - int(b.get("fan_happiness", 50) or 50)) // 2
    base += max(0, 58 - city_economy_score(save)) // 3
    base += 12 if owner_type in ("Billionaire", "Meddling") else 6 if owner_type == "Impatient" else 0
    base -= 10 if owner_type == "Legacy" else 0
    public_odds = int(max(12, min(88, c.get("tax_climate", 50) * 0.42 + b.get("fan_happiness", 50) * 0.38
                                  + c.get("transit", 50) * 0.16 - c.get("construction", 100) * 0.08)))
    amount = round(18 + (4 - min(3, int(b.get("stadium", 1) or 1))) * 10 + max(0, city_economy_score(save) - 55) * 0.25, 1)
    return {"score": int(max(0, min(100, base))), "public_odds": public_odds, "funding_amount": amount,
            "note": ("Relocation pressure is loud." if base >= 70 else
                     "Owner is watching the stadium situation." if base >= 45 else
                     "City/franchise relationship is stable.")}


def hold_public_stadium_vote(save):
    pressure = relocation_pressure(save)
    rng = _rng(int(save.get("seed", 1) or 1) + save.get("season", 1) * 877)
    passed = rng.randint(1, 100) <= pressure["public_odds"]
    if passed:
        _business(save)["cash"] = round(_business(save)["cash"] + pressure["funding_amount"], 1)
        msg = f"Public stadium funding passes: ${pressure['funding_amount']}M added to club cash."
        _rel_nudge(save, "league_office", 1, "secured public stadium support")
    else:
        msg = "Public stadium funding fails. Relocation pressure rises."
        _rel_nudge(save, "media", -1, "lost a public stadium vote")
    save.setdefault("world_log", []).insert(0, {"season": save.get("season", 1), "kind": "stadium_vote",
                                                "text": msg, "passed": passed})
    save["world_log"] = save["world_log"][:20]
    write_save(save)
    return passed, msg


def _succeed_owner(save, t, rng, kind, old_name):
    """New owner, new regime: roll a fresh archetype (heirs often keep the
    family lean; buyers start clean), and if it's YOUR club, the new boss
    forms his own opinion of you and issues a fresh mandate."""
    owner = t["owner"]
    old_type = owner.get("type", "Hands-Off")
    others = [x for x in OWNER_TYPES if x != old_type]
    if kind == "heir" and (old_type == "Legacy" or rng.random() < 0.5):
        new_type = old_type                              # family continuity
    else:
        new_type = rng.choice(others) if others else old_type
    owner["type"] = new_type
    if t["id"] == save.get("current_team_id"):
        gm = save.get("gm", {})
        ot = int(gm.get("owner_trust", 55) or 55)
        gm["owner_trust"] = int(round(50 + (ot - 50) * 0.35))   # he barely knows you yet
        save.pop("owner_directive", None)                       # a new mandate is coming
        prof = _OWNER_PROFILES.get(new_type, {})
        save["ownership_change"] = {
            "old": old_name, "new": owner.get("name", "the new owner"),
            "kind": kind, "type": new_type, "title": prof.get("title", "Owner"),
            "style": prof.get("style", ""), "trust": gm["owner_trust"]}
        _tl(save, save.get("season", 1), "owner", "\U0001F511",
            ("New ownership: " + owner.get("name", "A new owner") + " takes over the "
             + t["full"]),
            (("Inherits the franchise" if kind == "heir" else "Buys the franchise")
             + " as a " + new_type + " owner. Your standing resets \u2014 earn his trust."))
    return new_type


def evolve_world_systems(save, rng):
    ensure_world_systems(save)
    for t in save.get("teams", []):
        owner = t.setdefault("owner", {})
        owner["age"] = int(owner.get("age", 55) or 55) + 1
        if owner["age"] >= 84 and rng.random() < 0.20:
            old = owner.get("name", "The owner")
            owner["name"] = owner.get("heir") or _gen_name(rng)
            owner["age"] = rng.randint(34, 58)
            owner["heir"] = _gen_name(rng)
            _succeed_owner(save, t, rng, "heir", old)
            save.setdefault("world_log", []).insert(0, {"season": save.get("season", 1), "kind": "succession",
                                                        "text": f"{old} passes the {t['full']} to {owner['name']} ({owner['type']} owner)."})
        elif owner["age"] >= 72 and rng.random() < 0.05:
            old = owner.get("name", "The owner")
            owner["name"] = _gen_name(rng)
            owner["age"] = rng.randint(38, 64)
            owner["heir"] = _gen_name(rng)
            owner["net_worth"] = round(float(owner.get("net_worth", 6) or 6) * rng.uniform(0.8, 1.45), 1)
            _succeed_owner(save, t, rng, "sale", old)
            save.setdefault("world_log", []).insert(0, {"season": save.get("season", 1), "kind": "sale",
                                                        "text": f"{old} sells the {t['full']} to {owner['name']} ({owner['type']} owner)."})

    # Retired players can become part of the broader ecosystem.
    for r in (save.get("retirements") or [])[:4]:
        if r.get("hof") or rng.random() < 0.16:
            role = rng.choice(["coach", "scout", "agent", "broadcaster", "front-office assistant"])
            item = {"season": save.get("season", 1), "name": r.get("name"), "from": "retired player",
                    "role": role, "note": f"{r.get('pos', '')} career opens a second act."}
            save.setdefault("people_pipeline", []).insert(0, item)
            if role == "broadcaster":
                save.setdefault("media_personalities", []).insert(0, {"name": r.get("name"), "role": "Former Player Analyst",
                                                                       "angle": "player credibility", "favor": rng.randint(45, 68)})

    rec = (save.get("last_outcome") or {}).get("record", {})
    w, l = int(rec.get("w", 8) or 8), int(rec.get("l", 8) or 8)
    segs = save.get("fan_segments", {}).get(save.get("current_team_id"), {})
    if segs:
        segs["diehards"] = max(10, min(100, segs.get("diehards", 60) + (1 if w >= l else -1)))
        segs["casuals"] = max(10, min(100, segs.get("casuals", 50) + (2 if w >= 11 else -2 if w <= 5 else 0)))
        segs["stars"] = max(10, min(100, segs.get("stars", 50) + (1 if save.get("season_mvp") else 0)))

    save["world_log"] = save.get("world_log", [])[:20]
    save["people_pipeline"] = save.get("people_pipeline", [])[:30]
    save["media_personalities"] = save.get("media_personalities", [])[:12]


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


def _build_playoff_recap(save, my, opp, r, rng):
    """A full post-game recap for one of the user's playoff games (same shape the
    weekly recap page reads), built from the recorded round result. Box scores are
    generated with record=False so the playoffs don't skew regular-season leaders."""
    won, us, them, rnd = r["won"], r["us"], r["them"], r["round"]
    mine, my_sum = _game_perf(my, us, won, rng, record=False)
    theirs, opp_sum = (_game_perf(opp, them, not won, rng, record=False) if opp else ([], {}))
    st = max(mine, key=lambda x: x["score"]) if mine else None
    star = {k: st[k] for k in ("name", "pos", "line", "pid")} if st else None
    km = key_moment_summary(save)
    opp_full = opp["full"] if opp else r.get("opp", "?")
    opp_short = (opp.get("name", opp["full"]) if opp else r.get("opp", "?"))
    stakes = ("Win it all." if rnd == "BRK Championship" else "Win and advance." if won
              else "Win or your season is over.")
    return {
        "season": save.get("season", 1), "week": None, "round": rnd, "playoff": True,
        "won": won, "us": us, "them": them, "home": True,
        "opp": opp_full, "opp_short": opp_short,
        "my_team": my["full"], "my_short": my.get("name", my["full"]),
        "weather": None, "key_moment": km,
        "my_box": _game_box(mine), "opp_box": _game_box(theirs),
        "my_summary": my_sum, "opp_summary": opp_sum,
        "injuries": [], "incidents": [],
        "context": {"stakes": stakes, "round": rnd},
        "news": _compose_game_story(rng, won, us, them, my.get("name", my["full"]),
                                    opp_short, star, km.get("call", "Balanced"), None, round_name=rnd),
    }


def _begin_postseason(save):
    """The regular season is over. Freeze the season's awards, run the bracket, and
    (if the user made it) queue their playoff games to be PLAYED one at a time
    through the recap page instead of resolving invisibly."""
    rng = _rng(save["seed"] + save["season"] * 1000 + 991)
    teams = {t["id"]: t for t in save["teams"]}
    powers = {tid: power_rating(t)
              + (ai_coach_edge(t) if tid != save["current_team_id"] else 0.0)
              for tid, t in teams.items()}
    save["leaders"] = stat_leaders(save["teams"])          # from the season actually played
    save["season_mvp"] = stat_mvp(save["teams"])
    save["all_pro"] = all_pro_team(save["teams"])
    update_records(save, save["teams"], save["season"])
    _archive_season(save["teams"], save["season"])

    gl = (save.get("inseason") or {}).get("log", [])
    if gl:
        best = max(gl, key=lambda x: x.get("_score", 0))
        for g in gl:
            g["best"] = g is best
            g.pop("_score", None)
    save["game_log"] = gl

    standings = sorted(save["teams"], key=lambda t: (t["record"]["w"], powers[t["id"]]), reverse=True)
    champion, conf_champs, playoff_ids, run = _run_postseason(save, rng, standings, powers)

    uid = save["current_team_id"]
    queue = []
    if run.get("made"):
        my = teams[uid]
        for r in run["rounds"]:
            queue.append(_build_playoff_recap(save, my, teams.get(r.get("opp_id")), r, rng))
    save["postseason"] = {
        "active": bool(queue), "made": run.get("made", False),
        "queue": queue, "idx": 0,
        "champion": champion, "conf_champs": conf_champs,
        "playoff_ids": sorted(playoff_ids), "run": run,
        "standings_ids": [t["id"] for t in standings], "season": save["season"],
    }
    save.pop("inseason", None)
    if not queue:                                # missed the playoffs \u2014 nothing to play
        return _finalize_after_postseason(save)
    write_save(save)
    return save


def reveal_playoff_game(save):
    """Reveal the next queued playoff game as `last_game` (the recap page renders it).
    When the last one is shown, wrap the season into the offseason."""
    ps = save.get("postseason") or {}
    q = ps.get("queue", [])
    i = ps.get("idx", 0)
    if not ps.get("active") or i >= len(q):
        return False
    save["last_game"] = q[i]
    ps["idx"] = i + 1
    if ps["idx"] >= len(q):
        ps["active"] = False
        _finalize_after_postseason(save)
    else:
        write_save(save)
    return True


def _finalize_after_postseason(save):
    ps = save.get("postseason") or {}
    teams = {t["id"]: t for t in save["teams"]}
    powers = {tid: power_rating(t)
              + (ai_coach_edge(t) if tid != save["current_team_id"] else 0.0)
              for tid, t in teams.items()}
    champion = ps.get("champion")
    conf_champs = ps.get("conf_champs", [])
    playoff_ids = set(ps.get("playoff_ids", []))
    _run = ps.get("run", {"made": False, "rounds": []})
    standings = [teams[i] for i in ps.get("standings_ids", []) if i in teams] or \
        sorted(save["teams"], key=lambda t: (t["record"]["w"], powers[t["id"]]), reverse=True)
    _record_champion_bench(save, teams[champion])

    uid = save["current_team_id"]
    rec = dict(teams[uid]["record"])
    made_playoffs, won_title = uid in playoff_ids, champion == uid
    if _run["made"]:
        _last = _run["rounds"][-1] if _run["rounds"] else None
        _run["result"] = ("BRK Champions \U0001F3C6" if won_title else
                          "Runner-up \u2014 lost the BRK Championship"
                          if _last and _last["round"] == "BRK Championship" else
                          ("Eliminated in the " + _last["round"]) if _last else "Made the playoffs")
        _run["champion"] = teams[champion]["full"]
        _run["season"] = ps.get("season", save["season"])
        save["playoff_run"] = _run
    else:
        save.pop("playoff_run", None)
    _evaluate_owner_directive(save, rec, made_playoffs)
    outcome = _evaluate_gm(save, rec, made_playoffs, won_title, teams[champion]["full"])
    outcome["season"] = save["season"]
    _apply_finance(save, rec, won_title)

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
    _issue_owner_directive(save)
    _consider_career_promotion(save)
    owner_statement(save, outcome)
    owner_meeting(save, outcome)
    _log_season_milestones(save, outcome)          # thread the season into the career timeline
    _check_holdouts(save)
    generate_news(save)
    save.pop("inseason", None)
    save.pop("postseason", None)                   # the playoff run is over; card lives on playoff_run
    save.pop("pgl", None)                           # per-player game log resets for the new season
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
    while (save.get("postseason") or {}).get("active"):    # auto-play the playoffs for sim-to-end
        reveal_playoff_game(save)
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
    dev = sb["development"] + facility_development_bonus(save)
    cond = sb["conditioning"]
    uid = save["current_team_id"]
    _apply_role_friction(save)   # Loop 4: paid-but-benched players sour over the year
    for t in save["teams"]:      # dead money ages off as the season closes
        entries = [dict(e, seasons_left=int(e.get("seasons_left", 1)) - 1)
                   for e in t.get("dead_cap_entries", [])]
        t["dead_cap_entries"] = [e for e in entries if e["seasons_left"] > 0]
    mentor_pos = {p["pos"] for p in current_team(save)["roster"] if p.get("role") == "mentor"}
    breakouts, unlocks, evolution = [], [], []
    for t in save["teams"]:
        my = t["id"] == uid
        for p in t["roster"]:
            pre_ovr = p["overall"]
            pre_pot = p["potential"]
            bonus = (dev + position_coach_dev(save, p["pos"])) if my else 0   # position coaches
            if my and p["pos"] in mentor_pos and p.get("age", 30) <= 24 and p.get("role") != "mentor":
                bonus += 1                                                    # a mentor accelerates the kid
            if my and save.get("weekly_ops", {}).get("rookie_snaps") == "Develop" and p.get("age", 30) <= 23:
                bonus += 1                                                    # a season of developmental snaps
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
    for r in save["retirements"]:                     # great careers seed bloodlines
        if r.get("peak", 0) >= 80 and rng.random() < 0.35:
            parts = r["name"].split()
            save.setdefault("legacy_pool", []).append(
                {"first": parts[0], "last": parts[-1], "pos": r["pos"],
                 "retired": save["season"], "hof": bool(r.get("hof"))})
    save["legacy_pool"] = save.get("legacy_pool", [])[-20:]
    route_retiree_careers(save, rng)   # retirees enter the People registry + second careers
    evolve_city_economics(save, rng)
    evolve_world_systems(save, rng)
    develop_staff(save, rng)   # coaches age, sharpen/fade, and eventually retire
    run_coaching_carousel(save, rng)   # ...and the rest of the league moves too
    run_executive_carousel(save, rng)   # ...and the front offices move too
    save["free_agents"] = _gen_fa_pool(rng, season=save.get("season", 1) + 1, seen=league_names_seen(save))
    ensure_player_portraits(save)


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


def gm_legacy(save):
    """A GM's historical case: the grade is current reputation; legacy is what
    the league remembers when the career ends."""
    g = gm_grade(save)
    gm = save["gm"]
    seasons = int(g.get("seasons") or 0)
    titles = int(g.get("titles") or 0)
    playoffs = int(g.get("playoffs") or 0)
    rating = int(g.get("rating") or 0)
    money = int(g.get("money") or 0)
    jobs = len({c.get("team") for c in gm.get("career", []) if c.get("team")})
    score = rating + titles * 7 + playoffs * 2 + min(12, seasons) + min(10, money // 250) + max(0, jobs - 1) * 2
    score = int(max(0, min(125, score)))
    if score >= 105:
        tier = "First-ballot Executive Hall of Famer"
    elif score >= 88:
        tier = "Executive Hall of Fame"
    elif score >= 72:
        tier = "Franchise Legend"
    elif score >= 55:
        tier = "Respected Builder"
    elif score >= 35:
        tier = "Working GM"
    else:
        tier = "Unfinished Resume"
    case = []
    if titles:
        case.append(f"{titles} championship{'s' if titles != 1 else ''}")
    if playoffs:
        case.append(f"{playoffs} playoff run{'s' if playoffs != 1 else ''}")
    if g.get("w") or g.get("l"):
        case.append(f"{g['w']}-{g['l']} career record")
    if jobs > 1:
        case.append(f"built across {jobs} franchises")
    if money:
        case.append(f"${money}M in career revenue")
    return {**g, "score": score, "legacy_tier": tier, "jobs": jobs,
            "case": case or ["No completed seasons yet."],
            "hall_worthy": score >= 88 or titles >= 3 or (titles >= 2 and rating >= 74)}


def franchise_report_card(save):
    team = current_team(save)
    teams = save.get("teams", [])
    powers = sorted([power_rating(t) for t in teams], reverse=True)
    my_power = power_rating(team)
    rank = (powers.index(my_power) + 1) if my_power in powers else len(powers)
    roster_score = int(max(15, min(95, 96 - (rank - 1) * (70 / max(1, len(powers) - 1)))))

    sb = staff_bonus(save)
    staff_score = int(max(20, min(95, 58 + sb.get("power", 0) * 7 + sb.get("scheme", 0) * 4
                                  + (8 if sb.get("development") else 0) + (sb.get("scouting", 0) - 50) * 0.25)))

    b = _business(save)
    cap_room = cap_total(save) - cap_used(team)
    finance_score = int(max(15, min(98, 42 + min(25, b.get("cash", 0) / 6)
                                    + max(-12, min(12, cap_room / 2))
                                    + (b.get("fan_happiness", 50) - 50) * 0.35
                                    + (city_economy_score(save) - 50) * 0.25)))

    c = team_culture(save)
    traits = c.get("traits", {})
    culture_score = int(max(15, min(98, (sum(traits.values()) / len(traits)) if traits else 55)))

    young_core = [p for p in team.get("roster", []) if int(p.get("age", 30) or 30) <= 25 and p.get("overall", 0) >= 70]
    outlook_score = int(max(15, min(98, roster_score * 0.35 + staff_score * 0.2 + finance_score * 0.2
                                    + min(20, len(young_core) * 3) + max(-8, min(8, cap_room / 6)))))

    rows = [
        {"key": "roster", "label": "Roster", "score": roster_score, "grade": _rating_to_grade(roster_score),
         "note": f"#{rank} league power at {my_power}."},
        {"key": "staff", "label": "Staff", "score": staff_score, "grade": _rating_to_grade(staff_score),
         "note": f"Power edge {sb.get('power', 0):+.1f}, scheme {sb.get('scheme', 0):+.1f}."},
        {"key": "finance", "label": "Finance", "score": finance_score, "grade": _rating_to_grade(finance_score),
         "note": f"${b.get('cash', 0):.1f}M cash, ${cap_room:.1f}M cap room."},
        {"key": "culture", "label": "Culture", "score": culture_score, "grade": _rating_to_grade(culture_score),
         "note": c.get("identity", "Identity forming.")},
        {"key": "outlook", "label": "Outlook", "score": outlook_score, "grade": _rating_to_grade(outlook_score),
         "note": f"{len(young_core)} young core players, city score {city_economy_score(save)}."},
    ]
    overall = int(round(sum(r["score"] for r in rows) / len(rows)))
    return {"overall": overall, "grade": _rating_to_grade(overall),
            "verdict": ("Built to contend" if overall >= 78 else "Ascending" if overall >= 65 else
                        "Stable but flawed" if overall >= 50 else "Rebuild pressure"),
            "rows": rows}


def alert_inbox(save):
    alerts = []

    def add(kind, title, body, tab="dashboard", urgency=1):
        icons = {"draft": "D", "staff": "S", "trade": "T", "league": "L", "owner": "O",
                 "weekly": "W", "medical": "M", "contract": "$", "front-office": "!", "report": "R"}
        alerts.append({"kind": kind, "title": title, "body": body, "text": f"{title}: {body}".strip(": "),
                       "tab": tab, "urgency": urgency, "pri": urgency, "icon": icons.get(kind, "!")})

    if save.get("draft_pending"):
        add("draft", "Rookie Draft is open", "Your pick board is live. Make selections or work trade-down offers.", "draft", 3)
    if save.get("staff_poach"):
        p = save["staff_poach"]
        add("staff", f"{p.get('rival')} are chasing your coach", f"Decide whether to match for {p.get('name')}.", "staff", 3)
    if (save.get("inseason") or {}).get("offer"):
        o = save["inseason"]["offer"]
        add("trade", f"Trade offer from {o.get('team')}", "A rival deal is waiting for your answer.", "trades", 2)
    if save.get("league_vote"):
        add("league", "Owners' vote on the table", save["league_vote"].get("title", "A league proposal needs your position."), "league", 2)
    if save.get("owner_directive"):
        add("owner", "Owner directive active", save["owner_directive"].get("text", ""), "dashboard", 2)
    for i in (save.get("agenda") or [])[:3]:
        add("weekly", i.get("title", "Weekly decision"), i.get("detail", "A staff/player issue needs a call."), "command", 2)
    for i in (save.get("inseason", {}) or {}).get("injuries", [])[:3]:
        add("medical", f"{i.get('pos')} {i.get('name')} injured", f"Out about {i.get('weeks')} week(s). Review medical policy/depth.", "command", 2)
    if save.get("holdouts"):
        h = save["holdouts"][0]
        add("contract", f"{h.get('pos')} {h.get('name')} is holding out", "Extension pressure is affecting the roster.", "front-office", 2)
    if save.get("front_office_issues"):
        issue = save["front_office_issues"][0]
        add("front-office", issue.get("label", "Front-office issue"), issue.get("summary", ""), "front-office", 1)
    card = franchise_report_card(save)
    if card["overall"] < 50:
        add("report", "Franchise report card is under pressure", f"{card['grade']} overall: {card['verdict']}.", "dashboard", 1)
    return sorted(alerts, key=lambda a: -a["urgency"])[:10]


def retire_gm(save):
    """End the active GM career and, if the resume is strong enough, cast the
    GM into the executive wing of the Hall."""
    if save.get("gm_retired"):
        return False, "This GM career is already retired."
    leg = gm_legacy(save)
    if not leg.get("seasons"):
        return False, "Finish at least one season before retiring the GM."
    gm = save["gm"]
    record = {
        "name": gm.get("name", "GM"),
        "retired": save.get("season", 1),
        "tier": leg["legacy_tier"],
        "score": leg["score"],
        "grade": leg["grade"],
        "seasons": leg["seasons"],
        "record": f"{leg['w']}-{leg['l']}",
        "winpct": leg["winpct"],
        "titles": leg["titles"],
        "playoffs": leg["playoffs"],
        "money": leg["money"],
        "jobs": leg["jobs"],
        "case": leg["case"],
        "hof": bool(leg["hall_worthy"]),
    }
    save["gm_retired"] = record
    save["unemployed"] = True
    save.pop("inseason", None)
    save.pop("offseason", None)
    save.pop("offseason_mode", None)
    save.pop("draft_pending", None)
    save.pop("draft", None)
    save.pop("staff_poach", None)
    if record["hof"]:
        hall = save.setdefault("executive_hall", [])
        if not any(h.get("name") == record["name"] and h.get("retired") == record["retired"] for h in hall):
            hall.insert(0, record)
        save["executive_hall"] = hall[:20]
    _tl(save, save.get("season", 1), "hof" if record["hof"] else "retired", "🏛" if record["hof"] else "📁",
        f"{record['name']} retires — {record['tier']}",
        " · ".join(record["case"][:3]))
    write_save(save)
    return True, f"{record['name']} retires as {record['tier']}."


def gm_career_rank(save):
    """Your current place in a front-office career."""
    gm = save.get("gm", {})
    leg = gm_legacy(save)
    titles = int(leg.get("titles", 0) or 0)
    seasons = int(leg.get("seasons", 0) or 0)
    score = int(leg.get("score", 0) or 0)
    if gm.get("is_commissioner"):
        return {"title": "League Commissioner", "icon": "\u2696", "tier": "commissioner",
                "blurb": "You run the whole league now \u2014 the pinnacle of the profession."}
    if gm.get("part_owner"):
        return {"title": "GM & Part-Owner", "icon": "\U0001F3E6", "tier": "owner",
                "blurb": "You bought in. Owners don't fire themselves."}
    if gm.get("president"):
        return {"title": "GM & President of Football Ops", "icon": "\U0001F454", "tier": "president",
                "blurb": "You run the entire football operation, not just the roster."}
    if titles >= 2 or score >= 88:
        return {"title": "League Icon", "icon": "\U0001F31F", "tier": "icon",
                "blurb": "A name the whole league knows."}
    if titles >= 1 or score >= 72:
        return {"title": "Respected GM", "icon": "\U0001F4C8", "tier": "respected",
                "blurb": "You've proven you can build a winner."}
    if seasons >= 3:
        return {"title": "Established GM", "icon": "\U0001F4BC", "tier": "established",
                "blurb": "A steady hand running the show."}
    return {"title": "Rookie Executive", "icon": "\U0001F195", "tier": "rookie",
            "blurb": "Your career is just beginning."}


def _consider_career_promotion(save):
    """At the offseason, offer the next rung if it's been earned."""
    if save.get("career_offer"):
        return
    gm = save.get("gm", {})
    leg = gm_legacy(save)
    titles = int(leg.get("titles", 0) or 0)
    seasons = int(leg.get("seasons", 0) or 0)
    money = int(leg.get("money", 0) or 0)
    if gm.get("president") and titles >= 3 and seasons >= 10 and not gm.get("is_commissioner"):
        save["career_offer"] = {"kind": "commissioner", "title": "The Commissioner's Chair",
            "text": "The owners want YOU to run the league. Take the Commissioner's chair \u2014 the highest honor in football operations?"}
        return
    if titles >= 2 and money >= 1200 and not gm.get("part_owner") and not gm.get("is_commissioner"):
        save["career_offer"] = {"kind": "ownership", "title": "An Ownership Stake",
            "text": "You've earned the chance to buy an ownership stake in the club. Own a piece \u2014 and never fear the firing squad again?"}
        return
    if not gm.get("president") and not gm.get("part_owner") and titles >= 1 and seasons >= 4:
        save["career_offer"] = {"kind": "president", "title": "President of Football Operations",
            "text": "The owner wants to promote you to President of Football Operations \u2014 full authority over the entire football side. Take it?"}
        return


def resolve_career_offer(save, accept):
    off = save.pop("career_offer", None)
    if not off:
        return False, "There is no offer on the table."
    gm = save["gm"]
    kind = off["kind"]
    if not accept:
        _tl(save, save.get("season", 1), "owner", "\U0001F91A",
            "You turned down " + off["title"], "Not the right time \u2014 the door may open again.")
        write_save(save)
        return True, "You passed on " + off["title"] + " \u2014 for now."
    if kind == "president":
        gm["president"] = True
        _business(save)["cash"] = round(_business(save)["cash"] + 25.0, 1)
        _tl(save, save.get("season", 1), "owner", "\U0001F454",
            gm.get("name", "You") + " promoted to President of Football Operations",
            "Full authority over the football operation \u2014 and a longer leash from ownership.")
        write_save(save)
        return True, "Promotion accepted \u2014 you're now GM & President of Football Operations. The hot seat cools, and $25M is added to your operating budget."
    if kind == "ownership":
        gm["part_owner"] = True
        _tl(save, save.get("season", 1), "owner", "\U0001F3E6",
            gm.get("name", "You") + " buys an ownership stake",
            "You're part-owner now. Owners don't fire themselves \u2014 the hot seat is gone.")
        write_save(save)
        return True, "You bought in. As a part-owner you can no longer be fired, and a share of revenue flows to you each season."
    if kind == "commissioner":
        gm["is_commissioner"] = True
        leg = gm_legacy(save)
        save["commissioner"] = {"name": gm.get("name", "You"), "since": save.get("season", 1),
                                "age": 55, "is_user": True}
        rec = {"name": gm.get("name", "You"), "retired": save.get("season", 1),
               "tier": "League Commissioner", "score": 125, "grade": "A+",
               "seasons": int(leg.get("seasons", 0) or 0),
               "record": (str(leg.get("w", 0)) + "-" + str(leg.get("l", 0))) if leg.get("w") or leg.get("l") else "\u2014",
               "winpct": float(leg.get("winpct", 0) or 0), "titles": int(leg.get("titles", 0) or 0),
               "playoffs": int(leg.get("playoffs", 0) or 0), "money": int(leg.get("money", 0) or 0), "jobs": 1,
               "case": ["Rose from GM to Commissioner", "The pinnacle of the profession"], "hof": True}
        hall = save.setdefault("executive_hall", [])
        if not any(h.get("name") == rec["name"] and h.get("tier") == "League Commissioner" for h in hall):
            hall.insert(0, rec)
        save["executive_hall"] = hall[:20]
        _tl(save, save.get("season", 1), "hof", "\u2696",
            gm.get("name", "You") + " elected LEAGUE COMMISSIONER",
            "From running a roster to running the league \u2014 the rarest career capstone in football.")
        write_save(save)
        return True, "You've been elected League Commissioner \u2014 the pinnacle. You keep your club, but your name now sits atop the whole league."
    return False, "Unknown offer."


def career_ladder(save):
    gm = save.get("gm", {})
    steps = [
        {"title": "President of Football Ops", "icon": "\U0001F454",
         "have": bool(gm.get("president") or gm.get("part_owner") or gm.get("is_commissioner")),
         "need": "1 title + 4 seasons"},
        {"title": "Part-Owner", "icon": "\U0001F3E6",
         "have": bool(gm.get("part_owner") or gm.get("is_commissioner")),
         "need": "2 titles + deep pockets (\u2248$1.2B earned)"},
        {"title": "League Commissioner", "icon": "\u2696",
         "have": bool(gm.get("is_commissioner")),
         "need": "President + 3 titles + 10 seasons"},
    ]
    return {"rank": gm_career_rank(save), "steps": steps, "offer": save.get("career_offer")}


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

    fire_floor = 25
    if gm.get("president"):
        fire_floor = 12
    if gm.get("part_owner") or gm.get("is_commissioner"):
        fire_floor = -1
    status, headline, offers = "retained", "", []
    if gm["owner_trust"] < fire_floor:
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
        _rel_nudge(save, "media", 4, "delivered a championship season")
        _rel_nudge(save, "locker_room", 3, "the room saw the plan end in a title")
        _culture_nudge(save, "ambition", 3, "a championship raised the standard")
        _culture_nudge(save, "player_trust", 2, "the locker room saw the plan work")
    elif made_playoffs:
        _rel_nudge(save, "media", 1, "kept the club in the playoff conversation")
        _culture_nudge(save, "stability", 1, "a playoff season reinforced the process")
    if status == "fired":
        _rel_nudge(save, "media", -2, "ownership moved on after a failed mandate")
        _rel_nudge(save, "league_office", -1, "lost a front-office seat")
        _culture_nudge(save, "stability", -3, "another leadership change shook the building")
        _culture_nudge(save, "player_trust", -2, "players watched the front office turn over")
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


# --------------------------------------------------------------------------- #
# The LIVING LEAGUE — every rival club has a real coaching staff (HC/OC/DC),
# and the offseason carousel keeps the ecosystem moving: bad seasons get
# coaches fired, old coaches retire, coordinators get promoted to head jobs,
# your poached coaches actually join their new clubs, and your fired coaches
# resurface across the league.
# --------------------------------------------------------------------------- #
_AI_STAFF_ROLES = ("head_coach", "off_coord", "def_coord")
_AI_ROLE_LABEL = {"head_coach": "Head Coach", "off_coord": "OC", "def_coord": "DC"}


def _gen_ai_coach(rng, role):
    c = _gen_staff(rng, "off_coord" if role == "head_coach" else role)
    c.pop("id", None)
    return _fit_role(c, role, rng)


def _fit_role(c, role, rng):
    """Make a coach's kit match the chair he's sitting in."""
    c = dict(c)
    if role == "head_coach":
        c.pop("system", None)
        c.pop("playbook", None)
        c.setdefault("philosophy", rng.choice(["Analytics", "Old School", "Balanced"]))
        return c
    schemes = OFF_SCHEMES if role == "off_coord" else DEF_SCHEMES
    if c.get("system") not in schemes:
        c["system"] = rng.choice(list(schemes))
        c.pop("playbook", None)
    if not c.get("playbook"):
        pool = PLAYBOOK_PACKAGES.get(c["system"], [])
        c["playbook"] = rng.sample(pool, k=min(2, len(pool)))
    return c


def ensure_ai_staffs(save):
    """Every club that isn't yours gets a named HC / OC / DC. Returns True if
    anything changed so the caller can persist once."""
    changed = False
    uid = save.get("current_team_id")
    for t in save.get("teams", []):
        if t["id"] == uid:
            continue
        staff = t.setdefault("staff", {})
        for role in _AI_STAFF_ROLES:
            if not staff.get(role):
                rng = _rng(int(save.get("seed", 1) or 1)
                           + abs(hash(str(t["id"]) + role)) % 99991)
                staff[role] = _gen_ai_coach(rng, role)
                changed = True
    return changed


def ai_coach_edge(team):
    """A rival's bench matters: a well-coached AI club plays above its roster."""
    staff = team.get("staff") or {}
    if not staff:
        return 0.0
    ratings = [c.get("rating", 55) for c in staff.values() if isinstance(c, dict)]
    if not ratings:
        return 0.0
    return round((sum(ratings) / len(ratings) - 60) * 0.05, 2)


def _coach_joins_rival(save, coach, role, rival_full):
    """A coach who leaves you doesn't evaporate — he takes the rival's job
    (their old man drops into the carousel pool), or waits in the pool."""
    if not isinstance(coach, dict):
        return
    coach = dict(coach, rating=min(95, int(coach.get("rating", 55) or 55) + 2))
    rival = next((t for t in save.get("teams", [])
                  if t.get("full") == rival_full and t["id"] != save.get("current_team_id")), None)
    if rival is None:
        save.setdefault("coach_pool", []).append(dict(coach, ex_user=True, ex_role=role))
        return
    slot = role if role in _AI_STAFF_ROLES else (
        "off_coord" if role in ("qb_coach", "oline_coach", "cond_coach", "st_coord") else "def_coord")
    staff = rival.setdefault("staff", {})
    old = staff.get(slot)
    if isinstance(old, dict):
        save.setdefault("coach_pool", []).append(dict(old, ex_role=slot))
    rng = _rng(int(save.get("seed", 1) or 1) + sum(ord(ch) for ch in str(coach.get("name", ""))))
    staff[slot] = _fit_role(coach, slot, rng)


# --------------------------------------------------------------------------- #
# THE PEOPLE REGISTRY — a career-state machine. Any notable person (starting
# with retired players) gets a permanent record: their playing career, then
# their second act, then every stop after. The carousel and the championship
# write to it, so the world REMEMBERS — the QB you drafted can be tracked all
# the way to a title-winning head-coaching career somewhere else.
# --------------------------------------------------------------------------- #
_SECOND_CAREER_ROLES = {
    "scouting": ("Scout", "\U0001F50D", "takes a scouting job"),
    "broadcasting": ("Broadcaster", "\U0001F399", "joins the broadcast booth"),
    "front_office": ("Front Office", "\U0001F3E2", "moves into a front-office role"),
}
_SECOND_CAREER_WEIGHTS = [("coaching", 0.40), ("broadcasting", 0.26),
                          ("scouting", 0.20), ("front_office", 0.14)]


def _person_key(name):
    return " ".join(str(name or "").split()).lower()


def register_person(save, name, **fields):
    reg = save.setdefault("people", {})
    key = _person_key(name)
    if not key:
        return None
    e = reg.get(key)
    if e is None:
        e = {"name": name, "stints": []}
        reg[key] = e
    for k, v in fields.items():
        if v is not None:
            e[k] = v
    return e


def add_person_stint(save, name, role, team, note="", milestone=False):
    e = register_person(save, name)
    if e is None:
        return None
    season = save.get("season", 1)
    stints = e.setdefault("stints", [])
    if not (stints and stints[0].get("role") == role and stints[0].get("team") == team):
        stints.insert(0, {"season": season, "role": role, "team": team, "note": note})
        e["stints"] = stints[:20]
    e["current"] = {"role": role, "team": team, "season": season}
    if milestone:
        e["milestone"] = note or role
    return e


def _prune_people(save, cap=200):
    reg = save.get("people") or {}
    if len(reg) <= cap:
        return
    keep = [(k, e) for k, e in reg.items()
            if e.get("your_alum") or e.get("milestone") or e.get("hof")]
    rest = [(k, e) for k, e in reg.items()
            if not (e.get("your_alum") or e.get("milestone") or e.get("hof"))]
    rest.sort(key=lambda kv: (kv[1].get("current") or {}).get("season", 0), reverse=True)
    room = max(0, cap - len(keep))
    save["people"] = dict(keep + rest[:room])


def route_retiree_careers(save, rng):
    """This offseason's notable retirees enter the People registry with their
    playing career, and some pick up a second career. Coaching flows through
    the hireable staff market (inject_player_coaches); scouting/broadcasting/
    front-office are recorded here as league-wide career moves."""
    uid_team = current_team(save).get("full", "")
    for r in save.get("retirements", []):
        peak = int(r.get("peak", 0) or 0)
        if peak < 74:
            r["second_career"] = None
            continue
        e = register_person(
            save, r.get("name", ""),
            former_player={"pos": r.get("pos", ""), "peak": peak,
                           "hof": bool(r.get("hof")),
                           "seasons": int(r.get("seasons", 0) or 0),
                           "summary": r.get("summary", "")},
            hof=bool(r.get("hof")),
            your_alum=(bool(uid_team) and r.get("team") == uid_team))
        if e is not None and not e.get("stints"):
            e["stints"].append({"season": int(r.get("retired", save.get("season", 1)) or save.get("season", 1)),
                                "role": "Player (" + str(r.get("pos", "")) + ")",
                                "team": r.get("team", ""), "note": r.get("summary", "")})
        chance = 0.42 + (peak - 74) * 0.03 + (0.20 if r.get("hof") else 0)
        if rng.random() > min(0.90, chance):
            r["second_career"] = None
            continue
        total = sum(w for _, w in _SECOND_CAREER_WEIGHTS)
        roll, acc, kind = rng.random() * total, 0.0, "coaching"
        for k, w in _SECOND_CAREER_WEIGHTS:
            acc += w
            if roll <= acc:
                kind = k
                break
        r["second_career"] = kind
        if kind == "coaching":
            role0 = _PLAYER_COACH_ROLE.get(str(r.get("pos", "")).upper(), "off_coord")
            if role0 not in ("off_coord", "def_coord"):
                role0 = ("off_coord" if role0 in ("qb_coach", "oline_coach", "cond_coach", "st_coord")
                         else "def_coord")
            cc = _gen_ai_coach(rng, role0)
            cc["name"] = r.get("name", cc.get("name", ""))
            cc["rating"] = max(46, min(78, int(46 + (peak - 72) * 0.5
                                              + int(r.get("all_pro", 0) or 0) * 2
                                              + (5 if r.get("hof") else 0))))
            cc["age"] = min(48, 26 + int(r.get("seasons", 0) or 0) + rng.randint(1, 3))
            cc["former_player"] = {"pos": r.get("pos", ""), "peak": peak,
                                   "seasons": int(r.get("seasons", 0) or 0),
                                   "hof": bool(r.get("hof"))}
            save.setdefault("coach_pool", []).append(dict(cc, ex_role=role0))
            add_person_stint(save, r["name"], "Coaching ranks", "the league",
                             note="entering the coaching pipeline")
            continue
        role_label, icon, verb = _SECOND_CAREER_ROLES[kind]
        add_person_stint(save, r["name"], role_label, "the league",
                         note="second career after football")
        _tl(save, save.get("season", 1), "staff", icon,
            (str(r.get("pos", "")) + " " + str(r.get("name", ""))).strip() + " " + verb,
            ("A Hall of Famer" if r.get("hof") else "A respected veteran")
            + " begins his post-playing career.")
    _prune_people(save)


def _record_champion_bench(save, champ_team):
    """If an AI club wins the title with a former-player head coach, the world
    remembers — the loudest continuity payoff, extra loud if he was YOURS."""
    if not champ_team or champ_team.get("id") == save.get("current_team_id"):
        return
    hc = (champ_team.get("staff") or {}).get("head_coach")
    if not isinstance(hc, dict):
        return
    e = (save.get("people") or {}).get(_person_key(hc.get("name", "")))
    if not e or not e.get("former_player"):
        return
    fp = e["former_player"]
    add_person_stint(save, hc["name"], "Head Coach \u2014 League Champion",
                     champ_team["full"], note="won the title as a head coach", milestone=True)
    pos = str(fp.get("pos", "")).strip()
    if e.get("your_alum"):
        head = (pos + " " + hc["name"]).strip() + " wins it all as a head coach"
        sub = ("The " + (pos or "player") + " you developed just lifted the trophy as "
               + champ_team["full"] + " head coach. That one stings and shines.")
    else:
        head = (pos + " " + hc["name"]).strip() + " goes from the field to a title"
        sub = ("A former " + (pos or "player") + " wins the championship as "
               + champ_team["full"] + " head coach.")
    _tl(save, save.get("season", 1), "hof", "\U0001F3C6", head, sub)


def people_report(save):
    """Where they are now: your alumni's second acts, the milestone movers,
    and the notable Hall-of-Fame names spread across the league."""
    reg = list((save.get("people") or {}).values())
    tracked = [e for e in reg if e.get("former_player") and e.get("current")
               and (e.get("current") or {}).get("role") not in (None, "Coaching ranks", "Player")]
    def _peak(e):
        return int((e.get("former_player") or {}).get("peak", 0) or 0)
    alumni = sorted([e for e in tracked if e.get("your_alum")], key=lambda e: -_peak(e))
    milestones = sorted([e for e in tracked if e.get("milestone")], key=lambda e: -_peak(e))
    notable = sorted([e for e in tracked if e.get("hof") and not e.get("your_alum")],
                     key=lambda e: -_peak(e))
    return {"alumni": alumni[:12], "milestones": milestones[:10],
            "notable": notable[:12], "total": len(tracked)}


# --------------------------------------------------------------------------- #
# THE EXECUTIVE LADDER — the front-office half of the People machine. Every AI
# club has a GM; the league has a Commissioner; and over the decades people
# climb: front-office/scouting second-careers -> Assistant GM -> GM ->
# President of Football Ops -> (rarely) Commissioner. Accomplished builders
# retire into the Executive Hall next to the great GMs you retire yourself.
# --------------------------------------------------------------------------- #
def _gen_exec(rng, rank="GM", from_person=None):
    band = {"Personnel Director": (48, 70), "Assistant GM": (52, 74),
            "GM": (58, 82), "President of Football Ops": (66, 86)}.get(rank, (55, 78))
    rating = int(rng.triangular(band[0], band[1], (band[0] + band[1]) // 2))
    if from_person is not None:
        fp = from_person.get("former_player") or {}
        rating = max(rating, min(86, 52 + int(fp.get("peak", 70) or 70) // 3))
    age = rng.randint(42, 60) if rank in ("GM", "President of Football Ops") else rng.randint(34, 50)
    return {"name": (from_person or {}).get("name") or _gen_name(rng),
            "rank": rank, "rating": rating, "age": age, "tenure": 0,
            "former_player": (from_person or {}).get("former_player")}


def ensure_ai_executives(save):
    """Every rival club gets a GM; the league gets a Commissioner. Returns True
    if anything changed so the caller can persist once."""
    changed = False
    uid = save.get("current_team_id")
    for t in save.get("teams", []):
        if t["id"] == uid:
            continue
        ex = t.setdefault("exec", {})
        if not isinstance(ex.get("gm"), dict):
            rng = _rng(int(save.get("seed", 1) or 1) + abs(hash(str(t["id"]) + "gm")) % 99991)
            ex["gm"] = _gen_exec(rng, "GM")
            changed = True
    if not isinstance(save.get("commissioner"), dict):
        rng = _rng(int(save.get("seed", 1) or 1) + 90210)
        save["commissioner"] = {"name": _gen_name(rng), "since": save.get("season", 1),
                                "age": rng.randint(54, 64)}
        changed = True
    return changed


def _retire_exec(save, ex, team_full):
    if int(ex.get("tenure", 0) or 0) >= 8 and int(ex.get("rating", 0) or 0) >= 76:
        rec = {"name": ex["name"], "retired": save.get("season", 1),
               "tier": "Front-Office Builder", "score": int(ex.get("rating", 0) or 0),
               "grade": _rating_to_grade(int(ex.get("rating", 0) or 0)),
               "seasons": int(ex.get("tenure", 0) or 0), "record": "\u2014", "winpct": 0.0,
               "titles": 0, "playoffs": 0, "money": 0, "jobs": 1,
               "case": [str(ex.get("tenure", 0)) + " yrs in the chair",
                        "last with " + team_full,
                        "rose from " + str((ex.get("former_player") or {}).get("pos", "the ranks"))
                        if ex.get("former_player") else "career football man"],
               "hof": True}
        hall = save.setdefault("executive_hall", [])
        if not any(h.get("name") == rec["name"] and h.get("retired") == rec["retired"] for h in hall):
            hall.insert(0, rec)
        save["executive_hall"] = hall[:20]
    if ex.get("former_player"):
        add_person_stint(save, ex["name"], "Retired executive", team_full,
                         note="stepped away from football ops")


def run_executive_carousel(save, rng):
    """One offseason of front-office movement across the league."""
    ensure_ai_executives(save)
    uid = save["current_team_id"]
    pool = save.setdefault("exec_pool", [])
    prez_pool = save.setdefault("president_pool", [])
    log = []
    # former players in FO/scouting second careers step onto the exec ladder
    for e in list((save.get("people") or {}).values()):
        cur = e.get("current") or {}
        if (e.get("former_player") and cur.get("team") == "the league"
                and cur.get("role") in ("Front Office", "Scout")
                and rng.random() < 0.25):
            cand = _gen_exec(rng, "Assistant GM", from_person=e)
            pool.append(cand)
            add_person_stint(save, e["name"], "Assistant GM", "the league",
                             note="moves into football operations")
    for t in save["teams"]:
        if t["id"] == uid:
            continue
        ex = t.setdefault("exec", {})
        gm = ex.get("gm")
        if isinstance(gm, dict):
            gm["age"] = int(gm.get("age", 50) or 50) + 1
            gm["tenure"] = int(gm.get("tenure", 0) or 0) + 1
            drift = rng.randint(0, 2) if gm["age"] <= 54 else -rng.randint(0, 2)
            gm["rating"] = max(45, min(92, int(gm.get("rating", 60) or 60) + drift))
            if gm["tenure"] >= 8 and gm["rating"] >= 78 and rng.random() < 0.18:
                prez = dict(gm, rank="President of Football Ops")
                prez_pool.append(prez)
                add_person_stint(save, gm["name"], "President of Football Ops", t["full"],
                                 note="promoted to president", milestone=bool(gm.get("former_player")))
                log.append({"scope": t["full"], "role": "President", "name": gm["name"],
                            "why": "promoted from GM"})
                ex["gm"] = None
            elif gm["age"] >= 70 or (gm["age"] >= 64 and rng.random() < (gm["age"] - 60) * 0.06):
                _retire_exec(save, gm, t["full"])
                log.append({"scope": t["full"], "role": "GM", "name": gm["name"],
                            "why": "retired at " + str(gm["age"])})
                ex["gm"] = None
        if not isinstance(ex.get("gm"), dict):
            hire, why = None, ""
            if pool and rng.random() < 0.6:
                idx = max(range(len(pool)), key=lambda i: pool[i].get("rating", 0))
                hire = pool.pop(idx)
                hire["rank"], hire["tenure"] = "GM", 0
                why = ("a former player earns a GM job" if hire.get("former_player")
                       else "hired off the executive market")
            if hire is None:
                hire = _gen_exec(rng, "GM")
                why = "a new name gets the job"
            ex["gm"] = hire
            if hire.get("former_player"):
                add_person_stint(save, hire["name"], "GM", t["full"],
                                 note="named general manager", milestone=True)
                _tl(save, save.get("season", 1), "staff", "\U0001F9ED",
                    hire["name"] + " named GM of the " + t["full"],
                    "A former player is now running a franchise's football operations.")
            log.append({"scope": t["full"], "role": "GM", "name": hire["name"], "why": why})
    com = save.get("commissioner")
    if isinstance(com, dict) and not save.get("gm", {}).get("is_commissioner"):
        com["age"] = int(com.get("age", 58) or 58) + 1
        if com["age"] >= 72 or (com["age"] >= 66 and rng.random() < 0.15):
            new = (max(prez_pool, key=lambda p: p.get("rating", 0)) if prez_pool
                   else _gen_exec(rng, "President of Football Ops"))
            if new in prez_pool:
                prez_pool.remove(new)
            save["commissioner"] = {"name": new["name"], "since": save.get("season", 1),
                                    "age": max(56, int(new.get("age", 60) or 60))}
            add_person_stint(save, new["name"], "Commissioner", "the league",
                             note="elected league commissioner", milestone=True)
            _tl(save, save.get("season", 1), "hof", "\u2696",
                new["name"] + " elected league Commissioner",
                "The owners choose a new steward for the whole league.")
            log.append({"scope": "League", "role": "Commissioner", "name": new["name"],
                        "why": "elected"})
    save["exec_pool"] = pool[-20:]
    save["president_pool"] = prez_pool[-12:]
    save["exec_carousel_log"] = log[:20]
    _prune_people(save)


def exec_report(save):
    """League front offices + the commissioner, for the League tab."""
    uid = save.get("current_team_id")
    rows = []
    for t in sorted(save.get("teams", []), key=lambda x: x.get("full", "")):
        if t["id"] == uid:
            rows.append({"team": t["full"], "you": True,
                         "gm": save["gm"].get("name", "You") + " — you"})
        else:
            gm = (t.get("exec") or {}).get("gm") or {}
            tag = ""
            if gm.get("former_player"):
                tag = " (former " + str(gm["former_player"].get("pos", "player")) + ")"
            rows.append({"team": t["full"], "you": False,
                         "gm": (gm.get("name", "\u2014") + " (" + str(gm.get("rating", "?")) + ")" + tag)})
    return {"rows": rows, "commissioner": save.get("commissioner"),
            "log": save.get("exec_carousel_log", [])}


# --------------------------------------------------------------------------- #
# HIREABLE ALUMNI — bring a retired legend back into YOUR front office. Notable
# registry people (your alumni + Hall-of-Fame former players in scouting/FO/
# exec second careers) can be hired into your Head Scout / Analytics / Medical
# chairs, carrying a rating from their career and a continuity stint.
# --------------------------------------------------------------------------- #
_ALUMNI_SLOTS = {"head_scout": "Head of Scouting", "head_analytics": "Head of Analytics",
                 "head_medical": "Head of Medical"}


def _alumnus_rating(e):
    fp = e.get("former_player") or {}
    return max(48, min(84, 44 + int(fp.get("peak", 70) or 70) // 3
                       + (6 if e.get("hof") else 0)))


def alumni_front_office_market(save):
    """Notable people you could bring into your front office right now."""
    out = []
    for e in (save.get("people") or {}).values():
        if not e.get("former_player"):
            continue
        cur = e.get("current") or {}
        if not (e.get("your_alum") or e.get("hof")):
            continue
        if cur.get("role") in ("GM", "President of Football Ops", "Commissioner",
                               "Head Coach", "OC", "DC"):
            continue  # he's got a bigger job already
        out.append({"name": e["name"], "pos": (e.get("former_player") or {}).get("pos", ""),
                    "hof": bool(e.get("hof")), "alum": bool(e.get("your_alum")),
                    "rating": _alumnus_rating(e),
                    "doing": cur.get("role", "out of football")})
    out.sort(key=lambda x: (-x["rating"], not x["alum"]))
    return out[:12]


def hire_alumnus(save, name, role):
    if role not in _ALUMNI_SLOTS:
        return False, "That's not a front-office chair."
    e = (save.get("people") or {}).get(_person_key(name))
    if not e or not e.get("former_player"):
        return False, "No such alumnus is available."
    rating = _alumnus_rating(e)
    cost = staff_cost(rating)
    b = _business(save)
    if b["cash"] < cost:
        return False, "Bringing " + name + " aboard costs $" + str(cost) + "M - you have $" + str(b["cash"]) + "M."
    b["cash"] = round(b["cash"] - cost, 1)
    fp = e.get("former_player") or {}
    save.setdefault("staff", {})[role] = {
        "name": name, "rating": rating,
        "age": min(64, 34 + int(fp.get("seasons", 6) or 6)),
        "former_player": fp, "alumnus_hire": True,
        "ped": {"label": "Franchise legend" if e.get("your_alum") else "Former player",
                "tree": "Front office", "mentor": "the game itself", "experience": 0,
                "rep": max(40, min(92, 40 + int(fp.get("peak", 70) or 70) // 2)),
                "stops": [{"team": "Player", "role": str(fp.get("pos", "")), "years": int(fp.get("seasons", 0) or 0)}],
                "pros": 0, "playoffs": 0, "rings": 0}}
    add_person_stint(save, name, _ALUMNI_SLOTS[role], current_team(save).get("full", "your club"),
                     note="hired into your front office", milestone=bool(e.get("your_alum")))
    _tl(save, save.get("season", 1), "staff", "\U0001F91D",
        name + " joins your front office as " + _ALUMNI_SLOTS[role],
        ("A player you once had is back in the building." if e.get("your_alum")
         else "A respected former player joins your staff."))
    write_save(save)
    return True, name + " hired as " + _ALUMNI_SLOTS[role] + " (" + str(rating) + " OVR) for $" + str(cost) + "M."


def run_coaching_carousel(save, rng):
    """One offseason of league-wide staff movement. Runs at season end."""
    ensure_ai_staffs(save)
    uid = save["current_team_id"]
    pool = save.setdefault("coach_pool", [])
    log = []
    order = {s["id"]: i for i, s in enumerate(save.get("standings_cache", []))}
    n = max(8, len(order) or len(save["teams"]))
    for t in save["teams"]:
        if t["id"] == uid:
            continue
        staff = t.setdefault("staff", {})
        for role in _AI_STAFF_ROLES:                       # age, drift, retire
            c = staff.get(role)
            if not isinstance(c, dict):
                continue
            c["age"] = int(c.get("age", 48) or 48) + 1
            drift = (rng.randint(0, 2) if c["age"] <= 42 else
                     rng.randint(-1, 1) if c["age"] <= 55 else -rng.randint(0, 2))
            c["rating"] = max(40, min(95, int(c.get("rating", 55) or 55) + drift))
            if c["age"] >= 70 or (c["age"] >= 61 and rng.random() < (c["age"] - 58) * 0.05):
                log.append({"team": t["full"], "role": _AI_ROLE_LABEL[role],
                            "out": c["name"], "in": "", "why": "retired at " + str(c["age"])})
                staff[role] = None
        rank = order.get(t["id"], n // 2)                  # bad seasons cost jobs
        if rank >= n - 8 and rng.random() < 0.45:
            role = rng.choice(_AI_STAFF_ROLES)
            c = staff.get(role)
            if isinstance(c, dict):
                pool.append(dict(c, ex_role=role, fired_by=t["full"]))
                log.append({"team": t["full"], "role": _AI_ROLE_LABEL[role],
                            "out": c["name"], "in": "", "why": "fired after a lost season"})
                staff[role] = None
        for role in _AI_STAFF_ROLES:                       # fill the chairs
            if staff.get(role):
                continue
            hire, why = None, ""
            if role == "head_coach":                       # the coaching-tree chain
                cands = [r for r in ("off_coord", "def_coord")
                         if isinstance(staff.get(r), dict) and staff[r].get("rating", 0) >= 68]
                if cands and rng.random() < 0.5:
                    src_role = rng.choice(cands)
                    hire = dict(staff[src_role])
                    staff[src_role] = None
                    why = "promoted from " + _AI_ROLE_LABEL[src_role]
            if hire is None and pool and rng.random() < 0.6:
                hire = pool.pop(rng.randrange(len(pool)))
                was_user = hire.pop("ex_user", False)
                hire.pop("ex_role", None)
                why = "hired off the carousel"
                if was_user:
                    why = "your former coach lands on his feet"
                    _tl(save, save.get("season", 1), "staff", "\U0001F501",
                        (hire.get("name", "A coach")) + " hired as " + t["full"] + " " + _AI_ROLE_LABEL[role],
                        "A coach from your old staff resurfaces across the league.")
            if hire is None:
                hire = _gen_ai_coach(rng, role)
                mentor = next((staff[r]["name"] for r in _AI_STAFF_ROLES
                               if isinstance(staff.get(r), dict)), None)
                if mentor and hire.get("ped"):
                    hire["ped"]["mentor"] = mentor         # the tree grows
                why = "up-and-comer gets his shot"
            staff[role] = _fit_role(hire, role, rng)
            if staff[role].get("former_player"):
                is_hc = role == "head_coach"
                add_person_stint(save, staff[role]["name"], _AI_ROLE_LABEL[role], t["full"],
                                 note=("head coach of " + t["full"] if is_hc else why),
                                 milestone=is_hc)
                if is_hc:
                    fp = staff[role]["former_player"]
                    alum = (save.get("people") or {}).get(
                        _person_key(staff[role]["name"]), {}).get("your_alum")
                    _tl(save, save.get("season", 1), "staff", "\U0001F3AF",
                        (str(fp.get("pos", "")) + " " + staff[role]["name"]).strip()
                        + " named head coach of the " + t["full"],
                        ("A player you once had now runs a franchise." if alum
                         else "A former player takes over a sideline as head coach."))
            log.append({"team": t["full"], "role": _AI_ROLE_LABEL[role],
                        "out": "", "in": staff[role]["name"], "why": why})
    save["coach_pool"] = pool[-24:]
    save["carousel_log"] = log[:24]


# --------------------------------------------------------------------------- #
# Owner DIRECTIVES — the mandate beyond wins. Every archetype wants something
# different from your year, it's issued at the offseason, and the verdict
# lands on your trust at season's end.
# --------------------------------------------------------------------------- #
OWNER_DIRECTIVES = {
    "Cheap": [
        {"key": "profit", "target": 20,
         "text": "Run this club in the black — I want a ${target}M revenue season. Wins are optional; margins aren't."},
        {"key": "payroll", "target": 330,
         "text": "Keep the cap sheet under ${target}M. I'm not paying luxury prices to lose football games."},
    ],
    "Impatient": [
        {"key": "playoffs", "text": "Playoffs. This season. I don't want to hear about windows."},
        {"key": "wins", "text": "Ten wins minimum. Count them out loud if it helps."},
    ],
    "Meddling": [
        {"key": "draft_pos", "text": "I watch the games too — draft a {pos} early. Round one or two."},
        {"key": "splash", "text": "Sign somebody this town has heard of. A real free agent — $10M a year or better."},
    ],
    "Legacy": [
        {"key": "keep_star", "text": "{star} IS this franchise. He retires here — no trades, no cuts. Understood?"},
        {"key": "develop", "text": "Build through the draft like this club always has — I want the young ones starting."},
    ],
    "Billionaire": [
        {"key": "splash", "text": "Make a splash. Premium free agent, $10M-plus — I didn't buy this team to shop clearance."},
        {"key": "wins", "text": "I expect a double-digit win season. My other holdings deliver; so will this one."},
    ],
    "Hands-Off": [],
}


def _issue_owner_directive(save):
    team = current_team(save)
    pool = OWNER_DIRECTIVES.get(team["owner"]["type"], [])
    rng = _rng(save["seed"] + save.get("season", 1) * 313)
    if not pool or rng.random() < 0.25:
        save.pop("owner_directive", None)
        return
    d = dict(rng.choice(pool))
    if d["key"] == "draft_pos":
        needs = team_needs(save)
        d["pos"] = needs[0]["pos"] if needs else "QB"
        d["text"] = d["text"].format(pos=d["pos"])
    elif d["key"] == "keep_star":
        star = max(team["roster"], key=lambda p: p["overall"])
        d["pid"], d["star"] = star["id"], star["name"]
        d["text"] = d["text"].format(star=star["name"])
    elif "target" in d:
        d["text"] = d["text"].format(target=d["target"])
    d["season"] = save.get("season", 1)
    save["owner_directive"] = d
    save["season_flags"] = {}
    _tl(save, d["season"], "owner", "\U0001F5D2",
        "The owner's directive for the year", d["text"])


def _evaluate_owner_directive(save, rec, made_playoffs):
    d = save.pop("owner_directive", None)
    if not d:
        return
    team = current_team(save)
    flags = save.get("season_flags") or {}
    k = d.get("key")
    ok = False
    if k == "profit":
        ok = _business(save).get("last_revenue", 0) >= d.get("target", 20)
    elif k == "payroll":
        ok = cap_used(team) <= d.get("target", 330)
    elif k == "playoffs":
        ok = made_playoffs
    elif k == "wins":
        ok = rec.get("w", 0) >= 10
    elif k == "splash":
        ok = bool(flags.get("splash_fa"))
    elif k == "draft_pos":
        ok = any(x.get("pos") == d.get("pos") and int(x.get("round", 9) or 9) <= 2
                 for x in (save.get("last_draft_log") or []))
    elif k == "keep_star":
        ok = any(p["id"] == d.get("pid") for p in team["roster"])
    elif k == "develop":
        ok = int(flags.get("young_starters", 0) or 0) >= 3
    delta = 6 if ok else -8
    save["gm"]["owner_trust"] = max(0, min(100, save["gm"]["owner_trust"] + delta))
    _tl(save, save.get("season", 1), "owner", "\u2705" if ok else "\u274C",
        ("Directive delivered — the owner noticed (+6 trust)" if ok
         else "Directive failed — the owner noticed (\u22128 trust)"), d["text"])
    save["season_flags"] = {}


# --------------------------------------------------------------------------- #
# LEAGUE POLITICS — once a year a proposal comes to the owners' table. Every
# archetype leans a way, your vote counts, and a respected GM sways the room.
# --------------------------------------------------------------------------- #
LEAGUE_PROPOSALS = [
    {"key": "cap_up", "title": "Raise the salary cap by $15M",
     "blurb": "More money for everyone's stars — and everyone's mistakes.",
     "yes": {"Billionaire": .8, "Meddling": .6, "Impatient": .6, "Hands-Off": .5, "Legacy": .45, "Cheap": .15}},
    {"key": "seeds_up", "title": "Expand the playoffs by one seed per conference",
     "blurb": "Two more markets alive in December. Purists hate it; accountants love it.",
     "yes": {"Billionaire": .7, "Cheap": .7, "Meddling": .55, "Hands-Off": .5, "Impatient": .5, "Legacy": .3}},
    {"key": "rev_share", "title": "Boost small-market revenue sharing",
     "blurb": "The little markets want a bigger slice of the big markets' pie.",
     "yes": {"Legacy": .7, "Hands-Off": .6, "Cheap": .55, "Impatient": .5, "Meddling": .4, "Billionaire": .25}},
    {"key": "intl_games", "title": "Create an international games package",
     "blurb": "More global branding, more travel headaches, more league money.",
     "yes": {"Billionaire": .75, "Meddling": .62, "Hands-Off": .52, "Impatient": .5, "Legacy": .4, "Cheap": .35}},
    {"key": "deadline_late", "title": "Move the trade deadline back two weeks",
     "blurb": "Contenders want more time to buy; traditionalists hate the churn.",
     "yes": {"Impatient": .7, "Billionaire": .65, "Meddling": .58, "Hands-Off": .48, "Cheap": .42, "Legacy": .32}},
    {"key": "practice_slots", "title": "Expand practice squads by two spots",
     "blurb": "Development staffs want more young players in the building.",
     "yes": {"Legacy": .65, "Hands-Off": .62, "Cheap": .58, "Meddling": .48, "Impatient": .45, "Billionaire": .45}},
    {"key": "expansion_study", "title": "Authorize an expansion study",
     "blurb": "Portland, San Antonio, and other markets want into the room. This starts the process.",
     "yes": {"Billionaire": .72, "Cheap": .64, "Meddling": .56, "Hands-Off": .5, "Impatient": .44, "Legacy": .28}},
]


def propose_league_vote(save):
    """Bring one proposal to the annual owners' meeting (some years are quiet)."""
    if save.get("league_vote"):
        return
    rng = _rng(save["seed"] + save.get("season", 1) * 419)
    eligible = [p for p in LEAGUE_PROPOSALS
                if not (p["key"] == "seeds_up" and playoff_seeds(save) >= 8)
                and not (p["key"] == "rev_share" and save.get("rev_share"))]
    rules = save.setdefault("league_rules", {})
    eligible = [p for p in eligible
                if not (p["key"] == "intl_games" and rules.get("international_games"))
                and not (p["key"] == "deadline_late" and int(rules.get("trade_deadline_week", TRADE_DEADLINE_SOLO) or TRADE_DEADLINE_SOLO) >= TRADE_DEADLINE_SOLO + 2)
                and not (p["key"] == "practice_slots" and int(rules.get("practice_squad_slots", 12) or 12) >= 14)
                and not (p["key"] == "expansion_study" and rules.get("expansion_study"))]
    if not eligible or rng.random() < 0.30:
        return
    save["league_vote"] = dict(rng.choice(eligible), season=save.get("season", 1))


def resolve_league_vote(save, user_vote="abstain"):
    """Tally the room: 31 owners lean by archetype, you vote, and a respected
    GM swings a fence-sitter or two. 17 yeses carries it."""
    v = save.pop("league_vote", None)
    if not v:
        return False, "There is no proposal on the table."
    rng = _rng(save["seed"] + int(v.get("season", 1)) * 421)
    yes = 0
    for t in save["teams"]:
        if t["id"] == save["current_team_id"]:
            continue
        if rng.random() < v.get("yes", {}).get(t["owner"]["type"], 0.5):
            yes += 1
    rep = int(save["gm"].get("reputation", 50) or 50)
    sway = 2 if rep >= 70 else 1 if rep >= 55 else 0
    if user_vote == "for":
        yes += 1 + sway
    elif user_vote == "against":
        yes = max(0, yes - sway)
    league_size = max(1, len(save.get("teams", [])) or LEAGUE_SIZE)
    yes = min(league_size, yes)
    no = max(0, league_size - yes)
    passed = yes > league_size // 2
    note = ""
    if passed:
        if v["key"] == "cap_up":
            save["cap_total"] = round(cap_total(save) + 15.0, 1)
            note = f"The cap rises to ${save['cap_total']:.0f}M next season."
        elif v["key"] == "seeds_up":
            save["playoff_seeds"] = min(8, playoff_seeds(save) + 1)
            note = f"{save['playoff_seeds']} clubs per conference make the playoffs now."
        elif v["key"] == "rev_share":
            save["rev_share"] = True
            note = "Small markets get a bigger slice of league revenue."
        elif v["key"] == "intl_games":
            save.setdefault("league_rules", {})["international_games"] = True
            note = "International games enter the annual schedule package."
        elif v["key"] == "deadline_late":
            save.setdefault("league_rules", {})["trade_deadline_week"] = TRADE_DEADLINE_SOLO + 2
            note = "The trade deadline moves later, giving contenders more time to buy."
        elif v["key"] == "practice_slots":
            save.setdefault("league_rules", {})["practice_squad_slots"] = 14
            note = "Practice squads expand to 14 slots."
        elif v["key"] == "expansion_study":
            save.setdefault("league_rules", {})["expansion_study"] = True
            city = max(save.get("expansion_candidates", []), key=lambda x: x.get("score", 0), default={"city": "Portland"})
            note = f"The league authorizes an expansion study led by {city['city']}."
    if user_vote in ("for", "against"):
        _rel_nudge(save, "league_office", 1 if passed else -1,
                   f"took a public position on {v['title'].lower()}")
    save.setdefault("vote_history", []).insert(0, {
        "season": v.get("season", 1), "title": v["title"], "yes": yes,
        "passed": passed, "your_vote": user_vote})
    save["vote_history"] = save["vote_history"][:20]
    _tl(save, v.get("season", 1), "owner", "\U0001F5F3",
        f"Owners' vote: {v['title']} — {'PASSES' if passed else 'FAILS'} {yes}-{no}",
        (note or "The proposal dies on the table.") + f" You voted {user_vote}.")
    write_save(save)
    return True, f"The vote {'passes' if passed else 'fails'}, {yes} for. {note}".strip()


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


# --------------------------------------------------------------------------- #
# ATTRIBUTE-DRIVEN SCHEME FIT (opt-in, save['sim_depth']). Each scheme leans on
# specific ATTRIBUTES, not just style labels: an Air Raid wants Deep Accuracy +
# Deep Threat + Speed. When Deep Sim is on, a player whose key attributes beat
# his overall sharpens the scheme fit and earns a small, bounded sim edge.
# --------------------------------------------------------------------------- #
SCHEME_KEY_ATTRS = {
    "Air Raid": {"QB": ["Deep Accuracy", "Arm Strength"], "WR": ["Deep Threat", "Speed", "Release"]},
    "West Coast": {"QB": ["Short Accuracy", "Awareness"], "WR": ["Route Running", "Hands"],
                   "TE": ["Route Running", "Hands"]},
    "Power Run": {"RB": ["Power", "Vision"], "OL": ["Run Block", "Strength"], "TE": ["Run Blocking", "Strength"]},
    "Spread": {"QB": ["Mobility", "Short Accuracy"], "WR": ["YAC", "Route Running"], "RB": ["Elusiveness", "Speed"]},
    "4-3 Front": {"DL": ["Pass Rush", "Finesse Moves"], "LB": ["Tackle", "Pursuit"]},
    "3-4 Front": {"DL": ["Run Defense", "Strength"], "LB": ["Pass Rush", "Hit Power"]},
    "Cover 3 Zone": {"CB": ["Zone Coverage", "Ball Skills"], "S": ["Range", "Coverage"]},
    "Blitz Heavy": {"DL": ["Pass Rush", "Power Moves"], "LB": ["Pass Rush", "Speed"], "CB": ["Man Coverage", "Press"]},
}


def _attr_fit_delta(player, keys):
    """How much a player's scheme-key attributes beat (or trail) his overall."""
    attrs = {a["attr"]: a["value"] for a in player_attributes(player)}
    if not attrs:
        return 0.0
    vals = [attrs[k] for k in keys if k in attrs]
    if not vals:
        return 0.0
    return (sum(vals) / len(vals)) - int(player.get("overall") or player.get("grade") or 60)


def attr_scheme_edge(save):
    """Opt-in bounded sim edge for a roster whose ATTRIBUTES fit the scheme."""
    if not save.get("sim_depth"):
        return 0.0
    team = current_team(save)
    oc, dc = _team_schemes(save)
    total, n = 0.0, 0
    for pos, slots in ROSTER.items():
        scheme = oc if pos in OFFENSE_POS else dc
        keys = SCHEME_KEY_ATTRS.get(scheme, {}).get(pos) if scheme else None
        if not keys:
            continue
        for pl in pos_depth(team, pos)[:slots]:
            total += _attr_fit_delta(pl, keys)
            n += 1
    if not n:
        return 0.0
    return round(max(-2.5, min(2.5, (total / n) * 0.12)), 2)


def set_sim_depth(save, on):
    save["sim_depth"] = bool(on)
    write_save(save)
    return True, ("Deep Sim ON \u2014 attributes now sharpen scheme fit and the game."
                  if save["sim_depth"] else
                  "Deep Sim OFF \u2014 back to overall-driven fit.")


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
    result = {"pct": max(25, min(99, pct)), "label": label, "scheme": scheme, "style": style}
    if save.get("sim_depth"):
        keys = SCHEME_KEY_ATTRS.get(scheme, {}).get(pos)
        if keys:
            adj = int(round(max(-8, min(8, _attr_fit_delta(p, keys))) * 0.6))
            if adj:
                result["pct"] = max(20, min(99, result["pct"] + adj))
                result["attr_adj"] = adj
    return result


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


# --------------------------------------------------------------------------- #
# STAFF CONTRACTS, CAP, A REAL FREE-AGENT MARKET, AND POACHING
# Coaches are on the books now: a yearly salary against a staff cap and a term
# that runs down each offseason. When a deal expires he hits the open market;
# your hire screen is that market -- the actual coaches shaken loose by the
# league carousel (fired, contracts up, retired players), not invented names.
# And you can pry an employed coordinator out of a rival building for a premium.
# --------------------------------------------------------------------------- #
STAFF_CAP_BY_MARKET = {"Large": 88.0, "Mid": 78.0, "Small": 70.0}


def staff_salary(rating):
    """Annual salary ($M/yr) a coach of this rating commands."""
    return round(0.4 + int(rating or 50) * 0.075, 1)


def staff_cap(save):
    return round(STAFF_CAP_BY_MARKET.get(current_team(save).get("market"), 58.0), 1)


def staff_committed(save):
    tot = 0.0
    for c in (save.get("staff") or {}).values():
        if isinstance(c, dict):
            con = c.get("contract") or {}
            tot += float(con.get("salary", staff_salary(c.get("rating", 55))))
    return round(tot, 1)


def staff_cap_room(save):
    return round(staff_cap(save) - staff_committed(save), 1)


def staff_cap_view(save):
    cap, used = staff_cap(save), staff_committed(save)
    return {"cap": cap, "used": used, "room": round(cap - used, 1),
            "pct": min(100, round(used / cap * 100)) if cap else 0}


def _staff_family(role):
    if role in ("off_coord", "qb_coach", "oline_coach"):
        return "off"
    if role in ("def_coord", "db_coach"):
        return "def"
    return role


def _pool_fits_role(e, role):
    """Can this shaken-loose coach credibly fill your open chair?"""
    ex = e.get("ex_role") or ("head_coach" if e.get("former_player") else "off_coord")
    if _staff_family(ex) == _staff_family(role):
        return True
    if role == "head_coach" and ex in ("off_coord", "def_coord"):
        return True
    if ex == "head_coach" and role in ("off_coord", "def_coord"):
        return True
    return False


def _avail_reason(base):
    """Why is this man on the market? -> (short reason, where he's from)."""
    if base.get("expired_from"):
        return "contract expired", base["expired_from"]
    if base.get("fired_by"):
        return "fired", base["fired_by"]
    if base.get("ex_user"):
        return "you moved on", "your former staff"
    if base.get("former_player"):
        return "retired player", "new to coaching"
    return "free agent", ""


def _prep_candidate(save, rng, role, base, fa):
    c = dict(base)
    if role in ("head_coach", "off_coord", "def_coord"):
        c = _fit_role(c, role, rng)
    elif _staff_family(base.get("ex_role") or role) != _staff_family(role):
        c.pop("system", None)
        c.pop("playbook", None)
    for k in ("expired_from", "fired_by", "ex_user", "ex_role", "roster_fit"):
        c.pop(k, None)
    c["id"] = "s%d" % rng.randint(100000, 999999)
    _backfill_staff_entry(save, role, c)
    c["role"] = role
    c["rating"] = int(c.get("rating", 55) or 55)
    c["ask"] = staff_salary(c["rating"])
    c["term"] = rng.randint(2, 4)
    reason, frm = _avail_reason(base) if fa else ("up-and-comer", "first big job")
    c["avail"], c["from"], c["fa"] = reason, frm, bool(fa)
    return c


def build_staff_market(save, rng):
    """The hire screen: real free agents from the league carousel that fit each
    chair, topped up with up-and-comers so every role has options."""
    pool = [e for e in (save.get("coach_pool") or []) if isinstance(e, dict)]
    market = {}
    for role, _, _ in STAFF_ROLES:
        cands, used = [], []
        for e in pool:
            if len(cands) >= 4:
                break
            if _pool_fits_role(e, role):
                cands.append(_prep_candidate(save, rng, role, e, fa=True))
                used.append(id(e))
        while len(cands) < 4:
            cands.append(_prep_candidate(save, rng, role, _gen_staff(rng, role), fa=False))
        cands.sort(key=lambda c: c.get("rating", 0), reverse=True)
        market[role] = cands
    return market


def _remove_from_pool(save, cand):
    pool = save.get("coach_pool")
    if not isinstance(pool, list):
        return
    name = (cand or {}).get("name")
    if name:
        save["coach_pool"] = [e for e in pool
                              if not (isinstance(e, dict) and e.get("name") == name)]


def ensure_staff_contracts(save):
    """Backfill contracts on hired staff and upgrade a pre-contract staff market
    to the FA-aware one. Idempotent; returns True if anything changed."""
    changed = False
    for role, c in (save.get("staff") or {}).items():
        if isinstance(c, dict) and not isinstance(c.get("contract"), dict):
            rng = _staff_rng(save, "contract", role, c.get("name", ""))
            c["contract"] = {"years": rng.randint(2, 3),
                             "salary": staff_salary(c.get("rating", 55))}
            changed = True
    mk = save.get("staff_market")
    stale = (not isinstance(mk, dict) or not mk
             or any(isinstance(cd, dict) and "ask" not in cd
                    for cands in mk.values() for cd in (cands or [])))
    if stale:
        save["staff_market"] = build_staff_market(
            save, _staff_rng(save, "market", save.get("season", 1)))
        changed = True
    return changed


def employed_coach_targets(save, role):
    """Rival coordinators/HCs you could try to poach into this chair."""
    if role not in ("head_coach", "off_coord", "def_coord"):
        return []
    uid = save.get("current_team_id")
    want = (["head_coach", "off_coord", "def_coord"] if role == "head_coach" else [role])
    out = []
    for t in save.get("teams", []):
        if t["id"] == uid:
            continue
        st = t.get("staff") or {}
        for tr in want:
            c = st.get(tr)
            if not isinstance(c, dict):
                continue
            rating = int(c.get("rating", 55) or 55)
            if rating < 58:
                continue
            out.append({"team_id": t["id"], "team": t["full"], "their_role": tr,
                        "role_label": _AI_ROLE_LABEL.get(tr, tr), "name": c.get("name", ""),
                        "rating": rating, "salary": round(staff_salary(rating) * 1.25, 1),
                        "system": c.get("system"),
                        "promo": role == "head_coach" and tr in ("off_coord", "def_coord")})
    out.sort(key=lambda x: x["rating"], reverse=True)
    return out[:8]


def poach_coach(save, role, team_id, their_role):
    """Try to pry an employed rival coach into your open chair. He can say no;
    if he comes, you pay a premium salary + a one-time fee and the rival reloads."""
    if role not in ("head_coach", "off_coord", "def_coord"):
        return False, "You can only poach a rival's head coach or coordinator."
    t = next((x for x in save.get("teams", []) if x["id"] == team_id), None)
    if not t:
        return False, "That club is not in your league."
    st = t.setdefault("staff", {})
    c = st.get(their_role)
    if not isinstance(c, dict):
        return False, "He is no longer with that club."
    rating = int(c.get("rating", 55) or 55)
    salary = round(staff_salary(rating) * 1.25, 1)         # premium to pry him loose
    incumbent = save.get("staff", {}).get(role)            # poaching into a filled chair replaces him
    freed = (float((incumbent.get("contract") or {}).get("salary", staff_salary(incumbent.get("rating", 55))))
             if isinstance(incumbent, dict) else 0.0)
    room = staff_cap_room(save) + freed
    if salary > room + 0.05:
        return False, ("Prying %s loose runs $%.1fM/yr and you'd have $%.1fM of staff-cap room."
                       % (c.get("name", "him"), salary, round(room, 1)))
    fee = round(salary * 0.8, 1)
    b = _business(save)
    if b["cash"] < fee:
        return False, "The poaching fee is $%.1fM - you have $%.1fM cash." % (fee, b["cash"])
    rng = _staff_rng(save, "poach", team_id, their_role, c.get("name", ""),
                     save.get("season", 1), len(save.get("timeline", []) or []))
    order = {s["id"]: i for i, s in enumerate(save.get("standings_cache", []))}
    n = max(8, len(order) or len(save.get("teams", [])))
    rank = order.get(team_id, n // 2)
    p = 0.55
    if role == "head_coach" and their_role in ("off_coord", "def_coord"):
        p += 0.25                                          # a promotion tempts
    if rank < n // 3:
        p -= 0.22                                          # leaving a winner is hard
    if rank >= n - 6:
        p += 0.12                                          # jump a sinking ship
    p += min(0.15, (save.get("gm", {}).get("reputation", 50) - 50) * 0.006)
    if rng.random() >= max(0.1, min(0.9, p)):
        _tl(save, save.get("season", 1), "staff", "\U0001F6AB",
            "%s turns you down" % c.get("name", "The coach"),
            "%s stays with the %s. A better situation - or a bigger offer - might change his mind."
            % (c.get("name", "He"), t["full"]))
        write_save(save)
        return False, "%s turned it down - he's staying with the %s." % (c.get("name", "He"), t["full"])
    b["cash"] = round(b["cash"] - fee, 1)
    hire = _fit_role(dict(c), role, rng)
    hire.pop("id", None)
    _backfill_staff_entry(save, role, hire)
    years = rng.randint(3, 4)
    entry = {"name": hire.get("name", ""), "rating": rating,
             "contract": {"years": years, "salary": salary}}
    for k in ("philosophy", "system", "style", "ped", "age", "former_player", "playbook",
              "ideology", "versatility", "temperament", "specialties", "struggles_with"):
        if k in hire:
            entry[k] = hire[k]
    if isinstance(incumbent, dict):                        # the man you replace hits the market
        inc = dict(incumbent)
        inc.pop("contract", None)
        save.setdefault("coach_pool", []).append(dict(inc, ex_user=True, ex_role=role))
    save.setdefault("staff", {})[role] = entry
    st[their_role] = _gen_ai_coach(rng, their_role)        # the rival scrambles to reload
    _tl(save, save.get("season", 1), "staff", "\U0001F3A3",
        "Poached %s from the %s" % (entry["name"], t["full"]),
        "You pried their %s out of the building - $%.1fM/yr for %dyr, plus a $%.1fM fee."
        % (_AI_ROLE_LABEL.get(their_role, their_role), salary, years, fee))
    write_save(save)
    return True, "Got him. %s is your new %s - $%.1fM/yr for %dyr." % (
        entry["name"], _ROLE_LABELS.get(role, role), salary, years)


def resign_staff(save, role, years=3):
    """Extend a coach before his deal runs out. Salary resets to his market rate
    now -- a raise if he's grown."""
    c = save.get("staff", {}).get(role)
    if not isinstance(c, dict):
        return False, "No one to re-sign there."
    years = max(1, min(5, int(years or 3)))
    salary = staff_salary(c.get("rating", 55))
    cur = float((c.get("contract") or {}).get("salary", salary))
    room = staff_cap_room(save) + cur                      # his old deal frees up
    if salary > room + 0.05:
        return False, "His new deal is $%.1fM/yr; you'd have only $%.1fM of room." % (salary, round(room, 1))
    c["contract"] = {"years": years, "salary": salary}
    _tl(save, save.get("season", 1), "staff", "✍️",
        "Re-signed %s" % c.get("name", ""),
        "%s stays as your %s - $%.1fM/yr for %dyr." % (
            c.get("name", ""), _ROLE_LABELS.get(role, role), salary, years))
    write_save(save)
    return True, "%s re-signed - $%.1fM/yr for %dyr." % (c.get("name", ""), salary, years)



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
        "scouting": round((_sr(s, "head_scout") - 50) * 0.6 + facility_scouting_bonus(save), 1),
        "development": 1 if coord_avg >= 65 else 0,
        "medical": _sr(s, "head_medical") + cond["durability"] + facility_medical_bonus(save),
        "analytics": _sr(s, "head_analytics") + facility_scouting_bonus(save),
        "conditioning": cond,
    }


def hire_staff(save, role, candidate_id):
    market = save.setdefault("staff_market", {})
    cand = next((c for c in market.get(role, []) if c["id"] == candidate_id), None)
    if not cand:
        return False, "That candidate is no longer available."
    salary = float(cand.get("ask") or staff_salary(cand.get("rating", 55)))
    incumbent = save.get("staff", {}).get(role)                # replacing frees his salary
    freed = (float((incumbent.get("contract") or {}).get("salary", staff_salary(incumbent.get("rating", 55))))
             if isinstance(incumbent, dict) else 0.0)
    room = staff_cap_room(save) + freed
    if salary > room + 0.05:
        return False, ("Signing %s costs $%.1fM/yr and you'd have $%.1fM of staff-cap room. "
                       "Free up a chair or move money first." % (cand["name"], salary, round(room, 1)))
    fee = round(salary * 0.5, 1)
    b = _business(save)
    if b["cash"] < fee:
        return False, "The signing bonus is $%.1fM - you have $%.1fM cash." % (fee, b["cash"])
    b["cash"] = round(b["cash"] - fee, 1)
    years = int(cand.get("term") or 3)
    entry = {"name": cand["name"], "rating": cand["rating"],
             "contract": {"years": years, "salary": salary}}
    for k in ("philosophy", "system", "style", "ped", "age", "former_player", "playbook",
              "ideology", "versatility", "temperament", "specialties", "struggles_with"):
        if k in cand:
            entry[k] = cand[k]
    if isinstance(incumbent, dict):                            # the man you replace hits the market
        inc = dict(incumbent)
        inc.pop("contract", None)
        save.setdefault("coach_pool", []).append(dict(inc, ex_user=True, ex_role=role))
    save.setdefault("staff", {})[role] = entry
    market[role] = [c for c in market.get(role, []) if c["id"] != candidate_id]
    _remove_from_pool(save, cand)
    write_save(save)
    tail = (" (replacing %s)" % incumbent.get("name", "")) if isinstance(incumbent, dict) else ""
    return True, "Signed %s (%s OVR) - $%.1fM/yr for %dyr%s." % (cand["name"], cand["rating"], salary, years, tail)


def fire_staff(save, role):
    c = save.get("staff", {}).pop(role, None)
    if isinstance(c, dict):
        c.pop("contract", None)
        save.setdefault("coach_pool", []).append(dict(c, ex_user=True, ex_role=role))
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
    expired = []
    for role, c in list(staff.items()):
        if not isinstance(c, dict):
            continue
        con = c.get("contract")
        if not isinstance(con, dict):
            c["contract"] = {"years": rng.randint(2, 3), "salary": staff_salary(c.get("rating", 55))}
            continue
        con["years"] = int(con.get("years", 2) or 2) - 1
        if con["years"] <= 0:
            expired.append((role, c))
    club = current_team(save).get("full", "your club")
    for role, c in expired:
        staff.pop(role, None)
        c.pop("contract", None)
        save.setdefault("coach_pool", []).append(dict(c, ex_role=role, ex_user=True, expired_from=club))
        _tl(save, save.get("season", 1), "staff", "📄",
            "%s %s's contract is up" % (_ROLE_LABELS.get(role, role), c.get("name", "")),
            "His deal expired and he hit the open market. Re-sign a coach in his last year to keep him.")
    save["staff_contract_expiries"] = [
        {"role": role, "label": _ROLE_LABELS.get(role, role), "name": c.get("name", "")}
        for role, c in expired]
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
        _coach_joins_rival(save, staff.pop(role, None), role, poach.get("rival", ""))
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
        _coach_joins_rival(save, staff.pop(role, None), role, poach.get("rival", ""))
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
    pool = [r for r in (save.get("retirements") or [])
            if int(r.get("peak", 0) or 0) >= 76
            and r.get("second_career") in (None, "coaching")]
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
        add_person_stint(save, cand["name"], "Coaching ranks", "the market",
                         note="entered the coaching market")
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


def _gen_prospect(rng, pos, season=1, seen=None):
    true_ovr = max(50, min(90, int(rng.triangular(52, 86, 64))))
    true_pot = min(99, true_ovr + int(rng.triangular(2, 26, 12)))
    bg = _gen_background(rng)
    ident = _gen_identity(rng, bg["hometown"], season, seen)
    return {"id": f"d{rng.randint(100000, 999999)}", **ident, **bg, "pos": pos,
            "age": rng.randint(21, 23), "true_ovr": true_ovr, "true_pot": true_pot,
            "dev": rng.choice(["Normal", "Normal", "Star", "Slow", "Late Bloomer"]),
            "style": _style_for(rng, pos),
            "combine": _gen_combine(rng, pos, true_ovr, true_pot),
            **_gen_human_profile(rng)}


def generate_draft_class(rng, season=1, seen=None):
    weighted = []
    for pos, cnt in ROSTER.items():
        weighted += [pos] * (cnt + 1)
    seen = seen if seen is not None else set()
    return [_gen_prospect(rng, rng.choice(weighted), season=season, seen=seen)
            for _ in range(DRAFT_CLASS)]


def _inject_bloodlines(save, rng, cls):
    """A retired great's son can enter the draft: same last name, same position,
    Jr./III suffix, and expectations he didn't ask for."""
    pool = [l for l in save.get("legacy_pool", [])
            if save.get("season", 1) - l.get("retired", 0) >= 2]
    if not pool or rng.random() > 0.5:
        return
    legacy = rng.choice(pool)
    save["legacy_pool"].remove(legacy)
    pr = next((x for x in cls if x["pos"] == legacy["pos"]), cls[0])
    suffix = "Jr." if rng.random() < 0.7 else "III"
    pr["first"], pr["last"] = legacy["first"], legacy["last"]
    pr["name"] = f"{legacy['first']} {legacy['last']} {suffix}"
    pr["legal_name"] = f"{legacy['first']} {pr.get('middle', legacy['first'])} {legacy['last']} {suffix}"
    pr["jersey_name"] = f"{legacy['first'][0]}. {legacy['last']} {suffix}"
    if suffix == "III":
        pr["nickname"] = pr.get("nickname") or "Trey"
    pr["legacy"] = {"parent": f"{legacy['first']} {legacy['last']}", "hof": legacy["hof"]}
    pr["true_pot"] = min(99, pr["true_pot"] + 3)      # bloodlines carry juice
    _tl(save, save.get("season", 1), "draft", "🩸",
        f"Bloodlines: {pr['name']} declares for the draft",
        f"Son of {'Hall of Famer' if legacy['hof'] else 'the great'} "
        f"{legacy['first']} {legacy['last']} — same position, same name, enormous expectations.")


def ensure_player_identities(save):
    """Backfill identity fields (middle, legal, jersey, maybe a nickname) onto
    players from before the identity engine — deterministic per player, and the
    display name is left alone. Then fix same-team display collisions by
    inserting middle initials. Returns True if anything changed."""
    changed = False
    containers = [t.get("roster", []) + t.get("practice_squad", [])
                  for t in save.get("teams", [])]
    containers.append(save.get("free_agents", []))
    for players in containers:
        for p in players:
            if p.get("legal_name") or not p.get("name"):
                continue
            rng = _rng(int(save.get("seed", 1) or 1) + sum(ord(c) for c in str(p.get("id", p["name"]))))
            parts = p["name"].split()
            p["first"], p["last"] = parts[0], parts[-1]
            middle = rng.choice(_FIRST_WEIGHTED)
            while middle == p["first"]:
                middle = rng.choice(_FIRST_WEIGHTED)
            p["middle"] = middle
            p["legal_name"] = f"{p['first']} {middle} {p['last']}"
            p["jersey_name"] = f"{p['first'][0]}. {p['last']}"
            if rng.random() < 0.10:
                p["nickname"] = rng.choice(NICKNAMES)
            changed = True
    if disambiguate_rosters(save):
        changed = True
    return changed


def disambiguate_rosters(save):
    """Two men, one display name, same team -> both pick up their middle
    initial ('Marcus A. Davis' / 'Marcus L. Davis')."""
    changed = False
    for t in save.get("teams", []):
        by_name = {}
        for p in t.get("roster", []):
            by_name.setdefault(p.get("name", ""), []).append(p)
        for name, group in by_name.items():
            if len(group) < 2 or not name:
                continue
            for p in group:
                mid = (p.get("middle") or "X")[0]
                first = p.get("first") or name.split()[0]
                last = p.get("last") or name.split()[-1]
                new = f"{first} {mid}. {last}"
                if p["name"] != new:
                    p["name"] = new
                    changed = True
    return changed


def league_names_seen(save):
    """Every display name already in this universe — new names must dodge them."""
    seen = set()
    for t in save.get("teams", []):
        for p in t.get("roster", []) + t.get("practice_squad", []):
            seen.add(p.get("name", ""))
            if p.get("first") and p.get("last"):
                seen.add(f"{p['first']} {p['last']}")
    for p in save.get("free_agents", []):
        seen.add(p.get("name", ""))
    seen.discard("")
    return seen


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
            "portrait_id": p.get("portrait_id"),
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


def ensure_draft_preview(save):
    """Generate next spring's incoming class so it's scoutable all season.
    Early grades are fuzzy; the Senior Bowl then shakes them up."""
    target = save.get("season", 1) + 1
    prev = save.get("draft_preview")
    if isinstance(prev, dict) and prev.get("season") == target and prev.get("class"):
        return False
    rng = _rng(save["seed"] + target * 131 + 17)
    cls = generate_draft_class(rng, season=target, seen=league_names_seen(save))
    _inject_bloodlines(save, rng, cls)
    acc = max(20, min(66, int(save["gm"]["ratings"].get("drafting", 50)) - 8))
    for p in cls:
        _scout(rng, p, acc)
        p["buzz"] = ""
    save["draft_preview"] = {"season": target, "class": cls, "senior_bowl_done": False}
    run_senior_bowl(save)
    return True


def run_senior_bowl(save):
    """The pre-draft all-star showcase: mid-tier prospects have the most to
    gain or lose. Risers climb the board; strugglers slide."""
    prev = save.get("draft_preview")
    if not isinstance(prev, dict) or prev.get("senior_bowl_done"):
        return
    cls = prev.get("class") or []
    if not cls:
        return
    rng = _rng(save["seed"] + int(prev.get("season", 1)) * 313 + 71)
    ranked = sorted(cls, key=lambda p: -p.get("grade", 0))
    pool = ranked[3:44] if len(ranked) > 44 else ranked[1:]
    rng.shuffle(pool)
    risers, fallers = [], []
    for p in pool[:14]:
        roll = rng.gauss(0, 1)
        if roll > 0.8:
            p["grade"] = min(99, int(p.get("grade", 60)) + rng.randint(2, 5))
            p["pot_grade"] = min(99, max(int(p.get("pot_grade", p["grade"])), p["grade"]))
            p["buzz"] = "Senior Bowl riser"
            risers.append({"name": p["name"], "pos": p["pos"], "grade": p["grade"],
                           "college": p.get("college", "")})
        elif roll < -0.9:
            p["grade"] = max(40, int(p.get("grade", 60)) - rng.randint(2, 5))
            p["buzz"] = "Struggled at the Senior Bowl"
            fallers.append({"name": p["name"], "pos": p["pos"], "grade": p["grade"],
                            "college": p.get("college", "")})
    prev["senior_bowl_done"] = True
    prev["senior_bowl"] = {"risers": risers, "fallers": fallers}


def college_pipeline_report(save):
    prev = save.get("draft_preview") or {}
    cls = prev.get("class") or []
    board = sorted(cls, key=lambda p: -p.get("grade", 0))[:24]
    top = [{"name": p["name"], "pos": p["pos"], "grade": p.get("grade", 0),
            "pot": p.get("pot_grade", p.get("grade", 0)), "college": p.get("college", ""),
            "hometown": p.get("hometown", ""), "buzz": p.get("buzz", ""),
            "legacy": p.get("legacy")} for p in board]
    sb = prev.get("senior_bowl") or {"risers": [], "fallers": []}
    return {"season": prev.get("season"), "top": top, "count": len(cls),
            "risers": sb.get("risers", []), "fallers": sb.get("fallers", [])}


def sign_udfa(save, pid):
    """Sign an undrafted prospect to your practice squad."""
    pool = save.get("udfa_pool") or []
    entry = next((u for u in pool if u.get("id") == pid), None)
    if not entry:
        return False, "That player has already signed elsewhere."
    team = current_team(save)
    ps = team.setdefault("practice_squad", [])
    cap = int((save.get("league_rules") or {}).get("practice_squad_slots", PS_MAX) or PS_MAX)
    if len(ps) >= cap:
        return False, "Your practice squad is full (" + str(cap) + ")."
    rookie = _make_rookie(entry.get("_full") or entry)
    rookie["practice"] = True
    ps.append(rookie)
    save["udfa_pool"] = [u for u in pool if u.get("id") != pid]
    write_save(save)
    return True, "Signed UDFA " + str(entry.get("pos", "")) + " " + str(entry.get("name", "")) + " to the practice squad."


def start_draft(save):
    if save.get("draft_pending"):
        return
    rng = _rng(save["seed"] + save["season"] * 77 + 13)
    preview = save.get("draft_preview")
    if (isinstance(preview, dict) and preview.get("season") == save.get("season")
            and preview.get("class")):
        cls = preview["class"]                         # the class you watched all season
        save.pop("draft_preview", None)                # consumed into the live draft
    else:
        cls = generate_draft_class(rng, season=save.get("season", 1), seen=league_names_seen(save))
        _inject_bloodlines(save, rng, cls)
    scout_bonus = 9 if save.get("weekly_ops", {}).get("scout") == "Draft Class" else 0   # scouts worked the class
    acc = max(20, min(94, save["gm"]["ratings"].get("drafting", 50) + staff_bonus(save)["scouting"] + scout_bonus))
    for p in cls:
        _scout(rng, p, acc)
    save["staff_market"] = build_staff_market(save, rng)   # the real market: fired coaches, expired deals, up-and-comers
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
    ensure_player_portraits(save)
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
    _draft = save.get("draft") or {}
    _undrafted = sorted([p for p in _draft.get("class", []) if not p.get("drafted")],
                        key=lambda p: -p.get("grade", 0))
    save["udfa_pool"] = [{"id": p["id"], "name": p["name"], "pos": p["pos"],
                          "grade": p.get("grade", 0), "pot_grade": p.get("pot_grade", p.get("grade", 0)),
                          "college": p.get("college", ""), "style": p.get("style", ""), "_full": p}
                         for p in _undrafted[:16]]
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
            changed = ensure_staff_contracts(save) or changed
            changed = ensure_fa_prior_stats(save) or changed
            changed = ensure_team_histories(save) or changed
            changed = ensure_player_identities(save) or changed
            changed = ensure_ai_staffs(save) or changed
            changed = ensure_ai_executives(save) or changed
            changed = sync_front_office_issues(save) or changed
            changed = ensure_city_economics(save) or changed
            changed = ensure_team_cultures(save) or changed
            changed = ensure_world_systems(save) or changed
            changed = bool(ensure_player_portraits(save)) or changed
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
        "staff_market": {},
        "business": {"cash": 95.0, "fan_happiness": 50, "stadium": 1, "facility": 1,
                     "facilities": {"training": 1, "medical": 1, "analytics": 1, "fan_experience": 1},
                     "ticket": "normal"},
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    _set_expectation(save)
    generate_front_office_issues(save)
    save["staff_market"] = build_staff_market(save, _rng(seed + 999))
    ensure_player_portraits(save)
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


def sync_front_office_issues(save):
    """Drop any stored roster-keyed nags (inherited problems, holdouts) about
    players no longer on your roster — traded, cut, or walked. These lists are
    snapshots that only rebuild at season end, so they otherwise go stale the
    moment you move a player. Returns True if anything changed."""
    try:
        ids = {p["id"] for p in current_team(save)["roster"]}
    except Exception:
        return False
    changed = False
    issues = save.get("front_office_issues")
    if issues:
        kept = [i for i in issues if (i.get("player") or {}).get("id") in ids]
        if len(kept) != len(issues):
            save["front_office_issues"] = kept
            changed = True
    holdouts = save.get("holdouts")
    if holdouts:
        kept = [h for h in holdouts if h.get("id") in ids]
        if len(kept) != len(holdouts):
            save["holdouts"] = kept
            changed = True
    iz = save.get("inseason")           # a pending AI offer for a player you've since dealt
    if iz and isinstance(iz.get("offer"), dict) and iz["offer"].get("want_id") not in ids:
        iz["offer"] = None
        changed = True
    return changed


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
    if cap_used(team) + fa["contract"]["aav"] > cap_total(save):
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
    if cap_used(team) + aav > cap_total(save):
        res.update(status="rejected", msg=f"That ${aav}M deal puts you over the cap.")
    elif aav >= accept_at:
        fa["contract"] = {"years": years, "aav": aav, "guaranteed": round(aav * 0.5, 1)}
        fa.pop("agent", None)
        fa.pop("demand", None)
        team["roster"].append(fa)
        save["free_agents"] = [p for p in save["free_agents"] if p["id"] != player_id]
        save["gm"]["nego_wins"] = save["gm"].get("nego_wins", 0) + (2 if aav <= demand_aav else 1)
        if aav >= 10:
            save.setdefault("season_flags", {})["splash_fa"] = True
        _owner_sign_react(save, fa["name"], fa["pos"], fa["overall"], aav)
        _rel_nudge(save, "agents", 2, f"closed a free-agent deal with {agent_name}")
        _rel_nudge(save, "locker_room", 1, f"added {fa['pos']} {fa['name']} to the room")
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
        _rel_nudge(save, "agents", -1, f"low offer frustrated {agent_name}")
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


def sign_fa_at_ask(save, pid):
    """One-click: sign a free agent at his asking price (meeting a counter if
    the agent throws one). Cap-checked via negotiate. Signable in-season and in
    the FA window — the quick way to grab help after an injury or a thin spot."""
    fa = next((p for p in save.get("free_agents", []) if p["id"] == pid), None)
    if not fa:
        return False, "That free agent already signed elsewhere."
    demand = fa.get("demand") or {}
    ask = round(float(demand.get("aav", fa["contract"]["aav"]) or fa["contract"]["aav"]), 1)
    years = int(demand.get("years", 3) or 3)
    res = negotiate(save, pid, years, ask)
    if res.get("status") == "countered" and res.get("counter"):
        res = negotiate(save, pid, res["counter"]["years"], res["counter"]["aav"])
    return res.get("status") == "accepted", res.get("msg", "Couldn't get it done.")


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
    cap_room = round(cap_total(save) - cap_used(t) + sc.get("cap_bonus", 0))
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
            **profile, "name": owner.get("name") or profile["name"],
            "age": owner.get("age"), "heir": owner.get("heir"),
            "industry": owner.get("industry"), "net_worth": owner.get("net_worth")}


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
    cap_room = round(cap_total(save) - cap_used(team), 1)
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
    room = cap_total(save) - cap_used(team) + p["contract"].get("aav", 0)   # his old deal frees up
    if aav > room:
        res.update(status="rejected", msg=f"That ${aav}M deal won't fit under the cap.")
    elif aav >= ask:
        was_dispute = bool(p.get("holdout") or p.get("trade_request"))
        p["contract"] = {"years": years, "aav": aav, "guaranteed": round(aav * 0.55, 1)}
        p.pop("agent", None)
        p.pop("holdout", None)
        p.pop("holdout_reason", None)
        p.pop("trade_request", None)
        p.pop("trade_reason", None)
        p["morale"] = min(99, p.get("morale", 75) + 12)
        save["gm"]["nego_wins"] = save["gm"].get("nego_wins", 0) + (2 if aav <= ask else 1)
        _owner_sign_react(save, p["name"], p["pos"], p["overall"], aav)
        _rel_nudge(save, "agents", 2, f"extended {p['pos']} {p['name']}")
        if was_dispute:
            _rel_nudge(save, "locker_room", 2, f"resolved {p['pos']} {p['name']}'s dispute")
        res.update(status="accepted", msg=f"Extension done — {p['name']} for {years}yr / ${aav}M.")
    elif aav >= ask * 0.9:
        why = (" " + context["reasons"][0]) if context["reasons"] else ""
        res.update(status="countered", counter={"years": years, "aav": ask},
                   msg=f"{p['agent']['name']} counters: {years}yr at ${ask}M.{why}")
    else:
        why = " ".join(context["reasons"][:2])
        res.update(status="rejected",
                   msg=f"{p['agent']['name']} rejects ${aav}M - he wants about ${ask}M/yr. {why}".strip())
        _rel_nudge(save, "agents", -1, f"extension talks with {p['pos']} {p['name']} went nowhere")
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
    _apply_role_expectations(save)
    return flagged


# --------------------------------------------------------------------------- #
# PLAYER ROLES — a title beyond the depth chart that sets an expectation. A guy
# labeled a Starter who loses his job sours; a Mentor accepts the bench and
# develops a young teammate; role players are content in their niche.
# --------------------------------------------------------------------------- #
PLAYER_ROLES = {
    "cornerstone": {"label": "Franchise Cornerstone", "expects": 0, "content": False, "leader": True,
                    "blurb": "The face of the franchise — expects to start and be built around."},
    "captain": {"label": "Captain", "expects": 1, "content": False, "leader": True,
                "blurb": "A locker-room leader who expects to play."},
    "starter": {"label": "Starter", "expects": 1, "content": False,
                "blurb": "Expects a starting job and sours if he loses it."},
    "rotational": {"label": "Rotational Player", "expects": 3, "content": True,
                   "blurb": "Happy in a rotation — no starter's ego."},
    "specialist": {"label": "Specialist", "expects": 99, "content": True,
                   "blurb": "A situational role player, content with his niche."},
    "mentor": {"label": "Mentor", "expects": 99, "content": True, "mentor": True,
               "blurb": "Accepts fewer snaps to develop a young teammate."},
    "bridge": {"label": "Bridge Starter", "expects": 1, "content": True,
               "blurb": "A stopgap starter who knows he's keeping the seat warm."},
    "prospect": {"label": "Developmental Prospect", "expects": 99, "content": True,
                 "blurb": "A project — wants developmental snaps, patient on the bench."},
}


def set_player_role(save, pid, role):
    for p in current_team(save)["roster"]:
        if p["id"] == pid:
            if role in PLAYER_ROLES:
                p["role"] = role
            elif role in ("", "none"):
                p.pop("role", None)
            else:
                return False, "Unknown role."
            write_save(save)
            return True, f"{p['name']} is now your {PLAYER_ROLES.get(role, {}).get('label', 'role player') if role in PLAYER_ROLES else 'unassigned'}."
    return False, "Player not found."


def _apply_role_expectations(save):
    """Yearly: a Starter/Cornerstone buried on the depth chart loses morale; content
    roles don't mind the bench."""
    team = current_team(save)
    for pos in ROSTER:
        for slot, p in enumerate(pos_depth(team, pos)):
            role = PLAYER_ROLES.get(p.get("role"))
            if role and not role.get("content") and slot > role.get("expects", 99):
                p["morale"] = max(15, p.get("morale", 70) - 7)   # his role expectation was broken


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
            "playoff_odds": playoff_odds, "cap_used": cap, "cap_total": cap_total(save),
            "starter_value": starter_value, "cap_eff": round(starter_value / max(1.0, cap), 2),
            "best": best, "overpays": overpays}


# --------------------------------------------------------------------------- #
# GridIron Quant Desk — the numbers guys, applied to YOUR team. Honest playoff
# odds by Monte-Carlo-ing the rest of the season through the real game model,
# plus your power rank + week-over-week movement and remaining strength of
# schedule. Leans into the Data Mode identity of the platform.
# --------------------------------------------------------------------------- #
def playoff_projection(save, sims=160):
    """Simulate the remaining schedule many times to get real playoff odds, a
    projected win total, most-likely seed, and division-title odds."""
    iz = save.get("inseason")
    if not iz:
        return None
    week = iz["week"]
    uid = save["current_team_id"]
    teams = {t["id"]: t for t in save["teams"]}
    staff_pw = staff_bonus(save)["power"]
    pw = {tid: power_rating(t) + (staff_pw if tid == uid else ai_coach_edge(t))
          for tid, t in teams.items()}
    base_wins = {tid: teams[tid]["record"]["w"] for tid in teams}
    remaining = [g for g in save["schedule"] if g["week"] >= week]
    conf_of = {tid: t["conference"] for tid, t in teams.items()}
    div_of = {tid: (t["conference"], t["division"]) for tid, t in teams.items()}
    my_conf, my_div = conf_of[uid], div_of[uid]
    conf_ids = [tid for tid in teams if conf_of[tid] == my_conf]
    div_ids = [tid for tid in teams if div_of[tid] == my_div]
    seeds = playoff_seeds(save)
    rng = _rng(save["seed"] + week * 104729 + 55)
    made = seed_sum = win_sum = div_made = 0
    seed_counts = {}
    for _ in range(sims):
        wins = dict(base_wins)
        for g in remaining:
            h, a = g["home"], g["away"]
            if _sim_game(rng, pw[h], pw[a]):
                wins[h] += 1
            else:
                wins[a] += 1
        win_sum += wins[uid]
        seed = sorted(conf_ids, key=lambda t: (wins[t], pw[t]), reverse=True).index(uid) + 1
        if seed <= seeds:
            made += 1
            seed_sum += seed
            seed_counts[seed] = seed_counts.get(seed, 0) + 1
        if sorted(div_ids, key=lambda t: (wins[t], pw[t]), reverse=True)[0] == uid:
            div_made += 1
    return {"playoff_odds": round(100 * made / sims), "proj_wins": round(win_sum / sims, 1),
            "proj_seed": round(seed_sum / made) if made else None,
            "likely_seed": max(seed_counts, key=seed_counts.get) if seed_counts else None,
            "div_odds": round(100 * div_made / sims),
            "games_left": len([g for g in remaining if uid in (g["home"], g["away"])])}


def quant_desk(save):
    """The weekly analytics panel: playoff odds, projected finish, power rank +
    movement, and how tough your remaining schedule is."""
    iz = save.get("inseason")
    if not iz:
        return None
    uid = save["current_team_id"]
    team = current_team(save)
    tmap = {t["id"]: t for t in save["teams"]}
    rank = save.get("power_rank", {}).get(uid)
    prev = save.get("power_rank_prev", {}).get(uid)
    delta = (prev - rank) if (rank and prev) else 0        # +ve = climbed the board
    powers = [power_rating(t) for t in save["teams"]]
    league_avg = sum(powers) / len(powers)
    week = iz["week"]
    rem_opps = [(g["away"] if g["home"] == uid else g["home"])
                for g in save["schedule"] if g["week"] >= week and uid in (g["home"], g["away"])]
    sos = round(sum(power_rating(tmap[o]) for o in rem_opps) / len(rem_opps), 1) if rem_opps else 0.0
    rec = team["record"]
    return {"rank": rank, "rank_delta": delta, "league_size": len(save["teams"]),
            "power": round(power_rating(team) + staff_bonus(save)["power"], 1),
            "league_avg": round(league_avg, 1), "record": f"{rec['w']}-{rec['l']}",
            "proj": playoff_projection(save), "sos": sos, "sos_vs_avg": round(sos - league_avg, 1)}


# --------------------------------------------------------------------------- #
# Business / stadium / budget - revenue funds staff + facility investment
# --------------------------------------------------------------------------- #
MARKET_MULT = {"Small": 0.85, "Mid": 1.0, "Large": 1.3}
# ticket level -> (attendance mult, fan-happiness delta/season, price-per-seat mult)
TICKET = {"low": (1.12, 1, 0.84), "normal": (1.0, 0, 1.0), "high": (0.9, -3, 1.18)}
VENUE_PRICING = {"low": {"label": "Low", "rev": 0.84, "fan": 1},
                 "normal": {"label": "Normal", "rev": 1.0, "fan": 0},
                 "high": {"label": "High", "rev": 1.16, "fan": -2}}
STADIUM_CAP = {1: 45, 2: 58, 3: 68, 4: 76, 5: 85}     # seats (thousands) by stadium level
SPONSOR_SLOTS = {
    "naming_rights": {"label": "Naming Rights", "base": 10.0, "years": 4},
    "uniform_partner": {"label": "Uniform Partner", "base": 5.0, "years": 3},
    "training_camp": {"label": "Training Camp Sponsor", "base": 3.0, "years": 2},
    "local_media": {"label": "Local Media Partner", "base": 2.5, "years": 2},
    "luxury_suites": {"label": "Luxury Suite Partner", "base": 4.0, "years": 3},
}
SPONSOR_BRANDS = ["CrownBank", "Apex Wireless", "Summit Auto", "Volt Energy", "Keystone Health",
                  "Harbor Hotels", "MetroAir", "IronGate Logistics", "BlueLine Foods", "Northstar Tech"]
DISTRICT_PROJECTS = {
    "parking": {"label": "Parking & Transit", "effect": "Easier access raises attendance and game-day revenue.", "cost": 12.0, "rev": 1.8, "fan": 1},
    "restaurants": {"label": "Restaurants", "effect": "Food and nightlife turn games into full-day events.", "cost": 16.0, "rev": 2.4, "fan": 1},
    "retail": {"label": "Retail Row", "effect": "Team stores and local shops boost merchandise spend.", "cost": 14.0, "rev": 2.0, "fan": 0},
    "hotels": {"label": "Hotels", "effect": "Traveling fans and premium weekends expand the market.", "cost": 22.0, "rev": 3.1, "fan": 1},
    "entertainment": {"label": "Entertainment Plaza", "effect": "Concerts and events keep the district alive year-round.", "cost": 26.0, "rev": 3.8, "fan": 2},
}
CITY_MARKET_BASE = {
    "Small": {"population": (0.6, 2.5), "income": (84, 112), "corporate": (28, 62), "media": (32, 60)},
    "Mid": {"population": (1.5, 5.5), "income": (92, 122), "corporate": (45, 78), "media": (48, 76)},
    "Large": {"population": (4.5, 18.0), "income": (102, 138), "corporate": (65, 98), "media": (72, 99)},
}


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
    city_bump = round((city_economy_score(save, team["id"]) - 50) / 18.0)
    fill = (58 + (b["fan_happiness"] - 50) * 0.55 + diff * 1.6 + market_bump
            + city_bump + (am - 1.0) * 60 + district_attendance_bonus(save))
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
    legacy = int(b.get("facility", 1) or 1)
    b["facility"] = max(1, min(5, legacy))
    facilities = b.setdefault("facilities", {})
    for key in FACILITY_DEPARTMENTS:
        facilities.setdefault(key, b["facility"])
        try:
            facilities[key] = max(1, min(5, int(facilities[key])))
        except (TypeError, ValueError):
            facilities[key] = b["facility"]
    b["facility"] = max(facilities.values() or [b["facility"]])
    sponsors = b.setdefault("sponsors", {})
    for key, deal in list(sponsors.items()):
        if key not in SPONSOR_SLOTS or not isinstance(deal, dict):
            sponsors.pop(key, None)
    district = b.setdefault("district", {})
    for key in DISTRICT_PROJECTS:
        district.setdefault(key, 0)
        try:
            district[key] = max(0, min(3, int(district[key])))
        except (TypeError, ValueError):
            district[key] = 0
    b.setdefault("ticket", "normal")
    b.setdefault("parking_price", "normal")
    b.setdefault("concessions_price", "normal")
    return b


def _city_seed(save, team_id):
    return int(save.get("seed", 1) or 1) + sum((i + 1) * ord(ch) for i, ch in enumerate(str(team_id)))


def _new_city_economy(save, team):
    rng = _rng(_city_seed(save, team["id"]))
    base = CITY_MARKET_BASE.get(team.get("market"), CITY_MARKET_BASE["Mid"])
    pop_lo, pop_hi = base["population"]
    income_lo, income_hi = base["income"]
    corp_lo, corp_hi = base["corporate"]
    media_lo, media_hi = base["media"]
    return {
        "city": team.get("city", team.get("full", "")),
        "market": team.get("market", "Mid"),
        "population": round(rng.uniform(pop_lo, pop_hi), 2),      # metro population, millions
        "growth": round(rng.uniform(-0.4, 2.4), 2),               # annual percent
        "income_index": rng.randint(income_lo, income_hi),
        "corporate": rng.randint(corp_lo, corp_hi),
        "tourism": rng.randint(25, 96),
        "transit": rng.randint(28, 88),
        "tax_climate": rng.randint(28, 86),
        "construction": rng.randint(70, 145),
        "media": rng.randint(media_lo, media_hi),
        "college_football": rng.randint(20, 92),
        "youth_football": rng.randint(20, 92),
    }


def ensure_city_economics(save):
    cities = save.setdefault("city_economics", {})
    changed = False
    for team in save.get("teams", []):
        if team["id"] not in cities or not isinstance(cities.get(team["id"]), dict):
            cities[team["id"]] = _new_city_economy(save, team)
            changed = True
    return changed


def city_economy(save, team_id=None):
    ensure_city_economics(save)
    tid = team_id or save.get("current_team_id")
    return save.get("city_economics", {}).get(tid, {})


def city_economy_score(save, team_id=None):
    c = city_economy(save, team_id)
    if not c:
        return 50
    score = (
        min(100, c.get("population", 1.0) * 9)
        + c.get("income_index", 100) * 0.38
        + c.get("corporate", 50) * 0.34
        + c.get("tourism", 50) * 0.18
        + c.get("transit", 50) * 0.14
        + c.get("media", 50) * 0.22
        + c.get("tax_climate", 50) * 0.10
        - max(0, c.get("construction", 100) - 100) * 0.12
    )
    return int(max(20, min(99, round(score / 1.6))))


def city_revenue_multiplier(save):
    score = city_economy_score(save, save.get("current_team_id"))
    return round(0.92 + (score / 100.0) * 0.20, 3)  # 0.96-ish to 1.12-ish for most cities


def city_economics_view(save):
    c = city_economy(save)
    score = city_economy_score(save)
    return {**c, "score": score, "revenue_multiplier": city_revenue_multiplier(save)}


def evolve_city_economics(save, rng):
    ensure_city_economics(save)
    for tid, c in save.get("city_economics", {}).items():
        growth = float(c.get("growth", 0) or 0)
        c["population"] = round(max(0.25, float(c.get("population", 1.0) or 1.0) * (1 + growth / 100.0)), 2)
        c["growth"] = round(max(-1.2, min(3.2, growth + rng.uniform(-0.25, 0.25))), 2)
        for key in ("corporate", "tourism", "transit", "media", "tax_climate", "youth_football"):
            c[key] = max(10, min(100, int(c.get(key, 50) or 50) + rng.choice([-1, 0, 0, 1])))


FACILITY_DEPARTMENTS = {
    "training": {
        "label": "Training Complex",
        "effect": "Young-player development and camp growth.",
        "cost": 20.0,
    },
    "medical": {
        "label": "Medical Center",
        "effect": "Fewer injuries and better recovery decisions.",
        "cost": 18.0,
    },
    "analytics": {
        "label": "Analytics Department",
        "effect": "Sharper scouting and value intelligence.",
        "cost": 16.0,
    },
    "fan_experience": {
        "label": "Fan Experience",
        "effect": "Better attendance, revenue, and patience from the market.",
        "cost": 14.0,
    },
}


def facility_level(save, key="training"):
    b = _business(save)
    return int(b.get("facilities", {}).get(key, b.get("facility", 1)) or 1)


def facilities_view(save):
    _business(save)
    return [
        {**meta, "key": key, "level": facility_level(save, key), "cost": facility_cost(save, key)}
        for key, meta in FACILITY_DEPARTMENTS.items()
    ]


def facility_development_bonus(save):
    return 1 if facility_level(save, "training") >= 3 else 0


def facility_medical_bonus(save):
    return (facility_level(save, "medical") - 1) * 6


def facility_scouting_bonus(save):
    return round((facility_level(save, "analytics") - 1) * 3.5, 1)


def facility_revenue_multiplier(save):
    return 1.0 + (facility_level(save, "fan_experience") - 1) * 0.035


def sponsorship_revenue(save):
    sponsors = _business(save).get("sponsors", {})
    return round(sum(float(d.get("amount", 0) or 0) for d in sponsors.values()), 1)


def district_revenue(save):
    district = _business(save).get("district", {})
    return round(sum(DISTRICT_PROJECTS[k]["rev"] * int(district.get(k, 0) or 0)
                     for k in DISTRICT_PROJECTS), 1)


def district_fan_bonus(save):
    district = _business(save).get("district", {})
    return sum(DISTRICT_PROJECTS[k]["fan"] * int(district.get(k, 0) or 0)
               for k in DISTRICT_PROJECTS)


def district_attendance_bonus(save):
    district = _business(save).get("district", {})
    return min(8, int(district.get("parking", 0) or 0) * 2
               + int(district.get("restaurants", 0) or 0)
               + int(district.get("entertainment", 0) or 0))


def district_cost(save, key):
    key = key if key in DISTRICT_PROJECTS else "parking"
    level = int(_business(save).get("district", {}).get(key, 0) or 0)
    return round((level + 1) * DISTRICT_PROJECTS[key]["cost"], 1)


def district_view(save):
    b = _business(save)
    return {"annual": district_revenue(save), "rows": [
        {**meta, "key": key, "level": int(b["district"].get(key, 0) or 0), "cost": district_cost(save, key)}
        for key, meta in DISTRICT_PROJECTS.items()
    ]}


def upgrade_district(save, key):
    key = key if key in DISTRICT_PROJECTS else ""
    if not key:
        return False, "That district project does not exist."
    b = _business(save)
    level = int(b["district"].get(key, 0) or 0)
    label = DISTRICT_PROJECTS[key]["label"]
    if level >= 3:
        return False, f"{label} is already fully built."
    cost = district_cost(save, key)
    if b["cash"] < cost:
        return False, f"{label} costs ${cost}M - you have ${b['cash']}M."
    b["cash"] = round(b["cash"] - cost, 1)
    b["district"][key] = level + 1
    _rel_nudge(save, "media", 1, f"invested in the stadium district: {label}")
    write_save(save)
    return True, f"{label} upgraded to Level {level + 1}."


def _sponsor_offer(save, key):
    key = key if key in SPONSOR_SLOTS else "local_media"
    slot = SPONSOR_SLOTS[key]
    team = current_team(save)
    market = MARKET_MULT.get(team["market"], 1.0)
    att = attendance(save)
    city = city_economy(save)
    gm = save.get("gm", {})
    title_bonus = min(0.35, gm.get("titles", 0) * 0.08)
    rep_bonus = max(-0.12, min(0.22, (gm.get("reputation", 50) - 50) / 220.0))
    fan_bonus = max(-0.15, min(0.25, (_business(save)["fan_happiness"] - 50) / 180.0))
    stadium_bonus = (_business(save)["stadium"] - 1) * 0.045
    city_bonus = (city.get("corporate", 50) - 50) / 260.0 + (city.get("media", 50) - 50) / 320.0
    amount = round(slot["base"] * market * (0.75 + att["fill"] / 180.0 + title_bonus
                                            + rep_bonus + fan_bonus + stadium_bonus + city_bonus), 1)
    rng = _rng(save["seed"] + save.get("season", 1) * 733 + sum(ord(c) for c in key))
    return {"key": key, "label": slot["label"], "brand": rng.choice(SPONSOR_BRANDS),
            "amount": max(0.8, amount), "years": slot["years"]}


def sponsorship_view(save):
    b = _business(save)
    rows = []
    for key, slot in SPONSOR_SLOTS.items():
        active = b.get("sponsors", {}).get(key)
        rows.append({"key": key, "label": slot["label"], "active": active,
                     "offer": None if active else _sponsor_offer(save, key)})
    return {"annual": sponsorship_revenue(save), "rows": rows}


def sign_sponsor(save, key):
    key = key if key in SPONSOR_SLOTS else ""
    if not key:
        return False, "That sponsor slot does not exist."
    b = _business(save)
    sponsors = b.setdefault("sponsors", {})
    if key in sponsors:
        return False, f"{SPONSOR_SLOTS[key]['label']} is already under contract."
    offer = _sponsor_offer(save, key)
    sponsors[key] = {"brand": offer["brand"], "amount": offer["amount"], "years": offer["years"],
                     "signed": save.get("season", 1)}
    _rel_nudge(save, "media", 1, f"signed {offer['brand']} as {offer['label'].lower()}")
    write_save(save)
    return True, f"{offer['brand']} signs {offer['years']}yr / ${offer['amount']}M per year for {offer['label']}."


def projected_revenue(save):
    b = _business(save)
    att = attendance(save)
    mm = MARKET_MULT.get(current_team(save)["market"], 1.0)
    if save.get("rev_share"):
        mm = max(mm, 0.97)   # the league props up small markets
    _, _, pm = TICKET.get(b["ticket"], TICKET["normal"])
    parking = VENUE_PRICING.get(b.get("parking_price", "normal"), VENUE_PRICING["normal"])
    concessions = VENUE_PRICING.get(b.get("concessions_price", "normal"), VENUE_PRICING["normal"])
    # seats actually filled x price-per-seat x market (so winning -> fuller house -> more money)
    gate = ((16 + b["stadium"] * 5) * mm * (att["fill"] / 100.0 + 0.22) * pm
            * facility_revenue_multiplier(save) * city_revenue_multiplier(save))
    gameday = (3.8 + b["stadium"] * 0.9) * (att["fill"] / 100.0 + 0.15) * mm
    gameday *= (parking["rev"] * 0.45 + concessions["rev"] * 0.55)
    return round(gate + gameday + sponsorship_revenue(save) + district_revenue(save), 1)


def stadium_cost(save):
    return round(_business(save)["stadium"] * 28.0, 1)


def facility_cost(save, which="training"):
    which = which if which in FACILITY_DEPARTMENTS else "training"
    return round(facility_level(save, which) * FACILITY_DEPARTMENTS[which]["cost"], 1)


def staff_cost(rating):
    return round(rating * 0.12, 1)


def _apply_finance(save, rec, won_title):
    b = _business(save)
    rev = projected_revenue(save)
    b["cash"] = round(b["cash"] + rev, 1)
    if save.get("gm", {}).get("part_owner"):
        b["cash"] = round(b["cash"] + rev * 0.10, 1)   # your ownership dividend
    _, hd, _ = TICKET.get(b["ticket"], TICKET["normal"])
    parking_hd = VENUE_PRICING.get(b.get("parking_price", "normal"), VENUE_PRICING["normal"])["fan"]
    concessions_hd = VENUE_PRICING.get(b.get("concessions_price", "normal"), VENUE_PRICING["normal"])["fan"]
    fan_bonus = max(0, facility_level(save, "fan_experience") - 1) + district_fan_bonus(save)
    b["fan_happiness"] = max(0, min(100, b["fan_happiness"] + (rec["w"] - rec["l"]) * 1.5
                                    + (10 if won_title else 0) + hd + parking_hd + concessions_hd + fan_bonus))
    b["last_revenue"] = rev
    save["gm"]["money_earned"] = round(save["gm"].get("money_earned", 0) + rev, 1)   # career revenue
    for key, deal in list(b.get("sponsors", {}).items()):
        deal["years"] = int(deal.get("years", 1) or 1) - 1
        if deal["years"] <= 0:
            b["sponsors"].pop(key, None)


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


def upgrade_facility(save, which="training"):
    which = which if which in FACILITY_DEPARTMENTS else "training"
    b = _business(save)
    facilities = b.setdefault("facilities", {})
    current = facility_level(save, which)
    label = FACILITY_DEPARTMENTS[which]["label"]
    if current >= 5:
        return False, f"{label} is already at the max level."
    c = facility_cost(save, which)
    if b["cash"] < c:
        return False, f"{label} upgrade costs ${c}M - you have ${b['cash']}M."
    b["cash"] = round(b["cash"] - c, 1)
    facilities[which] = current + 1
    b["facility"] = max(facilities.values())
    write_save(save)
    return True, f"{label} upgraded to Level {facilities[which]}."


def set_ticket(save, level):
    if level in TICKET:
        _business(save)["ticket"] = level
        write_save(save)
    return True


def set_venue_pricing(save, kind, level):
    if kind not in ("parking_price", "concessions_price") or level not in VENUE_PRICING:
        return False
    _business(save)[kind] = level
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

    room = round(cap_total(save) - cap_used(team), 1)
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
# The world reacts — a LIVE awards race and box-score storylines from the stats
# the season is actually producing (not just an end-of-year recap). Cheap, and
# it gives the in-season week real personality.
# --------------------------------------------------------------------------- #
def _mvp_score(s):
    return (s.get("pass_yd", 0) * 0.04 + s.get("pass_td", 0) * 4 - s.get("int", 0) * 2
            + s.get("rush_yd", 0) * 0.05 + s.get("rush_td", 0) * 6
            + s.get("rec_yd", 0) * 0.05 + s.get("rec_td", 0) * 6 + s.get("sack", 0) * 4)


def awards_race(save):
    """The live MVP ladder + statistical leaders, mid-season, from real totals."""
    if not save.get("inseason"):
        return None
    uid = save["current_team_id"]
    teams = save["teams"]
    if not any(p.get("stats") for t in teams for p in t["roster"]):
        return None
    ladder = sorted(((_mvp_score(p.get("stats") or {}), p, t) for t in teams for p in t["roster"]
                     if p.get("stats")), key=lambda x: -x[0])
    mvp = [{"rank": i + 1, "name": p["name"], "pos": p["pos"], "team": t.get("name", t["full"]),
            "line": stat_line(p), "you": t["id"] == uid, "pid": p["id"]}
           for i, (v, p, t) in enumerate(ladder[:5])]
    cats = [("Passing", "pass_yd"), ("Rushing", "rush_yd"), ("Receiving", "rec_yd"), ("Sacks", "sack")]
    leaders = []
    for label, key in cats:
        rows = sorted([(p, t) for t in teams for p in t["roster"] if (p.get("stats") or {}).get(key)],
                      key=lambda x: -x[0]["stats"][key])[:3]
        if rows:
            leaders.append({"label": label, "rows": [
                {"name": p["name"], "pos": p["pos"], "team": t.get("name", t["full"]),
                 "val": p["stats"][key], "you": t["id"] == uid, "pid": p["id"]} for p, t in rows]})
    return {"mvp": mvp, "leaders": leaders, "week": save["inseason"]["week"]}


def _skill_prod(p):
    s = p.get("stats") or {}
    return (s.get("pass_yd", 0) * 0.04 + s.get("pass_td", 0) * 4 + s.get("rush_yd", 0) * 0.06
            + s.get("rush_td", 0) * 6 + s.get("rec_yd", 0) * 0.06 + s.get("rec_td", 0) * 6)


def team_storylines(save):
    """Box-score storylines about YOUR team: a big game, a WR1 controversy, a TD
    streak, a young breakout. Each carries a pid so the UI can link the player."""
    if not save.get("inseason"):
        return []
    team = current_team(save)
    stories = []
    lg = save.get("last_game") or {}
    box = lg.get("my_box") or []
    if box:                                            # 1) hot hand — a big last game
        top = box[0]
        g = top.get("g") or {}
        tds = g.get("pass_td", 0) + g.get("rush_td", 0) + g.get("rec_td", 0)
        if g.get("pass_yd", 0) >= 300 or g.get("rush_yd", 0) >= 110 or g.get("rec_yd", 0) >= 110 or tds >= 3:
            stories.append({"icon": "🔥", "kind": "hot", "pid": top.get("pid"),
                            "head": f"{top['pos']} {top['name']} went off", "sub": top["line"]})
    wrs = sorted([p for p in team["roster"] if p["pos"] == "WR" and (p.get("stats") or {}).get("rec_yd")],
                 key=lambda p: -p["stats"]["rec_yd"])
    if len(wrs) >= 2:                                  # 2) WR1 controversy
        w1, w2 = wrs[0], wrs[1]
        y1, y2 = w1["stats"]["rec_yd"], w2["stats"]["rec_yd"]
        if y1 >= 250 and y2 >= 0.9 * y1:
            stories.append({"icon": "📣", "kind": "wr", "pid": w2["id"],
                            "head": "A WR1 question in the room",
                            "sub": f"{w2['name']} ({y2} yds) is right on {w1['name']} ({y1}) — who's the go-to guy?"})
    pgl = save.get("pgl") or {}                        # 3) TD streak
    for p in team["roster"]:
        recent = (pgl.get(p["id"]) or [])[-3:]
        if len(recent) >= 3 and all((g.get("rush_td", 0) + g.get("rec_td", 0) + g.get("pass_td", 0)) > 0
                                    for g in recent):
            stories.append({"icon": "⚡", "kind": "streak", "pid": p["id"],
                            "head": f"{p['pos']} {p['name']}: TD in {len(recent)} straight",
                            "sub": "He's finding the end zone every week."})
            break
    young = sorted([p for p in team["roster"] if p.get("age", 30) <= 23 and _skill_prod(p) > 0],
                   key=lambda p: -_skill_prod(p))
    if young and _skill_prod(young[0]) >= 55:          # 4) young breakout
        yb = young[0]
        stories.append({"icon": "🌟", "kind": "young", "pid": yb["id"],
                        "head": f"{yb['pos']} {yb['name']} is breaking out",
                        "sub": f"A {yb['age']}-year-old already producing: {stat_line(yb)}."})
    return stories[:4]


def _log_player_games(save, perf, week):
    """Append each skill player's single-game line to the per-player game log
    (last 6 games) so storylines can spot streaks and trends."""
    pgl = save.setdefault("pgl", {})
    for b in perf:
        g = b.get("g")
        if not g or b.get("pos") not in ("QB", "RB", "WR", "TE"):
            continue
        lst = pgl.setdefault(b["pid"], [])
        lst.append({"wk": week, **{k: g.get(k, 0) for k in
                    ("pass_yd", "pass_td", "rush_yd", "rush_td", "rec", "rec_yd", "rec_td")}})
        del lst[:-6]


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
            "executive_hall": save.get("executive_hall", []),
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
        line = f"{s['pass_yd']:,} yd, {s['pass_td']} TD, {s['int']} INT"
        if s.get("rush_yd", 0) >= 150:                 # a dual-threat QB's legs matter
            line += f" · {s['rush_yd']:,} rush yd, {s.get('rush_td', 0)} rush TD"
        return line
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


# --------------------------------------------------------------------------- #
# DEEP PER-POSITION ATTRIBUTES — a full scouting breakdown for every player,
# DERIVED from his overall + style + combine + age. It's a lens on the player
# (the sim still runs on overall in v1), so it adds scouting depth without
# rebalancing anything. Deterministic per player id.
# --------------------------------------------------------------------------- #
POSITION_ATTRIBUTES = {
    "QB": [("Arm Strength", "Physical"), ("Deep Accuracy", "Skill"), ("Short Accuracy", "Skill"),
           ("Throw on Run", "Skill"), ("Release", "Skill"), ("Awareness", "Mental"),
           ("Poise", "Mental"), ("Mobility", "Physical"), ("Toughness", "Physical")],
    "RB": [("Speed", "Physical"), ("Acceleration", "Physical"), ("Power", "Physical"),
           ("Elusiveness", "Skill"), ("Vision", "Mental"), ("Hands", "Skill"),
           ("Pass Protection", "Skill"), ("Ball Security", "Mental"), ("Durability", "Physical")],
    "WR": [("Speed", "Physical"), ("Acceleration", "Physical"), ("Route Running", "Skill"),
           ("Hands", "Skill"), ("Release", "Skill"), ("Contested Catch", "Skill"),
           ("YAC", "Skill"), ("Deep Threat", "Skill"), ("Awareness", "Mental")],
    "TE": [("Speed", "Physical"), ("Run Blocking", "Skill"), ("Route Running", "Skill"),
           ("Hands", "Skill"), ("Contested Catch", "Skill"), ("Strength", "Physical"),
           ("Awareness", "Mental")],
    "OL": [("Run Block", "Skill"), ("Pass Block", "Skill"), ("Strength", "Physical"),
           ("Anchor", "Skill"), ("Agility", "Physical"), ("Awareness", "Mental"),
           ("Toughness", "Physical")],
    "DL": [("Pass Rush", "Skill"), ("Run Defense", "Skill"), ("Strength", "Physical"),
           ("Power Moves", "Skill"), ("Finesse Moves", "Skill"), ("Motor", "Mental"),
           ("Awareness", "Mental")],
    "LB": [("Tackle", "Skill"), ("Coverage", "Skill"), ("Pass Rush", "Skill"),
           ("Speed", "Physical"), ("Play Recognition", "Mental"), ("Hit Power", "Physical"),
           ("Pursuit", "Physical")],
    "CB": [("Man Coverage", "Skill"), ("Zone Coverage", "Skill"), ("Speed", "Physical"),
           ("Press", "Skill"), ("Ball Skills", "Mental"), ("Recovery", "Physical"),
           ("Awareness", "Mental")],
    "S": [("Coverage", "Skill"), ("Run Support", "Skill"), ("Speed", "Physical"),
          ("Ball Skills", "Mental"), ("Hit Power", "Physical"), ("Range", "Physical"),
          ("Awareness", "Mental")],
    "K": [("Kick Power", "Physical"), ("Kick Accuracy", "Skill"), ("Clutch", "Mental")],
    "P": [("Punt Power", "Physical"), ("Punt Accuracy", "Skill"), ("Hang Time", "Skill")],
}

# style -> per-attribute tilt. Keys not on a position are harmlessly ignored,
# so shared style names (e.g. "Zone" for OL and CB) can co-exist in one entry.
STYLE_TILTS = {
    "Pocket Passer": {"Arm Strength": 6, "Deep Accuracy": 6, "Poise": 5, "Mobility": -9, "Throw on Run": -4},
    "Dual Threat": {"Mobility": 10, "Throw on Run": 7, "Release": 3, "Poise": -4, "Deep Accuracy": -3},
    "Game Manager": {"Short Accuracy": 7, "Awareness": 6, "Arm Strength": -5, "Deep Accuracy": -6},
    "RPO Specialist": {"Mobility": 8, "Release": 6, "Short Accuracy": 5, "Deep Accuracy": -4},
    "Power Back": {"Power": 10, "Durability": 5, "Elusiveness": -7, "Speed": -6, "Acceleration": -3},
    "Scat Back": {"Speed": 9, "Acceleration": 8, "Elusiveness": 9, "Hands": 5, "Power": -9},
    "Every-Down": {"Vision": 6, "Pass Protection": 6, "Hands": 3, "Durability": 3},
    "Deep Threat": {"Speed": 10, "Acceleration": 6, "Deep Threat": 11, "Route Running": -5, "Contested Catch": -2},
    "Possession": {"Hands": 9, "Contested Catch": 9, "Route Running": 6, "Speed": -5, "YAC": -2},
    "Slot": {"Route Running": 9, "YAC": 9, "Release": 6, "Deep Threat": -6, "Awareness": 3},
    "Move TE": {"Speed": 7, "Route Running": 8, "Hands": 6, "Run Blocking": -9, "Strength": -4},
    "In-Line Blocker": {"Run Blocking": 9, "Strength": 7, "Route Running": -7, "Speed": -5},
    "Power": {"Run Block": 9, "Strength": 8, "Anchor": 6, "Agility": -7, "Pass Block": -2},
    "Zone": {"Agility": 8, "Pass Block": 6, "Awareness": 4, "Strength": -4,
             "Zone Coverage": 9, "Man Coverage": -6, "Recovery": 3},
    "Press Man": {"Man Coverage": 10, "Press": 10, "Recovery": 5, "Zone Coverage": -6},
    "Pass Rusher": {"Pass Rush": 10, "Finesse Moves": 8, "Power Moves": 2, "Run Defense": -7},
    "Run Stuffer": {"Run Defense": 9, "Strength": 8, "Power Moves": 7, "Pass Rush": -7},
    "Coverage": {"Coverage": 9, "Speed": 6, "Play Recognition": 5, "Hit Power": -6, "Pass Rush": -3},
    "Thumper": {"Tackle": 8, "Hit Power": 9, "Pass Rush": 5, "Coverage": -9, "Pursuit": -2},
    "Box": {"Run Support": 10, "Hit Power": 8, "Coverage": -7, "Range": -5},
    "Center Field": {"Coverage": 8, "Range": 10, "Ball Skills": 6, "Run Support": -7, "Hit Power": -4},
    "Big Leg": {"Kick Power": 11, "Kick Accuracy": -5},
    "Accurate": {"Kick Accuracy": 11, "Kick Power": -5, "Clutch": 4},
}

_ATTR_MENTAL = {"Awareness", "Poise", "Play Recognition", "Vision", "Ball Security",
                "Ball Skills", "Motor", "Clutch"}
_ATTR_SPEED = {"Speed", "Acceleration", "Mobility", "Range", "Recovery", "Elusiveness",
               "Pursuit", "Agility"}


def _combine_attr_deltas(pos, combine):
    d = {}
    if not combine:
        return d
    forty, bench, vert, cone = (combine.get("forty"), combine.get("bench"),
                                combine.get("vert"), combine.get("cone"))
    if forty:
        fast = max(-8, min(8, round((_COMBINE_40.get(pos, 4.8) - forty) * 40)))
        for a in ("Speed", "Acceleration", "Mobility", "Range", "Recovery", "Deep Threat", "Pursuit"):
            d[a] = d.get(a, 0) + fast
    if bench:
        strong = max(-6, min(6, round((bench - _COMBINE_BENCH.get(pos, 18)) * 0.8)))
        for a in ("Strength", "Power", "Run Block", "Power Moves", "Anchor", "Run Defense", "Hit Power"):
            d[a] = d.get(a, 0) + strong
    if vert:
        hi = max(-5, min(6, round((vert - 33) * 0.7)))
        for a in ("Contested Catch", "Ball Skills", "Deep Threat"):
            d[a] = d.get(a, 0) + hi
    if cone:
        agile = max(-5, min(6, round((7.05 - cone) * 30)))
        for a in ("Agility", "Elusiveness", "Route Running", "Man Coverage", "Press"):
            d[a] = d.get(a, 0) + agile
    return d


def player_attributes(p):
    """The full derived attribute set for one player (or prospect)."""
    spec = POSITION_ATTRIBUTES.get(p.get("pos"))
    if not spec:
        return []
    ovr = int(p.get("overall") or p.get("grade") or 60)
    tilts = STYLE_TILTS.get(p.get("style"), {})
    cdelta = _combine_attr_deltas(p.get("pos"), p.get("combine") or {})
    age = int(p.get("age", 26) or 26)
    seed = sum(ord(c) for c in str(p.get("id", "x")))
    out = []
    for attr, cat in spec:
        d = tilts.get(attr, 0) + cdelta.get(attr, 0)
        if attr in _ATTR_MENTAL:
            d += max(-2, min(5, (age - 25) // 2))       # vets sharper mentally
        if attr in _ATTR_SPEED:
            d += max(-6, min(2, (25 - age) // 2))        # legs fade with age
        noise = ((seed + sum(ord(c) for c in attr)) % 7) - 3
        out.append({"attr": attr, "cat": cat, "value": max(28, min(99, ovr + d + noise))})
    return out


def attribute_groups(p):
    """Grouped for the profile: Physical / Skill / Mental, plus his top traits."""
    attrs = player_attributes(p)
    if not attrs:
        return None
    groups = {}
    for a in attrs:
        groups.setdefault(a["cat"], []).append(a)
    ordered = [(cat, groups[cat]) for cat in ("Physical", "Skill", "Mental") if groups.get(cat)]
    top = [a["attr"] for a in sorted(attrs, key=lambda a: -a["value"])[:3]]
    return {"groups": ordered, "top": top}


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


def practice_squad_limit(save):
    return int(save.get("league_rules", {}).get("practice_squad_slots", PS_MAX) or PS_MAX)


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
    if len(team.get("practice_squad", [])) >= practice_squad_limit(save):
        return False
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return False
    team["roster"] = [x for x in team["roster"] if x["id"] != pid]
    p["practice"] = True
    team.setdefault("practice_squad", []).append(p)
    write_save(save)
    return True


PS_PROTECT_MAX = 2


def protect_ps(save, pid):
    """Toggle poaching protection on a practice-squad player (at most PS_PROTECT_MAX)."""
    ps = current_team(save).get("practice_squad", [])
    p = next((x for x in ps if x["id"] == pid), None)
    if not p:
        return False, "Not on your practice squad."
    if p.get("protected"):
        p.pop("protected", None)
        write_save(save)
        return True, f"{p['name']} is no longer protected."
    if sum(1 for x in ps if x.get("protected")) >= PS_PROTECT_MAX:
        return False, f"You can protect at most {PS_PROTECT_MAX} practice-squad players."
    p["protected"] = True
    write_save(save)
    return True, f"{p['name']} is protected from poaching."


def _roll_ps_poaching(save, week, rng):
    """Rivals raid your unprotected practice squad — the better the player, the more
    likely he's signed away to a rival's active roster."""
    team = current_team(save)
    poached = []
    for p in list(team.get("practice_squad", [])):
        if p.get("protected") or p.get("overall", 60) < 68:
            continue
        if rng.random() < min(0.25, (p["overall"] - 66) * 0.02):
            club = rng.choice([t for t in save["teams"] if t["id"] != team["id"]])
            team["practice_squad"] = [x for x in team["practice_squad"] if x["id"] != p["id"]]
            p.pop("practice", None)
            club["roster"].append(p)
            poached.append({"name": p["name"], "pos": p["pos"], "ovr": p["overall"], "to": club.get("name", club["full"])})
            _tl(save, save.get("season", 1), "poached", "📤",
                f"Lost {p['pos']} {p['name']} to a poach",
                f"{club['full']} signed him off your practice squad in Week {week}.")
    return poached


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
    room = round(cap_total(save) - cap_used(team))
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
        deadline = int(save.get("league_rules", {}).get("trade_deadline_week", TRADE_DEADLINE_SOLO) or TRADE_DEADLINE_SOLO)
        return iz.get("week", 1) <= deadline
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
    p["ex_team"], p["ex_team_name"] = team["id"], team["full"]   # for reunion-game story
    ai["roster"].append(p)
    uid = team["id"]
    for pk in off["picks"]:
        save.setdefault("pick_swaps", []).append(
            {"season": off["season"], "round": pk["round"], "orig": off["team_id"], "to": uid})
    picks_txt = " + ".join(f"R{pk['round']}" for pk in off["picks"])
    save["last_trade"] = {"ok": True, "summary":
                          f"Traded {p['pos']} {p['name']} to the {off['team']} for {picks_txt} (season {off['season']} draft)."}
    _rel_nudge(save, "rival_gms", 1, f"completed a draft-pick deal with {off['team']}")
    _rel_nudge(save, "locker_room", -1, f"traded {p['pos']} {p['name']} out of the building")
    _culture_nudge(save, "player_trust", -1, f"{p['pos']} {p['name']} was moved for picks")
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


def draft_order_projection(save):
    """Projected pick slot (1..n) for every club in a FUTURE draft, from current
    power — the weakest team is projected to pick first. The real order is set by
    where clubs actually finish; this is the read you trade on today."""
    teams = save.get("teams", [])
    order = sorted(teams, key=lambda t: (power_rating(t), t.get("full", "")))
    return {t["id"]: i + 1 for i, t in enumerate(order)}, len(teams)


def _round_tier(pir, n):
    third = max(1, round(n / 3.0))
    return "early" if pir <= third else "late" if pir > n - third else "mid"


def annotated_pick_shop(save):
    """save['pick_shop'] with each offered pick tagged with its PROJECTED draft
    slot: the offering club's own pick, so its position is that club's projected
    finish. Lets you tell an early-2nd from a late-2nd before you accept."""
    shop = save.get("pick_shop")
    if not shop:
        return None
    slot_by_team, n = draft_order_projection(save)
    offers = []
    for o in shop.get("offers", []):
        pir = slot_by_team.get(o.get("team_id"), (n + 1) // 2)
        picks = [dict(pk, pir=pir, ov=(pk["round"] - 1) * n + pir,
                      tier=_round_tier(pir, n)) for pk in o.get("picks", [])]
        offers.append(dict(o, picks=picks, pir=pir, tier=_round_tier(pir, n)))
    return dict(shop, offers=offers, teams_n=n)


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
        _rel_nudge(save, "rival_gms", -1, f"{target['full']} rejected a light trade offer")
    elif cap_used(user) - give["contract"]["aav"] + get["contract"]["aav"] > cap_total(save):
        result["accepted"] = False
        result["msg"] = f"{target['full']} would do it, but {get['name']}'s contract puts you over the cap."
    else:
        give["ex_team"], give["ex_team_name"] = user["id"], user["full"]   # reunion-game story
        get.pop("ex_team", None); get.pop("ex_team_name", None)            # he's home now
        user["roster"] = [p for p in user["roster"] if p["id"] != give_id] + [get]
        target["roster"] = [p for p in target["roster"] if p["id"] != get_id] + [give]
        result["accepted"] = True
        result["msg"] = f"Trade accepted! {give['name']} to {target['full']} for {get['name']}."
        _rel_nudge(save, "rival_gms", 1, f"completed a player trade with {target['full']}")
        _rel_nudge(save, "locker_room", -1, f"traded away {give['pos']} {give['name']}")
        _culture_nudge(save, "player_trust", -1, f"{give['pos']} {give['name']} was traded")
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
          f"Roster {len(t['roster'])}  Cap {cap_used(t)}/{cap_total(s)}")
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
