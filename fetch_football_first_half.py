#!/usr/bin/env python3
"""Fetch FIRST-HALF spread + total for football from The Odds API.

Full-game lines come from the bulk /odds endpoint (fetch_game_lines.py) and,
for CFB, from CFBD. First-half markets (spreads_h1 / totals_h1) are only served
from The Odds API's PER-EVENT endpoint, so they need their own pass. Writes a
compact consensus file the board reads to show a "1H" line next to the game.

  data/odds/NFL_FirstHalf.csv   /  data/odds/NCAAF_FirstHalf.csv
  cols: Date,Time,Away,Home,SpreadH1,TotalH1,Books,GameID,LastUpdated
  (SpreadH1 is the HOME-perspective 1H spread, matching the full-game convention.)

    python fetch_football_first_half.py --sport americanfootball_nfl --days 4
    python fetch_football_first_half.py --sport americanfootball_ncaaf --days 4

Credits: per-event, ~2 credits each (2 markets x 1 region). Keep --days tight;
first-half lines only post close to kickoff anyway.
"""
import argparse, csv, json, os, pathlib, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = timezone(timedelta(hours=-4))

ROOT = pathlib.Path(__file__).resolve().parent
PREFIX = {"americanfootball_nfl": "NFL", "americanfootball_ncaaf": "NCAAF"}
COLS = ["Date", "Time", "Away", "Home", "SpreadH1", "TotalH1", "Books", "GameID", "LastUpdated"]


def _key():
    k = os.environ.get("ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY")
    if k:
        return k.strip()
    for name in (".env.local", ".env"):
        f = ROOT / name
        try:
            if f.exists():
                for line in f.read_text().splitlines():
                    s = line.strip()
                    if s.startswith("ODDS_API_KEY") or s.startswith("THE_ODDS_API_KEY"):
                        return s.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    raise SystemExit("No ODDS_API_KEY in environment or .env(.local)")


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r), r.headers.get("x-requests-remaining")


def _et(iso):
    if not iso:
        return None, ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
        t = dt.strftime("%I:%M %p").lstrip("0")
        return dt.strftime("%Y-%m-%d"), t
    except Exception:
        return iso[:10], ""


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def build(sport, days, bookmakers):
    key = _key()
    base = f"https://api.the-odds-api.com/v4/sports/{sport}"
    events, rem = _get(f"{base}/events?apiKey={key}")
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=days)
    rows = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = 0
    for ev in events:
        date, t = _et(ev.get("commence_time"))
        if not date or not (today.strftime("%Y-%m-%d") <= date <= horizon.strftime("%Y-%m-%d")):
            continue
        home, away = ev.get("home_team"), ev.get("away_team")
        qs = urllib.parse.urlencode({"apiKey": key, "regions": "us",
                                     "markets": "spreads_h1,totals_h1",
                                     "oddsFormat": "american", "bookmakers": bookmakers})
        try:
            odds, rem = _get(f"{base}/events/{ev['id']}/odds?{qs}")
        except urllib.error.HTTPError:
            continue
        checked += 1
        h_spreads, totals, books = [], [], 0
        for bk in odds.get("bookmakers", []):
            got = False
            for m in bk.get("markets", []):
                if m.get("key") == "spreads_h1":
                    for o in m.get("outcomes", []):
                        if o.get("name") == home and o.get("point") is not None:
                            h_spreads.append(float(o["point"])); got = True
                elif m.get("key") == "totals_h1":
                    for o in m.get("outcomes", []):
                        if o.get("name") == "Over" and o.get("point") is not None:
                            totals.append(float(o["point"])); got = True
            if got:
                books += 1
        sp, tot = _avg(h_spreads), _avg(totals)
        if sp is None and tot is None:
            continue
        rows.append({"Date": date, "Time": t, "Away": away, "Home": home,
                     "SpreadH1": sp if sp is not None else "", "TotalH1": tot if tot is not None else "",
                     "Books": books, "GameID": ev.get("id"), "LastUpdated": now})

    rows.sort(key=lambda r: (r["Date"], r["Home"]))
    (ROOT / "data" / "odds").mkdir(parents=True, exist_ok=True)
    out = ROOT / "data" / "odds" / f"{PREFIX.get(sport, sport)}_FirstHalf.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader(); w.writerows(rows)
    print(f"{sport}: window {today}..{horizon}, checked {checked} events, wrote {len(rows)} first-half rows -> {out.name}")
    print(f"  credits remaining: {rem}")
    if rows:
        s = rows[0]
        print(f"  e.g. {s['Date']} {s['Away']} @ {s['Home']}  1H spread(home) {s['SpreadH1']}  1H total {s['TotalH1']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="americanfootball_nfl")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--bookmakers", default="draftkings,caesars,fanduel,betmgm")
    a = ap.parse_args()
    build(a.sport, a.days, a.bookmakers)
