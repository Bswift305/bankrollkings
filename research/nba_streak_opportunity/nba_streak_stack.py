# -*- coding: utf-8 -*-
"""Part 2: stack the filters, add significance + break-even framing, test a
3-game streak, and take an early read against the LOCAL graded props (small)."""
import pandas as pd, numpy as np
ROOT = "C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls"

g = pd.read_csv(f"{ROOT}/data/gamelogs/NBA_GameLogs.csv", dtype=str, low_memory=False)
g['Date'] = pd.to_datetime(g['Date'], errors='coerce')
def to_min(x):
    x=str(x).strip()
    if ':' in x:
        try: a,b=x.split(':')[:2]; return float(a)+float(b)/60
        except: return np.nan
    try: return float(x)
    except: return np.nan
g['MINf']=g['MIN'].map(to_min)
for s in ['PTS','REB','AST']: g[s]=pd.to_numeric(g[s],errors='coerce')
g['home']=~g['Matchup'].astype(str).str.contains('@')
g=g.dropna(subset=['Date','PlayerID','Team','Game_ID']).sort_values(['PlayerID','Date']).reset_index(drop=True)
g=g[g['MINf']>0]

present=g.groupby(['Team','Game_ID'])['PlayerID'].apply(set).to_dict()
prof=g.groupby(['Team','PlayerID']).agg(games=('MINf','size'),avgmin=('MINf','mean'),avgpts=('PTS','mean')).reset_index()
rotation={};stars={}
for t,sub in prof.groupby('Team'):
    rot=sub[(sub['avgmin']>=18)&(sub['games']>=10)]
    rotation[t]=set(rot['PlayerID']); stars[t]=set(rot.sort_values('avgpts',ascending=False).head(2)['PlayerID'])
def oc(r):
    pres=present.get((r['Team'],r['Game_ID']),set()); rot=rotation.get(r['Team'],set())-{r['PlayerID']}
    out=rot-pres; return pd.Series({'star_out':bool((stars.get(r['Team'],set())-{r['PlayerID']})&out)})
g['star_out']=g.apply(oc,axis=1)['star_out']

def ci(p,n):
    if n==0: return (np.nan,np.nan)
    h=1.96*np.sqrt(p*(1-p)/n); return (p-h,p+h)

def analyze(stat, streak_len=2):
    d=g.copy()
    d['line']=d.groupby('PlayerID')[stat].transform(lambda x:x.shift(1).rolling(10,min_periods=10).median())
    d=d.dropna(subset=['line',stat]); d['over']=(d[stat]>d['line']).astype(int)
    ov=d.groupby('PlayerID')['over']
    streak = pd.Series(True,index=d.index)
    for k in range(1,streak_len+1): streak &= (ov.shift(k)==1)
    d['streak']=streak
    opp_allowed=d.groupby('Opp')[stat].mean(); d['soft']=d['Opp'].map(opp_allowed)>=opp_allowed.quantile(2/3)
    base=d['over'].mean()
    def cell(m):
        mm=d[m]; n=len(mm); p=mm['over'].mean() if n else np.nan
        lo,hi=ci(p,n); return n,p,lo,hi,(mm[stat]-mm['line']).mean() if n else np.nan
    print(f"\n===== {stat}  ({streak_len}-game streak) =====   base={base:.1%}")
    rows=[("streak alone", d['streak']),
          ("streak + star OUT", d['streak']&d['star_out']),
          ("streak + soft opp", d['streak']&d['soft']),
          ("streak + star OUT + soft opp  (STACK)", d['streak']&d['star_out']&d['soft'])]
    for lab,m in rows:
        n,p,lo,hi,lift=cell(m)
        be = "  BEATS -110" if lo>0.524 else ("  ~coin-flip vs -110" if p and p>0.50 else "")
        print(f"  {lab:42s} {p:.1%}  95%CI[{lo:.1%},{hi:.1%}]  n={n:,}  +{lift:.2f} vs line{be}")

for s in ['PTS','REB','AST']:
    analyze(s,2)
analyze('PTS',3)  # does a longer streak help?

# ---- early read vs LOCAL graded props (small; honest about n) ----
print("\n\n===== EARLY READ vs LOCAL graded props (real outcomes) =====")
pr=pd.read_csv(f"{ROOT}/data/tracking/NBA_AllPropResults.csv",dtype=str,low_memory=False)
pr['OutcomeState']=pr['OutcomeState'].astype(str)
graded=pr[pr['OutcomeState'].isin(['Hit','Miss'])].copy()
print(f"graded props total: {len(graded):,}  (Hit={ (graded['OutcomeState']=='Hit').sum() }, Miss={ (graded['OutcomeState']=='Miss').sum() })")
def numeric(c): return pd.to_numeric(graded[c],errors='coerce')
price = numeric('ClosePrice').fillna(numeric('MarketPrice')).fillna(numeric('BetPrice'))
graded['price']=price
withprice=graded[graded['price'].notna()]
print(f"graded WITH a usable price: {len(withprice):,}")
if len(withprice):
    def payout(row):
        p=row['price']; win = row['OutcomeState']=='Hit'
        dec = 1+ (p/100 if p>0 else 100/abs(p))
        return (dec-1) if win else -1.0
    withprice=withprice.copy(); withprice['ret']=withprice.apply(payout,axis=1)
    print(f"  overall ROI on graded+priced props: {withprice['ret'].mean()*100:+.1f}%  (n={len(withprice):,})")
    print("  NOTE: tiny, off-season snapshot sample, StreakLen not stored -> cannot")
    print("  reliably tag streak+opportunity here. Real test needs the in-season prod archive.")
