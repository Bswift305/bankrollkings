from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
HISTORICAL_DIR = BASE_DIR / "data" / "historical"
TRACKING_DIR = BASE_DIR / "data" / "tracking"
PROPS_PATH = HISTORICAL_DIR / "NFL_Props_History.csv"
GAMES_PATH = HISTORICAL_DIR / "NFL_Games_nfldata.csv"
OUTPUT_PATH = TRACKING_DIR / "NFL_AllPropResults.csv"
GAME_SCRIPT_REPORT_PATH = TRACKING_DIR / "NFL_GameScript_Calibration_Report.csv"
PLAYER_PROFILE_PATH = TRACKING_DIR / "NFL_Player_Hit_Profiles.csv"

STAT_FAMILY = {
    "PASS YDS": "PASSING",
    "PASS ATT": "PASSING",
    "PASS COMP": "PASSING",
    "PASS INTS": "PASSING",
    "PASS INT": "PASSING",
    "PASS TDS": "PASSING",
    "RUSH YDS": "RUSHING",
    "RUSH ATT": "RUSHING",
    "RUSH TDS": "RUSHING",
    "REC YDS": "RECEIVING",
    "RECEPTIONS": "RECEIVING",
    "REC TDS": "RECEIVING",
}


def american_to_implied(odds) -> float | None:
    value = pd.to_numeric(pd.Series([odds]), errors="coerce").iloc[0]
    if pd.isna(value) or float(value) == 0:
        return None
    value = float(value)
    if value < 0:
        return abs(value) / (abs(value) + 100)
    return 100 / (value + 100)


def devig_side_probability(over_odds, under_odds, direction: str) -> float | None:
    over_prob = american_to_implied(over_odds)
    under_prob = american_to_implied(under_odds)
    if over_prob is None and under_prob is None:
        return None
    if over_prob is not None and under_prob is not None and over_prob + under_prob > 0:
        total_prob = over_prob + under_prob
        over_prob = over_prob / total_prob
        under_prob = under_prob / total_prob
    side_prob = over_prob if direction == "OVER" else under_prob
    return round(float(side_prob) * 100, 1) if side_prob is not None else None


def grade_prop(actual, line, direction: str) -> str:
    actual_num = pd.to_numeric(pd.Series([actual]), errors="coerce").iloc[0]
    line_num = pd.to_numeric(pd.Series([line]), errors="coerce").iloc[0]
    if pd.isna(actual_num) or pd.isna(line_num):
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


def normalize_team(value) -> str:
    return str(value or "").strip().upper()


def build_game_lookup(games: pd.DataFrame) -> dict:
    lookup = {}
    if games.empty:
        return lookup
    games = games.copy()
    games["season"] = pd.to_numeric(games.get("season"), errors="coerce")
    games["week"] = pd.to_numeric(games.get("week"), errors="coerce")
    for _, row in games.iterrows():
        season = row.get("season")
        week = row.get("week")
        if pd.isna(season) or pd.isna(week):
            continue
        away = normalize_team(row.get("away_team"))
        home = normalize_team(row.get("home_team"))
        key = (int(season), int(week), away, home)
        lookup[key] = row.to_dict()
    return lookup


