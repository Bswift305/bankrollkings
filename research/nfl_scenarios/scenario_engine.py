# -*- coding: utf-8 -*-
"""
NFL SCENARIO ENGINE — grade players and teams by EVERY main situation, from real snaps.

Data: data/pbp/nfl_pbp_2019_2025_slim.parquet  (nflverse play-by-play, 7 seasons
2019-2025, 344,622 plays, 61 columns: real down/distance/field-position/pressure/
drive-outcome/EPA on every snap). Every number here traces to a graded play — no
projections, no invented numbers. Thin samples are labeled and held below the boards.

This is the "information haven": the numbers to prove any claim.

============================== PLAYER BOARDS ==============================
  qb  <scenario>        QBs: conv%, EPA/db, success, comp%, CPOE, sack%, INT%, aDOT
  rb  <scenario>        RBs: yds/carry, success, EPA, move-chains%, stuff%, 10+%, TD%
  wr  <scenario>        WR/TE: targets, catch%, yds/tgt, YAC, aDOT, move%, TD%, deep%
  player "<name>"       auto-detect QB/RB/WR -> that player's full situational card

============================== TEAM PROFILES =============================
  team-off <TEAM>       one team's full offensive profile (all situations)
  team-def <TEAM>       one team's full defensive profile
  team-3rd              league: 3rd-down conversion % by distance bucket
  team-redzone          league: red-zone TD% per trip (offense + defense)
  team-drive            league: per-drive TD%, score%, giveaway%, 3-and-out%, plays/dr
  team-explosive        league: explosive pass (20+) & rush (10+) rate, for & against
  team-pressure         league: sack% & QB-hit% — pass-pro (offense) and pass-rush (def)
  team-early            league: early-down (1st/2nd) pass rate + EPA (tendency)

============================== SCENARIOS ================================
  3rd-short (1-3) · 3rd-med (4-6) · 3rd-long (7+) · 3rd-10plus (10+) · 4th-down
  redzone (<=20) · goalline (<=5) · deep (air 20+) · two-min (last 2:00) · any
  score states inside cards: leading / trailing / one-score

MODIFIERS  --season YYYY   --min N   --down D   --dist BUCKET
"""
import sys, argparse, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
PBP  = ROOT / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
pd.set_option("mode.chained_assignment", None)

# ------------------------------------------------------------------ scenarios
def dist_mask(df, spec):
    y = df["ydstogo"]
    return {"1-3": (y>=1)&(y<=3), "short": (y>=1)&(y<=3),
            "4-6": (y>=4)&(y<=6), "med": (y>=4)&(y<=6), "medium": (y>=4)&(y<=6),
            "7+": y>=7, "long": y>=7, "7plus": y>=7,
            "10+": y>=10, "10plus": y>=10}.get(str(spec).lower(), pd.Series(True, index=df.index))

SCENARIOS = {
    "3rd-short":  dict(down=3, dist="1-3",  label="3rd & short (1-3)"),
    "3rd-med":    dict(down=3, dist="4-6",  label="3rd & medium (4-6)"),
    "3rd-long":   dict(down=3, dist="7+",   label="3rd & long (7+)"),
    "3rd-10plus": dict(down=3, dist="10+",  label="3rd & 10+"),
    "4th-down":   dict(down=4, dist=None,   label="4th down"),
    "redzone":    dict(zone=20, label="red zone (<=20)"),
    "goalline":   dict(zone=5,  label="goal-to-go area (<=5)"),
    "deep":       dict(deep=True, label="deep shots (air 20+)"),
    "two-min":    dict(twomin=True, label="two-minute (last 2:00 of half)"),
    "any":        dict(label="all downs"),
}

def apply_scenario(df, down=None, dist=None, zone=None, twomin=False, deep=False, state=None):
    m = pd.Series(True, index=df.index)
    if down is not None: m &= df["down"] == down
    if dist is not None: m &= dist_mask(df, dist)
    if zone is not None: m &= df["yardline_100"] <= zone
    if twomin:           m &= df["half_seconds_remaining"] <= 120
    if deep:             m &= df["air_yards"] >= 20
    if state == "leading":  m &= df["score_differential"] > 0
    if state == "trailing": m &= df["score_differential"] < 0
    if state == "onescore": m &= df["score_differential"].abs() <= 8
    return df[m]

