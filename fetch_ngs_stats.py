"""
Bankroll Kings - Fetch NFL Next Gen Stats
=========================================

Pulls public statboard data from nextgenstats.nfl.com for passing, receiving,
and rushing. The script uses the same same-origin JSON endpoints used by the
Next Gen Stats website and writes normalized CSV files under data/ngs/.

Examples:
    py -3 fetch_ngs_stats.py --season 2025 --aggregate
    py -3 fetch_ngs_stats.py --season 2025 --season-types REG,POST --weekly --aggregate
    py -3 fetch_ngs_stats.py --season 2025 --categories passing,receiving --weeks 1,2,3
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "ngs"
BASE_URL = "https://nextgenstats.nfl.com/api/statboard"
VALID_CATEGORIES = {"passing", "receiving", "rushing"}
DEFAULT_CATEGORIES = ["passing", "receiving", "rushing"]
DEFAULT_SEASON_TYPE_WEEKS = {
    "REG": list(range(1, 19)),
    "POST": list(range(19, 24)),
}


def _parse_csv(raw: str | None, default: Iterable[str]) -> list[str]:
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_weeks(raw: str | None, season_type: str) -> list[int]:
    if not raw:
        return DEFAULT_SEASON_TYPE_WEEKS.get(season_type.upper(), [])
    weeks: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            weeks.extend(range(int(start), int(end) + 1))
        else:
            weeks.append(int(item))
    return sorted(set(weeks))


def _category_title(category: str) -> str:
    return category.strip().lower().capitalize()


def _headers(category: str, season: int, season_type: str, week: int | None = None) -> dict[str, str]:
    path = f"/stats/{category}/{season}/{season_type}"
    if week is not None:
        path = f"{path}/{week}"
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "X-Override-Env": "false",
        "Referer": f"https://nextgenstats.nfl.com{path}",
    }


def fetch_statboard(category: str, season: int, season_type: str, week: int | None = None) -> dict:
    params: dict[str, str | int] = {
        "season": season,
        "seasonType": season_type.upper(),
    }
    if week is not None:
        params["week"] = int(week)
    response = requests.get(
        f"{BASE_URL}/{category}",
        params=params,
        headers=_headers(category, season, season_type, week),
        timeout=45,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{category} {season} {season_type} week={week or 'season'} returned {response.status_code}: {response.text[:300]}")
    return response.json()


def normalize_payload(payload: dict, category: str, fetched_at: str) -> pd.DataFrame:
    rows = payload.get("stats") or []
    df = pd.json_normalize(rows)
    if df.empty:
        df = pd.DataFrame()
    df.insert(0, "Category", category)
    df.insert(1, "Season", payload.get("season", ""))
    df.insert(2, "SeasonType", payload.get("seasonType", ""))
    df.insert(3, "Week", payload.get("week", ""))
    df.insert(4, "Threshold", payload.get("threshold", ""))
    df.insert(5, "Filter", payload.get("filter", ""))
    df.insert(6, "FetchedAt", fetched_at)
    return df


def save_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def fetch_aggregate(category: str, season: int, season_type: str, raw_json: bool, delay: float) -> pd.DataFrame:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = fetch_statboard(category, season, season_type)
    df = normalize_payload(payload, category, fetched_at)
    title = _category_title(category)
    csv_path = OUTPUT_DIR / f"NGS_{title}_{season}_{season_type.upper()}.csv"
    write_csv(df, csv_path)
    if raw_json:
        save_json(payload, OUTPUT_DIR / "raw" / f"ngs_{category}_{season}_{season_type.upper()}.json")
    print(f"[PASS] {category} {season} {season_type.upper()} aggregate rows={len(df)} -> {csv_path}")
    if delay > 0:
        time.sleep(delay)
    return df


def fetch_weekly(category: str, season: int, season_type: str, weeks: list[int], raw_json: bool, delay: float) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for week in weeks:
        fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = fetch_statboard(category, season, season_type, week=week)
        df = normalize_payload(payload, category, fetched_at)
        frames.append(df)
        title = _category_title(category)
        csv_path = OUTPUT_DIR / "weekly" / f"NGS_{title}_{season}_{season_type.upper()}_Week{week:02d}.csv"
        write_csv(df, csv_path)
        if raw_json:
            save_json(payload, OUTPUT_DIR / "raw" / f"ngs_{category}_{season}_{season_type.upper()}_week{week:02d}.json")
        print(f"[PASS] {category} {season} {season_type.upper()} week={week} rows={len(df)} -> {csv_path}")
        if delay > 0:
            time.sleep(delay)

    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    title = _category_title(category)
    combined_path = OUTPUT_DIR / f"NGS_{title}_{season}_{season_type.upper()}_Weekly.csv"
    write_csv(combined, combined_path)
    print(f"[PASS] {category} {season} {season_type.upper()} weekly combined rows={len(combined)} -> {combined_path}")
    return combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch NFL Next Gen Stats statboards")
    parser.add_argument("--season", type=int, default=2025, help="NFL season to fetch")
    parser.add_argument("--season-types", default="REG", help="Comma-separated season types, usually REG,POST")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="Comma-separated categories: passing,receiving,rushing")
    parser.add_argument("--weeks", help="Comma-separated weeks or ranges. Defaults to 1-18 for REG and 19-23 for POST when --weekly is set.")
    parser.add_argument("--aggregate", action="store_true", help="Fetch full-season aggregate files")
    parser.add_argument("--weekly", action="store_true", help="Fetch numeric week files and combined weekly files")
    parser.add_argument("--raw-json", action="store_true", help="Also save raw JSON responses under data/ngs/raw")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait between requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    categories = [item.lower() for item in _parse_csv(args.categories, DEFAULT_CATEGORIES)]
    invalid = sorted(set(categories) - VALID_CATEGORIES)
    if invalid:
        raise ValueError(f"Unsupported NGS categories: {', '.join(invalid)}")
    season_types = [item.upper() for item in _parse_csv(args.season_types, ["REG"])]
    if not args.aggregate and not args.weekly:
        args.aggregate = True

    print("=" * 60)
    print("BANKROLL KINGS - NFL NEXT GEN STATS FETCH")
    print("=" * 60)
    print(f"Season: {args.season}")
    print(f"Season types: {', '.join(season_types)}")
    print(f"Categories: {', '.join(categories)}")
    print(f"Aggregate: {args.aggregate}")
    print(f"Weekly: {args.weekly}")
    print()

    for season_type in season_types:
        weeks = _parse_weeks(args.weeks, season_type)
        for category in categories:
            if args.aggregate:
                fetch_aggregate(category, args.season, season_type, args.raw_json, args.delay)
            if args.weekly:
                fetch_weekly(category, args.season, season_type, weeks, args.raw_json, args.delay)
    print("NGS fetch completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
