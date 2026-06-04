from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
HISTORICAL_DIR = BASE_DIR / "data" / "historical"
TRACKING_DIR = BASE_DIR / "data" / "tracking"
DEFAULT_PROPS_PATH = HISTORICAL_DIR / "MLB_Props_History.csv"
FALLBACK_PROPS_PATH = BASE_DIR / "data" / "props" / "MLB_Props.csv"
GAMELOGS_PATH = BASE_DIR / "data" / "gamelogs" / "MLB_GameLogs.csv"
OUTPUT_PATH = TRACKING_DIR / "MLB_HistoricalBackfillResults.csv"
BUCKET_REPORT_PATH = TRACKING_DIR / "MLB_HistoricalBackfill_BucketReport.csv"
PLAYER_PROFILE_PATH = TRACKING_DIR / "MLB_HistoricalBackfill_PlayerProfiles.csv"


STAT_TO_LOG_COLUMN = {
    "HITS": "H",
    "BATTER HITS": "H",
    "TOTAL BASES": "TB",
    "HOME RUNS": "HR",
    "BATTER HOME RUNS": "HR",
    "RBIS": "RBI",
    "RBI": "RBI",
    "RUNS": "R",
    "BATTER RUNS": "R",
    "STOLEN BASES": "SB",
    "BATTER WALKS": "BB",
    "WALKS": "BB",
    "BATTER STRIKEOUTS": "SO",
    "SINGLES": "1B",
    "DOUBLES": "2B",
    "TRIPLES": "3B",
    "PITCHER KS": "P_SO",
    "PITCHER STRIKEOUTS": "P_SO",
    "PITCHER HITS ALLOWED": "P_H",
    "PITCHER EARNED RUNS": "P_ER",
    "PITCHER OUTS": "P_OUTS",
}


