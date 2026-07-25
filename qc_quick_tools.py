"""Smoke QC for the cross-sport Quick Tools (/tools/*).

These seven surfaces were built fast in one session and share loaders/caches, so a
regression in any one (a renamed context key, a bad groupby, a template typo) would
otherwise ship silently. This renders each route with an authenticated QC session and
asserts a 200 plus a distinctive marker, then exercises the filter/input paths that carry
the real logic (best-lines pagination, risk-radar flag filter, ticket-check parsing).
"""
from __future__ import annotations

from datetime import datetime

from app import app
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


# (path, [any-of markers that prove the page rendered its own content, not an error/gate])
ROUTES = [
    ("/tools/slate-pulse", ["Slate", "slate-table", "Live Sports"]),
    ("/tools/best-lines", ["Best", "best-lines-table", "Best Number"]),
    ("/tools/risk-radar", ["Risk", "rr-table", "verified warnings", "No warnings"]),
    ("/tools/ticket-check", ["Ticket", "Check Ticket", "Paste a ticket"]),
    ("/tools/game-context", ["Game", "Context Coverage", "gc-matrix"]),
    ("/tools/track-record", ["Track", "Break-Even", "Forward-captured"]),
    ("/tools/injury-report", ["Injury", "inj-table", "Injury Report"]),
]

# Paths that exercise the logic-bearing query/input handling.
LOGIC_PATHS = [
    "/tools/best-lines?league=mlb&direction=OVER&multi=1",
    "/tools/best-lines?page=2",
    "/tools/risk-radar?flag=injury",
    "/tools/track-record?sport=MLB&min_sample=50",
    "/tools/ticket-check?legs=MLB%20%7C%20Aaron%20Judge%20%7C%20Home%20Runs%20%7C%20Over%20%7C%20%2B150",
]


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = app.test_client()
    qc_user = _ensure_qc_user("sharp")
    with client.session_transaction() as sess:
        sess["user_id"] = qc_user["user_id"]
        sess["user_email"] = qc_user["email"]

    failures: list[str] = []
    checks = 0

    for path, markers in ROUTES:
        checks += 1
        try:
            resp = client.get(path)
        except Exception as exc:  # a raised exception in the view is the worst case
            failures.append(f"{path}: raised {type(exc).__name__}: {str(exc)[:120]}")
            continue
        text = resp.get_data(as_text=True)
        if resp.status_code != 200:
            failures.append(f"{path}: HTTP {resp.status_code} (expected 200).")
        elif not any(marker in text for marker in markers):
            failures.append(f"{path}: 200 but none of the expected markers rendered {markers}.")

    for path in LOGIC_PATHS:
        checks += 1
        try:
            resp = client.get(path)
        except Exception as exc:
            failures.append(f"{path}: raised {type(exc).__name__}: {str(exc)[:120]}")
            continue
        if resp.status_code != 200:
            failures.append(f"{path}: HTTP {resp.status_code} (expected 200).")

    # The ticket parser must actually flag an all-over injured ticket.
    checks += 1
    ticket = ("MLB | Aaron Judge | Home Runs | Over | +150\n"
              "MLB | Aaron Judge | Total Bases | Over | +120\n"
              "NBA | Some Longshot | Points | Over | +800")
    from urllib.parse import quote
    tresp = client.get("/tools/ticket-check?legs=" + quote(ticket))
    ttext = tresp.get_data(as_text=True)
    if "All-OVER" not in ttext:
        failures.append("ticket-check: an all-over ticket did not raise the All-OVER warning.")

    report = {
        "checked_at": checked_at,
        "check_count": checks,
        "failure_count": len(failures),
        "clean": not failures,
        "failures": failures,
    }
    append_qc_run_log("quick_tools", {
        "checked_at": checked_at,
        "clean": not failures,
        "pass_count": checks - len(failures),
        "warning_count": 0,
        "failure_count": len(failures),
        "notes": f"Quick Tools smoke: {checks - len(failures)}/{checks} checks passed.",
    })
    return report


def main() -> int:
    report = run_qc()
    print("=" * 64)
    print("QUICK TOOLS SMOKE QC")
    print("=" * 64)
    print(f"Checked at: {report['checked_at']}")
    print(f"Checks: {report['check_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print()
    if report["clean"]:
        print("All Quick Tools rendered and their logic paths held.")
        return 0
    for failure in report["failures"]:
        print(f"[FAIL] {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
