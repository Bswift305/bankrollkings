from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_GameLineResults.csv"
RETURNING_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_ReturningProduction.csv"
PORTAL_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_TransferPortal.csv"
PLAYER_MASTER_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_PlayerMaster.csv"
TEAMRANKINGS_PATH = BASE_DIR / "data" / "historical" / "NCAAF_TeamRankings_2025_TeamStats.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_GameLineResults_Scored.csv"
MODEL_VERSION = "NCAAF_EdgeScore_v1"


def _normalize_team(value) -> str:
    text = " ".join(str(value or "").strip().upper().replace("&AMP;", "&").split())
    replacements = {
        "N ": "NORTH ",
        "S ": "SOUTH ",
        "E ": "EAST ",
        "W ": "WEST ",
        "C ": "CENTRAL ",
    }
    for prefix, expanded in replacements.items():
        if text.startswith(prefix):
            text = expanded + text[len(prefix):]
            break
    text = re.sub(r"\bST\b", "STATE", text)
    mascot_words = {
        "49ERS", "AGGIES", "AZTECS", "BEARCATS", "BEARS", "BEAVERS", "BENGALS", "BLUE", "BOILERMAKERS",
        "BRONCOS", "BRUINS", "BULLDOGS", "BULLS", "CARDINAL", "CARDINALS", "CAVALIERS", "CHANTICLEERS",
        "COUGARS", "COWBOYS", "CYCLONES", "DUCKS", "FALCONS", "FIGHTING", "GATORS", "GAELS", "GAMECOCKS",
        "GOLDEN", "GREEN", "HAWKEYES", "HILLTOPPERS", "HOOSIERS", "HORNED", "HUSKERS", "HUSKIES",
        "IRISH", "JACKETS", "JAYHAWKS", "KNIGHTS", "LOBOS", "LONGHORNS", "MEAN", "MINERS", "MOUNTAINEERS",
        "MUSTANGS", "NITTANY", "ORANGE", "OWLS", "PANTHERS", "RAIDERS", "REBELS", "RED", "RUSH",
        "SPARTANS", "TERRAPINS", "TIDE", "TIGERS", "TROJANS", "TURTLES", "UTES", "VOLUNTEERS",
        "WILDCATS", "WOLF", "WOLFPACK", "WOLVERINES",
    }
    words = [word for word in text.split() if word not in mascot_words]
    return " ".join(words) or text


