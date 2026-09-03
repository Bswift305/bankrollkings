# -*- coding: utf-8 -*-
"""
Full Phil-Steele-style ATS + O/U records for every FBS team (2016-2025), from the
CFBD games+lines we already pulled. Overall / home / away / as favorite / as dog,
plus over-under. Every game traces to a real graded result at the consensus line.

    python research/cfb_favorites/cfb_ats_records.py            # best/worst ATS
    python research/cfb_favorites/cfb_ats_records.py --team Georgia
"""
import csv, argparse, pathlib
from collections import defaultdict

H = pathlib.Path(__file__).resolve().parents[2] / "data" / "historical"
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}

def load():
    games = {}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv", encoding="utf-8")):
        games[(r["season"], r["week"], r["homeTeam"], r["awayTeam"])] = r
    lines = list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv", encoding="utf-8")))
    return games, lines

class Rec:
    __slots__=("g","w","l","p")
    def __init__(s): s.g=s.w=s.l=s.p=0
    def add(s,res):
        s.g+=1
        if res>0: s.w+=1
        elif res<0: s.l+=1
        else: s.p+=1
    def pct(s): d=s.w+s.l; return s.w/d if d else 0.0
    def str(s): return f"{s.w}-{s.l}" + (f"-{s.p}" if s.p else "")

def build():
    games, lines = load()
    T = defaultdict(lambda: defaultdict(Rec))   # team -> {'ats','home','away','fav','dog','ou'} -> Rec
    conf = {}
    for L in lines:
        try: sp=float(L["spread"]);
        except: continue
        g = games.get((L["season"], L["week"], L["homeTeam"], L["awayTeam"]))
        if not g: continue
        try: hp,ap=int(float(g["homePts"])), int(float(g["awayPts"]))
        except: continue
        home, away = g["homeTeam"], g["awayTeam"]
        conf[home]=g["homeConf"]; conf[away]=g["awayConf"]
        margin = hp-ap
        home_ats = 1 if (margin+sp)>0 else (-1 if (margin+sp)<0 else 0)   # home cover
        # home perspective
        T[home]["ats"].add(home_ats); T[home]["home"].add(home_ats)
        (T[home]["fav"] if sp<0 else T[home]["dog"]).add(home_ats)
        # away perspective (flip)
        T[away]["ats"].add(-home_ats); T[away]["away"].add(-home_ats)
        (T[away]["fav"] if sp>0 else T[away]["dog"]).add(-home_ats)
        # over/under (both teams)
        try:
            tot=float(L["total"]); actual=hp+ap
            ou = 1 if actual>tot else (-1 if actual<tot else 0)   # 1=over
            T[home]["ou"].add(ou); T[away]["ou"].add(ou)
        except: pass
    return T, conf

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--team"); ap.add_argument("--min",type=int,default=60); a=ap.parse_args()
    T, conf = build()
    fbs=[t for t in T if conf.get(t) in FBS]
    if a.team:
        t=next((x for x in T if x.lower()==a.team.lower()), None)
        if not t: print("team not found"); return
        r=T[t]
        print(f"{t} — ATS & O/U, 2016-2025 (consensus lines)")
        for k,lab in [("ats","Overall ATS"),("home","  Home ATS"),("away","  Away ATS"),
                      ("fav","  As favorite"),("dog","  As underdog")]:
            print(f"  {lab:<16} {r[k].str():<10} ({r[k].pct()*100:.0f}%)  n={r[k].g}")
        ou=r["ou"]; ov=ou.w; un=ou.l
        print(f"  Over/Under       O {ov} - U {un}" + (f" - P {ou.p}" if ou.p else "") + f"   ({ov/(ov+un)*100 if ov+un else 0:.0f}% over)")
        return
    print(f"FBS teams with ATS records: {len(fbs)}  (2016-2025)\n")
    ranked=sorted(((t,T[t]["ats"]) for t in fbs if T[t]["ats"].g>=a.min), key=lambda z:-z[1].pct())
    print(f"BEST ATS (min {a.min} games):")
    for t,r in ranked[:10]: print(f"  {t[:22]:<22} {r.str():<10} {r.pct()*100:.0f}%  ({r.g} g)")
    print(f"\nWORST ATS:")
    for t,r in ranked[-10:]: print(f"  {t[:22]:<22} {r.str():<10} {r.pct()*100:.0f}%  ({r.g} g)")

if __name__=="__main__": main()
