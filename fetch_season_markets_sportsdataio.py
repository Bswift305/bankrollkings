"""Fetch season-long betting futures from SportsDataIO into the Season Markets pipeline.

Season-long team win totals and player season totals (passing/rushing/receiving
yards, touchdowns, points, etc.) feed `/tools/season-markets` — our projections
vs. the sportsbook O/U. Championship outrights and single-game totals are a
different product and are skipped here.

Auth
----
Reads the subscription key from the environment and sends it as the
`Ocp-Apim-Subscription-Key` header, so the key never appears in a URL, a log
line, or the saved dump. Set it (do NOT paste it into chat):

    # PowerShell, this session only:
    $env:SPORTSDATAIO_KEY = "<your key>"
    # or add a line to .env.local:  SPORTSDATAIO_KEY=<your key>

Usage
-----
    # 1) Confirm the REAL schema first — saves raw JSON locally + prints its shape:
    python fetch_season_markets_sportsdataio.py --dump --sport NFL --season 2026

    # 2) Once the parser is confirmed against the dump, populate market rows:
    python fetch_season_markets_sportsdataio.py --sport NFL --season 2026
    python fetch_season_markets_sportsdataio.py --all      # every configured sport
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from services.season_markets import MARKET_COLUMNS

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "season_markets" / "_raw"
API_ROOT = "https://api.sportsdata.io/v3"

# Try these env names in order; the first non-empty wins.
KEY_ENV_NAMES = ("SPORTSDATAIO_KEY", "SPORTSDATA_IO_KEY", "SPORTSDATAIO_API_KEY", "SPORTSDATA_KEY")

# Our sport label -> SportsDataIO URL segment + a sensible default season string.
# Season formats differ per league; override with --season when needed. The --dump
# response will tell us the exact accepted format.
SPORTS = {
    "NFL":    {"path": "nfl",  "season": "2026"},
    "NBA":    {"path": "nba",  "season": "2026"},
    "MLB":    {"path": "mlb",  "season": "2026"},
    "WNBA":   {"path": "wnba", "season": "2026"},
    "NCAAF":  {"path": "cfb",  "season": "2026"},
    "NCAAMB": {"path": "cbb",  "season": "2026"},
}

# Bet-type keywords -> normalized team-win market. Everything else that isn't a
# team-win future is treated as a player season total (labelled from its bet type).
TEAM_WIN_KEYWORDS = ("regular season win", "total win", "win total", "season win")


def _dotenv_value(names: tuple[str, ...]) -> str:
    """Read a key from .env.local / .env without needing them sourced first
    (these scripts don't auto-load dotenv, and PowerShell has no `source`)."""
    wanted = {n.lower() for n in names}
    for fname in (".env.local", ".env"):
        path = BASE_DIR / fname
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip().lower() in wanted:
                return v.strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    for name in KEY_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    from_file = _dotenv_value(KEY_ENV_NAMES)
    if from_file:
        return from_file
    raise SystemExit(
        "No SportsDataIO key found. Set one of "
        + ", ".join(KEY_ENV_NAMES)
        + " (e.g. add SPORTSDATAIO_KEY=<key> to .env.local, then re-run)."
    )


def _get(sport_path: str, season: str, key: str) -> object:
    url = f"{API_ROOT}/{sport_path}/odds/json/BettingFuturesBySeason/{season}"
    resp = requests.get(url, headers={"Ocp-Apim-Subscription-Key": key}, timeout=45)
    # Never surface the key; show only the (key-free) URL on failure.
    if resp.status_code != 200:
        raise SystemExit(f"SportsDataIO {resp.status_code} for {url}\n{resp.text[:400]}")
    return resp.json()


def _g(obj: dict, *names, default=None):
    """First present key among `names`, case-insensitive."""
    if not isinstance(obj, dict):
        return default
    lower = {str(k).lower(): v for k, v in obj.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return v
    return default


def _book_name(outcome: dict) -> str:
    sb = _g(outcome, "SportsBook", "Sportsbook", "Book")
    if isinstance(sb, dict):
        return str(_g(sb, "Name", default="") or "")
    return str(sb or "")


def _iter_markets(payload: object):
    """Yield (market_dict) from the futures payload, tolerant of nesting shape."""
    events = payload if isinstance(payload, list) else [payload]
    for event in events:
        if not isinstance(event, dict):
            continue
        markets = _g(event, "BettingMarkets", "Markets", default=None)
        if isinstance(markets, list):
            for m in markets:
                if isinstance(m, dict):
                    yield m
        elif _g(event, "BettingOutcomes", "Outcomes"):
            # already a market-shaped object
            yield event


def parse(payload: object, sport: str, season: str) -> pd.DataFrame:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # key: (entity, team, market, line, book) -> row with Over/Under merged
    rows: dict[tuple, dict] = {}

    for market in _iter_markets(payload):
        bet_type = str(_g(market, "BettingBetType", "BetType", "Name", default="") or "")
        market_type = str(_g(market, "BettingMarketType", "MarketType", default="") or "")
        low = f"{bet_type} {market_type}".lower()
        is_team_win = any(k in low for k in TEAM_WIN_KEYWORDS)

        outcomes = _g(market, "BettingOutcomes", "Outcomes", default=[]) or []
        for oc in outcomes:
            if not isinstance(oc, dict):
                continue
            side = str(_g(oc, "BettingOutcomeType", "OutcomeType", "Name", default="") or "").lower()
            if side not in ("over", "under"):
                continue  # season O/U only; skip yes/no + moneyline-style outcomes
            line = _g(oc, "Value", "Line", "Point")
            if line is None:
                continue
            price = _g(oc, "PayoutAmerican", "American", "OddsAmerican", "MoneyLine")
            player = _g(oc, "PlayerName", "Player", "Participant", "Name")
            team = _g(oc, "Team", "TeamName", "TeamKey")
            book = _book_name(oc)
            updated = _g(oc, "Updated", "Created") or _g(market, "Updated", "Created") or now

            if is_team_win:
                entity = str(team or player or "").strip()
                team_val = entity
                market_label = "Regular Season Wins"
                etype = "team"
            else:
                entity = str(player or "").strip()
                team_val = str(team or "").strip()
                market_label = bet_type.strip() or "Season Total"
                etype = "player"
            if not entity:
                continue

            k = (etype, entity, team_val, market_label, float(line), book)
            row = rows.get(k)
            if row is None:
                row = {
                    "SnapshotAt": now, "Sport": sport, "Season": str(season),
                    "EntityType": etype, "Entity": entity, "Team": team_val,
                    "Market": market_label, "Line": float(line),
                    "OverOdds": None, "UnderOdds": None, "Book": book,
                    "Source": "SportsDataIO", "SourceUpdatedAt": updated,
                }
                rows[k] = row
            if side == "over":
                row["OverOdds"] = price
            else:
                row["UnderOdds"] = price

    frame = pd.DataFrame(list(rows.values()), columns=MARKET_COLUMNS)
    return frame


def _describe(payload: object) -> str:
    """Human summary of the payload shape for the --dump step (no key, no PII spam)."""
    lines = []
    events = payload if isinstance(payload, list) else [payload]
    lines.append(f"top-level: {'list' if isinstance(payload, list) else type(payload).__name__}, {len(events)} item(s)")
    if events and isinstance(events[0], dict):
        lines.append("first item keys: " + ", ".join(list(events[0].keys())[:20]))
        markets = _g(events[0], "BettingMarkets", "Markets")
        if isinstance(markets, list) and markets:
            lines.append(f"  BettingMarkets: {len(markets)}; first market keys: " + ", ".join(list(markets[0].keys())[:20]))
            ocs = _g(markets[0], "BettingOutcomes", "Outcomes")
            if isinstance(ocs, list) and ocs:
                lines.append(f"    BettingOutcomes: {len(ocs)}; first outcome keys: " + ", ".join(list(ocs[0].keys())[:24]))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch SportsDataIO season betting futures.")
    ap.add_argument("--sport", default="NFL", help="One of: " + ", ".join(SPORTS))
    ap.add_argument("--season", default="", help="Override season string (default per sport).")
    ap.add_argument("--all", action="store_true", help="Fetch every configured sport.")
    ap.add_argument("--dump", action="store_true", help="Save raw JSON locally and print its shape; do not write market CSVs.")
    ap.add_argument("--write", action="store_true", help="Write parsed rows into data/season_markets/ (via the refresh pipeline).")
    args = ap.parse_args()

    key = _api_key()
    targets = list(SPORTS) if args.all else [args.sport.upper()]
    for sport in targets:
        if sport not in SPORTS:
            print(f"skip {sport}: not configured"); continue
        cfg = SPORTS[sport]
        season = args.season or cfg["season"]
        payload = _get(cfg["path"], season, key)

        if args.dump:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            out = RAW_DIR / f"{sport.lower()}_futures_{season}.json"
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"[{sport}] raw JSON -> {out}")
            print(_describe(payload))
            continue

        frame = parse(payload, sport, season)
        print(f"[{sport} {season}] parsed {len(frame)} season-market row(s); "
              f"markets: {frame['Market'].nunique() if len(frame) else 0}")
        if args.write and len(frame):
            from refresh_season_markets import normalize, _write, CURRENT, HISTORY
            current = normalize(frame, default_source="SportsDataIO")
            _write(current, CURRENT)
            if HISTORY.exists() and HISTORY.stat().st_size:
                try:
                    hist = pd.read_csv(HISTORY, low_memory=False)
                except pd.errors.EmptyDataError:
                    hist = pd.DataFrame(columns=MARKET_COLUMNS)
            else:
                hist = pd.DataFrame(columns=MARKET_COLUMNS)
            hist = pd.concat([hist, current], ignore_index=True).drop_duplicates(
                subset=["SnapshotAt", "Sport", "Season", "EntityType", "Entity", "Team", "Market", "Book"],
                keep="last")
            _write(hist[MARKET_COLUMNS], HISTORY)
            print(f"[{sport}] wrote {len(current)} rows -> {CURRENT.name} (history {len(hist)})")
        elif not args.write and len(frame):
            print(frame.head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
