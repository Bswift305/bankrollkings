"""
Bankroll Kings - Live Scores poller (The Odds API /scores)
==========================================================

Lightweight, standalone job. Pulls live/final game scores from The Odds API
`/v4/sports/{key}/scores` and writes one normalized multi-sport CSV
(data/live_scores/Live_Scores.csv). Designed to run every ~60s on its OWN
systemd timer (bk-live-scores) -- NOT part of run_daily.py / the heavy chain.

Quota hygiene: only polls a sport that has a game TODAY whose start window is
open (and not all-final yet). Off-season / no-game / pre-window runs are a cheap
no-op (no API calls). Fail-soft: on API error a sport's existing rows are kept.

NOTE: The Odds API /scores returns score + completed flag + last_update only --
no period/clock. Period/Clock columns are kept blank so a richer source
(ESPN/SportsDataIO) can fill them later without changing the data contract.

Usage:
    py refresh_live_scores.py                # gated poll (timer uses this)
    py refresh_live_scores.py --force        # ignore gating (manual test)
    py refresh_live_scores.py --sport basketball_nba --force
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from services.env_loader import load_local_env

BASE_DIR = Path(__file__).parent.resolve()
load_local_env(BASE_DIR)

OUTPUT_PATH = BASE_DIR / "data" / "live_scores" / "Live_Scores.csv"
COLUMNS = [
    "Sport", "GameId", "Date", "Away", "Home", "AwayScore", "HomeScore",
    "Status", "Period", "Clock", "StartTime", "LastUpdated", "Source",
]
SOURCE = "the-odds-api"

# sport_key -> short prefix used across the app (NBA_Schedule.csv, Sport column, etc.)
SPORTS = {
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
    "baseball_mlb": "MLB",
    "americanfootball_nfl": "NFL",
    "americanfootball_ncaaf": "NCAAF",
}

# Don't poll until ~20 min before the day's first game; keep polling through it.
PREGAME_LEAD = timedelta(minutes=20)


def get_api_key() -> str:
    key = os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not key:
        raise ValueError("Missing API key. Set ODDS_API_KEY (or THE_ODDS_API_KEY).")
    return key.strip()


def _today_str() -> str:
    # Schedule rows are dated in server-local time (UTC on prod); match that.
    return datetime.now().strftime("%Y-%m-%d")


def _read_csv_safe(path: Path) -> pd.DataFrame:
    try:
        if path.exists() and path.stat().st_size > 0:
            return pd.read_csv(path, low_memory=False)
    except Exception:
        pass
    return pd.DataFrame()


def _schedule_for(prefix: str) -> pd.DataFrame:
    for name in (f"{prefix}_Schedule.csv", f"{prefix}_Odds.csv"):
        df = _read_csv_safe(BASE_DIR / "data" / "schedules" / name)
        if not df.empty and {"Date", "Away", "Home"}.issubset(df.columns):
            return df
    return pd.DataFrame()


def _existing_rows(prefix: str, today: str) -> pd.DataFrame:
    df = _read_csv_safe(OUTPUT_PATH)
    if df.empty or "Sport" not in df.columns:
        return pd.DataFrame()
    return df[(df["Sport"].astype(str) == prefix) & (df.get("Date", "").astype(str) == today)].copy()


def sport_has_live_window(prefix: str, now: datetime) -> bool:
    """True if this sport has a game today whose window is open and not all-final."""
    today = now.strftime("%Y-%m-%d")
    sched = _schedule_for(prefix)
    if sched.empty:
        return False
    todays = sched[sched["Date"].astype(str).str.strip() == today]
    if todays.empty:
        return False

    # Too early? Skip until ~20 min before the first start (if we can parse times).
    starts = []
    for _, row in todays.iterrows():
        t = str(row.get("Time", "") or "").strip()
        try:
            starts.append(datetime.strptime(f"{today} {t}", "%Y-%m-%d %H:%M"))
        except ValueError:
            continue
    if starts and now < (min(starts) - PREGAME_LEAD):
        return False

    # All of today's games already final in our CSV? Stop polling for the night.
    existing = _existing_rows(prefix, today)
    if not existing.empty and len(existing) >= len(todays):
        statuses = set(existing.get("Status", "").astype(str).str.lower())
        if statuses and statuses <= {"final"}:
            return False
    return True


def fetch_scores(sport_key: str, api_key: str) -> tuple[list, dict]:
    """Return (events, response_headers). Raises on transport/HTTP error."""
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"
        f"?{urlencode({'apiKey': api_key, 'daysFrom': 1, 'dateFormat': 'iso'})}"
    )
    with urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        headers = {k.lower(): v for k, v in resp.headers.items()}
    return (payload if isinstance(payload, list) else []), headers


def _iso_to_date(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _score_for(scores, team_name):
    if not scores:
        return ""
    for item in scores:
        if str(item.get("name", "")).strip() == str(team_name).strip():
            val = item.get("score", "")
            return "" if val is None else str(val)
    return ""


def normalize_event(prefix: str, event: dict) -> dict | None:
    away = str(event.get("away_team", "") or "").strip()
    home = str(event.get("home_team", "") or "").strip()
    if not away or not home:
        return None
    scores = event.get("scores")
    completed = bool(event.get("completed"))
    if completed:
        status = "final"
    elif scores:
        status = "live"
    else:
        status = "pre"
    return {
        "Sport": prefix,
        "GameId": str(event.get("id", "") or ""),
        "Date": _iso_to_date(event.get("commence_time", "")),
        "Away": away,
        "Home": home,
        "AwayScore": _score_for(scores, away),
        "HomeScore": _score_for(scores, home),
        "Status": status,
        "Period": "",   # not provided by The Odds API
        "Clock": "",    # not provided by The Odds API
        "StartTime": str(event.get("commence_time", "") or ""),
        "LastUpdated": str(event.get("last_update", "") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "Source": SOURCE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll The Odds API for live scores.")
    parser.add_argument("--sport", help="Single sport_key (default: all in-season with games today).")
    parser.add_argument("--force", action="store_true", help="Ignore game-day/window gating.")
    args = parser.parse_args()

    now = datetime.now()
    sport_keys = [args.sport] if args.sport else list(SPORTS.keys())
    sport_keys = [s for s in sport_keys if s in SPORTS]

    # Decide which sports to actually poll (quota hygiene).
    to_poll = [s for s in sport_keys if args.force or sport_has_live_window(SPORTS[s], now)]
    if not to_poll:
        print(f"[live-scores] no live windows {now:%Y-%m-%d %H:%M} -- no API calls.")
        return 0

    try:
        api_key = get_api_key()
    except ValueError as exc:
        print(f"[live-scores] {exc}")
        return 1

    existing_all = _read_csv_safe(OUTPUT_PATH)
    if not existing_all.empty:
        for col in COLUMNS:
            if col not in existing_all.columns:
                existing_all[col] = ""
        existing_all = existing_all[COLUMNS]

    fresh_frames = []
    polled_prefixes = []
    failures = []
    for sport_key in to_poll:
        prefix = SPORTS[sport_key]
        try:
            events, headers = fetch_scores(sport_key, api_key)
        except Exception as exc:
            failures.append((prefix, str(exc)))
            print(f"[live-scores] {prefix}: FETCH FAILED ({exc}) -- keeping existing rows.")
            continue
        rows = [r for r in (normalize_event(prefix, e) for e in events) if r]
        polled_prefixes.append(prefix)
        if rows:
            fresh_frames.append(pd.DataFrame(rows, columns=COLUMNS))
        live_n = sum(1 for r in rows if r["Status"] == "live")
        rem = headers.get("x-requests-remaining", "?")
        print(f"[live-scores] {prefix}: {len(rows)} games ({live_n} live) | x-requests-remaining={rem}")

    # Merge: drop old rows for successfully-polled sports, keep everyone else, add fresh.
    keep = existing_all
    if not keep.empty and polled_prefixes:
        keep = keep[~keep["Sport"].astype(str).isin(polled_prefixes)].copy()
    out = pd.concat([keep] + fresh_frames, ignore_index=True) if (not keep.empty or fresh_frames) else pd.DataFrame(columns=COLUMNS)

    if out.empty and existing_all.empty:
        print("[live-scores] nothing to write yet.")
        return 1 if failures else 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f"[live-scores] wrote {len(out)} rows -> {OUTPUT_PATH}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
