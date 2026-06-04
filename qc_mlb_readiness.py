from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from app import (
    app,
    DATA_DIR,
    load_mlb_game_market_odds,
    load_mlb_gamelogs,
    load_mlb_market_coverage,
    load_mlb_live_props_feed,
    load_mlb_schedule,
)
from qc_mlb_injuries import run_qc as run_mlb_injury_qc
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/mlb", ("MLB Slate Intelligence", "MLB Prop Board")),
    ("/sports/mlb/market-edge", ("MLB Market Edge", "MLB Slate Intelligence")),
    ("/sports/mlb/floor", ("MLB Floor Plays", "MLB Slate Intelligence")),
    ("/sports/mlb/trends", ("MLB Trends", "MLB Slate Intelligence")),
)


def run_qc(skip_routes: bool = False) -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    props_df, refresh_meta = load_mlb_live_props_feed(require_fresh=False)
    odds_df = load_mlb_game_market_odds()
    schedule_df = load_mlb_schedule()
    gamelogs_df = load_mlb_gamelogs()

    failures: list[str] = []
    warnings: list[str] = []
    advisories: list[str] = []
    route_count = 0
    if skip_routes:
        advisories.append("Route render checks skipped for daily refresh; scorecards cover page-level QA.")
    else:
        client = app.test_client()
        qc_user = _ensure_qc_user("sharp")
        with client.session_transaction() as sess:
            sess["user_id"] = qc_user["user_id"]
            sess["user_email"] = qc_user["email"]
        for path, markers in ROUTES:
            route_count += 1
            response = client.get(path)
            text = response.get_data(as_text=True)
            if response.status_code != 200 or not any(marker in text for marker in markers):
                failures.append(f"{path}: expected MLB page markers not found (status {response.status_code}).")

    if schedule_df.empty:
        warnings.append("MLB schedule feed is not loaded yet.")
    if odds_df.empty:
        warnings.append("MLB odds feed is not loaded yet.")
    if props_df.empty:
        warnings.append("MLB props feed is not loaded yet.")
    if gamelogs_df.empty:
        warnings.append("MLB game logs are not loaded yet.")
    if refresh_meta.get("is_stale"):
        warnings.append(f"MLB live props are stale at {refresh_meta.get('age_hours')}h old.")

    coverage = load_mlb_market_coverage()
    missing_markets = coverage.get("missing", [])
    if missing_markets:
        hard_missing = []
        unavailable_today = []
        for row in missing_markets:
            reason = str(row.get("missing_reason") or "").strip().lower()
            if "returned no rows" in reason or "no rows from selected books" in reason:
                unavailable_today.append(row)
            else:
                hard_missing.append(row)
        if hard_missing:
            missing_labels = ", ".join(row.get("stat", "") for row in hard_missing)
            warnings.append(f"MLB market coverage has missing required markets: {missing_labels}.")
        if unavailable_today:
            missing_labels = ", ".join(row.get("stat", "") for row in unavailable_today)
            advisories.append(f"Markets requested but not offered by selected books today: {missing_labels}.")

    context_path = DATA_DIR / "context" / "MLB_GameContext.csv"
    context_df = pd.read_csv(context_path) if context_path.exists() else pd.DataFrame()
    if context_df.empty:
        warnings.append("MLB game context is empty; weather, umpire, and ballpark tags are not fully active.")
    else:
        if "Ballpark" in context_df.columns and context_df["Ballpark"].fillna("").astype(str).str.strip().eq("").any():
            warnings.append("MLB game context has games missing ballpark labels.")
        if "Temperature" in context_df.columns and context_df["Temperature"].fillna("").astype(str).str.strip().eq("").all():
            advisories.append("Weather feed is not connected yet; ballpark/run-environment context is still available.")
        if "Umpire" in context_df.columns and context_df["Umpire"].fillna("").astype(str).str.strip().eq("").all():
            advisories.append("Umpire assignments are not connected yet; pitcher/K context runs without zone adjustment.")

    injury_report = run_mlb_injury_qc(persist=False)
    if injury_report.get("failure_count", 0) > 0:
        failures.append(
            f"MLB injury feed QC has {injury_report.get('failure_count', 0)} active failures."
        )
    elif injury_report.get("warning_count", 0) > 0:
        warnings.append(
            f"MLB injury feed QC still has {injury_report.get('warning_count', 0)} warnings."
        )

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": max(route_count - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": route_count,
        "notes": " | ".join(
            [
                f"Props rows: {len(props_df)}",
                f"Odds rows: {len(odds_df)}",
                f"Schedule rows: {len(schedule_df)}",
                f"Gamelog rows: {len(gamelogs_df)}",
                *advisories,
            ]
        ),
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("mlb_readiness", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MLB data and optional route readiness QC.")
    parser.add_argument("--skip-routes", action="store_true", help="Skip expensive Flask route rendering checks.")
    args = parser.parse_args()
    report = run_qc(skip_routes=args.skip_routes)
    print("=" * 60)
    print("MLB READINESS QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Routes checked: {report['route_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    print()
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
