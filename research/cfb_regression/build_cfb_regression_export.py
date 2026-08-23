# -*- coding: utf-8 -*-
"""
Precompute the CFB Regression Watch site data -> data/scenarios/cfb_regression.json.

Fixed export: the 2025 regression base is history; 2026 returning production is a
snapshot (rerun when CFBD finalizes rosters). The page reads this one JSON — no
pandas at request time. Generic tables {columns:[{label,fmt}], rows:[[...]]};
percent values stored as fractions (JS x100). Every cell traces to real data.

    python research/cfb_regression/build_cfb_regression_export.py
"""
import json, pathlib
import pandas as pd, numpy as np
import cfb_regression_watch as W   # same folder

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT  = ROOT / "data" / "scenarios" / "cfb_regression.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-08-23"

def _r(x, n=2):
    return None if x is None or (isinstance(x,float) and np.isnan(x)) else round(float(x), n)

REG_COLS = [{"label":"Team","fmt":"text"},{"label":"Conf","fmt":"text"},{"label":"2025 Rec","fmt":"text"},
            {"label":"Win%","fmt":"pct"},{"label":"YPP Margin","fmt":"p2"},{"label":"TO Margin","fmt":"p2"},
            {"label":"1-Score","fmt":"text"},{"label":"Ret%","fmt":"pct"},{"label":"Luck","fmt":"p2"}]

def reg_rows(d):
    rows = []
    for _, r in d.iterrows():
        osc = f"{int(r['osc_w'])}-{int(r['osc_l'])}" if r["osc_gp"]>0 else "-"
        rows.append([r["team"], (r["conf"] or ""), f"{int(r['w'])}-{int(r['l'])}",
                     _r(r["win_pct"],3), _r(r["ypp_margin"]), _r(r["to_margin"]), osc,
                     (_r(r["ret"],3) if pd.notna(r["ret"]) else None), _r(r["luck"])])
    return rows

def experience_board(df):
    # Overall returning production only. CFBD's per-unit percentages (passing/rushing PPA)
    # can legitimately exceed 100% or go negative, which reads as a bug to a casual user;
    # the overall percentPPA is the clean, standard 0-100% experience metric.
    ret = pd.read_csv(W.RET)
    ret["k"] = ret["team"].map(W.norm)
    m = df[["k","team","conf","w","l"]].merge(ret[["k","percentPPA"]], on="k", how="left").dropna(subset=["percentPPA"])
    m = m.sort_values("percentPPA", ascending=False)
    cols = [{"label":"Team","fmt":"text"},{"label":"Conf","fmt":"text"},
            {"label":"2025 Rec","fmt":"text"},{"label":"Returning%","fmt":"pct"}]
    rows = [[r["team"], (r["conf"] or ""), f"{int(r['w'])}-{int(r['l'])}", _r(r["percentPPA"],3)] for _, r in m.iterrows()]
    return {"columns":cols, "rows":rows}

def main():
    df = W.build()
    down = df.sort_values("luck", ascending=False).head(20)
    up   = df.sort_values("luck", ascending=True).head(20)
    out = {"meta":{"base_season":2025, "returning_season":2026, "teams":int(len(df)), "generated":GEN_DATE},
           "boards":{
               "regression_down":{"columns":REG_COLS, "rows":reg_rows(down)},
               "bounceback_up":{"columns":REG_COLS, "rows":reg_rows(up)},
               "experience":experience_board(df),
           }}
    OUT.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
    print(f"WROTE {OUT}  ({OUT.stat().st_size/1024:.0f} KB)  {len(df)} FBS teams")

if __name__ == "__main__":
    main()
