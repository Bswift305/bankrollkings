from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
OUTPUT_JSON = TRACKING_DIR / "Formula_Status.json"
OUTPUT_CSV = TRACKING_DIR / "Formula_Status.csv"

SPORT_CONFIG = {
    "NBA": {
        "formula": "BK NBA EdgeScore",
        "scored": TRACKING_DIR / "NBA_AllPropResults.csv",
        "calibration": TRACKING_DIR / "NBA_Calibration_Report.csv",
    },
    "WNBA": {
        "formula": "BK WNBA EdgeScore",
        "scored": TRACKING_DIR / "WNBA_AllPropResults.csv",
        "calibration": TRACKING_DIR / "WNBA_Calibration_Report.csv",
    },
    "MLB": {
        "formula": "BK MLB ContextScore",
        "scored": TRACKING_DIR / "MLB_AllPropResults_Scored.csv",
        "calibration": TRACKING_DIR / "MLB_Formula_Calibration_Summary.csv",
    },
    "NFL": {
        "formula": "BK NFL EdgeScore + PropScore",
        "scored": TRACKING_DIR / "NFL_AllPropResults_Scored.csv",
        "calibration": TRACKING_DIR / "NFL_Formula_Calibration_Summary.csv",
    },
    "NCAAF": {
        "formula": "BK CFB EdgeScore",
        "scored": TRACKING_DIR / "NCAAF_AllPropResults.csv",
        "calibration": TRACKING_DIR / "NCAAF_Calibration_Report.csv",
    },
}


def _mtime(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _read_head(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False, nrows=1000)
    except Exception:
        return pd.DataFrame()


def _model_version(df: pd.DataFrame, sport: str) -> str:
    version_cols = ["ModelVersion", "PropModelVersion", "MLBModelVersion"]
    versions = []
    for col in version_cols:
        if col in df.columns:
            values = sorted({str(value).strip() for value in df[col].dropna().tolist() if str(value).strip()})
            versions.extend(values[:2])
    if versions:
        return " + ".join(dict.fromkeys(versions))
    if sport == "MLB":
        return "MLB_ContextScore_v1"
    if sport == "NFL":
        return "NFL_EdgeScore_v1 + NFL_PropScore_v1"
    return f"{sport}_Calibration_v1"


def build_formula_status() -> list[dict]:
    rows = []
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for sport, config in SPORT_CONFIG.items():
        scored_path = config["scored"]
        calibration_path = config["calibration"]
        df = _read_head(scored_path)
        status = "LIVE" if scored_path.exists() and calibration_path.exists() else "NEEDS_CALIBRATION"
        rows.append({
            "Sport": sport,
            "Formula": config["formula"],
            "ModelVersion": _model_version(df, sport),
            "Status": status,
            "ScoredArtifact": str(scored_path.relative_to(BASE_DIR)),
            "CalibrationArtifact": str(calibration_path.relative_to(BASE_DIR)),
            "LastScoredAt": _mtime(scored_path),
            "LastCalibratedAt": _mtime(calibration_path),
            "CheckedAt": checked_at,
        })
    return rows


def main() -> int:
    rows = build_formula_status()
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
    print("=" * 60)
    print("BANKROLL KINGS - FORMULA STATUS")
    print("=" * 60)
    print(f"Rows written: {len(rows)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"CSV: {OUTPUT_CSV}")
    print(pd.DataFrame(rows)[["Sport", "Formula", "ModelVersion", "Status", "LastCalibratedAt"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
