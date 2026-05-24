from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
FLOOR_INDEX_PATH = TRACKING_DIR / "Floor_Play_Index.csv"

RESULT_SOURCES = {
    "NBA": TRACKING_DIR / "NBA_AllPropResults.csv",
    "WNBA": TRACKING_DIR / "WNBA_AllPropResults.csv",
    "MLB": TRACKING_DIR / "MLB_AllPropResults.csv",
    "NFL": TRACKING_DIR / "NFL_AllPropResults.csv",
    "NCAAF": TRACKING_DIR / "NCAAF_AllPropResults.csv",
}

FALLBACK_SOURCES = {
    "NBA": TRACKING_DIR / "NBA_FeaturedResults.csv",
    "WNBA": TRACKING_DIR / "WNBA_FeaturedResults.csv",
    "MLB": TRACKING_DIR / "MLB_FeaturedResults.csv",
    "NFL": TRACKING_DIR / "NFL_FeaturedResults.csv",
    "NCAAF": TRACKING_DIR / "NCAAF_FeaturedResults.csv",
}


def _bet_tier_label(value) -> str:
    if isinstance(value, dict):
        return str(value.get("label") or value.get("tier") or "").strip()
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return str(parsed.get("label") or parsed.get("tier") or "").strip()
        except (SyntaxError, ValueError):
            return text
    return text


def derive_review_tier(row) -> str:
    label = _bet_tier_label(row.get("BetTier")).upper()
    if "TIER 1" in label or "FULL UNIT" in label:
        return "Tier 1"
    if "TIER 2" in label or "HALF UNIT" in label:
        return "Tier 2"
    if "TIER 3" in label or "SKIP" in label or "WATCH" in label:
        return "Tier 3"
    confidence = pd.to_numeric(pd.Series([row.get("Confidence")]), errors="coerce").iloc[0]
    if pd.isna(confidence):
        return "Tier 3"
    if float(confidence) >= 80:
        return "Tier 1"
    if float(confidence) >= 70:
        return "Tier 2"
    return "Tier 3"


def calculate_floor_reliability(resolved_count, hit_rate) -> str:
    count = int(resolved_count or 0)
    if hit_rate is None or pd.isna(hit_rate):
        return "SMALL SAMPLE"
    rate = float(hit_rate)
    if count < 10:
        return "SMALL SAMPLE"
    if count >= 20 and rate >= 0.65:
        return "ANCHOR"
    if count >= 10 and rate >= 0.60:
        return "WATCH"
    if count >= 10 and rate < 0.52:
        return "AVOID"
    return "DEVELOPING"


def build_floor_reliability_lookup(index: pd.DataFrame) -> dict:
    if index is None or index.empty:
        return {}
    floor = index[index["IsFloorPlay"].astype(bool)].copy()
    if floor.empty:
        return {}
    resolved = floor[floor["OutcomeState"].isin(["Hit", "Miss"])].copy()
    lookup = {}
    for keys, group in floor.groupby(["Sport", "Stat", "Direction"], dropna=False):
        sport, stat, direction = [str(part).upper() for part in keys]
        if not sport or not stat or not direction:
            continue
        decisive = resolved[
            (resolved["Sport"].str.upper() == sport)
            & (resolved["Stat"].str.upper() == stat)
            & (resolved["Direction"].str.upper() == direction)
        ].copy()
        resolved_count = int(len(decisive))
        hits = int((decisive["OutcomeState"] == "Hit").sum()) if resolved_count else 0
        hit_rate = hits / resolved_count if resolved_count else None
        reliability = calculate_floor_reliability(resolved_count, hit_rate)
        lookup[(sport, stat, direction)] = {
            "label": reliability,
            "note": f"{resolved_count} resolved at {round(hit_rate * 100, 1)}%" if hit_rate is not None else "No resolved bucket sample yet",
            "eligible": reliability in {"ANCHOR", "WATCH"},
        }
    return lookup


def _load_source(sport: str, path: Path) -> pd.DataFrame:
    if not path.exists():
        fallback = FALLBACK_SOURCES.get(sport)
        if fallback and fallback.exists():
            path = fallback
        else:
            return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["Sport"] = sport
    df["SourceFile"] = path.name
    return df


def build_floor_play_index() -> pd.DataFrame:
    frames = []
    for sport, path in RESULT_SOURCES.items():
        df = _load_source(sport, path)
        if not df.empty:
            frames.append(df)
    if not frames:
        index = pd.DataFrame()
    else:
        index = pd.concat(frames, ignore_index=True, sort=False)

    if not index.empty:
        for column in ["Method", "OutcomeState", "ResultDate", "SnapshotDate", "Sport", "Stat", "Direction"]:
            if column not in index.columns:
                index[column] = ""
            index[column] = index[column].fillna("").astype(str)
        index["IsFloorPlay"] = index["Method"].str.contains("floor", case=False, na=False)
        index["Hit_Binary"] = index["OutcomeState"].map({"Hit": 1, "Miss": 0})
        index["ReviewTier"] = index.apply(derive_review_tier, axis=1)
        index["ResultDay"] = index["ResultDate"].where(index["ResultDate"].str.strip() != "", index["SnapshotDate"])
        index["ResultDay"] = pd.to_datetime(index["ResultDay"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        reliability_lookup = build_floor_reliability_lookup(index)
        reliability_labels = []
        reliability_notes = []
        parlay_eligible = []
        for _, row in index.iterrows():
            key = (
                str(row.get("Sport") or "").upper(),
                str(row.get("Stat") or "").upper(),
                str(row.get("Direction") or "").upper(),
            )
            info = reliability_lookup.get(key)
            if bool(row.get("IsFloorPlay")) and info:
                reliability_labels.append(info["label"])
                reliability_notes.append(info["note"])
                parlay_eligible.append(info["eligible"])
            elif bool(row.get("IsFloorPlay")):
                reliability_labels.append("SMALL SAMPLE")
                reliability_notes.append("No resolved bucket sample yet")
                parlay_eligible.append(False)
            else:
                reliability_labels.append("")
                reliability_notes.append("")
                parlay_eligible.append(False)
        index["FloorReliability"] = reliability_labels
        index["FloorReliabilityNote"] = reliability_notes
        index["FloorParlayEligible"] = parlay_eligible
        index["SnapshotWrittenAt"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    FLOOR_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    index.to_csv(FLOOR_INDEX_PATH, index=False)
    return index


def main() -> int:
    index = build_floor_play_index()
    floor = index[index.get("IsFloorPlay", pd.Series(dtype=bool)).astype(bool)] if not index.empty else pd.DataFrame()
    resolved = floor[floor.get("OutcomeState", pd.Series(dtype=str)).isin(["Hit", "Miss"])] if not floor.empty else pd.DataFrame()
    hit_rate = float(resolved["Hit_Binary"].mean()) * 100 if not resolved.empty else None
    print("BANKROLL KINGS - Floor Play Index")
    print(f"Rows written: {len(index)}")
    print(f"Floor rows: {len(floor)}")
    print(f"Resolved floor rows: {len(resolved)}")
    print(f"Floor hit rate: {hit_rate:.1f}%" if hit_rate is not None else "Floor hit rate: -")
    print(f"Output: {FLOOR_INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
