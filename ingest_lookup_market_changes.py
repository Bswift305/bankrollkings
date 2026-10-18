#!/usr/bin/env python3
"""Ingest cleared Odds API NFL player-prop snapshots into the dark Lookup store.

The saved props CSV does not retain provider player ids or timezone offsets.  This
adapter therefore resolves players through the stable current-roster ``PlayerID``
and preserves ``LastUpdated`` as raw, timezone-unknown lineage.  Ambiguous alternate
lines, unresolved identities, and incomplete quotes are rejected rather than merged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from services.lookup_changes import LookupChangeStore, ObservedChangeInput, utc_now


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROPS = BASE_DIR / "data" / "props" / "NFL_Props.csv"
DEFAULT_ROSTER = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clean_number(value: Any) -> int | float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    number = float(parsed)
    return int(number) if number.is_integer() else number


def _roster_ids(path: Path) -> tuple[dict[str, str], set[str]]:
    roster = pd.read_csv(path, dtype={"PlayerID": "string"})
    required = {"PlayerID", "Player"}
    if roster.empty or not required.issubset(roster.columns):
        raise ValueError("current NFL roster is empty or missing PlayerID/Player")
    candidates: dict[str, set[str]] = {}
    for _, row in roster.iterrows():
        key = _name_key(row.get("Player"))
        player_id = str(row.get("PlayerID") or "").strip()
        if key and player_id and player_id.lower() not in {"nan", "none", "<na>"}:
            candidates.setdefault(key, set()).add(player_id)
    ambiguous = {key for key, ids in candidates.items() if len(ids) != 1}
    return {key: next(iter(ids)) for key, ids in candidates.items() if len(ids) == 1}, ambiguous


def _observation_id(row: pd.Series, player_id: str) -> str:
    payload = {
        "player_id": player_id,
        "market": str(row.get("MarketKey") or row.get("Stat") or "").strip(),
        "game": str(row.get("Game") or "").strip(),
        "book": str(row.get("Book") or "").strip(),
        "line": _clean_number(row.get("Line")),
        "over": _clean_number(row.get("OverOdds")),
        "under": _clean_number(row.get("UnderOdds")),
        "book_updated_raw": str(row.get("LastUpdated") or "").strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ingest_file(
    store: LookupChangeStore,
    props_path: Path,
    roster_path: Path,
    *,
    captured_at: str | None = None,
) -> dict[str, int]:
    props = pd.read_csv(props_path)
    required = {"Player", "Stat", "Line", "Game", "Book", "OverOdds", "UnderOdds"}
    if props.empty or not required.issubset(props.columns):
        raise ValueError("NFL props snapshot is empty or missing canonical market columns")
    ids, ambiguous_names = _roster_ids(roster_path)
    captured = captured_at or utc_now()
    report: Counter[str] = Counter()

    working = props.copy()
    working["_player_key"] = working["Player"].map(_name_key)
    working["_market"] = working.get("MarketKey", working["Stat"]).fillna(working["Stat"]).astype(str)
    working["_book"] = working["Book"].fillna("").astype(str).str.strip()
    # Multiple simultaneous lines for one player/book/market are alternate quotes.  The current
    # snapshot does not label a primary line, so no single stream may be chosen honestly.
    group_cols = ["_player_key", "_market", "_book", "Game"]
    ambiguous_quote = working.groupby(group_cols, dropna=False)["Line"].nunique(dropna=True)
    ambiguous_streams = set(ambiguous_quote[ambiguous_quote > 1].index.tolist())

    for _, row in working.iterrows():
        key = row["_player_key"]
        group_key = tuple(row[col] for col in group_cols)
        if not key or key in ambiguous_names or key not in ids:
            report["unresolved_identity"] += 1
            continue
        if group_key in ambiguous_streams:
            report["ambiguous_alt_line"] += 1
            continue
        line = _clean_number(row.get("Line"))
        over = _clean_number(row.get("OverOdds"))
        under = _clean_number(row.get("UnderOdds"))
        if line is None or (over is None and under is None):
            report["incomplete_quote"] += 1
            continue
        source_updated_raw = str(row.get("LastUpdated") or "").strip()
        if not source_updated_raw or source_updated_raw.lower() in {"nan", "none", "null", "<na>"}:
            # Without the provider update value, a quote that moves away and later returns to the
            # same price cannot be distinguished from re-ingesting the original observation.
            report["missing_source_update"] += 1
            continue
        book = str(row.get("Book") or "").strip()
        game = str(row.get("Game") or "").strip()
        market = str(row.get("MarketKey") or row.get("Stat") or "").strip()
        if not book or not game or not market:
            report["incomplete_identity"] += 1
            continue
        player_id = ids[key]
        field = f"market_quote:nfl:{market}:{book.lower()}:{game.lower()}"
        result = store.ingest_observed(ObservedChangeInput(
            entity_type="player",
            entity_id=f"nfl:espn:{player_id}",
            field=field,
            current_value={"line": line, "over_price": over, "under_price": under,
                           "book": book, "game": game, "stat": str(row.get("Stat") or "")},
            dataset="odds_api_player_props",
            source="The Odds API",
            source_observation_id=_observation_id(row, player_id),
            first_captured_at=captured,
            # The persisted feed discarded the provider offset.  Keep it as raw lineage only.
            source_updated_at=None,
            source_updated_raw=source_updated_raw,
            reliability_state="confirmed",
            market_relative_timing="unknown",
            explanation="The captured sportsbook market quote changed.",
        ))
        report[result["status"]] += 1
    report["rows_seen"] = len(working)
    return dict(sorted(report.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--props", type=Path, default=DEFAULT_PROPS)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()
    try:
        with LookupChangeStore(args.db) as store:
            report = ingest_file(store, args.props, args.roster)
            totals = store.counts()
    except Exception as exc:
        print(f"[lookup-ingest] FAIL: {type(exc).__name__}: {exc}")
        return 1
    print("[lookup-ingest] " + json.dumps({"ingest": report, "store": totals}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
