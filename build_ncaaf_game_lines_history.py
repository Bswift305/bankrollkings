from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
ODDS_PATH = BASE_DIR / "data" / "historical" / "NCAAF_OddsAPI_GameLines_History.csv"
SCORES_TEMPLATE = BASE_DIR / "data" / "historical" / "NCAAF_CFBD_Games_{year}.csv"
OUTPUT_PATH = BASE_DIR / "data" / "historical" / "NCAAF_GameLines_History.csv"


MASCOT_WORDS = {
    "49ERS", "AGGIES", "AZTECS", "BEARCATS", "BEARS", "BEAVERS", "BENGALS", "BISON", "BLUE",
    "BOILERMAKERS", "BRONCOS", "BRUINS", "BUCKEYES", "BULLDOGS", "BULLS", "CARDINAL",
    "CARDINALS", "CAVALIERS", "CHANTICLEERS", "COMMODORES", "COUGARS", "COWBOYS", "CYCLONES",
    "DEMON", "DEVILS", "DUCKS", "EAGLES", "FALCONS", "FIGHTING", "GATORS", "GAELS", "GAMECOCKS",
    "GOLDEN", "GREEN", "HAWKEYES", "HILLTOPPERS", "HOOSIERS", "HORNED", "HURRICANES", "HUSKERS",
    "HUSKIES", "IRISH", "JACKETS", "JAGUARS", "JAYHAWKS", "KNIGHTS", "LIONS", "LOBOS", "LONGHORNS",
    "MEAN", "MINERS", "MOUNTAINEERS", "MUSTANGS", "NITTANY", "ORANGE", "OWLS", "PANTHERS",
    "RAIDERS", "REBELS", "RED", "RUSH", "SPARTANS", "TERRAPINS", "TIDE", "TIGERS", "TROJANS",
    "TURTLES", "UTES", "VOLUNTEERS", "WARRIORS", "WILDCATS", "WOLF", "WOLFPACK", "WOLVERINES",
}


ALIASES = {
    "APP STATE": "APPALACHIAN STATE",
    "ARIZONA STATE": "ARIZONA STATE",
    "BOWLING GREEN STATE": "BOWLING GREEN",
    "BYU": "BRIGHAM YOUNG",
    "CAL": "CALIFORNIA",
    "CHARLOTTE": "CHARLOTTE",
    "FIU": "FLORIDA INTERNATIONAL",
    "JAMES MADISON": "JAMES MADISON",
    "KANSAS STATE": "KANSAS STATE",
    "LSU": "LOUISIANA STATE",
    "MIAMI FL": "MIAMI",
    "MIAMI OH": "MIAMI OHIO",
    "MTSU": "MIDDLE TENNESSEE",
    "NC STATE": "NORTH CAROLINA STATE",
    "NMSU": "NEW MEXICO STATE",
    "NIU": "NORTHERN ILLINOIS",
    "OLE MISS": "MISSISSIPPI",
    "SJSU": "SAN JOSE STATE",
    "SMU": "SOUTHERN METHODIST",
    "TCU": "TCU",
    "UAB": "UAB",
    "UCF": "UCF",
    "UCLA": "UCLA",
    "UCONN": "CONNECTICUT",
    "UL MONROE": "LOUISIANA MONROE",
    "UMASS": "MASSACHUSETTS",
    "UNLV": "UNLV",
    "USC": "USC",
    "UTEP": "UTEP",
    "UTSA": "UTSA",
}


