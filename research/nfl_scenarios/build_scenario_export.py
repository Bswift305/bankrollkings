# -*- coding: utf-8 -*-
"""
Precompute the NFL Scenario Lab site data -> data/scenarios/nfl_scenarios.json.

The site page reads this ONE static JSON (no pandas/parquet needed at request time,
memory-safe on prod). Regenerate whenever the slim PBP file gains a season:
    python research/nfl_scenarios/build_scenario_export.py

Every table is generic: {columns:[{label,fmt}], rows:[[...]]} so one JS renderer
handles all of them. Percent values are stored as fractions (JS x100). Nothing is
invented — each cell traces to a graded snap.
"""
import json, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
PBP  = ROOT / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
OUT  = ROOT / "data" / "scenarios" / "nfl_scenarios.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-08-22"   # Date.now() unavailable in some runtimes; stamp explicitly

def load():
    df = pd.read_parquet(PBP)
    df["qb_name"] = df["passer_player_name"]
    scr = (df["qb_scramble"] == 1) & df["qb_name"].isna()
    df.loc[scr, "qb_name"] = df.loc[scr, "rusher_player_name"]
    df["moved"] = ((df["first_down"] == 1) | (df["touchdown"] == 1)).astype(int)
    for c in ("third_down_converted","fourth_down_converted","qb_hit"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def r(x, n=3):
    return None if x is None or (isinstance(x,float) and (np.isnan(x))) else round(float(x), n)

# ---------------- scenario masks
def scen_mask(df, spec):
    m = pd.Series(True, index=df.index)
    if spec.get("down") is not None: m &= df["down"] == spec["down"]
    d = spec.get("dist")
    if d == "1-3":  m &= (df["ydstogo"]>=1)&(df["ydstogo"]<=3)
    if d == "4-6":  m &= (df["ydstogo"]>=4)&(df["ydstogo"]<=6)
    if d == "7+":   m &= df["ydstogo"]>=7
    if d == "10+":  m &= df["ydstogo"]>=10
    if spec.get("zone"):   m &= df["yardline_100"] <= spec["zone"]
    if spec.get("deep"):   m &= df["air_yards"] >= 20
    if spec.get("twomin"): m &= df["half_seconds_remaining"] <= 120
    return df[m]

QB_SCEN = [("3rd-10plus","3rd & 10+",dict(down=3,dist="10+")),
           ("3rd-long","3rd & long (7+)",dict(down=3,dist="7+")),
           ("3rd-short","3rd & short (1-3)",dict(down=3,dist="1-3")),
           ("redzone","Red zone (<=20)",dict(zone=20)),
           ("deep","Deep shots (air 20+)",dict(deep=True)),
           ("twomin","Two-minute drill",dict(twomin=True)),
           ("any","All dropbacks",dict())]
RB_SCEN = [("any","All carries",dict()),
           ("3rd-short","3rd & short (1-3)",dict(down=3,dist="1-3")),
           ("redzone","Red zone (<=20)",dict(zone=20)),
           ("goalline","Goal-to-go (<=5)",dict(zone=5))]
WR_SCEN = [("any","All targets",dict()),
           ("deep","Deep targets (air 20+)",dict(deep=True)),
           ("3rd-long","3rd & long (7+)",dict(down=3,dist="7+")),
           ("redzone","Red zone (<=20)",dict(zone=20))]

# ---------------- player boards
def qb_board(df, spec, minp):
    p = scen_mask(df, spec); p = p[(p["qb_dropback"]==1) & p["qb_name"].notna()].copy()
    if p.empty: return {"columns":[],"rows":[]}
    p["conv"] = p["third_down_converted"] if spec.get("down")==3 else (
                p["fourth_down_converted"] if spec.get("down")==4 else p["moved"])
    att = p[p["pass_attempt"]==1]
    g = p.groupby("qb_name").agg(n=("conv","size"),conv=("conv","mean"),epa=("epa","mean"),
        succ=("success","mean"),sack=("sack","mean"),intr=("interception","mean")).join(
        att.groupby("qb_name").agg(comp=("complete_pass","mean"),cpoe=("cpoe","mean"),adot=("air_yards","mean")))
    g = g[g["n"]>=minp].sort_values("conv",ascending=False).head(24).reset_index()
    cols = [{"label":"QB","fmt":"text"},{"label":"Plays","fmt":"int"},{"label":"Conv%","fmt":"pct"},
            {"label":"EPA/db","fmt":"p2"},{"label":"Succ%","fmt":"pct"},{"label":"Comp%","fmt":"pct"},
            {"label":"CPOE","fmt":"p1"},{"label":"Sack%","fmt":"pct"},{"label":"INT%","fmt":"pct"},{"label":"aDOT","fmt":"f1"}]
    rows = [[x["qb_name"],int(x["n"]),r(x["conv"]),r(x["epa"]),r(x["succ"]),r(x["comp"]),
             r(x["cpoe"],1),r(x["sack"]),r(x["intr"]),r(x["adot"],1)] for _,x in g.iterrows()]
    return {"columns":cols,"rows":rows}

def rb_board(df, spec, minp):
    p = scen_mask(df, spec); p = p[(p["rush_attempt"]==1) & p["rusher_player_name"].notna()].copy()
    if p.empty: return {"columns":[],"rows":[]}
    p["stuff"]=(p["yards_gained"]<=0).astype(int); p["expl"]=(p["yards_gained"]>=10).astype(int)
    g = p.groupby("rusher_player_name").agg(n=("yards_gained","size"),ypc=("yards_gained","mean"),
        succ=("success","mean"),epa=("epa","mean"),move=("moved","mean"),stuff=("stuff","mean"),
        expl=("expl","mean"),td=("rush_touchdown","mean"))
    g = g[g["n"]>=minp].sort_values("epa",ascending=False).head(24).reset_index()
    cols=[{"label":"RB","fmt":"text"},{"label":"Car","fmt":"int"},{"label":"Yds/C","fmt":"f1"},
          {"label":"Succ%","fmt":"pct"},{"label":"EPA","fmt":"p2"},{"label":"Move%","fmt":"pct"},
          {"label":"Stuff%","fmt":"pct"},{"label":"10+%","fmt":"pct"},{"label":"TD%","fmt":"pct"}]
    rows=[[x["rusher_player_name"],int(x["n"]),r(x["ypc"],1),r(x["succ"]),r(x["epa"]),r(x["move"]),
           r(x["stuff"]),r(x["expl"]),r(x["td"])] for _,x in g.iterrows()]
    return {"columns":cols,"rows":rows}

def wr_board(df, spec, minp):
    p = scen_mask(df, spec); p = p[(p["pass_attempt"]==1) & p["receiver_player_name"].notna()].copy()
    if p.empty: return {"columns":[],"rows":[]}
    p["deept"]=(p["air_yards"]>=20).astype(int); comp=p[p["complete_pass"]==1]
    g = p.groupby("receiver_player_name").agg(n=("epa","size"),catch=("complete_pass","mean"),
        ypt=("yards_gained","mean"),epa=("epa","mean"),move=("moved","mean"),adot=("air_yards","mean"),
        deep=("deept","mean"),td=("pass_touchdown","mean")).join(
        comp.groupby("receiver_player_name").agg(yac=("yards_after_catch","mean")))
    g = g[g["n"]>=minp].sort_values("epa",ascending=False).head(24).reset_index()
    cols=[{"label":"Receiver","fmt":"text"},{"label":"Tgt","fmt":"int"},{"label":"Catch%","fmt":"pct"},
          {"label":"Yds/T","fmt":"f1"},{"label":"YAC","fmt":"f1"},{"label":"aDOT","fmt":"f1"},
          {"label":"EPA","fmt":"p2"},{"label":"Move%","fmt":"pct"},{"label":"Deep%","fmt":"pct"},{"label":"TD%","fmt":"pct"}]
    rows=[[x["receiver_player_name"],int(x["n"]),r(x["catch"]),r(x["ypt"],1),r(x["yac"],1),r(x["adot"],1),
           r(x["epa"]),r(x["move"]),r(x["deep"]),r(x["td"])] for _,x in g.iterrows()]
    return {"columns":cols,"rows":rows}

# ---------------- team leaderboards
def _drive_stats(d):
    d = d.copy(); d["off_play"]=((d["pass"]==1)|(d["rush"]==1)).astype(int)
    dr = d[d["fixed_drive"].notna()].groupby(["game_id","fixed_drive"]).agg(
        res=("fixed_drive_result","first"),plays=("off_play","sum")).reset_index()
    if dr.empty: return None
    return dict(drives=len(dr), td=dr["res"].eq("Touchdown").mean(),
        score=dr["res"].isin(["Touchdown","Field goal"]).mean(),
        give=dr["res"].isin(["Turnover","Opp touchdown"]).mean(),
        threeout=((dr["plays"]<=3)&dr["res"].eq("Punt")).mean(), ppd=dr["plays"].mean())

def team_third(df, minp=40):
    d3 = df[(df["down"]==3)&df["posteam"].notna()].copy(); d3["conv"]=d3["third_down_converted"]
    d3["b"]=np.select([d3["ydstogo"]<=3,d3["ydstogo"]<=6,d3["ydstogo"]<=9],["s","m","l"],default="x")
    piv=d3.pivot_table(index="posteam",columns="b",values="conv",aggfunc="mean")
    cnt=d3.groupby("posteam").size(); allc=d3.groupby("posteam")["conv"].mean()
    teams=[t for t in piv.index if cnt.get(t,0)>=minp]
    cols=[{"label":"Team","fmt":"text"},{"label":"Short 1-3","fmt":"pct"},{"label":"Med 4-6","fmt":"pct"},
          {"label":"Long 7-9","fmt":"pct"},{"label":"10+","fmt":"pct"},{"label":"Overall","fmt":"pct"}]
    rows=sorted([[t,r(piv.loc[t].get("s")),r(piv.loc[t].get("m")),r(piv.loc[t].get("l")),
          r(piv.loc[t].get("x")),r(allc.get(t))] for t in teams], key=lambda z:-(z[5] or 0))
    return {"columns":cols,"rows":rows}

def team_redzone(df, side):
    col = "posteam" if side=="off" else "defteam"
    rz=df[(df["yardline_100"]<=20)&df["posteam"].notna()&df["fixed_drive"].notna()]
    t=rz.groupby(["game_id","fixed_drive","posteam","defteam"]).agg(td=("pass_touchdown","max"),rtd=("rush_touchdown","max")).reset_index()
    t["td"]=((t["td"]==1)|(t["rtd"]==1)).astype(int)
    g=t.groupby(col).agg(trips=("td","size"),td=("td","mean")).reset_index()
    g=g[g["trips"]>=20].sort_values("td",ascending=(side=="def"))
    lab = "RZ TD%" if side=="off" else "RZ TD% Allowed"
    cols=[{"label":"Team","fmt":"text"},{"label":lab,"fmt":"pct"},{"label":"Trips","fmt":"int"}]
    return {"columns":cols,"rows":[[x[col],r(x["td"]),int(x["trips"])] for _,x in g.iterrows()]}

def team_drive(df, side):
    col="posteam" if side=="off" else "defteam"
    rows=[]
    for t in sorted(df[col].dropna().unique()):
        s=_drive_stats(df[df[col]==t])
        if s and s["drives"]>=40: rows.append([t,int(s["drives"]),r(s["td"]),r(s["score"]),r(s["give"]),r(s["threeout"]),r(s["ppd"],1)])
    rows.sort(key=lambda z:-(z[2] or 0))
    suf=" Allowed" if side=="def" else ""
    cols=[{"label":"Team","fmt":"text"},{"label":"Drives","fmt":"int"},{"label":"TD%"+suf,"fmt":"pct"},
          {"label":"Score%"+suf,"fmt":"pct"},{"label":"Giveaway%","fmt":"pct"},{"label":"3-out%","fmt":"pct"},{"label":"Plays/Dr","fmt":"f1"}]
    return {"columns":cols,"rows":rows}

def team_explosive(df):
    scr=df[df["down"].notna()&df["posteam"].notna()]
    p=scr[scr["pass_attempt"]==1]; ru=scr[scr["rush_attempt"]==1]
    xp=p.assign(x=(p["yards_gained"]>=20).astype(int)).groupby("posteam")["x"].mean()
    xr=ru.assign(x=(ru["yards_gained"]>=10).astype(int)).groupby("posteam")["x"].mean()
    pa=p.assign(x=(p["yards_gained"]>=20).astype(int)).groupby("defteam")["x"].mean()
    n=scr.groupby("posteam").size()
    teams=[t for t in xp.index if n.get(t,0)>=300]
    cols=[{"label":"Team","fmt":"text"},{"label":"Pass 20+","fmt":"pct"},{"label":"Rush 10+","fmt":"pct"},{"label":"Pass 20+ Allowed","fmt":"pct"}]
    rows=sorted([[t,r(xp.get(t)),r(xr.get(t)),r(pa.get(t))] for t in teams],key=lambda z:-(z[1] or 0))
    return {"columns":cols,"rows":rows}

def team_pressure(df, side):
    db=df[df["qb_dropback"]==1]; col="posteam" if side=="off" else "defteam"
    g=db.groupby(col).agg(n=("sack","size"),sack=("sack","mean"),hit=("qb_hit","mean"))
    g=g[g["n"]>=200].sort_values("sack",ascending=(side=="off")).reset_index()
    lab="allowed" if side=="off" else "generated"
    cols=[{"label":"Team","fmt":"text"},{"label":f"Sack% ({lab})","fmt":"pct"},{"label":f"QB-hit% ({lab})","fmt":"pct"}]
    return {"columns":cols,"rows":[[x[col],r(x["sack"]),r(x["hit"])] for _,x in g.iterrows()]}

def team_early(df):
    e=df[df["down"].isin([1,2])&df["posteam"].notna()]
    g=e.groupby("posteam").agg(n=("pass","size"),pr=("pass","mean"),epa=("epa","mean"))
    g=g[g["n"]>=300].sort_values("pr",ascending=False).reset_index()
    cols=[{"label":"Team","fmt":"text"},{"label":"Pass%","fmt":"pct"},{"label":"EPA/play","fmt":"p3"},{"label":"Plays","fmt":"int"}]
    return {"columns":cols,"rows":[[x["posteam"],r(x["pr"]),r(x["epa"]),int(x["n"])] for _,x in g.iterrows()]}

# ---------------- team profile card
def team_profile(df, team, side):
    off = side=="off"; oc = "posteam" if off else "defteam"
    d = df[df[oc]==team]; scr = d[d["down"].notna()]
    if scr.empty: return None
    d3=scr[scr["down"]==3]; d3l=d3[d3["ydstogo"]>=7]
    p=scr[scr["pass_attempt"]==1]; ru=scr[scr["rush_attempt"]==1]
    early=scr[scr["down"].isin([1,2])]; db=scr[scr["qb_dropback"]==1]
    rz=df[(df["yardline_100"]<=20)&(df[oc]==team)&df["fixed_drive"].notna()]
    rzt=rz.groupby(["game_id","fixed_drive"]).agg(td=("pass_touchdown","max"),rtd=("rush_touchdown","max")).reset_index()
    rztd=((rzt["td"]==1)|(rzt["rtd"]==1)).mean() if len(rzt) else None
    dr=_drive_stats(d)
    def pc(x): return None if x is None or (isinstance(x,float) and np.isnan(x)) else round(float(x)*100,1)
    stats=[["EPA / play", r(scr["epa"].mean()), "p3"],
           ["Success rate", pc(scr["success"].mean()), "pctv"],
           ["3rd-down conv%", pc(d3["third_down_converted"].mean()), "pctv"],
           ["3rd & long (7+)", pc(d3l["third_down_converted"].mean()) if len(d3l) else None, "pctv"],
           ["Red-zone TD%/trip", pc(rztd), "pctv"],
           ["Explosive pass 20+", pc((p["yards_gained"]>=20).mean()) if len(p) else None, "pctv"],
           ["Explosive rush 10+", pc((ru["yards_gained"]>=10).mean()) if len(ru) else None, "pctv"],
           ["Early-down pass%", pc(early["pass"].mean()) if len(early) else None, "pctv"],
           ["Sack% "+("allowed" if off else "generated"), pc(db["sack"].mean()) if len(db) else None, "pctv"],
           ["QB-hit% "+("allowed" if off else "generated"), pc(db["qb_hit"].mean()) if len(db) else None, "pctv"]]
    if dr:
        stats += [["Drives", dr["drives"], "int"],
                  ["TD / drive", pc(dr["td"]), "pctv"],
                  ["Score / drive", pc(dr["score"]), "pctv"],
                  ["Giveaway / drive", pc(dr["give"]), "pctv"],
                  ["3-and-out%", pc(dr["threeout"]), "pctv"],
                  ["Plays / drive", r(dr["ppd"],1), "f1"]]
    return stats

# ---------------- assemble
def build_scope(df):
    mins = {"qb":18,"rb":15,"wr":15} if len(df["season"].unique())<=1 else {"qb":50,"rb":45,"wr":45}
    players = {"qb":{"scenarios":[{"key":k,"label":l} for k,l,_ in QB_SCEN],
                     "boards":{k:qb_board(df,s,mins["qb"] if k!="deep" else max(8,mins["qb"]//3)) for k,l,s in QB_SCEN}},
               "rb":{"scenarios":[{"key":k,"label":l} for k,l,_ in RB_SCEN],
                     "boards":{k:rb_board(df,s,mins["rb"] if k in("any","redzone") else max(8,mins["rb"]//3)) for k,l,s in RB_SCEN}},
               "wr":{"scenarios":[{"key":k,"label":l} for k,l,_ in WR_SCEN],
                     "boards":{k:wr_board(df,s,mins["wr"] if k in("any","redzone") else max(8,mins["wr"]//3)) for k,l,s in WR_SCEN}}}
    cats=[("third","3rd Down by Distance",lambda:team_third(df)),
          ("redzone_off","Red Zone — Offense",lambda:team_redzone(df,"off")),
          ("redzone_def","Red Zone — Defense",lambda:team_redzone(df,"def")),
          ("drive_off","Per Drive — Offense",lambda:team_drive(df,"off")),
          ("drive_def","Per Drive — Defense",lambda:team_drive(df,"def")),
          ("explosive","Explosive Plays",lambda:team_explosive(df)),
          ("pressure_off","Pass Protection",lambda:team_pressure(df,"off")),
          ("pressure_def","Pass Rush",lambda:team_pressure(df,"def")),
          ("early","Early-Down Tendency",lambda:team_early(df))]
    teamRankings={"categories":[{"key":k,"label":l} for k,l,_ in cats],
                  "boards":{k:fn() for k,l,fn in cats}}
    teams=sorted(set(df["posteam"].dropna().unique()) | set(df["defteam"].dropna().unique()))
    teams=[t for t in teams if isinstance(t,str) and len(t)<=3]
    profiles={t:{"off":team_profile(df,t,"off"),"def":team_profile(df,t,"def")} for t in teams}
    profiles={t:v for t,v in profiles.items() if v["off"]}
    return {"players":players,"teamRankings":teamRankings,"teamProfiles":profiles}

def main():
    df = load()
    scopes = {"2025": df[df["season"]==2025], "2024": df[df["season"]==2024], "career": df}
    out = {"meta":{"seasons":"2019-2025","plays":int(len(df)),"generated":GEN_DATE,
                   "scopeOrder":[["2025","2025 Season"],["2024","2024 Season"],["career","Career (2019-2025)"]]},
           "scopes":{k:build_scope(v) for k,v in scopes.items()}}
    OUT.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
    print(f"WROTE {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    for k in scopes: print(f"  scope {k}: {len(out['scopes'][k]['teamProfiles'])} team profiles")

if __name__ == "__main__":
    main()
