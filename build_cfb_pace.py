#!/usr/bin/env python3
"""CFB Totals & Pace -- the tempo context behind this week's over/unders. Totals live and
die on PACE: a fast team runs more plays, which means more scoring chances, which pushes
the over; a grind-it-out team does the opposite.

For the current season we compute each team's offensive PLAYS PER GAME (national rank +
tier) and its typical scoring ENVIRONMENT (points for + against per game). For each upcoming
game we pair both sides into a combined tempo + scoring read against the posted total.

HONEST: pace is CONTEXT for a total, not a projected number -- the market prices tempo, and
this read is NOT opponent-adjusted (cfb_current_form.total_read does the adjusted projection).
It tells you WHY a total sits where it does, and whether the environment leans over or under.

Sources: CFBD /stats/season/advanced (plays, drives), /games (scoring + games played),
/lines (this week's totals). Writes data/scenarios/cfb_pace.json. Needs CFBD_API_KEY.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_pace.json"
API = "https://api.collegefootballdata.com"


def _get(path, key):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _median(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _ord(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")

    adv = _get(f"/stats/season/advanced?year={season}&excludeGarbageTime=false", key)
    games = _get(f"/games?year={season}&seasonType=regular", key)
    lines = _get(f"/lines?year={season}&seasonType=regular", key)

    # scoring + games played, from completed games
    gp = defaultdict(int)
    pf = defaultdict(float)
    pa = defaultdict(float)
    for g in games:
        hs, as_ = g.get("homePoints"), g.get("awayPoints")
        if hs is None or as_ is None:
            continue
        h, a = g.get("homeTeam"), g.get("awayTeam")
        gp[h] += 1; gp[a] += 1
        pf[h] += hs; pa[h] += as_
        pf[a] += as_; pa[a] += hs

    teams = {}
    for r in adv:
        t = r.get("team")
        off = r.get("offense") or {}
        plays = off.get("plays")
        n = gp.get(t, 0)
        if not t or not plays or n < 2:
            continue
        ppg = plays / n
        env = (pf.get(t, 0) + pa.get(t, 0)) / n  # typical combined points in this team's games
        teams[t] = {"plays_pg": round(ppg, 1), "env": round(env, 1), "games": n,
                    "ppa": round(off.get("ppa") or 0, 3)}

    if len(teams) < 10:
        print(f"[build_cfb_pace] only {len(teams)} teams with data; skipping")
        return {"season": season, "teams": {}, "games": []}

    # national pace rank + tier (percentile on plays/game)
    order = sorted(teams, key=lambda t: -teams[t]["plays_pg"])
    nt = len(order)
    for i, t in enumerate(order):
        pct = round(100 * (nt - 1 - i) / (nt - 1)) if nt > 1 else 50
        teams[t]["pace_rank"] = i + 1
        teams[t]["pace_pct"] = pct
        teams[t]["pace_tier"] = ("fast" if pct >= 70 else "slow" if pct <= 30 else "average")
    avg_env = round(statistics.mean(x["env"] for x in teams.values()), 1)

    # this week's upcoming games + totals
    upc = {}
    for g in lines:
        if g.get("homeScore") is not None:
            continue
        total = _median([l.get("overUnder") for l in (g.get("lines") or [])])
        h, a = g.get("homeTeam"), g.get("awayTeam")
        start = g.get("startDate") or ""
        hc = str(g.get("homeClassification") or "").lower()
        ac = str(g.get("awayClassification") or "").lower()
        if (hc != "fbs" and ac != "fbs"):
            continue
        gid = g.get("id")
        if gid in upc:
            continue
        if h in teams or a in teams:
            upc[gid] = {"away": a, "home": h, "week": g.get("week"), "start": start,
                        "total": (round(total, 1) if total is not None else None)}

    # the lines feed returns every remaining week -- keep only the nearest upcoming week
    wks = [v["week"] for v in upc.values() if v.get("week") is not None]
    if wks:
        min_wk = min(wks)
        upc = {k: v for k, v in upc.items() if v.get("week") == min_wk}

    out_games = []
    for gm in upc.values():
        ta, th = teams.get(gm["away"]), teams.get(gm["home"])
        if not ta and not th:
            continue
        paces = [x["plays_pg"] for x in (ta, th) if x]
        envs = [x["env"] for x in (ta, th) if x]
        pcts = [x["pace_pct"] for x in (ta, th) if x]
        combo_pace = round(statistics.mean(paces), 1) if paces else None
        env_proj = round(statistics.mean(envs), 1) if envs else None
        combo_pct = round(statistics.mean(pcts)) if pcts else 50
        tempo = "fast" if combo_pct >= 66 else "slow" if combo_pct <= 34 else "average"
        lean = None
        tot = gm["total"]
        if tot is not None and env_proj is not None:
            if tempo == "fast" and env_proj - tot >= 3:
                lean = "over"
            elif tempo == "slow" and tot - env_proj >= 3:
                lean = "under"
        out_games.append({**gm, "combo_pace": combo_pace, "combo_pct": combo_pct,
                          "tempo": tempo, "env_proj": env_proj, "lean": lean,
                          "away_pace": (ta or {}).get("plays_pg"), "home_pace": (th or {}).get("plays_pg"),
                          "away_rank": (ta or {}).get("pace_rank"), "home_rank": (th or {}).get("pace_rank"),
                          "away_tier": (ta or {}).get("pace_tier"), "home_tier": (th or {}).get("pace_tier")})
    # sort: clearest tempo spots first (farthest from average), then by combined pace
    out_games.sort(key=lambda x: (-abs((x["combo_pct"] or 50) - 50), -(x["combo_pace"] or 0)))

    # fastest / slowest leaderboard
    fastest = [{"team": t, "plays_pg": teams[t]["plays_pg"], "rank": teams[t]["pace_rank"],
                "env": teams[t]["env"]} for t in order[:12]]
    slowest = [{"team": t, "plays_pg": teams[t]["plays_pg"], "rank": teams[t]["pace_rank"],
                "env": teams[t]["env"]} for t in order[-12:][::-1]]
    return {"season": season, "teams_rated": nt, "avg_env": avg_env,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "games": out_games, "fastest": fastest, "slowest": slowest}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[build_cfb_pace] {args.season}: {data.get('teams_rated', 0)} teams, "
          f"{len(data.get('games', []))} upcoming games -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
