"""Franchise Kings - GM career simulator engine (v0.1, football / fictional BRK League).

Pure-Python, JSON-serializable game state. No Flask dependency so it can be unit
-tested from the command line. The web layer (app.py) only calls into here and
renders the returned dicts.

Core loop: create GM -> take a job -> sign free agents -> sim season -> owner
evaluation -> retained / extended / fired / poached -> career history.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "data" / "franchise"

LEAGUE_SIZE = 16
REG_GAMES = 14
PLAYOFF_TEAMS = 8
CAP_TOTAL = 220.0  # millions

# Fictional cities + mascots (no real franchises).
CITIES = [
    "Atlas", "Granite", "Harbor", "Iron City", "Summit", "Delta", "Crown Point",
    "Bayou", "Cascade", "Verdant", "Cobalt", "Sable", "Frontier", "Monarch",
    "Tidewater", "Vanguard", "Helix", "Sterling", "Meridian", "Onyx",
]
MASCOTS = [
    "Kings", "Titans", "Vipers", "Sentinels", "Outlaws", "Wolves", "Reign",
    "Dreadnoughts", "Phantoms", "Apex", "Voltage", "Ironsides", "Stampede",
    "Warhawks", "Krakens", "Comets", "Renegades", "Juggernauts", "Stags", "Aces",
]
FIRST_NAMES = [
    "Marcus", "DeShawn", "Tyrell", "Cole", "Brock", "Xavier", "Jaylen", "Trey",
    "Dominic", "Isaiah", "Hunter", "Malik", "Cooper", "Diego", "Andre", "Kade",
    "Roman", "Silas", "Tobias", "Quinton", "Rashad", "Beau", "Khalil", "Jaxon",
]
LAST_NAMES = [
    "Reed", "Locke", "Vance", "Mercer", "Hollis", "Bishop", "Cross", "Rhodes",
    "Kane", "Sloan", "Boone", "Hayes", "Dawson", "Foster", "Mata", "Okafor",
    "Vega", "Prince", "Steele", "Calloway", "Drummond", "Fontaine", "Ash", "Roy",
]

# Starter slots per position (the depth chart auto-starts the best by position).
ROSTER = {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 3, "DL": 3, "LB": 2, "CB": 2, "S": 1, "K": 1}
# Position weight for the Power Rating (football = QB-heavy).
POS_WEIGHT = {"QB": 5.0, "WR": 1.6, "OL": 1.5, "DL": 1.5, "CB": 1.4, "LB": 1.2,
              "S": 1.1, "RB": 1.1, "TE": 1.0, "K": 0.4}

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


def _rng(seed):
    return random.Random(seed)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _gen_name(rng):
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _gen_player(rng, pos, base=None):
    age = rng.randint(21, 34)
    # younger players skew lower OVR but higher potential
    overall = base if base is not None else int(rng.triangular(58, 92, 74))
    overall = max(48, min(99, overall))
    pot_gap = max(0, int(rng.triangular(0, 22, 6)) - (age - 24))
    potential = max(overall, min(99, overall + pot_gap))
    aav = round(max(0.7, (overall - 55) ** 1.7 / 22.0), 1)  # millions, steep at the top
    return {
        "id": f"p{rng.randint(100000, 999999)}",
        "name": _gen_name(rng),
        "pos": pos,
        "age": age,
        "overall": overall,
        "potential": potential,
        "dev": rng.choice(["Normal", "Star", "Slow", "Late Bloomer"]),
        "contract": {"years": rng.randint(1, 4), "aav": aav, "guaranteed": round(aav * rng.uniform(0.3, 0.8), 1)},
        "morale": rng.randint(55, 90),
        "injury_risk": rng.choice(["Low", "Low", "Medium", "High"]),
    }


def _gen_roster(rng, strength):
    """strength 0..1 nudges the talent floor so weak teams feel weak."""
    roster = []
    for pos, count in ROSTER.items():
        for _ in range(count + 1):  # one backup per slot
            base = int(rng.triangular(54, 90, 66 + strength * 14))
            roster.append(_gen_player(rng, pos, base))
    return roster


def _gen_team(rng, idx, city, mascot):
    strength = rng.random()
    roster = _gen_roster(rng, strength)
    return {
        "id": f"t{idx}",
        "city": city,
        "name": mascot,
        "full": f"{city} {mascot}",
        "market": rng.choice(["Small", "Small", "Mid", "Mid", "Large"]),
        "owner": {"type": rng.choice(OWNER_TYPES)},
        "roster": roster,
        "record": {"w": 0, "l": 0},
    }


def new_league(seed):
    rng = _rng(seed)
    cities = rng.sample(CITIES, LEAGUE_SIZE)
    mascots = rng.sample(MASCOTS, LEAGUE_SIZE)
    teams = [_gen_team(rng, i, cities[i], mascots[i]) for i in range(LEAGUE_SIZE)]
    free_agents = [_gen_player(rng, rng.choice(list(ROSTER)), int(rng.triangular(60, 88, 70)))
                   for _ in range(28)]
    return teams, free_agents


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


def _sim_game(rng, pa, pb):
    # home edge baked into pa
    diff = (pa + 2.2) - pb
    p = 1.0 / (1.0 + math.exp(-diff / 6.0))
    return rng.random() < p  # True => home wins


def sim_season(save):
    """Play the schedule, produce standings, playoffs, champion, then advance the
    league a year and evaluate the GM. Mutates and returns `save`."""
    rng = _rng(save["seed"] + save["season"] * 1000)
    teams = {t["id"]: t for t in save["teams"]}
    for t in save["teams"]:
        t["record"] = {"w": 0, "l": 0}
    powers = {tid: power_rating(t) for tid, t in teams.items()}

    for g in save["schedule"]:
        home_win = _sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win]["record"]["w"] += 1
        teams[lose]["record"]["l"] += 1

    standings = sorted(
        save["teams"],
        key=lambda t: (t["record"]["w"], powers[t["id"]]), reverse=True,
    )
    # single-elim playoff among the top seeds
    bracket = [t["id"] for t in standings[:PLAYOFF_TEAMS]]
    while len(bracket) > 1:
        nxt = []
        for i in range(0, len(bracket), 2):
            a, b = bracket[i], bracket[i + 1]
            nxt.append(a if _sim_game(rng, powers[a], powers[b]) else b)
        bracket = nxt
    champion = bracket[0]

    user_team = teams[save["current_team_id"]]
    rec = dict(user_team["record"])
    made_playoffs = save["current_team_id"] in [t["id"] for t in standings[:PLAYOFF_TEAMS]]
    won_title = champion == save["current_team_id"]
    outcome = _evaluate_gm(save, rec, made_playoffs, won_title,
                           champion_name=teams[champion]["full"])

    # advance world: age players, regenerate FA pool, new expectations next year
    _advance_year(save)
    save["season"] += 1
    save["schedule"] = make_schedule(save["seed"], [t["id"] for t in save["teams"]])
    save["standings_cache"] = [
        {"id": t["id"], "full": t["full"], "w": t["record"]["w"], "l": t["record"]["l"],
         "power": powers[t["id"]]} for t in standings
    ]
    save["last_champion"] = teams[champion]["full"]
    save["last_outcome"] = outcome
    save["unemployed"] = outcome["status"] == "fired"
    _set_expectation(save)
    write_save(save)
    return save, outcome


def _advance_year(save):
    rng = _rng(save["seed"] + save["season"] * 31 + 5)
    for t in save["teams"]:
        for p in t["roster"]:
            p["age"] += 1
            if p["age"] <= 26 and p["overall"] < p["potential"]:
                p["overall"] = min(p["potential"], p["overall"] + rng.randint(0, 3))
            elif p["age"] >= 31:
                p["overall"] = max(45, p["overall"] - rng.randint(0, 3))
            p["contract"]["years"] = max(0, p["contract"]["years"] - 1)
    save["free_agents"] = [_gen_player(rng, rng.choice(list(ROSTER)),
                                       int(rng.triangular(60, 88, 70))) for _ in range(28)]


# --------------------------------------------------------------------------- #
# Owner expectations + career outcomes
# --------------------------------------------------------------------------- #
def _league_rank(save, team_id):
    ranked = sorted(save["teams"], key=lambda t: -power_rating(t))
    return [t["id"] for t in ranked].index(team_id)  # 0 = best


def _set_expectation(save):
    rank = _league_rank(save, save["current_team_id"])
    if rank <= 4:
        save["expectation"] = {"wins": 10, "text": "Win the title or it's a disappointment."}
    elif rank <= 9:
        save["expectation"] = {"wins": 8, "text": "Make the playoffs (8+ wins)."}
    else:
        save["expectation"] = {"wins": 6, "text": "Show progress - 6+ wins."}


def _evaluate_gm(save, rec, made_playoffs, won_title, champion_name):
    gm = save["gm"]
    exp = save["expectation"]["wins"]
    margin = rec["w"] - exp
    delta = 6 if margin >= 0 else -8
    delta += margin * 2
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
    pool = ranked[:6] if want == "bad" else ranked[-6:]
    pool = [t for t in pool if t["id"] != save["current_team_id"]]
    return [{"id": t["id"], "full": t["full"], "power": power_rating(t), "market": t["market"],
             "owner": t["owner"]["type"]} for t in pool[:3]]


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


def create_save(user_id, gm_name, background, seed=None):
    background = background if background in BACKGROUNDS else "scout"
    seed = seed if seed is not None else random.randint(1, 10 ** 9)
    teams, free_agents = new_league(seed)
    # the user starts with a bottom-third team (the classic rebuild)
    weak = sorted(teams, key=lambda t: power_rating(t))[2]
    ratings = {k: 50 for k in ("drafting", "trading", "free_agency", "cap", "staff", "media", "owner")}
    for stat, d in BACKGROUNDS[background]["tilt"].items():
        ratings[stat] = max(20, min(90, ratings[stat] + d))
    save = {
        "version": "0.1",
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
            "ratings": ratings,
            "owner_trust": 55, "fan_support": 50, "reputation": 50,
            "titles": 0, "career": [],
        },
        "standings_cache": [],
        "last_champion": "",
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


def take_job(save, team_id):
    if team_id not in [t["id"] for t in save["teams"]]:
        return False
    save["current_team_id"] = team_id
    # a fresh start resets owner trust to a wary baseline
    save["gm"]["owner_trust"] = 50
    save["unemployed"] = False
    save["last_outcome"] = None
    _set_expectation(save)
    write_save(save)
    return True


def delete_save(user_id):
    p = _save_path(user_id)
    if p.exists():
        p.unlink()


# --------------------------------------------------------------------------- #
# CLI self-test:  python franchise_kings.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    s = create_save("selftest_user", "Darrel Copper", "analytics", seed=42)
    print("GM:", s["gm"]["name"], "| background:", s["gm"]["background"], "| ratings:", s["gm"]["ratings"])
    t = current_team(s)
    print(f"Team: {t['full']}  Power {power_rating(t)}  Cap {cap_used(t)}/{CAP_TOTAL}")
    print("Expectation:", s["expectation"]["text"])
    if s["free_agents"]:
        ok, msg = sign_free_agent(s, s["free_agents"][0]["id"])
        print("Sign FA:", ok, msg)
    for yr in range(4):
        s, out = sim_season(s)
        print(f"Season done -> {out['status'].upper()}: {out['headline']}")
        if out["offers"]:
            pick = out["offers"][0]
            take_job(s, pick["id"])
            print("   -> took job with", pick["full"])
    print("Career:", json.dumps(s["gm"]["career"], indent=1))
    delete_save("selftest_user")
    print("OK")