def normalize_team(value) -> str:
    text = str(value or "").upper()
    text = text.replace("&AMP;", "&")
    text = re.sub(r"[^A-Z0-9& ]+", " ", text)
    text = " ".join(text.split())
    text = re.sub(r"\bST\b", "STATE", text)
    text = re.sub(r"\bN\b", "NORTH", text)
    text = re.sub(r"\bS\b", "SOUTH", text)
    text = re.sub(r"\bE\b", "EAST", text)
    text = re.sub(r"\bW\b", "WEST", text)
    if text in ALIASES:
        return ALIASES[text]
    words = [word for word in text.split() if word not in MASCOT_WORDS]
    clean = " ".join(words) or text
    return ALIASES.get(clean, clean)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _prepare_odds(odds: pd.DataFrame) -> pd.DataFrame:
    if odds.empty:
        return odds
    working = odds.copy()
    working["SnapshotParsed"] = pd.to_datetime(working.get("SnapshotDate"), errors="coerce", utc=True)
    working["CommenceParsed"] = pd.to_datetime(working.get("CommenceTime"), errors="coerce", utc=True)
    working["Date"] = pd.to_datetime(working.get("Date"), errors="coerce").dt.strftime("%Y-%m-%d")
    working["AwayKey"] = working.get("Away", "").apply(normalize_team)
    working["HomeKey"] = working.get("Home", "").apply(normalize_team)
    for col in ["Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds", "AwayML", "HomeML"]:
        if col in working.columns:
            working[col] = pd.to_numeric(working[col], errors="coerce")
    # Keep only snapshots taken before kickoff. If kickoff is missing, keep the row.
    has_times = working["SnapshotParsed"].notna() & working["CommenceParsed"].notna()
    working = working[(~has_times) | (working["SnapshotParsed"] <= working["CommenceParsed"])].copy()
    working = working.sort_values(["Date", "AwayKey", "HomeKey", "SnapshotParsed"])
    latest = working.groupby(["Date", "AwayKey", "HomeKey", "Book"], dropna=False).tail(1)
    grouped = latest.groupby(["Date", "AwayKey", "HomeKey"], dropna=False)
    rows = grouped.agg(
        Away=("Away", "first"),
        Home=("Home", "first"),
        HomeSpread=("Spread", "median"),
        Spread=("Spread", "median"),
        SpreadOdds=("SpreadOdds", "median"),
        Total=("Total", "median"),
        CloseTotal=("Total", "median"),
        OverOdds=("OverOdds", "median"),
        UnderOdds=("UnderOdds", "median"),
        AwayML=("AwayML", "median"),
        HomeML=("HomeML", "median"),
        Books=("Book", lambda s: ", ".join(sorted(set(str(x) for x in s if str(x) != "nan")))),
        BookCount=("Book", "nunique"),
        FirstSnapshot=("SnapshotParsed", "min"),
        LastSnapshot=("SnapshotParsed", "max"),
        CommenceTime=("CommenceParsed", "first"),
    ).reset_index()
    rows["AwaySpread"] = -pd.to_numeric(rows["HomeSpread"], errors="coerce")
    return rows


def _prepare_scores(scores: pd.DataFrame) -> pd.DataFrame:
    if scores.empty:
        return scores
    working = scores.copy()
    working["Date"] = pd.to_datetime(working.get("Date"), errors="coerce").dt.strftime("%Y-%m-%d")
    working["AwayKey"] = working.get("Away", "").apply(normalize_team)
    working["HomeKey"] = working.get("Home", "").apply(normalize_team)
    for col in ["Season", "Week", "AwayScore", "HomeScore"]:
        if col in working.columns:
            working[col] = pd.to_numeric(working[col], errors="coerce")
    if "Completed" in working.columns:
        working = working[working["Completed"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    return working


def build_history(odds: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    odds_prepped = _prepare_odds(odds)
    scores_prepped = _prepare_scores(scores)
    if odds_prepped.empty or scores_prepped.empty:
        return pd.DataFrame(
            columns=[
                "Date", "Season", "Week", "Away", "Home", "Spread", "HomeSpread", "AwaySpread",
                "Total", "CloseTotal", "AwayScore", "HomeScore", "BookCount", "Books", "Source",
            ]
        )

    merged = odds_prepped.merge(
        scores_prepped[
            [
                "Date",
                "AwayKey",
                "HomeKey",
                "Season",
                "Week",
                "AwayScore",
                "HomeScore",
                "SeasonType",
                "NeutralSite",
                "ConferenceGame",
                "Venue",
            ]
        ],
        on=["Date", "AwayKey", "HomeKey"],
        how="inner",
    )
    if merged.empty:
        return merged
    merged["Source"] = "oddsapi_lines+cfbd_scores"
    merged["IsBackfill"] = True
    columns = [
        "Date",
        "Season",
        "Week",
        "Away",
        "Home",
        "Spread",
        "HomeSpread",
        "AwaySpread",
        "SpreadOdds",
        "Total",
        "CloseTotal",
        "OverOdds",
        "UnderOdds",
        "AwayML",
        "HomeML",
        "AwayScore",
        "HomeScore",
        "SeasonType",
        "NeutralSite",
        "ConferenceGame",
        "Venue",
        "BookCount",
        "Books",
        "FirstSnapshot",
        "LastSnapshot",
        "CommenceTime",
        "Source",
        "IsBackfill",
    ]
    for col in columns:
        if col not in merged.columns:
            merged[col] = pd.NA
    return merged[columns].sort_values(["Date", "Away", "Home"]).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical NCAAF game-line history from Odds API lines and CFBD scores.")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--odds", default=str(ODDS_PATH))
    parser.add_argument("--scores", default="")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    odds = _load_csv(Path(args.odds))
    scores_path = Path(args.scores) if args.scores else Path(str(SCORES_TEMPLATE).format(year=args.year))
    scores = _load_csv(scores_path)
    history = build_history(odds, scores)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(output, index=False)
    print(f"Odds rows: {len(odds)}")
    print(f"Score rows: {len(scores)}")
    print(f"Merged game rows: {len(history)}")
    print(f"Wrote {output}")
    if not history.empty:
        print(f"Date range: {history['Date'].min()} to {history['Date'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
