"""
Bankroll Kings - Cross-Sport Injury Fetcher
===========================================
Fetches injury reports from ESPN injury pages for supported sports.

Usage:
  py fetch_sport_injuries.py --sport wnba
  py fetch_sport_injuries.py --sport nfl
  py fetch_sport_injuries.py --sport mlb
  py fetch_sport_injuries.py --sport ncaaf
"""

from __future__ import annotations

import argparse
from datetime import datetime
from html import unescape
from pathlib import Path
import re

import pandas as pd
import requests

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
INJURIES_DIR = DATA_DIR / "injuries"
ROSTERS_DIR = DATA_DIR / "rosters"
INJURIES_DIR.mkdir(parents=True, exist_ok=True)

SPORT_CONFIG = {
    "wnba": {
        "url": "https://www.espn.com/wnba/injuries",
        "prefix": "WNBA",
        "team_map": {
            "Atlanta Dream": "ATL",
            "Chicago Sky": "CHI",
            "Connecticut Sun": "CON",
            "Dallas Wings": "DAL",
            "Golden State Valkyries": "GSV",
            "Indiana Fever": "IND",
            "Las Vegas Aces": "LVA",
            "Los Angeles Sparks": "LAS",
            "Minnesota Lynx": "MIN",
            "New York Liberty": "NYL",
            "Phoenix Mercury": "PHX",
            "Seattle Storm": "SEA",
            "Washington Mystics": "WAS",
            "Toronto Tempo": "TOR",
        },
    },
    "nfl": {
        "url": "https://www.espn.com/nfl/injuries",
        "prefix": "NFL",
        "team_map": {
            "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
            "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
            "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
            "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
            "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
            "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
            "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
            "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
            "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
            "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
            "Tennessee Titans": "TEN", "Washington Commanders": "WSH",
        },
    },
    "mlb": {
        "url": "https://www.espn.com/mlb/injuries",
        "prefix": "MLB",
        "team_map": {
            "Arizona Diamondbacks": "ARI", "Athletics": "ATH", "Atlanta Braves": "ATL",
            "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
            "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
            "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
            "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
            "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
            "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
            "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
            "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
            "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
        },
    },
    "ncaaf": {
        "url": None,
        "prefix": "NCAAF",
        "team_map": {},
    },
}


def build_safe_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies.clear()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def injuries_path_for(prefix: str) -> Path:
    return INJURIES_DIR / f"{prefix}_Injuries.csv"


def injuries_backup_path_for(prefix: str) -> Path:
    return INJURIES_DIR / f"{prefix}_Injuries_last_good.csv"


def injuries_manual_path_for(prefix: str) -> Path:
    return INJURIES_DIR / f"{prefix}_Injuries_Manual.csv"


def ensure_manual_template(prefix: str):
    path = injuries_manual_path_for(prefix)
    required_cols = ["Player", "Team", "Status", "Reason", "Updated", "Active", "ExpiresOn"]
    if not path.exists():
        pd.DataFrame(columns=required_cols).to_csv(path, index=False)
        return
    try:
        df = pd.read_csv(path)
    except Exception:
        pd.DataFrame(columns=required_cols).to_csv(path, index=False)
        return
    changed = False
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
            changed = True
    if changed or list(df.columns) != required_cols:
        df = df[required_cols].copy()
        df.to_csv(path, index=False)


def load_existing(prefix: str) -> pd.DataFrame:
    for path in [injuries_path_for(prefix), injuries_backup_path_for(prefix)]:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if not df.empty:
            return df
    return pd.DataFrame(columns=["Player", "Team", "Status", "Reason", "Updated"])


