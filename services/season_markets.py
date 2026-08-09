"""Cross-sport season-long market normalization and model comparison."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


SPORTS = ("NFL", "NCAAF", "NBA", "WNBA", "MLB", "NCAAMB", "NCAAWB")
MARKET_COLUMNS = [
    "SnapshotAt", "Sport", "Season", "EntityType", "Entity", "Team", "Market",
    "Line", "OverOdds", "UnderOdds", "Book", "Source", "SourceUpdatedAt",
]
PROJECTION_COLUMNS = [
    "Sport", "Season", "EntityType", "Entity", "Team", "Market",
    "ProjectedValue", "ModelLabel", "SampleSize", "UpdatedAt", "Note",
]


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)
    try:
        frame = pd.read_csv(path, low_memory=False)
    except (pd.errors.EmptyDataError, OSError, ValueError):
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns].copy()


def _clean_text(series: pd.Series, upper: bool = False) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    return values.str.upper() if upper else values


def load_season_markets(base_dir: Path) -> pd.DataFrame:
    frame = _read(base_dir / "data" / "season_markets" / "Season_Markets.csv", MARKET_COLUMNS)
    if frame.empty:
        return frame
    frame["Sport"] = _clean_text(frame["Sport"], upper=True)
    frame["Season"] = _clean_text(frame["Season"])
    frame["EntityType"] = _clean_text(frame["EntityType"]).str.lower()
    frame["Entity"] = _clean_text(frame["Entity"])
    frame["Team"] = _clean_text(frame["Team"])
    frame["Market"] = _clean_text(frame["Market"])
    frame["Book"] = _clean_text(frame["Book"])
    for column in ("Line", "OverOdds", "UnderOdds"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[
        frame["Sport"].isin(SPORTS)
        & frame["EntityType"].isin(("team", "player"))
        & frame["Entity"].ne("")
        & frame["Market"].ne("")
        & frame["Line"].notna()
    ]
    return frame


def load_season_projections(base_dir: Path) -> pd.DataFrame:
    frame = _read(base_dir / "data" / "season_markets" / "Season_Projections.csv", PROJECTION_COLUMNS)
    if frame.empty:
        return frame
    frame["Sport"] = _clean_text(frame["Sport"], upper=True)
    frame["Season"] = _clean_text(frame["Season"])
    frame["EntityType"] = _clean_text(frame["EntityType"]).str.lower()
    frame["Entity"] = _clean_text(frame["Entity"])
    frame["Team"] = _clean_text(frame["Team"])
    frame["Market"] = _clean_text(frame["Market"])
    frame["ProjectedValue"] = pd.to_numeric(frame["ProjectedValue"], errors="coerce")
    frame["SampleSize"] = pd.to_numeric(frame["SampleSize"], errors="coerce")
    return frame[
        frame["Sport"].isin(SPORTS)
        & frame["EntityType"].isin(("team", "player"))
        & frame["Entity"].ne("")
        & frame["Market"].ne("")
        & frame["ProjectedValue"].notna()
    ]


def _price(value):
    if pd.isna(value):
        return None
    number = int(round(float(value)))
    return f"+{number}" if number > 0 else str(number)


def build_season_market_context(
    base_dir: Path,
    sport: str = "",
    entity_type: str = "",
    market: str = "",
    search: str = "",
) -> dict:
    markets = load_season_markets(base_dir)
    projections = load_season_projections(base_dir)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if markets.empty:
        return {
            "rows": [], "sports": list(SPORTS), "markets": [], "market_rows": 0,
            "comparison_rows": 0, "books": [], "generated_at": generated_at,
            "feed_state": "awaiting_feed",
            "feed_note": "The comparison system is ready, but no licensed season-market feed has populated it yet.",
        }

    keys = ["Sport", "Season", "EntityType", "Entity", "Team", "Market"]
    consensus = (
        markets.groupby(keys, dropna=False)
        .agg(
            ConsensusLine=("Line", "median"),
            LowLine=("Line", "min"),
            HighLine=("Line", "max"),
            BookCount=("Book", lambda values: int(values.replace("", pd.NA).dropna().nunique())),
            BestOverOdds=("OverOdds", "max"),
            BestUnderOdds=("UnderOdds", "max"),
            LatestSnapshot=("SnapshotAt", "max"),
        )
        .reset_index()
    )
    if not projections.empty:
        projection_latest = (
            projections.sort_values("UpdatedAt")
            .drop_duplicates(keys, keep="last")
        )
        consensus = consensus.merge(
            projection_latest[keys + ["ProjectedValue", "ModelLabel", "SampleSize", "UpdatedAt", "Note"]],
            on=keys,
            how="left",
        )
    else:
        for column in ("ProjectedValue", "ModelLabel", "SampleSize", "UpdatedAt", "Note"):
            consensus[column] = pd.NA

    consensus["Gap"] = consensus["ProjectedValue"] - consensus["ConsensusLine"]
    consensus["Direction"] = consensus["Gap"].map(
        lambda value: "" if pd.isna(value) else "Higher" if value >= 0.5 else "Lower" if value <= -0.5 else "In line"
    )

    sport_filter = str(sport or "").strip().upper()
    type_filter = str(entity_type or "").strip().lower()
    market_filter = str(market or "").strip()
    search_filter = str(search or "").strip().lower()
    filtered = consensus
    if sport_filter:
        filtered = filtered[filtered["Sport"] == sport_filter]
    if type_filter:
        filtered = filtered[filtered["EntityType"] == type_filter]
    if market_filter:
        filtered = filtered[filtered["Market"] == market_filter]
    if search_filter:
        haystack = (
            filtered["Entity"].fillna("").astype(str)
            + " " + filtered["Team"].fillna("").astype(str)
            + " " + filtered["Market"].fillna("").astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(search_filter, regex=False)]

    filtered = filtered.sort_values(
        ["Sport", "EntityType", "Market", "Entity"],
        kind="stable",
    )
    rows = []
    for _, row in filtered.iterrows():
        rows.append({
            "sport": row["Sport"],
            "season": row["Season"],
            "entity_type": row["EntityType"],
            "entity": row["Entity"],
            "team": row["Team"],
            "market": row["Market"],
            "consensus_line": round(float(row["ConsensusLine"]), 2),
            "line_range": (
                f"{float(row['LowLine']):g}–{float(row['HighLine']):g}"
                if float(row["LowLine"]) != float(row["HighLine"]) else f"{float(row['ConsensusLine']):g}"
            ),
            "book_count": int(row["BookCount"]),
            "best_over_odds": _price(row["BestOverOdds"]),
            "best_under_odds": _price(row["BestUnderOdds"]),
            "projected_value": None if pd.isna(row["ProjectedValue"]) else round(float(row["ProjectedValue"]), 2),
            "gap": None if pd.isna(row["Gap"]) else round(float(row["Gap"]), 2),
            "direction": row["Direction"],
            "model_label": "" if pd.isna(row["ModelLabel"]) else str(row["ModelLabel"]),
            "sample_size": None if pd.isna(row["SampleSize"]) else int(row["SampleSize"]),
            "model_note": "" if pd.isna(row["Note"]) else str(row["Note"]),
            "latest_snapshot": row["LatestSnapshot"],
        })

    return {
        "rows": rows,
        "sports": sorted(markets["Sport"].dropna().unique().tolist()),
        "markets": sorted(markets["Market"].dropna().unique().tolist()),
        "market_rows": int(len(consensus)),
        "comparison_rows": int(consensus["ProjectedValue"].notna().sum()),
        "books": sorted(book for book in markets["Book"].dropna().unique().tolist() if book),
        "generated_at": generated_at,
        "feed_state": "live",
        "feed_note": "Consensus is the median posted line across available books. A model gap is context, not proof of betting edge.",
    }
