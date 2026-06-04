from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
TRACKING_DIR = BASE_DIR / "data" / "tracking"
JSON_PATH = TRACKING_DIR / "Run_Status.json"
CSV_PATH = TRACKING_DIR / "Run_Status.csv"


CHECKS = [
    {
        "name": "Daily Operator",
        "kind": "log",
        "patterns": ["daily_operator_*.log", "daily_refresh_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Full refresh wrapper for active sports plus analysis.",
    },
    {
        "name": "Edge Engine",
        "kind": "log",
        "patterns": ["bk_edge_engine_pipeline_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Formula, calibration, streak heat, drift, and status chain.",
    },
    {
        "name": "Scorecards",
        "kind": "log",
        "patterns": ["all_scorecards_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "NBA/WNBA/MLB/NFL/prelaunch readiness checks.",
    },
    {
        "name": "NBA Results",
        "kind": "artifact",
        "paths": ["data/tracking/NBA_AllPropResults.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Resolved NBA prop history used by review and calibration.",
    },
    {
        "name": "WNBA Results",
        "kind": "artifact",
        "paths": ["data/tracking/WNBA_AllPropResults.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Resolved WNBA prop history used by review and calibration.",
    },
    {
        "name": "MLB Results",
        "kind": "artifact",
        "paths": ["data/tracking/MLB_AllPropResults_Scored.csv", "data/tracking/MLB_AllPropResults.csv"],
        "fresh_hours": 24,
        "aging_hours": 42,
        "note": "Scored MLB prop history and context scores.",
    },
    {
        "name": "Injury Refresh",
        "kind": "artifact",
        "paths": [
            "data/injuries/NBA_Injuries.csv",
            "data/injuries/WNBA_Injuries.csv",
            "data/injuries/NFL_Injuries.csv",
            "data/injuries/MLB_Injuries.csv",
        ],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "All-sport injury files. WATCH can still mean source preserved last-good data.",
    },
    {
        "name": "Formula Status",
        "kind": "artifact",
        "paths": ["data/tracking/Formula_Status.json"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Board-facing formula and model status badge source.",
    },
    {
        "name": "Driver Calibration",
        "kind": "artifact",
        "paths": ["data/tracking/Sport_Driver_Calibration.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Sport-specific promote/reduce driver buckets.",
    },
    {
        "name": "Streak Heat",
        "kind": "artifact",
        "paths": ["data/tracking/Streak_Heat_Index.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Hot-hand streak chart index.",
    },
    {
        "name": "Active Simulations",
        "kind": "artifact",
        "paths": ["data/tracking/Active_Sport_Simulation_Summary.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "NBA/WNBA/MLB simulated hit probability summary.",
    },
    {
        "name": "Team Priors",
        "kind": "artifact",
        "paths": ["data/tracking/Team_Strength_Priors.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Market and result based team-strength priors for game environment.",
    },
    {
        "name": "MLB Umpires",
        "kind": "artifact",
        "paths": ["data/context/MLB_UmpireAssignments.csv"],
        "fresh_hours": 24,
        "aging_hours": 42,
        "note": "Home plate umpire sidecar used by MLB context scoring.",
    },
    {
        "name": "Drift Alerts",
        "kind": "artifact",
        "paths": ["data/tracking/Live_Drift_Alerts.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Featured vs unplayed drift warnings.",
    },
]


def _latest_file(patterns: list[str], base: Path) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(base.glob(pattern))
    files = [path for path in matches if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _latest_artifact(paths: list[str]) -> Path | None:
    files = [BASE_DIR / path for path in paths]
    existing = [path for path in files if path.exists() and path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _age_hours(path: Path, now: datetime) -> float:
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return max(0.0, (now - modified).total_seconds() / 3600)


def _classify(age: float | None, fresh_hours: int, aging_hours: int) -> str:
    if age is None:
        return "MISSING"
    if age <= fresh_hours:
        return "FRESH"
    if age <= aging_hours:
        return "AGING"
    return "STALE"


def _status_note(status: str) -> str:
    return {
        "FRESH": "Green",
        "AGING": "Watch",
        "STALE": "Needs refresh",
        "MISSING": "Missing",
    }.get(status, "Unknown")


def build_run_status() -> dict:
    now = datetime.now(timezone.utc)
    rows = []
    for check in CHECKS:
        if check["kind"] == "log":
            artifact = _latest_file(check.get("patterns", []), LOG_DIR)
        else:
            artifact = _latest_artifact(check.get("paths", []))

        age = _age_hours(artifact, now) if artifact else None
        status = _classify(age, int(check["fresh_hours"]), int(check["aging_hours"]))
        modified = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc) if artifact else None
        rows.append({
            "Name": check["name"],
            "Status": status,
            "StatusNote": _status_note(status),
            "LastRunAt": modified.astimezone().isoformat(timespec="seconds") if modified else "",
            "AgeHours": round(age, 2) if age is not None else "",
            "Artifact": str(artifact.relative_to(BASE_DIR)) if artifact else "",
            "Note": check["note"],
        })

    counts = {status: sum(1 for row in rows if row["Status"] == status) for status in ["FRESH", "AGING", "STALE", "MISSING"]}
    overall = "GREEN" if counts["STALE"] == 0 and counts["MISSING"] == 0 else "WATCH"
    if counts["FRESH"] == 0:
        overall = "RED"
    return {
        "generated_at": now.astimezone().isoformat(timespec="seconds"),
        "overall": overall,
        "counts": counts,
        "rows": rows,
    }


def write_outputs(payload: dict) -> None:
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = payload.get("rows", [])
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Name", "Status", "StatusNote", "LastRunAt", "AgeHours", "Artifact", "Note"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    payload = build_run_status()
    write_outputs(payload)
    print("=" * 60)
    print("BANKROLL KINGS - RUN STATUS")
    print("=" * 60)
    print(f"Overall: {payload['overall']}")
    print(f"Output: {JSON_PATH}")
    for row in payload["rows"]:
        print(f"{row['Status']:<7} {row['Name']:<20} {row['AgeHours']}h {row['Artifact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
