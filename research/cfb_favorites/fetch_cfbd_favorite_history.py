# -*- coding: utf-8 -*-
"""
Pull multi-season CFB history from CFBD (games + lines + coaches) for the
big-favorite / fast-vs-slow-starter trend. Everything joins on CFBD naming, so no
name-matching guesswork. Writes three CSVs to data/historical/:
    CFBD_Games_2016_2025.csv    (scores, week, conference)
    CFBD_Lines_2016_2025.csv    (consensus spread + total per game)
    CFBD_Coaches_2016_2025.csv  (coach per school per year)

Needs CFBD_API_KEY in the environment (source .env.local first).
    source .env.local && python research/cfb_favorites/fetch_cfbd_favorite_history.py
"""
import os, json, csv, pathlib, statistics, urllib.request, time

KEY = os.environ.get("CFBD_API_KEY", "").strip()
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "historical"
YEARS = range(2016, 2026)

def get(path):
    req = urllib.request.Request("https://api.collegefootballdata.com" + path,
                                 headers={"Authorization": f"Bearer {KEY}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2: raise
            time.sleep(2)

def g(rec, *keys):
    for k in keys:
        if k in rec and rec[k] is not None: return rec[k]
    return None

def main():
    if not KEY:
        raise SystemExit("No CFBD_API_KEY — run: source .env.local first")
    games, lines = [], []
    for y in YEARS:
        gs = get(f"/games?year={y}&seasonType=regular")
        for r in gs:
            games.append({
                "id": g(r,"id"), "season": g(r,"season"), "week": g(r,"week"),
                "homeTeam": g(r,"homeTeam","home_team"), "awayTeam": g(r,"awayTeam","away_team"),
                "homeConf": g(r,"homeConference","home_conference"),
                "awayConf": g(r,"awayConference","away_conference"),
                "homePts": g(r,"homePoints","home_points"), "awayPts": g(r,"awayPoints","away_points"),
                "neutral": g(r,"neutralSite","neutral_site"),
            })
        ls = get(f"/lines?year={y}&seasonType=regular")
        for r in ls:
            sp = [ln.get("spread") for ln in (r.get("lines") or []) if ln.get("spread") is not None]
            ou = [ln.get("overUnder") for ln in (r.get("lines") or []) if ln.get("overUnder") is not None]
            if not sp: continue
            lines.append({
                "season": g(r,"season"), "week": g(r,"week"),
                "homeTeam": g(r,"homeTeam","home_team"), "awayTeam": g(r,"awayTeam","away_team"),
                "spread": round(statistics.median([float(s) for s in sp]), 1),
                "total": round(statistics.median([float(o) for o in ou]), 1) if ou else "",
                "books": len(sp),
            })
        print(f"  {y}: {len(gs)} games, {len(ls)} lined games", flush=True)

    coaches = []
    for c in get("/coaches?minYear=2016&maxYear=2025"):
        name = f"{(c.get('firstName') or '').strip()} {(c.get('lastName') or '').strip()}".strip()
        for s in (c.get("seasons") or []):
            coaches.append({"coach": name, "school": g(s,"school"), "year": g(s,"year"),
                            "games": g(s,"games"), "wins": g(s,"wins"), "losses": g(s,"losses")})

    OUT.mkdir(parents=True, exist_ok=True)
    def write(name, rows):
        p = OUT / name
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print(f"WROTE {p}  ({len(rows)} rows)")
    write("CFBD_Games_2016_2025.csv", games)
    write("CFBD_Lines_2016_2025.csv", lines)
    write("CFBD_Coaches_2016_2025.csv", coaches)

if __name__ == "__main__":
    main()
