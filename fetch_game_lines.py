"""
Bankroll Kings - Fetch Game Lines from The Odds API
===================================================

Examples:
    $env:ODDS_API_KEY="your_key_here"; py fetch_game_lines.py
    py fetch_game_lines.py --sport basketball_nba --bookmakers draftkings,fanduel --days 5
    py fetch_game_lines.py --sport americanfootball_nfl --bookmakers draftkings,caesars,fanduel,betmgm --days 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from services.env_loader import load_local_env
from services.timeutils import to_eastern_datetime_str, to_utc_z_str


BASE_DIR = Path(__file__).parent.resolve()
load_local_env(BASE_DIR)
SPORT_OUTPUTS = {
    "basketball_nba": {
        "odds": BASE_DIR / "data" / "odds" / "NBA_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NBA_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NBA_Schedule.csv",
    },
    "basketball_wnba": {
        "odds": BASE_DIR / "data" / "odds" / "WNBA_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "WNBA_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "WNBA_Schedule.csv",
    },
    "americanfootball_nfl": {
        "odds": BASE_DIR / "data" / "odds" / "NFL_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NFL_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NFL_Schedule.csv",
    },
    "americanfootball_ncaaf": {
        "odds": BASE_DIR / "data" / "odds" / "NCAAF_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NCAAF_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NCAAF_Schedule.csv",
    },
    "americanfootball_nfl_preseason": {
        "odds": BASE_DIR / "data" / "odds" / "NFL_Preseason_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NFL_Preseason_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NFL_Preseason_Schedule.csv",
    },
    "baseball_mlb": {
        "odds": BASE_DIR / "data" / "odds" / "MLB_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "MLB_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "MLB_Schedule.csv",
    },
}
DEFAULT_SPORT = "basketball_nba"
DEFAULT_BOOKMAKERS = "draftkings"
DEFAULT_REGIONS = "us"
SPORT_DEFAULT_MARKETS = {
    "basketball_nba": ["h2h", "spreads", "totals"],
    "basketball_wnba": ["h2h", "spreads", "totals"],
    "americanfootball_nfl": ["h2h", "spreads", "totals"],
    "americanfootball_nfl_preseason": ["h2h", "spreads", "totals"],
    "americanfootball_ncaaf": ["h2h", "spreads", "totals"],
    "baseball_mlb": ["h2h", "spreads", "totals"],
}
SPORT_TRACKING_PREFIX = {
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
    "americanfootball_nfl": "NFL",
    "americanfootball_nfl_preseason": "NFL_Preseason",
    "americanfootball_ncaaf": "NCAAF",
    "baseball_mlb": "MLB",
}

BOOKMAKER_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
}

# Sports whose game lines validate per EVENT (docs/game_lines_event_contract.md). Only these sports'
# artifacts carry the EventCommenceAtUTC column; every other sport keeps the GAME_LINES_SPEC whole-file
# validator and a byte-for-byte unchanged schema. NFL/NCAAF (F5) migrate by adding a spec here.
EVENT_AWARE_GAME_LINES_SPORTS = frozenset({"basketball_nba"})
EVENT_TIME_COL = "EventCommenceAtUTC"

# Per-run provider facts (events returned by /odds), recorded so the receipt can tell a genuine
# NO_ACTIVE_EVENTS (provider answered: zero events in the window) from a failure.
_FETCH_FACTS: dict = {}

# Receipt outcome vocabulary for _last_game_lines_fetch_<sport>.json. Only NO_ACTIVE_EVENTS (non-event-aware
# sports) is a proven benign non-publish; every other non-UPDATED outcome is a failure. Event-aware sports
# (NBA) never record NO_ACTIVE_EVENTS: an empty provider answer there is SCHEDULE_UNAVAILABLE
# (services/nba_schedule_authority.py) unless an authoritative independent schedule says otherwise.
LINES_UPDATED = "UPDATED"
LINES_NO_ACTIVE_EVENTS = "NO_ACTIVE_EVENTS"
LINES_PROVIDER_ERROR = "PROVIDER_ERROR"
LINES_VALIDATION_FAILED = "VALIDATION_FAILED"
LINES_COST_RECEIPT_FAILED = "COST_RECEIPT_FAILED"
LINES_PUBLISH_FAILED = "PUBLISH_FAILED"


def _event_spec_for(sport: str):
    if sport not in EVENT_AWARE_GAME_LINES_SPORTS:
        return None
    from services.feed_validation import NBA_GAME_LINES_EVENT_SPEC
    return {"basketball_nba": NBA_GAME_LINES_EVENT_SPEC}.get(sport)


def lines_receipt_path(sport: str) -> Path:
    return BASE_DIR / "data" / "tracking" / f"_last_game_lines_fetch_{sport.replace('/', '_')}.json"


def _sha256_file(path: Path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _write_lines_receipt(sport: str, payload: dict) -> None:
    """Atomically write the per-sport game-lines fetch receipt (every exit path). Sanitized: counts,
    event ids, book names, hashes and reason codes only -- never prices or the API key."""
    path = lines_receipt_path(sport)
    # Receipt-identity contract (2026-11-04): the caller's run token (services/run_receipts.STAGE_RUN_ENV) is
    # stamped on the receipt, so a runner (refresh_line_movement_snapshots, the NBA publisher's caller) can
    # identify the receipt written by ITS invocation -- never by file mtime. No/unsafe token -> null.
    try:
        from services.run_receipts import UnsafeRunToken, env_token
        token = env_token()
    except UnsafeRunToken:
        token = None
    payload = {**payload, "stage_run_id": token}
    try:
        from services.receipt_io import replace_with_retry
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        replace_with_retry(tmp, path)
        print(f"Game-lines receipt: {path.name} (outcome={payload.get('outcome')}, "
              f"published={payload.get('published')})")
    except OSError as exc:
        print(f"[WARN] could not write game-lines receipt: {exc}")


def get_api_key(cli_value: str | None) -> str:
    api_key = cli_value or os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise ValueError("Missing API key. Set ODDS_API_KEY or pass --api-key.")
    return api_key.strip()


from services.odds_quota import QuotaRecorder

_QUOTA = QuotaRecorder()   # per-run quota accounting; get_json records each paid response's usage headers


def _sport_tokens(sport: str):
    """League token(s) the output filename must contain, so e.g. an NFL fetch cannot overwrite the NBA file."""
    s = (sport or "").lower()
    for needle, token in (("ncaaf", "NCAAF"), ("nfl", "NFL"), ("wnba", "WNBA"), ("nba", "NBA"), ("mlb", "MLB")):
        if needle in s:
            return (token,)
    return ()


def get_json(url: str) -> list | dict:
    with urlopen(url, timeout=30) as response:
        _QUOTA.record(response.headers, paid=True)   # capture x-requests-* (never logs the url/key)
        return json.loads(response.read().decode("utf-8"))


def build_url(path: str, **params) -> str:
    clean_params = {k: v for k, v in params.items() if v not in [None, ""]}
    return f"https://api.the-odds-api.com{path}?{urlencode(clean_params)}"


def to_iso_local(value: str | None) -> str:
    # Convert the API's UTC commence time to a fixed Eastern display string.
    # See services.timeutils for why a bare .astimezone() is unsafe here.
    return to_eastern_datetime_str(value)


def fetch_events(api_key: str, days: int, sport: str = DEFAULT_SPORT) -> list[dict]:
    now = datetime.now(timezone.utc)
    commence_from = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commence_to = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = build_url(
        f"/v4/sports/{sport}/events",
        apiKey=api_key,
        dateFormat="iso",
        commenceTimeFrom=commence_from,
    )
    events = get_json(url)

    filtered = []
    for event in events:
        commence_time = event.get("commence_time")
        if not commence_time:
            continue
        if commence_time <= commence_to:
            filtered.append(event)
    return filtered


def blank_row(event: dict, bookmaker_title: str) -> dict:
    commence_time = event.get("commence_time")
    local_time = to_iso_local(commence_time)
    game_dt = ""
    game_time = ""
    if local_time:
        parts = local_time.split(" ", 1)
        game_dt = parts[0]
        game_time = parts[1] if len(parts) > 1 else ""

    return {
        "Date": game_dt,
        "Time": game_time,
        "Away": event.get("away_team", ""),
        "Home": event.get("home_team", ""),
        "AwayFull": event.get("away_team", ""),
        "HomeFull": event.get("home_team", ""),
        "AwayML": pd.NA,
        "HomeML": pd.NA,
        "Spread": pd.NA,
        "SpreadOdds": pd.NA,
        "Total": pd.NA,
        "OverOdds": pd.NA,
        "UnderOdds": pd.NA,
        "Book": bookmaker_title,
        "GameID": event.get("id", ""),
        # Authoritative provider kickoff, canonical UTC 'Z' (never derived from the Eastern display
        # Date/Time). Kept only for EVENT_AWARE_GAME_LINES_SPORTS by build_dataframe.
        EVENT_TIME_COL: to_utc_z_str(commence_time),
        "LastUpdated": "",
    }


def parse_event_markets(event: dict, bookmaker: dict) -> dict:
    bookmaker_title = bookmaker.get("title") or BOOKMAKER_TITLES.get(bookmaker.get("key", ""), bookmaker.get("key", ""))
    row = blank_row(event, bookmaker_title)
    row["LastUpdated"] = to_iso_local(bookmaker.get("last_update"))

    home = str(event.get("home_team", "")).strip()
    away = str(event.get("away_team", "")).strip()

    for market in bookmaker.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])

        if key == "h2h":
            for outcome in outcomes:
                name = str(outcome.get("name", "")).strip()
                price = outcome.get("price")
                if name == home:
                    row["HomeML"] = price
                elif name == away:
                    row["AwayML"] = price

        elif key == "spreads":
            for outcome in outcomes:
                name = str(outcome.get("name", "")).strip()
                point = outcome.get("point")
                price = outcome.get("price")
                if name == home:
                    row["Spread"] = point
                    row["SpreadOdds"] = price
                    break
                if name == away and point not in [None, ""]:
                    row["Spread"] = -float(point)
                    row["SpreadOdds"] = price
                    break

        elif key == "totals":
            for outcome in outcomes:
                side = str(outcome.get("name", "")).strip().lower()
                point = outcome.get("point")
                price = outcome.get("price")
                if point not in [None, ""] and pd.isna(row["Total"]):
                    row["Total"] = point
                if side == "over":
                    row["OverOdds"] = price
                    if point not in [None, ""]:
                        row["Total"] = point
                elif side == "under":
                    row["UnderOdds"] = price
                    if point not in [None, ""] and pd.isna(row["Total"]):
                        row["Total"] = point

    return row


def fetch_odds_rows(api_key: str, sport: str, bookmakers: str, markets: list[str], regions: str, days: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    commence_from = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commence_to = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = build_url(
        f"/v4/sports/{sport}/odds",
        apiKey=api_key,
        regions=regions,
        bookmakers=bookmakers,
        markets=",".join(markets),
        oddsFormat="american",
        dateFormat="iso",
        commenceTimeFrom=commence_from,
        commenceTimeTo=commence_to,
    )
    payload = get_json(url)
    _FETCH_FACTS["events_returned"] = len(payload) if isinstance(payload, list) else None
    _FETCH_FACTS["event_ids"] = sorted(str(e.get("id") or "") for e in payload) if isinstance(payload, list) else []
    rows = []
    for event in payload:
        for bookmaker in event.get("bookmakers", []):
            rows.append(parse_event_markets(event, bookmaker))
    return rows


def build_dataframe(rows: list[dict], include_event_utc: bool = False) -> pd.DataFrame:
    columns = [
        "Date",
        "Time",
        "Away",
        "Home",
        "AwayFull",
        "HomeFull",
        "AwayML",
        "HomeML",
        "Spread",
        "SpreadOdds",
        "Total",
        "OverOdds",
        "UnderOdds",
        "Book",
        "GameID",
        "LastUpdated",
    ]
    if include_event_utc:
        columns.insert(columns.index("GameID") + 1, EVENT_TIME_COL)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=columns)

    for col in ["AwayML", "HomeML", "Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[columns]
    df = df.drop_duplicates(subset=["Date", "Away", "Home", "Book"], keep="last")
    return df.sort_values(["Date", "Time", "Away", "Home", "Book"]).reset_index(drop=True)


def build_schedule_alias(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Date", "Time", "Away", "Home"])

    alias_columns = [
        "Date", "Time", "Away", "Home",
        "AwayFull", "HomeFull", "Book", "GameID", EVENT_TIME_COL, "LastUpdated"
    ]
    available = [col for col in alias_columns if col in df.columns]
    alias_df = df[available].copy()
    alias_df = alias_df.drop_duplicates(subset=[col for col in ["Date", "Away", "Home"] if col in alias_df.columns], keep="last")
    sort_cols = [col for col in ["Date", "Time", "Away", "Home"] if col in alias_df.columns]
    if sort_cols:
        alias_df = alias_df.sort_values(sort_cols).reset_index(drop=True)
    return alias_df


def append_line_movement_snapshot(df: pd.DataFrame, sport: str) -> None:
    if df is None or df.empty:
        return
    sport_prefix = SPORT_TRACKING_PREFIX.get(sport, sport.upper().replace("-", "_"))
    tracking_dir = BASE_DIR / "data" / "tracking"
    tracking_dir.mkdir(parents=True, exist_ok=True)
    history_path = tracking_dir / f"{sport_prefix}_LineMovementHistory.csv"
    current_path = tracking_dir / f"{sport_prefix}_LineMovementCurrent.csv"

    snapshot_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snapshot = df.copy()
    snapshot.insert(0, "SnapshotAt", snapshot_at)
    snapshot.insert(1, "Sport", sport_prefix)

    if history_path.exists():
        try:
            history = pd.read_csv(history_path)
        except Exception:
            history = pd.DataFrame()
        history = pd.concat([history, snapshot], ignore_index=True, sort=False)
    else:
        history = snapshot

    dedupe_cols = [
        col for col in ["SnapshotAt", "Sport", "GameID", "Date", "Away", "Home", "Book"]
        if col in history.columns
    ]
    if dedupe_cols:
        history = history.drop_duplicates(subset=dedupe_cols, keep="last")
    history.to_csv(history_path, index=False)

    key_cols = [col for col in ["Sport", "GameID", "Date", "Away", "Home", "Book"] if col in history.columns]
    if not key_cols:
        return
    sort_cols = [col for col in ["SnapshotAt", "LastUpdated"] if col in history.columns]
    ordered = history.sort_values(sort_cols) if sort_cols else history.copy()
    rows = []
    tracked_fields = ["AwayML", "HomeML", "Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds"]
    for key_values, group in ordered.groupby(key_cols, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        group = group.copy()
        latest_row = group.tail(1).iloc[0]
        row = {col: value for col, value in zip(key_cols, key_values)}
        row["FirstSeen"] = str(group["SnapshotAt"].iloc[0]) if "SnapshotAt" in group.columns else ""
        row["LastSnapshotAt"] = str(latest_row.get("SnapshotAt", ""))
        row["LastUpdated"] = str(latest_row.get("LastUpdated", ""))
        for field in tracked_fields:
            values = pd.to_numeric(group.get(field), errors="coerce") if field in group.columns else pd.Series(dtype=float)
            values = values.dropna()
            open_value = values.iloc[0] if not values.empty else pd.NA
            current_value = pd.to_numeric(pd.Series([latest_row.get(field)]), errors="coerce").iloc[0] if field in latest_row else pd.NA
            row[f"Open{field}"] = open_value
            row[f"Current{field}"] = current_value
            try:
                row[f"{field}Move"] = round(float(current_value) - float(open_value), 3)
            except Exception:
                row[f"{field}Move"] = pd.NA
        rows.append(row)

    current = pd.DataFrame(rows)
    if not current.empty:
        current = current.sort_values([col for col in ["Date", "Time", "Away", "Home", "Book"] if col in current.columns])
    current.to_csv(current_path, index=False)
    print(f"Tracked line movement snapshot at {history_path}")
    print(f"Updated current movement summary at {current_path}")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch game lines from The Odds API")
    parser.add_argument("--api-key", help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--sport", default=DEFAULT_SPORT, help="Odds API sport key, e.g. basketball_nba or basketball_wnba")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS, help="Comma-separated bookmaker keys, e.g. draftkings,fanduel")
    parser.add_argument("--regions", default=DEFAULT_REGIONS, help="Comma-separated region keys, e.g. us,us2. Included for API compatibility even when bookmakers are specified.")
    parser.add_argument("--days", type=int, default=5, help="How many days ahead of events to include")
    parser.add_argument("--output", help="Primary output CSV path")
    parser.add_argument("--schedules-output", help="Optional schedule fallback output CSV path")
    parser.add_argument("--schedule-alias-output", help="Canonical schedule CSV path to keep in sync with fresh game lines")
    parser.add_argument("--skip-line-movement", action="store_true", help="Do not append this fetch to line movement tracking files.")
    parser.add_argument("--expected-cost", type=int, default=None,
                        help="Documented expected credit cost; the fetch fails if the actual cost exceeds it (recovery safety).")
    parser.add_argument("--allow-collapse", action="store_true",
                        help="Explicit override to allow an unusually small row count vs the last valid artifact.")
    # Single NBA publisher (services/nba_lines_publisher.py). Ignored for sports that are not event-aware.
    parser.add_argument("--caller", default="fetch_game_lines_cli",
                        help="NBA only: who is publishing (recorded in the publisher receipt).")
    parser.add_argument("--allow-reuse", action="store_true",
                        help="NBA only: reuse a receipt-verified publish from the last "
                             "REUSE_WINDOW_MINUTES instead of paying for another fetch.")
    parser.add_argument("--lock-wait-seconds", type=float, default=0.0,
                        help="NBA only: bounded wait for the shared publisher lock before SKIPPED_LOCKED.")
    parser.add_argument("--no-fetch-after-lock", action="store_true",
                        help="NBA only (with --allow-reuse): after WAITING for another publisher, do not fetch "
                             "if no valid fresh publish exists -- record NO_FRESH_AFTER_LOCK (exit 1) instead.")
    return parser.parse_args(argv)


def _output_paths(args, sport: str) -> dict:
    defaults = SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])
    return {
        "odds": Path(args.output).expanduser().resolve() if args.output else defaults["odds"].resolve(),
        "schedules": Path(args.schedules_output).expanduser().resolve() if args.schedules_output else defaults["schedules"].resolve(),
        "schedule_alias": Path(args.schedule_alias_output).expanduser().resolve() if args.schedule_alias_output else defaults["schedule_alias"].resolve(),
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    sport = str(args.sport or DEFAULT_SPORT).strip().lower()
    if sport in EVENT_AWARE_GAME_LINES_SPORTS:
        # Every NBA publish goes through the ONE publisher: shared lock before any paid request, optional
        # receipt-verified reuse, then the same validation + atomic publish (run_fetch).
        from services import nba_lines_publisher
        return nba_lines_publisher.publish(
            args, run_fetch=run_fetch, base_dir=BASE_DIR, outputs=_output_paths(args, sport),
            caller=str(args.caller or "fetch_game_lines_cli"), allow_reuse=bool(args.allow_reuse),
            lock_wait_seconds=float(args.lock_wait_seconds or 0.0),
            fetch_after_contention=not bool(args.no_fetch_after_lock))
    return run_fetch(args)


def run_fetch(args) -> int:
    sport = str(args.sport or DEFAULT_SPORT).strip().lower()
    if sport in EVENT_AWARE_GAME_LINES_SPORTS:
        from services import nba_lines_publisher
        if not nba_lines_publisher.lock_is_held():
            # Defense in depth: an event-aware fetch outside the publisher would be a second, unlocked
            # publish path. Refuse before any paid request or write.
            print("REFUSED: NBA game lines must be fetched through services.nba_lines_publisher "
                  "(shared lock not held). No request made, nothing written.")
            return 1
    api_key = get_api_key(args.api_key)
    paths = _output_paths(args, sport)
    output_path, schedules_output_path, schedule_alias_output_path = (
        paths["odds"], paths["schedules"], paths["schedule_alias"])

    print("=" * 60)
    print("BANKROLL KINGS - Fetch Game Lines")
    print("=" * 60)
    print(f"Sport: {sport}")
    print(f"Bookmakers: {args.bookmakers}")
    print(f"Regions: {args.regions}")
    markets = SPORT_DEFAULT_MARKETS.get(sport, SPORT_DEFAULT_MARKETS[DEFAULT_SPORT])
    print(f"Markets: {', '.join(markets)}")
    print(f"Days ahead: {args.days}")
    print()

    run_id = uuid.uuid4().hex
    fetch_start = datetime.now(timezone.utc).isoformat(timespec="seconds")
    event_spec = _event_spec_for(sport)
    requested_books = [b.strip() for b in str(args.bookmakers or "").split(",") if b.strip()]
    outputs = {"odds": output_path, "schedules": schedules_output_path, "schedule_alias": schedule_alias_output_path}
    sha_before = {k: _sha256_file(p) for k, p in outputs.items()}

    all_rows: list[dict] = []
    fetch_failed = False
    _FETCH_FACTS.clear()
    # Governed no-game decision (docs/game_lines_event_contract.md "Governed no-game result"): consult the
    # independent schedule authority BEFORE any paid call. No authoritative source exists (audit in
    # services/nba_schedule_authority.py), so the verdict is SCHEDULE_UNAVAILABLE and the provider is
    # always asked; an empty answer is then classified from this verdict, never assumed to be a no-game day.
    schedule_verdict = None
    if event_spec is not None:
        from services.nba_schedule_authority import schedule_verdict as _schedule_verdict
        schedule_verdict = _schedule_verdict()
    try:
        all_rows = fetch_odds_rows(api_key, sport, args.bookmakers, markets, args.regions, args.days)
        print(f"Loaded {len(all_rows)} bookmaker rows from the standard /odds endpoint")
    except Exception as exc:
        print(f"ERROR: {exc}")
        fetch_failed = True

    def finish(outcome: str, exit_code: int, vreceipt=None, errors=(), published_rows: int = 0) -> int:
        """Write the receipt for THIS run (every exit path) and return the exit code."""
        _write_lines_receipt(sport, {
            "run_id": run_id,
            "sport": sport,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fetch_start": fetch_start,
            "fetch_end": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "contract": (vreceipt or {}).get("contract_version") or (
                "game_lines_event_v1" if event_spec is not None else "GAME_LINES_SPEC whole-file"),
            "requested_bookmakers": requested_books,
            "markets": list(markets),
            "days": args.days,
            "provider_fetch_failed": bool(fetch_failed),
            "events_returned": _FETCH_FACTS.get("events_returned"),
            "raw_bookmaker_rows": len(all_rows),
            "outcome": outcome,
            "exit_code": int(exit_code),
            "published": outcome == LINES_UPDATED,
            "published_rows": int(published_rows) if outcome == LINES_UPDATED else 0,
            "validation_errors": [str(e) for e in list(errors)[:12]],
            "validation": vreceipt,
            "schedule_verdict": schedule_verdict,
            "outputs": {k: {"path": str(p.name), "sha256_before": sha_before[k], "sha256_after": _sha256_file(p)}
                        for k, p in outputs.items()},
        })
        return exit_code

    # Per-request quota receipt (incident 2026-10-23): prove the fetch cost from the response usage
    # headers; FAIL the receipt rather than guess if the provider omitted them.
    cost_ok, _receipt = _QUOTA.print_receipt(
        endpoint_family="game_lines /events + /odds", sport=sport, markets=markets,
        expected_cost=getattr(args, "expected_cost", None),
        status="HTTP 200" if not fetch_failed else "fetch error",
        ledger_base_dir=BASE_DIR)

    df = build_dataframe(all_rows, include_event_utc=event_spec is not None)
    if fetch_failed and df.empty:
        print()
        print("No new game-line rows were fetched. Preserving existing CSV files instead of overwriting with an empty dataset.")
        return finish(LINES_PROVIDER_ERROR, 1, errors=["provider fetch failed"])
    if not cost_ok:
        print("Cost receipt FAILED (missing usage headers or cost over budget). Preserving existing files.")
        return finish(LINES_COST_RECEIPT_FAILED, 1, errors=["cost receipt failed"])
    if not fetch_failed and _FETCH_FACTS.get("events_returned") == 0 and event_spec is not None:
        # Event-aware (NBA): an empty provider answer is NOT proof of a no-game day. Without a fresh
        # authoritative independent schedule it is SCHEDULE_UNAVAILABLE (alerting, fail closed); when the
        # schedule expected games it is a validation failure. Existing files preserved either way.
        from services.nba_schedule_authority import zero_event_outcome
        outcome, reason = zero_event_outcome(schedule_verdict)
        print()
        print(f"Provider returned zero events and no authoritative schedule confirms a no-game day "
              f"({outcome}: {reason}). Preserving existing files; this is NOT a benign skip.")
        return finish(outcome, 1, errors=[f"provider returned zero events ({reason})"])
    if not fetch_failed and _FETCH_FACTS.get("events_returned") == 0:
        # The provider ANSWERED with zero events in the window (off-season / between slates). Proven benign
        # non-publish: nothing to add, existing files preserved. Exit code unchanged (1) for every caller;
        # the receipt is what distinguishes this from a failure.
        print()
        print("Provider returned zero events in the fetch window. Preserving existing files (NO_ACTIVE_EVENTS).")
        return finish(LINES_NO_ACTIVE_EVENTS, 1, errors=["provider returned zero events"])

    # Strong semantic validation on the TEMP frame + atomic replace. A structurally-wrong fetch (bad
    # schema, non-finite lines, timestamp regression, conflicting duplicates, wrong-sport path, implausible
    # collapse) must NOT replace last-known-good (incident 2026-10-23).
    from services.atomic_csv import atomic_write_csv_set, CsvValidationError
    from services.feed_validation import GAME_LINES_SPEC, validate_feed, validate_game_lines_event_slate
    prior, prior_unreadable = None, False
    if output_path.exists():
        try:
            prior = pd.read_csv(output_path)
        except Exception:
            prior, prior_unreadable = None, True
    vreceipt = None
    if event_spec is not None:
        # Event-aware game-lines contract (docs/game_lines_event_contract.md): last night's PLAYED games in
        # the prior must not make today's current slate read as a collapse. Started events are removed from
        # both sides and never published; a still-future published event that vanishes fails closed.
        if getattr(args, "allow_collapse", False):
            print("[INFO] --allow-collapse is ignored for event-aware game-lines validation.")
        ok, errs, vreceipt, publish_df = validate_game_lines_event_slate(
            df, event_spec, prior_df=prior, path=output_path, sport_tokens=_sport_tokens(sport),
            provider_errors=1 if fetch_failed else 0, requested_books=requested_books,
            prior_unreadable=prior_unreadable)
        print("---- VALIDATION RECEIPT (event-aware game lines) ----")
        for k in ("contract_version", "now_utc", "provider_errors", "prior_rows", "prior_kickoff_basis",
                  "derived_legacy_kickoff_rows", "prior_kickoff_invalid", "candidate_rows",
                  "completed_events_removed", "completed_rows_removed", "started_candidate_rows_removed",
                  "identity_invalid_rows", "rows_dropped_by_reason", "market_quotes_nulled_by_reason",
                  "prior_active_events", "overlapping_events_retained", "new_events_added",
                  "prior_active_events_absent", "vanished_events", "coverage_status", "coverage_degraded_events",
                  "sparse_new_events", "final_published_rows", "final_published_events", "decision",
                  "reason_code"):
            print(f"  {k}: {vreceipt.get(k)}")
        if ok:
            df = publish_df
    else:
        ok, errs = validate_feed(df, GAME_LINES_SPEC, prior_df=prior, path=output_path,
                                 sport_tokens=_sport_tokens(sport), allow_collapse=bool(getattr(args, "allow_collapse", False)))
    if not ok:
        print("Strong validation FAILED, preserving existing files:")
        for e in errs:
            print(f"  - {e}")
        outcome = (LINES_PROVIDER_ERROR if (vreceipt or {}).get("reason_code") == "PROVIDER_ERROR"
                   else LINES_VALIDATION_FAILED)
        return finish(outcome, 1, vreceipt, errors=errs)
    try:
        # The three artifacts publish as one unit: every temp is staged + checked before ANY replace, so a
        # failure leaves all three byte-identical.
        atomic_write_csv_set([
            (df, output_path, {"index": False, "required_cols": ["Away", "Home"]}),
            (df, schedules_output_path, {"index": False, "required_cols": ["Away", "Home"]}),
            (build_schedule_alias(df), schedule_alias_output_path, {"index": False}),
        ])
    except CsvValidationError as exc:
        print(f"Atomic publish failed, preserving existing files: {exc}")
        return finish(LINES_PUBLISH_FAILED, 1, vreceipt, errors=[str(exc)])
    if not args.skip_line_movement:
        append_line_movement_snapshot(df, sport)

    print()
    print(f"Saved {len(df)} rows to {output_path}")
    print(f"Mirrored {len(df)} rows to {schedules_output_path}")
    print(f"Updated schedule alias at {schedule_alias_output_path}")
    return finish(LINES_UPDATED, 0, vreceipt, published_rows=len(df))


if __name__ == "__main__":
    raise SystemExit(main())
