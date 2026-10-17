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
        # EXACT provider identity for the game-ID reconciliation. Team/Opponent use the raw CFBD names
        # (names are presentation-only identity, reconciliation is on (GameID, TeamSide)). Fall back to
        # the normalized columns only for legacy rows, which lack a GameID and are therefore ineligible
        # for authoritative sync (the wave keeps them fail-closed).
        game_id = game.get("GameID")
        away = str(game.get("AwayTeamRaw") or game.get("Away") or "").strip()
        home = str(game.get("HomeTeamRaw") or game.get("Home") or "").strip()
        home_conf = game.get("HomeConf")
        away_conf = game.get("AwayConf")
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
            ("HOME", home, away, home_conf, away_conf, home_spread, home_score, away_score),
            ("AWAY", away, home, away_conf, home_conf, away_spread, away_score, home_score),
        ]
        for side, team, opponent, conf, opp_conf, line, team_score, opponent_score in spread_rows:
            if pd.isna(line):
                continue
            rows.append({
                "Sport": "NCAAF",
                "Season": season,
                "Week": week,
                "GameDate": date,
                "ResultDate": date,
                "Game": game_label,
                "GameID": game_id,
                "TeamSide": side,
                "Team": team,
                "Opponent": opponent,
                "Conf": conf,
                "OppConf": opp_conf,
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


def validate_results_current_season(results, season):
    """STRONG pre-publish validation (testable). The current-season SPREAD slice must be NONEMPTY and
    every row must carry a canonical GameID, a valid HOME/AWAY side, exact Team/Opponent names, a valid
    week + parseable date, a numeric line, and a conference value present. Returns (ok, message)."""
    import bk_runtime
    if results is None or results.empty or 'MarketType' not in results.columns:
        return False, "empty results frame"
    cur = results[(results["MarketType"].astype(str).str.upper() == "SPREAD")
                  & (pd.to_numeric(results["Season"], errors="coerce") == season)]
    if cur.empty:
        return False, f"no current-season ({season}) SPREAD results in a {len(results)}-row file"
    bad = 0
    for _, r in cur.iterrows():
        side = str(r.get("TeamSide") or "").strip().upper()
        if not (bk_runtime.cfb_game_id(r.get("GameID")) and side in ("HOME", "AWAY")
                and bk_runtime.valid_text(r.get("Team")) and bk_runtime.valid_text(r.get("Opponent"))
                and bk_runtime.valid_week(r.get("Week")) and bk_runtime.valid_date(r.get("GameDate"))
                and pd.notna(pd.to_numeric(r.get("Line"), errors="coerce"))
                and bk_runtime.valid_text(r.get("Conf"))):
            bad += 1
    if bad:
        return False, f"{bad} of {len(cur)} current-season SPREAD rows fail validation"
    return True, f"{len(cur)} current-season ({season}) SPREAD rows valid"


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"[FAIL] missing NCAAF historical game lines: {INPUT_PATH}")
        return 2
    history = pd.read_csv(INPUT_PATH, low_memory=False)
    results = build_results(history)
    if results.empty:
        print("[FAIL] grader produced 0 rows; leaving the existing results file untouched.")
        return 2
    import bk_runtime
    from datetime import date as _date
    today = _date.today()
    cur_season = today.year if today.month >= 8 else today.year - 1
    ok, msg = validate_results_current_season(results, cur_season)
    if not ok:
        print(f"[FAIL] results pre-publish validation ({cur_season}): {msg}; leaving the existing "
              "file untouched.")
        return 2
    bk_runtime.write_csv_atomic(results, OUTPUT_PATH)      # temp + fsync + os.replace
    resolved = int(results["OutcomeState"].isin(["Hit", "Miss", "Push"]).sum())
    with_id = int(results["GameID"].apply(lambda v: bk_runtime.cfb_game_id(v) is not None).sum()) \
        if "GameID" in results.columns else 0
    print(f"Wrote {len(results)} NCAAF game-line backfill rows to {OUTPUT_PATH}")
    print(f"Resolved rows: {resolved} | rows with a canonical GameID: {with_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