def load_manual(prefix: str) -> pd.DataFrame:
    ensure_manual_template(prefix)
    path = injuries_manual_path_for(prefix)
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=["Player", "Team", "Status", "Reason", "Updated", "Active", "ExpiresOn"])
    for col in ["Player", "Team", "Status", "Reason", "Updated", "Active", "ExpiresOn"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[df["Player"] != ""].copy()
    if df.empty:
        return df
    now = pd.Timestamp.now()
    updated_dt = pd.to_datetime(df["Updated"], errors="coerce")
    expires_dt = pd.to_datetime(df["ExpiresOn"], errors="coerce")
    active_flag = df["Active"].str.lower().isin({"1", "true", "yes", "y", "active"})
    recent_flag = updated_dt >= (now - pd.Timedelta(days=3))
    unexpired_flag = expires_dt.isna() | (expires_dt >= now.normalize())
    keep_mask = unexpired_flag & (active_flag | recent_flag)
    return df[keep_mask].copy()


def standardize_status(raw_status: str, sport_key: str) -> str:
    value = str(raw_status or "").strip()
    if not value:
        return "UNKNOWN"
    upper_value = value.upper()
    common_map = {
        "OUT": "OUT",
        "DOUBTFUL": "DOUBTFUL",
        "QUESTIONABLE": "QUESTIONABLE",
        "PROBABLE": "PROBABLE",
        "AVAILABLE": "AVAILABLE",
        "ACTIVE": "ACTIVE",
        "DAY-TO-DAY": "GTD",
        "DAY TO DAY": "GTD",
        "GAME TIME DECISION": "GTD",
        "INJURED RESERVE": "OUT",
        "INJURED RESERVE-RETURN": "OUT",
        "PHYSICALLY UNABLE TO PERFORM": "OUT",
        "NON-FOOTBALL INJURY": "OUT",
    }
    if upper_value in common_map:
        return common_map[upper_value]
    if sport_key == "mlb":
        if "IL" in upper_value:
            return "OUT"
        if upper_value == "DAY-TO-DAY":
            return "GTD"
    return upper_value


def parse_espn_injury_table(html: str, team_map: dict[str, str], sport_key: str) -> list[dict]:
    injuries = []
    section_pattern = re.compile(
        r'<span class="injuries__teamName ml2">(.*?)</span>.*?<tbody class="Table__TBODY">(.*?)</tbody>',
        re.IGNORECASE | re.DOTALL,
    )
    row_pattern = re.compile(
        r'<td class="col-name Table__TD">.*?>(.*?)</a></td>.*?'
        r'<td class="col-date Table__TD">(.*?)</td>.*?'
        r'<td class="col-stat Table__TD">.*?>(.*?)</span></td>.*?'
        r'<td class="col-desc Table__TD">(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    for team_name, tbody in section_pattern.findall(html):
        team_name = unescape(re.sub(r"<.*?>", "", team_name)).strip()
        team_code = team_map.get(team_name)
        if not team_code:
            continue
        for player_name, return_date, status, comment in row_pattern.findall(tbody):
            player_name = unescape(re.sub(r"<.*?>", "", player_name)).strip()
            return_date = unescape(re.sub(r"<.*?>", "", return_date)).strip()
            status = unescape(re.sub(r"<.*?>", "", status)).strip()
            comment = unescape(re.sub(r"<.*?>", "", comment)).strip()
            if not player_name or not status:
                continue
            reason = comment
            if return_date and return_date.lower() != "nan":
                reason = f"{return_date} | {comment}" if comment else return_date
            injuries.append(
                {
                    "Player": player_name,
                    "Team": team_code,
                    "Status": standardize_status(status, sport_key),
                    "Reason": reason or "ESPN injury report",
                    "Updated": updated,
                }
            )
    return injuries


def merge_manual(df: pd.DataFrame, prefix: str, sport_key: str) -> pd.DataFrame:
    manual = load_manual(prefix)
    if manual.empty:
        if df is None:
            return pd.DataFrame(columns=["Player", "Team", "Status", "Reason", "Updated"])
        return df
    merged = pd.concat([df, manual], ignore_index=True) if df is not None and not df.empty else manual.copy()
    merged["Status"] = merged["Status"].apply(lambda value: standardize_status(value, sport_key))
    merged["Player"] = merged["Player"].fillna("").astype(str).str.strip()
    merged = merged[merged["Player"] != ""].copy()
    return merged.drop_duplicates(subset=["Player"], keep="last").reset_index(drop=True)


def save_df(df: pd.DataFrame, prefix: str):
    out_path = injuries_path_for(prefix)
    backup_path = injuries_backup_path_for(prefix)
    df.to_csv(out_path, index=False)
    if not df.empty:
        df.to_csv(backup_path, index=False)


def build_ncaaf_team_map() -> dict[str, str]:
    roster_path = ROSTERS_DIR / "NCAAF_CurrentRoster.csv"
    if not roster_path.exists():
        return {}
    try:
        roster = pd.read_csv(roster_path, usecols=["CurrentTeam", "TeamAbbreviation"], low_memory=False)
    except Exception:
        return {}
    roster = roster.dropna(subset=["CurrentTeam", "TeamAbbreviation"]).copy()
    roster["CurrentTeam"] = roster["CurrentTeam"].astype(str).str.strip()
    roster["TeamAbbreviation"] = roster["TeamAbbreviation"].astype(str).str.strip()
    return (
        roster.drop_duplicates(subset=["CurrentTeam"], keep="first")
        .set_index("CurrentTeam")["TeamAbbreviation"]
        .to_dict()
    )


def fetch_sport_injuries(sport_key: str) -> pd.DataFrame:
    sport_key = str(sport_key or "").strip().lower()
    if sport_key not in SPORT_CONFIG:
        raise ValueError(f"Unsupported sport: {sport_key}")

    config = dict(SPORT_CONFIG[sport_key])
    prefix = config["prefix"]
    url = config["url"]
    team_map = dict(config.get("team_map") or {})
    if sport_key == "ncaaf":
        team_map = build_ncaaf_team_map()

    existing = load_existing(prefix)

    if not url:
        print(f"No live injury endpoint configured for {sport_key.upper()} yet.")
        preserved = merge_manual(existing, prefix, sport_key)
        save_df(preserved, prefix)
        return preserved

    session = build_safe_session()
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        print(f"Error fetching {sport_key.upper()} injuries: {exc}")
        preserved = merge_manual(existing, prefix, sport_key)
        save_df(preserved, prefix)
        return preserved

    injuries = parse_espn_injury_table(response.text, team_map, sport_key)
    if injuries:
        df = pd.DataFrame(injuries)
        df = merge_manual(df, prefix, sport_key)
        save_df(df, prefix)
        print(f"Saved {len(df)} {sport_key.upper()} injuries to {injuries_path_for(prefix)}")
        return df

    print(f"No parsed {sport_key.upper()} injuries found from ESPN page.")
    preserved = merge_manual(existing, prefix, sport_key)
    save_df(preserved, prefix)
    return preserved


def main():
    parser = argparse.ArgumentParser(description="Fetch injuries for a supported sport.")
    parser.add_argument("--sport", required=True, choices=sorted(SPORT_CONFIG.keys()))
    args = parser.parse_args()
    fetch_sport_injuries(args.sport)


if __name__ == "__main__":
    main()
