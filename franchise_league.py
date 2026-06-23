"""Franchise Kings - MULTIPLAYER commissioner leagues (foundation / M1).

A shared league multiple human GMs join (one team each; AI runs the rest), with a
REAL-TIME weekly clock: every `cadence_days` a game day fires automatically -
games sim, standings update, the week advances. Teams whose manager didn't act go
on AUTO-PILOT (reuses the single-player AI + each team's ideology later).

Storage: one JSON per league at data/franchise_leagues/<code>.json (shared state,
NOT per-user). Reuses franchise_kings for the 32-team world + game sim.

This module is the foundation: league lifecycle, membership, the clock, and the
weekly auto-sim. Per-team in-league management + social features build on top.
"""
from __future__ import annotations

import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import franchise_kings as fk

BASE_DIR = Path(__file__).resolve().parent
LEAGUES_DIR = BASE_DIR / "data" / "franchise_leagues"
_FMT = "%Y-%m-%dT%H:%M:%S"


# --------------------------------------------------------------------------- #
# Time helpers (server-side; datetime is fine here)
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now()


def _iso(dt):
    return dt.strftime(_FMT)


def _parse(s):
    try:
        return datetime.strptime(s, _FMT)
    except (TypeError, ValueError):
        return _now()


def time_left(league):
    """Seconds until the next game day (negative if overdue)."""
    return (_parse(league["next_deadline"]) - _now()).total_seconds()


def deadline_label(league):
    if league.get("paused"):
        return "Paused by commissioner"
    secs = time_left(league)
    if secs <= 0:
        return "Game day is processing..."
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h to game day"
    if h:
        return f"{h}h {m}m to game day"
    return f"{m}m to game day"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _path(code):
    return LEAGUES_DIR / f"{code}.json"


def _new_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not _path(code).exists():
            return code


def load_league(code):
    p = _path(str(code or "").upper())
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_league(league):
    LEAGUES_DIR.mkdir(parents=True, exist_ok=True)
    _path(league["id"]).write_text(json.dumps(league), encoding="utf-8")


def leagues_for_user(user_id):
    out = []
    if not LEAGUES_DIR.exists():
        return out
    for f in LEAGUES_DIR.glob("*.json"):
        try:
            lg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if user_id in lg.get("members", {}) or lg.get("commissioner") == user_id:
            out.append(lg)
    out.sort(key=lambda l: l.get("created_at", ""), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def create_league(commissioner_id, name, cadence_days=3, gm_name="Commissioner", seed=None):
    seed = seed if seed is not None else random.randint(1, 10 ** 9)
    teams, free_agents = fk.new_league(seed)
    cadence_days = max(1, min(7, int(cadence_days or 3)))
    # the commissioner claims a (bottom-third) team to start
    weak = sorted(teams, key=fk.power_rating)[6]
    league = {
        "id": _new_code(),
        "name": (name or "BRK League").strip()[:48],
        "commissioner": commissioner_id,
        "cadence_days": cadence_days,
        "seed": seed,
        "status": "open",           # open -> active -> complete
        "week": 1,
        "next_deadline": _iso(_now() + timedelta(days=cadence_days)),
        "teams": teams,
        "free_agents": free_agents,
        "schedule": fk.make_schedule(seed, [t["id"] for t in teams]),
        "standings_cache": [],
        "results_log": [],
        "members": {
            commissioner_id: {"team_id": weak["id"], "name": (gm_name or "Commissioner")[:40],
                              "joined": _iso(_now()), "ready": False, "is_commish": True}
        },
        "created_at": _iso(_now()),
    }
    save_league(league)
    return league


def open_team_ids(league):
    claimed = {m["team_id"] for m in league["members"].values()}
    return [t["id"] for t in league["teams"] if t["id"] not in claimed]


def join_league(code, user_id, gm_name="GM", team_id=None):
    league = load_league(code)
    if not league:
        return None, "League not found - check the code."
    if user_id in league["members"]:
        return league, "You're already in this league."
    openers = open_team_ids(league)
    if not openers:
        return None, "This league is full."
    pick = team_id if team_id in openers else openers[0]
    league["members"][user_id] = {"team_id": pick, "name": (gm_name or "GM")[:40],
                                  "joined": _iso(_now()), "ready": False, "is_commish": False}
    save_league(league)
    return league, "Joined! Your team is set."


def team_by_id(league, team_id):
    return next((t for t in league["teams"] if t["id"] == team_id), None)


def my_membership(league, user_id):
    return league.get("members", {}).get(user_id)


# --------------------------------------------------------------------------- #
# The weekly clock: sim ONE week, advance, reset, reschedule
# --------------------------------------------------------------------------- #
def _sim_week(league):
    week = league["week"]
    rng = random.Random(league["seed"] + week * 1009)
    teams = {t["id"]: t for t in league["teams"]}
    powers = {tid: fk.power_rating(t) for tid, t in teams.items()}
    results = []
    for g in league["schedule"]:
        if g["week"] != week:
            continue
        home_win = fk._sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win].setdefault("record", {"w": 0, "l": 0})["w"] += 1
        teams[lose].setdefault("record", {"w": 0, "l": 0})["l"] += 1
        results.append({"home": teams[g["home"]]["full"], "away": teams[g["away"]]["full"],
                        "winner": teams[win]["full"]})
    standings = sorted(league["teams"],
                       key=lambda t: (t.get("record", {}).get("w", 0), powers[t["id"]]), reverse=True)
    league["standings_cache"] = [
        {"id": t["id"], "full": t["full"], "conf": t["conference"], "div": t["division"],
         "w": t.get("record", {}).get("w", 0), "l": t.get("record", {}).get("l", 0)}
        for t in standings]
    league["results_log"].insert(0, {"week": week, "games": results[:16]})
    league["results_log"] = league["results_log"][:8]


