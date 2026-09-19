# -*- coding: utf-8 -*-
"""CFB game-line niche hunt: TOTALS (over/under) + SPREADS with REAL prices, full 2025
season (935 games). Join OddsAPI consensus lines -> CFBD final scores + conference.
1 season -> split early(<=wk7)/late for a rough out-of-sample. Honest, directional."""
import pandas as pd, numpy as np
ROOT="C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls"
POWER={'SEC','Big Ten','ACC','Big 12','Pac-12','FBS Independents'}

def norm(s): return ''.join(ch for ch in str(s).lower() if ch.isalnum())
def core(name):  # drop mascot (last token): "Kansas State Wildcats" -> "kansasstate"
    toks=str(name).split(); return norm(' '.join(toks[:-1])) if len(toks)>1 else norm(name)

h=pd.read_csv(f"{ROOT}/data/historical/NCAAF_OddsAPI_GameLines_History.csv",dtype=str,low_memory=False)
for c in ['Spread','Total','SpreadOdds','OverOdds','UnderOdds','AwayML','HomeML']:
    h[c]=pd.to_numeric(h[c],errors='coerce')
h['d']=pd.to_datetime(h['Date'],errors='coerce')
# consensus per game = median line/prices across books+snapshots
lines=h.groupby('GameID').agg(Date=('d','first'),Away=('Away','first'),Home=('Home','first'),
    Spread=('Spread','median'),Total=('Total','median'),SpreadOdds=('SpreadOdds','median'),
    OverOdds=('OverOdds','median'),UnderOdds=('UnderOdds','median'),
    AwayML=('AwayML','median'),HomeML=('HomeML','median')).reset_index()
lines['hk']=lines['Home'].map(core); lines['ak']=lines['Away'].map(core)
lines['wk']=((lines['Date']-lines['Date'].min()).dt.days//7)+1

g=pd.read_csv(f"{ROOT}/data/historical/NCAAF_CFBD_Games_2025.csv",dtype=str,low_memory=False)
for c in ['HomeScore','AwayScore']: g[c]=pd.to_numeric(g[c],errors='coerce')
g=g.dropna(subset=['HomeScore','AwayScore'])
g['hk']=g['Home'].map(norm); g['ak']=g['Away'].map(norm)
g['power']=g['HomeConference'].isin(POWER).astype(int)+g['AwayConference'].isin(POWER).astype(int)
scores=g.groupby(['hk','ak']).agg(HomeScore=('HomeScore','first'),AwayScore=('AwayScore','first'),
    Neutral=('NeutralSite','first'),ConfGame=('ConferenceGame','first'),powerN=('power','first')).reset_index()

m=lines.merge(scores,on=['hk','ak'],how='inner')
print(f"joined games: {len(m):,} / {len(lines):,} odds games (match rate {len(m)/len(lines):.0%})")
m=m.dropna(subset=['Total','Spread','HomeScore','AwayScore'])
m['tot']=m['HomeScore']+m['AwayScore']; m['margin']=m['HomeScore']-m['AwayScore']
m['fav_mag']=m['Spread'].abs()

def dec(p): return 1+(p/100 if p>0 else 100/abs(p))
def roi(sub,side):
    if side=='OVER': win=sub['tot']>sub['Total']; price=sub['OverOdds']
    elif side=='UNDER': win=sub['tot']<sub['Total']; price=sub['UnderOdds']
    elif side=='HOME': win=(sub['margin']+sub['Spread'])>0; price=sub['SpreadOdds']
    elif side=='AWAY': win=(sub['margin']+sub['Spread'])<0; price=sub['SpreadOdds']
    r=[(dec(p)-1) if w else -1 for p,w in zip(price.fillna(-110),win)]
    return np.mean(r), np.mean(win), len(sub)
def test(name,mask,side):
    s=m[mask]
    if len(s)<25: print(f"  {name:36s}[{side}] n={len(s)} small"); return
    parts=[]
    for lab,ss in [('ALL',s),('early(<=wk7)',s[s['wk']<=7]),('late',s[s['wk']>7])]:
        if len(ss)>=20: r,hit,n=roi(ss,side); parts.append(f"{lab}: {r*100:+5.1f}% (hit {hit:.0%}, n={n})")
    print(f"  {name:36s}[{side}] "+"  ".join(parts))

print("\nTOTALS -----------------------------------------------------------------")
test("baseline",m['Total'].notna(),'OVER')
test("baseline",m['Total'].notna(),'UNDER')
test("blowout spread 14+",m['fav_mag']>=14,'OVER')
test("blowout spread 21+",m['fav_mag']>=21,'OVER')
test("blowout spread 21+",m['fav_mag']>=21,'UNDER')
test("high total 60+",m['Total']>=60,'UNDER')
test("low total <=45",m['Total']<=45,'OVER')
test("G5 only (0 power teams)",m['powerN']==0,'OVER')
test("G5 only",m['powerN']==0,'UNDER')
test("power vs G5 mismatch",m['powerN']==1,'OVER')

print("\nSPREADS ----------------------------------------------------------------")
test("home favorite",m['Spread']<0,'HOME')
test("home dog",m['Spread']>0,'HOME')
test("big fav 21+ (cover)",m['fav_mag']>=21,'HOME' ,)  # home if home is fav
test("power vs G5 (home) ",m['powerN']==1,'HOME')
test("neutral site",m['Neutral'].astype(str).str.lower().isin(['true','1']),'HOME')

print("\nMONEYLINE DOGS (bet dog to win outright) -------------------------------")
d=m[m['HomeML']>0]  # home dog
if len(d)>=25:
    win=d['HomeScore']>d['AwayScore']; r=[(dec(p)-1) if w else -1 for p,w in zip(d['HomeML'],win)]
    print(f"  home ML dogs: {np.mean(r)*100:+.1f}% ROI (win {np.mean(win):.0%}, n={len(d)})")
a=m[m['AwayML']>0]
if len(a)>=25:
    win=a['AwayScore']>a['HomeScore']; r=[(dec(p)-1) if w else -1 for p,w in zip(a['AwayML'],win)]
    print(f"  away ML dogs: {np.mean(r)*100:+.1f}% ROI (win {np.mean(win):.0%}, n={len(a)})")
print("\n(1 season -> directional. Want + in BOTH early & late halves + sane n.)")
