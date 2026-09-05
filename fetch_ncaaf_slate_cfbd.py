#!/usr/bin/env python3
"""Populate the live NCAAF board from CFBD (games + consensus lines).

The site's College Football board / Best Spots / command center read this week's
slate from data/odds/NCAAF_Odds.csv (spreads/totals/ML) and data/schedules/
NCAAF_Schedule.csv (the games). The Odds-API feed leaves those empty out-of-week,
so the board falls back to generic trends. CFBD has the full FBS slate with lines
days ahead and for free, so we source the upcoming slate from it directly.

Writes, in the exact schema the app expects:
  data/schedules/NCAAF_Schedule.csv   every upcoming FBS game (so all games list)
  data/odds/NCAAF_Odds.csv            games that have a consensus line (spread/total/ML)
  data/schedules/NCAAF_Odds.csv       mirror of the odds file (secondary path)

    source .env.local            # needs CFBD_API_KEY
    python fetch_ncaaf_slate_cfbd.py --year 2026 --days 10
"""
import argparse, csv, json, os, pathlib, urllib.request
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = timezone(timedelta(hours=-4))  # fallback: fixed EDT offset

ROOT = pathlib.Path(__file__).resolve().parent
FBS = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic","American",
       "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}
ODDS_COLS = ["Date","Time","Away","Home","AwayFull","HomeFull","AwayML","HomeML",
             "Spread","SpreadOdds","Total","OverOdds","UnderOdds","Book","GameID","LastUpdated"]


def _key():
    k = os.environ.get("CFBD_API_KEY")
    if k:
        return k.strip()
    for name in (".env.local", ".env"):   # dev keeps it in .env.local, prod in .env
        envf = ROOT / name
        try:
            if envf.exists():
                for line in envf.read_text().splitlines():
                    if line.strip().startswith("CFBD_API_KEY"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue   # e.g. .env readable only by the service user -> rely on env instead
    raise SystemExit("No CFBD_API_KEY in environment (set it, or run as the service user that can read .env)")


def _get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    return json.load(urllib.request.urlopen(req, timeout=45))


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _et(start_iso):
    """CFBD startDate (UTC ISO) -> (YYYY-MM-DD, 'H:MMam/pm') in US/Eastern."""
    if not start_iso:
        return None, ""
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(ET)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%-I:%M %p").lstrip("0") if os.name != "nt" \
            else dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return start_iso[:10], ""


def build(year, days):
    key = _key()
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=days)

    # figure out which weeks fall in the window (pull a few, filter by date)
    games = []
    lines_by_id = {}
    for wk in range(1, 17):
        try:
            gs = _get(f"https://api.collegefootballdata.com/games?year={year}&week={wk}&seasonType=regular", key)
        except Exception:
            continue
        wk_dates = [(_et(g.get("startDate"))[0]) for g in gs if g.get("startDate")]
        wk_dates = [d for d in wk_dates if d]
        if not wk_dates:
            continue
        # weeks are chronological: skip ones entirely before today, stop once past the horizon
        if max(wk_dates) < today.strftime("%Y-%m-%d"):
            continue
        if min(wk_dates) > horizon.strftime("%Y-%m-%d"):
            break
        games.extend(gs)
        try:
            for L in _get(f"https://api.collegefootballdata.com/lines?year={year}&week={wk}&seasonType=regular", key):
                lines_by_id[L.get("id")] = L.get("lines") or []
        except Exception:
            pass

    sched_rows, odds_rows = [], []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for g in games:
        date, t = _et(g.get("startDate"))
        if not date or not (today.strftime("%Y-%m-%d") <= date <= horizon.strftime("%Y-%m-%d")):
            continue
        home, away = g.get("homeTeam"), g.get("awayTeam")
        if g.get("homeConference") not in FBS and g.get("awayConference") not in FBS:
            continue
        sched_rows.append({"Date": date, "Time": t, "Away": away, "Home": home})
        prov = lines_by_id.get(g.get("id"), [])
        spread = _avg([p.get("spread") for p in prov])          # home perspective
        total = _avg([p.get("overUnder") for p in prov])
        hml = _avg([p.get("homeMoneyline") for p in prov])
        aml = _avg([p.get("awayMoneyline") for p in prov])
        if spread is None and total is None:
            continue   # no line yet -> lives on the schedule only
        odds_rows.append({
            "Date": date, "Time": t, "Away": away, "Home": home,
            "AwayFull": away, "HomeFull": home,
            "AwayML": int(aml) if aml is not None else "", "HomeML": int(hml) if hml is not None else "",
            "Spread": spread if spread is not None else "", "SpreadOdds": -110,
            "Total": total if total is not None else "", "OverOdds": -110, "UnderOdds": -110,
            "Book": "CFBD consensus", "GameID": g.get("id"), "LastUpdated": now,
        })

    sched_rows.sort(key=lambda r: (r["Date"], r["Home"]))
    odds_rows.sort(key=lambda r: (r["Date"], r["Home"]))

    (ROOT / "data" / "schedules").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "odds").mkdir(parents=True, exist_ok=True)

    with open(ROOT / "data" / "schedules" / "NCAAF_Schedule.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Date", "Time", "Away", "Home"]); w.writeheader(); w.writerows(sched_rows)
    for p in (ROOT / "data" / "odds" / "NCAAF_Odds.csv", ROOT / "data" / "schedules" / "NCAAF_Odds.csv"):
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=ODDS_COLS); w.writeheader(); w.writerows(odds_rows)

    print(f"window {today} .. {horizon}")
    print(f"  schedule: {len(sched_rows)} games")
    print(f"  odds:     {len(odds_rows)} games with a consensus line")
    if odds_rows:
        s = odds_rows[0]
        print(f"  e.g. {s['Date']} {s['Away']} @ {s['Home']}  spread(home) {s['Spread']}  total {s['Total']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--days", type=int, default=10)
    build(*(lambda a: (a.year, a.days))(ap.parse_args()))
