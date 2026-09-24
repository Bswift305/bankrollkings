#!/usr/bin/env python3
"""Fetch FIRST-HALF spread + total for football from The Odds API.

Full-game lines come from the bulk /odds endpoint (fetch_game_lines.py) and,
for CFB, from CFBD. Period markets (spreads_h1 / totals_h1 and the _q1 first-quarter
equivalents) are only served from The Odds API's PER-EVENT endpoint, so they need
their own pass. Writes a compact consensus file the board reads to show "1H" and
"1Q" lines next to the game -- more ways to play the same read (e.g. a first-half
under when both defenses start strong).

  data/odds/NFL_FirstHalf.csv   /  data/odds/NCAAF_FirstHalf.csv
  cols: Date,Time,Away,Home,SpreadH1,TotalH1,SpreadQ1,TotalQ1,Books,GameID,LastUpdated
  (SpreadH1/SpreadQ1 are the HOME-perspective spreads, matching the full-game convention.
   Consensus is the MEDIAN across books, which shrugs off the occasional book-side outlier.)

    python fetch_football_first_half.py --sport americanfootball_nfl --days 4
    python fetch_football_first_half.py --sport americanfootball_ncaaf --days 4

Credits: per-event, ~2 credits each (2 markets x 1 region). Keep --days tight;
first-half lines only post close to kickoff anyway.
"""
import argparse, csv, json, os, pathlib, statistics, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = timezone(timedelta(hours=-4))

ROOT = pathlib.Path(__file__).resolve().parent
PREFIX = {"americanfootball_nfl": "NFL", "americanfootball_ncaaf": "NCAAF"}
COLS = ["Date", "Time", "Away", "Home", "SpreadH1", "TotalH1", "SpreadQ1", "TotalQ1",
        "Books", "GameID", "LastUpdated"]


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


def _consensus(vals):
    """Median across books -- robust to the occasional garbage line one book posts."""
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


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
                                     "markets": "spreads_h1,totals_h1,spreads_q1,totals_q1",
                                     "oddsFormat": "american", "bookmakers": bookmakers})
        try:
            odds, rem = _get(f"{base}/events/{ev['id']}/odds?{qs}")
        except urllib.error.HTTPError:
            continue
        checked += 1
        h_spreads, h_totals, q_spreads, q_totals, books = [], [], [], [], 0
        for bk in odds.get("bookmakers", []):
            got = False
            for m in bk.get("markets", []):
                key_m = m.get("key")
                spread_bucket = h_spreads if key_m == "spreads_h1" else (q_spreads if key_m == "spreads_q1" else None)
                total_bucket = h_totals if key_m == "totals_h1" else (q_totals if key_m == "totals_q1" else None)
                if spread_bucket is not None:
                    for o in m.get("outcomes", []):
                        if o.get("name") == home and o.get("point") is not None:
                            spread_bucket.append(float(o["point"])); got = True
                elif total_bucket is not None:
                    for o in m.get("outcomes", []):
                        if o.get("name") == "Over" and o.get("point") is not None:
                            total_bucket.append(float(o["point"])); got = True
            if got:
                books += 1
        sp, tot = _consensus(h_spreads), _consensus(h_totals)
        qsp, qtot = _consensus(q_spreads), _consensus(q_totals)
        if sp is None and tot is None and qsp is None and qtot is None:
            continue
        rows.append({"Date": date, "Time": t, "Away": away, "Home": home,
                     "SpreadH1": sp if sp is not None else "", "TotalH1": tot if tot is not None else "",
                     "SpreadQ1": qsp if qsp is not None else "", "TotalQ1": qtot if qtot is not None else "",
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
        print(f"  e.g. {s['Date']} {s['Away']} @ {s['Home']}  1H {s['SpreadH1']}/{s['TotalH1']}  1Q {s['SpreadQ1']}/{s['TotalQ1']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="americanfootball_nfl")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--bookmakers", default="draftkings,caesars,fanduel,betmgm")
    a = ap.parse_args()
    build(a.sport, a.days, a.bookmakers)
