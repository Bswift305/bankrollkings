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


# Optional keys added by later features; normalized on load so older league files
# (and the strict-undefined templates) never trip over a missing key.
_OPTIONAL_KEYS = {"board": list, "recaps": list, "history": list, "trades": list,
                  "autopilot_log": list, "power_rank_prev": dict,
                  "waivers": list, "waiver_log": list,
                  "draft": dict, "draft_history": list,
                  "paused": False, "season": 1, "champion_name": ""}


def _ensure_keys(lg):
    for k, default in _OPTIONAL_KEYS.items():
        if k not in lg:
            lg[k] = default() if callable(default) else default
    return lg


def load_league(code):
    p = _path(str(code or "").upper())
    if not p.exists():
        return None
    try:
        return _ensure_keys(json.loads(p.read_text(encoding="utf-8")))
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
        "season": 1,
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
    upset = None                              # (power gap, winner, loser)
    for g in league["schedule"]:
        if g["week"] != week:
            continue
        home_win = fk._sim_game(rng, powers[g["home"]], powers[g["away"]])
        win, lose = (g["home"], g["away"]) if home_win else (g["away"], g["home"])
        teams[win].setdefault("record", {"w": 0, "l": 0})["w"] += 1
        teams[lose].setdefault("record", {"w": 0, "l": 0})["l"] += 1
        gap = powers[lose] - powers[win]
        if upset is None or gap > upset[0]:
            upset = (gap, teams[win]["full"], teams[lose]["full"])
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
    _build_recap(league, week, upset, powers)


# --------------------------------------------------------------------------- #
# Waivers: drop a player to the wire; GMs place claims; claims resolve at game day
# in priority order (worst record gets first pick). Unclaimed players clear to FA.
# --------------------------------------------------------------------------- #
def _waiver_priority(league):
    """Ordered uids - worst record (best waiver priority) first."""
    sc = league.get("standings_cache") or []
    rank = {s["id"]: i for i, s in enumerate(sc)}        # 0 = best record
    members = league.get("members", {})
    return sorted(members.keys(), key=lambda uid: -rank.get(members[uid]["team_id"], 999))


def drop_player(league, user_id, player_id):
    m = league.get("members", {}).get(user_id)
    if not m:
        return False
    t = team_by_id(league, m["team_id"])
    p = next((x for x in t["roster"] if x["id"] == player_id), None)
    if not p:
        return False
    t["roster"] = [x for x in t["roster"] if x["id"] != player_id]
    league.setdefault("waivers", []).append({"player": p, "from_team": t["full"], "claims": []})
    save_league(league)
    return True


def claim_player(league, user_id, player_id):
    if user_id not in league.get("members", {}):
        return False
    e = next((w for w in league.get("waivers", []) if w["player"]["id"] == player_id), None)
    if not e:
        return False
    if user_id not in e["claims"]:
        e["claims"].append(user_id)
        save_league(league)
    return True


def _process_waivers(league):
    wire = league.get("waivers", [])
    if not wire:
        return
    priority = _waiver_priority(league)
    log = []
    for e in wire:
        if e["claims"]:
            winner = min(e["claims"], key=lambda u: priority.index(u) if u in priority else 999)
            t = team_by_id(league, league["members"][winner]["team_id"])
            if t:
                t["roster"].append(e["player"])
                log.append(f"{league['members'][winner]['name']} claimed "
                           f"{e['player']['pos']} {e['player']['name']}")
        else:
            league.setdefault("free_agents", []).append(e["player"])   # clears to FA
    league["waivers"] = []
    league["waiver_log"] = log[:8]


