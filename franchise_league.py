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
                  "draft": dict, "draft_history": list, "offseason": dict, "leaders": list,
                  "playoffs": dict, "picks": list, "potw": dict, "all_pro": list,
                  "records": dict, "career_records": dict,
                  "hall_of_fame": list, "retirements": list, "news": list,
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
    init_picks(league)                          # each team owns its 7 picks for the next draft
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
    week_stars = []
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
        gstars = []                           # box-score standouts for this game
        for tid in (g["home"], g["away"]):
            for pos in ("QB", "RB", "WR"):
                sp = fk.game_starter(teams[tid], pos)
                if sp:
                    line, score = fk.game_line(sp, tid == win, rng)
                    gstars.append({"name": sp["name"], "pos": pos, "team": teams[tid]["name"],
                                   "pid": sp["id"], "line": line, "score": score})
        star = max(gstars, key=lambda s: s["score"]) if gstars else None
        week_stars.extend(gstars)
        results.append({"home": teams[g["home"]]["full"], "away": teams[g["away"]]["full"],
                        "winner": teams[win]["full"],
                        "star": {k: star[k] for k in ("name", "pos", "team", "line", "pid")} if star else None})
    if week_stars:
        p = max(week_stars, key=lambda s: s["score"])
        league["potw"] = {"week": week, "name": p["name"], "pos": p["pos"],
                          "team": p["team"], "line": p["line"], "pid": p["pid"]}
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


def _league_news(league, week):
    """GridIron Network weekly headlines from this game day's events."""
    items = []
    rc = league.get("recaps", [])
    if rc:
        for line in rc[0]["lines"][:3]:
            items.append({"tag": "RECAP", "head": line, "body": ""})
    potw = league.get("potw")
    if potw and potw.get("week") == week:
        items.append({"tag": "POTW", "head": f"Player of the Week: {potw['pos']} {potw['name']}",
                      "body": f"{potw['line']} for the {potw['team']}."})
    for t in (league.get("trades") or []):
        if t.get("status") == "accepted" and not t.get("_newsed"):
            items.append({"tag": "TRADE", "head": f"Trade alert: {t['from_name']} and {t['to_name']} make a deal",
                          "body": ""})
            t["_newsed"] = True
    for line in (league.get("waiver_log") or [])[:2]:
        items.append({"tag": "WAIVER", "head": line, "body": ""})
    if items:
        league["news"] = ([{"week": week, **it} for it in items] + league.get("news", []))[:24]


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
    _league_news(league, league["week"])        # GridIron Network headlines
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
def run_league_playoffs(league):
    """NFL-style postseason: top 7 per conference, #1 bye, Wild Card -> Divisional
    (reseeded) -> Conference Championship -> the title game. Returns a displayable
    bracket + the champion (the team that wins it, not the best record)."""
    rng = random.Random(league["seed"] + league.get("season", 1) * 7919 + 13)
    teams = {t["id"]: t for t in league["teams"]}
    powers = {tid: fk.power_rating(t) for tid, t in teams.items()}
    sc = league.get("standings_cache") or []
    nm = lambda tid: teams[tid]["full"]
    game = lambda a, b: a if fk._sim_game(rng, powers[a], powers[b]) else b   # a = higher seed (home)

    def matchup(a, b, so):
        w = game(a, b)
        return {"sa": so[a], "ta": nm(a), "sb": so[b], "tb": nm(b), "w": nm(w), "wid": w}

    conf_champs, brackets = {}, {}
    for conf in fk.CONFERENCES:
        seeds = [s["id"] for s in sc if s.get("conf") == conf][:7]
        if len(seeds) < 7:
            extra = sorted([t["id"] for t in league["teams"]
                            if t["conference"] == conf and t["id"] not in seeds], key=lambda x: -powers[x])
            seeds = (seeds + extra)[:7]
        so = {tid: i + 1 for i, tid in enumerate(seeds)}
        wc = [matchup(seeds[1], seeds[6], so), matchup(seeds[2], seeds[5], so), matchup(seeds[3], seeds[4], so)]
        adv = sorted([seeds[0]] + [g["wid"] for g in wc], key=lambda tid: so[tid])
        dv = [matchup(adv[0], adv[3], so), matchup(adv[1], adv[2], so)]
        fin = sorted([dv[0]["wid"], dv[1]["wid"]], key=lambda tid: so[tid])
        cc = matchup(fin[0], fin[1], so)
        brackets[conf] = [{"name": "Wild Card", "games": wc},
                          {"name": "Divisional", "games": dv},
                          {"name": conf + " Championship", "games": [cc]}]
        conf_champs[conf] = cc["wid"]
    a_id, n_id = conf_champs["American"], conf_champs["National"]
    sb_w = game(a_id, n_id) if powers[a_id] >= powers[n_id] else game(n_id, a_id)
    return {"brackets": brackets, "champion": nm(sb_w), "champion_id": sb_w,
            "runner_up": nm(n_id if sb_w == a_id else a_id),
            "sb": {"ta": nm(a_id), "tb": nm(n_id), "w": nm(sb_w)}}


