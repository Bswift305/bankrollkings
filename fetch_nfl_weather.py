"""
Bankroll Kings - Fetch NFL game-day weather (wind) for upcoming outdoor games
=============================================================================

Wind is the one football totals signal the market underprices (see
backtest_football_wind_totals.py: outdoor games with 15+ mph wind hit the UNDER
~55%, +5% ROI, holds out of sample). This fetches the game-day wind forecast for
upcoming OUTDOOR home games so the command center can flag high-wind games.

Source: Open-Meteo forecast API -- free, no key, ~16-day horizon. One call per
stadium (a 16-day daily array), then each game's date is picked out of it. Domes
and retractables are skipped (no wind effect). Self-skips cleanly with no games in
range or on any network error, preserving the existing file.

Run:  python fetch_nfl_weather.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from services.nfl_stadiums import NFL_STADIUMS

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_PATHS = [
    BASE_DIR / "data" / "schedules" / "NFL_Schedule.csv",
    BASE_DIR / "data" / "schedules" / "NFL_Preseason_Schedule.csv",
]
OUTPUT = BASE_DIR / "data" / "context" / "NFL_GameWeather.csv"
FORECAST_DAYS = 16  # Open-Meteo max


def _load_home_games() -> pd.DataFrame:
    frames = []
    for path in SCHEDULE_PATHS:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "Date" not in df.columns:
            continue
        home_col = "HomeFull" if "HomeFull" in df.columns else "Home"
        if home_col not in df.columns:
            continue
        frames.append(df[["Date", home_col]].rename(columns={home_col: "Home"}))
    if not frames:
        return pd.DataFrame(columns=["Date", "Home"])
    return pd.concat(frames, ignore_index=True, sort=False).dropna().drop_duplicates()


def _fetch_stadium(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "daily": "wind_speed_10m_max,wind_gusts_10m_max,precipitation_sum,temperature_2m_max",
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "forecast_days": FORECAST_DAYS,
        "timezone": "America/New_York",
    })
    with urllib.request.urlopen(url, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    daily = payload.get("daily", {})
    times = daily.get("time", [])

    def _col(name):
        return daily.get(name, [None] * len(times))

    wind, gust, precip, temp = _col("wind_speed_10m_max"), _col("wind_gusts_10m_max"), _col("precipitation_sum"), _col("temperature_2m_max")
    return {t: {"wind": wind[i], "gust": gust[i], "precip": precip[i], "temp": temp[i]} for i, t in enumerate(times)}


def main() -> int:
    games = _load_home_games()
    if games.empty:
        print("No NFL schedule rows found; nothing to fetch.")
        return 0

    today = datetime.now().date()
    horizon = today + timedelta(days=FORECAST_DAYS - 1)
    forecast_cache: dict[str, dict] = {}
    rows = []
    for _, game in games.iterrows():
        home = str(game["Home"]).strip()
        info = NFL_STADIUMS.get(home)
        if not info or not info[3]:  # unknown stadium, or dome/retractable (not wind-exposed)
            continue
        game_date = pd.to_datetime(game["Date"], errors="coerce")
        if pd.isna(game_date) or not (today <= game_date.date() <= horizon):
            continue
        if home not in forecast_cache:
            try:
                forecast_cache[home] = _fetch_stadium(info[0], info[1])
            except Exception as exc:
                print(f"  weather fetch failed for {home}: {type(exc).__name__}: {exc}")
                forecast_cache[home] = {}
        forecast = forecast_cache[home].get(game_date.strftime("%Y-%m-%d"))
        if not forecast or forecast.get("wind") is None:
            continue
        rows.append({
            "Date": game_date.strftime("%Y-%m-%d"),
            "HomeTeam": home,
            "WindMph": round(float(forecast["wind"]), 1),
            "GustMph": round(float(forecast["gust"]), 1) if forecast.get("gust") is not None else "",
            "PrecipMm": forecast.get("precip"),
            "TempF": round(float(forecast["temp"]), 0) if forecast.get("temp") is not None else "",
            "Roof": info[2],
            "Updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["Date", "HomeTeam", "WindMph", "GustMph", "PrecipMm", "TempF", "Roof", "Updated"]).to_csv(OUTPUT, index=False)
    high = sum(1 for r in rows if r["WindMph"] >= 15)
    print(f"Wrote {len(rows)} NFL game-weather rows ({high} high-wind >=15mph) to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
