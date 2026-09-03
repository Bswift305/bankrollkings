# -*- coding: utf-8 -*-
"""
CFB big-favorite trend: which teams (and COACHES) cover as heavy early-season
favorites, and which don't. Built from CFBD games + lines + coaches (2016-2025),
all joined on CFBD IDs/names -- no fuzzy matching. Coach matters: the tendency
often follows the coach's DNA, not the school, so we grade both.

Cover = favorite wins by MORE than the closing number (push if exactly equal).
Scope = early-season (weeks 1-4 by default) games where an FBS team is favored by
>= THRESHOLD (default 30). Every number traces to a real graded game.

    python research/cfb_favorites/cfb_favorite_trends.py            # 30+, weeks 1-4
    python research/cfb_favorites/cfb_favorite_trends.py --min-line 40 --weeks 1
    python research/cfb_favorites/cfb_favorite_trends.py --team Georgia
"""
import csv, argparse, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","Mid-American",
       "Mountain West","Conference USA","FBS Independents","Pac-12","American"}

def load():
    games = {}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv", encoding="utf-8")):
        key = (r["season"], r["week"], r["homeTeam"], r["awayTeam"])
        games[key] = r
    lines = list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv", encoding="utf-8")))
    coach = {}
    cg = defaultdict(int)
    for r in csv.DictReader(open(H/"CFBD_Coaches_2016_2025.csv", encoding="utf-8")):
        try: gp = int(float(r.get("games") or 0))
        except: gp = 0
        k = (r["school"], str(r["year"]))
        if gp >= cg[k]:                      # keep the coach with the most games that (school,year)
            cg[k] = gp; coach[k] = r["coach"]
    return games, lines, coach

def build(min_line, weeks):
    games, lines, coach = load()
    rows = []
    for L in lines:
        try: wk = int(L["week"])
        except: continue
        if weeks and wk not in weeks: continue
        try: sp = float(L["spread"])
        except: continue
        if abs(sp) < min_line: continue
        gk = (L["season"], L["week"], L["homeTeam"], L["awayTeam"])
        g = games.get(gk)
        if not g: continue
        try: hp, ap = int(float(g["homePts"])), int(float(g["awayPts"]))
        except: continue
        home_fav = sp < 0
        fav  = g["homeTeam"] if home_fav else g["awayTeam"]
        dog  = g["awayTeam"] if home_fav else g["homeTeam"]
        fav_conf = g["homeConf"] if home_fav else g["awayConf"]
        if fav_conf not in FBS: continue
        margin = (hp - ap) if home_fav else (ap - hp)
        line = abs(sp)
        result = 0 if abs(margin - line) < 1e-9 else (1 if margin > line else -1)  # 1 cover, -1 no, 0 push
        rows.append({"season": g["season"], "week": wk, "fav": fav, "dog": dog, "line": line,
                     "margin": margin, "result": result,
                     "coach": coach.get((fav, str(g["season"])), "?")})
    return rows

def rate(rows):
    c = sum(1 for r in rows if r["result"] == 1); n = sum(1 for r in rows if r["result"] == -1)
    return c, n, (c/(c+n) if (c+n) else 0.0)

def table(rows, key, ming, label):
    agg = defaultdict(list)
    for r in rows: agg[r[key]].append(r)
    stats = []
    for name, rs in agg.items():
        c, n, pct = rate(rs)
        if c + n >= ming: stats.append((name, c, n, pct, len(rs)))
    stats.sort(key=lambda x: (x[3], -(x[1]+x[2])))
    print(f"\n===== {label} (min {ming} graded games) =====")
    print(f"{'':<24}{'Cover%':>8}{'Rec':>9}")
    print("  -- SLOWEST as big favorites (worst cover%) --")
    for name, c, n, pct, tot in stats[:12]:
        print(f"  {name[:22]:<22}{pct*100:>7.0f}% {f'{c}-{n}':>9}")
    print("  -- FASTEST as big favorites (best cover%) --")
    for name, c, n, pct, tot in list(reversed(stats))[:12]:
        print(f"  {name[:22]:<22}{pct*100:>7.0f}% {f'{c}-{n}':>9}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-line", type=float, default=30)
    ap.add_argument("--weeks", default="1-4")
    ap.add_argument("--min-games", type=int, default=5)
    ap.add_argument("--team", default=None)
    a = ap.parse_args()
    weeks = set()
    for part in a.weeks.split(","):
        if "-" in part: lo,hi = part.split("-"); weeks.update(range(int(lo), int(hi)+1))
        elif part.strip(): weeks.add(int(part))
    rows = build(a.min_line, weeks)
    c, n, pct = rate(rows)
    print(f"CFB early-season (weeks {sorted(weeks)}) FBS favorites of {a.min_line:.0f}+  (2016-2025)")
    print(f"Games: {len(rows)}   Favorites covered {c}-{n}  ->  {pct*100:.0f}%")
    if a.team:
        tr = [r for r in rows if r["fav"].lower() == a.team.lower()]  # exact: "Georgia" != "Georgia Tech"
        tc, tn, tp = rate(tr)
        print(f"\n{a.team}: {tc}-{tn} ATS as a {a.min_line:.0f}+ favorite ({tp*100:.0f}%)")
        for r in sorted(tr, key=lambda x:(x['season'],x['week'])):
            v = 'COVER' if r['result']==1 else ('push' if r['result']==0 else 'no')
            print(f"  {r['season']} wk{r['week']}  -{r['line']:.1f} vs {r['dog'][:20]:<20} won by {r['margin']:+d}  {v}   [{r['coach']}]")
        return
    table(rows, "fav", a.min_games, "BY TEAM")
    table(rows, "coach", a.min_games, "BY HEAD COACH")

if __name__ == "__main__":
    main()
