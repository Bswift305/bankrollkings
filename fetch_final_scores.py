#!/usr/bin/env python3
"""
Same-day final scores for NFL + CFB from ESPN's public scoreboard.

nflverse/CFBD box scores lag ~a day, so grading a just-finished game meant fetching ESPN
by hand (e.g. the Thursday-night final graded Friday morning). This pulls the current
scoreboard -- which carries live and just-completed games -- and stores the FINALS, so a
fresh results source is readily on hand for grading and for showing outcomes on-site.

ESPN 403s a "BankrollKings" user-agent, so a plain browser UA is used.

Output: data/scores/{NFL,CFB}_Finals.csv
  cols: GameID, Sport, Date, Away, Home, AwayScore, HomeScore, Status, Updated
Newly-final games are merged in; existing rows for other weeks are kept.
"""
from __future__ import annotations
import argparse
import csv
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "data" / "scores"
SPORTS = {
    "nfl": ("football/nfl", "NFL", ""),
    "cfb": ("football/college-football", "CFB", "&groups=80"),  # 80 = FBS
}
FIELDS = ["GameID", "Sport", "Date", "Away", "Home", "AwayScore", "HomeScore", "Status", "Updated"]
UA = {"User-Agent": "Mozilla/5.0"}


def _scoreboard(path, extra, dates=None):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?limit=400{extra}"
    if dates:
        url += f"&dates={dates}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _finals(path, label, extra, dates):
    data = _scoreboard(path, extra, dates)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    rows = []
    for e in data.get("events", []):
        st = e.get("status", {}).get("type", {})
        if not st.get("completed"):
            continue  # finals only
        comp = (e.get("competitions") or [{}])[0]
        away = home = None
        for c in comp.get("competitors", []):
            side = {"abbr": c.get("team", {}).get("abbreviation"),
                    "name": c.get("team", {}).get("displayName"),
                    "score": c.get("score")}
            if c.get("homeAway") == "home":
                home = side
            else:
                away = side
        if not away or not home:
            continue
        rows.append({
            "GameID": e.get("id"), "Sport": label,
            "Date": (e.get("date") or "")[:10],
            "Away": away["name"], "Home": home["name"],
            "AwayScore": away["score"], "HomeScore": home["score"],
            "Status": st.get("description", "Final"), "Updated": now,
        })
    return rows


def _merge(out_path, new_rows):
    existing = {}
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                existing[str(r.get("GameID"))] = r
    for r in new_rows:
        existing[str(r["GameID"])] = r  # newest wins
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(existing.values(), key=lambda r: (r.get("Date", ""), r.get("Home", "")))
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return len(new_rows), len(ordered)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=list(SPORTS) + ["all"], default="all")
    ap.add_argument("--dates", default=None, help="YYYYMMDD or YYYYMMDD-YYYYMMDD (default: current week)")
    args = ap.parse_args()
    which = list(SPORTS) if args.sport == "all" else [args.sport]
    for s in which:
        path, label, extra = SPORTS[s]
        try:
            rows = _finals(path, label, extra, args.dates)
        except Exception as e:
            print(f"[{label}] fetch failed: {e}")
            continue
        added, total = _merge(OUT_DIR / f"{label}_Finals.csv", rows)
        print(f"[{label}] {added} finals from scoreboard, {total} total -> {label}_Finals.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