def _build_recap(league, week, upset, powers):
    """Auto-generated weekly recap + power rankings (with movement vs last week)."""
    def score(t):
        return powers[t["id"]] + t.get("record", {}).get("w", 0) * 2.0
    ranked = sorted(league["teams"], key=score, reverse=True)
    prev = league.get("power_rank_prev", {})
    rankings = []
    for i, t in enumerate(ranked[:12]):
        old = prev.get(t["id"])
        rankings.append({"rank": i + 1, "id": t["id"], "full": t["full"],
                         "w": t.get("record", {}).get("w", 0), "l": t.get("record", {}).get("l", 0),
                         "move": (0 if old is None else old - i)})
    league["power_rank_prev"] = {t["id"]: i for i, t in enumerate(ranked)}
    leader = ranked[0]
    lw, ll = leader.get("record", {}).get("w", 0), leader.get("record", {}).get("l", 0)
    lines = [f"{leader['full']} lead the power rankings at {lw}-{ll}."]
    if upset and upset[0] > 1:
        lines.append(f"Upset of the week: {upset[1]} took down {upset[2]}.")
    risers = [r for r in rankings if r["move"] > 0]
    if risers:
        top = max(risers, key=lambda r: r["move"])
        lines.append(f"{top['full']} climbed {top['move']} spot{'s' if top['move'] != 1 else ''} in the rankings.")
    league.setdefault("recaps", []).insert(0, {
        "week": week, "headline": f"Week {week} — {leader['full']} on top",
        "lines": lines, "rankings": rankings})
    league["recaps"] = league["recaps"][:6]


def post_message(league, user_id, text):
    """A league member posts to the message board (trash talk)."""
    m = league.get("members", {}).get(user_id)
    if not m:
        return False
    text = str(text or "").strip()[:280]
    if not text:
        return False
    league.setdefault("board", []).insert(0, {
        "id": _new_trade_id(), "uid": user_id, "name": m["name"],
        "text": text, "at": _iso(_now())})
    league["board"] = league["board"][:60]
    save_league(league)
    return True