def complete_season(league):
    """Wrap a season: run the playoffs, crown the champion, hand out awards, append
    to the dynasty history. (Champion = who wins the postseason.)"""
    league["status"] = "complete"
    league["next_deadline"] = _iso(_now() + timedelta(days=3650))
    sc = league.get("standings_cache", [])
    if not sc:
        return league
    league["playoffs"] = run_league_playoffs(league)
    champ = next((s for s in sc if s["id"] == league["playoffs"]["champion_id"]), sc[0])
    fk.assign_season_stats(league["teams"], {s["id"]: s["w"] for s in sc},
                           league["seed"] + league.get("season", 1), season=league.get("season", 1))
    league["leaders"] = fk.stat_leaders(league["teams"])
    league["all_pro"] = fk.all_pro_team(league["teams"])
    fk.update_records(league, league["teams"], league.get("season", 1))
    mvp = fk.stat_mvp(league["teams"]) or {}        # MVP earned by production, not rating
    best_gm = None
    for uid, m in league.get("members", {}).items():
        row = next((s for s in sc if s["id"] == m["team_id"]), None)
        if row and (best_gm is None or row["w"] > best_gm["w"]):
            best_gm = {"name": m["name"], "team": row["full"], "w": row["w"], "l": row["l"]}
    league.setdefault("history", []).insert(0, {
        "season": league.get("season", 1),
        "champion": champ["full"], "record": f"{champ['w']}-{champ['l']}",
        "runner_up": league["playoffs"]["runner_up"],
        "mvp": mvp.get("name", "—"), "mvp_pos": mvp.get("pos", ""),
        "mvp_team": mvp.get("team", ""), "mvp_ovr": mvp.get("ovr", 0),
        "mvp_line": mvp.get("line", ""), "best_gm": best_gm})
    league["champion_name"] = champ["full"]
    begin_offseason(league)                 # roll straight into the phased offseason
    return league


# --------------------------------------------------------------------------- #
# The phased, NFL-calendar OFFSEASON. After a season ends the league walks a real
# sequence of windows, each on the real-time clock (auto-advances on its deadline,
# or the commissioner pushes it forward): Franchise Tag -> Legal Tampering -> Free
# Agency -> Draft -> OTAs/Minicamp (development) -> Cut-Down Day -> next kickoff.
# --------------------------------------------------------------------------- #
OFFSEASON_PHASES = [
    {"key": "tag",         "title": "Franchise Tag",   "icon": "🏷",
     "blurb": "Tag one expiring player to keep him a year at a premium salary."},
    {"key": "tamper",      "title": "Legal Tampering", "icon": "🤝",
     "blurb": "Scout the market - signing opens when free agency does."},
    {"key": "free_agency", "title": "Free Agency",     "icon": "💰",
     "blurb": "The market is open - sign free agents from your team page."},
    {"key": "draft",       "title": "The Draft",       "icon": "🎓",
     "blurb": "The 7-round rookie draft - worst record picks first."},
    {"key": "otas",        "title": "OTAs & Minicamp", "icon": "📈",
     "blurb": "Players age and develop toward their ceilings."},
    {"key": "cutdown",     "title": "Cut-Down Day",    "icon": "✂",
     "blurb": "Every roster trims to the 53-man limit, then the season kicks off."},
]
OFFSEASON_KEYS = [p["key"] for p in OFFSEASON_PHASES]


def begin_offseason(league):
    league["offseason"] = {"active": True, "phase": "tag", "tags": {}, "risers": [],
                           "phase_deadline": _iso(_now() + timedelta(days=league["cadence_days"]))}
    save_league(league)
    return league


def offseason_phase(league):
    return (league.get("offseason") or {}).get("phase")


def offseason_progress(league):
    cur = offseason_phase(league)
    ci = OFFSEASON_KEYS.index(cur) if cur in OFFSEASON_KEYS else 0
    return [dict(p, state=("done" if i < ci else "current" if i == ci else "todo"))
            for i, p in enumerate(OFFSEASON_PHASES)]


