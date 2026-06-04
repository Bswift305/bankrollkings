from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import (
    COMBINED_PROP_COMPONENTS,
    normalize_combined_prop_key,
    load_nba_review_gamelogs,
    load_wnba_gamelogs,
    load_mlb_gamelogs,
    load_nfl_gamelogs,
    load_ncaaf_gamelogs,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_PATH = DATA_DIR / "tracking" / "Combined_Prop_Coverage.csv"

PROP_FILES = {
    "NBA": DATA_DIR / "props" / "NBA_Props.csv",
    "WNBA": DATA_DIR / "props" / "WNBA_Props.csv",
    "MLB": DATA_DIR / "props" / "MLB_Props.csv",
    "NFL": DATA_DIR / "props" / "NFL_Props.csv",
    "NCAAF": DATA_DIR / "props" / "NCAAF_Props.csv",
}

GAMELOG_LOADERS = {
    "NBA": load_nba_review_gamelogs,
    "WNBA": load_wnba_gamelogs,
    "MLB": load_mlb_gamelogs,
    "NFL": load_nfl_gamelogs,
    "NCAAF": load_ncaaf_gamelogs,
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _market_stats(props: pd.DataFrame) -> set[str]:
    if props.empty:
        return set()
    columns = [col for col in ["Stat", "StatType", "MarketKey", "Market"] if col in props.columns]
    stats: set[str] = set()
    for col in columns:
        stats.update(
            normalize_combined_prop_key(value)
            for value in props[col].dropna().astype(str).tolist()
            if str(value).strip()
        )
    return stats


def build_combined_prop_coverage() -> pd.DataFrame:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for sport, specs in COMBINED_PROP_COMPONENTS.items():
        props = _read_csv(PROP_FILES.get(sport, Path()))
        market_stats = _market_stats(props)
        try:
            logs = GAMELOG_LOADERS.get(sport, lambda: pd.DataFrame())()
        except Exception:
            logs = pd.DataFrame()
        log_columns = set(logs.columns)

        for output_col, components in specs.items():
            rows.append({
                "CheckedAt": checked_at,
                "Sport": sport,
                "CombinedStat": output_col,
                "Components": "+".join(components),
                "PropMarketLive": output_col in market_stats,
                "ComponentColumnsReady": all(component in log_columns for component in components),
                "ResolvedColumnReady": output_col in log_columns,
                "PropRows": int(len(props[props.get("Stat", pd.Series(dtype=str)).astype(str).map(normalize_combined_prop_key) == output_col])) if not props.empty and "Stat" in props.columns else 0,
                "Status": "READY" if output_col in log_columns else "NEEDS_COMPONENTS",
            })
    return pd.DataFrame(rows)


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    coverage = build_combined_prop_coverage()
    coverage.to_csv(OUTPUT_PATH, index=False)
    ready = int((coverage["Status"] == "READY").sum()) if not coverage.empty else 0
    live = int(coverage["PropMarketLive"].sum()) if not coverage.empty else 0
    print("=" * 70)
    print("BANKROLL KINGS - COMBINED PROP COVERAGE")
    print("=" * 70)
    print(f"Rows written: {len(coverage)}")
    print(f"Resolved columns ready: {ready}")
    print(f"Live combined markets detected: {live}")
    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
