"""Import a licensed season-long odds feed into Bankroll Kings.

Accepted input is CSV or JSON containing the normalized columns documented in
docs/season_markets_setup.md. The source may be a local export or an authenticated
provider endpoint configured with SEASON_MARKETS_FEED_URL and optional
SEASON_MARKETS_FEED_TOKEN.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from services.season_markets import MARKET_COLUMNS, SPORTS


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "data" / "season_markets"
CURRENT = OUT_DIR / "Season_Markets.csv"
HISTORY = OUT_DIR / "Season_Market_History.csv"

ALIASES = {
    "sport": "Sport", "league": "Sport", "season": "Season",
    "entity_type": "EntityType", "type": "EntityType",
    "entity": "Entity", "name": "Entity", "player": "Entity",
    "team": "Team", "market": "Market", "stat": "Market",
    "line": "Line", "point": "Line", "over_odds": "OverOdds",
    "under_odds": "UnderOdds", "book": "Book", "sportsbook": "Book",
    "source": "Source", "updated_at": "SourceUpdatedAt",
    "snapshot_at": "SnapshotAt",
}


def _load_input(path: str = "") -> pd.DataFrame:
    if path:
        source = Path(path)
        if source.suffix.lower() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
            return pd.json_normalize(payload.get("data", payload) if isinstance(payload, dict) else payload)
        return pd.read_csv(source, low_memory=False)

    url = os.getenv("SEASON_MARKETS_FEED_URL", "").strip()
    if not url:
        raise RuntimeError("Provide --input or configure SEASON_MARKETS_FEED_URL.")
    headers = {}
    token = os.getenv("SEASON_MARKETS_FEED_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type:
        payload = response.json()
        return pd.json_normalize(payload.get("data", payload) if isinstance(payload, dict) else payload)
    return pd.read_csv(io.StringIO(response.text), low_memory=False)


def normalize(frame: pd.DataFrame, default_source: str = "Licensed feed") -> pd.DataFrame:
    renamed = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_")
        if key in ALIASES:
            renamed[column] = ALIASES[key]
    frame = frame.rename(columns=renamed).copy()
    for column in MARKET_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    frame["SnapshotAt"] = frame["SnapshotAt"].fillna(now).replace("", now)
    frame["Sport"] = frame["Sport"].fillna("").astype(str).str.strip().str.upper()
    frame["Season"] = frame["Season"].fillna("").astype(str).str.strip()
    frame["EntityType"] = frame["EntityType"].fillna("").astype(str).str.strip().str.lower()
    frame["Entity"] = frame["Entity"].fillna("").astype(str).str.strip()
    frame["Team"] = frame["Team"].fillna("").astype(str).str.strip()
    frame["Market"] = frame["Market"].fillna("").astype(str).str.strip()
    frame["Book"] = frame["Book"].fillna("").astype(str).str.strip()
    frame["Source"] = frame["Source"].fillna(default_source).replace("", default_source)
    frame["SourceUpdatedAt"] = frame["SourceUpdatedAt"].fillna(frame["SnapshotAt"])
    for column in ("Line", "OverOdds", "UnderOdds"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    valid = frame[
        frame["Sport"].isin(SPORTS)
        & frame["EntityType"].isin(("team", "player"))
        & frame["Entity"].ne("")
        & frame["Market"].ne("")
        & frame["Line"].notna()
    ][MARKET_COLUMNS].copy()
    if valid.empty:
        raise ValueError("Input produced zero valid season-market rows after normalization.")
    return valid.drop_duplicates(
        subset=["Sport", "Season", "EntityType", "Entity", "Team", "Market", "Book"],
        keep="last",
    )


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh cross-sport season-long market lines.")
    parser.add_argument("--input", default="", help="Provider-normalized CSV or JSON export.")
    parser.add_argument("--source", default="Licensed feed", help="Source label when input omits one.")
    args = parser.parse_args()

    if not args.input and not os.getenv("SEASON_MARKETS_FEED_URL", "").strip():
        print("Season markets skipped: SEASON_MARKETS_FEED_URL is not configured.")
        return 0

    current = normalize(_load_input(args.input), default_source=args.source)
    _write(current, CURRENT)

    if HISTORY.exists() and HISTORY.stat().st_size:
        try:
            history = pd.read_csv(HISTORY, low_memory=False)
        except pd.errors.EmptyDataError:
            history = pd.DataFrame(columns=MARKET_COLUMNS)
    else:
        history = pd.DataFrame(columns=MARKET_COLUMNS)
    history = pd.concat([history, current], ignore_index=True)
    history = history.drop_duplicates(
        subset=["SnapshotAt", "Sport", "Season", "EntityType", "Entity", "Team", "Market", "Book"],
        keep="last",
    )
    _write(history[MARKET_COLUMNS], HISTORY)

    print(f"Season markets refreshed: {len(current)} current rows across {current['Sport'].nunique()} sport(s).")
    print(f"Books: {current['Book'].replace('', pd.NA).dropna().nunique()} | History rows: {len(history)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
