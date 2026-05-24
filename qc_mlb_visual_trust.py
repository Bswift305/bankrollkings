from __future__ import annotations

from datetime import datetime

from app import app, find_user_by_email
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/mlb", ("Daily Slate Command", "Live Board Status", "MLB Prop Board")),
    ("/sports/mlb/market-edge?date=all", ("MLB Method Board", "How To Use", "Context")),
    ("/sports/mlb/floor?date=all", ("MLB Method Board", "How To Use", "Context")),
    ("/sports/mlb/trends?date=all", ("MLB Method Board", "How To Use", "Context")),
)


def _owner_session(client) -> None:
    owner = find_user_by_email("decaturjones019@gmail.com")
    if not owner:
        return
    with client.session_transaction() as sess:
        sess["user_id"] = owner.get("UserId", "") or owner.get("user_id", "")
        sess["user_email"] = owner.get("Email", "") or owner.get("email", "")


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = app.test_client()
    _owner_session(client)

    failures: list[str] = []
    warnings: list[str] = []
    route_count = 0

    for path, markers in ROUTES:
        route_count += 1
        response = client.get(path)
        text = response.get_data(as_text=True)
        if response.status_code != 200:
            failures.append(f"{path}: returned {response.status_code}.")
            continue
        missing = [marker for marker in markers if marker not in text]
        if missing:
            failures.append(f"{path}: missing visual trust markers: {', '.join(missing)}.")

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": max(route_count - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": route_count,
        "notes": "Verified key MLB surfaces expose trust markers for live board state, method guidance, and context language.",
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("mlb_visual_trust", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("MLB VISUAL TRUST QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Routes checked: {report['route_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
