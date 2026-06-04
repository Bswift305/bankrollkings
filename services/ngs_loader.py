from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
NGS_DIR = DATA_DIR / "ngs"
DEFAULT_SEASON = 2025

NGS_TEAM_ID_TO_ABBR = {
    "200": "ATL",
    "325": "BAL",
    "610": "BUF",
    "750": "CAR",
    "810": "CHI",
    "920": "CIN",
    "1050": "CLE",
    "1200": "DAL",
    "1400": "DEN",
    "1540": "DET",
    "1800": "GB",
    "2120": "HOU",
    "2200": "IND",
    "2250": "JAX",
    "2310": "KC",
    "2510": "LAR",
    "2520": "LV",
    "2700": "LAC",
    "3000": "MIA",
    "3200": "MIN",
    "3300": "NE",
    "3400": "NO",
    "3410": "NYG",
    "3430": "NYJ",
    "3700": "PHI",
    "3900": "PIT",
    "4400": "SEA",
    "4500": "SF",
    "4600": "TB",
    "4800": "TEN",
    "5110": "WAS",
    "2100": "ARI",
}


def normalize_player_name(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def _ngs_path(category: str, season: int = DEFAULT_SEASON, season_type: str = "REG", weekly: bool = False) -> Path:
    suffix = "_Weekly" if weekly else ""
    return NGS_DIR / f"NGS_{category.capitalize()}_{season}_{season_type.upper()}{suffix}.csv"


@lru_cache(maxsize=24)
def load_ngs_dataframe(category: str = "receiving", season: int = DEFAULT_SEASON, season_type: str = "REG", weekly: bool = False) -> pd.DataFrame:
    path = _ngs_path(category, season=season, season_type=season_type, weekly=weekly)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    for name_col in ["player.displayName", "playerName"]:
        if name_col in df.columns:
            df["_PlayerKey"] = df[name_col].fillna("").astype(str).map(normalize_player_name)
            break
    else:
        df["_PlayerKey"] = ""
    if "teamId" in df.columns:
        team_ids = pd.to_numeric(df["teamId"], errors="coerce").astype("Int64").astype(str).str.replace("<NA>", "", regex=False)
        df["_TeamAbbr"] = team_ids.map(lambda value: NGS_TEAM_ID_TO_ABBR.get(str(value).strip(), ""))
    else:
        df["_TeamAbbr"] = ""
    return df


def load_ngs_lookup(category: str = "receiving", season_type: str = "REG", season: int = DEFAULT_SEASON) -> dict[str, dict]:
    df = load_ngs_dataframe(category, season=season, season_type=season_type, weekly=False)
    if df.empty or "_PlayerKey" not in df.columns:
        return {}
    return {
        str(row.get("_PlayerKey", "")): row
        for row in df.to_dict("records")
        if str(row.get("_PlayerKey", "")).strip()
    }


def load_ngs_weekly_trend(category: str = "receiving", player_name: str = "", weeks: int = 4, season: int = DEFAULT_SEASON) -> list[dict]:
    df = load_ngs_dataframe(category, season=season, season_type="REG", weekly=True)
    if df.empty or "_PlayerKey" not in df.columns:
        return []
    key = normalize_player_name(player_name)
    player_df = df[df["_PlayerKey"] == key].copy()
    if player_df.empty:
        return []
    week_col = "player.week" if "player.week" in player_df.columns else "Week"
    player_df["_WeekSort"] = pd.to_numeric(player_df.get(week_col), errors="coerce")
    player_df = player_df.dropna(subset=["_WeekSort"]).sort_values("_WeekSort", ascending=False)
    return player_df.head(weeks).to_dict("records")


def _clean_value(row: dict, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        if str(value).strip() != "":
            return value
    return None


def _number(row: dict, *keys: str) -> float | None:
    value = _clean_value(row, *keys)
    if value is None:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _percent_from_decimal(row: dict, *keys: str) -> float | None:
    value = _number(row, *keys)
    if value is None:
        return None
    return value * 100 if abs(value) <= 1 else value


def _fmt(value: float | None, decimals: int = 1, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "-"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.{decimals}f}{suffix}"


def _metric(label: str, value: str, note: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "note": note}


def _trend_label(values: list[float]) -> str:
    if len(values) < 2:
        return "Trend pending"
    first = values[0]
    last = values[-1]
    delta = last - first
    if delta >= 0.35:
        return "Improving"
    if delta <= -0.35:
        return "Fading"
    return "Stable"


def _trend(category: str, player_name: str, metric_key: str, label: str, decimals: int = 1, signed: bool = False) -> dict:
    rows = list(reversed(load_ngs_weekly_trend(category, player_name, weeks=4)))
    values = []
    points = []
    for row in rows:
        value = _number(row, metric_key)
        week = _number(row, "player.week", "Week")
        if value is None:
            continue
        values.append(value)
        points.append({"week": int(week) if week is not None else "", "value": _fmt(value, decimals=decimals, signed=signed)})
    return {
        "label": label,
        "points": points,
        "summary": _trend_label(values),
    }


def _trend_percent_decimal(category: str, player_name: str, metric_key: str, label: str) -> dict:
    rows = list(reversed(load_ngs_weekly_trend(category, player_name, weeks=4)))
    values = []
    points = []
    for row in rows:
        value = _percent_from_decimal(row, metric_key)
        week = _number(row, "player.week", "Week")
        if value is None:
            continue
        values.append(value)
        points.append({"week": int(week) if week is not None else "", "value": _fmt(value, decimals=1, suffix="%")})
    return {
        "label": label,
        "points": points,
        "summary": _trend_label(values),
    }


def _profile_from_row(category: str, row: dict, player_name: str) -> dict:
    display_name = str(_clean_value(row, "player.displayName", "playerName") or player_name)
    position = str(_clean_value(row, "player.position", "position") or "").upper()
    team = str(row.get("_TeamAbbr") or "")
    if category == "passing":
        metrics = [
            _metric("CPOE", _fmt(_number(row, "completionPercentageAboveExpectation"), 1, "%", signed=True), "Completion quality against expectation."),
            _metric("Avg Time To Throw", _fmt(_number(row, "avgTimeToThrow"), 2, "s"), "Release speed and pressure resistance context."),
            _metric("Aggressiveness", _fmt(_number(row, "aggressiveness"), 1, "%"), "Tight-window throw rate."),
            _metric("Avg Intended Air Yards", _fmt(_number(row, "avgIntendedAirYards"), 1), "Downfield intent versus check-down profile."),
            _metric("Air Yards Diff", _fmt(_number(row, "avgAirYardsDifferential"), 1, signed=True), "Completed air yards versus intended air yards."),
        ]
        trends = [
            _trend("passing", player_name, "completionPercentageAboveExpectation", "L4 CPOE", decimals=1, signed=True),
            _trend("passing", player_name, "avgTimeToThrow", "L4 Time To Throw", decimals=2),
        ]
    elif category == "receiving":
        metrics = [
            _metric("Air Yards Share", _fmt(_number(row, "percentShareOfIntendedAirYards"), 1, "%"), "True target-depth share in the offense."),
            _metric("Avg Separation", _fmt(_number(row, "avgSeparation"), 2, " yds"), "Space created at target/catch point."),
            _metric("aDOT", _fmt(_number(row, "avgIntendedAirYards"), 1, " yds"), "Deep-threat versus possession role."),
            _metric("Cushion", _fmt(_number(row, "avgCushion"), 1, " yds"), "How much space defenders concede pre-target."),
            _metric("YAC Over Expected", _fmt(_number(row, "avgYACAboveExpectation"), 2, signed=True), "Creation after catch beyond expectation."),
        ]
        trends = [
            _trend("receiving", player_name, "avgSeparation", "L4 Separation", decimals=2),
            _trend("receiving", player_name, "percentShareOfIntendedAirYards", "L4 Air Yards Share", decimals=1),
        ]
    else:
        metrics = [
            _metric("RYOE / Att", _fmt(_number(row, "rushYardsOverExpectedPerAtt"), 2, signed=True), "Yards created beyond expected per carry."),
            _metric("Rush % Over Expected", _fmt(_percent_from_decimal(row, "rushPctOverExpected"), 1, "%"), "Share of carries beating expectation."),
            _metric("Stacked Box %", _fmt(_number(row, "percentAttemptsGteEightDefenders"), 1, "%"), "How often the runner faces 8+ defenders."),
            _metric("Avg Time To LOS", _fmt(_number(row, "avgTimeToLos"), 2, "s"), "Patience and timing before crossing the line."),
            _metric("Efficiency", _fmt(_number(row, "efficiency"), 2), "North-south rushing efficiency context."),
        ]
        trends = [
            _trend("rushing", player_name, "rushYardsOverExpectedPerAtt", "L4 RYOE / Att", decimals=2, signed=True),
            _trend_percent_decimal("rushing", player_name, "rushPctOverExpected", "L4 Rush % Over Exp"),
        ]
    return {
        "category": category,
        "title": category.capitalize(),
        "display_name": display_name,
        "position": position,
        "team": team,
        "metrics": metrics,
        "trends": trends,
    }


def build_ngs_player_context(player_name: str, season: int = DEFAULT_SEASON) -> dict:
    key = normalize_player_name(player_name)
    if not key:
        return {"available": False, "profiles": []}
    profiles = []
    for category in ["passing", "receiving", "rushing"]:
        lookup = load_ngs_lookup(category, season=season, season_type="REG")
        row = lookup.get(key)
        if row:
            profiles.append(_profile_from_row(category, row, player_name))
    if not profiles:
        return {"available": False, "profiles": []}
    primary = profiles[0]
    return {
        "available": True,
        "season": season,
        "season_type": "REG",
        "player": primary.get("display_name") or player_name,
        "team": primary.get("team") or "",
        "position": primary.get("position") or "",
        "profiles": profiles,
    }


def build_ngs_prop_signal(player_name: str, stat: str, direction: str = "OVER", season: int = DEFAULT_SEASON) -> dict:
    stat_text = str(stat or "").strip().lower()
    direction = str(direction or "OVER").strip().upper()
    if not player_name or not stat_text:
        return {"available": False, "score_delta": 0.0, "tags": [], "note": ""}

    if "pass" in stat_text:
        category = "passing"
    elif "rush" in stat_text:
        category = "rushing"
    elif "rec" in stat_text:
        category = "receiving"
    else:
        return {"available": False, "score_delta": 0.0, "tags": [], "note": ""}

    lookup = load_ngs_lookup(category, season=season, season_type="REG")
    row = lookup.get(normalize_player_name(player_name))
    if not row:
        return {"available": False, "score_delta": 0.0, "tags": [], "note": ""}

    delta = 0.0
    tags: list[str] = []
    notes: list[str] = []

    if category == "receiving":
        air_share = _number(row, "percentShareOfIntendedAirYards")
        separation = _number(row, "avgSeparation")
        adot = _number(row, "avgIntendedAirYards")
        yac_oe = _number(row, "avgYACAboveExpectation")
        if direction == "OVER":
            if air_share is not None and air_share >= 25:
                delta += 3.0
                tags.append("NGS AIR SHARE")
                notes.append(f"{_fmt(air_share, 1, '%')} air-yards share supports ceiling")
            if separation is not None and separation >= 3.0:
                delta += 2.0
                tags.append("NGS SEPARATION")
                notes.append(f"{_fmt(separation, 2, ' yds')} separation supports target quality")
            if air_share is not None and air_share < 10:
                delta -= 3.0
                tags.append("LOW NGS SHARE")
                notes.append("low air-yards share limits receiving ceiling")
            if yac_oe is not None and yac_oe >= 0.75:
                delta += 1.5
                tags.append("YAC CREATOR")
        else:
            if air_share is not None and air_share < 12:
                delta += 3.0
                tags.append("LOW NGS SHARE")
                notes.append("limited air-yards role supports under risk")
            if separation is not None and separation < 2.2:
                delta += 2.0
                tags.append("LOW SEPARATION")
            if adot is not None and adot >= 13 and air_share is not None and air_share >= 25:
                delta -= 2.0
                tags.append("EXPLOSIVE ROLE")

    elif category == "rushing":
        ryoe_att = _number(row, "rushYardsOverExpectedPerAtt")
        rush_pct = _percent_from_decimal(row, "rushPctOverExpected")
        stacked = _number(row, "percentAttemptsGteEightDefenders")
        if direction == "OVER":
            if ryoe_att is not None and ryoe_att >= 0.5:
                delta += 4.0
                tags.append("NGS RYOE")
                notes.append(f"{_fmt(ryoe_att, 2, signed=True)} RYOE/att supports runner-created value")
            if rush_pct is not None and rush_pct >= 42:
                delta += 2.0
                tags.append("BEATS EXPECTATION")
            if stacked is not None and stacked >= 30:
                delta -= 3.0
                tags.append("STACKED BOX")
                notes.append(f"{_fmt(stacked, 1, '%')} stacked-box rate adds rushing friction")
        else:
            if ryoe_att is not None and ryoe_att < -0.2:
                delta += 3.0
                tags.append("NEGATIVE RYOE")
            if stacked is not None and stacked >= 30:
                delta += 2.0
                tags.append("STACKED BOX")
            if ryoe_att is not None and ryoe_att >= 0.75:
                delta -= 3.0
                tags.append("ELITE RYOE")

    elif category == "passing":
        cpoe = _number(row, "completionPercentageAboveExpectation")
        ttt = _number(row, "avgTimeToThrow")
        aggression = _number(row, "aggressiveness")
        air_yards = _number(row, "avgIntendedAirYards")
        if direction == "OVER":
            if cpoe is not None and cpoe >= 2.0:
                delta += 3.0
                tags.append("NGS CPOE")
                notes.append(f"{_fmt(cpoe, 1, '%', signed=True)} CPOE supports pass efficiency")
            if air_yards is not None and air_yards >= 8.5:
                delta += 2.0
                tags.append("DOWNFIELD INTENT")
            if aggression is not None and aggression < 13 and air_yards is not None and air_yards < 7.5:
                delta -= 3.0
                tags.append("CONSERVATIVE NGS")
                notes.append("low aggression plus short targets caps passing ceiling")
            if ttt is not None and ttt >= 3.0:
                delta -= 1.5
                tags.append("SLOW RELEASE")
        else:
            if aggression is not None and aggression < 13 and air_yards is not None and air_yards < 7.5:
                delta += 3.0
                tags.append("CONSERVATIVE NGS")
                notes.append("short, low-aggression profile supports under risk")
            if cpoe is not None and cpoe >= 3.0:
                delta -= 2.0
                tags.append("HIGH CPOE")

    capped = max(-6.0, min(6.0, delta))
    return {
        "available": True,
        "category": category,
        "score_delta": round(capped, 1),
        "tags": list(dict.fromkeys(tags)),
        "note": "; ".join(notes[:2]),
    }
