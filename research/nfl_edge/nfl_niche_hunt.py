# -*- coding: utf-8 -*-
"""NFL niche hunt on REAL graded props (2024-25). ROI at BetPrice, one side per test
(both sides stored -> tautology), split 2024(scout)/2025(out-of-sample)."""
import pandas as pd, numpy as np
ROOT="C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls"
df=pd.read_csv(f"{ROOT}/data/tracking/NFL_AllPropResults_Scored.csv",dtype=str,low_memory=False)
g=df[df['OutcomeState'].isin(['Hit','Miss'])].copy()
for c in ['BetPrice','WindMph','Temperature','RestDays','Line','ResultValue']:
    g[c]=pd.to_numeric(g[c],errors='coerce')
g=g[g['BetPrice'].between(-1000,1000)]
g['win']=g['OutcomeState']=='Hit'
g['dir']=g['Direction'].str.upper()
PASS={'Pass Yds','Pass Comp','Pass Att','Rec Yds','Receptions'}
RUSH={'Rush Yds','Rush Att'}

def ret(price,win):
    dec=1+(price/100 if price>0 else 100/abs(price)); return (dec-1) if win else -1.0
g['ret']=[ret(p,w) for p,w in zip(g['BetPrice'],g['win'])]

def show(name, mask, direction):
    m=g[mask & (g['dir']==direction)]
    line=f"{name:44s} [{direction}]"
    for season in ['2024','2025']:
        s=m[m['Season']==season]
        if len(s)>=25:
            line+=f"   {season}: {s['ret'].mean()*100:+5.1f}% ROI (hit {s['win'].mean():.0%}, n={len(s):,})"
        else:
            line+=f"   {season}: n={len(s)} (small)"
    print(line)

print("BASELINES ------------------------------------------------------------")
show("all props", g['Line'].notna(), 'OVER')
show("all props", g['Line'].notna(), 'UNDER')

print("\nWEATHER --------------------------------------------------------------")
show("WIND 15+ , passing/rec", g['Stat'].isin(PASS) & (g['WindMph']>=15), 'UNDER')
show("WIND 15+ , passing/rec", g['Stat'].isin(PASS) & (g['WindMph']>=15), 'OVER')
show("WIND 12+ , passing/rec", g['Stat'].isin(PASS) & (g['WindMph']>=12), 'UNDER')
show("WIND 15+ , rushing", g['Stat'].isin(RUSH) & (g['WindMph']>=15), 'OVER')
show("COLD <=32F, passing/rec", g['Stat'].isin(PASS) & (g['Temperature']<=32), 'UNDER')
show("DOME/closed, passing/rec", g['Roof'].isin(['dome','closed']) & g['Stat'].isin(PASS), 'OVER')
show("OUTDOORS, passing/rec", (g['Roof']=='outdoors') & g['Stat'].isin(PASS), 'UNDER')

print("\nMODEL WIND TAGS ------------------------------------------------------")
sit=g['Situations'].fillna('')
show("tagged WIND_UNDER_SUPPORT", sit.str.contains('WIND_UNDER_SUPPORT'), 'UNDER')
show("tagged WIND_PASS_OVER_RISK -> fade over", sit.str.contains('WIND_PASS_OVER_RISK'), 'UNDER')

print("\nREST -----------------------------------------------------------------")
show("long rest 10+ (off bye)", g['RestDays']>=10, 'OVER')
show("long rest 10+ (off bye)", g['RestDays']>=10, 'UNDER')

print("\nHOT STREAK (does it fit NFL?) ----------------------------------------")
# per (Player,Stat) over-hit sequence by game date; streak = prior 2 overs
one=g[g['dir']=='OVER'].dropna(subset=['Line','ResultValue']).copy()
one['gd']=pd.to_datetime(one['GameDay'],errors='coerce')
one=one.dropna(subset=['gd']).drop_duplicates(['Player','Stat','GameDay']).sort_values(['Player','Stat','gd'])
one['over_hit']=(one['ResultValue']>one['Line']).astype(int)
o1=one.groupby(['Player','Stat'])['over_hit']
one['streak2']=(o1.shift(1)==1)&(o1.shift(2)==1)
one['ret']=[ret(p,w) for p,w in zip(one['BetPrice'],one['over_hit']==1)]
for label,mask in [("bet OVER after 2 straight overs", one['streak2']),
                   ("bet OVER (no streak, baseline)", ~one['streak2'])]:
    m=one[mask]; line=f"  {label:38s}"
    for season in ['2024','2025']:
        s=m[m['Season']==season]
        line+=f"   {season}: {s['ret'].mean()*100:+5.1f}% ROI (hit {(s['over_hit']==1).mean():.0%}, n={len(s):,})" if len(s)>=25 else f"   {season}: n={len(s)}"
    print(line)
print("\n(ROI at BetPrice. >0 = profitable. Want it positive in BOTH seasons.)")
