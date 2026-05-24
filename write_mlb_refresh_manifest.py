from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRACKING_DIR = DATA_DIR / "tracking"
OUTPUT_PATH = TRACKING_DIR / "MLB_DailyRefresh_Manifest.json"
HISTORY_PATH = TRACKING_DIR / "MLB_DailyRefresh_Manifest_History.csv"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _file_info(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "rows": 0, "modified": ""}
    df = _read_csv(path)
    return {
        "exists": True,
        "rows": int(len(df)),
        "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_manifest() -> dict:
    coverage = _read_csv(TRACKING_DIR / "MLB_Props_MarketCoverage.csv")
    audit = _read_csv(TRACKING_DIR / "MLB_MarketKey_Audit.csv")
    all_results = _read_csv(TRACKING_DIR / "MLB_AllPropResults.csv")
    floor = _read_csv(TRACKING_DIR / "Floor_Play_Index.csv")

    coverage_rows = coverage.to_dict("records") if not coverage.empty else []
    missing_markets = [
        {
            "market_key": str(row.get("MarketKey") or ""),
            "stat": str(row.get("Stat") or ""),
            "reason": str(row.get("MissingReason") or ""),
        }
        for row in coverage_rows
        if str(row.get("Status") or "").upper() == "MISSING"
    ]
    one_sided_markets = [
        {
            "market_key": str(row.get("MarketKey") or ""),
            "stat": str(row.get("Stat") or ""),
            "rows": int(pd.to_numeric(row.get("Rows"), errors="coerce") or 0),
            "books": int(pd.to_numeric(row.get("Books"), errors="coerce") or 0),
        }
        for row in coverage_rows
        if str(row.get("PriceFormat") or "").upper() == "ONE_SIDED_YES"
    ]

    resolved = 0
    pending = 0
    if not all_results.empty and "OutcomeState" in all_results.columns:
        state = all_results["OutcomeState"].fillna("").astype(str)
        resolved = int(state.isin(["Hit", "Miss", "Push"]).sum())
        pending = int((state == "Pending").sum())

    floor_rows = 0
    floor_resolved = 0
    if not floor.empty and "Sport" in floor.columns:
        mlb_floor = floor[floor["Sport"].fillna("").astype(str).str.upper() == "MLB"].copy()
        if "IsFloorPlay" in mlb_floor.columns:
            mlb_floor = mlb_floor[mlb_floor["IsFloorPlay"].astype(str).str.lower().isin(["true", "1", "yes"])]
        floor_rows = int(len(mlb_floor))
        if "OutcomeState" in mlb_floor.columns:
            floor_resolved = int(mlb_floor["OutcomeState"].isin(["Hit", "Miss"]).sum())

    files = {
        "schedule": _file_info(DATA_DIR / "schedules" / "MLB_Schedule.csv"),
        "game_lines": _file_info(DATA_DIR / "odds" / "MLB_Odds.csv"),
        "props": _file_info(DATA_DIR / "props" / "MLB_Props.csv"),
        "props_fallback": _file_info(DATA_DIR / "props" / "MLB_Props_Fallback.csv"),
        "game_context": _file_info(DATA_DIR / "context" / "MLB_GameContext.csv"),
        "gamelogs": _file_info(DATA_DIR / "gamelogs" / "MLB_GameLogs.csv"),
        "all_results": _file_info(TRACKING_DIR / "MLB_AllPropResults.csv"),
        "calibration": _file_info(TRACKING_DIR / "MLB_Calibration_Report.csv"),
        "floor_index": _file_info(TRACKING_DIR / "Floor_Play_Index.csv"),
        "injuries": _file_info(DATA_DIR / "injuries" / "MLB_Injuries.csv"),
        "scorecard_99": _file_info(TRACKING_DIR / "MLB_99_Scorecard.csv"),
    }

    audit_summary = {}
    if not audit.empty and "Status" in audit.columns:
        audit_summary = {str(k): int(v) for k, v in audit["Status"].value_counts().to_dict().items()}

    live_count = int((coverage["Status"].fillna("").astype(str).str.upper() == "LIVE").sum()) if not coverage.empty else 0
    requested_count = int(len(coverage)) if not coverage.empty else 0
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sport": "MLB",
        "coverage": {
            "requested": requested_count,
            "live": live_count,
            "missing": len(missing_markets),
            "one_sided": len(one_sided_markets),
            "missing_markets": missing_markets,
            "one_sided_markets": one_sided_markets,
        },
        "results": {
            "rows": int(len(all_results)),
            "resolved": resolved,
            "pending": pending,
            "floor_rows": floor_rows,
            "floor_resolved": floor_resolved,
        },
        "market_key_audit": audit_summary,
        "files": files,
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    history_row = {
        "CheckedAt": manifest["checked_at"],
        "RequestedMarkets": manifest["coverage"]["requested"],
        "LiveMarkets": manifest["coverage"]["live"],
        "MissingMarkets": manifest["coverage"]["missing"],
        "OneSidedMarkets": manifest["coverage"]["one_sided"],
        "AllPropRows": manifest["results"]["rows"],
        "ResolvedRows": manifest["results"]["resolved"],
        "PendingRows": manifest["results"]["pending"],
        "FloorRows": manifest["results"]["floor_rows"],
        "FloorResolved": manifest["results"]["floor_resolved"],
    }
    history = _read_csv(HISTORY_PATH)
    history = pd.concat([history, pd.DataFrame([history_row])], ignore_index=True)
    history.to_csv(HISTORY_PATH, index=False)

    print("=" * 60)
    print("BANKROLL KINGS - MLB REFRESH MANIFEST")
    print("=" * 60)
    print(f"Coverage: {manifest['coverage']['live']}/{manifest['coverage']['requested']} live, {manifest['coverage']['one_sided']} one-sided")
    if manifest["coverage"]["missing_markets"]:
        missing = ", ".join(row["stat"] for row in manifest["coverage"]["missing_markets"])
        print(f"Missing: {missing}")
    print(f"All-prop rows: {manifest['results']['rows']} | resolved: {manifest['results']['resolved']} | pending: {manifest['results']['pending']}")
    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
