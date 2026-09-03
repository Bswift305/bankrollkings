# -*- coding: utf-8 -*-
"""
Precompute the CFB Matchup Edge Card data -> data/scenarios/cfb_matchup.json.
Per FBS team, bundle everything the suite knows into one dossier: full ATS splits
(overall/home/away/fav/dog + O/U), the CURRENT (2026) head coach and his career ATS,
and 2026 returning production. The page picks two teams and renders a side-by-side
edge card. All from CFBD; every number traces to graded games.

    python research/cfb_favorites/build_cfb_matchup_export.py
"""
import csv, json, pathlib
from collections import defaultdict
import build_cfb_ats_export as A   # reuse build() + helpers

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
OUT = ROOT / "data" / "scenarios" / "cfb_matchup.json"
GEN_DATE = "2026-09-03"

def current_coaches():
    """team -> most recent HC (prefer 2026, else latest year)."""
    best = {}
    for r in csv.DictReader(open(H/"CFBD_Coaches_2016_2025.csv", encoding="utf-8")):
        try: yr = int(r["year"])
        except: continue
        sch = r["school"]
        if sch not in best or yr > best[sch][0]:
            best[sch] = (yr, r["coach"])
    return {k: v[1] for k, v in best.items()}

def returning():
    p = H/"NCAAF_CFBD_ReturningProduction_2026.csv"
    out = {}
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8")):
            try: out[r["team"]] = round(float(r["percentPPA"]), 3)
            except: pass
    return out

def split(r):
    return {"pct": A.pct(r), "rec": A.rec(r), "n": A.n(r)}

def main():
    T, C, conf = A.build()
    coaches = current_coaches()
    ret = returning()
    fbs = [t for t in T if conf.get(t) in A.FBS and A.n(T[t]["ats"]) >= 40]
    teams = {}
    for t in fbs:
        r = T[t]
        hc = coaches.get(t)
        cats = C.get(hc) if hc else None
        teams[t] = {
            "conf": conf.get(t) or "",
            "coach": hc or "—",
            "coach_ats": A.pct(cats["ats"]) if cats else None,
            "coach_rec": A.rec(cats["ats"]) if cats else "",
            "ret": ret.get(t),
            "ats": {
                "overall": split(r["ats"]), "home": split(r["home"]), "away": split(r["away"]),
                "fav": split(r["fav"]), "dog": split(r["dog"]),
                "over": {"pct": A.pct(r["ou"]), "rec": A.rec(r["ou"])},  # ou counter: w=over, l=under
            },
        }
    out = {"meta": {"seasons": "2016-2025", "teams": len(teams), "generated": GEN_DATE},
           "teams": teams, "teamList": sorted(teams)}
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)  {len(teams)} teams")
    g = teams.get("Georgia", {})
    print("  Georgia:", g.get("coach"), "| coach ATS", g.get("coach_ats"), "| ret", g.get("ret"),
          "| home", g.get("ats",{}).get("home"))

if __name__ == "__main__":
    main()
