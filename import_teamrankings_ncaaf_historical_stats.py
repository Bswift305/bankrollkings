from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
BASE_URL = "https://www.teamrankings.com"
INDEX_URL = f"{BASE_URL}/ncf/team-stats/"
LONG_OUTPUT = BASE_DIR / "data" / "historical" / "NCAAF_TeamRankings_2025_TeamStats_Long.csv"
WIDE_OUTPUT = BASE_DIR / "data" / "historical" / "NCAAF_TeamRankings_2025_TeamStats.csv"
SOURCE_LABEL = "teamrankings_historical_research"


DEFAULT_STAT_SLUGS = [
    "points-per-game",
    "average-scoring-margin",
    "yards-per-point",
    "points-per-play",
    "yards-per-game",
    "yards-per-play",
    "rushing-yards-per-game",
    "passing-yards-per-game",
    "third-down-conversion-pct",
    "red-zone-scoring-pct",
    "opponent-points-per-game",
    "opponent-average-scoring-margin",
    "opponent-yards-per-game",
    "opponent-yards-per-play",
    "opponent-rushing-yards-per-game",
    "opponent-passing-yards-per-game",
    "opponent-third-down-conversion-pct",
    "opponent-red-zone-scoring-pct",
    "turnover-margin-per-game",
    "average-time-of-possession-net-of-ot",
]


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {key: value or "" for key, value in attrs}
        self._href = attrs_dict.get("href", "")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = ""
            self._text = []


class TeamRankingsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.headers: list[str] = []
        self.rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._cell_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table" and not self.in_table:
            attrs_dict = {key: value or "" for key, value in attrs}
            if "tr-table" in attrs_dict.get("class", ""):
                self.in_table = True
        if not self.in_table:
            return
        if tag == "tr":
            self.in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self._cell_tag = tag
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.in_table:
            return
        if tag in {"td", "th"} and self.in_cell:
            text = " ".join(" ".join(self._current_cell).split())
            self._current_row.append(text)
            self.in_cell = False
            self._current_cell = []
        elif tag == "tr" and self.in_row:
            if self._current_row:
                if not self.headers:
                    self.headers = self._current_row
                else:
                    self.rows.append(self._current_row)
            self.in_row = False
            self._current_row = []
        elif tag == "table":
            self.in_table = False


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "BankrollKingsHistoricalResearch/1.0"})
    with urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="ignore")


def discover_stat_links() -> list[tuple[str, str]]:
    html = fetch_html(INDEX_URL)
    parser = LinkParser()
    parser.feed(html)
    links = []
    seen = set()
    for href, text in parser.links:
        if "/college-football/stat/" not in href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen:
            continue
        seen.add(slug)
        links.append((slug, text or slug.replace("-", " ").title()))
    return links


def _clean_metric_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_")


def _to_number(value: str):
    text = str(value or "").strip().replace("%", "").replace(",", "")
    if text in {"", "--", "-", "N/A"}:
        return pd.NA
    try:
        return float(text)
    except ValueError:
        return pd.NA


def parse_stat_page(slug: str, stat_name: str, season: int) -> pd.DataFrame:
    url = f"{BASE_URL}/college-football/stat/{slug}"
    html = fetch_html(url)
    parser = TeamRankingsTableParser()
    parser.feed(html)
    if not parser.headers or not parser.rows:
        return pd.DataFrame()
    rows = []
    for raw_row in parser.rows:
        if len(raw_row) < len(parser.headers):
            raw_row = raw_row + [""] * (len(parser.headers) - len(raw_row))
        row = dict(zip(parser.headers, raw_row))
        team = str(row.get("Team") or "").strip()
        if not team:
            continue
        rows.append({
            "Season": season,
            "Team": team,
            "StatSlug": slug,
            "StatName": stat_name,
            "Rank": _to_number(row.get("Rank")),
            "SeasonValue": _to_number(row.get(str(season))),
            "Last3Value": _to_number(row.get("Last 3")),
            "Last1Value": _to_number(row.get("Last 1")),
            "HomeValue": _to_number(row.get("Home")),
            "AwayValue": _to_number(row.get("Away")),
            "PriorSeasonValue": _to_number(row.get(str(season - 1))),
            "Source": SOURCE_LABEL,
            "IsBackfill": True,
            "FetchedAt": datetime.now().isoformat(timespec="seconds"),
            "SourceUrl": url,
        })
    return pd.DataFrame(rows)


def build_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    if long_df.empty:
        return pd.DataFrame()
    frames = []
    value_columns = ["Rank", "SeasonValue", "HomeValue", "AwayValue", "PriorSeasonValue"]
    for value_col in value_columns:
        pivot = long_df.pivot_table(
            index=["Season", "Team"],
            columns="StatSlug",
            values=value_col,
            aggfunc="first",
        )
        pivot.columns = [f"{_clean_metric_name(col)}_{value_col}" for col in pivot.columns]
        frames.append(pivot)
    wide = pd.concat(frames, axis=1).reset_index()
    wide["Source"] = SOURCE_LABEL
    wide["IsBackfill"] = True
    return wide


def main() -> int:
    parser = argparse.ArgumentParser(description="Import historical NCAAF team stats from TeamRankings.")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--all", action="store_true", help="Import every stat link on the TeamRankings NCAAF team-stats index.")
    parser.add_argument("--slugs", default="", help="Comma-separated TeamRankings stat slugs. Overrides the default curated list.")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between stat page requests.")
    parser.add_argument("--long-output", default=str(LONG_OUTPUT))
    parser.add_argument("--wide-output", default=str(WIDE_OUTPUT))
    args = parser.parse_args()

    discovered = discover_stat_links()
    discovered_map = {slug: name for slug, name in discovered}
    if args.all:
        selected = discovered
    elif args.slugs.strip():
        slugs = [item.strip() for item in args.slugs.split(",") if item.strip()]
        selected = [(slug, discovered_map.get(slug, slug.replace("-", " ").title())) for slug in slugs]
    else:
        selected = [(slug, discovered_map.get(slug, slug.replace("-", " ").title())) for slug in DEFAULT_STAT_SLUGS]

    frames = []
    for index, (slug, stat_name) in enumerate(selected, start=1):
        frame = parse_stat_page(slug, stat_name, args.season)
        frames.append(frame)
        print(f"[{index}/{len(selected)}] {slug}: {len(frame)} rows")
        if index < len(selected) and args.delay > 0:
            time.sleep(args.delay)

    long_df = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    wide_df = build_wide(long_df)
    long_path = Path(args.long_output)
    wide_path = Path(args.wide_output)
    long_path.parent.mkdir(parents=True, exist_ok=True)
    wide_path.parent.mkdir(parents=True, exist_ok=True)
    long_df.to_csv(long_path, index=False, quoting=csv.QUOTE_MINIMAL)
    wide_df.to_csv(wide_path, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"Wrote {len(long_df)} long rows to {long_path}")
    print(f"Wrote {len(wide_df)} team rows to {wide_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
