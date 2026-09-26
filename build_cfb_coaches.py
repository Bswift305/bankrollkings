#!/usr/bin/env python3
"""
Map each 2026 FBS team to its current head coach (CFBD /coaches).

The coach-trend layer needs to know WHO coaches each team now, so it can attach that
coach's ATS history to this week's games. CFBD /coaches returns each coach's season log;
this keeps the 2026 school -> coach name mapping. Small, committable.

Output: data/scenarios/cfb_coaches_2026.json  { season, coaches: {school: "First Last"} }
"""
from __future__ import annotations
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_coaches_2026.json"


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    req = urllib.request.Request(f"https://api.collegefootballdata.com/coaches?year={season}",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    coaches = {}
    for c in data:
        name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
        for s in c.get("seasons", []):
            if s.get("year") == season and s.get("school"):
                coaches[s["school"]] = name
    return {"season": season,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "coaches": coaches}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(data['coaches'])} team->coach mappings -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
