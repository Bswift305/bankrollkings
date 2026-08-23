# -*- coding: utf-8 -*-
"""
Precompute the NRFI / First-Inning site data -> data/scenarios/mlb_nrfi.json.

NRFI = "No Run First Inning". From the enriched pitch parquet (post-play scores),
compute first-inning run outcomes per game and attribute them:
  - Starting pitchers: how often they keep the 1st inning scoreless (NRFI%).
  - Team offense: how often they put a run on the board in the 1st (score-first%).
  - Team pitching staff: how often they hold the 1st scoreless.
Honest CONTEXT, not a claimed edge (we have no historical NRFI lines to prove ROI).
Every number traces to a real first inning.

    python research/mlb_statcast/build_nrfi_export.py
"""
import json, pathlib, glob, warnings
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
import mlb_situational as E   # reuse _titlecase / name handling

ROOT = pathlib.Path(__file__).resolve().parents[2]
PBP_GLOB = str(ROOT / "data" / "pbp" / "MLB_statcast_pbp_*.parquet")
OUT  = ROOT / "data" / "scenarios" / "mlb_nrfi.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-08-23"

def load():
    df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(PBP_GLOB))], ignore_index=True)
    df["pit_name"] = df["player_name"].apply(
        lambda s: E._titlecase(f"{str(s).split(',')[1]} {str(s).split(',')[0]}") if isinstance(s,str) and "," in s else str(s))
    return df

def half_innings(df):
    """One row per (game, half of the 1st inning): runs the batting team scored,
    and the starter who allowed them."""
    i1 = df[df["inning"] == 1].copy()
    i1["is_top"] = i1["inning_topbot"].astype(str).str.startswith("Top")
    i1["bat_team"] = np.where(i1["is_top"], i1["away_team"], i1["home_team"])
    i1["fld_team"] = np.where(i1["is_top"], i1["home_team"], i1["away_team"])
    i1["post_bat_score"] = pd.to_numeric(i1["post_bat_score"], errors="coerce")
    # starter of the half = pitcher of the earliest at-bat in that half
    i1 = i1.sort_values(["game_pk","is_top","at_bat_number","pitch_number"])
    rows = []
    for (gpk, top), g in i1.groupby(["game_pk","is_top"]):
        starter = g["pitcher"].iloc[0]
        rows.append({"game_pk": gpk, "bat_team": g["bat_team"].iloc[0], "fld_team": g["fld_team"].iloc[0],
                     "runs": float(g["post_bat_score"].max()), "starter": starter,
                     "starter_name": g.loc[g["pitcher"]==starter, "pit_name"].iloc[0]})
    return pd.DataFrame(rows)

def board(cols, rows):
    return {"columns": cols, "rows": rows}

def _pct(x, n=3): return None if pd.isna(x) else round(float(x), n)

def build():
    df = load(); h = half_innings(df)
    # ---- starting pitchers: NRFI rate ----
    pit = h.groupby(["starter","starter_name"]).agg(n=("runs","size"),
        nrfi=("runs", lambda s: (s == 0).mean()), rpg=("runs","mean")).reset_index()
    pit = pit[pit["n"] >= 20].sort_values("nrfi", ascending=False).head(30)
    pit_cols = [{"label":"Pitcher","fmt":"text"},{"label":"1st Inn","fmt":"int"},
                {"label":"NRFI%","fmt":"pct"},{"label":"Runs/1st","fmt":"f2"}]
    pit_rows = [[r["starter_name"], int(r["n"]), _pct(r["nrfi"]), round(float(r["rpg"]),2)] for _,r in pit.iterrows()]
    # ---- team offense: score-in-1st rate ----
    off = h.groupby("bat_team").agg(n=("runs","size"), score=("runs", lambda s:(s>0).mean()),
        rpg=("runs","mean")).reset_index().sort_values("score", ascending=False)
    off_cols = [{"label":"Team","fmt":"text"},{"label":"Games","fmt":"int"},
                {"label":"Score 1st%","fmt":"pct"},{"label":"Runs/1st","fmt":"f2"}]
    off_rows = [[r["bat_team"], int(r["n"]), _pct(r["score"]), round(float(r["rpg"]),2)] for _,r in off.iterrows()]
    # ---- team pitching: hold-1st-scoreless rate ----
    dff = h.groupby("fld_team").agg(n=("runs","size"), nrfi=("runs", lambda s:(s==0).mean()),
        rpg=("runs","mean")).reset_index().sort_values("nrfi", ascending=False)
    dff_cols = [{"label":"Team","fmt":"text"},{"label":"Games","fmt":"int"},
                {"label":"Hold 1st%","fmt":"pct"},{"label":"Runs allowed/1st","fmt":"f2"}]
    dff_rows = [[r["fld_team"], int(r["n"]), _pct(r["nrfi"]), round(float(r["rpg"]),2)] for _,r in dff.iterrows()]
    # ---- overall game NRFI rate (neither team scores in the 1st) ----
    game = h.groupby("game_pk")["runs"].sum()
    nrfi_game_rate = float((game == 0).mean())
    seasons = sorted(int(s) for s in df["season"].dropna().unique())
    span = f"{seasons[0]}-{seasons[-1]}" if len(seasons)>1 else str(seasons[0])
    out = {"meta":{"season":span, "games":int(len(game)), "nrfi_rate":round(nrfi_game_rate,3),
                   "generated":GEN_DATE},
           "boards":{"pitchers":board(pit_cols,pit_rows),
                     "offense":board(off_cols,off_rows),
                     "defense":board(dff_cols,dff_rows)}}
    OUT.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
    print(f"WROTE {OUT}  ({OUT.stat().st_size/1024:.0f} KB)  {span}  games={len(game):,}  "
          f"league NRFI={nrfi_game_rate:.1%}")
    print("top NRFI starters:", [(r[0],f'{r[2]*100:.0f}%') for r in pit_rows[:5]])
    print("score-1st offenses:", [(r[0],f'{r[2]*100:.0f}%') for r in off_rows[:5]])

if __name__ == "__main__":
    build()
