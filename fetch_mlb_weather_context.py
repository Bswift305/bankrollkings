from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_PATH = DATA_DIR / "schedules" / "MLB_Schedule.csv"
FACTORS_PATH = DATA_DIR / "context" / "MLB_BallparkFactors.csv"
OUTPUT_PATH = DATA_DIR / "context" / "MLB_WeatherContext.csv"

CENTRAL = ZoneInfo("America/Chicago")

BALLPARK_COORDS = {
    "American Family Field": (43.0280, -87.9712),
    "Angel Stadium": (33.8003, -117.8827),
    "Busch Stadium": (38.6226, -90.1928),
    "Chase Field": (33.4455, -112.0667),
    "Citi Field": (40.7571, -73.8458),
    "Citizens Bank Park": (39.9061, -75.1665),
    "Comerica Park": (42.3390, -83.0485),
    "Coors Field": (39.7559, -104.9942),
    "Daikin Park": (29.7573, -95.3555),
    "Dodger Stadium": (34.0739, -118.2400),
    "Fenway Park": (42.3467, -71.0972),
    "George M. Steinbrenner Field": (27.9803, -82.5067),
    "Globe Life Field": (32.7473, -97.0842),
    "Great American Ball Park": (39.0979, -84.5082),
    "Kauffman Stadium": (39.0517, -94.4803),
    "loanDepot park": (25.7781, -80.2197),
    "Nationals Park": (38.8730, -77.0074),
    "Oracle Park": (37.7786, -122.3893),
    "Oriole Park at Camden Yards": (39.2840, -76.6217),
    "Petco Park": (32.7073, -117.1566),
    "PNC Park": (40.4469, -80.0057),
    "Progressive Field": (41.4962, -81.6852),
    "Rate Field": (41.8300, -87.6339),
    "Rogers Centre": (43.6414, -79.3894),
    "Sutter Health Park": (38.5803, -121.5139),
    "T-Mobile Park": (47.5914, -122.3325),
    "Target Field": (44.9817, -93.2776),
    "Truist Park": (33.8908, -84.4678),
    "Wrigley Field": (41.9484, -87.6553),
    "Yankee Stadium": (40.8296, -73.9262),
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def degrees_to_cardinal(degrees: float | None) -> str:
    if degrees is None or pd.isna(degrees):
        return ""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return directions[int((float(degrees) + 22.5) // 45) % 8]


def nearest_hour_index(hourly_times: list[str], target: datetime) -> int | None:
    if not hourly_times:
        return None
    target_naive = target.replace(tzinfo=None)
    best_idx = None
    best_delta = None
    for idx, value in enumerate(hourly_times):
        try:
            parsed = datetime.fromisoformat(value)
        except Exception:
            continue
        delta = abs((parsed - target_naive).total_seconds())
        if best_delta is None or delta < best_delta:
            best_idx = idx
            best_delta = delta
    return best_idx


def fetch_hourly_weather(lat: float, lon: float, date: str) -> dict:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,windspeed_10m,winddirection_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "America/Chicago",
            "start_date": date,
            "end_date": date,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def build_weather_context() -> pd.DataFrame:
    schedule = read_csv(SCHEDULE_PATH)
    factors = read_csv(FACTORS_PATH)
    if schedule.empty:
        return pd.DataFrame(columns=["Date", "Away", "Home", "Temperature", "WindMph", "WindDirection", "WeatherSource", "LastUpdated"])

    factor_lookup = {}
    if not factors.empty:
        for _, row in factors.iterrows():
            factor_lookup[str(row.get("Team") or "").strip()] = row.to_dict()

    rows = []
    cache: dict[tuple[str, str], dict] = {}
    for _, game in schedule.drop_duplicates(subset=["Date", "AwayFull", "HomeFull"]).iterrows():
        date = str(game.get("Date") or "").strip()
        away = str(game.get("AwayFull") or game.get("Away") or "").strip()
        home = str(game.get("HomeFull") or game.get("Home") or "").strip()
        time_text = str(game.get("Time") or "19:00").strip()
        factor = factor_lookup.get(home, {})
        ballpark = str(factor.get("Ballpark") or "").strip()
        coords = BALLPARK_COORDS.get(ballpark)
        temperature = ""
        wind_mph = ""
        wind_direction = ""
        source = "open_meteo_missing_coords"
        if coords and date:
            try:
                cache_key = (ballpark, date)
                payload = cache.get(cache_key)
                if payload is None:
                    payload = fetch_hourly_weather(coords[0], coords[1], date)
                    cache[cache_key] = payload
                hourly = payload.get("hourly", {})
                target = datetime.fromisoformat(f"{date}T{time_text}")
                idx = nearest_hour_index(hourly.get("time", []), target)
                if idx is not None:
                    temps = hourly.get("temperature_2m", [])
                    winds = hourly.get("windspeed_10m", [])
                    dirs = hourly.get("winddirection_10m", [])
                    temperature = round(float(temps[idx]), 1) if idx < len(temps) and temps[idx] is not None else ""
                    wind_mph = round(float(winds[idx]), 1) if idx < len(winds) and winds[idx] is not None else ""
                    wind_direction = degrees_to_cardinal(float(dirs[idx])) if idx < len(dirs) and dirs[idx] is not None else ""
                    source = "open_meteo_forecast"
            except Exception as exc:
                source = f"open_meteo_error:{type(exc).__name__}"
        rows.append(
            {
                "Date": date,
                "Away": away,
                "Home": home,
                "Temperature": temperature,
                "WindMph": wind_mph,
                "WindDirection": wind_direction,
                "WeatherSource": source,
                "LastUpdated": datetime.now(CENTRAL).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    weather = build_weather_context()
    weather.to_csv(OUTPUT_PATH, index=False)
    missing_temp = int(weather["Temperature"].fillna("").astype(str).str.strip().eq("").sum()) if not weather.empty else 0
    missing_wind = int(weather["WindMph"].fillna("").astype(str).str.strip().eq("").sum()) if not weather.empty else 0
    print("=" * 60)
    print("BANKROLL KINGS - MLB WEATHER CONTEXT")
    print("=" * 60)
    print(f"Rows written: {len(weather)}")
    print(f"Missing temperature: {missing_temp}")
    print(f"Missing wind: {missing_wind}")
    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