def offseason_deadline_label(league):
    os = league.get("offseason") or {}
    secs = (_parse(os.get("phase_deadline", _iso(_now()))) - _now()).total_seconds()
    if secs <= 0:
        return "advancing…"
    d, rem = divmod(int(secs), 86400)
    h = rem // 3600
    return f"{d}d {h}h left in this window" if d else f"{h}h left in this window"


def _expected_tag(p):
    return round(max(6.0, (max(0, p["overall"] - 60) ** 1.5) / 6.0), 1)


def taggable_players(league, user_id):
    m = league.get("members", {}).get(user_id)
    if not m:
        return []
    t = team_by_id(league, m["team_id"])
    return sorted([p for p in t["roster"] if p.get("contract", {}).get("years", 9) <= 1],
                  key=lambda p: -p["overall"])[:12]


def franchise_tag(league, user_id, player_id):
    os = league.get("offseason") or {}
    if os.get("phase") != "tag":
        return False, "The franchise-tag window is closed."
    if user_id in os.get("tags", {}):
        return False, "You've already used your tag this offseason."
    m = league.get("members", {}).get(user_id)
    if not m:
        return False, "Not in this league."
    p = next((x for x in team_by_id(league, m["team_id"])["roster"] if x["id"] == player_id), None)
    if not p:
        return False, "Player not found."
    c = p.setdefault("contract", {"years": 1, "aav": 1.0, "guaranteed": 1.0})
    c["aav"] = round(max(c.get("aav", 1.0) * 1.3, _expected_tag(p)), 1)
    c["years"], c["guaranteed"] = 1, c["aav"]
    p["tagged"] = True
    os.setdefault("tags", {})[user_id] = player_id
    save_league(league)
    return True, f"Franchise-tagged {p['name']} (${c['aav']:.0f}M, 1 yr)."


def fa_is_open(league):
    """Signing is open in-season and only during the Free-Agency window of the offseason."""
    os = league.get("offseason") or {}
    return (not os.get("active")) or os.get("phase") == "free_agency"


