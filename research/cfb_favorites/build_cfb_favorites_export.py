# -*- coding: utf-8 -*-
"""
Precompute the CFB Big-Favorite Trends site data -> data/scenarios/cfb_favorites.json.
Fixed historical export (2016-2025). Team + coach cover rates as early-season 30+ and
40+ favorites, with an "avg vs line" (how far they beat/miss the number on average).
Generic tables {columns:[{label,fmt}], rows:[[...]]}; pct stored as fraction (JS x100).

    python research/cfb_favorites/build_cfb_favorites_export.py
"""
import json, pathlib, statistics
from collections import defaultdict
import cfb_favorite_trends as T

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "scenarios" / "cfb_favorites.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
GEN_DATE = "2026-09-03"
WEEKS = {1, 2, 3, 4}

COLS = [{"label": "Team", "fmt": "text"}, {"label": "Games", "fmt": "int"},
        {"label": "Cover%", "fmt": "pct"}, {"label": "Record", "fmt": "text"},
        {"label": "Avg vs Line", "fmt": "p1"}]

def board(rows, key, ming, label):
    agg = defaultdict(list)
    for r in rows:
        if r[key] and r[key] != "?": agg[r[key]].append(r)
    out = []
    for name, rs in agg.items():
        c = sum(1 for x in rs if x["result"] == 1)
        n = sum(1 for x in rs if x["result"] == -1)
        if c + n < ming: continue
        avg = statistics.mean(x["margin"] - x["line"] for x in rs)
        out.append([name, c + n, round(c / (c + n), 3), f"{c}-{n}", round(avg, 1)])
    out.sort(key=lambda z: (-z[2], -z[1]))          # cover% desc, then sample size
    cols = [dict(COLS[0], label=label)] + COLS[1:]
    return {"columns": cols, "rows": out}

def overall(rows):
    c = sum(1 for r in rows if r["result"] == 1); n = sum(1 for r in rows if r["result"] == -1)
    return {"games": c + n, "cover": round(c / (c + n), 3) if (c + n) else None}

def main():
    bands = {}
    meta_bands = {}
    for line, ming_team, ming_coach in [(30, 8, 8), (40, 5, 5)]:
        rows = T.build(line, WEEKS)
        bands[str(line)] = {
            "teams": board(rows, "fav", ming_team, "Team"),
            "coaches": board(rows, "coach", ming_coach, "Head Coach"),
        }
        meta_bands[str(line)] = overall(rows)
    out = {
        "meta": {"seasons": "2016-2025", "weeks": "1-4", "generated": GEN_DATE,
                 "band30": meta_bands["30"], "band40": meta_bands["40"]},
        "bands": bands,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    for b in ("30", "40"):
        print(f"  {b}+: {len(bands[b]['teams']['rows'])} teams, {len(bands[b]['coaches']['rows'])} coaches; "
              f"overall {meta_bands[b]['games']} games {meta_bands[b]['cover']*100:.0f}% cover")

if __name__ == "__main__":
    main()
