from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app import (
    app,
    load_wnba_live_props_feed,
)
from qc_wnba_injuries import run_qc as run_wnba_injury_qc
from qc_wnba_contradictions import run_qc as run_wnba_contradiction_qc
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/wnba", ("Command Center", "Market", "Props")),
    ("/sports/wnba/market-edge", ("Market Edge", "WNBA market spots")),
    ("/sports/wnba/floor", ("Floor Plays", "steady WNBA floor candidates")),
    ("/sports/wnba/trends", ("Trends", "trend-backed WNBA candidates")),
)


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    props_df, refresh_meta = load_wnba_live_props_feed(require_fresh=False)
    client = app.test_client()
    qc_user = _ensure_qc_user("sharp")
    with client.session_transaction() as sess:
        sess["user_id"] = qc_user["user_id"]
        sess["user_email"] = qc_user["email"]

    failures: list[str] = []
    warnings: list[str] = []
    route_count = 0
    for path, markers in ROUTES:
        route_count += 1
        response = client.get(path)
        text = response.get_data(as_text=True)
        if response.status_code != 200 or not any(marker in text for marker in markers):
            failures.append(f"{path}: expected WNBA page markers not found (status {response.status_code}).")
        if refresh_meta.get("warning") and refresh_meta["warning"] not in text:
            failures.append(f"{path}: stale-feed warning missing from WNBA surface.")

    if refresh_meta.get("is_stale"):
        warnings.append(
            f"WNBA live props are stale at {refresh_meta.get('age_hours')}h old, but the site is degrading honestly."
        )
    if not refresh_meta.get("has_live_props"):
        warnings.append("WNBA live props are absent; archive/calibration volume may remain thin.")

    if not Path("refresh_wnba_featured_results.py").exists():
        failures.append("Missing refresh_wnba_featured_results.py archive hook.")

    injury_report = run_wnba_injury_qc(persist=False)
    if injury_report.get("failure_count", 0) > 0:
        failures.append(
            f"WNBA injury feed QC has {injury_report.get('failure_count', 0)} active failures."
        )
    elif injury_report.get("warning_count", 0) > 0:
        warnings.append(
            f"WNBA injury feed QC still has {injury_report.get('warning_count', 0)} warnings."
        )

    contradiction_report = run_wnba_contradiction_qc(persist=False)
    if contradiction_report.get("failure_count", 0) > 0:
        failures.append(
            f"WNBA contradiction QC has {contradiction_report.get('failure_count', 0)} active failures."
        )
    elif contradiction_report.get("warning_count", 0) > 0:
        warnings.append(
            f"WNBA contradiction QC still has {contradiction_report.get('warning_count', 0)} warnings."
        )

    advisory = "WNBA calibration is still maturing; this does not block daily board readiness."

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": max(route_count - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": route_count,
        "notes": (
            f"Props status: {refresh_meta.get('status')} | "
            f"Books: {refresh_meta.get('book_count', 0)} | "
            f"Rows: {refresh_meta.get('row_count', 0)} | "
            f"{advisory}"
        ),
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("wnba_readiness", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("WNBA READINESS QC")
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
