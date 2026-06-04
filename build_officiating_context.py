from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTEXT_DIR = DATA_DIR / "context"

SPORTS = ["MLB", "NBA", "WNBA", "NFL", "NCAAF", "NCAAMB", "NCAAWB"]
OFFICIATING_COLUMNS = [
    "Date",
    "Sport",
    "Away",
    "Home",
    "Official",
    "Crew",
    "ZoneProfile",
    "PaceImpact",
    "ScoringImpact",
    "FoulImpact",
    "Source",
    "AssignmentStatus",
    "ImpactMarkets",
    "ContextNote",
    "LastUpdated",
]


SPORT_OFFICIATING_IMPACT = {
    "MLB": {
        "markets": "Pitcher Ks; Pitcher Walks; Game Total; F5 Total; Batter Walks",
        "note": "Home plate umpire zone profile affects strikeouts, walks, totals, and pitcher-control props.",
    },
    "NBA": {
        "markets": "Game Total; Team Total; PRA; PTS; Rebounds; Fouls",
        "note": "Crew foul rate and pace interruption affect free throws, scoring props, and possession flow.",
    },
    "WNBA": {
        "markets": "Game Total; Team Total; PRA; PTS; Rebounds; Fouls",
        "note": "Crew foul rate and pace interruption affect free throws, scoring props, and possession flow.",
    },
    "NFL": {
        "markets": "Game Total; Team Total; Passing Props; Penalty-sensitive SGPs",
        "note": "Referee crew penalty profile affects drive extension, pass interference, holding, and totals.",
    },
    "NCAAF": {
        "markets": "Game Total; Team Total; Spread; Penalty-sensitive SGPs",
        "note": "Crew and conference penalty profile affects game script, totals, and possession extension.",
    },
    "NCAAMB": {
        "markets": "Game Total; Team Total; Spread; Player Fouls; Free Throws",
        "note": "Referee foul profile affects bonus timing, tempo, free throws, and totals.",
    },
    "NCAAWB": {
        "markets": "Game Total; Team Total; Spread; Player Fouls; Free Throws",
        "note": "Referee foul profile affects bonus timing, tempo, free throws, and totals.",
    },
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _clean(value) -> str:
    text = str(value or "").strip()
    if text.lower() == "nan":
        return ""
    return "" if text == "-" else text


def _normalize_mlb_assignments() -> pd.DataFrame:
    source = _read_csv(CONTEXT_DIR / "MLB_UmpireAssignments.csv")
    if source.empty:
        return pd.DataFrame(columns=OFFICIATING_COLUMNS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for _, row in source.iterrows():
        official = _clean(row.get("Umpire"))
        rows.append({
            "Date": _clean(row.get("Date")),
            "Sport": "MLB",
            "Away": _clean(row.get("Away")),
            "Home": _clean(row.get("Home")),
            "Official": official,
            "Crew": "",
            "ZoneProfile": _clean(row.get("UmpireZone")),
            "PaceImpact": "",
            "ScoringImpact": _clean(row.get("RunImpact")),
            "FoulImpact": "",
            "Source": _clean(row.get("UmpireSource")) or "mlb_umpire_assignments",
            "AssignmentStatus": "CONFIRMED" if official else "NEEDS_ASSIGNMENT",
            "ImpactMarkets": SPORT_OFFICIATING_IMPACT["MLB"]["markets"],
            "ContextNote": SPORT_OFFICIATING_IMPACT["MLB"]["note"],
            "LastUpdated": _clean(row.get("LastUpdated")) or now,
        })
    return pd.DataFrame(rows, columns=OFFICIATING_COLUMNS)


def _empty_sport_frame(sport: str) -> pd.DataFrame:
    path = CONTEXT_DIR / f"{sport}_OfficiatingContext.csv"
    if path.exists():
        existing = _read_csv(path)
        for col in OFFICIATING_COLUMNS:
            if col not in existing.columns:
                existing[col] = ""
        impact = SPORT_OFFICIATING_IMPACT.get(sport, {})
        if "ImpactMarkets" in existing.columns:
            existing["ImpactMarkets"] = existing["ImpactMarkets"].fillna("").astype(str)
            existing.loc[existing["ImpactMarkets"].str.strip().eq(""), "ImpactMarkets"] = impact.get("markets", "")
        if "ContextNote" in existing.columns:
            existing["ContextNote"] = existing["ContextNote"].fillna("").astype(str)
            existing.loc[existing["ContextNote"].str.strip().eq(""), "ContextNote"] = impact.get("note", "")
        return existing[OFFICIATING_COLUMNS]
    return pd.DataFrame(columns=OFFICIATING_COLUMNS)


def build_officiating_context() -> pd.DataFrame:
    frames = [_normalize_mlb_assignments()]
    for sport in SPORTS:
        if sport == "MLB":
            continue
        frames.append(_empty_sport_frame(sport))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=OFFICIATING_COLUMNS)
    for col in OFFICIATING_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    return combined[OFFICIATING_COLUMNS]


def main() -> int:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    combined = build_officiating_context()
    output = CONTEXT_DIR / "OfficiatingContext.csv"
    combined.to_csv(output, index=False)

    for sport in SPORTS:
        sport_path = CONTEXT_DIR / f"{sport}_OfficiatingContext.csv"
        sport_frame = combined[combined["Sport"].astype(str).str.upper() == sport].copy()
        if sport_frame.empty:
            sport_frame = pd.DataFrame(columns=OFFICIATING_COLUMNS)
        sport_frame.to_csv(sport_path, index=False)

    confirmed = int((combined["AssignmentStatus"].astype(str).str.upper() == "CONFIRMED").sum()) if not combined.empty else 0
    print("=" * 60)
    print("BANKROLL KINGS - OFFICIATING CONTEXT")
    print("=" * 60)
    print(f"Rows written: {len(combined)}")
    print(f"Confirmed assignments: {confirmed}")
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
