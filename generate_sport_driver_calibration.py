from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
OUTPUT_PATH = TRACKING_DIR / "Sport_Driver_Calibration.csv"
NOTES_PATH = TRACKING_DIR / "Sport_Driver_Calibration_Notes.txt"

SPORTS = {
    "NBA": TRACKING_DIR / "NBA_AllPropResults.csv",
    "WNBA": TRACKING_DIR / "WNBA_AllPropResults.csv",
    "MLB": TRACKING_DIR / "MLB_AllPropResults_Scored.csv",
    "NFL": TRACKING_DIR / "NFL_AllPropResults_Scored.csv",
}


def _read(path: Path, sport: str) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    df["Sport"] = sport
    for col in [
        "OutcomeState", "Stat", "Direction", "Method", "RoleLabel", "VolatilityFlag",
        "MarketGate", "MarketDepthBucket", "MarketMoveBucket", "Situations", "MethodLabels",
        "MarketTags", "BaselineReason", "GameScriptTags", "ContradictionTags", "MLBEnvironmentTags",
        "GameTotalLine", "GameSpreadLine", "WindMph", "Temperature", "RestDays", "WeightProfile",
    ]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    return df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()


def _classify(sample: int, rate: float) -> str:
    if sample < 10:
        return "WATCH_THIN"
    if sample >= 20 and rate >= 0.62:
        return "PROMOTE"
    if sample >= 20 and rate < 0.48:
        return "REDUCE"
    return "CALIBRATED"


def _add_group(rows: list[dict], sport: str, driver: str, frame: pd.DataFrame, group_col: str) -> None:
    if frame.empty or group_col not in frame.columns:
        return
    for key, group in frame.groupby(group_col, dropna=False):
        label = str(key or "").strip() or "UNKNOWN"
        if not label or label == "nan":
            label = "UNKNOWN"
        sample = int(len(group))
        hit_rate = float(group["OutcomeState"].eq("Hit").mean()) if sample else 0.0
        rows.append({
            "Sport": sport,
            "Driver": driver,
            "Bucket": label,
            "SampleSize": sample,
            "HitRate": round(hit_rate, 4),
            "Classification": _classify(sample, hit_rate),
        })


def _tag_rows(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=["OutcomeState", "Tag"])
    rows = []
    for _, row in frame.iterrows():
        tags = [part.strip() for part in str(row.get(column) or "").split("|") if part.strip()]
        for tag in tags:
            rows.append({"OutcomeState": row.get("OutcomeState"), "Tag": tag})
    return pd.DataFrame(rows)


def _contains_any(value: str, needles: list[str]) -> bool:
    haystack = str(value or "").upper()
    return any(needle in haystack for needle in needles)


def _bucket_from_text(value: str, rules: list[tuple[str, list[str]]], fallback: str = "UNSPECIFIED") -> str:
    for label, needles in rules:
        if _contains_any(value, needles):
            return label
    return fallback


def _numeric_bucket(value, buckets: list[tuple[str, float | None, float | None]], fallback: str = "UNKNOWN") -> str:
    try:
        number = float(value)
    except Exception:
        return fallback
    for label, low, high in buckets:
        if low is not None and number < low:
            continue
        if high is not None and number > high:
            continue
        return label
    return fallback


def _abs_number(value):
    try:
        return abs(float(value))
    except Exception:
        return ""


