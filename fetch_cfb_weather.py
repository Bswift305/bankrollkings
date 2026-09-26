#!/usr/bin/env python3
"""
CFB game weather (free sources), for this week's slate.

CFBD's own weather endpoint is paywalled, so this builds it from two free sources:
  - CFBD /teams/fbs -> each team's home venue lat/long + dome flag (free tier).
  - Open-Meteo forecast API (no key) -> wind / temp / precip at kickoff.

Outdoor wind of 15+ mph leans a total DOWN. In the NFL this is a backtested edge; in
CFB it is NOT proven, so it is surfaced as CONTEXT, never as an edge -- the honest label.
Dome games are marked and skipped.

Output: data/scenarios/cfb_weather.json (committable). Run in the CFB refresh lane.
Kickoff times + this-week matchups come from data/odds/NCAAF_Odds.csv.
"""
from __future__ import annotations
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
ODDS_PATH = BASE_DIR / "data" / "odds" / "NCAAF_Odds.csv"
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_weather.json"
WIND_FLAG = 15.0  # mph: outdoor wind at/above this leans the total down (context)
ET = timezone(timedelta(hours=-4))  # EDT for September/October


def _norm(s):
    return str(s or "").strip().lower()


def _team_venues(key):
    """school (normalized) -> (lat, lon, dome) from CFBD FBS teams."""
    req = urllib.request.Request("https://api.collegefootballdata.com/teams/fbs?year=2026",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        teams = json.load(r)
    out = {}
    for t in teams:
        loc = t.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            continue
        names = [t.get("school")] + (t.get("alternateNames") or [])
        for n in names:
            out[_norm(n)] = (float(lat), float(lon), bool(loc.get("dome")))
    return out


def _resolve(mascot_name, venues):
    """Map an odds-feed mascot name ('Georgia Bulldogs') to a CFBD school key."""
    q = _norm(mascot_name)
    if q in venues:
        return q
    for school in sorted(venues, key=len, reverse=True):  # longest-first prefix
        if q.startswith(school + " ") or q == school:
            return school
    return None


def _kickoff_utc(date_str, time_str):
    """ET date + 24h ET time ('15:30') -> UTC datetime (nearest hour)."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p"):
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=ET)
            return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        except (ValueError, TypeError):
            continue
    return None


def build():
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    if not ODDS_PATH.exists():
        raise SystemExit(f"No slate at {ODDS_PATH}")
    venues = _team_venues(key)

    odds = pd.read_csv(ODDS_PATH)
    games = odds.groupby(["Away", "Home"]).agg(Date=("Date", "first"), Time=("Time", "first")).reset_index()

    # collect one venue per game (home team's), keep outdoor ones for a bulk forecast
    rows, coords = [], []
    for _, g in games.iterrows():
        school = _resolve(g["Home"], venues)
        v = venues.get(school) if school else None
        rec = {"away": g["Away"], "home": g["Home"], "date": g["Date"], "time": g["Time"],
               "dome": bool(v[2]) if v else None, "wind": None, "temp": None, "precip": None}
        if v and not v[2]:
            rec["_ll"] = (v[0], v[1])
            rec["_ko"] = _kickoff_utc(g["Date"], g["Time"])
            coords.append((v[0], v[1]))
        rows.append(rec)

    # one bulk Open-Meteo call for every outdoor venue
    forecasts = {}
    if coords:
        lats = ",".join(str(c[0]) for c in coords)
        lons = ",".join(str(c[1]) for c in coords)
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
               "&hourly=temperature_2m,precipitation,wind_speed_10m"
               "&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=GMT&forecast_days=8")
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.load(r)
        if isinstance(data, dict):
            data = [data]
        for c, block in zip(coords, data):
            forecasts[c] = block.get("hourly", {})

    for rec in rows:
        ll, ko = rec.pop("_ll", None), rec.pop("_ko", None)
        h = forecasts.get(ll)
        if not h or not ko:
            continue
        target = ko.strftime("%Y-%m-%dT%H:00")
        times = h.get("time", [])
        idx = times.index(target) if target in times else (len(times) // 2 if times else None)
        if idx is None:
            continue
        rec["wind"] = round(h["wind_speed_10m"][idx], 1)
        rec["temp"] = round(h["temperature_2m"][idx])
        rec["precip"] = round(h["precipitation"][idx], 2)
        rec["wind_flag"] = rec["wind"] is not None and rec["wind"] >= WIND_FLAG

    return {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "wind_flag_mph": WIND_FLAG, "games": rows}


def main() -> int:
    load_local_env(BASE_DIR)
    data = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    windy = sum(1 for g in data["games"] if g.get("wind_flag"))
    print(f"Wrote weather for {len(data['games'])} games ({windy} at {WIND_FLAG}+ mph wind) -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