def team_game_context(prop: pd.Series, game_lookup: dict) -> dict:
    season = pd.to_numeric(pd.Series([prop.get("Season")]), errors="coerce").iloc[0]
    week = pd.to_numeric(pd.Series([prop.get("Week")]), errors="coerce").iloc[0]
    if pd.isna(season) or pd.isna(week):
        return {}
    away = normalize_team(prop.get("AwayAbbr"))
    home = normalize_team(prop.get("HomeAbbr"))
    team = normalize_team(prop.get("Team"))
    opponent = normalize_team(prop.get("Opponent"))
    game = game_lookup.get((int(season), int(week), away, home))
    if not game:
        return {}

    spread = pd.to_numeric(pd.Series([game.get("spread_line")]), errors="coerce").iloc[0]
    total_line = pd.to_numeric(pd.Series([game.get("total_line")]), errors="coerce").iloc[0]
    wind = pd.to_numeric(pd.Series([game.get("wind")]), errors="coerce").iloc[0]
    temp = pd.to_numeric(pd.Series([game.get("temp")]), errors="coerce").iloc[0]
    away_score = pd.to_numeric(pd.Series([game.get("away_score")]), errors="coerce").iloc[0]
    home_score = pd.to_numeric(pd.Series([game.get("home_score")]), errors="coerce").iloc[0]
    away_rest = pd.to_numeric(pd.Series([game.get("away_rest")]), errors="coerce").iloc[0]
    home_rest = pd.to_numeric(pd.Series([game.get("home_rest")]), errors="coerce").iloc[0]
    is_home = team == home
    projected_margin = None
    if not pd.isna(spread):
        # nflverse spread_line is the home-team spread. Negative means home is favored.
        projected_margin = -float(spread) if is_home else float(spread)
    actual_margin = None
    if not pd.isna(away_score) and not pd.isna(home_score):
        actual_margin = float(home_score - away_score) if is_home else float(away_score - home_score)
    rest_days = home_rest if is_home else away_rest
    tags = []
    if projected_margin is not None:
        if projected_margin >= 10:
            tags.append("PROJECTED_BLOWOUT_WIN")
        elif projected_margin >= 7:
            tags.append("PROJECTED_CLEAR_WIN")
        elif projected_margin <= -10:
            tags.append("PROJECTED_BLOWOUT_TRAIL")
        elif projected_margin <= -7:
            tags.append("PROJECTED_TRAIL")
        elif abs(projected_margin) <= 2.5:
            tags.append("PROJECTED_TIGHT_GAME")
    if not pd.isna(total_line):
        if float(total_line) >= 50:
            tags.append("HIGH_TOTAL")
        elif float(total_line) <= 42:
            tags.append("LOW_TOTAL")
    if not pd.isna(wind) and float(wind) >= 15:
        tags.append("WIND_15_PLUS")
    if not pd.isna(temp) and float(temp) <= 32:
        tags.append("COLD_WEATHER")
    if str(game.get("roof") or "").strip().lower() in {"dome", "closed"}:
        tags.append("DOME")
    if not pd.isna(rest_days) and float(rest_days) <= 4:
        tags.append("SHORT_REST")
    if str(game.get("div_game") or "").strip() in {"1", "1.0", "True", "true"}:
        tags.append("DIVISION_GAME")
    if actual_margin is not None:
        if actual_margin >= 17:
            tags.append("ACTUAL_BLOWOUT_WIN")
        elif actual_margin <= -17:
            tags.append("ACTUAL_BLOWOUT_LOSS")
    return {
        "GameDate": game.get("gameday", ""),
        "Matchup": f"{away} @ {home}",
        "GameTotalLine": round(float(total_line), 1) if not pd.isna(total_line) else "",
        "GameSpreadLine": round(float(spread), 1) if not pd.isna(spread) else "",
        "ProjectedMargin": round(float(projected_margin), 1) if projected_margin is not None else "",
        "ActualMargin": round(float(actual_margin), 1) if actual_margin is not None else "",
        "WindMph": round(float(wind), 1) if not pd.isna(wind) else "",
        "Temperature": round(float(temp), 1) if not pd.isna(temp) else "",
        "Roof": game.get("roof", ""),
        "Surface": game.get("surface", ""),
        "RestDays": round(float(rest_days), 1) if not pd.isna(rest_days) else "",
        "GameScriptTags": " | ".join(tags),
    }