def advance_league(league):
    """Run one game day: sim the current week, advance the clock, reset readiness."""
    if league["status"] == "complete":
        return league
    if league["status"] == "open":
        league["status"] = "active"
    # auto-pilot any human GM who didn't lock in: one philosophy-driven move each
    ap = []
    for uid, m in list(league["members"].items()):
        if not m.get("ready"):
            note = auto_pilot_member(league, uid)
            if note:
                ap.append(f"{m['name']}: {note}")
    league["autopilot_log"] = ap[:8]
    _sim_week(league)
    league["week"] += 1
    for m in league["members"].values():
        m["ready"] = False
        m.pop("autopilot_note", None)
    if league["week"] > fk.REG_GAMES:
        league["status"] = "complete"
        league["next_deadline"] = _iso(_now() + timedelta(days=3650))
    else:
        league["next_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    save_league(league)
    return league


def check_and_advance(league):
    """Lazy auto-advance: if the deadline passed, run game day (may catch up several
    weeks if nobody loaded the league for a while). Returns the (updated) league."""
    if league and league.get("paused"):
        return league
    guard = 0
    while league and league["status"] != "complete" and time_left(league) <= 0 and guard < 30:
        league = advance_league(league)
        guard += 1
    return league


def run_due_leagues():
    """Scheduler entry point (a systemd timer / tick script calls this): advance
    every league whose deadline has passed, even if nobody's viewing it."""
    advanced = 0
    if not LEAGUES_DIR.exists():
        return advanced
    for f in list(LEAGUES_DIR.glob("*.json")):
        lg = load_league(f.stem)
        if lg and not lg.get("paused") and lg["status"] != "complete" and time_left(lg) <= 0:
            check_and_advance(lg)
            advanced += 1
    return advanced


# --------------------------------------------------------------------------- #
# Commissioner tools
# --------------------------------------------------------------------------- #
def update_settings(league, name=None, cadence_days=None):
    if name and str(name).strip():
        league["name"] = str(name).strip()[:48]
    if cadence_days:
        league["cadence_days"] = max(1, min(7, int(cadence_days)))
    save_league(league)
    return league


def set_paused(league, paused):
    league["paused"] = bool(paused)
    if not paused:                          # resuming restarts the clock fresh
        league["next_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    save_league(league)
    return league


def remove_member(league, target_uid):
    """Drop a GM; their team reverts to AI and the slot reopens for a new human.
    The commissioner cannot be removed."""
    if target_uid == league.get("commissioner"):
        return False
    if target_uid in league.get("members", {}):
        del league["members"][target_uid]
        save_league(league)
        return True
    return False


# --------------------------------------------------------------------------- #
# Per-team management in a league: reuse the single-player engine via an adapter
# that points the engine at the SHARED league teams/free-agents, then syncs back.
# --------------------------------------------------------------------------- #
def member_save(league, user_id):
    """A save-shaped view of one member's team, backed by the shared league lists
    (mutations to team rosters stick; reassigned keys are synced by sync_member)."""
    m = league.get("members", {}).get(user_id)
    if not m:
        return None
    m.setdefault("gm", {"name": m.get("name", "GM"), "philosophy": "Balanced",
                        "ratings": {k: 50 for k in ("drafting", "trading", "free_agency",
                                                    "cap", "staff", "media", "owner")},
                        "owner_trust": 55, "fan_support": 50, "reputation": 50,
                        "titles": 0, "career": []})
    m.setdefault("staff", {})
    m.setdefault("business", {"cash": 40.0, "fan_happiness": 50, "stadium": 1,
                              "facility": 1, "ticket": "normal"})
    return {
        "user_id": f"__mp_{league['id']}_{user_id}",   # engine write target (junk; deleted)
        "teams": league["teams"],
        "free_agents": league["free_agents"],
        "current_team_id": m["team_id"],
        "seed": league["seed"],
        "season": league.get("week", 1),
        "gm": m["gm"], "staff": m["staff"], "business": m["business"],
        "last_nego": m.get("last_nego"), "last_trade": m.get("last_trade"),
    }


def sync_member(league, user_id, save):
    """Persist the parts the engine reassigned (free agents + this member's state)
    back into the shared league, and drop the engine's throwaway solo file."""
    m = league.get("members", {}).get(user_id)
    if not m:
        return
    league["free_agents"] = save.get("free_agents", league["free_agents"])
    m["gm"] = save.get("gm", m.get("gm"))
    m["staff"] = save.get("staff", {})
    m["business"] = save.get("business", m.get("business"))
    m["last_nego"] = save.get("last_nego")
    m["last_trade"] = save.get("last_trade")
    save_league(league)
    fk.delete_save(save["user_id"])


def set_ready(league, user_id, ready=True):
    m = league.get("members", {}).get(user_id)
    if m:
        m["ready"] = bool(ready)
        save_league(league)
    return league


# --------------------------------------------------------------------------- #
# Auto-pilot: if a GM doesn't lock in before game day, the AI makes ONE
# philosophy-driven roster move for them so the team doesn't stagnate.
# --------------------------------------------------------------------------- #
def auto_pilot_member(league, user_id):
    save = member_save(league, user_id)
    if not save:
        return None
    team = fk.current_team(save)
    phil = league["members"][user_id].get("gm", {}).get("philosophy", "Balanced")
    best_at = {}
    for p in team["roster"]:
        best_at[p["pos"]] = max(best_at.get(p["pos"], 0), p["overall"])
    # weakest starting position = lowest "best player" among required slots
    target = min(fk.ROSTER, key=lambda pos: best_at.get(pos, 0))

    def value(p):
        ovr = p["overall"]
        pot = p.get("potential", ovr)
        age = p.get("age", 27)
        if phil == "Analytics":          # upside + youth, value over cost
            return ovr + (pot - ovr) * 0.6 - max(0, age - 26) * 0.5
        if phil == "Old School":         # proven prime veterans
            return ovr - abs(age - 28) * 0.3
        return ovr + (pot - ovr) * 0.25  # Balanced

    pool = [p for p in save["free_agents"] if p["pos"] == target] or save["free_agents"]
    pool = sorted(pool, key=value, reverse=True)
    room = fk.CAP_TOTAL - fk.cap_used(team)
    for fa in pool:
        demand = (fa.get("demand") or {}).get("aav", fa["contract"]["aav"])
        if demand <= room and fa["overall"] >= best_at.get(fa["pos"], 0):
            res = fk.negotiate(save, fa["id"], (fa.get("demand") or {}).get("years", 3), demand)
            if res.get("status") == "accepted":
                note = f"signed {fa['pos']} {fa['name']} ({fa['overall']} OVR)"
                league["members"][user_id]["autopilot_note"] = note
                sync_member(league, user_id, save)
                return note
    league["members"][user_id]["autopilot_note"] = "stood pat (no upgrade fit the cap)"
    save_league(league)
    return None


# --------------------------------------------------------------------------- #
# CLI self-test:  python franchise_league.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    lg = create_league("commish_user", "Test League", cadence_days=3, gm_name="Darrel")
    print("Created league", lg["id"], "| cadence", lg["cadence_days"], "days | teams", len(lg["teams"]))
    print("Commish team:", fk.team_by_id(lg, lg["members"]["commish_user"]["team_id"])["full"]
          if False else team_by_id(lg, lg["members"]["commish_user"]["team_id"])["full"])
    lg2, msg = join_league(lg["id"], "player2", "Rival GM")
    print("Join:", msg, "| open teams left:", len(open_team_ids(lg2)))
    # force the deadline into the past and auto-advance a few weeks
    lg2["next_deadline"] = _iso(_now() - timedelta(seconds=1))
    for _ in range(3):
        lg2["next_deadline"] = _iso(_now() - timedelta(seconds=1))
        lg2 = check_and_advance(lg2)
    print("After 3 game days -> week", lg2["week"], "| top of standings:",
          lg2["standings_cache"][0]["full"], lg2["standings_cache"][0]["w"], "-", lg2["standings_cache"][0]["l"])
    print("Latest results week", lg2["results_log"][0]["week"], "->", lg2["results_log"][0]["games"][0])
    _path(lg["id"]).unlink()
    print("OK multiplayer league foundation works")
