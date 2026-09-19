# -*- coding: utf-8 -*-
"""Hot-streak + opportunity SIGNAL backtest on real NBA game logs (2025-26).
Tests: after a player goes OVER a rolling line 2 games in a row, is the NEXT game
elevated vs base rate? And does teammate-out OPPORTUNITY / home-away / opp-defense
change that? Leakage-free (line = trailing-10 median of PRIOR games). OOS split by
season half.  No market prices here -> this measures SIGNAL, not ROI-vs-close."""
import pandas as pd, numpy as np

g = pd.read_csv("C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls/data/gamelogs/NBA_GameLogs.csv",
                dtype=str, low_memory=False)
g['Date'] = pd.to_datetime(g['Date'], errors='coerce')

def to_min(x):
    x = str(x).strip()
    if ':' in x:
        a,b = x.split(':')[:2]
        try: return float(a) + float(b)/60.0
        except: return np.nan
    try: return float(x)
    except: return np.nan
g['MINf'] = g['MIN'].map(to_min)
for s in ['PTS','REB','AST']:
    g[s] = pd.to_numeric(g[s], errors='coerce')
g['home'] = ~g['Matchup'].astype(str).str.contains('@')   # "TEAM @ OPP" = away
g = g.dropna(subset=['Date','PlayerID','Team','Game_ID']).sort_values(['PlayerID','Date']).reset_index(drop=True)
g = g[g['MINf'] > 0]

season_mid = g['Date'].quantile(0.5)

# ---- presence / rotation / stars per team (for opportunity) ----
present = g.groupby(['Team','Game_ID'])['PlayerID'].apply(lambda s: set(s)).to_dict()
prof = g.groupby(['Team','PlayerID']).agg(games=('MINf','size'), avgmin=('MINf','mean'), avgpts=('PTS','mean')).reset_index()
rotation = {}   # team -> set of rotation PlayerIDs (avg >=18 min, >=10 games)
stars = {}      # team -> set of top-2 scorers (rotation)
for team, sub in prof.groupby('Team'):
    rot = sub[(sub['avgmin']>=18) & (sub['games']>=10)]
    rotation[team] = set(rot['PlayerID'])
    stars[team] = set(rot.sort_values('avgpts', ascending=False).head(2)['PlayerID'])

def out_context(row):
    t, gid, pid = row['Team'], row['Game_ID'], row['PlayerID']
    pres = present.get((t,gid), set())
    rot = rotation.get(t, set()) - {pid}
    out = rot - pres
    star_out = bool((stars.get(t,set()) - {pid}) & out)
    return pd.Series({'any_out': len(out) >= 1, 'star_out': star_out})
g[['any_out','star_out']] = g.apply(out_context, axis=1)

# ---- opponent defense: avg stat conceded per Opp (team-level), soft = top third allowed ----
def report_stat(stat):
    d = g.copy()
    # line = trailing-10 median of PRIOR games (leakage-free)
    d['line'] = d.groupby('PlayerID')[stat].transform(lambda x: x.shift(1).rolling(10, min_periods=10).median())
    d = d.dropna(subset=['line', stat])
    d['over'] = (d[stat] > d['line']).astype(int)
    d['o1'] = d.groupby('PlayerID')['over'].shift(1)
    d['o2'] = d.groupby('PlayerID')['over'].shift(2)
    d['streak2'] = ((d['o1']==1) & (d['o2']==1))
    # opponent defense (allowed): mean of `stat` by opponent across all games
    opp_allowed = d.groupby('Opp')[stat].mean()
    thr = opp_allowed.quantile(2/3)
    d['soft_opp'] = d['Opp'].map(opp_allowed) >= thr    # allows a lot = soft
    d['half'] = np.where(d['Date'] <= season_mid, 'H1(in-samp)', 'H2(out-samp)')

    def rate(mask):
        m = d[mask]
        return (len(m), m['over'].mean() if len(m) else np.nan, (m[stat]-m['line']).mean() if len(m) else np.nan)

    print(f"\n================  {stat}  ================")
    base_n, base_r, _ = rate(d.index==d.index)  # all
    print(f"BASE over-rate (all eligible games): {base_r:.1%}   n={base_n:,}")
    for half in ['H1(in-samp)','H2(out-samp)']:
        h = d['half']==half
        n_s, r_s, lift_s = rate(h & d['streak2'])
        n_b, r_b, _      = rate(h & ~d['streak2'])
        print(f"\n  [{half}]  base(no streak) {r_b:.1%} (n={n_b:,})   |   after 2-streak {r_s:.1%} (n={n_s:,})   lift={ (r_s-r_b)*100:+.1f}pp")
        # opportunity split WITHIN post-streak
        for label, mm in [("  streak + STAR teammate OUT", h & d['streak2'] & d['star_out']),
                          ("  streak + any rotation OUT ", h & d['streak2'] & d['any_out']),
                          ("  streak + full lineup       ", h & d['streak2'] & ~d['any_out']),
                          ("  streak + HOME              ", h & d['streak2'] & d['home']),
                          ("  streak + AWAY              ", h & d['streak2'] & ~d['home']),
                          ("  streak + SOFT opp (allows) ", h & d['streak2'] & d['soft_opp']),
                          ("  streak + TOUGH opp         ", h & d['streak2'] & ~d['soft_opp'])]:
            n,r,lift = rate(mm)
            flag = "  <-- small n" if n < 60 else ""
            print(f"    {label}: {r:.1%}  (n={n:,})  avg vs line {lift:+.2f}{flag}")

for s in ['PTS','REB','AST']:
    report_stat(s)
print("\nNOTE: 'over' = beat the player's trailing-10 median (a prop-line proxy). This")
print("measures predictive SIGNAL, not profit vs the real closing number.")
