# -*- coding: utf-8 -*-
"""Precompute all-weeks big-favorite ATS records -> cfb_bigfav_records.json.

Per THRESHOLD (20 / 30 / 40 point favorite), the cover% + W-L record + avg margin
vs the line for every FBS TEAM and every COACH (career, across schools), 2016-2025.
This feeds the live "Today's Big Favorites" board (/tools/cfb-big-favorites), which
joins it to the current slate. Committed so prod (no raw CFBD CSVs) can serve it.

    python research/cfb_favorites/build_cfb_bigfav_records.py
"""
import json, pathlib, sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cfb_favorite_trends as T  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "data" / "scenarios" / "cfb_bigfav_records.json"
GEN = "2026-09-05"
THRESHOLDS = (20, 30, 40)
ALL_WEEKS = set(range(0, 17))


def _agg(rows):
    teams = defaultdict(lambda: [0, 0, 0.0, 0])   # w, l, sum(margin-line), n
    coaches = defaultdict(lambda: [0, 0, 0.0, 0])
    for r in rows:
        for key, d in ((r.get("fav"), teams), (r.get("coach"), coaches)):
            if not key:
                continue
            e = d[key]
            if r["result"] == 1:
                e[0] += 1
            elif r["result"] == -1:
                e[1] += 1
            e[2] += (r["margin"] - r["line"])
            e[3] += 1

    def fmt(d):
        out = {}
        for k, (w, l, vs, n) in d.items():
            dec = w + l
            out[k] = [round(w / dec, 3) if dec else None,
                      f"{w}-{l}",
                      round(vs / n, 1) if n else None]
        return out
    return fmt(teams), fmt(coaches)


def main():
    payload = {"meta": {"seasons": "2016-2025", "generated": GEN,
                        "thresholds": list(THRESHOLDS)}, "thresholds": {}}
    for thr in THRESHOLDS:
        rows = T.build(thr, ALL_WEEKS)
        teams, coaches = _agg(rows)
        payload["thresholds"][str(thr)] = {"teams": teams, "coaches": coaches}
        print(f"  {thr}+: {len(rows)} games -> {len(teams)} teams, {len(coaches)} coaches")
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {OUT} ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
