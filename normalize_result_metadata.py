from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"

TARGETS = [
    ("NBA", TRACKING_DIR / "NBA_AllPropResults.csv", "NBA_Calibration_v1"),
    ("WNBA", TRACKING_DIR / "WNBA_AllPropResults.csv", "WNBA_Calibration_v1"),
    ("MLB", TRACKING_DIR / "MLB_AllPropResults.csv", "MLB_ContextScore_v1"),
    ("MLB", TRACKING_DIR / "MLB_AllPropResults_Scored.csv", "MLB_ContextScore_v1"),
    ("NFL", TRACKING_DIR / "NFL_AllPropResults.csv", "NFL_Backfill_v1"),
    ("NFL", TRACKING_DIR / "NFL_AllPropResults_Scored.csv", "NFL_EdgeScore_v1"),
    ("NCAAF", TRACKING_DIR / "NCAAF_AllPropResults.csv", "NCAAF_Calibration_v1"),
]


def _season_from_date(sport: str, value) -> str:
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        year = datetime.now().year
        return f"{year - 1}-{str(year)[2:]}" if sport == "NBA" and datetime.now().month < 10 else str(year)
    year = int(parsed.year)
    month = int(parsed.month)
    if sport == "NBA":
        return f"{year}-{str(year + 1)[2:]}" if month >= 10 else f"{year - 1}-{str(year)[2:]}"
    return str(year)


def _infer_season_column(df: pd.DataFrame, sport: str) -> pd.Series:
    date_source = pd.Series([""] * len(df), index=df.index, dtype=object)
    for col in ["ResultDate", "SnapshotDate", "SavedAt", "GameDate", "GameDay"]:
        if col in df.columns:
            values = df[col].fillna("").astype(str)
            date_source = date_source.where(date_source.astype(str).str.strip().ne(""), values)
    return date_source.apply(lambda value: _season_from_date(sport, value))


def _infer_backfill(df: pd.DataFrame) -> pd.Series:
    if "IsBackfill" in df.columns:
        existing = df["IsBackfill"].fillna("").astype(str).str.strip()
    else:
        existing = pd.Series([""] * len(df), index=df.index, dtype=str)
    method = df.get("Method", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.upper()
    sample = df.get("SampleMode", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.upper()
    source = df.get("SourceFile", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.upper()
    inferred = method.str.contains("HISTORICAL|BACKFILL", na=False) | sample.str.contains("HISTORICAL", na=False) | source.str.contains("HISTORY|HISTORICAL", na=False)
    output = existing.where(existing.ne(""), inferred.map(lambda value: "True" if value else "False"))
    return output


def normalize_file(sport: str, path: Path, model_version: str) -> dict:
    if not path.exists() or path.stat().st_size <= 2:
        return {"Sport": sport, "File": str(path), "Rows": 0, "Status": "MISSING"}
    df = pd.read_csv(path, low_memory=False)
    if "Sport" not in df.columns:
        df["Sport"] = sport
    else:
        df["Sport"] = df["Sport"].fillna("").astype(str).replace("", sport)

    if "Season" not in df.columns:
        df["Season"] = _infer_season_column(df, sport)
    else:
        season = df["Season"].fillna("").astype(str).str.strip()
        df["Season"] = season.where(season.ne(""), _infer_season_column(df, sport))

    df["IsBackfill"] = _infer_backfill(df)

    if "ModelVersion" not in df.columns:
        df["ModelVersion"] = model_version
    else:
        model = df["ModelVersion"].fillna("").astype(str).str.strip()
        df["ModelVersion"] = model.where(model.ne(""), model_version)

    if sport == "MLB":
        if "MLBModelVersion" not in df.columns:
            df["MLBModelVersion"] = model_version
        else:
            mlb_model = df["MLBModelVersion"].fillna("").astype(str).str.strip()
            df["MLBModelVersion"] = mlb_model.where(mlb_model.ne(""), model_version)
    if sport == "NFL":
        if "PropModelVersion" not in df.columns and "BK_NFL_PropScore" in df.columns:
            df["PropModelVersion"] = "NFL_PropScore_v1"
        elif "PropModelVersion" in df.columns:
            prop_model = df["PropModelVersion"].fillna("").astype(str).str.strip()
            df["PropModelVersion"] = prop_model.where(prop_model.ne(""), "NFL_PropScore_v1")

    df.to_csv(path, index=False)
    return {
        "Sport": sport,
        "File": str(path.relative_to(BASE_DIR)),
        "Rows": int(len(df)),
        "Status": "UPDATED",
        "BackfillRows": int(df["IsBackfill"].astype(str).str.lower().isin(["true", "1", "yes"]).sum()),
        "Seasons": ",".join(sorted({str(value) for value in df["Season"].dropna().astype(str).tolist() if str(value).strip()})),
    }


def main() -> int:
    rows = [normalize_file(sport, path, model_version) for sport, path, model_version in TARGETS]
    print("=" * 60)
    print("BANKROLL KINGS - RESULT METADATA NORMALIZATION")
    print("=" * 60)
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
