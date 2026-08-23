# -*- coding: utf-8 -*-
"""
Precompute the MLB Situational Lab site data -> data/scenarios/mlb_situational.json.

The page reads this ONE static JSON (no pandas/parquet at request time, memory-safe
on prod). Rebuild when a new season's pitch parquet is added:
    python research/mlb_statcast/build_mlb_situational_export.py

Generic tables {columns:[{label,fmt}], rows:[[...]]}; percent values stored as
fractions (JS x100). Every cell traces to a real plate appearance.
"""
import json, pathlib
import pandas as pd, numpy as np
import mlb_situational as E   # same folder

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT  = ROOT / "data" / "scenarios" / "mlb_situational.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-08-22"

# min PA per scenario, sized for a 3-season (2023-2025) aggregate so the platoon/
# RISP splits rest on real volume and a small-sample fluke can't top a board.
H_MIN = {"overall":600,"vs_rhp":450,"vs_lhp":180,"risp":150,"bases_empty":400}
P_MIN = {"overall":400,"vs_rhb":300,"vs_lhb":180,"tto1":250,"tto3":150,"first_inning":120}

COLS = [{"label":"Player","fmt":"text"},{"label":"PA","fmt":"int"},{"label":"wOBA","fmt":"f3"},
        {"label":"K%","fmt":"pct"},{"label":"BB%","fmt":"pct"},{"label":"Hard-Hit%","fmt":"pct"},{"label":"HR","fmt":"int"}]

def _r(x, n=3):
    return None if x is None or (isinstance(x,float) and np.isnan(x)) else round(float(x), n)

def build_boards(pa, df, role):
    scens = E.H_SCEN if role=="hitters" else E.P_SCEN
    mins  = H_MIN if role=="hitters" else P_MIN
    idcol = "batter" if role=="hitters" else "pitcher"
    # resolve names once for all qualifying ids across scenarios
    qualifying = set()
    prepped = {}
    for key,(label,fn) in scens.items():
        sub = fn(pa); rows = []
        for pid,g in sub.groupby(idcol):
            a = E._agg(g)
            if a["n"] >= mins[key]:
                rows.append((pid,a)); qualifying.add(int(pid))
        prepped[key] = (label, rows)
    if role=="hitters":
        names = E.batter_names(list(qualifying)); namef = lambda pid: names.get(int(pid), str(pid))
    else:
        pmap = df.groupby("pitcher")["pit_name"].first().to_dict(); namef = lambda pid: pmap.get(pid, str(pid))
    boards, scen_meta = {}, []
    for key,(label,rows) in prepped.items():
        b = pd.DataFrame([{"Player":namef(pid), **a} for pid,a in rows])
        out_rows = []
        if not b.empty:
            b = b.sort_values("woba", ascending=(role=="pitchers")).head(30)
            out_rows = [[r["Player"], int(r["n"]), _r(r["woba"]), _r(r["k"]), _r(r["bb"]), _r(r["hard"]), int(r["hr"])]
                        for _,r in b.iterrows()]
        boards[key] = {"columns":COLS, "rows":out_rows}
        scen_meta.append({"key":key,"label":label})
    return {"scenarios":scen_meta, "boards":boards}

def main():
    df = E.load(); pa = E.pa_table(df)
    seasons = sorted(int(s) for s in df["season"].dropna().unique()) if "season" in df.columns else [2025]
    span = f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])
    out = {"meta":{"season":span, "seasons":seasons, "pitches":int(len(df)), "pa":int(len(pa)), "generated":GEN_DATE},
           "hitters":build_boards(pa, df, "hitters"),
           "pitchers":build_boards(pa, df, "pitchers")}
    OUT.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
    print(f"WROTE {OUT}  ({OUT.stat().st_size/1024:.0f} KB)  span={span} PA={len(pa):,}")

if __name__ == "__main__":
    main()
