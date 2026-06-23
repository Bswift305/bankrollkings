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
CAP_TOTAL = 240.0        # millions
DRAFT_ROUNDS = 7
DRAFT_CLASS = 240        # prospects (>= rounds * teams)
ROSTER_CAP = 48          # roster size kept after the draft (cuts trim the rest)

CONFERENCES = ["Apex", "Crown"]
DIVISIONS = ["North", "South", "East", "West"]

# 36 fictional cities + 36 mascots (need >=32; extras keep the league varied).
CITIES = [
    "Atlas", "Granite", "Harbor", "Iron City", "Summit", "Delta", "Crown Point",
    "Bayou", "Cascade", "Verdant", "Cobalt", "Sable", "Frontier", "Monarch",
    "Tidewater", "Vanguard", "Helix", "Sterling", "Meridian", "Onyx", "Cardinal",
    "Redwood", "Saltlake", "Gulf City", "Highland", "Magnolia", "Copperfield",
    "Stonebridge", "Bracton", "Lakeshore", "Northgate", "Sunridge", "Prairie",
    "Crescent", "Ironwood", "Silvercreek",
]
MASCOTS = [
    "Kings", "Titans", "Vipers", "Sentinels", "Outlaws", "Wolves", "Reign",
    "Dreadnoughts", "Phantoms", "Apex", "Voltage", "Ironsides", "Stampede",
    "Warhawks", "Krakens", "Comets", "Renegades", "Juggernauts", "Stags", "Aces",
    "Maulers", "Tempest", "Grizzlies", "Sabers", "Hammers", "Rampage", "Pioneers",
    "Vortex", "Falcons", "Bulls", "Sharks", "Cyclones", "Raptors", "Avalanche",
    "Mustangs", "Legion",
]
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
# Position weight for the Power Rating (football = QB-heavy, OL/DL count a lot).
POS_WEIGHT = {"QB": 5.0, "WR": 1.5, "OL": 1.3, "DL": 1.4, "CB": 1.3, "LB": 1.1,
              "S": 1.0, "RB": 1.0, "TE": 0.9, "K": 0.4}

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
    overall = base if base is not None else int(rng.triangular(58, 92, 74))
    overall = max(48, min(99, overall))
    pot_gap = max(0, int(rng.triangular(0, 22, 6)) - (age - 24))
    potential = max(overall, min(99, overall + pot_gap))
    aav = round(max(0.7, max(0, overall - 55) ** 1.7 / 22.0), 1)
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
        for _ in range(count + 1):  # one backup per starter slot
            base = int(rng.triangular(54, 90, 66 + strength * 14))
            roster.append(_gen_player(rng, pos, base))
    return roster


def _gen_team(rng, idx, city, mascot):
    strength = rng.random()
    return {
        "id": f"t{idx}",
        "city": city,
        "name": mascot,
        "full": f"{city} {mascot}",
        "conference": CONFERENCES[idx // 16],
        "division": DIVISIONS[(idx % 16) // 4],
        "market": rng.choice(["Small", "Small", "Mid", "Mid", "Large"]),
        "owner": {"type": rng.choice(OWNER_TYPES)},
        "roster": _gen_roster(rng, strength),
        "record": {"w": 0, "l": 0},
    }


def new_league(seed):
    rng = _rng(seed)
    cities = rng.sample(CITIES, LEAGUE_SIZE)
    mascots = rng.sample(MASCOTS, LEAGUE_SIZE)
    teams = [_gen_team(rng, i, cities[i], mascots[i]) for i in range(LEAGUE_SIZE)]
    free_agents = [_gen_player(rng, rng.choice(list(ROSTER)), int(rng.triangular(60, 88, 70)))
                   for _ in range(40)]
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
    powers[save["current_team_id"]] += staff_bonus(save)["power"]   # your coaching edge

    for g in save["schedule"]:
        home_win = _sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win]["record"]["w"] += 1
        teams[lose]["record"]["l"] += 1

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
            if p["age"] <= 26 and p["overall"] < p["potential"]:
                p["overall"] = min(p["potential"], p["overall"] + rng.randint(0, 3) + bonus)
            elif p["age"] >= 31:
                p["overall"] = max(45, p["overall"] - rng.randint(0, 3))
            p["contract"]["years"] = max(0, p["contract"]["years"] - 1)
    save["free_agents"] = [_gen_player(rng, rng.choice(list(ROSTER)),
                                       int(rng.triangular(60, 88, 70))) for _ in range(40)]


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
STAFF_ROLES = [
    ("head_coach", "Head Coach", "Lifts team performance and young-player development."),
    ("off_coord", "Offensive Coordinator", "Sharpens the offense."),
    ("def_coord", "Defensive Coordinator", "Sharpens the defense."),
    ("head_scout", "Head Scout", "Tightens draft scouting - fewer busts."),
    ("head_medical", "Head of Medical", "Keeps players healthier (grows once injuries land)."),
    ("head_analytics", "Head of Analytics", "Better projections and edge (grows with the analytics layer)."),
]
_STAFF_BASE = 48  # an unhired slot runs at replacement level


def _gen_staff(rng, role):
    return {"id": f"s{rng.randint(100000, 999999)}", "name": _gen_name(rng),
            "role": role, "rating": int(rng.triangular(42, 86, 60))}


def generate_staff_market(rng):
    return {role: [_gen_staff(rng, role) for _ in range(4)] for role, _, _ in STAFF_ROLES}


def _sr(staff, role):
    return staff.get(role, {}).get("rating", _STAFF_BASE)


def staff_bonus(save):
    s = save.get("staff", {})
    coaching = (_sr(s, "head_coach") + _sr(s, "off_coord") + _sr(s, "def_coord")) / 3.0
    return {
        "power": round((coaching - 50) * 0.10, 2),          # +/- ~5 power
        "scouting": round((_sr(s, "head_scout") - 50) * 0.6, 1),
        "development": 1 if _sr(s, "head_coach") >= 65 else 0,
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
    save.setdefault("staff", {})[role] = {"name": cand["name"], "rating": cand["rating"]}
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


def create_save(user_id, gm_name, background, seed=None):
    background = background if background in BACKGROUNDS else "scout"
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
            "ratings": ratings,
            "owner_trust": 55, "fan_support": 50, "reputation": 50,
            "titles": 0, "career": [],
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
