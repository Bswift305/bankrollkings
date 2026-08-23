# -*- coding: utf-8 -*-
"""
MLB SITUATIONAL ENGINE — grade hitters and pitchers by situation, from real pitches.

Data: data/pbp/MLB_statcast_pbp_<year>.parquet (Statcast pitch-by-pitch; count,
base-out state, batter/pitcher handedness, pitch type, outcome on every pitch).
Every number traces to a real plate appearance — no projections, no invented data.
Thin samples are labeled and held below the boards.

    python research/mlb_statcast/mlb_situational.py hitters vs_lhp
    python research/mlb_statcast/mlb_situational.py hitters risp --min 40
    python research/mlb_statcast/mlb_situational.py pitchers tto3
    python research/mlb_statcast/mlb_situational.py scenarios

Hitter scenarios:  overall · vs_rhp · vs_lhp · risp · bases_empty
Pitcher scenarios: overall · vs_rhb · vs_lhb · tto1 · tto3 · first_inning
"""
import sys, argparse, pathlib, glob, warnings
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
PBP_GLOB = str(ROOT / "data" / "pbp" / "MLB_statcast_pbp_*.parquet")
NAMES = ROOT / "data" / "pbp" / "mlb_player_names.csv"

def _titlecase(s): return " ".join(w.capitalize() for w in str(s).split())

def batter_names(ids):
    """id -> 'First Last', cached to a CSV so we hit the lookup once."""
    cache = {}
    if NAMES.exists():
        c = pd.read_csv(NAMES)
        cache = {int(r["id"]): r["name"] for _, r in c.iterrows()}
    missing = [int(i) for i in ids if int(i) not in cache]
    if missing:
        from pybaseball import playerid_reverse_lookup
        m = playerid_reverse_lookup(missing, key_type="mlbam")
        for _, r in m.iterrows():
            cache[int(r["key_mlbam"])] = _titlecase(f"{r['name_first']} {r['name_last']}")
        pd.DataFrame([{"id": k, "name": v} for k, v in cache.items()]).to_csv(NAMES, index=False)
    return cache

def load(season=None):
    files = sorted(glob.glob(PBP_GLOB))
    if season: files = [f for f in files if str(season) in f]
    if not files: raise SystemExit(f"no pbp parquet found at {PBP_GLOB}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    # pitcher name is already in player_name as "Last, First"
    df["pit_name"] = df["player_name"].apply(lambda s: _titlecase(f"{str(s).split(',')[1]} {str(s).split(',')[0]}") if isinstance(s,str) and "," in s else str(s))
    return df

def pa_table(df):
    """one row per plate appearance (the pitch that ended it), + TTO."""
    pa = df[df["events"].notna()].copy()
    pa["k"]   = pa["events"].isin(["strikeout","strikeout_double_play"]).astype(int)
    pa["bb"]  = (pa["events"] == "walk").astype(int)
    pa["hr"]  = (pa["events"] == "home_run").astype(int)
    pa["risp"] = (pa["on_2b"].notna() | pa["on_3b"].notna())
    pa["hard"] = np.where(pa["launch_speed"].notna(), (pa["launch_speed"] >= 95).astype(float), np.nan)
    pa["woba_num"] = pd.to_numeric(pa["woba_value"], errors="coerce")
    pa["woba_den"] = pd.to_numeric(pa["woba_denom"], errors="coerce")
    # times through order: within (game, pitcher), order PAs, //9 + 1
    pa = pa.sort_values(["game_pk","pitcher","at_bat_number"])
    pa["tto"] = pa.groupby(["game_pk","pitcher"]).cumcount() // 9 + 1
    return pa

H_SCEN = {"overall":("All PA", lambda d: d),
          "vs_rhp":("vs RHP", lambda d: d[d["p_throws"]=="R"]),
          "vs_lhp":("vs LHP", lambda d: d[d["p_throws"]=="L"]),
          "risp":("RISP", lambda d: d[d["risp"]]),
          "bases_empty":("Bases empty", lambda d: d[~(d["on_1b"].notna()|d["on_2b"].notna()|d["on_3b"].notna())])}
P_SCEN = {"overall":("All PA", lambda d: d),
          "vs_rhb":("vs RHB", lambda d: d[d["stand"]=="R"]),
          "vs_lhb":("vs LHB", lambda d: d[d["stand"]=="L"]),
          "tto1":("1st time through order", lambda d: d[d["tto"]==1]),
          "tto3":("3rd+ time through order", lambda d: d[d["tto"]>=3]),
          "first_inning":("First inning", lambda d: d[d["inning"]==1])}

def _agg(g):
    pa = len(g); den = g["woba_den"].sum()
    return dict(n=pa, woba=(g["woba_num"].sum()/den if den else np.nan),
                k=g["k"].mean(), bb=g["bb"].mean(),
                hard=g["hard"].mean(), hr=int(g["hr"].sum()))

def board(role, scen, season=None, minpa=None):
    df = load(season); pa = pa_table(df)
    scens = H_SCEN if role=="hitters" else P_SCEN
    if scen not in scens: print("unknown scenario; try 'scenarios'"); return
    label, fn = scens[scen]; sub = fn(pa)
    idcol = "batter" if role=="hitters" else "pitcher"
    minpa = minpa or (150 if scen in("overall","vs_rhp","bases_empty") else 40)
    rows = []
    for pid, g in sub.groupby(idcol):
        a = _agg(g)
        if a["n"] >= minpa: rows.append((pid, a))
    if not rows: print("no qualifiers."); return
    if role=="hitters":
        names = batter_names([pid for pid,_ in rows])
        namef = lambda pid: names.get(int(pid), str(pid))
    else:
        pmap = df.groupby("pitcher")["pit_name"].first().to_dict()
        namef = lambda pid: pmap.get(pid, str(pid))
    b = pd.DataFrame([{"Player":namef(pid), **a} for pid,a in rows])
    b = b.sort_values("woba", ascending=(role=="pitchers"))  # hitters high=good, pitchers low=good
    span = season or "2025"
    who = "HITTER" if role=="hitters" else "PITCHER (wOBA against)"
    print(f"MLB {who} — {label}  ({span}, min {minpa} PA)   qualifying: {len(b)}")
    print("="*66)
    print(f"{'Player':<22}{'PA':>5}{'wOBA':>7}{'K%':>7}{'BB%':>7}{'HardH%':>8}{'HR':>5}")
    for _,r in b.head(25).iterrows():
        print(f"{r['Player']:<22}{int(r['n']):>5}{r['woba']:>7.3f}{r['k']*100:>6.1f}%{r['bb']*100:>6.1f}%"
              f"{(r['hard']*100 if pd.notna(r['hard']) else float('nan')):>7.1f}%{r['hr']:>5}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("role", nargs="?", default="hitters")
    ap.add_argument("scen", nargs="?", default="overall")
    ap.add_argument("--season", default=None); ap.add_argument("--min", type=int, default=None)
    a = ap.parse_args()
    if a.role == "scenarios":
        print("hitters:", ", ".join(H_SCEN)); print("pitchers:", ", ".join(P_SCEN)); sys.exit()
    board(a.role, a.scen, a.season, a.min)
