from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
STATCAST_DIR = DATA_DIR / "statcast"
DEFAULT_SEASON = 2026


def normalize_player_name(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def _profile_path(role: str, season: int = DEFAULT_SEASON) -> Path:
    suffix = "Hitters" if role == "hitter" else "Pitchers"
    return STATCAST_DIR / f"MLB_Statcast_{suffix}_{season}.csv"


@lru_cache(maxsize=8)
def load_statcast_dataframe(role: str = "hitter", season: int = DEFAULT_SEASON) -> pd.DataFrame:
    path = _profile_path(role, season)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    if "PlayerKey" not in df.columns:
        df["PlayerKey"] = df.get("Player", pd.Series(dtype=str)).fillna("").astype(str).map(normalize_player_name)
    return df


@lru_cache(maxsize=8)
def load_statcast_lookup(role: str = "hitter", season: int = DEFAULT_SEASON) -> dict[str, dict]:
    df = load_statcast_dataframe(role, season)
    if df.empty or "PlayerKey" not in df.columns:
        return {}
    lookup = {}
    for row in df.to_dict("records"):
        key = str(row.get("PlayerKey") or "").strip()
        player = str(row.get("Player") or "").strip()
        if key and player and player.lower() != "nan":
            lookup[key] = row
    return lookup


def _value(row: dict, *keys: str) -> Any:
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
    value = _value(row, *keys)
    if value is None:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _fmt(value: float | None, decimals: int = 1, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "-"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.{decimals}f}{suffix}"


def _metric(label: str, value: str, note: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "note": note}


def _hitter_profile(row: dict) -> dict:
    return {
        "role": "hitter",
        "title": "Statcast Hitter",
        "player": str(row.get("Player") or "").strip(),
        "metrics": [
            _metric("xwOBA", _fmt(_number(row, "Expected_est_woba"), 3), "Expected production quality."),
            _metric("xSLG", _fmt(_number(row, "Expected_est_slg"), 3), "Expected power output."),
            _metric("Barrel %", _fmt(_number(row, "Barrel_brl_percent"), 1, "%"), "Ideal contact rate for HR/TB upside."),
            _metric("Hard-Hit %ile", _fmt(_number(row, "Percentile_hard_hit_percent"), 0), "Percentile rank for hard-contact quality."),
            _metric("Sprint Speed", _fmt(_number(row, "Sprint_sprint_speed"), 1), "Speed layer for runs, steals, and extra bases."),
        ],
    }


def _pitcher_profile(row: dict) -> dict:
    return {
        "role": "pitcher",
        "title": "Statcast Pitcher",
        "player": str(row.get("Player") or "").strip(),
        "metrics": [
            _metric("xERA", _fmt(_number(row, "Expected_xera"), 2), "Expected run prevention quality."),
            _metric("xwOBA Allowed", _fmt(_number(row, "Expected_est_woba"), 3), "Expected contact damage allowed."),
            _metric("K %ile", _fmt(_number(row, "Percentile_k_percent"), 0), "Strikeout percentile."),
            _metric("Whiff %ile", _fmt(_number(row, "Percentile_whiff_percent"), 0), "Swing-and-miss percentile."),
            _metric("Best Whiff Pitch", str(_value(row, "BestWhiffPitch") or "-"), f"{_fmt(_number(row, 'BestWhiffPct'), 1, '%')} whiff"),
        ],
    }


def build_statcast_player_context(player_name: str, season: int = DEFAULT_SEASON) -> dict:
    key = normalize_player_name(player_name)
    if not key:
        return {"available": False, "profiles": []}
    profiles = []
    hitter = load_statcast_lookup("hitter", season).get(key)
    pitcher = load_statcast_lookup("pitcher", season).get(key)
    if hitter:
        profiles.append(_hitter_profile(hitter))
    if pitcher:
        profiles.append(_pitcher_profile(pitcher))
    if not profiles:
        return {"available": False, "profiles": []}
    return {
        "available": True,
        "season": season,
        "player": profiles[0].get("player") or player_name,
        "profiles": profiles,
    }


def _is_pitcher_stat(stat: str) -> bool:
    text = str(stat or "").upper()
    return "PITCHER" in text or text in {"PITCHER KS", "PITCHER OUTS", "PITCHER HITS ALLOWED", "PITCHER EARNED RUNS", "PITCHER WALKS"}


def build_statcast_prop_signal(player_name: str, stat: str, direction: str = "OVER", season: int = DEFAULT_SEASON) -> dict:
    stat_text = str(stat or "").strip().upper()
    direction = str(direction or "OVER").strip().upper()
    role = "pitcher" if _is_pitcher_stat(stat_text) else "hitter"
    row = load_statcast_lookup(role, season).get(normalize_player_name(player_name))
    if not row:
        return {"available": False, "score_delta": 0.0, "tags": [], "note": ""}

    delta = 0.0
    tags: list[str] = []
    notes: list[str] = []

    if role == "hitter":
        xwoba_pct = _number(row, "Percentile_xwoba")
        barrel_pctile = _number(row, "Percentile_brl_percent")
        hardhit_pctile = _number(row, "Percentile_hard_hit_percent")
        k_pctile = _number(row, "Percentile_k_percent")
        sprint = _number(row, "Sprint_sprint_speed")
        power_stat = any(token in stat_text for token in ["HOME RUN", "TOTAL BASE", "HITS + RUNS + RBIS", "RBI", "RUNS"])
        contact_stat = any(token in stat_text for token in ["HITS", "SINGLES", "DOUBLES", "TRIPLES"])
        strikeout_stat = "BATTER STRIKEOUT" in stat_text

        if strikeout_stat:
            if direction == "OVER" and k_pctile is not None and k_pctile <= 30:
                delta += 3.0
                tags.append("STATCAST K RISK")
                notes.append("low K percentile means strikeout risk is elevated")
            elif direction == "UNDER" and k_pctile is not None and k_pctile >= 70:
                delta += 3.0
                tags.append("CONTACT PROFILE")
                notes.append("strong K-avoidance percentile supports strikeout under")
        elif direction == "OVER":
            if power_stat and barrel_pctile is not None and barrel_pctile >= 75:
                delta += 4.0
                tags.append("BARREL SUPPORT")
                notes.append(f"{_fmt(barrel_pctile, 0)} barrel percentile supports power upside")
            if hardhit_pctile is not None and hardhit_pctile >= 70:
                delta += 2.0
                tags.append("HARD HIT")
            if xwoba_pct is not None and xwoba_pct >= 70:
                delta += 2.0
                tags.append("XWOBA SUPPORT")
            if contact_stat and k_pctile is not None and k_pctile <= 25:
                delta -= 2.0
                tags.append("K RISK")
            if "STOLEN" in stat_text and sprint is not None and sprint >= 28:
                delta += 3.0
                tags.append("SPRINT SPEED")
        else:
            if xwoba_pct is not None and xwoba_pct <= 30:
                delta += 3.0
                tags.append("LOW XWOBA")
                notes.append("low xwOBA percentile supports hitter under risk")
            if power_stat and barrel_pctile is not None and barrel_pctile <= 30:
                delta += 3.0
                tags.append("LOW BARREL")
            if power_stat and barrel_pctile is not None and barrel_pctile >= 80:
                delta -= 3.0
                tags.append("POWER RISK")

    else:
        k_pctile = _number(row, "Percentile_k_percent")
        whiff_pctile = _number(row, "Percentile_whiff_percent")
        xera_pctile = _number(row, "Percentile_xera")
        hardhit_pctile = _number(row, "Percentile_hard_hit_percent")
        arsenal_whiff = _number(row, "ArsenalAvgWhiffPct")
        if "KS" in stat_text or "STRIKEOUT" in stat_text:
            if direction == "OVER":
                if k_pctile is not None and k_pctile >= 70:
                    delta += 4.0
                    tags.append("K PERCENTILE")
                    notes.append(f"{_fmt(k_pctile, 0)} K percentile supports strikeout upside")
                if whiff_pctile is not None and whiff_pctile >= 70:
                    delta += 2.0
                    tags.append("WHIFF SUPPORT")
                if arsenal_whiff is not None and arsenal_whiff >= 30:
                    delta += 2.0
                    tags.append("ARSENAL WHIFF")
            else:
                if k_pctile is not None and k_pctile <= 35:
                    delta += 3.0
                    tags.append("LOW K PROFILE")
                if whiff_pctile is not None and whiff_pctile <= 35:
                    delta += 2.0
                    tags.append("LOW WHIFF")
        elif direction == "OVER":
            if ("HITS ALLOWED" in stat_text or "EARNED RUNS" in stat_text) and hardhit_pctile is not None and hardhit_pctile <= 35:
                delta += 3.0
                tags.append("HARD CONTACT ALLOWED")
            if "OUTS" in stat_text and xera_pctile is not None and xera_pctile >= 70:
                delta += 3.0
                tags.append("XERA SUPPORT")
        else:
            if ("HITS ALLOWED" in stat_text or "EARNED RUNS" in stat_text) and xera_pctile is not None and xera_pctile >= 70:
                delta += 3.0
                tags.append("RUN PREVENTION")
            if "OUTS" in stat_text and xera_pctile is not None and xera_pctile <= 30:
                delta += 3.0
                tags.append("LOW XERA")

    capped = max(-6.0, min(6.0, delta))
    return {
        "available": True,
        "role": role,
        "score_delta": round(capped, 1),
        "tags": list(dict.fromkeys(tags)),
        "note": "; ".join(notes[:2]),
    }
