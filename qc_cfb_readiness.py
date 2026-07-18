from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app import (
    app,
    load_ncaaf_live_props_feed,
)
from qc_cfb_contradictions import run_qc as run_cfb_contradiction_qc
from qc_cfb_injuries import run_qc as run_cfb_injury_qc
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/ncaaf?postseason=1", ("Roster Coverage", "Top Returning Teams")),
    ("/sports/ncaaf/game-lines?postseason=1", ("Current Team Signals", "Top Returning Teams")),
    ("/sports/ncaaf/totals?postseason=1", ("Top Returning Teams", "Current Team Signals")),
    ("/sports/ncaaf/trends?postseason=1", ("Current Team Signals", "Top Returning Teams")),
    # Props is the shared screener (props.html via render_props_screener_page),
    # not the method board — assert the board decision columns it actually renders,
    # mirroring the nfl_visual_trust check. The method-board markers ("Optional
    # Props", "Current Team Signals") only exist on football_method_board.html,
    # which serves ncaaf game-lines/totals/trends but NOT props.
    ("/sports/ncaaf/props?postseason=1", ("Market", "Confidence", "Player")),
)


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    props_df, refresh_meta = load_ncaaf_live_props_feed(require_fresh=False)
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
            failures.append(f"{path}: expected CFB page markers not found (status {response.status_code}).")
        if refresh_meta.get("warning") and path != "/sports/ncaaf?postseason=1" and refresh_meta["warning"] not in text:
            failures.append(f"{path}: stale-feed warning missing from CFB surface.")
        if path == "/sports/ncaaf?postseason=1" and not refresh_meta.get("has_live_props") and "Unavailable" not in text:
            failures.append(f"{path}: command page is not honestly showing unavailable live props state.")

    if refresh_meta.get("is_stale"):
        warnings.append(
            f"CFB live props are stale at {refresh_meta.get('age_hours')}h old, but the site is degrading honestly."
        )
    if not refresh_meta.get("has_live_props"):
        warnings.append("CFB live props are absent; props should remain support-only until live market volume improves.")

    if not Path("refresh_ncaaf_featured_results.py").exists():
        failures.append("Missing refresh_ncaaf_featured_results.py archive hook.")

    injury_report = run_cfb_injury_qc(persist=False)
    if injury_report.get("failure_count", 0) > 0:
        failures.append(
            f"CFB injury feed QC has {injury_report.get('failure_count', 0)} active failures."
        )
    elif injury_report.get("warning_count", 0) > 0:
        warnings.append(
            f"CFB injury feed QC still has {injury_report.get('warning_count', 0)} warnings."
        )
    contradiction_report = run_cfb_contradiction_qc(persist=False)
    if contradiction_report.get("failure_count", 0) > 0:
        failures.append(
            f"CFB contradiction QC has {contradiction_report.get('failure_count', 0)} active failures."
        )
    elif contradiction_report.get("warning_count", 0) > 0:
        warnings.append(
            f"CFB contradiction QC still has {contradiction_report.get('warning_count', 0)} warnings."
        )

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
            f"Rows: {refresh_meta.get('row_count', 0)}"
        ),
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("cfb_readiness", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("CFB READINESS QC")
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