# ------------------------------------------------------------------ load
def load(season=None):
    df = pd.read_parquet(PBP)
    if season: df = df[df["season"] == int(season)].copy()
    df["qb_name"] = df["passer_player_name"]
    scr = (df["qb_scramble"] == 1) & df["qb_name"].isna()
    df.loc[scr, "qb_name"] = df.loc[scr, "rusher_player_name"]
    df["moved"] = ((df["first_down"] == 1) | (df["touchdown"] == 1)).astype(int)
    for c in ("third_down_converted","fourth_down_converted","qb_hit"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def _pct(x): return f"{x*100:.1f}%" if pd.notna(x) else "  -"
SPAN = lambda s: str(int(s)) if s else "2019-2025"

# ================================================================== QB
def qb_board(df, scen, season=None, minplays=25):
    s = SCENARIOS.get(scen, {}); down = s.get("down")
    plays = apply_scenario(df, **{k:s[k] for k in ("down","dist","zone","twomin","deep") if k in s})
    plays = plays[(plays["qb_dropback"] == 1) & plays["qb_name"].notna()]
    if plays.empty: print("no plays match."); return
    if down in (3, 4):
        plays["conv"] = plays["third_down_converted"] if down==3 else plays["fourth_down_converted"]
    else:
        plays["conv"] = plays["moved"]
    att = plays[plays["pass_attempt"] == 1]
    g = plays.groupby("qb_name").agg(n=("conv","size"), conv=("conv","mean"),
        epa=("epa","mean"), succ=("success","mean"), sack=("sack","mean"),
        intr=("interception","mean")).join(
        att.groupby("qb_name").agg(comp=("complete_pass","mean"), cpoe=("cpoe","mean"),
        adot=("air_yards","mean")))
    g = g.reset_index()
    board = g[g["n"] >= minplays].sort_values("conv", ascending=False)
    print(f"QB — {s.get('label',scen)}  ({SPAN(season)}, min {minplays} dropbacks)   qualifying: {len(board)}")
    print("="*88)
    print(f"{'QB':<15}{'Plays':>6}{'Conv%':>8}{'EPA':>7}{'Succ%':>7}{'Comp%':>7}{'CPOE':>7}{'Sack%':>7}{'INT%':>6}{'aDOT':>6}")
    for _, r in board.head(24).iterrows():
        print(f"{r['qb_name']:<15}{int(r['n']):>6}{_pct(r['conv']):>8}{r['epa']:>7.2f}{_pct(r['succ']):>7}"
              f"{_pct(r['comp']):>7}{r['cpoe']:>+7.1f}{_pct(r['sack']):>7}{_pct(r['intr']):>6}{r['adot']:>6.1f}")
    _thin(g, minplays, "qb_name")

# ================================================================== RB
def rb_board(df, scen, season=None, minplays=25):
    s = SCENARIOS.get(scen, {})
    plays = apply_scenario(df, **{k:s[k] for k in ("down","dist","zone","twomin") if k in s})
    plays = plays[(plays["rush_attempt"] == 1) & plays["rusher_player_name"].notna()]
    if plays.empty: print("no plays match."); return
    plays["stuff"] = (plays["yards_gained"] <= 0).astype(int)
    plays["expl"]  = (plays["yards_gained"] >= 10).astype(int)
    g = plays.groupby("rusher_player_name").agg(n=("yards_gained","size"),
        ypc=("yards_gained","mean"), succ=("success","mean"), epa=("epa","mean"),
        move=("moved","mean"), stuff=("stuff","mean"), expl=("expl","mean"),
        td=("rush_touchdown","mean")).reset_index()
    board = g[g["n"] >= minplays].sort_values("epa", ascending=False)
    print(f"RB — {s.get('label',scen)}  ({SPAN(season)}, min {minplays} carries)   qualifying: {len(board)}")
    print("="*82)
    print(f"{'RB':<17}{'Car':>5}{'Yds/C':>7}{'Succ%':>7}{'EPA':>7}{'Move%':>7}{'Stuff%':>8}{'10+%':>7}{'TD%':>6}")
    for _, r in board.head(24).iterrows():
        print(f"{r['rusher_player_name']:<17}{int(r['n']):>5}{r['ypc']:>7.1f}{_pct(r['succ']):>7}{r['epa']:>7.2f}"
              f"{_pct(r['move']):>7}{_pct(r['stuff']):>8}{_pct(r['expl']):>7}{_pct(r['td']):>6}")
    _thin(g, minplays, "rusher_player_name")

# ================================================================== WR/TE
def wr_board(df, scen, season=None, minplays=25):
    s = SCENARIOS.get(scen, {})
    plays = apply_scenario(df, **{k:s[k] for k in ("down","dist","zone","twomin","deep") if k in s})
    plays = plays[(plays["pass_attempt"] == 1) & plays["receiver_player_name"].notna()]
    if plays.empty: print("no plays match."); return
    plays["deept"] = (plays["air_yards"] >= 20).astype(int)
    comp = plays[plays["complete_pass"] == 1]
    g = plays.groupby("receiver_player_name").agg(tgt=("epa","size"), catch=("complete_pass","mean"),
        ypt=("yards_gained","mean"), epa=("epa","mean"), move=("moved","mean"),
        adot=("air_yards","mean"), deep=("deept","mean"), td=("pass_touchdown","mean")).join(
        comp.groupby("receiver_player_name").agg(yac=("yards_after_catch","mean")))
    g = g.reset_index()
    board = g[g["tgt"] >= minplays].sort_values("epa", ascending=False)
    print(f"WR/TE — {s.get('label',scen)}  ({SPAN(season)}, min {minplays} targets)   qualifying: {len(board)}")
    print("="*84)
    print(f"{'Receiver':<17}{'Tgt':>5}{'Catch%':>8}{'Yds/T':>7}{'YAC':>6}{'aDOT':>6}{'EPA':>7}{'Move%':>7}{'Deep%':>7}{'TD%':>6}")
    for _, r in board.head(24).iterrows():
        print(f"{r['receiver_player_name']:<17}{int(r['tgt']):>5}{_pct(r['catch']):>8}{r['ypt']:>7.1f}{r['yac']:>6.1f}"
              f"{r['adot']:>6.1f}{r['epa']:>7.2f}{_pct(r['move']):>7}{_pct(r['deep']):>7}{_pct(r['td']):>6}")
    _thin(g.rename(columns={"tgt":"n"}), minplays, "receiver_player_name")

def _thin(g, minplays, key):
    lo = max(8, minplays//3)
    thin = g[(g["n"] >= lo) & (g["n"] < minplays)] if "n" in g else pd.DataFrame()
    if len(thin):
        names = ", ".join(thin.sort_values("n", ascending=False)[key].head(6))
        print(f"\n(small sample {lo}-{minplays-1}, not ranked: {names} ...)")

# ================================================================== player card
def player_card(df, name):
    key = name.lower()
    asq = df[df["qb_name"].notna() & df["qb_name"].str.lower().str.contains(key)]
    asr = df[df["rusher_player_name"].notna() & df["rusher_player_name"].str.lower().str.contains(key)]
    asw = df[df["receiver_player_name"].notna() & df["receiver_player_name"].str.lower().str.contains(key)]
    counts = {"QB": len(asq[asq["qb_dropback"]==1]), "RB": len(asr), "WR": len(asw)}
    pos = max(counts, key=counts.get)
    if counts[pos] == 0: print(f"no player matching '{name}'."); return
    if pos == "QB":   _qb_card(asq)
    elif pos == "RB": _rb_card(asr)
    else:             _wr_card(asw)

def _sit_rows():
    return [("3rd & short (1-3)",dict(down=3,dist="1-3")),("3rd & medium (4-6)",dict(down=3,dist="4-6")),
            ("3rd & long (7+)",dict(down=3,dist="7+")),("3rd & 10+",dict(down=3,dist="10+")),
            ("1st down",dict(down=1)),("2nd & long (7+)",dict(down=2,dist="7+")),
            ("4th down",dict(down=4)),("red zone (<=20)",dict(zone=20)),
            ("goal-to-go (<=5)",dict(zone=5)),("two-minute",dict(twomin=True)),
            ("when leading",dict(state="leading")),("when trailing",dict(state="trailing"))]

def _qb_card(df):
    who = df["qb_name"].value_counts().index[0]; d = df[(df["qb_name"]==who)&(df["qb_dropback"]==1)]
    print(f"QB SCENARIO CARD — {who}   (2019-2025, {len(d):,} dropbacks)")
    print("="*74); print(f"{'Situation':<22}{'Plays':>6}{'Conv/Move%':>12}{'EPA':>7}{'Succ%':>7}{'Comp%':>7}")
    for lbl, sc in _sit_rows():
        s = apply_scenario(d, **sc)
        if len(s) < 8: print(f"{lbl:<22}{len(s):>6}   (small sample)"); continue
        dn = sc.get("down")
        c = s["third_down_converted"].mean() if dn==3 else s["fourth_down_converted"].mean() if dn==4 else s["moved"].mean()
        comp = s[s["pass_attempt"]==1]["complete_pass"].mean()
        print(f"{lbl:<22}{len(s):>6}{_pct(c):>12}{s['epa'].mean():>7.2f}{_pct(s['success'].mean()):>7}{_pct(comp):>7}")

def _rb_card(df):
    who = df["rusher_player_name"].value_counts().index[0]; d = df[df["rusher_player_name"]==who]
    print(f"RB SCENARIO CARD — {who}   (2019-2025, {len(d):,} carries)")
    print("="*66); print(f"{'Situation':<22}{'Car':>5}{'Yds/C':>7}{'Succ%':>7}{'EPA':>7}{'Move%':>7}")
    for lbl, sc in _sit_rows():
        if sc.get("down")==4: continue
        s = apply_scenario(d, **sc)
        if len(s) < 6: print(f"{lbl:<22}{len(s):>5}   (small sample)"); continue
        print(f"{lbl:<22}{len(s):>5}{s['yards_gained'].mean():>7.1f}{_pct(s['success'].mean()):>7}"
              f"{s['epa'].mean():>7.2f}{_pct(s['moved'].mean()):>7}")

def _wr_card(df):
    who = df["receiver_player_name"].value_counts().index[0]; d = df[df["receiver_player_name"]==who]
    print(f"WR/TE SCENARIO CARD — {who}   (2019-2025, {len(d):,} targets)")
    print("="*70); print(f"{'Situation':<22}{'Tgt':>5}{'Catch%':>8}{'Yds/T':>7}{'EPA':>7}{'Move%':>7}")
    for lbl, sc in _sit_rows():
        if sc.get("down")==4: continue
        s = apply_scenario(d, **sc)
        if len(s) < 6: print(f"{lbl:<22}{len(s):>5}   (small sample)"); continue
        print(f"{lbl:<22}{len(s):>5}{_pct(s['complete_pass'].mean()):>8}{s['yards_gained'].mean():>7.1f}"
              f"{s['epa'].mean():>7.2f}{_pct(s['moved'].mean()):>7}")

# ================================================================== team helpers
def _drive_stats(df, team_col, team, season=None):
    d = df[df[team_col] == team].copy()
    d["off_play"] = ((d["pass"] == 1) | (d["rush"] == 1)).astype(int)   # scrimmage snaps only (not the punt/FG)
    dr = d[d["fixed_drive"].notna()].groupby(["game_id","fixed_drive"]).agg(
        res=("fixed_drive_result","first"), plays=("off_play","sum")).reset_index()
    if dr.empty: return {}
    td = dr["res"].eq("Touchdown").mean()
    score = dr["res"].isin(["Touchdown","Field goal"]).mean()
    give = dr["res"].isin(["Turnover","Opp touchdown"]).mean()
    threeout = ((dr["plays"] <= 3) & dr["res"].eq("Punt")).mean()
    return dict(drives=len(dr), td=td, score=score, give=give, threeout=threeout, ppd=dr["plays"].mean())

def _rz_rate(df, team_col, team):
    rz = df[(df["yardline_100"] <= 20) & (df[team_col] == team) & df["fixed_drive"].notna()]
    if rz.empty: return np.nan, 0
    t = rz.groupby(["game_id","fixed_drive"]).agg(td=("pass_touchdown","max"), rtd=("rush_touchdown","max")).reset_index()
    t["td"] = ((t["td"]==1)|(t["rtd"]==1)).astype(int)
    return t["td"].mean(), len(t)

def _team_profile(df, team, side, season):
    off = side == "off"; oc, dc = ("posteam","defteam") if off else ("defteam","posteam")
    d = df[df[oc] == team]
    scr = d[d["down"].notna()]
    epa = scr["epa"].mean(); succ = scr["success"].mean()
    d3 = scr[scr["down"]==3]; conv3 = d3["third_down_converted"].mean()
    d3l = d3[d3["ydstogo"]>=7]; conv3l = d3l["third_down_converted"].mean() if len(d3l) else np.nan
    p = scr[scr["pass_attempt"]==1]; r = scr[scr["rush_attempt"]==1]
    xpass = (p["yards_gained"]>=20).mean() if len(p) else np.nan
    xrush = (r["yards_gained"]>=10).mean() if len(r) else np.nan
    early = scr[scr["down"].isin([1,2])]; passrate = early["pass"].mean() if len(early) else np.nan
    db = scr[scr["qb_dropback"]==1]; sackr = db["sack"].mean() if len(db) else np.nan; hitr = db["qb_hit"].mean() if len(db) else np.nan
    rz, rzn = _rz_rate(df, oc, team); dr = _drive_stats(df, oc, team, season)
    lab = "OFFENSE" if off else "DEFENSE"
    print(f"{team} {lab} PROFILE  ({SPAN(season)})")
    print("="*50)
    print(f"  EPA/play            {epa:>+7.3f}")
    print(f"  Success rate        {_pct(succ):>7}")
    print(f"  3rd-down conv%      {_pct(conv3):>7}    (3rd & long 7+: {_pct(conv3l)})")
    print(f"  Red-zone TD%/trip   {_pct(rz):>7}    (n={rzn})")
    print(f"  Explosive pass 20+  {_pct(xpass):>7}")
    print(f"  Explosive rush 10+  {_pct(xrush):>7}")
    print(f"  Early-down pass%    {_pct(passrate):>7}")
    print(f"  Sack% / QB-hit%     {_pct(sackr):>7} / {_pct(hitr)}   ({'allowed' if off else 'generated'})")
    if dr:
        print(f"  Per drive: TD {_pct(dr['td'])} | score {_pct(dr['score'])} | "
              f"giveaway {_pct(dr['give'])} | 3-out {_pct(dr['threeout'])} | plays {dr['ppd']:.1f}  (n={dr['drives']})")
    # split by game state (offense only)
    if off:
        for st, lbl in [("leading","when leading"),("trailing","when trailing")]:
            ss = apply_scenario(scr, state=st)
            if len(ss) > 50: print(f"  EPA {lbl:<14}{ss['epa'].mean():>+7.3f}   (pass% {_pct(ss[ss['down'].isin([1,2])]['pass'].mean())})")

# ================================================================== team leaderboards
def team_third(df, season=None, minplays=40):
    d3 = df[(df["down"]==3) & df["posteam"].notna()].copy()
    d3["conv"] = d3["third_down_converted"]
    d3["bucket"] = np.select([d3["ydstogo"]<=3, d3["ydstogo"]<=6, d3["ydstogo"]<=9],
                             ["short(1-3)","med(4-6)","long(7-9)"], default="10+")
    piv = d3.pivot_table(index="posteam", columns="bucket", values="conv", aggfunc="mean")
    cnt = d3.pivot_table(index="posteam", columns="bucket", values="conv", aggfunc="size")
    piv = piv.reindex(columns=[c for c in ["short(1-3)","med(4-6)","long(7-9)","10+"] if c in piv.columns])
    piv["ALL"] = d3.groupby("posteam")["conv"].mean()
    piv = piv[cnt.sum(axis=1) >= minplays].sort_values("ALL", ascending=False)
    print(f"TEAM 3rd-DOWN CONVERSION % by distance  ({SPAN(season)}, min {minplays})"); print("="*60)
    print(f"{'Team':<6}" + "".join(f"{c:>12}" for c in piv.columns))
    for tm, r in piv.iterrows():
        print(f"{tm:<6}" + "".join(f"{v*100:>11.1f}%" if pd.notna(v) else f"{'-':>12}" for v in r))

def team_redzone(df, season=None):
    rz = df[(df["yardline_100"]<=20) & df["posteam"].notna() & df["fixed_drive"].notna()].copy()
    trips = rz.groupby(["game_id","fixed_drive","posteam","defteam"]).agg(
        td=("pass_touchdown","max"), rtd=("rush_touchdown","max")).reset_index()
    trips["td"] = ((trips["td"]==1)|(trips["rtd"]==1)).astype(int)
    off = trips.groupby("posteam").agg(trips=("td","size"), td=("td","mean")).reset_index()
    dff = trips.groupby("defteam").agg(trips=("td","size"), td=("td","mean")).reset_index()
    off = off[off["trips"]>=20].sort_values("td", ascending=False)
    dff = dff[dff["trips"]>=20].sort_values("td")
    print(f"RED-ZONE TD% per trip  ({SPAN(season)}, min 20 trips)"); print("="*56)
    print(f"{'OFFENSE (best scoring)':<28}{'DEFENSE (best stopping)':<28}")
    for i in range(16):
        o = off.iloc[i] if i<len(off) else None; d = dff.iloc[i] if i<len(dff) else None
        lo = f"{o['posteam']:<5}{o['td']*100:>6.1f}%  ({int(o['trips'])})" if o is not None else ""
        ld = f"{d['defteam']:<5}{d['td']*100:>6.1f}%  ({int(d['trips'])})" if d is not None else ""
        print(f"{lo:<28}{ld:<28}")

def team_drive(df, season=None, side="posteam"):
    teams = sorted(df[side].dropna().unique())
    rows = [dict(Team=t, **_drive_stats(df, side, t, season)) for t in teams]
    b = pd.DataFrame([r for r in rows if r.get("drives",0) >= 40]).sort_values("td", ascending=False)
    lab = "OFFENSE" if side=="posteam" else "DEFENSE (allowed)"
    print(f"TEAM PER-DRIVE — {lab}  ({SPAN(season)})"); print("="*62)
    print(f"{'Team':<6}{'Drives':>7}{'TD%':>8}{'Score%':>8}{'Giveaway%':>11}{'3-out%':>8}{'Plays':>7}")
    for _, r in b.iterrows():
        print(f"{r['Team']:<6}{int(r['drives']):>7}{_pct(r['td']):>8}{_pct(r['score']):>8}"
              f"{_pct(r['give']):>11}{_pct(r['threeout']):>8}{r['ppd']:>7.1f}")

def team_explosive(df, season=None):
    scr = df[df["down"].notna() & df["posteam"].notna()]
    def rates(gcol):
        p = scr[scr["pass_attempt"]==1]; r = scr[scr["rush_attempt"]==1]
        xp = p.assign(x=(p["yards_gained"]>=20).astype(int)).groupby(gcol)["x"].mean()
        xr = r.assign(x=(r["yards_gained"]>=10).astype(int)).groupby(gcol)["x"].mean()
        n  = scr.groupby(gcol).size()
        return pd.DataFrame({"xpass":xp,"xrush":xr,"n":n})
    off = rates("posteam"); dff = rates("defteam")
    off = off[off["n"]>=300].sort_values("xpass", ascending=False)
    print(f"EXPLOSIVE PLAY RATE  ({SPAN(season)})  pass 20+ / rush 10+"); print("="*58)
    print(f"{'Team':<6}{'Pass20+ (off)':>15}{'Rush10+ (off)':>15}{'Pass20+ allowed':>17}")
    for tm, r in off.iterrows():
        da = dff.loc[tm,"xpass"] if tm in dff.index else np.nan
        print(f"{tm:<6}{_pct(r['xpass']):>15}{_pct(r['xrush']):>15}{_pct(da):>17}")

def team_pressure(df, season=None):
    db = df[(df["qb_dropback"]==1)]
    off = db.groupby("posteam").agg(n=("sack","size"), sack=("sack","mean"), hit=("qb_hit","mean"))
    dff = db.groupby("defteam").agg(n=("sack","size"), sack=("sack","mean"), hit=("qb_hit","mean"))
    off = off[off["n"]>=200].sort_values("sack")           # best pass-pro = fewest sacks
    dff = dff[dff["n"]>=200].sort_values("sack", ascending=False)  # best rush = most sacks
    print(f"PRESSURE  ({SPAN(season)})   sack% & QB-hit% per dropback"); print("="*60)
    print(f"{'PASS-PRO (offense, low=good)':<30}{'PASS-RUSH (defense, high=good)':<30}")
    for i in range(16):
        o = off.reset_index().iloc[i] if i<len(off) else None
        d = dff.reset_index().iloc[i] if i<len(dff) else None
        lo = f"{o['posteam']:<5} sack {o['sack']*100:>4.1f}% hit {o['hit']*100:>4.1f}%" if o is not None else ""
        ld = f"{d['defteam']:<5} sack {d['sack']*100:>4.1f}% hit {d['hit']*100:>4.1f}%" if d is not None else ""
        print(f"{lo:<30}{ld:<30}")

def team_early(df, season=None):
    e = df[df["down"].isin([1,2]) & df["posteam"].notna()]
    g = e.groupby("posteam").agg(n=("pass","size"), passrate=("pass","mean"), epa=("epa","mean"))
    g = g[g["n"]>=300].sort_values("passrate", ascending=False)
    print(f"EARLY-DOWN (1st/2nd) TENDENCY  ({SPAN(season)})  pass rate + EPA/play"); print("="*50)
    print(f"{'Team':<6}{'Pass%':>9}{'EPA/play':>11}{'Plays':>8}")
    for tm, r in g.iterrows():
        print(f"{tm:<6}{_pct(r['passrate']):>9}{r['epa']:>+11.3f}{int(r['n']):>8}")

# ================================================================== cli
def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?", default="help")
    ap.add_argument("arg", nargs="?", default=None)
    ap.add_argument("--season", default=None); ap.add_argument("--min", type=int, default=None)
    ap.add_argument("--down", type=int, default=None); ap.add_argument("--dist", default=None)
    a = ap.parse_args()
    if a.cmd == "help": print(__doc__); return
    if a.cmd == "scenarios":
        for k, v in SCENARIOS.items(): print(f"  {k:<12} {v.get('label','')}")
        return
    df = load(a.season)
    # allow ad-hoc --down/--dist to define a scenario on the fly
    if a.down is not None or a.dist is not None:
        SCENARIOS["_adhoc"] = dict(down=a.down, dist=a.dist,
            label=f"{a.down or 'any'} down, {a.dist or 'any'} to go"); scen = "_adhoc"
    else:
        scen = a.arg or "3rd-10plus"
    mn = a.min or 25
    if   a.cmd == "qb":  qb_board(df, scen, a.season, mn)
    elif a.cmd == "rb":  rb_board(df, scen, a.season, mn)
    elif a.cmd == "wr":  wr_board(df, scen, a.season, mn)
    elif a.cmd == "player": player_card(df, a.arg or "")
    elif a.cmd == "team-off": _team_profile(df, (a.arg or "").upper(), "off", a.season)
    elif a.cmd == "team-def": _team_profile(df, (a.arg or "").upper(), "def", a.season)
    elif a.cmd == "team-3rd": team_third(df, a.season, a.min or 40)
    elif a.cmd == "team-redzone": team_redzone(df, a.season)
    elif a.cmd == "team-drive": team_drive(df, a.season, "posteam" if a.arg!="def" else "defteam")
    elif a.cmd == "team-explosive": team_explosive(df, a.season)
    elif a.cmd == "team-pressure": team_pressure(df, a.season)
    elif a.cmd == "team-early": team_early(df, a.season)
    else: print(__doc__)

if __name__ == "__main__":
    main()
