"""Franchise Kings - the in-depth OFFSEASON process with competitive equity.

The league starts at the beginning of an offseason. Every team gets a SCENARIO
derived from how it finished last season: the champion faces a brutal offseason
(cap crunch, stars hitting free agency, complacency/regression, the last pick in
the draft) while the cellar team gets an attractive one (top pick, the most cap
space, a young core ready to leap). The result: all 32 teams can converge on the
champion, and staying #1 is hard.

The GM walks a staged offseason - Recap -> Voluntary Workouts (evaluate talent) ->
Re-Sign your own -> Free Agency -> Draft -> Training-Camp Cuts to 53 -> Kickoff -
making real decisions at each step before the season is played.

Pure functions over the franchise_kings save dict; reuses fk for the world,
contracts, FA negotiation and the draft. CLI self-test: python franchise_offseason.py
"""
from __future__ import annotations

import random

import franchise_kings as fk

ROSTER_FINAL = 53            # the final 53-man roster
CAMP_KEEP_MAX = 80          # camp rosters are capped here before cuts

STAGES = [
    {"key": "recap",       "title": "Season Recap",       "icon": "\U0001F4CB"},
    {"key": "workouts",    "title": "Voluntary Workouts", "icon": "\U0001F3CB"},
    {"key": "resign",      "title": "Re-Sign Your Own",   "icon": "✍"},
    {"key": "free_agency", "title": "Free Agency",        "icon": "\U0001F4B0"},
    {"key": "draft",       "title": "The Draft",          "icon": "\U0001F393"},
    {"key": "cuts",        "title": "Cuts to 53",         "icon": "✂"},
    {"key": "kickoff",     "title": "Kickoff",            "icon": "\U0001F3C8"},
]
STAGE_KEYS = [s["key"] for s in STAGES]


# --------------------------------------------------------------------------- #
# Scenario = the competitive-equity spine
# --------------------------------------------------------------------------- #
_TIER_PROFILE = {
    # tier        dev_bias  cap_bonus  comp_picks   (dev_bias = the equalizer:
    "champion":  (-1,       0.0,       0),       #   good teams' vets dip a little,
    "contender": (0,        8.0,       0),       #   cellar's young players pop -
    "middle":    (1,        18.0,      1),       #   so the league converges without
    "rebuild":   (2,        34.0,      2),       #   dooming the team you just took.
}


