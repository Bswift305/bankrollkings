# -*- coding: utf-8 -*-
"""
Precompute two CFB boards from the CFBD 2026 ratings snapshot:
  data/scenarios/cfb_power.json   — Power Rankings (SP+ / FPI), "who's for real"
  data/scenarios/cfb_talent.json  — Talent vs Performance (recruiting composite
                                     rank vs SP+ rank -> over/underachievers)

    python research/cfb_favorites/build_cfb_ratings_export.py
"""
import csv, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
SC = ROOT / "data" / "scenarios"
GEN_DATE = "2026-09-03"

def fnum(v):
    try: return float(v)
    except: return None

def main():
    rows = list(csv.DictReader(open(H/"CFBD_Ratings_2026.csv", encoding="utf-8")))
    R = []
    for r in rows:
        R.append({"team": r["team"], "conf": r["conf"], "sp": fnum(r["sp"]),
                  "sp_off": fnum(r["sp_off"]), "sp_def": fnum(r["sp_def"]),
                  "fpi": fnum(r["fpi"]), "talent": fnum(r["talent"])})

    # ---- Power Rankings (SP+) ----
    pcols = [{"label":"Team","fmt":"text"},{"label":"Conf","fmt":"text"},{"label":"SP+","fmt":"p1"},
             {"label":"Offense","fmt":"p1"},{"label":"Defense","fmt":"p1"},{"label":"FPI","fmt":"p1"}]
    prows = [[x["team"], x["conf"], x["sp"], x["sp_off"], x["sp_def"], x["fpi"]]
             for x in R if x["sp"] is not None]
    prows.sort(key=lambda z: -(z[2] if z[2] is not None else -99))
    (SC/"cfb_power.json").write_text(json.dumps(
        {"meta":{"season":2026,"teams":len(prows),"generated":GEN_DATE,"source":"SP+ / FPI via CFBD"},
         "board":{"columns":pcols,"rows":prows}}, separators=(",",":")), encoding="utf-8")

    # ---- Talent vs Performance ----
    have = [x for x in R if x["talent"] is not None and x["sp"] is not None]
    by_talent = sorted(have, key=lambda z:-z["talent"])
    trank = {x["team"]: i+1 for i, x in enumerate(by_talent)}
    by_sp = sorted(have, key=lambda z:-z["sp"])
    srank = {x["team"]: i+1 for i, x in enumerate(by_sp)}
    tcols = [{"label":"Team","fmt":"text"},{"label":"Conf","fmt":"text"},{"label":"Talent","fmt":"f0"},
             {"label":"Talent Rk","fmt":"int"},{"label":"SP+ Rk","fmt":"int"},{"label":"Over/Under","fmt":"ps"}]
    trows = []
    for x in have:
        tr, sr = trank[x["team"]], srank[x["team"]]
        gap = tr - sr   # >0 rated higher than talent = overachiever; <0 loaded but underrated
        trows.append([x["team"], x["conf"], x["talent"], tr, sr, gap])
    trows.sort(key=lambda z:-z[5])   # biggest overachievers first
    (SC/"cfb_talent.json").write_text(json.dumps(
        {"meta":{"season":2026,"teams":len(trows),"generated":GEN_DATE},
         "board":{"columns":tcols,"rows":trows}}, separators=(",",":")), encoding="utf-8")

    print(f"WROTE cfb_power.json ({len(prows)} teams) + cfb_talent.json ({len(trows)} teams)")
    print("  power top5:", [r[0] for r in prows[:5]])
    print("  overachievers:", [(r[0],f'+{r[5]}') for r in trows[:4]])
    print("  underachievers:", [(r[0],r[5]) for r in trows[-4:]])

if __name__ == "__main__":
    main()
