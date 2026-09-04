# -*- coding: utf-8 -*-
"""
Precompute the CFB Team ATS Trends site data -> data/scenarios/cfb_ats.json.
Full Phil-Steele-style ATS + O/U for every FBS team (2016-2025), by team AND coach.

Stores PER-SEASON raw counts [w,l,p] for every split so the site can recompute the
league table, coach table, and team profile for ANY year window (All / Last 5 / Last
3 / Last 2, etc.) client-side. No invented numbers — real graded games only.

    python research/cfb_favorites/build_cfb_ats_export.py
"""
import csv, json, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
OUT = ROOT / "data" / "scenarios" / "cfb_ats.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-09-03"
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}
SPLITS = ("ats","home","away","fav","dog","ou")


def add(counter, res):
    counter[0 if res > 0 else (1 if res < 0 else 2)] += 1  # [w, l, p]


def load():
    games = {}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv", encoding="utf-8")):
        games[(r["season"], r["week"], r["homeTeam"], r["awayTeam"])] = r
    lines = list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv", encoding="utf-8")))
    coach = {}
    cg = defaultdict(int)
    for r in csv.DictReader(open(H/"CFBD_Coaches_2016_2025.csv", encoding="utf-8")):
        try:
            gp = int(float(r.get("games") or 0))
        except ValueError:
            gp = 0
        k = (r["school"], str(r["year"]))
        if gp >= cg[k]:
            cg[k] = gp
            coach[k] = r["coach"]
    return games, lines, coach


def build():
    games, lines, coach = load()
    # team_seasons[team][season][split] = [w,l,p]
    T = defaultdict(lambda: defaultdict(lambda: {k: [0, 0, 0] for k in SPLITS}))
    C = defaultdict(lambda: defaultdict(lambda: {k: [0, 0, 0] for k in ("ats", "ou")}))
    conf = {}
    seasons = set()
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
        except (ValueError, TypeError):
            continue
        yr = str(g["season"])
        seasons.add(yr)
        home, away = g["homeTeam"], g["awayTeam"]
        conf[home] = g["homeConf"]
        conf[away] = g["awayConf"]
        m = hp - ap
        h_ats = 1 if (m + sp) > 0 else (-1 if (m + sp) < 0 else 0)
        add(T[home][yr]["ats"], h_ats); add(T[home][yr]["home"], h_ats)
        add(T[home][yr]["fav" if sp < 0 else "dog"], h_ats)
        add(T[away][yr]["ats"], -h_ats); add(T[away][yr]["away"], -h_ats)
        add(T[away][yr]["fav" if sp > 0 else "dog"], -h_ats)
        hc = coach.get((home, yr)); ac = coach.get((away, yr))
        if hc:
            add(C[hc][yr]["ats"], h_ats)
        if ac:
            add(C[ac][yr]["ats"], -h_ats)
        try:
            tot = float(L["total"])
            ou = 1 if (hp + ap) > tot else (-1 if (hp + ap) < tot else 0)
            add(T[home][yr]["ou"], ou); add(T[away][yr]["ou"], ou)
            if hc:
                add(C[hc][yr]["ou"], ou)
            if ac:
                add(C[ac][yr]["ou"], ou)
        except (ValueError, TypeError):
            pass
    return T, C, conf, sorted(seasons)


def _total_decided(team_seasons):
    return sum(s["ats"][0] + s["ats"][1] for s in team_seasons.values())


def main():
    T, C, conf, seasons = build()
    # keep FBS programs with a real body of games
    fbs = [t for t in T if conf.get(t) in FBS and _total_decided(T[t]) >= 20]

    team_seasons = {}
    for t in fbs:
        team_seasons[t] = {"conf": conf.get(t), "s": {
            yr: {k: T[t][yr][k] for k in SPLITS} for yr in T[t]
        }}
    coach_seasons = {}
    for c in C:
        # aggregate a coach's total decided games to gate out tiny names
        tot = sum(s["ats"][0] + s["ats"][1] for s in C[c].values())
        if tot >= 8:
            coach_seasons[c] = {yr: {k: C[c][yr][k] for k in ("ats", "ou")} for yr in C[c]}

    out = {
        "meta": {
            "seasons": f"{seasons[0]}-{seasons[-1]}",
            "min_year": int(seasons[0]),
            "max_year": int(seasons[-1]),
            "teams": len(fbs),
            "generated": GEN_DATE,
        },
        "seasons": [int(s) for s in seasons],
        "team_seasons": team_seasons,
        "coach_seasons": coach_seasons,
        "teamList": sorted(fbs),
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)  {len(fbs)} teams, "
          f"{len(coach_seasons)} coaches, seasons {seasons[0]}-{seasons[-1]}")


if __name__ == "__main__":
    main()
