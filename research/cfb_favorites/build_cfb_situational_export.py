# -*- coding: utf-8 -*-
"""
Precompute CFB Situational ATS Trends -> data/scenarios/cfb_situational.json.
The Phil-Steele situational tables, from our CFBD games+lines (2016-2025): each
team's ATS record in named spots (off a bye / off a loss / road favorite / big
favorite / conference / late season, ...), plus the league-wide trend for each.

    python research/cfb_favorites/build_cfb_situational_export.py
"""
import csv, json, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
OUT = ROOT / "data" / "scenarios" / "cfb_situational.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-09-03"
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}

# situation key -> (label, predicate on a team-game dict)
SITS = [
    ("off_bye",   "Off a bye week",      lambda t: t["off_bye"]),
    ("off_loss",  "Off a straight-up loss", lambda t: t["prev_su"] == "L"),
    ("off_win",   "Off a straight-up win",  lambda t: t["prev_su"] == "W"),
    ("off_ats_l", "Off an ATS loss",     lambda t: t["prev_ats"] == -1),
    ("off_ats_w", "Off an ATS cover",    lambda t: t["prev_ats"] == 1),
    ("home_fav",  "Home favorite",       lambda t: t["home"] and t["spread"] < 0),
    ("road_fav",  "Road favorite",       lambda t: (not t["home"]) and t["spread"] < 0),
    ("home_dog",  "Home underdog",       lambda t: t["home"] and t["spread"] > 0),
    ("road_dog",  "Road underdog",       lambda t: (not t["home"]) and t["spread"] > 0),
    ("big_fav",   "Favored by 14+",      lambda t: t["spread"] <= -14),
    ("big_dog",   "Underdog of 14+",     lambda t: t["spread"] >= 14),
    ("conf",      "Conference game",     lambda t: t["conf_game"]),
    ("nonconf",   "Non-conference game", lambda t: not t["conf_game"]),
    ("late",      "Late season (Wk 10+)", lambda t: t["week"] >= 10),
]

def R(): return {"w":0,"l":0,"p":0,"o":0,"u":0}
def add_ats(r,res): r["w" if res>0 else ("l" if res<0 else "p")] += 1
def add_ou(r,res):
    if res>0: r["o"]+=1
    elif res<0: r["u"]+=1
def pct(r): d=r["w"]+r["l"]; return round(r["w"]/d,3) if d else None
def ovr(r): d=r["o"]+r["u"]; return round(r["o"]/d,3) if d else None
def rec(r): return f'{r["w"]}-{r["l"]}' + (f'-{r["p"]}' if r["p"] else '')
def n(r): return r["w"]+r["l"]+r["p"]

def load():
    games={}
    for r in csv.DictReader(open(H/"CFBD_Games_2016_2025.csv",encoding="utf-8")):
        games[(r["season"],r["week"],r["homeTeam"],r["awayTeam"])]=r
    lines=list(csv.DictReader(open(H/"CFBD_Lines_2016_2025.csv",encoding="utf-8")))
    return games,lines

def build_team_games():
    games,lines=load()
    tg=[]   # one dict per team-perspective of each lined game
    for L in lines:
        try: sp=float(L["spread"])
        except: continue
        g=games.get((L["season"],L["week"],L["homeTeam"],L["awayTeam"]))
        if not g: continue
        try: hp,ap=int(float(g["homePts"])),int(float(g["awayPts"]))
        except: continue
        try: wk=int(L["week"])
        except: continue
        m=hp-ap
        h_ats = 1 if (m+sp)>0 else (-1 if (m+sp)<0 else 0)
        conf_game = (g["homeConf"] in FBS and g["awayConf"] in FBS and g["homeConf"]==g["awayConf"])
        try: tot=float(L["total"]); ou = 1 if (hp+ap)>tot else (-1 if (hp+ap)<tot else 0)
        except: ou=0
        for team, home, tspread, tmargin, tats, tconf in [
            (g["homeTeam"], True,  sp,  m,  h_ats, g["homeConf"]),
            (g["awayTeam"], False, -sp, -m, -h_ats, g["awayConf"]),
        ]:
            if tconf not in FBS: continue
            tg.append({"team":team,"season":L["season"],"week":wk,"home":home,
                       "spread":tspread,"su": 1 if tmargin>0 else -1,"ats":tats,"ou":ou,
                       "conf_game":conf_game,"prev_su":None,"prev_ats":None,"off_bye":False})
    # prior-game context within (team, season)
    byteam=defaultdict(list)
    for t in tg: byteam[(t["team"],t["season"])].append(t)
    for key, seq in byteam.items():
        seq.sort(key=lambda x:x["week"])
        for i in range(1,len(seq)):
            prev=seq[i-1]
            seq[i]["prev_su"] = "W" if prev["su"]>0 else "L"
            seq[i]["prev_ats"] = prev["ats"]
            seq[i]["off_bye"] = (seq[i]["week"]-prev["week"])>=2
    return tg

def build():
    tg=build_team_games()
    league={k:R() for k,_,_ in SITS}
    team={k:defaultdict(R) for k,_,_ in SITS}
    for t in tg:
        for k,_,pred in SITS:
            if pred(t):
                add_ats(league[k],t["ats"]); add_ou(league[k],t["ou"])
                add_ats(team[k][t["team"]],t["ats"]); add_ou(team[k][t["team"]],t["ou"])
    out_sits=[]
    for k,label,_ in SITS:
        lg=league[k]
        cols=[{"label":"Team","fmt":"text"},{"label":"G","fmt":"int"},{"label":"ATS%","fmt":"pct"},
              {"label":"Record","fmt":"text"},{"label":"Over%","fmt":"pct"}]
        rows=[]
        for tm,r in team[k].items():
            if n(r)>=12: rows.append([tm,n(r),pct(r),rec(r),ovr(r)])
        rows.sort(key=lambda z:-(z[2] or 0))
        out_sits.append({"key":k,"label":label,
            "league":{"rec":rec(lg),"ats":pct(lg),"over":ovr(lg),"n":n(lg)},
            "board":{"columns":cols,"rows":rows}})
    out={"meta":{"seasons":"2016-2025","generated":GEN_DATE,"situations":len(SITS)},
         "situations":out_sits}
    OUT.write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    for s in out_sits:
        lg=s["league"]
        print(f"  {s['label']:<22} league {lg['rec']:<12} {(lg['ats']*100 if lg['ats'] else 0):.0f}% ATS  (n={lg['n']})  |  {len(s['board']['rows'])} teams")

if __name__=="__main__": build()
