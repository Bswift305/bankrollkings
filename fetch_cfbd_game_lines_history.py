from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

import bk_runtime
from app import _format_ncaaf_game_lines_history
from services.env_loader import load_local_env


BASE_DIR = Path(__file__).parent.resolve()
BASE_URL = "https://api.collegefootballdata.com"
OUTPUT_PATH = BASE_DIR / "data" / "historical" / "NCAAF_GameLines_History.csv"


def get_api_key(cli_value: str | None) -> str:
    load_local_env(BASE_DIR)
    api_key = cli_value or os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not api_key:
        raise ValueError("Missing CFBD API key. Set CFBD_API_KEY or pass --api-key.")
    return api_key.strip()


def get_json(path: str, api_key: str, **params: Any) -> list[dict] | dict:
    query = {key: value for key, value in params.items() if value not in [None, ""]}
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "BankrollKings/1.0",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _num(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _first_line(row: dict, provider: str = "") -> dict:
    lines = row.get("lines") or []
    if not isinstance(lines, list) or not lines:
        return {}
    if provider:
        provider_clean = provider.lower().strip()
        for line in lines:
            line_provider = str(line.get("provider") or "").lower().strip()
            if line_provider == provider_clean:
                return line
    return lines[0]


def _home_spread(line: dict) -> float | None:
    for key in ("homeSpread", "home_spread", "spread"):
        value = _num(line.get(key))
        if value is not None:
            return value
    away_spread = _num(line.get("awaySpread") or line.get("away_spread"))
    if away_spread is not None:
        return -away_spread
    return None


def _away_spread(line: dict, home_spread: float | None) -> float | None:
    for key in ("awaySpread", "away_spread"):
        value = _num(line.get(key))
        if value is not None:
            return value
    if home_spread is not None:
        return -home_spread
    return None


def normalize_payload(payload: list[dict], season: int, provider: str = "") -> pd.DataFrame:
    rows: list[dict] = []
    for item in payload:
        line = _first_line(item, provider)
        if not line:
            continue
        home_spread = _home_spread(line)
        away_spread = _away_spread(line, home_spread)
        close_total = _num(line.get("overUnder") or line.get("total") or line.get("closeTotal"))
        open_total = _num(line.get("overUnderOpen") or line.get("openTotal"))
        rows.append({
            "Date": item.get("startDate") or item.get("start_date") or item.get("date"),
            "Season": item.get("season") or season,
            "Week": item.get("week"),
            # Authoritative identity for the ATS grader (game-ID reconciliation): stable CFBD game id,
            # EXACT provider names, and conference metadata. Carried as NEW columns; the existing
            # normalized Home/Away stay for other (presentation) consumers.
            "GameID": bk_runtime.cfb_game_id(item.get("id") or item.get("game_id")),
            "HomeTeamRaw": item.get("homeTeam") or item.get("home_team"),
            "AwayTeamRaw": item.get("awayTeam") or item.get("away_team"),
            "HomeConf": item.get("homeConference") or item.get("home_conference"),
            "AwayConf": item.get("awayConference") or item.get("away_conference"),
            "Away": item.get("awayTeam") or item.get("away_team"),
            "Home": item.get("homeTeam") or item.get("home_team"),
            "AwayScore": item.get("awayScore") if item.get("awayScore") is not None else item.get("away_score"),
            "HomeScore": item.get("homeScore") if item.get("homeScore") is not None else item.get("home_score"),
            "Spread": home_spread,
            "HomeSpread": home_spread,
            "AwaySpread": away_spread,
            "OpenHomeSpread": _num(line.get("homeSpreadOpen") or line.get("spreadOpen")),
            "OpenAwaySpread": _num(line.get("awaySpreadOpen")),
            "Total": close_total,
            "OpenTotal": open_total,
            "CloseTotal": close_total,
            "HomeCloseML": _num(line.get("homeMoneyline") or line.get("home_ml")),
            "AwayCloseML": _num(line.get("awayMoneyline") or line.get("away_ml")),
            "Source": f"cfbd:{line.get('provider') or provider or 'default'}",
        })
    if not rows:
        return pd.DataFrame()
    return _format_ncaaf_game_lines_history(pd.DataFrame(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch historical NCAAF game lines from CollegeFootballData.")
    parser.add_argument("--year", type=int, action="append", help="Season year to fetch. Repeat for multiple years.")
    parser.add_argument("--start-year", type=int, default=None, help="First season in a range.")
    parser.add_argument("--end-year", type=int, default=None, help="Last season in a range.")
    parser.add_argument("--season-type", default="regular", help="regular, postseason, or both if supported by CFBD.")
    parser.add_argument("--provider", default="", help="Optional CFBD line provider preference.")
    parser.add_argument("--api-key", default=None, help="CFBD API key. Prefer CFBD_API_KEY env var.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path.")
    args = parser.parse_args()

    years = list(args.year or [])
    if args.start_year is not None and args.end_year is not None:
        years.extend(range(args.start_year, args.end_year + 1))
    years = sorted(set(years))
    if not years:
        # No years given -> rebuild a rolling window ending at the CURRENT CFB season,
        # so the weekly refresh always folds in this week's completed games. The season
        # year rolls over in August (a Sept 2026 game is season 2026).
        from datetime import date
        today = date.today()
        current_season = today.year if today.month >= 8 else today.year - 1
        years = list(range(current_season - 5, current_season + 1))
        print(f"No years given; defaulting to rolling window {years[0]}-{years[-1]}.")

    # "both" fans out to regular + postseason so a rebuild keeps bowl/playoff games
    # (CFBD's /lines takes one seasonType per call).
    season_types = ["regular", "postseason"] if args.season_type == "both" else [args.season_type]

    api_key = get_api_key(args.api_key)
    frames = []
    for year in years:
        year_rows = 0
        for season_type in season_types:
            payload = get_json("/lines", api_key, year=year, seasonType=season_type)
            frame = normalize_payload(payload if isinstance(payload, list) else [], year, args.provider)
            if not frame.empty:
                frames.append(frame)
                year_rows += len(frame)
        print(f"{year}: {year_rows} line rows")

    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    output_path = Path(args.output)
    required = {"GameID", "HomeTeamRaw", "AwayTeamRaw", "HomeConf", "AwayConf", "Week", "Season", "Date"}
    if output.empty or not required.issubset(output.columns):
        print(f"[FAIL] history fetch produced {len(output)} rows / missing "
              f"{required - set(output.columns)}; leaving the existing file untouched.")
        return 2
    # STRONG pre-publish validation: every AUTHORITATIVE current-season row must carry a canonical
    # GameID, exact provider names, a valid week/date, and a conference value PRESENT for each side
    # (an UNKNOWN-but-present conf may still publish for diagnosis; a NULL conf may not). If any fails,
    # leave the last good history untouched rather than grade a malformed generation.
    from datetime import date as _date
    today = _date.today()
    cur_season = today.year if today.month >= 8 else today.year - 1
    cur = output[pd.to_numeric(output["Season"], errors="coerce") == cur_season]
    bad = 0
    for _, r in cur.iterrows():
        gid = bk_runtime.cfb_game_id(r.get("GameID"))
        home = str(r.get("HomeTeamRaw") or "").strip()
        away = str(r.get("AwayTeamRaw") or "").strip()
        wk = pd.to_numeric(r.get("Week"), errors="coerce")
        dt = str(r.get("Date") or "").strip()
        hc = str(r.get("HomeConf") or "").strip()
        ac = str(r.get("AwayConf") or "").strip()
        if (gid is None or not home or not away or pd.isna(wk) or not dt
                or not hc or hc.lower() == "nan" or not ac or ac.lower() == "nan"):
            bad += 1
    if bad:
        print(f"[FAIL] {bad} current-season ({cur_season}) history rows fail validation "
              "(GameID/names/week/date/conference); leaving the existing file untouched.")
        return 2
    bk_runtime.write_csv_atomic(output, output_path)       # temp + fsync + os.replace
    print(f"Wrote {len(output)} rows to {output_path} ({len(cur)} current-season {cur_season} rows valid)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
