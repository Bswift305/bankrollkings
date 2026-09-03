# -*- coding: utf-8 -*-
"""
Precompute CFB Totals & Pace Trends -> data/scenarios/cfb_totals.json.
Per FBS team (recent 5 seasons 2021-2025): over/under record + over%, the actual
scoring environment (avg combined points, points for/against), and real PACE
(offensive plays per game, from CFBD advanced stats). League table, sortable.

    python research/cfb_favorites/build_cfb_totals_export.py
"""
import csv, json, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
OUT = ROOT / "data" / "scenarios" / "cfb_totals.json"
GEN_DATE = "2026-09-03"
YEARS = {"2021","2022","2023","2024","2025"}
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}

def fnum(v):
    try: return float(v)
    except: return None

def load():
    games={}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv",encoding="utf-8")):
        if r["season"] in YEARS: games[(r["season"],r["week"],r["homeTeam"],r["awayTeam"])]=r
    lines=[r for r in csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv",encoding="utf-8")) if r["season"] in YEARS]
    adv=defaultdict(lambda:{"plays":0.0,"succ":[],"dsucc":[]})   # team -> plays sum + success rates
    for r in csv.DictReader(open(H/"CFBD_Advanced_2021_2025.csv",encoding="utf-8")):
        p=fnum(r["off_plays"]);  s=fnum(r["off_success"]); ds=fnum(r["def_success"])
        if p: adv[r["team"]]["plays"]+=p
        if s is not None: adv[r["team"]]["succ"].append(s)
        if ds is not None: adv[r["team"]]["dsucc"].append(ds)
    return games,lines,adv

def build():
    games,lines,adv=load()
    T=defaultdict(lambda:{"o":0,"u":0,"p":0,"pts_for":0,"pts_ag":0,"tot":0,"g":0,"conf":""})
    gcount=defaultdict(int)   # team -> games with scores (for pace normalization)
    # count games per team (from games file) for pace
    for (s,w,ht,at),g in games.items():
        try: int(float(g["homePts"])); int(float(g["awayPts"]))
        except: continue
        gcount[ht]+=1; gcount[at]+=1
    for L in lines:
        tot=fnum(L["total"])
        if tot is None: continue
        g=games.get((L["season"],L["week"],L["homeTeam"],L["awayTeam"]))
        if not g: continue
        try: hp,ap=int(float(g["homePts"])),int(float(g["awayPts"]))
        except: continue
        combined=hp+ap
        ou = 1 if combined>tot else (-1 if combined<tot else 0)
        for team,pf,pa,conf in [(g["homeTeam"],hp,ap,g["homeConf"]),(g["awayTeam"],ap,hp,g["awayConf"])]:
            d=T[team]; d["conf"]=conf
            if ou>0: d["o"]+=1
            elif ou<0: d["u"]+=1
            else: d["p"]+=1
            d["pts_for"]+=pf; d["pts_ag"]+=pa; d["tot"]+=combined; d["g"]+=1
    fbs=[t for t in T if T[t]["conf"] in FBS and T[t]["g"]>=30]
    cols=[{"label":"Team","fmt":"text"},{"label":"G","fmt":"int"},{"label":"Plays/G","fmt":"f1"},
          {"label":"Avg Total","fmt":"f1"},{"label":"Over%","fmt":"pct"},{"label":"O/U","fmt":"text"},
          {"label":"PPG","fmt":"f1"},{"label":"Opp PPG","fmt":"f1"}]
    rows=[]
    for t in fbs:
        d=T[t]; ou_dec=d["o"]+d["u"]
        pace = round(adv[t]["plays"]/gcount[t],1) if (t in adv and gcount.get(t)) else None
        rows.append([t, d["g"], pace, round(d["tot"]/d["g"],1),
                     round(d["o"]/ou_dec,3) if ou_dec else None,
                     f'{d["o"]}-{d["u"]}'+(f'-{d["p"]}' if d["p"] else ''),
                     round(d["pts_for"]/d["g"],1), round(d["pts_ag"]/d["g"],1)])
    rows.sort(key=lambda z:-(z[2] or 0))   # default: fastest pace first
    # league summary
    allo=sum(T[t]["o"] for t in fbs); allu=sum(T[t]["u"] for t in fbs)
    avg_tot=round(sum(T[t]["tot"] for t in fbs)/sum(T[t]["g"] for t in fbs),1)
    avg_pace=round(sum(r[2] for r in rows if r[2])/sum(1 for r in rows if r[2]),1)
    out={"meta":{"seasons":"2021-2025","teams":len(fbs),"generated":GEN_DATE,
                 "over_rate":round(allo/(allo+allu),3) if (allo+allu) else None,
                 "avg_total":avg_tot,"avg_pace":avg_pace},
         "board":{"columns":cols,"rows":rows}}
    OUT.write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)  {len(fbs)} teams  league over {out['meta']['over_rate']} avgTot {avg_tot} avgPace {avg_pace}")
    print("  fastest:", [(r[0],r[2]) for r in rows[:4]])
    print("  highest-scoring env:", [(r[0],r[3]) for r in sorted(rows,key=lambda z:-z[3])[:4]])

if __name__=="__main__": build()
