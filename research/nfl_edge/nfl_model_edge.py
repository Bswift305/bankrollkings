# -*- coding: utf-8 -*-
"""Does the NFL model's own edge actually beat the market? (real ROI at BetPrice,
2024 scout / 2025 out-of-sample). One bet per prop = the model's LEAN side
(Confidence>50), so no tautology."""
import pandas as pd, numpy as np
ROOT="C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls"
df=pd.read_csv(f"{ROOT}/data/tracking/NFL_AllPropResults_Scored.csv",dtype=str,low_memory=False)
g=df[df['OutcomeState'].isin(['Hit','Miss'])].copy()
for c in ['BetPrice','Confidence','BK_NFL_EdgeScore','BK_NFL_PropScore','UsageStability','GameScriptEdge','MatchupEdge']:
    g[c]=pd.to_numeric(g[c],errors='coerce')
g=g[g['BetPrice'].between(-1000,1000)]
g['win']=g['OutcomeState']=='Hit'
def ret(p,w):
    dec=1+(p/100 if p>0 else 100/abs(p)); return (dec-1) if w else -1.0
g['ret']=[ret(p,w) for p,w in zip(g['BetPrice'],g['win'])]

# the model's LEAN = the side with Confidence > 50 (one row per prop)
lean = g[g['Confidence']>50].copy()
print(f"model-lean bets (one per prop): {len(lean):,}")

def roi(sub):
    return f"{sub['ret'].mean()*100:+5.1f}% (hit {sub['win'].mean():.0%}, n={len(sub):,})" if len(sub)>=30 else f"n={len(sub)} (small)"
def line(name, sub):
    print(f"  {name:42s}  2024: {roi(sub[sub['Season']=='2024'])}   2025: {roi(sub[sub['Season']=='2025'])}")

print("\nMODEL LEAN, by edge-score strength ----------------------------------")
line("all model leans", lean)
for thr in [5,10,15,20]:
    line(f"EdgeScore >= {thr}", lean[lean['BK_NFL_EdgeScore']>=thr])
print("  (want ROI to climb as EdgeScore rises, and stay + in BOTH seasons)")

print("\nMODEL LEAN, by PropScore --------------------------------------------")
for thr in [10,20]:
    line(f"PropScore >= {thr}", lean[lean['BK_NFL_PropScore']>=thr])

print("\nSITUATIONAL TAGS (bet model lean within tag) ------------------------")
sit=lean['Situations'].fillna('')
for tag in ['LOW_TOTAL_UNDER_SUPPORT','PROJECTED_TIGHT_GAME','LOW_TOTAL','HIGH_TOTAL','DIVISION_GAME']:
    line(f"tag: {tag}", lean[sit.str.contains(tag)])

print("\nUSAGE / SCRIPT / MATCHUP edges (model lean) -------------------------")
line("UsageStability top quartile", lean[lean['UsageStability']>=lean['UsageStability'].quantile(.75)])
line("GameScriptEdge >= 4", lean[lean['GameScriptEdge']>=4])
line("MatchupEdge >= 4", lean[lean['MatchupEdge']>=4])

print("\nBY STAT GROUP (model lean, EdgeScore>=10) --------------------------")
strong=lean[lean['BK_NFL_EdgeScore']>=10]
for rl in ['RECEIVING','PASSING','RUSHING']:
    line(f"{rl}", strong[strong['RoleLabel']==rl])