def contradiction_tags(stat: str, direction: str, game_tags: str) -> str:
    stat_upper = str(stat or "").upper()
    tags = set(str(game_tags or "").split(" | "))
    flags = []
    if stat_upper.startswith("RUSH") and direction == "OVER" and {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        flags.append("TRAILING_RB_RUSH_OVER_RISK")
    if stat_upper.startswith("RUSH") and direction == "UNDER" and {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        flags.append("TRAILING_RB_UNDER_SUPPORT")
    if stat_upper in {"PASS YDS", "PASS ATT", "PASS COMP"} and direction == "OVER" and {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        flags.append("TRAILING_PASS_VOLUME_SUPPORT")
    if stat_upper in {"PASS YDS", "REC YDS"} and direction == "OVER" and "WIND_15_PLUS" in tags:
        flags.append("WIND_PASS_OVER_RISK")
    if stat_upper in {"PASS YDS", "REC YDS"} and direction == "UNDER" and "WIND_15_PLUS" in tags:
        flags.append("WIND_UNDER_SUPPORT")
    if stat_upper.startswith("RUSH") and direction == "OVER" and {"PROJECTED_CLEAR_WIN", "PROJECTED_BLOWOUT_WIN"} & tags:
        flags.append("POSITIVE_SCRIPT_RUSH_SUPPORT")
    if stat_upper in {"PASS YDS", "REC YDS", "RECEPTIONS"} and direction == "OVER" and "HIGH_TOTAL" in tags:
        flags.append("HIGH_TOTAL_VOLUME_SUPPORT")
    if stat_upper in {"PASS YDS", "REC YDS", "RECEPTIONS"} and direction == "UNDER" and "LOW_TOTAL" in tags:
        flags.append("LOW_TOTAL_UNDER_SUPPORT")
    return " | ".join(flags)


def build_rows(props: pd.DataFrame, games: pd.DataFrame, seasons: set[int] | None = None) -> pd.DataFrame:
    game_lookup = build_game_lookup(games)
    output_rows = []
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    props = props.copy()
    props["Season"] = pd.to_numeric(props.get("Season"), errors="coerce")
    props["Week"] = pd.to_numeric(props.get("Week"), errors="coerce")
    if seasons:
        props = props[props["Season"].isin(seasons)].copy()
    props = props.dropna(subset=["Season", "Week", "Player", "Stat", "Line"]).copy()

    for _, prop in props.iterrows():
        context = team_game_context(prop, game_lookup)
        for direction, price_col in [("OVER", "OverOdds"), ("UNDER", "UnderOdds")]:
            outcome = grade_prop(prop.get("Actual"), prop.get("Line"), direction)
            confidence = devig_side_probability(prop.get("OverOdds"), prop.get("UnderOdds"), direction)
            if confidence is None:
                confidence = 50.0
            game_tags = context.get("GameScriptTags", "")
            qc_tags = contradiction_tags(prop.get("Stat"), direction, game_tags)
            situations = " | ".join([item for item in [game_tags, qc_tags] if item])
            stat = str(prop.get("Stat") or "").strip()
            season = int(prop.get("Season"))
            week = int(prop.get("Week"))
            price = prop.get(price_col)
            output_rows.append({
                "SnapshotDate": prop.get("SnapshotDate", ""),
                "SavedAt": now_text,
                "Sport": "NFL",
                "Method": "Historical Backfill",
                "PostseasonOnly": 0,
                "SampleMode": "historical",
                "Player": prop.get("Player", ""),
                "Team": prop.get("Team", ""),
                "Stat": stat,
                "Direction": direction,
                "Line": prop.get("Line", ""),
                "Confidence": confidence,
                "RawConfidence": confidence,
                "Avg": "",
                "WeightedOverRate": "",
                "WeightedUnderRate": "",
                "MarketPrice": price,
                "CurrentLine": prop.get("Line", ""),
                "OpenLine": "",
                "CloseLine": "",
                "BetLine": prop.get("Line", ""),
                "OpenPrice": "",
                "ClosePrice": "",
                "BetPrice": price,
                "LineMove": "",
                "ClvLine": "",
                "ClvPricePct": "",
                "MarketGapPct": "",
                "MarketViewLabel": "Historical Market",
                "MarketViewNote": "Backfilled from historical NFL player prop market.",
                "Book": prop.get("Book", ""),
                "BookCount": 1,
                "EdgePct": "",
                "EvPct": "",
                "Matchup": context.get("Matchup", prop.get("Game", "")),
                "Opponent": prop.get("Opponent", ""),
                "GameDay": context.get("GameDate", prop.get("CommenceTime", "")),
                "Situations": situations,
                "MethodLabels": "Historical Backfill",
                "MarketTags": qc_tags,
                "BaselineReason": f"{season} Week {week} historical {stat} market.",
                "WeightProfile": "historical",
                "SeriesGameNumber": week,
                "SeriesWeight": "",
                "VolatilityFlag": "ELEVATED" if stat.upper() in {"PASS TDS", "PASS INT", "REC TDS", "RUSH TDS"} else "STABLE",
                "MarketGate": "HOLD" if "RISK" in qc_tags else "CLEAR",
                "BetTier": "",
                "RoleLabel": STAT_FAMILY.get(stat.upper(), "UNSPECIFIED"),
                "ReturnImpactPct": "",
                "ResultDate": context.get("GameDate", prop.get("CommenceTime", "")),
                "ResultValue": prop.get("Actual", ""),
                "DaysToResult": 0 if outcome in {"Hit", "Miss", "Push"} else "",
                "OutcomeState": outcome,
                "MarketMoveBucket": "Historical",
                "MarketDepthBucket": "Single-Book",
                "SnapshotWrittenAt": now_text,
                "SourceFile": PROPS_PATH.name,
                "IsFloorPlay": False,
                "Hit_Binary": 1 if outcome == "Hit" else 0 if outcome == "Miss" else "",
                "ReviewTier": "Tier 2" if confidence >= 60 else "Tier 3",
                "ResultDay": context.get("GameDate", ""),
                "Season": season,
                "Week": week,
                "SeasonType": prop.get("SeasonType", ""),
                "IsBackfill": True,
                "GameScriptTags": game_tags,
                "ContradictionTags": qc_tags,
                **context,
            })
    df = pd.DataFrame(output_rows)
    if df.empty:
        return df
    return df.sort_values(["Season", "Week", "Matchup", "Player", "Stat", "Direction"]).reset_index(drop=True)


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows built."
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    hit_rate = round(float((resolved["OutcomeState"] == "Hit").mean()) * 100, 1) if not resolved.empty else None
    lines = [
        f"Rows: {len(df):,}",
        f"Resolved: {len(resolved):,}",
        f"Hit rate: {hit_rate if hit_rate is not None else '-'}%",
    ]
    if "Season" in df.columns:
        lines.append("Seasons: " + ", ".join(str(int(x)) for x in sorted(df["Season"].dropna().unique())))
    if not resolved.empty:
        by_tag = (
            resolved.assign(Tag=resolved["ContradictionTags"].replace("", pd.NA))
            .dropna(subset=["Tag"])
            .groupby("Tag")["OutcomeState"]
            .agg(sample="count", hit_rate=lambda s: round(float((s == "Hit").mean()) * 100, 1))
            .sort_values(["sample", "hit_rate"], ascending=[False, False])
            .head(8)
        )
        if not by_tag.empty:
            lines.append("Top game-script QC buckets:")
            for tag, row in by_tag.iterrows():
                lines.append(f"  {tag}: {row['hit_rate']}% ({int(row['sample'])})")
    return "\n".join(lines)


def rate_table(df: pd.DataFrame, group_cols: list[str], bucket_type: str, min_sample: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    if resolved.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in resolved.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        if any(not str(part or "").strip() for part in keys):
            continue
        sample = int(len(group))
        if sample < min_sample:
            continue
        hits = int((group["OutcomeState"] == "Hit").sum())
        misses = int((group["OutcomeState"] == "Miss").sum())
        hit_rate = hits / sample if sample else None
        rows.append({
            "BucketType": bucket_type,
            "BucketLabel": " | ".join(str(part) for part in keys),
            "SampleSize": sample,
            "Hits": hits,
            "Misses": misses,
            "HitRate": round(hit_rate * 100, 1) if hit_rate is not None else "",
        })
    if not rows:
        return pd.DataFrame(columns=["BucketType", "BucketLabel", "SampleSize", "Hits", "Misses", "HitRate"])
    out = pd.DataFrame(rows)
    return out.sort_values(["HitRate", "SampleSize"], ascending=[False, False]).reset_index(drop=True)


def build_game_script_report(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["BucketType", "BucketLabel", "SampleSize", "Hits", "Misses", "HitRate"])
    frames = []
    frames.append(rate_table(df, ["Stat", "Direction"], "Stat + Direction"))
    frames.append(rate_table(df, ["Stat", "Direction", "MarketGate"], "Stat + Direction + Gate"))
    exploded_game = df.copy()
    exploded_game["GameScriptTag"] = exploded_game.get("GameScriptTags", "").fillna("").astype(str).str.split(" | ", regex=False)
    exploded_game = exploded_game.explode("GameScriptTag")
    exploded_game["GameScriptTag"] = exploded_game["GameScriptTag"].fillna("").astype(str).str.strip()
    exploded_game = exploded_game[exploded_game["GameScriptTag"] != ""].copy()
    frames.append(rate_table(exploded_game, ["GameScriptTag", "Stat", "Direction"], "Game Script + Stat + Direction"))
    exploded_qc = df.copy()
    exploded_qc["ContradictionTag"] = exploded_qc.get("ContradictionTags", "").fillna("").astype(str).str.split(" | ", regex=False)
    exploded_qc = exploded_qc.explode("ContradictionTag")
    exploded_qc["ContradictionTag"] = exploded_qc["ContradictionTag"].fillna("").astype(str).str.strip()
    exploded_qc = exploded_qc[exploded_qc["ContradictionTag"] != ""].copy()
    frames.append(rate_table(exploded_qc, ["ContradictionTag", "Stat", "Direction"], "QC Tag + Stat + Direction"))
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["BucketType", "BucketLabel", "SampleSize", "Hits", "Misses", "HitRate"])
    report = pd.concat(frames, ignore_index=True, sort=False)
    return report.sort_values(["BucketType", "HitRate", "SampleSize"], ascending=[True, False, False]).reset_index(drop=True)


def reliability_label(sample: int, hit_rate_pct) -> str:
    if hit_rate_pct in ["", None] or pd.isna(hit_rate_pct):
        return "SMALL SAMPLE"
    rate = float(hit_rate_pct) / 100
    if sample < 10:
        return "SMALL SAMPLE"
    if sample >= 20 and rate >= 0.65:
        return "ANCHOR"
    if sample >= 10 and rate >= 0.60:
        return "WATCH"
    if sample >= 10 and rate < 0.52:
        return "AVOID"
    return "DEVELOPING"


def model_accuracy_label(avg_confidence, hit_rate_pct) -> str:
    if avg_confidence in ["", None] or hit_rate_pct in ["", None] or pd.isna(avg_confidence) or pd.isna(hit_rate_pct):
        return "CALIBRATED"
    conf = float(avg_confidence)
    rate = float(hit_rate_pct) / 100
    if conf >= 60 and rate < 0.48:
        return "OVERVALUED"
    if conf <= 52 and rate >= 0.58:
        return "UNDERVALUED"
    return "CALIBRATED"


def build_player_profiles(df: pd.DataFrame) -> pd.DataFrame:
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy() if not df.empty else pd.DataFrame()
    if resolved.empty:
        return pd.DataFrame(columns=[
            "Player", "Team", "Stat", "Direction", "Resolved", "Hits", "Misses",
            "HitRate", "AvgLine", "AvgConfidence", "Reliability", "ModelAccuracy"
        ])
    resolved["LineNum"] = pd.to_numeric(resolved.get("Line"), errors="coerce")
    resolved["ConfidenceNum"] = pd.to_numeric(resolved.get("Confidence"), errors="coerce")
    rows = []
    for keys, group in resolved.groupby(["Player", "Team", "Stat", "Direction"], dropna=False):
        player, team, stat, direction = [str(part or "").strip() for part in keys]
        if not player or not stat or not direction:
            continue
        sample = int(len(group))
        hits = int((group["OutcomeState"] == "Hit").sum())
        misses = int((group["OutcomeState"] == "Miss").sum())
        hit_rate = round(float(hits / sample) * 100, 1) if sample else ""
        avg_conf = group["ConfidenceNum"].mean()
        rows.append({
            "Player": player,
            "Team": team,
            "Stat": stat,
            "Direction": direction,
            "Resolved": sample,
            "Hits": hits,
            "Misses": misses,
            "HitRate": hit_rate,
            "AvgLine": round(float(group["LineNum"].mean()), 1) if not pd.isna(group["LineNum"].mean()) else "",
            "AvgConfidence": round(float(avg_conf), 1) if not pd.isna(avg_conf) else "",
            "Reliability": reliability_label(sample, hit_rate),
            "ModelAccuracy": model_accuracy_label(avg_conf, hit_rate),
        })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["Reliability", "HitRate", "Resolved"], ascending=[True, False, False]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build resolved NFL historical calibration rows from local props, player stats, and game context.")
    parser.add_argument("--props", default=str(PROPS_PATH), help="Historical NFL prop CSV.")
    parser.add_argument("--games", default=str(GAMES_PATH), help="NFL games/context CSV.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output tracking CSV.")
    parser.add_argument("--game-script-report", default=str(GAME_SCRIPT_REPORT_PATH), help="Output game-script calibration report CSV.")
    parser.add_argument("--player-profiles", default=str(PLAYER_PROFILE_PATH), help="Output NFL player hit-profile CSV.")
    parser.add_argument("--season", action="append", type=int, help="Season to include. Can be supplied multiple times. Defaults to all in props file.")
    return parser.parse_args()


def load_games_with_pbp_exports(games_path: Path) -> pd.DataFrame:
    frames = []
    if games_path.exists():
        frames.append(pd.read_csv(games_path, low_memory=False))
    for path in sorted(HISTORICAL_DIR.glob("NFL_Games_*_from_pbp.csv")):
        if path.resolve() == games_path.resolve():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    games = pd.concat(frames, ignore_index=True, sort=False)
    if "game_type" not in games.columns and "season_type" in games.columns:
        games["game_type"] = games["season_type"]
    if "season_type" not in games.columns and "game_type" in games.columns:
        games["season_type"] = games["game_type"]
    dedupe_cols = [col for col in ["season", "week", "away_team", "home_team"] if col in games.columns]
    if dedupe_cols:
        games = games.drop_duplicates(subset=dedupe_cols, keep="last")
    return games


def main() -> int:
    args = parse_args()
    props_path = Path(args.props)
    games_path = Path(args.games)
    output_path = Path(args.output)
    game_script_report_path = Path(args.game_script_report)
    player_profile_path = Path(args.player_profiles)
    props = pd.read_csv(props_path, low_memory=False)
    games = load_games_with_pbp_exports(games_path)
    rows = build_rows(props, games, set(args.season or []))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_path, index=False)
    game_script_report = build_game_script_report(rows)
    game_script_report_path.parent.mkdir(parents=True, exist_ok=True)
    game_script_report.to_csv(game_script_report_path, index=False)
    player_profiles = build_player_profiles(rows)
    player_profile_path.parent.mkdir(parents=True, exist_ok=True)
    player_profiles.to_csv(player_profile_path, index=False)
    print(summarize(rows))
    print(f"Saved: {output_path}")
    print(f"Game-script report: {game_script_report_path} ({len(game_script_report):,} buckets)")
    print(f"Player profiles: {player_profile_path} ({len(player_profiles):,} buckets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