def _safe_num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def build_team_context() -> pd.DataFrame:
    teams: dict[str, dict] = {}

    returning = _load_csv(RETURNING_PATH)
    if not returning.empty and "Team" in returning.columns:
        returning = returning.copy()
        returning["TeamKey"] = returning["Team"].apply(_normalize_team)
        for _, row in returning.sort_values([col for col in ["Year", "Team"] if col in returning.columns]).iterrows():
            key = row.get("TeamKey")
            if not key:
                continue
            profile = teams.setdefault(key, {"TeamKey": key, "Team": row.get("Team")})
            for col in [
                "ReturningProduction", "PassingUsage", "RushingUsage", "ReceivingUsage",
                "OffensiveLineUsage", "DefensiveLineUsage", "LinebackerUsage", "DefensiveBackUsage",
            ]:
                if col in returning.columns:
                    profile[col] = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]

    portal = _load_csv(PORTAL_PATH)
    if not portal.empty:
        portal = portal.copy()
        for col in ["OriginTeam", "DestinationTeam"]:
            if col not in portal.columns:
                portal[col] = ""
            portal[col] = portal[col].apply(_normalize_team)
        incoming = portal[portal["DestinationTeam"] != ""].groupby("DestinationTeam").size()
        outgoing = portal[portal["OriginTeam"] != ""].groupby("OriginTeam").size()
        for key, count in incoming.items():
            profile = teams.setdefault(key, {"TeamKey": key, "Team": key.title()})
            profile["PortalIn"] = int(count)
        for key, count in outgoing.items():
            profile = teams.setdefault(key, {"TeamKey": key, "Team": key.title()})
            profile["PortalOut"] = int(count)

    master = _load_csv(PLAYER_MASTER_PATH)
    if not master.empty and "CurrentTeam" in master.columns:
        working = master.copy()
        working["TeamKey"] = working["CurrentTeam"].apply(_normalize_team)
        for col in ["CareerPassYds", "CareerRushYds", "CareerRecYds", "CareerTackles", "TransferFlag"]:
            if col not in working.columns:
                working[col] = 0
        working["TransferFlagBool"] = working["TransferFlag"].astype(str).str.lower().isin(["true", "1", "yes"])
        grouped = working.groupby("TeamKey", dropna=False).agg(
            CareerPassYds=("CareerPassYds", "sum"),
            CareerRushYds=("CareerRushYds", "sum"),
            CareerRecYds=("CareerRecYds", "sum"),
            CareerTackles=("CareerTackles", "sum"),
            RosterTransfers=("TransferFlagBool", "sum"),
            RosterRows=("TeamKey", "count"),
        )
        for key, row in grouped.iterrows():
            if not key:
                continue
            profile = teams.setdefault(key, {"TeamKey": key, "Team": key.title()})
            profile.update(row.to_dict())

    teamrankings = _load_csv(TEAMRANKINGS_PATH)
    if not teamrankings.empty and "Team" in teamrankings.columns:
        tr = teamrankings.copy()
        tr["TeamKey"] = tr["Team"].apply(_normalize_team)
        for _, row in tr.iterrows():
            key = str(row.get("TeamKey") or "")
            if not key:
                continue
            profile = teams.setdefault(key, {"TeamKey": key, "Team": row.get("Team")})
            for col in [
                "points_per_game_SeasonValue",
                "average_scoring_margin_SeasonValue",
                "yards_per_play_SeasonValue",
                "yards_per_game_SeasonValue",
                "third_down_conversion_pct_SeasonValue",
                "red_zone_scoring_pct_SeasonValue",
                "opponent_points_per_game_SeasonValue",
                "opponent_yards_per_play_SeasonValue",
                "opponent_yards_per_game_SeasonValue",
                "opponent_third_down_conversion_pct_SeasonValue",
                "turnover_margin_per_game_SeasonValue",
            ]:
                if col in tr.columns:
                    profile[col] = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]

    df = pd.DataFrame(teams.values())
    if df.empty:
        return pd.DataFrame(columns=["TeamKey", "Team", "CFBTeamContextScore", "CFBTeamContextTier"])

    for col in [
        "ReturningProduction", "PassingUsage", "RushingUsage", "ReceivingUsage", "OffensiveLineUsage",
        "DefensiveLineUsage", "LinebackerUsage", "DefensiveBackUsage", "PortalIn", "PortalOut",
        "CareerPassYds", "CareerRushYds", "CareerRecYds", "CareerTackles", "RosterTransfers", "RosterRows",
        "points_per_game_SeasonValue", "average_scoring_margin_SeasonValue", "yards_per_play_SeasonValue",
        "yards_per_game_SeasonValue", "third_down_conversion_pct_SeasonValue", "red_zone_scoring_pct_SeasonValue",
        "opponent_points_per_game_SeasonValue", "opponent_yards_per_play_SeasonValue",
        "opponent_yards_per_game_SeasonValue", "opponent_third_down_conversion_pct_SeasonValue",
        "turnover_margin_per_game_SeasonValue",
    ]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["PortalNet"] = df["PortalIn"] - df["PortalOut"]
    df["OffensiveContinuity"] = (
        df["ReturningProduction"].clip(0, 1) * 20
        + df["PassingUsage"].clip(0, 1) * 10
        + df["OffensiveLineUsage"].clip(0, 1) * 8
        + (df["CareerPassYds"] / 4000).clip(0, 8)
        + (df["CareerRushYds"] / 5000).clip(0, 5)
        + (df["CareerRecYds"] / 7000).clip(0, 5)
    )
    df["DefensiveContinuity"] = (
        df["DefensiveLineUsage"].clip(0, 1) * 8
        + df["LinebackerUsage"].clip(0, 1) * 6
        + df["DefensiveBackUsage"].clip(0, 1) * 6
        + (df["CareerTackles"] / 700).clip(0, 8)
    )
    df["PortalStability"] = (df["PortalNet"].clip(-10, 10) * 1.2) - (df["PortalOut"].clip(0, 20) * 0.5)
    df["TeamRankingsOffenseScore"] = (
        ((df["points_per_game_SeasonValue"] - 24) / 12).clip(-2, 2) * 5
        + ((df["yards_per_play_SeasonValue"] - 5.5) / 1.2).clip(-2, 2) * 4
        + ((df["average_scoring_margin_SeasonValue"]) / 14).clip(-2, 2) * 4
        + ((df["third_down_conversion_pct_SeasonValue"] - 38) / 12).clip(-2, 2) * 3
        + ((df["red_zone_scoring_pct_SeasonValue"] - 80) / 12).clip(-2, 2) * 2
    )
    df["TeamRankingsDefenseScore"] = (
        ((24 - df["opponent_points_per_game_SeasonValue"]) / 12).clip(-2, 2) * 5
        + ((5.5 - df["opponent_yards_per_play_SeasonValue"]) / 1.2).clip(-2, 2) * 4
        + ((38 - df["opponent_third_down_conversion_pct_SeasonValue"]) / 12).clip(-2, 2) * 3
        + (df["turnover_margin_per_game_SeasonValue"].clip(-2, 2) * 2)
    )
    df["CFBTeamContextScore"] = (
        42
        + df["OffensiveContinuity"]
        + df["DefensiveContinuity"]
        + df["PortalStability"]
        + df["TeamRankingsOffenseScore"]
        + df["TeamRankingsDefenseScore"]
    ).clip(20, 95).round(1)
    df["CFBTeamContextTier"] = pd.cut(
        df["CFBTeamContextScore"],
        bins=[-1, 48, 60, 72, 100],
        labels=["VOLATILE", "MIXED", "SUPPORTED", "STABLE"],
    ).astype(str)
    return df