def _finalize_offseason(league):
    rng = random.Random(league["seed"] + league.get("season", 1) * 17 + 3)
    league["free_agents"] = (league.get("free_agents", []) + fk._gen_fa_pool(rng, 24))[-80:]
    league.pop("offseason", None)
    league["season"] = league.get("season", 1) + 1
    league["week"] = 1
    league["status"] = "active"
    for t in league["teams"]:
        t["record"] = {"w": 0, "l": 0}
    league["schedule"] = fk.make_schedule(league["seed"] + league["season"],
                                          [t["id"] for t in league["teams"]])
    league["standings_cache"], league["results_log"], league["recaps"] = [], [], []
    league.pop("power_rank_prev", None)
    for m in league["members"].values():
        m["ready"] = False
    league["next_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    save_league(league)


def _advance_offseason_phase(league):
    os = league.get("offseason")
    if not os or not os.get("active"):
        return
    cur = os["phase"]
    if cur == "cutdown":
        _autocut_all(league)
        _finalize_offseason(league)
        return
    nxt = OFFSEASON_KEYS[OFFSEASON_KEYS.index(cur) + 1]
    os["phase"] = nxt
    os["phase_deadline"] = _iso(_now() + timedelta(days=league["cadence_days"]))
    if nxt == "draft":
        start_draft(league)
    elif nxt == "otas":
        os["risers"] = _advance_players(league)
    save_league(league)


def advance_offseason(league):
    """Commissioner pushes the offseason to the next window now."""
    if (league.get("offseason") or {}).get("active"):
        _advance_offseason_phase(league)
    return league


def offseason_check(league):
    """Auto-advance the offseason on the real-time clock (lazy view + tick). The
    Draft window waits for the live draft to finish; the rest advance on deadline."""
    os = league.get("offseason")
    if not os or not os.get("active") or league.get("paused"):
        return league
    guard = 0
    while os and os.get("active") and guard < 12:
        if os["phase"] == "draft":
            draft_check(league)
            if (league.get("draft") or {}).get("active"):
                break
            _advance_offseason_phase(league)
        elif _parse(os["phase_deadline"]) <= _now():
            _advance_offseason_phase(league)
        else:
            break
        os = league.get("offseason")
        guard += 1
    return league


def _advance_players(league):
    """Off-season player progression - CIRCUMSTANCES MATTER. Every player ages a
    year and develops via his trait toward his ceiling; the worst teams' young
    players get a development bump (catch-up) while the best teams' veterans regress
    a touch, and a top-tier training facility (a human GM's) adds growth. So the
    same rookie rises faster on a rebuilding/well-run club than on a stacked one."""
    rng = random.Random(league["seed"] + league.get("season", 1) * 53 + 11)
    sc = league.get("standings_cache") or []
    rank = {s["id"]: i for i, s in enumerate(sc)}          # 0 = best finish
    n = max(1, len(league["teams"]))
    fac = {}                                               # team_id -> facility level (humans)
    for m in league.get("members", {}).values():
        fac[m["team_id"]] = (m.get("business") or {}).get("facility", 1)
    risers = []
    for t in league["teams"]:
        r = rank.get(t["id"], n // 2)
        tier_bonus = 1 if r >= (2 * n) // 3 else 0          # bottom third develops faster
        regress = r <= max(2, n // 6)                       # top teams' vets dip
        fac_bonus = 1 if fac.get(t["id"], 1) >= 3 else 0    # L3+ facility (human GMs)
        for p in t["roster"]:
            before = p["overall"]
            p["age"] = p.get("age", 25) + 1
            fk._develop(p, rng, tier_bonus + fac_bonus)
            if regress and p["age"] >= 30:
                p["overall"] = max(45, p["overall"] - 1)
            gain = p["overall"] - before
            if gain >= 2:
                risers.append({"name": p["name"], "pos": p["pos"], "ovr": p["overall"],
                               "gain": gain, "team": t["full"]})
            c = p.get("contract")
            if c and "years" in c:
                c["years"] = max(0, c["years"] - 1)
    risers.sort(key=lambda x: -x["gain"])
    league["retirements"] = fk.process_retirements(            # age players out + HoF
        league["teams"], league.get("season", 1), league.setdefault("hall_of_fame", []))
    league["hall_of_fame"] = league["hall_of_fame"][:40]
    return risers[:10]


def _autocut_all(league):
    """Enforce the 53-man roster: keep the best (position-weighted) 53, the rest are
    released to free agency. Humans can cut first on their team page; this is the
    safety net so every season kicks off with legal rosters."""
    for t in league["teams"]:
        if len(t["roster"]) <= ROSTER_FINAL:
            continue
        t["roster"].sort(key=lambda p: -(p["overall"] + fk.POS_WEIGHT.get(p["pos"], 1.0)))
        cut = t["roster"][ROSTER_FINAL:]
        t["roster"] = t["roster"][:ROSTER_FINAL]
        league.setdefault("free_agents", []).extend(cut)


def release_player(league, user_id, player_id):
    """Direct cut to free agency (used to trim down to 53 in the offseason)."""
    m = league.get("members", {}).get(user_id)
    if not m:
        return False
    t = team_by_id(league, m["team_id"])
    p = next((x for x in t["roster"] if x["id"] == player_id), None)
    if not p:
        return False
    t["roster"] = [x for x in t["roster"] if x["id"] != player_id]
    league.setdefault("free_agents", []).append(p)
    save_league(league)
    return True


def start_next_season(league):
    """Commissioner rolls the league into a fresh season: players age + develop
    (circumstances matter), rosters trim to 53, fresh FAs hit the market, then
    records/schedule/recaps reset and the clock restarts."""
    if league.get("status") != "complete":
        return False
    _advance_players(league)                          # age + trait development (uses last finish)
    _autocut_all(league)                              # enforce 53-man rosters
    rng = random.Random(league["seed"] + league.get("season", 1) * 17 + 3)
    league["free_agents"] = (league.get("free_agents", []) + fk._gen_fa_pool(rng, 24))[-80:]
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
LEAGUE_DRAFT_ROUNDS = 7        # full NFL-length draft
DRAFT_PICK_SECONDS = 90
ROSTER_FINAL = 53              # the 53-man active roster


def _draft_on_clock(draft):
    seq = draft.get("sequence")
    if seq is not None:
        return seq[draft["ptr"]] if draft["ptr"] < len(seq) else None
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
    via = ""
    orig_seq = draft.get("orig_seq")
    if orig_seq and draft["ptr"] < len(orig_seq) and orig_seq[draft["ptr"]] != team_id:
        ot = team_by_id(league, orig_seq[draft["ptr"]])
        via = ot["full"] if ot else ""
    t["roster"].append(fk._make_rookie(prospect))
    draft["class"] = [p for p in draft["class"] if p["id"] != prospect["id"]]
    draft["log"].insert(0, {"round": rnd, "team": t["full"], "name": prospect["name"],
                            "pos": prospect["pos"], "ovr": prospect.get("true_ovr", 0), "via": via})
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
    init_picks(league)                              # fresh pick inventory for next year's draft


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
    if not league.get("picks"):
        init_picks(league)
    owner_of = {(p["round"], p["orig"]): p["owner"] for p in league["picks"]}
    teams = {t["id"]: t for t in league["teams"]}
    sequence, orig_seq = [], []                      # who picks here / whose slot it was
    for r in range(1, LEAGUE_DRAFT_ROUNDS + 1):
        for tid in order:
            sequence.append(owner_of.get((r, tid), tid))
            orig_seq.append(tid)
    league["draft"] = {"active": True, "class": cls, "order": order,
                       "sequence": sequence, "orig_seq": orig_seq,
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
    if league and (league.get("offseason") or {}).get("active"):
        return offseason_check(league)          # between seasons: walk the NFL calendar
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
        if (lg.get("offseason") or {}).get("active"):   # walk the offseason calendar
            offseason_check(lg)
            advanced += 1
            continue
        if (lg.get("draft") or {}).get("active"):       # legacy standalone drafts
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


# ---- Draft picks as tradeable assets (for the UPCOMING draft) ----
def init_picks(league):
    league["picks"] = [{"id": f"pk{r}_{t['id']}", "round": r, "orig": t["id"], "owner": t["id"]}
                       for t in league["teams"] for r in range(1, LEAGUE_DRAFT_ROUNDS + 1)]
    return league["picks"]


def pick_by_id(league, pid):
    return next((p for p in league.get("picks", []) if p["id"] == pid), None)


def _pick_value(rnd):
    return max(2.0, (8 - rnd) * 4.5)             # round 1 ~31.5, round 7 ~4.5


def team_picks(league, team_id):
    if not league.get("picks"):
        init_picks(league)
        save_league(league)                     # backfill picks for older leagues
    teams = {t["id"]: t for t in league["teams"]}
    out = []
    for p in league["picks"]:
        if p["owner"] == team_id:
            lbl = f"Round {p['round']} pick"
            if p["orig"] != team_id:
                lbl += f" (from {teams[p['orig']]['full']})"
            out.append(dict(p, label=lbl))
    return sorted(out, key=lambda x: (x["round"], x["orig"]))


def _is_pick(aid):
    return str(aid).startswith("pk")


def _asset_owned_by(league, aid, team_id):
    if _is_pick(aid):
        p = pick_by_id(league, aid)
        return bool(p and p["owner"] == team_id)
    return _owned_by(league, aid, team_id)


def _asset_value(league, aid):
    if _is_pick(aid):
        p = pick_by_id(league, aid)
        return _pick_value(p["round"]) if p else 0
    pl = player_by_id(league, aid)
    return fk.trade_value(pl) if pl else 0


def asset_label(league, aid):
    if _is_pick(aid):
        p = pick_by_id(league, aid)
        teams = {t["id"]: t for t in league["teams"]}
        if not p:
            return "Pick"
        return f"R{p['round']} pick" + (f" (from {teams[p['orig']]['full']})" if p['orig'] != p['owner'] else "")
    pl = player_by_id(league, aid)
    return f"{pl['pos']} {pl['name']} ({pl['overall']})" if pl else "—"


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
    """Fairness from the PROPOSER's view: value received vs value sent (A..F).
    Players and draft picks both count."""
    out = sum(_asset_value(league, a) for a in give_ids)
    inc = sum(_asset_value(league, a) for a in get_ids)
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
    give = [a for a in give_ids if _asset_owned_by(league, a, from_tid)]
    get = [a for a in get_ids if _asset_owned_by(league, a, to_tid)]
    if not give or not get:
        return False, "Pick at least one asset from each side."
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
    if not all(_asset_owned_by(league, a, ft["id"]) for a in trade["give"]) or \
       not all(_asset_owned_by(league, a, tt["id"]) for a in trade["get"]):
        return False

    def move(ids, src, dst, dst_tid):
        for a in ids:
            if _is_pick(a):
                pick_by_id(league, a)["owner"] = dst_tid
            else:
                pl = next((x for x in src["roster"] if x["id"] == a), None)
                if pl:
                    src["roster"] = [x for x in src["roster"] if x["id"] != a]
                    dst["roster"].append(pl)
    move(trade["give"], ft, tt, tt["id"])
    move(trade["get"], tt, ft, ft["id"])
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