def advance_league(league):
    """Run one game day: sim the current week, advance the clock, reset readiness."""
    if league["status"] == "complete":
        return league
    if league["status"] == "open":
        league["status"] = "active"
    _process_waivers(league)        # resolve pending waiver claims before the games
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
        complete_season(league)
    else:
        league["next_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    save_league(league)
    return league


# --------------------------------------------------------------------------- #
# Season awards + multi-season dynasty
# --------------------------------------------------------------------------- #
def complete_season(league):
    """Wrap a season: crown the champion, hand out awards, append to the dynasty
    history. (Champion = best regular-season record this league.)"""
    league["status"] = "complete"
    league["next_deadline"] = _iso(_now() + timedelta(days=3650))
    sc = league.get("standings_cache", [])
    if not sc:
        return league
    champ = sc[0]
    mvp, mvp_team = None, ""
    for t in league["teams"]:                       # MVP = best player on a top-8 team
        if not any(s["id"] == t["id"] for s in sc[:8]):
            continue
        for p in t["roster"]:
            if mvp is None or p["overall"] > mvp["overall"]:
                mvp, mvp_team = p, t["full"]
    best_gm = None
    for uid, m in league.get("members", {}).items():
        row = next((s for s in sc if s["id"] == m["team_id"]), None)
        if row and (best_gm is None or row["w"] > best_gm["w"]):
            best_gm = {"name": m["name"], "team": row["full"], "w": row["w"], "l": row["l"]}
    league.setdefault("history", []).insert(0, {
        "season": league.get("season", 1),
        "champion": champ["full"], "record": f"{champ['w']}-{champ['l']}",
        "mvp": mvp["name"] if mvp else "—", "mvp_pos": mvp["pos"] if mvp else "",
        "mvp_team": mvp_team, "mvp_ovr": mvp["overall"] if mvp else 0,
        "best_gm": best_gm})
    league["champion_name"] = champ["full"]
    save_league(league)
    return league


def start_next_season(league):
    """Commissioner rolls the league into a fresh season: rosters + members carry
    over, records/schedule/recaps reset, the clock restarts."""
    if league.get("status") != "complete":
        return False
    league["season"] = league.get("season", 1) + 1
    league["week"] = 1
    league["status"] = "active"
    for t in league["teams"]:
        t["record"] = {"w": 0, "l": 0}
    league["schedule"] = fk.make_schedule(league["seed"] + league["season"],
                                          [t["id"] for t in league["teams"]])
    league["standings_cache"] = []
    league["results_log"] = []
    league["recaps"] = []
    league.pop("power_rank_prev", None)
    for m in league["members"].values():
        m["ready"] = False
    league["next_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    save_league(league)
    return True


# --------------------------------------------------------------------------- #
# Live, on-the-clock multiplayer ROOKIE DRAFT. Order = reverse standings (worst
# picks first). Each human pick has a clock; idle GMs are auto-picked (best
# available) by the lazy-advance/tick, so the draft never stalls. AI teams pick
# instantly. Reuses fk's prospect class + scouting + rookie conversion.
# --------------------------------------------------------------------------- #
LEAGUE_DRAFT_ROUNDS = 5
DRAFT_PICK_SECONDS = 90


def _draft_on_clock(draft):
    if draft["ptr"] >= draft["rounds"] * len(draft["order"]):
        return None
    return draft["order"][draft["ptr"] % len(draft["order"])]


def _draft_round_pick(draft):
    n = len(draft["order"])
    return draft["ptr"] // n + 1, draft["ptr"] % n + 1


def _draft_is_human(league, team_id):
    return any(m["team_id"] == team_id for m in league.get("members", {}).values())


def draft_available(draft):
    return sorted(draft["class"], key=lambda p: -p.get("grade", 0))


def _draft_take(league, team_id, prospect):
    t = team_by_id(league, team_id)
    draft = league["draft"]
    rnd, _ = _draft_round_pick(draft)
    t["roster"].append(fk._make_rookie(prospect))
    draft["class"] = [p for p in draft["class"] if p["id"] != prospect["id"]]
    draft["log"].insert(0, {"round": rnd, "team": t["full"], "name": prospect["name"],
                            "pos": prospect["pos"], "ovr": prospect.get("true_ovr", 0)})
    draft["log"] = draft["log"][:60]
    draft["ptr"] += 1


def _draft_autoadvance(league):
    """Auto-pick for AI teams until a human is on the clock (set their deadline) or
    the draft ends."""
    draft = league["draft"]
    while True:
        oc = _draft_on_clock(draft)
        if oc is None:
            _finish_draft(league)
            return
        if _draft_is_human(league, oc):
            draft["pick_deadline"] = _iso(_now() + timedelta(seconds=draft["pick_seconds"]))
            return
        avail = draft_available(draft)
        if avail:
            _draft_take(league, oc, avail[0])
        else:
            draft["ptr"] += 1


def _finish_draft(league):
    draft = league.get("draft") or {}
    draft["active"] = False
    league.setdefault("draft_history", []).insert(
        0, {"season": league.get("season", 1), "log": draft.get("log", [])[:32]})


def start_draft(league):
    if (league.get("draft") or {}).get("active"):
        return False
    rng = random.Random(league["seed"] + league.get("season", 1) * 131 + 7)
    cls = fk.generate_draft_class(rng)
    for p in cls:
        fk._scout(rng, p, 70)                       # league-wide moderate scouting
    sc = league.get("standings_cache") or []
    order = ([s["id"] for s in reversed(sc)] if sc
             else [t["id"] for t in sorted(league["teams"], key=fk.power_rating)])
    league["draft"] = {"active": True, "class": cls, "order": order,
                       "rounds": LEAGUE_DRAFT_ROUNDS, "ptr": 0,
                       "pick_seconds": DRAFT_PICK_SECONDS,
                       "pick_deadline": _iso(_now() + timedelta(seconds=DRAFT_PICK_SECONDS)),
                       "log": []}
    _draft_autoadvance(league)                      # blow through any leading AI picks
    save_league(league)
    return True


def draft_pick(league, user_id, prospect_id):
    draft = league.get("draft")
    if not draft or not draft.get("active"):
        return False, "No live draft is running."
    oc = _draft_on_clock(draft)
    m = league.get("members", {}).get(user_id)
    if not m or m["team_id"] != oc:
        return False, "You're not on the clock."
    prospect = next((p for p in draft["class"] if p["id"] == prospect_id), None)
    if not prospect:
        return False, "That prospect is already gone."
    _draft_take(league, oc, prospect)
    _draft_autoadvance(league)
    save_league(league)
    return True, f"Drafted {prospect['name']}."


def draft_check(league):
    """Lazy/tick advance: auto-pick (best available) for any human GM whose clock
    expired, then roll through AI picks. Keeps the draft moving when GMs are away."""
    draft = league.get("draft")
    if not draft or not draft.get("active"):
        return league
    changed, guard = False, 0
    while draft.get("active") and guard < 600:
        oc = _draft_on_clock(draft)
        if oc is None:
            _finish_draft(league)
            changed = True
            break
        if _draft_is_human(league, oc) and _parse(draft["pick_deadline"]) > _now():
            break                                   # human still on the clock with time
        avail = draft_available(draft)
        if avail:
            _draft_take(league, oc, avail[0])
        else:
            draft["ptr"] += 1
        _draft_autoadvance(league)
        changed = True
        guard += 1
    if changed:
        save_league(league)
    return league


def draft_seconds_left(league):
    draft = league.get("draft") or {}
    if not draft.get("active"):
        return 0
    return max(0, int((_parse(draft["pick_deadline"]) - _now()).total_seconds()))


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
        if not lg:
            continue
        if (lg.get("draft") or {}).get("active"):       # keep live drafts moving
            draft_check(lg)
        if not lg.get("paused") and lg["status"] != "complete" and time_left(lg) <= 0:
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
# GM-to-GM trades: one human GM offers players to another; the target accepts or
# rejects; if a (third-party) commissioner runs the league the accepted deal goes
# to commish review before it processes (veto power). Reuses fk.trade_value to
# grade fairness for both sides.
# --------------------------------------------------------------------------- #
def _new_trade_id():
    return "tr" + "".join(random.choices(string.ascii_lowercase + string.digits, k=7))


def _owned_by(league, pid, team_id):
    t = team_by_id(league, team_id)
    return bool(t and any(p["id"] == pid for p in t["roster"]))


def player_by_id(league, pid):
    for t in league["teams"]:
        for p in t["roster"]:
            if p["id"] == pid:
                return p
    return None


def trade_partners(league, user_id):
    """Other human GMs (uid, name, team) you can trade with."""
    out = []
    for uid, m in league.get("members", {}).items():
        if uid == user_id:
            continue
        t = team_by_id(league, m["team_id"])
        out.append({"uid": uid, "name": m["name"], "team": t["full"] if t else "", "team_id": m["team_id"]})
    return out


def _grade_trade(league, give_ids, get_ids):
    """Fairness from the PROPOSER's view: value received vs value sent (A..F)."""
    out = sum(fk.trade_value(player_by_id(league, p)) for p in give_ids if player_by_id(league, p))
    inc = sum(fk.trade_value(player_by_id(league, p)) for p in get_ids if player_by_id(league, p))
    if out <= 0:
        return "C"
    ratio = inc / out
    return ("A" if ratio >= 1.25 else "B" if ratio >= 1.05 else "C" if ratio >= 0.9
            else "D" if ratio >= 0.75 else "F")


def propose_gm_trade(league, from_uid, to_uid, give_ids, get_ids):
    members = league.get("members", {})
    if from_uid not in members or to_uid not in members or from_uid == to_uid:
        return False, "Invalid trade partner."
    from_tid, to_tid = members[from_uid]["team_id"], members[to_uid]["team_id"]
    give = [pid for pid in give_ids if _owned_by(league, pid, from_tid)]
    get = [pid for pid in get_ids if _owned_by(league, pid, to_tid)]
    if not give or not get:
        return False, "Pick at least one player from each side."
    trade = {"id": _new_trade_id(), "from": from_uid, "to": to_uid,
             "from_name": members[from_uid]["name"], "to_name": members[to_uid]["name"],
             "give": give, "get": get, "grade": _grade_trade(league, give, get),
             "status": "offered", "created": _iso(_now())}
    league.setdefault("trades", []).insert(0, trade)
    league["trades"] = league["trades"][:40]
    save_league(league)
    return True, "Offer sent."


def _apply_gm_trade(league, trade):
    ft = team_by_id(league, league["members"][trade["from"]]["team_id"])
    tt = team_by_id(league, league["members"][trade["to"]]["team_id"])
    if not ft or not tt:
        return False
    if not all(_owned_by(league, p, ft["id"]) for p in trade["give"]) or \
       not all(_owned_by(league, p, tt["id"]) for p in trade["get"]):
        return False
    give = [p for p in ft["roster"] if p["id"] in trade["give"]]
    get = [p for p in tt["roster"] if p["id"] in trade["get"]]
    ft["roster"] = [p for p in ft["roster"] if p["id"] not in trade["give"]] + get
    tt["roster"] = [p for p in tt["roster"] if p["id"] not in trade["get"]] + give
    return True


def _has_third_party_commish(league, trade):
    c = league.get("commissioner")
    return bool(c and c in league.get("members", {}) and c not in (trade["from"], trade["to"]))


def respond_trade(league, trade_id, user_id, accept):
    tr = next((t for t in league.get("trades", []) if t["id"] == trade_id), None)
    if not tr or tr["status"] != "offered" or tr["to"] != user_id:
        return False, "Trade not available."
    if not accept:
        tr["status"] = "rejected"
        save_league(league)
        return True, "Trade rejected."
    if _has_third_party_commish(league, tr):
        tr["status"] = "review"
        save_league(league)
        return True, "Accepted - awaiting commissioner approval."
    if _apply_gm_trade(league, tr):
        tr["status"] = "accepted"
        save_league(league)
        return True, "Trade complete!"
    tr["status"] = "expired"
    save_league(league)
    return False, "Players no longer available."


def review_trade(league, trade_id, commish_uid, approve):
    if commish_uid != league.get("commissioner"):
        return False, "Only the commissioner can review trades."
    tr = next((t for t in league.get("trades", []) if t["id"] == trade_id), None)
    if not tr or tr["status"] != "review":
        return False, "Nothing to review."
    if not approve:
        tr["status"] = "vetoed"
        save_league(league)
        return True, "Trade vetoed."
    if _apply_gm_trade(league, tr):
        tr["status"] = "accepted"
        save_league(league)
        return True, "Trade approved."
    tr["status"] = "expired"
    save_league(league)
    return False, "Players no longer available."


def cancel_trade(league, trade_id, user_id):
    tr = next((t for t in league.get("trades", []) if t["id"] == trade_id), None)
    if tr and tr["status"] == "offered" and tr["from"] == user_id:
        tr["status"] = "cancelled"
        save_league(league)
        return True
    return False


def trades_for(league, user_id):
    trades = league.get("trades", [])
    incoming = [t for t in trades if t["to"] == user_id and t["status"] == "offered"]
    outgoing = [t for t in trades if t["from"] == user_id and t["status"] in ("offered", "review")]
    review = ([t for t in trades if t["status"] == "review"]
              if user_id == league.get("commissioner") else [])
    history = [t for t in trades if t["status"] in ("accepted", "rejected", "vetoed", "cancelled", "expired")
               and (t["from"] == user_id or t["to"] == user_id or user_id == league.get("commissioner"))][:8]
    return {"incoming": incoming, "outgoing": outgoing, "review": review, "history": history}


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