def _team_profile(team_context: dict[str, dict], team_name) -> dict:
    key = _normalize_team(team_name)
    if key in team_context:
        return team_context[key]
    if not key:
        return {}
    for existing_key, profile in team_context.items():
        if not existing_key:
            continue
        if key.startswith(existing_key) or existing_key.startswith(key):
            return profile
    return {}


def _score_line(row: pd.Series, team_context: dict[str, dict]) -> dict:
    market = str(row.get("MarketType") or "").upper()
    team_key = _normalize_team(row.get("Team"))
    home_key = _normalize_team(row.get("HomeTeam"))
    away_key = _normalize_team(row.get("AwayTeam"))
    team_profile = _team_profile(team_context, row.get("Team"))
    home_profile = _team_profile(team_context, row.get("HomeTeam"))
    away_profile = _team_profile(team_context, row.get("AwayTeam"))

    if market == "SPREAD":
        team_score = float(team_profile.get("CFBTeamContextScore", 50))
        opponent_key = _normalize_team(row.get("Opponent"))
        opponent_score = float(_team_profile(team_context, row.get("Opponent")).get("CFBTeamContextScore", 50))
        context_edge = team_score - opponent_score
        line = pd.to_numeric(pd.Series([row.get("Line")]), errors="coerce").iloc[0]
        favorite_penalty = 0
        if not pd.isna(line) and float(line) < -14:
            favorite_penalty = 6
        edge_score = 55 + context_edge * 0.45 - favorite_penalty
        note = f"Roster edge {context_edge:+.1f}; {team_profile.get('CFBTeamContextTier', 'UNKNOWN')} vs opponent."
    else:
        home_score = float(home_profile.get("CFBTeamContextScore", 50))
        away_score = float(away_profile.get("CFBTeamContextScore", 50))
        continuity = (home_score + away_score) / 2
        direction = str(row.get("Direction") or "").upper()
        if direction == "OVER":
            edge_score = 50 + max(0, continuity - 58) * 0.6
            note = f"Combined continuity {continuity:.1f}; stronger continuity can support cleaner offensive expectations."
        else:
            volatility = max(0, 58 - continuity)
            edge_score = 50 + volatility * 0.55
            note = f"Combined continuity {continuity:.1f}; volatility can support caution on totals."

    edge_score = round(max(20, min(float(edge_score), 95)), 1)
    if edge_score >= 72:
        gate = "PROMOTE"
    elif edge_score >= 62:
        gate = "WATCH"
    elif edge_score <= 45:
        gate = "REDUCE"
    else:
        gate = "STANDARD"
    return {
        "BK_CFB_EdgeScore": edge_score,
        "CFBFormulaGate": gate,
        "CFBFormulaNote": note,
        "ModelVersion": MODEL_VERSION,
        "Confidence": edge_score,
    }


def main() -> int:
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing NCAAF game-line result file: {INPUT_PATH}")
    results = _load_csv(INPUT_PATH)
    context = build_team_context()
    context_lookup = {
        str(row.get("TeamKey") or ""): row
        for row in context.to_dict("records")
        if str(row.get("TeamKey") or "")
    }
    if results.empty:
        scored = results
    else:
        additions = results.apply(lambda row: _score_line(row, context_lookup), axis=1, result_type="expand")
        scored = pd.concat([results.drop(columns=[col for col in additions.columns if col in results.columns], errors="ignore"), additions], axis=1)
        scored["IsBackfill"] = scored.get("IsBackfill", True)
        scored["Sport"] = "NCAAF"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(scored)} scored NCAAF game-line rows to {OUTPUT_PATH}")
    if not context.empty:
        print(f"Team context profiles loaded: {len(context)}")
    else:
        print("Team context profiles loaded: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
