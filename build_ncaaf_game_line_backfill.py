from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "historical" / "NCAAF_GameLines_History.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_GameLineResults.csv"
MODEL_VERSION = "NCAAF_GameLineBackfill_v1"


def _num(value):
    return pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]


def _outcome(score_value: float, line: float, direction: str) -> str:
    if pd.isna(score_value) or pd.isna(line):
        return "Pending"
    if direction == "OVER":
        if score_value > line:
            return "Hit"
        if score_value < line:
            return "Miss"
        return "Push"
    if direction == "UNDER":
        if score_value < line:
            return "Hit"
        if score_value > line:
            return "Miss"
        return "Push"
    return "Pending"


def _cover_outcome(team_score: float, opponent_score: float, spread: float) -> str:
    if pd.isna(team_score) or pd.isna(opponent_score) or pd.isna(spread):
        return "Pending"
    margin_against_spread = team_score + spread - opponent_score
    if margin_against_spread > 0:
        return "Hit"
    if margin_against_spread < 0:
        return "Miss"
    return "Push"


def _line_bucket(value) -> str:
    line = _num(value)
    if pd.isna(line):
        return "Unknown"
    absolute = abs(float(line))
    if absolute < 3:
        return "Pick/Short"
    if absolute < 7:
        return "3-6.5"
    if absolute < 14:
        return "7-13.5"
    return "14+"


def build_results(history: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, game in history.iterrows():
        date = game.get("Date")
        season = game.get("Season")
        week = game.get("Week")
        away = str(game.get("Away") or "").strip()
        home = str(game.get("Home") or "").strip()
        if not away or not home:
            continue

        away_score = _num(game.get("AwayScore"))
        home_score = _num(game.get("HomeScore"))
        actual_total = away_score + home_score if not pd.isna(away_score) and not pd.isna(home_score) else pd.NA
        home_spread = _num(game.get("HomeSpread") if "HomeSpread" in game else game.get("Spread"))
        away_spread = _num(game.get("AwaySpread"))
        if pd.isna(away_spread) and not pd.isna(home_spread):
            away_spread = -float(home_spread)
        total = _num(game.get("CloseTotal") if "CloseTotal" in game else game.get("Total"))
        if pd.isna(total):
            total = _num(game.get("Total"))
        source = str(game.get("Source") or "historical").strip()
        game_label = f"{away} @ {home}"

        spread_rows = [
            (home, away, home_spread, home_score, away_score),
            (away, home, away_spread, away_score, home_score),
        ]
        for team, opponent, line, team_score, opponent_score in spread_rows:
            if pd.isna(line):
                continue
            rows.append({
                "Sport": "NCAAF",
                "Season": season,
                "Week": week,
                "GameDate": date,
                "ResultDate": date,
                "Game": game_label,
                "Team": team,
                "Opponent": opponent,
                "HomeTeam": home,
                "AwayTeam": away,
                "MarketType": "SPREAD",
                "Method": "Game Line Backfill",
                "Stat": "SPREAD",
                "Direction": "COVER",
                "Line": round(float(line), 2),
                "Actual": round(float(team_score + line - opponent_score), 2) if not pd.isna(team_score) and not pd.isna(opponent_score) else pd.NA,
                "TeamScore": team_score,
                "OpponentScore": opponent_score,
                "ActualTotal": actual_total,
                "OutcomeState": _cover_outcome(team_score, opponent_score, line),
                "Confidence": 55,
                "WeightProfile": "cfb_game_line",
                "MarketGate": "CLEAR",
                "VolatilityFlag": "STABLE" if abs(float(line)) < 14 else "HIGH_SPREAD",
                "Situations": f"SPREAD_BUCKET={_line_bucket(line)}",
                "IsBackfill": True,
                "ModelVersion": MODEL_VERSION,
                "Source": source,
            })

        if not pd.isna(total):
            for direction in ("OVER", "UNDER"):
                rows.append({
                    "Sport": "NCAAF",
                    "Season": season,
                    "Week": week,
                    "GameDate": date,
                    "ResultDate": date,
                    "Game": game_label,
                    "Team": "",
                    "Opponent": "",
                    "HomeTeam": home,
                    "AwayTeam": away,
                    "MarketType": "TOTAL",
                    "Method": "Game Total Backfill",
                    "Stat": "TOTAL",
                    "Direction": direction,
                    "Line": round(float(total), 2),
                    "Actual": actual_total,
                    "TeamScore": pd.NA,
                    "OpponentScore": pd.NA,
                    "ActualTotal": actual_total,
                    "OutcomeState": _outcome(actual_total, total, direction),
                    "Confidence": 55,
                    "WeightProfile": "cfb_total",
                    "MarketGate": "CLEAR",
                    "VolatilityFlag": "STABLE",
                    "Situations": "TOTAL_BACKFILL",
                    "IsBackfill": True,
                    "ModelVersion": MODEL_VERSION,
                    "Source": source,
                })
    return pd.DataFrame(rows)


def main() -> int:
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing NCAAF historical game lines: {INPUT_PATH}")
    history = pd.read_csv(INPUT_PATH)
    results = build_results(history)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTPUT_PATH, index=False)
    resolved = int(results.get("OutcomeState", pd.Series(dtype=str)).isin(["Hit", "Miss", "Push"]).sum()) if not results.empty else 0
    print(f"Wrote {len(results)} NCAAF game-line backfill rows to {OUTPUT_PATH}")
    print(f"Resolved rows: {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