def build_driver_calibration() -> pd.DataFrame:
    rows: list[dict] = []
    for sport, path in SPORTS.items():
        df = _read(path, sport)
        if df.empty:
            continue

        if sport == "NBA":
            combined_context = (
                df["Situations"].fillna("")
                + " | "
                + df["MethodLabels"].fillna("")
                + " | "
                + df["MarketTags"].fillna("")
                + " | "
                + df["BaselineReason"].fillna("") if "BaselineReason" in df.columns else ""
            )
            df["UsageDriver"] = (
                df["Stat"].str.upper()
                + " | "
                + df["Direction"].str.upper()
                + " | "
                + df["RoleLabel"].replace("", "UNSPECIFIED")
            )
            df["MarketDriver"] = df["Direction"].str.upper() + " | " + df["MarketGate"].replace("", "CLEAR")
            df["RotationDriver"] = combined_context.apply(lambda value: _bucket_from_text(value, [
                ("ROLE_BOOST", ["BOOST", "ROLE UP", "TEAMMATE", "OUT", "INJURY"]),
                ("ROLE_RISK", ["ROLE SLIP", "BENCH", "MINUTES RISK", "VOLATILE", "QUESTIONABLE"]),
                ("MINUTES_SECURE", ["MINUTES", "SECURE", "WORKLOAD", "CORE ROLE"]),
            ], "ROTATION_STABLE"))
            df["PaceEnvironmentDriver"] = combined_context.apply(lambda value: _bucket_from_text(value, [
                ("PACE_UP", ["PACE UP", "FAST", "HIGH PACE", "MORE POSSESSIONS"]),
                ("PACE_DOWN", ["PACE DOWN", "SLOW", "LOW PACE", "FEWER POSSESSIONS"]),
                ("TOTAL_SUPPORT", ["TOTAL SUPPORT", "HIGH TOTAL", "ENVIRONMENT SUPPORT"]),
                ("TOTAL_RISK", ["LOW TOTAL", "ENVIRONMENT RISK", "UNDER ENVIRONMENT"]),
            ], "PACE_NEUTRAL"))
            _add_group(rows, sport, "Minutes/Usage Proxy", df, "UsageDriver")
            _add_group(rows, sport, "Market Gate", df, "MarketDriver")
            _add_group(rows, sport, "Rotation/Injury Proxy", df, "RotationDriver")
            _add_group(rows, sport, "Pace/Environment Proxy", df, "PaceEnvironmentDriver")

        elif sport == "WNBA":
            combined_context = (
                df["Situations"].fillna("")
                + " | "
                + df["MethodLabels"].fillna("")
                + " | "
                + df["MarketTags"].fillna("")
            )
            df["RoleStabilityDriver"] = (
                df["Method"].replace("", "UNKNOWN")
                + " | "
                + df["Direction"].str.upper()
                + " | "
                + df["VolatilityFlag"].replace("", "STABLE")
            )
            df["StatDirectionDriver"] = df["Stat"].str.upper() + " | " + df["Direction"].str.upper()
            df["MarketDepthDriver"] = df["MarketDepthBucket"].replace("", "UNKNOWN") + " | " + df["Direction"].str.upper()
            df["RoleShiftDriver"] = combined_context.apply(lambda value: _bucket_from_text(value, [
                ("USAGE_UP", ["BOOST", "ROLE UP", "TEAMMATE", "OUT", "INJURY"]),
                ("USAGE_RISK", ["ROLE SLIP", "BENCH", "MINUTES RISK", "VOLATILE", "QUESTIONABLE"]),
                ("FLOOR_STABLE", ["FLOOR", "SECURE", "WORKLOAD", "CORE ROLE"]),
            ], "ROLE_STABLE"))
            _add_group(rows, sport, "Role Stability", df, "RoleStabilityDriver")
            _add_group(rows, sport, "Stat Direction", df, "StatDirectionDriver")
            _add_group(rows, sport, "Market Depth", df, "MarketDepthDriver")
            _add_group(rows, sport, "Role Shift Proxy", df, "RoleShiftDriver")

        elif sport == "MLB":
            df["ContextDriver"] = df["Stat"].str.upper() + " | " + df["Direction"].str.upper()
            _add_group(rows, sport, "Pitcher/Hitter Context", df, "ContextDriver")
            tags = _tag_rows(df, "MLBEnvironmentTags")
            _add_group(rows, sport, "Game Environment Tags", tags, "Tag")

        elif sport == "NFL":
            df["GameScriptDriver"] = df["Stat"].str.upper() + " | " + df["Direction"].str.upper()
            df["TotalDriver"] = df["GameTotalLine"].apply(lambda value: _numeric_bucket(value, [
                ("LOW_TOTAL", None, 41.5),
                ("NEUTRAL_TOTAL", 42.0, 47.5),
                ("HIGH_TOTAL", 48.0, None),
            ])) + " | " + df["Direction"].str.upper()
            df["SpreadDriver"] = df["GameSpreadLine"].apply(lambda value: _numeric_bucket(_abs_number(value), [
                ("CLOSE_SPREAD", None, 3.0),
                ("MID_SPREAD", 3.5, 6.5),
                ("BIG_SPREAD", 7.0, None),
            ])) + " | " + df["Stat"].str.upper()
            df["WeatherDriver"] = df.apply(
                lambda row: (
                    "WIND_GAME" if _numeric_bucket(row.get("WindMph"), [("WIND_GAME", 15.0, None)], "") == "WIND_GAME"
                    else "COLD_GAME" if _numeric_bucket(row.get("Temperature"), [("COLD_GAME", None, 39.0)], "") == "COLD_GAME"
                    else "WEATHER_NEUTRAL"
                ) + " | " + str(row.get("Direction") or "").upper(),
                axis=1,
            )
            _add_group(rows, sport, "EPA/Game Script Proxy", df, "GameScriptDriver")
            _add_group(rows, sport, "Total Script", df, "TotalDriver")
            _add_group(rows, sport, "Spread Script", df, "SpreadDriver")
            _add_group(rows, sport, "Weather Script", df, "WeatherDriver")
            tags = _tag_rows(df, "GameScriptTags")
            _add_group(rows, sport, "Game Script Tags", tags, "Tag")
            ctags = _tag_rows(df, "ContradictionTags")
            _add_group(rows, sport, "Risk Tags", ctags, "Tag")

    out = pd.DataFrame(rows)
    if not out.empty:
        order = {"PROMOTE": 0, "REDUCE": 1, "CALIBRATED": 2, "WATCH_THIN": 3}
        out["_Order"] = out["Classification"].map(order).fillna(9)
        out = out.sort_values(["Sport", "_Order", "HitRate", "SampleSize"], ascending=[True, True, False, False])
        out = out.drop(columns=["_Order"])
    return out


