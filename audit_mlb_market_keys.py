from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError

import pandas as pd

from fetch_player_props import (
    BOOKMAKER_TITLES,
    MARKET_STAT_MAP,
    SPORT_REQUIRED_MARKETS,
    build_url,
    fetch_events,
    get_api_key,
    get_json,
)
from services.env_loader import load_local_env


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "MLB_MarketKey_Audit.csv"
SPORT = "baseball_mlb"
DEFAULT_BOOKMAKERS = "draftkings,williamhill_us,fanduel,betmgm,betrivers,fanatics"

ALTERNATE_KEYS = {
    "batter_home_runs": ["player_home_runs", "home_runs"],
    "batter_strikeouts": ["batter_strikeouts_thrown", "player_strikeouts", "strikeouts"],
    "batter_triples": ["player_triples", "triples"],
}


def _audit_key(api_key: str, event: dict, key: str, bookmakers: str) -> dict:
    url = build_url(
        f"/v4/sports/{SPORT}/events/{event['id']}/odds",
        apiKey=api_key,
        regions="us",
        bookmakers=bookmakers,
        markets=key,
        oddsFormat="american",
        dateFormat="iso",
    )
    try:
        payload = get_json(url)
    except HTTPError as exc:
        if exc.code == 422:
            return {"valid": False, "books": 0, "outcomes": 0, "returned": "", "error": "INVALID_KEY_422"}
        return {"valid": False, "books": 0, "outcomes": 0, "returned": "", "error": f"HTTP_{exc.code}"}
    except Exception as exc:
        return {"valid": False, "books": 0, "outcomes": 0, "returned": "", "error": type(exc).__name__}

    returned_keys = []
    outcomes = 0
    books = 0
    for bookmaker in payload.get("bookmakers", []):
        books += 1
        for market in bookmaker.get("markets", []):
            market_key = str(market.get("key") or "").strip()
            if market_key:
                returned_keys.append(market_key)
            outcomes += len(market.get("outcomes", []) or [])
    return {
        "valid": True,
        "books": books,
        "outcomes": outcomes,
        "returned": ",".join(sorted(set(returned_keys))),
        "error": "",
    }


def run_audit(max_events: int = 3, bookmakers: str = DEFAULT_BOOKMAKERS) -> pd.DataFrame:
    load_local_env(BASE_DIR)
    api_key = get_api_key(None)
    events = fetch_events(api_key, SPORT, days=5)[:max_events]
    checked_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    keys = []
    for required in SPORT_REQUIRED_MARKETS.get(SPORT, []):
        keys.append((required, MARKET_STAT_MAP.get(required, required), "REQUIRED", required))
        for alternate in ALTERNATE_KEYS.get(required, []):
            keys.append((alternate, MARKET_STAT_MAP.get(required, required), "ALTERNATE", required))

    rows = []
    for key, stat, key_type, canonical in keys:
        event_results = [_audit_key(api_key, event, key, bookmakers) for event in events]
        valid_seen = any(result["valid"] for result in event_results)
        invalid_seen = any(not result["valid"] and result["error"] == "INVALID_KEY_422" for result in event_results)
        books = sum(int(result["books"]) for result in event_results)
        outcomes = sum(int(result["outcomes"]) for result in event_results)
        returned = sorted({part for result in event_results for part in str(result["returned"]).split(",") if part})
        if valid_seen and outcomes > 0:
            status = "LIVE"
            note = "Valid key returned rows from selected books."
        elif valid_seen:
            status = "VALID_NO_ROWS"
            note = "Valid key, but selected books returned no markets in audited events."
        elif invalid_seen:
            status = "INVALID_KEY"
            note = "Provider rejected this market key."
        else:
            status = "ERROR"
            note = "Audit request failed before key validity could be confirmed."
        rows.append({
            "CheckedAt": checked_at,
            "Sport": SPORT,
            "MarketKey": key,
            "CanonicalKey": canonical,
            "Stat": stat,
            "KeyType": key_type,
            "Status": status,
            "EventsChecked": len(events),
            "BooksReturned": books,
            "OutcomeRows": outcomes,
            "ReturnedMarketKeys": ",".join(returned),
            "Bookmakers": ",".join(BOOKMAKER_TITLES.get(part.strip(), part.strip()) for part in bookmakers.split(",") if part.strip()),
            "Note": note,
        })
    return pd.DataFrame(rows)


def main() -> int:
    audit = run_audit()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(OUTPUT_PATH, index=False)
    print("=" * 60)
    print("BANKROLL KINGS - MLB MARKET KEY AUDIT")
    print("=" * 60)
    print(f"Rows written: {len(audit)}")
    print(f"Output: {OUTPUT_PATH}")
    for _, row in audit[audit["MarketKey"].isin(["batter_home_runs", "batter_strikeouts", "batter_triples"])].iterrows():
        print(f"{row['MarketKey']}: {row['Status']} | outcomes={row['OutcomeRows']} | {row['Note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
