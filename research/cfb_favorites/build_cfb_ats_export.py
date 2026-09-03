# -*- coding: utf-8 -*-
"""
Precompute the CFB Team ATS Trends site data -> data/scenarios/cfb_ats.json.
Full Phil-Steele-style ATS + O/U for every FBS team (2016-2025), by team AND coach.
League table (sortable % columns) + per-team profile cards with records.

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

def R(): return {"w":0,"l":0,"p":0}
def add(r,res): r["w" if res>0 else ("l" if res<0 else "p")] += 1
def pct(r): d=r["w"]+r["l"]; return round(r["w"]/d,3) if d else None
def rec(r): return f'{r["w"]}-{r["l"]}' + (f'-{r["p"]}' if r["p"] else '')
def n(r): return r["w"]+r["l"]+r["p"]

def load():
    games={}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv",encoding="utf-8")):
        games[(r["season"],r["week"],r["homeTeam"],r["awayTeam"])]=r
    lines=list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv",encoding="utf-8")))
    coach={}; cg=defaultdict(int)
    for r in csv.DictReader(open(H/"CFBD_Coaches_2016_2025.csv",encoding="utf-8")):
        try: gp=int(float(r.get("games") or 0))
        except: gp=0
        k=(r["school"],str(r["year"]))
        if gp>=cg[k]: cg[k]=gp; coach[k]=r["coach"]
    return games,lines,coach

def build():
    games,lines,coach=load()
    T=defaultdict(lambda: {k:R() for k in ("ats","home","away","fav","dog","ou")})
    C=defaultdict(lambda: {k:R() for k in ("ats","ou")})
    conf={}
    for L in lines:
        try: sp=float(L["spread"])
        except: continue
        g=games.get((L["season"],L["week"],L["homeTeam"],L["awayTeam"]))
        if not g: continue
        try: hp,ap=int(float(g["homePts"])),int(float(g["awayPts"]))
        except: continue
        home,away=g["homeTeam"],g["awayTeam"]; conf[home]=g["homeConf"]; conf[away]=g["awayConf"]
        m=hp-ap
        h_ats = 1 if (m+sp)>0 else (-1 if (m+sp)<0 else 0)
        add(T[home]["ats"],h_ats); add(T[home]["home"],h_ats); add(T[home]["fav" if sp<0 else "dog"],h_ats)
        add(T[away]["ats"],-h_ats); add(T[away]["away"],-h_ats); add(T[away]["fav" if sp>0 else "dog"],-h_ats)
        hc=coach.get((home,str(g["season"]))); ac=coach.get((away,str(g["season"])))
        if hc: add(C[hc]["ats"],h_ats)
        if ac: add(C[ac]["ats"],-h_ats)
        try:
            tot=float(L["total"]); ou=1 if (hp+ap)>tot else (-1 if (hp+ap)<tot else 0)
            add(T[home]["ou"],ou); add(T[away]["ou"],ou)
            if hc: add(C[hc]["ou"],ou)
            if ac: add(C[ac]["ou"],ou)
        except: pass
    return T,C,conf

def main():
    T,C,conf=build()
    fbs=[t for t in T if conf.get(t) in FBS and n(T[t]["ats"])>=60]
    # league table
    tcols=[{"label":"Team","fmt":"text"},{"label":"G","fmt":"int"},{"label":"ATS%","fmt":"pct"},
           {"label":"Home%","fmt":"pct"},{"label":"Away%","fmt":"pct"},{"label":"Fav%","fmt":"pct"},
           {"label":"Dog%","fmt":"pct"},{"label":"Over%","fmt":"pct"}]
    trows=[]
    for t in fbs:
        r=T[t]
        trows.append([t, n(r["ats"]), pct(r["ats"]), pct(r["home"]), pct(r["away"]),
                      pct(r["fav"]), pct(r["dog"]), pct(r["ou"])])
    trows.sort(key=lambda z:-(z[2] or 0))
    # coaches
    ccols=[{"label":"Head Coach","fmt":"text"},{"label":"G","fmt":"int"},{"label":"ATS%","fmt":"pct"},{"label":"Over%","fmt":"pct"}]
    crows=[[c, n(C[c]["ats"]), pct(C[c]["ats"]), pct(C[c]["ou"])] for c in C if n(C[c]["ats"])>=40]
    crows.sort(key=lambda z:-(z[2] or 0))
    # profiles (records + pct + n) per team
    prof={}
    for t in fbs:
        r=T[t]
        prof[t]=[[lab, rec(r[k]), pct(r[k]), n(r[k])] for k,lab in
                 [("ats","Overall ATS"),("home","Home"),("away","Away"),("fav","As favorite"),("dog","As underdog"),("ou","Over/Under")]]
    out={"meta":{"seasons":"2016-2025","teams":len(fbs),"generated":GEN_DATE},
         "teams":{"columns":tcols,"rows":trows},
         "coaches":{"columns":ccols,"rows":crows},
         "profiles":prof,
         "teamList":sorted(fbs)}
    OUT.write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)  {len(fbs)} teams, {len(crows)} coaches")
    print("  best ATS:", trows[0][0], trows[0][2], "| worst:", trows[-1][0], trows[-1][2])

if __name__=="__main__": main()
