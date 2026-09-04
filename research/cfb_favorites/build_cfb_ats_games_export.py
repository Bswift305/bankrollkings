# -*- coding: utf-8 -*-
"""
Precompute the per-team GAME LOG behind the ATS tables -> cfb_ats_games.json.
Every graded, lined game 2016-2025 from the team's perspective: season, week,
opponent, home/away, the spread, the final, whether it covered, and O/U. This
is the drill-down behind the Team ATS Trends tables (click a team -> game log).

Read server-side and served per-team on demand (not embedded whole), so the
file can be large without bloating the page.

    python research/cfb_favorites/build_cfb_ats_games_export.py
"""
import csv, json, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
OUT = ROOT / "data" / "scenarios" / "cfb_ats_games.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-09-03"
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}


def load():
    games = {}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv", encoding="utf-8")):
        games[(r["season"], r["week"], r["homeTeam"], r["awayTeam"])] = r
    lines = list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv", encoding="utf-8")))
    return games, lines


def build():
    games, lines = load()
    by_team = defaultdict(list)   # team -> list of game rows
    conf_seen = {}
    for L in lines:
        try:
            sp = float(L["spread"])
        except (ValueError, TypeError):
            continue
        g = games.get((L["season"], L["week"], L["homeTeam"], L["awayTeam"]))
        if not g:
            continue
        try:
            hp, ap = int(float(g["homePts"])), int(float(g["awayPts"]))
            wk = int(L["week"]); yr = int(g["season"])
        except (ValueError, TypeError):
            continue
        try:
            tot = float(L["total"])
        except (ValueError, TypeError):
            tot = None
        home, away = g["homeTeam"], g["awayTeam"]
        conf_seen[home] = g["homeConf"]; conf_seen[away] = g["awayConf"]
        m = hp - ap
        h_ats = 1 if (m + sp) > 0 else (-1 if (m + sp) < 0 else 0)
        ou = None
        if tot is not None:
            ou = 1 if (hp + ap) > tot else (-1 if (hp + ap) < tot else 0)
        # row from each team's perspective:
        # [season, week, opp, loc(H/A), line, teamPts, oppPts, ats, ou]
        by_team[home].append([yr, wk, away, "H", round(sp, 1), hp, ap, h_ats, ou])
        by_team[away].append([yr, wk, home, "A", round(-sp, 1), ap, hp, -h_ats, ou])

    # keep FBS programs (their most-recent conf is FBS)
    out = {}
    for t, rows in by_team.items():
        if conf_seen.get(t) not in FBS:
            continue
        rows.sort(key=lambda r: (r[0], r[1]))
        out[t] = rows

    payload = {
        "meta": {"seasons": "2016-2025", "generated": GEN_DATE, "teams": len(out),
                 "cols": ["season", "week", "opp", "loc", "line", "pts", "oppPts", "ats", "ou"]},
        "games": out,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tot = sum(len(v) for v in out.values())
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)  {len(out)} teams, {tot} team-games")


if __name__ == "__main__":
    build()
