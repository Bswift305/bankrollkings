# -*- coding: utf-8 -*-
"""CFB 'Reveal' test: a clean-slate, in-season-only Elo (NO preseason priors) that learns
game-by-game. Does its number beat the MARKET spread once teams have tape? Tests the
'react, don't predict' thesis on 2025. Bet ATS at flat -110 when model diverges from market,
only after each team has played >= G games. Split by how much tape exists."""
import numpy as np, pandas as pd
ROOT="C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls"

def norm(s): return ''.join(c for c in str(s).lower() if c.isalnum())
def core(n):
    t=str(n).split(); return norm(' '.join(t[:-1])) if len(t)>1 else norm(n)

# --- games (scores) in chronological order to BUILD Elo ---
g=pd.read_csv(f"{ROOT}/data/historical/NCAAF_CFBD_Games_2025.csv",dtype=str,low_memory=False)
for c in ['HomeScore','AwayScore']: g[c]=pd.to_numeric(g[c],errors='coerce')
g['dt']=pd.to_datetime(g['Date'],errors='coerce')
g=g.dropna(subset=['HomeScore','AwayScore','dt']).sort_values('dt').reset_index(drop=True)
g['wk']=pd.to_numeric(g['Week'],errors='coerce')

# --- market lines (consensus) to TEST betting ---
h=pd.read_csv(f"{ROOT}/data/historical/NCAAF_OddsAPI_GameLines_History.csv",dtype=str,low_memory=False)
h['Spread']=pd.to_numeric(h['Spread'],errors='coerce')
L=h.groupby('GameID').agg(Home=('Home','first'),Away=('Away','first'),Spread=('Spread','median')).reset_index()
L['hk']=L['Home'].map(core); L['ak']=L['Away'].map(core)
mkt={(r['hk'],r['ak']):r['Spread'] for _,r in L.iterrows() if pd.notna(r['Spread'])}

# --- clean-slate Elo, walk forward ---
HFA=65.0; K=42.0; PPE=25.0  # home-field Elo, K-factor, Elo-per-point
elo={}; played={}
def E(a,b): return 1/(1+10**((b-a)/400))
bets=[]
for _,r in g.iterrows():
    hk,ak=norm(r['Home']),norm(r['Away'])
    rh=elo.get(hk,1500.0); ra=elo.get(ak,1500.0)
    ph,pa=rh+HFA,ra
    model_home_spread=-(ph-pa)/PPE            # neg = home favored by N
    gh,ga=played.get(hk,0),played.get(ak,0)   # games of tape each team has
    if (hk,ak) in mkt and min(gh,ga)>=1:
        ms=mkt[(hk,ak)]                        # market home spread
        edge=ms-model_home_spread              # >0: model likes home MORE than market
        margin=r['HomeScore']-r['AwayScore']
        home_cover=(margin+ms)>0
        bet_home = edge>0
        win = home_cover if bet_home else (not home_cover)
        bets.append({'wk':r['wk'],'tape':min(gh,ga),'edge':abs(edge),'win':win})
    # update Elo
    eh=E(ph,pa); ah=1.0 if r['HomeScore']>r['AwayScore'] else (0.5 if r['HomeScore']==r['AwayScore'] else 0.0)
    m=abs(r['HomeScore']-r['AwayScore']); diff=(ph-pa) if ah==1 else (pa-ph)
    mov=np.log(m+1)*(2.2/(diff*0.001+2.2))
    d=K*mov*(ah-eh); elo[hk]=rh+d; elo[ak]=ra-d
    played[hk]=gh+1; played[ak]=ga+1

b=pd.DataFrame(bets)
roi=lambda w: w*(100/110)-(1-w)
def show(name, sub):
    if len(sub)<25: print(f"  {name:34s} n={len(sub)} (small)"); return
    w=sub['win'].mean(); print(f"  {name:34s} {w:.1%} cover -> {roi(w)*100:+5.1f}% @-110  (n={len(sub):,})")
print(f"total model-vs-market bets: {len(b):,}   (break-even 52.4%)")
print("\nBY TAPE (min games each team has played) ----------------------------")
for lo,hi,lab in [(1,2,'1-2 games (thin)'),(3,4,'3-4 games'),(5,7,'5-7 games'),(8,20,'8+ games')]:
    show(lab, b[(b['tape']>=lo)&(b['tape']<=hi)])
print("\nWITH TAPE >=4  x  MODEL EDGE size ----------------------------------")
t=b[b['tape']>=4]
for lo,lab in [(0,'any edge'),(3,'edge >=3 pts'),(6,'edge >=6 pts'),(10,'edge >=10 pts')]:
    show(lab, t[t['edge']>=lo])
print("\nBY WEEK BUCKET (tape>=4) -------------------------------------------")
show("weeks 5-9",  t[(t['wk']>=5)&(t['wk']<=9)])
show("weeks 10-15",t[t['wk']>=10])
