"""Score THIS WEEK's live NFL props with the validated PropScore model.

Why this exists
---------------
calculate_nfl_prop_score.py only ever ran over finished, graded props: it reads and
writes data/tracking/NFL_AllPropResults*.csv and never touches data/props/NFL_Props.csv.
So the live board could only LOOK UP a 2024/2025 score for a matching
(player, stat, direction, line) and reuse it. Tonight's props had no score of their own.

research/nfl_edge/FINDINGS.md validated three angles out of sample and ends with
"In-season, point it at the live scored props for that week's slate". This produces
that file. It reuses score_rows() from calculate_nfl_prop_score unchanged, so a live
score is computed by exactly the model the backtest measured -- only the inputs are
assembled from live sources instead of from graded history.

What is honest about the inputs, in Week 1
------------------------------------------
  - Wind / game-script tags are fully live: they come from the game lines and the
    morning weather pull, so the wind angle needs nothing from the current season.
  - UsageStability comes from NFL_Player_Hit_Profiles.csv, which is built from
    2024-25. Early in a season that is a PRIOR, not a current-season read, and it
    sharpens as 2026 props are graded. The same approach the fantasy engine uses.
  - Rest days and the division flag are not available live, so SHORT_REST and
    DIVISION_GAME never fire here. Neither survived out-of-sample anyway (see
    FINDINGS.md "What did NOT hold").

One-sided markets (no two-way price to de-vig) are excluded. The research measured
de-vigged two-way props, so scoring a market the model was never validated on would
be inventing coverage.

Run: python score_live_nfl_props.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app import (
    build_football_live_prop_board,
    load_nfl_game_market_odds,
    load_nfl_live_props_feed,
    load_nfl_schedule,
)
from build_nfl_historical_calibration import contradiction_tags
from calculate_nfl_prop_score import score_rows

BASE_DIR = Path(__file__).resolve().parent
WEATHER_PATH = BASE_DIR / "data" / "context" / "NFL_GameWeather.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_LiveProps_Scored.csv"

OUTPUT_COLUMNS = [
    "Player", "Team", "Opponent", "Stat", "Direction", "Line", "RoleLabel",
    "Confidence", "MarketPrice", "MarketGate", "VolatilityFlag",
    "GameTotalLine", "GameSpreadLine", "ProjectedMargin", "WindMph", "Temperature", "Roof",
    "GameScriptTags", "ContradictionTags",
    "UsageStability", "MatchupAdvantage", "GameScriptFit", "LineValue",
    "VolatilityPenalty", "NGSModifier", "NGSNote", "BK_NFL_PropScore",
    "PropModelVersion", "Matchup", "GameDate", "Book", "ScoredAt",
]


def _num(value):
    return pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]


def _clean(value) -> str:
    return str(value or "").strip()


def build_game_script_tags(total, projected_margin, wind, temp_f, roof) -> str:
    """Identical thresholds to the game context in build_nfl_historical_calibration.

    Kept deliberately in lockstep: if a live tag were defined differently from the
    one the model was fitted on, a live PropScore would not be comparable to the
    backtested one and the validated ROI would not carry over. Tags that need a
    finished game (actual margin) or data with no live source (rest, division) are
    simply absent rather than approximated.
    """
    tags = []
    margin = _num(projected_margin)
    if not pd.isna(margin):
        margin = float(margin)
        if margin >= 10:
            tags.append("PROJECTED_BLOWOUT_WIN")
        elif margin >= 7:
            tags.append("PROJECTED_CLEAR_WIN")
        elif margin <= -10:
            tags.append("PROJECTED_BLOWOUT_TRAIL")
        elif margin <= -7:
            tags.append("PROJECTED_TRAIL")
        elif abs(margin) <= 2.5:
            tags.append("PROJECTED_TIGHT_GAME")
    total_line = _num(total)
    if not pd.isna(total_line):
        if float(total_line) >= 50:
            tags.append("HIGH_TOTAL")
        elif float(total_line) <= 42:
            tags.append("LOW_TOTAL")
    wind_mph = _num(wind)
    if not pd.isna(wind_mph) and float(wind_mph) >= 15:
        tags.append("WIND_15_PLUS")
    temp = _num(temp_f)
    if not pd.isna(temp) and float(temp) <= 32:
        tags.append("COLD_WEATHER")
    if _clean(roof).lower() in {"dome", "closed"}:
        tags.append("DOME")
    return " | ".join(tags)


def load_weather() -> dict:
    """(date, home team) -> forecast. Empty when the morning pull has not run, in
    which case wind tags simply never fire and the run says so."""
    if not WEATHER_PATH.exists():
        return {}
    try:
        frame = pd.read_csv(WEATHER_PATH)
    except (pd.errors.EmptyDataError, OSError):
        return {}
    lookup = {}
    for _, row in frame.iterrows():
        key = (_clean(row.get("Date")), _clean(row.get("HomeTeam")).lower())
        if key[1]:
            lookup[key] = row.to_dict()
    return lookup


def load_game_lines() -> list[dict]:
    odds = load_nfl_game_market_odds()
    if odds is None or odds.empty:
        return []
    return odds.to_dict("records")


def match_game(row: dict, games: list[dict]) -> dict:
    """Find the game-lines row for a board row, by full or abbreviated home name."""
    home = _clean(row.get("home")).lower()
    away = _clean(row.get("away")).lower()
    for game in games:
        candidates = {_clean(game.get(col)).lower() for col in ("Home", "HomeFull")}
        away_candidates = {_clean(game.get(col)).lower() for col in ("Away", "AwayFull")}
        if home in candidates and (not away or away in away_candidates or not away_candidates):
            return game
    return {}


def team_is_home(team: str, game: dict) -> bool | None:
    team_key = _clean(team).lower()
    if not team_key:
        return None
    if team_key in {_clean(game.get(col)).lower() for col in ("Home", "HomeFull")}:
        return True
    if team_key in {_clean(game.get(col)).lower() for col in ("Away", "AwayFull")}:
        return False
    return None


def build_live_frame(date_filter: str = "all") -> tuple[pd.DataFrame, dict]:
    props, refresh_meta = load_nfl_live_props_feed()
    if props is None or props.empty:
        return pd.DataFrame(), {"prop_rows": 0}

    # Player -> team, taken from the feed: the board row does not carry it, and the
    # team is what turns a home spread into THIS player's projected margin.
    team_by_player = {}
    if "Player" in props.columns and "Team" in props.columns:
        for player, team in zip(props["Player"], props["Team"]):
            name = _clean(player)
            if name and name not in team_by_player:
                team_by_player[name] = _clean(team)

    board = build_football_live_prop_board(
        props,
        load_nfl_game_market_odds(),
        load_nfl_schedule(),
        method_key="props",
        date_filter=date_filter,
        sport_key="nfl",
    )
    games = load_game_lines()
    weather = load_weather()

    stats = {
        "prop_rows": int(len(props)),
        "board_rows": len(board),
        "one_sided_skipped": 0,
        "no_game_line": 0,
        "with_wind": 0,
        "weather_rows": len(weather),
    }

    records = []
    for row in board:
        if row.get("one_sided_price"):
            stats["one_sided_skipped"] += 1
            continue
        player = _clean(row.get("player"))
        team = team_by_player.get(player, "")
        game = match_game(row, games)
        if not game:
            stats["no_game_line"] += 1
        is_home = team_is_home(team, game) if game else None

        spread = _num(game.get("Spread")) if game else pd.NA
        total = _num(game.get("Total")) if game else pd.NA
        projected_margin = pd.NA
        if not pd.isna(spread) and is_home is not None:
            # Spread is the HOME line (negative = home favoured), same convention as
            # nflverse spread_line, so flip it for the away side.
            projected_margin = -float(spread) if is_home else float(spread)

        game_date = _clean(game.get("Date")) if game else _clean(row.get("date"))
        forecast = weather.get((game_date, _clean(row.get("home")).lower()), {})
        wind = forecast.get("WindMph", pd.NA)
        temp = forecast.get("TempF", pd.NA)
        roof = forecast.get("Roof", "")
        if not pd.isna(_num(wind)) and float(_num(wind)) >= 15:
            stats["with_wind"] += 1

        stat = _clean(row.get("stat")).upper()
        direction = _clean(row.get("direction")).upper() or "OVER"
        game_tags = build_game_script_tags(total, projected_margin, wind, temp, roof)

        records.append({
            "Player": player,
            "Team": team,
            "Opponent": _clean(row.get("away") if is_home else row.get("home")),
            "Stat": stat,
            "Direction": direction,
            "Line": row.get("line"),
            "RoleLabel": _clean(row.get("stat_family")).upper(),
            # The de-vigged market probability, which is what the Confidence column
            # holds in the graded history the model was fitted on.
            "Confidence": row.get("market_prob"),
            "MarketPrice": row.get("market_price"),
            "MarketGate": "CLEAR",
            "VolatilityFlag": "STABLE",
            "GameTotalLine": None if pd.isna(total) else float(total),
            "GameSpreadLine": None if pd.isna(spread) else float(spread),
            "ProjectedMargin": None if pd.isna(projected_margin) else float(projected_margin),
            "WindMph": None if pd.isna(_num(wind)) else float(_num(wind)),
            "Temperature": None if pd.isna(_num(temp)) else float(_num(temp)),
            "Roof": _clean(roof),
            "GameScriptTags": game_tags,
            "ContradictionTags": contradiction_tags(stat, direction, game_tags),
            "Matchup": _clean(row.get("matchup")),
            "GameDate": game_date,
            "Book": _clean(row.get("best_book")),
        })

    return pd.DataFrame(records), stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Score this week's live NFL props with the validated PropScore model.")
    parser.add_argument("--date", default="all", help="Board date filter: all, today, tomorrow. Default: all")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    frame, stats = build_live_frame(date_filter=args.date)
    print("=" * 60)
    print("NFL LIVE PROP SCORING")
    print("=" * 60)
    if frame.empty:
        print(f"No two-way live NFL props to score (feed rows: {stats.get('prop_rows', 0)}).")
        print("Nothing written; the existing file is left alone.")
        return 0

    scored = score_rows(frame)
    scored["ScoredAt"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    for column in OUTPUT_COLUMNS:
        if column not in scored.columns:
            scored[column] = ""
    scored = scored[OUTPUT_COLUMNS].sort_values("BK_NFL_PropScore", ascending=False)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(output_path, index=False)

    print(f"Feed rows: {stats['prop_rows']:,} | board rows: {stats['board_rows']:,}")
    print(f"Scored: {len(scored):,} | one-sided skipped: {stats['one_sided_skipped']:,} | no game line: {stats['no_game_line']:,}")
    print(f"Weather rows loaded: {stats['weather_rows']:,} | props in 15+ mph wind: {stats['with_wind']:,}")
    if not stats["weather_rows"]:
        print("[WARN] No weather file, so WIND_15_PLUS never fired. Run fetch_nfl_weather.py.")
    score = pd.to_numeric(scored["BK_NFL_PropScore"], errors="coerce")
    print(f"PropScore >= 20 (premium band): {int((score >= 20).sum()):,}")
    print(f"PropScore >= 10 (top plays):    {int((score >= 10).sum()):,}")
    wind_support = scored["ContradictionTags"].astype(str).str.contains("WIND_UNDER_SUPPORT").sum()
    print(f"Wind-under support tags:        {int(wind_support):,}")
    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
