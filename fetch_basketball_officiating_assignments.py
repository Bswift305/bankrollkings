from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTEXT_DIR = DATA_DIR / "context"
SOURCE_URL = "https://official.nba.com/referee-assignments/"

OUTPUT_COLUMNS = [
    "Date",
    "Sport",
    "Away",
    "Home",
    "Official",
    "Crew",
    "ZoneProfile",
    "PaceImpact",
    "ScoringImpact",
    "FoulImpact",
    "Source",
    "AssignmentStatus",
    "ImpactMarkets",
    "ContextNote",
    "LastUpdated",
]

BASKETBALL_IMPACT_MARKETS = "Game Total; Team Total; PRA; PTS; Fouls; Free Throws"
BASKETBALL_CONTEXT_NOTE = "Referee crew foul rate and pace interruption affect possessions, free throws, scoring props, and totals."


def _clean(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return "" if text.lower() in {"nan", "none", "-"} else text


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    if "Date" in df.columns:
        df["Date"] = df["Date"].map(_normalize_date)
    return df[OUTPUT_COLUMNS]


def _strip_html(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean(text)


def _fetch_html() -> str:
    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "BankrollKings/1.0 (+local analytics pipeline)"},
        timeout=25,
    )
    response.raise_for_status()
    return response.text


def _parse_matchup(value: str) -> tuple[str, str]:
    text = _clean(value)
    for sep in (" vs. ", " vs ", " @ ", " at "):
        if sep in text:
            left, right = text.split(sep, 1)
            return _clean(left), _clean(right)
    return "", ""


def _normalize_date(value: str) -> str:
    parsed = pd.to_datetime(_clean(value), errors="coerce")
    if pd.isna(parsed):
        return datetime.now().strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def _rows_from_html(raw_html: str, sport: str, section_title: str) -> list[dict]:
    section_match = re.search(
        rf"<h1[^>]*>\s*{re.escape(section_title)}\s*</h1>.*?<div class=\"entry-meta\">(.*?)</div>.*?<tbody>(.*?)</tbody>",
        raw_html,
        flags=re.I | re.S,
    )
    if not section_match:
        return []
    date_label = _normalize_date(_strip_html(section_match.group(1)))
    tbody = section_match.group(2)
    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, flags=re.I | re.S):
        cells = [_strip_html(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)]
        if len(cells) < 4:
            continue
        away, home = _parse_matchup(cells[0])
        if not away or not home:
            continue
        officials = [cell for cell in cells[1:5] if cell]
        crew = "; ".join(dict.fromkeys(officials))
        primary = officials[0] if officials else ""
        rows.append({
            "Date": date_label,
            "Sport": sport,
            "Away": away,
            "Home": home,
            "Official": primary,
            "Crew": crew,
            "ZoneProfile": "",
            "PaceImpact": "",
            "ScoringImpact": "",
            "FoulImpact": "",
            "Source": "official.nba.com/referee-assignments",
            "AssignmentStatus": "CONFIRMED" if primary else "NEEDS_ASSIGNMENT",
            "ImpactMarkets": BASKETBALL_IMPACT_MARKETS,
            "ContextNote": BASKETBALL_CONTEXT_NOTE,
            "LastUpdated": now,
        })
    return rows


def fetch_basketball_officiating(default_sport: str = "NBA") -> pd.DataFrame:
    rows = []
    raw_html = _fetch_html()
    if default_sport in {"NBA", "ALL"}:
        rows.extend(_rows_from_html(raw_html, "NBA", "NBA Referee Assignments"))
    if default_sport in {"WNBA", "ALL"}:
        rows.extend(_rows_from_html(raw_html, "WNBA", "WNBA Referee Assignments"))
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS).drop_duplicates(
        subset=["Date", "Sport", "Away", "Home", "Official"],
        keep="last",
    )


def main() -> int:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("BANKROLL KINGS - BASKETBALL OFFICIATING FETCH")
    print("=" * 70)
    try:
        assignments = fetch_basketball_officiating("ALL")
    except Exception as exc:
        print(f"Fetch skipped: {type(exc).__name__}: {exc}")
        print("Existing NBA/WNBA officiating sidecars preserved.")
        return 0

    if assignments.empty:
        print("No official assignment rows parsed. Existing sidecars preserved.")
        return 0

    for sport in ["NBA", "WNBA"]:
        sport_frame = assignments[assignments["Sport"].astype(str).str.upper() == sport].copy()
        if sport_frame.empty:
            continue
        path = CONTEXT_DIR / f"{sport}_OfficiatingContext.csv"
        existing = _read_existing(path)
        combined = pd.concat([existing, sport_frame], ignore_index=True, sort=False)
        combined = combined.drop_duplicates(subset=["Date", "Sport", "Away", "Home", "Official"], keep="last")
        combined.to_csv(path, index=False)

    print(f"Rows parsed: {len(assignments)}")
    print(f"NBA/WNBA outputs: {CONTEXT_DIR}")
    print("Run build_officiating_context.py afterward to refresh the universal context file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