def write_notes(df: pd.DataFrame) -> None:
    lines = [
        "Sport Driver Calibration Notes",
        "=" * 32,
        "",
        "Purpose:",
        "- NBA: minutes/usage, market gate, rotation/injury, and pace/environment buckets.",
        "- WNBA: role stability, stat-direction, market-depth, and role-shift buckets.",
        "- MLB: pitcher/hitter context and environment tags.",
        "- NFL: EPA/game-script, total, spread, weather, and risk-tag buckets from historical backfill.",
        "",
    ]
    if df.empty:
        lines.append("No driver calibration rows generated.")
    else:
        for sport in sorted(df["Sport"].dropna().unique().tolist()):
            lines.append(f"{sport}:")
            subset = df[(df["Sport"].eq(sport)) & (df["Classification"].isin(["PROMOTE", "REDUCE"]))].copy()
            if subset.empty:
                lines.append("- No promote/reduce driver buckets yet.")
            else:
                for _, row in subset.head(10).iterrows():
                    lines.append(
                        f"- {row.Classification}: {row.Driver} / {row.Bucket} "
                        f"hit {float(row.HitRate) * 100:.1f}% on {int(row.SampleSize):,} rows."
                    )
            lines.append("")
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    df = build_driver_calibration()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    write_notes(df)
    print("=" * 60)
    print("BANKROLL KINGS - SPORT DRIVER CALIBRATION")
    print("=" * 60)
    print(f"Rows written: {len(df):,}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Notes: {NOTES_PATH}")
    if not df.empty:
        print(df.head(16).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