def _tier(rank, n, won_title):
    if won_title:
        return "champion"
    if rank <= max(2, n // 5):
        return "contender"
    if rank <= (n * 2) // 3:
        return "middle"
    return "rebuild"


def scenario_for(rank, n, won_title):
    """rank 0 = best finish ... n-1 = worst."""
    tier = _tier(rank, n, won_title)
    dev_bias, cap_bonus, comp = _TIER_PROFILE[tier]
    return {
        "tier": tier,
        "finish_rank": rank,
        "draft_slot": n - rank,          # worst (rank n-1) picks 1; best picks n
        "dev_bias": dev_bias,
        "cap_bonus": cap_bonus,
        "comp_picks": comp,
        "won_title": won_title,
    }


def _finish_order(save):
    """Ordered team ids best->worst + the champion id, from last season if it was
    played, else seeded by current power (a fresh league's 'prior finish')."""
    sc = save.get("standings_cache")
    if sc:
        order = [s["id"] for s in sc]
        champ_name = save.get("last_champion", "")
        champ = next((s["id"] for s in sc if s["full"] == champ_name), order[0])
        return order, champ
    ranked = sorted(save["teams"], key=lambda t: -fk.power_rating(t))
    order = [t["id"] for t in ranked]
    return order, order[0]


def compute_scenarios(save):
    order, champ = _finish_order(save)
    n = len(order)
    save["scenarios"] = {tid: scenario_for(rank, n, tid == champ)
                         for rank, tid in enumerate(order)}
    save["last_champion"] = save.get("last_champion") or next(
        (t["full"] for t in save["teams"] if t["id"] == champ), "")
    return save["scenarios"]


def my_scenario(save):
    return save.get("scenarios", {}).get(save["current_team_id"], scenario_for(15, 32, False))


_TIER_TEXT = {
    "champion": {
        "label": "Defending Champions",
        "head": "You're on top of the world - and everyone's coming for you.",
        "challenges": ["Cap is maxed out by your stars' big-money deals",
                       "Several core players are hitting free agency and want raises",
                       "Coordinators are being poached for head-coaching jobs",
                       "You pick LAST in every round of the draft",
                       "Complacency + age: a few veterans are due to regress"],
        "opportunities": ["You have the talent - protect the core that matters most",
                          "A title makes you a destination for veteran-minimum ring-chasers"],
    },
    "contender": {
        "label": "Win-Now Contender",
        "head": "You're close. This is the offseason that pushes you over the top - or back.",
        "challenges": ["Cap space is tight", "Key contributors are up for new deals",
                       "You pick late in the draft"],
        "opportunities": ["One or two right moves makes you the favorite",
                          "Veterans want to join a winner"],
    },
    "middle": {
        "label": "On the Bubble",
        "head": "A swing season. Build smart and you're a playoff team; stand pat and you're stuck.",
        "challenges": ["No margin for a wasted pick or bad signing"],
        "opportunities": ["Solid cap room to add", "A mid-first-round pick",
                          "A comp pick for any free agents you lost"],
    },
    "rebuild": {
        "label": "Rebuild - Attractive Job",
        "head": "Rock bottom last year means a goldmine of opportunity now.",
        "challenges": ["The roster needs talent across the board"],
        "opportunities": ["A top pick in every round", "The most cap space in the league",
                          "Extra compensatory picks", "A young core primed to take a leap"],
    },
}


def scenario_narrative(scenario):
    t = dict(_TIER_TEXT[scenario["tier"]])
    t["draft_slot"] = scenario["draft_slot"]
    t["cap_bonus"] = scenario["cap_bonus"]
    t["comp_picks"] = scenario["comp_picks"]
    return t


# --------------------------------------------------------------------------- #
# Offseason lifecycle + stage machine
# --------------------------------------------------------------------------- #
def offseason_active(save):
    return bool(save.get("offseason"))


def current_stage(save):
    return (save.get("offseason") or {}).get("stage", "recap")


def stage_meta(key):
    return next((s for s in STAGES if s["key"] == key), STAGES[0])


def stage_progress(save):
    """List of {key,title,icon,state} where state in done|current|todo (for the tracker)."""
    cur = current_stage(save)
    if cur == "select":
        cur = "recap"
    ci = STAGE_KEYS.index(cur) if cur in STAGE_KEYS else 0
    out = []
    for i, s in enumerate(STAGES):
        out.append(dict(s, state=("done" if i < ci else "current" if i == ci else "todo")))
    return out


def start_offseason(save, choose_team=False):
    """Open the offseason: compute scenarios, apply the equity shift, set the stage.
    With choose_team, the GM first picks any of the 32 from the scenario board."""
    compute_scenarios(save)
    if not save.get("standings_cache"):
        # seed a finish order so the draft (which picks worst-first) is balanced
        order, _ = _finish_order(save)
        tmap = {t["id"]: t for t in save["teams"]}
        save["standings_cache"] = [
            {"id": tid, "full": tmap[tid]["full"], "conf": tmap[tid]["conference"],
             "div": tmap[tid]["division"], "w": 0, "l": 0} for tid in order]
    _apply_scenario_shift(save)
    save["offseason_mode"] = True               # this save uses the staged offseason loop
    save["offseason"] = {"stage": "select" if choose_team else "recap",
                         "year": save.get("season", 1), "log": []}
    if not choose_team:
        fk.generate_front_office_issues(save)
    fk.write_save(save)
    return save


def pick_team(save, team_id):
    if any(t["id"] == team_id for t in save["teams"]):
        save["current_team_id"] = team_id
        fk._set_expectation(save)
        fk.generate_front_office_issues(save)
        fk._tl(save, save.get("season", 1), "hired", "📝",
               f"Hired as GM of the {fk.current_team(save)['full']}", "Your story begins here.")
        save["offseason"]["stage"] = "recap"
        fk.write_save(save)
        return True
    return False


def advance_stage(save):
    cur = current_stage(save)
    if cur not in STAGE_KEYS:
        return save
    i = STAGE_KEYS.index(cur)
    if cur == "cuts":
        _finalize_camp(save)                 # AI cuts to 53 + safety-trim the user
    if i + 1 < len(STAGE_KEYS):
        save["offseason"]["stage"] = STAGE_KEYS[i + 1]
    if cur == "draft":
        _seed_camp_rosters(save)             # entering cuts: make sure camp rosters exist
    fk.write_save(save)
    return save


def _apply_scenario_shift(save):
    """The equalizer: good teams' aging vets decline, weak teams' young players pop -
    so the league regresses toward the mean and every club can converge."""
    rng = fk._rng(save["seed"] + save.get("season", 1) * 4099 + 7)
    for t in save["teams"]:
        sc = save["scenarios"].get(t["id"])
        if not sc:
            continue
        bias = sc["dev_bias"]
        for p in t["roster"]:
            pot = p.get("potential", p["overall"])
            if bias < 0 and (p["age"] >= 29 or rng.random() < 0.45):
                p["overall"] = max(45, p["overall"] + bias)
            elif bias > 0 and p["age"] <= 26 and pot > p["overall"]:
                p["overall"] = min(pot, p["overall"] + bias)


# --------------------------------------------------------------------------- #
# Stage: Voluntary Workouts - evaluate your talent
# --------------------------------------------------------------------------- #
def workouts_report(save):
    """Per-player evaluation: trajectory (rising/declining/steady) + contract status."""
    team = fk.current_team(save)
    out = []
    for p in sorted(team["roster"], key=lambda x: -x["overall"]):
        pot = p.get("potential", p["overall"])
        age = p["age"]
        if pot - p["overall"] >= 4 and age <= 25:
            traj, tag = "rising", "Ascending"
        elif age >= 30:
            traj, tag = "declining", "Age cliff risk"
        elif pot > p["overall"]:
            traj, tag = "rising", "Room to grow"
        else:
            traj, tag = "steady", "At his ceiling"
        yrs = p.get("contract", {}).get("years", 1)
        out.append({
            "id": p["id"], "name": p["name"], "pos": p["pos"], "number": p.get("number"),
            "age": age, "overall": p["overall"], "potential": pot,
            "traj": traj, "tag": tag,
            "expiring": yrs <= 0, "years": yrs,
            "aav": p.get("contract", {}).get("aav", 0),
        })
    return out


# --------------------------------------------------------------------------- #
# Stage: Re-Sign Your Own - expiring contracts
# --------------------------------------------------------------------------- #
def expiring_players(save):
    return [p for p in fk.current_team(save)["roster"] if p.get("contract", {}).get("years", 1) <= 0]


def let_walk(save, player_id):
    """Release an expiring player to free agency; weaker teams bank a comp pick."""
    team = fk.current_team(save)
    p = next((x for x in team["roster"] if x["id"] == player_id), None)
    if not p or p.get("contract", {}).get("years", 1) > 0:
        return False
    team["roster"] = [x for x in team["roster"] if x["id"] != player_id]
    save.setdefault("free_agents", []).append(p)
    sc = my_scenario(save)
    if sc["comp_picks"] > 0:
        save["offseason"].setdefault("comp_pick_credit", 0)
        save["offseason"]["comp_pick_credit"] += 1
    fk.write_save(save)
    return True


def resign(save, player_id, years, aav):
    """Re-sign one of your expiring players (reuses the agent negotiation)."""
    return fk.negotiate(save, player_id, years, aav)


# --------------------------------------------------------------------------- #
# Stage: Cuts to 53
# --------------------------------------------------------------------------- #
def _seed_camp_rosters(save):
    for t in save["teams"]:
        if len(t["roster"]) > CAMP_KEEP_MAX:
            t["roster"].sort(key=lambda p: -p["overall"])
            del t["roster"][CAMP_KEEP_MAX:]


def camp_count(save):
    return len(fk.current_team(save)["roster"])


def cut_player(save, player_id):
    team = fk.current_team(save)
    p = next((x for x in team["roster"] if x["id"] == player_id), None)
    if not p:
        return False
    team["roster"] = [x for x in team["roster"] if x["id"] != player_id]
    save.setdefault("free_agents", []).append(p)
    fk.write_save(save)
    return True


def _finalize_camp(save):
    """AI teams auto-cut to 53 (best players, keeping position coverage); the user's
    team is safety-trimmed if still over 53."""
    uid = save["current_team_id"]
    for t in save["teams"]:
        if len(t["roster"]) <= ROSTER_FINAL:
            continue
        t["roster"].sort(key=lambda p: -(p["overall"] + fk.POS_WEIGHT.get(p["pos"], 1.0)))
        cut = t["roster"][ROSTER_FINAL:]
        t["roster"] = t["roster"][:ROSTER_FINAL]
        if t["id"] == uid:
            save.setdefault("free_agents", []).extend(cut)


# --------------------------------------------------------------------------- #
# Stage: Kickoff -> hand back to the season sim
# --------------------------------------------------------------------------- #
def ready_to_kick(save):
    return camp_count(save) <= ROSTER_FINAL


def finish_offseason(save):
    """Close the offseason; the caller then runs fk.sim_season(save)."""
    save.pop("offseason", None)
    fk.write_save(save)
    return save


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    s = fk.create_save("offs_test", "Darrel", "scout", "Balanced", seed=7)
    start_offseason(s, choose_team=True)
    # board: tier per team
    board = [(t["full"], s["scenarios"][t["id"]]["tier"], s["scenarios"][t["id"]]["draft_slot"])
             for t in sorted(s["teams"], key=lambda t: s["scenarios"][t["id"]]["finish_rank"])]
    print("Champion scenario:", board[0])
    print("Cellar scenario:", board[-1])
    # pick the champion (hardest)
    champ_id = next(t["id"] for t in s["teams"] if s["scenarios"][t["id"]]["tier"] == "champion")
    pick_team(s, champ_id)
    sc = my_scenario(s)
    print("Picked champion -> tier", sc["tier"], "| draft slot", sc["draft_slot"],
          "| cap bonus", sc["cap_bonus"], "| dev bias", sc["dev_bias"])
    print("Workouts report (top 3):", [(r["name"], r["overall"], r["tag"]) for r in workouts_report(s)[:3]])
    print("Expiring players:", len(expiring_players(s)))
    # walk the stages
    for _ in range(len(STAGE_KEYS)):
        st = current_stage(s)
        if st == "cuts":
            print("Camp roster before cuts:", camp_count(s))
        advance_stage(s)
    print("Final roster after cuts:", camp_count(s), "| ready to kick:", ready_to_kick(s))
    fk.delete_save("offs_test")
    print("OK offseason engine works")