MARKET_TO_STAT = {
    "batter_hits": "HITS",
    "batter_total_bases": "TOTAL BASES",
    "batter_home_runs": "HOME RUNS",
    "batter_rbis": "RBIS",
    "batter_runs_scored": "RUNS",
    "batter_stolen_bases": "STOLEN BASES",
    "batter_walks": "BATTER WALKS",
    "batter_strikeouts": "BATTER STRIKEOUTS",
    "batter_singles": "SINGLES",
    "batter_doubles": "DOUBLES",
    "batter_triples": "TRIPLES",
    "pitcher_strikeouts": "PITCHER KS",
    "pitcher_hits_allowed": "PITCHER HITS ALLOWED",
    "pitcher_earned_runs": "PITCHER EARNED RUNS",
    "pitcher_outs": "PITCHER OUTS",
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _clean_text(value) -> str:
    return str(value or "").strip()


def _num(value):
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _normal_stat(row: pd.Series) -> str:
    stat = _clean_text(row.get("Stat") or row.get("StatType")).upper()
    if stat:
        return MARKET_TO_STAT.get(stat.lower(), stat)
    market_key = _clean_text(row.get("MarketKey") or row.get("Market")).lower()
    return MARKET_TO_STAT.get(market_key, market_key.upper())


def _normal_date(row: pd.Series, fallback_date: str = "") -> str:
    for col in ["GameDate", "Date", "CommenceDate", "SnapshotDate", "ResultDate"]:
        value = _clean_text(row.get(col))
        if value:
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.notna(parsed):
                return parsed.strftime("%Y-%m-%d")
    return fallback_date


def _split_game_label(game: str) -> tuple[str, str]:
    text = _clean_text(game)
    if "@" in text:
        left, right = text.split("@", 1)
        return _clean_text(left), _clean_text(right)
    if " at " in text.lower():
        left, right = text.lower().split(" at ", 1)
        return _clean_text(left.title()), _clean_text(right.title())
    return "", ""


def _grade(actual, line, direction: str) -> str:
    actual_num = _num(actual)
    line_num = _num(line)
    direction = _clean_text(direction).upper()
    if actual_num is None or line_num is None:
        return "Pending"
    if direction == "OVER":
        if actual_num > line_num:
            return "Hit"
        if actual_num < line_num:
            return "Miss"
        return "Push"
    if direction == "UNDER":
        if actual_num < line_num:
            return "Hit"
        if actual_num > line_num:
            return "Miss"
        return "Push"
    return "Pending"


def _build_gamelog_lookup(gamelogs: pd.DataFrame) -> dict:
    if gamelogs.empty or not {"Date", "Player"}.issubset(gamelogs.columns):
        return {}
    logs = gamelogs.copy()
    logs["DateKey"] = pd.to_datetime(logs["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    logs["PlayerKey"] = logs["Player"].fillna("").astype(str).str.strip().str.lower()
    lookup = {}
    for _, row in logs.dropna(subset=["DateKey"]).iterrows():
        key = (row["DateKey"], row["PlayerKey"])
        if key not in lookup:
            lookup[key] = row.to_dict()
    return lookup


def _side_probability(row: pd.Series, direction: str) -> float:
    over_odds = _num(row.get("OverOdds") if row.get("OverOdds") is not None else row.get("OpenOverOdds"))
    under_odds = _num(row.get("UnderOdds") if row.get("UnderOdds") is not None else row.get("OpenUnderOdds"))

    def implied(odds):
        if odds is None or odds == 0:
            return None
        return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

    over = implied(over_odds)
    under = implied(under_odds)
    if over is not None and under is not None and over + under > 0:
        over, under = over / (over + under), under / (over + under)
    side = over if direction == "OVER" else under
    return round(float(side) * 100, 1) if side is not None else 50.0


def build_rows(props: pd.DataFrame, gamelogs: pd.DataFrame, fallback_date: str = "") -> pd.DataFrame:
    if props.empty or gamelogs.empty:
        return pd.DataFrame()
    lookup = _build_gamelog_lookup(gamelogs)
    rows = []
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for _, prop in props.iterrows():
        player = _clean_text(prop.get("Player"))
        stat = _normal_stat(prop)
        stat_col = STAT_TO_LOG_COLUMN.get(stat)
        line = prop.get("CurrentLine") if pd.notna(prop.get("CurrentLine", pd.NA)) else prop.get("Line")
        game_date = _normal_date(prop, fallback_date=fallback_date)
        if not player or not stat_col or not game_date:
            continue
        actual_row = lookup.get((game_date, player.lower()))
        if not actual_row:
            continue
        actual = actual_row.get(stat_col)
        away, home = _split_game_label(prop.get("Game"))
        for direction, price_col in [("OVER", "OverOdds"), ("UNDER", "UnderOdds")]:
            outcome = _grade(actual, line, direction)
            confidence = _side_probability(prop, direction)
            rows.append({
                "SnapshotDate": _normal_date(prop, fallback_date=game_date),
                "SavedAt": now_text,
                "Sport": "MLB",
                "Method": "Historical Backfill",
                "PostseasonOnly": 0,
                "SampleMode": "historical",
                "Player": player,
                "Team": _clean_text(prop.get("Team") or actual_row.get("Team")),
                "Stat": stat,
                "Direction": direction,
                "Line": line,
                "Confidence": confidence,
                "RawConfidence": confidence,
                "MarketPrice": prop.get(price_col),
                "CurrentLine": line,
                "Book": _clean_text(prop.get("Book")),
                "BookCount": 1,
                "Matchup": f"{away} @ {home}".strip(" @") or _clean_text(prop.get("Game")),
                "Opponent": _clean_text(actual_row.get("Opp")),
                "GameDay": game_date,
                "Situations": "MLB Historical Backfill",
                "MethodLabels": "Historical Backfill",
                "MarketTags": "",
                "BaselineReason": f"Historical MLB {stat} market graded against player game log.",
                "WeightProfile": "historical",
                "VolatilityFlag": "ELEVATED" if stat in {"HOME RUNS", "TRIPLES", "STOLEN BASES"} else "STABLE",
                "MarketGate": "CLEAR",
                "ResultDate": game_date,
                "ResultValue": actual,
                "DaysToResult": 0 if outcome in {"Hit", "Miss", "Push"} else "",
                "OutcomeState": outcome,
                "MarketMoveBucket": "Historical",
                "MarketDepthBucket": "Single-Book",
                "SnapshotWrittenAt": now_text,
                "SourceFile": "MLB_Props_History.csv",
                "IsFloorPlay": False,
                "Hit_Binary": 1 if outcome == "Hit" else 0 if outcome == "Miss" else "",
                "ReviewTier": "Tier 2" if confidence >= 60 else "Tier 3",
                "IsBackfill": True,
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["ResultDate", "Matchup", "Player", "Stat", "Direction"]).reset_index(drop=True)


def build_rate_table(rows: pd.DataFrame, group_cols: list[str], bucket_type: str, min_sample: int = 3) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    resolved = rows[rows["OutcomeState"].isin(["Hit", "Miss"])].copy()
    out = []
    for keys, group in resolved.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        sample = int(len(group))
        if sample < min_sample:
            continue
        hits = int((group["OutcomeState"] == "Hit").sum())
        hit_rate = round(float(hits / sample) * 100, 1)
        row = {"BucketType": bucket_type, "Resolved": sample, "Hits": hits, "Misses": sample - hits, "HitRate": hit_rate}
        for col, value in zip(group_cols, keys):
            row[col] = value
        out.append(row)
    return pd.DataFrame(out).sort_values(["HitRate", "Resolved"], ascending=[False, False]) if out else pd.DataFrame()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade MLB historical prop rows against player game logs.")
    parser.add_argument("--props", default="", help="MLB prop history CSV. Defaults to data/historical/MLB_Props_History.csv when present.")
    parser.add_argument("--gamelogs", default=str(GAMELOGS_PATH), help="MLB player game logs CSV.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Resolved backfill output CSV.")
    parser.add_argument("--bucket-report", default=str(BUCKET_REPORT_PATH), help="Bucket report output CSV.")
    parser.add_argument("--player-profiles", default=str(PLAYER_PROFILE_PATH), help="Player profile output CSV.")
    parser.add_argument("--fallback-date", default="", help="Date to use when the prop input has no game date.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    props_path = Path(args.props) if args.props else DEFAULT_PROPS_PATH if DEFAULT_PROPS_PATH.exists() else FALLBACK_PROPS_PATH
    gamelogs_path = Path(args.gamelogs)
    props = _read_csv(props_path)
    gamelogs = _read_csv(gamelogs_path)
    rows = build_rows(props, gamelogs, fallback_date=args.fallback_date)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_path, index=False)
    bucket_report = pd.concat([
        build_rate_table(rows, ["Stat", "Direction"], "STAT_DIRECTION"),
        build_rate_table(rows, ["Player", "Stat", "Direction"], "PLAYER_STAT_DIRECTION"),
    ], ignore_index=True, sort=False) if not rows.empty else pd.DataFrame()
    Path(args.bucket_report).parent.mkdir(parents=True, exist_ok=True)
    bucket_report.to_csv(args.bucket_report, index=False)
    player_profiles = build_rate_table(rows, ["Player", "Team", "Stat", "Direction"], "PLAYER_PROFILE")
    Path(args.player_profiles).parent.mkdir(parents=True, exist_ok=True)
    player_profiles.to_csv(args.player_profiles, index=False)
    resolved = rows[rows["OutcomeState"].isin(["Hit", "Miss"])] if not rows.empty else pd.DataFrame()
    hit_rate = round(float((resolved["OutcomeState"] == "Hit").mean()) * 100, 1) if not resolved.empty else "-"
    print(f"Input props: {props_path}")
    print(f"Rows: {len(rows):,}")
    print(f"Resolved: {len(resolved):,}")
    print(f"Hit rate: {hit_rate}%")
    print(f"Saved: {output_path}")
    print(f"Bucket report: {args.bucket_report} ({len(bucket_report):,} rows)")
    print(f"Player profiles: {args.player_profiles} ({len(player_profiles):,} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
