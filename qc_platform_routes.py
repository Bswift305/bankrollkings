from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app import app, find_user_by_email, save_user
from services.qc_tracking import append_qc_run_log


@dataclass(frozen=True)
class RouteCheck:
    path: str
    label: str
    markers: tuple[str, ...]
    group: str
    fast: bool = False


ROUTE_CHECKS: tuple[RouteCheck, ...] = (
    RouteCheck("/dashboard", "Home", ("HOME", "Live Sports"), "core", True),
    RouteCheck("/dashboard?postseason=1", "Dashboard", ("Platform Lens", "Sports Dashboard"), "core"),
    RouteCheck("/pricing", "Pricing", ("Choose Your Edge", "Pricing"), "core"),
    RouteCheck("/login", "Login", ("Welcome Back", "Pricing"), "core"),
    RouteCheck("/signup?plan=pro&billing=monthly", "Signup", ("Create Your Account", "Choose Plan"), "core"),
    RouteCheck("/info", "Info", ("How It Works", "Platform Lens"), "core"),
    RouteCheck("/glossary", "Glossary", ("Glossary", "Platform Lens"), "core"),
    RouteCheck("/test-drive", "Test Drive", ("Test Drive", "Platform Lens"), "core"),
    RouteCheck("/sports/nba?postseason=1", "NBA Command", ("NBA Data Pulse", "Tonight's Card"), "nba", True),
    RouteCheck("/schedule?postseason=1", "NBA Schedule", ("Schedule", "Upcoming"), "nba"),
    RouteCheck("/game-lines?postseason=1", "NBA Game Lines", ("Game Lines", "Market Read"), "nba"),
    RouteCheck("/sports/nba/props?postseason=1&sample=current&date=today", "NBA Props", ("Props Screener", "Platform Lens"), "nba", True),
    RouteCheck("/props/floor?postseason=1", "NBA Floor Plays", ("Floor Plays", "How To Use Floor Plays"), "nba"),
    RouteCheck("/market-edge?postseason=1&sample=current&date=today", "NBA Market Edge", ("Platform Lens", "Market Edge"), "nba"),
    RouteCheck("/matchup-lens?postseason=1", "NBA Matchup Lens", ("Tonight's Card", "Matchup Lens"), "nba"),
    RouteCheck("/matchup/CLE-DET?postseason=1", "NBA Matchup", ("Offensive Fit", "Team Form Snapshot"), "nba"),
    RouteCheck("/series/pistons-cavaliers?postseason=1", "NBA Series", ("Series Offensive Fit", "Playoff sample"), "nba"),
    RouteCheck("/trend-board?postseason=1", "NBA Trend Board", ("Playoff Field Consistency Trends", "PLAYOFF FIELD CONSISTENCY"), "nba"),
    RouteCheck("/bet-review?postseason=1", "NBA Bet Review", ("Review Lens", "Bet Review"), "nba"),
    RouteCheck("/candidate-review?postseason=1", "NBA Candidate Review", ("Candidate Review", "Review Lens"), "nba"),
    RouteCheck("/sports/nfl?postseason=1", "NFL Command", ("Closeout Check", "NFL Command Surface"), "football", True),
    RouteCheck("/sports/nfl/game-lines?postseason=1", "NFL Game Lines", ("Historical Coverage", "NFL Game Lines"), "football"),
    RouteCheck("/sports/nfl/totals?postseason=1", "NFL Totals", ("Historical Coverage", "NFL Totals"), "football"),
    RouteCheck("/sports/nfl/trends?postseason=1", "NFL Trends", ("Historical Coverage", "NFL Trends"), "football"),
    RouteCheck("/sports/nfl/props?postseason=1", "NFL Props", ("Historical Coverage", "NFL Props"), "football"),
    RouteCheck("/sports/nfl/matchup/game/car-at-tb?postseason=1", "NFL Matchup", ("Best Floor Plays", "Workbook"), "football"),
    RouteCheck("/sports/ncaaf?postseason=1", "CFB Command", ("Roster Coverage", "Top Returning Teams"), "football", True),
    RouteCheck("/sports/ncaaf/game-lines?postseason=1", "CFB Game Lines", ("Current Team Signals", "Top Returning Teams"), "football"),
    RouteCheck("/sports/ncaaf/totals?postseason=1", "CFB Totals", ("Top Returning Teams", "Current Team Signals"), "football"),
    RouteCheck("/sports/ncaaf/trends?postseason=1", "CFB Trends", ("Current Team Signals", "Top Returning Teams"), "football"),
    RouteCheck("/sports/ncaaf/props?postseason=1", "CFB Optional Props", ("Optional Props", "Current Team Signals"), "football"),
)


def _ensure_qc_user(plan: str = "sharp") -> dict:
    email = f"qc_platform_{plan}@bankrollkings.local"
    user = find_user_by_email(email)
    if user:
        return {
            "user_id": str(user.get("UserId") or user.get("user_id") or "").strip(),
            "email": str(user.get("Email") or user.get("email") or "").strip().lower(),
        }
    entry = {
        "UserId": uuid4().hex,
        "DisplayName": f"QC {plan.title()}",
        "Email": email,
        "PasswordHash": "",
        "Plan": plan,
        "BillingCycle": "monthly",
        "PlanStatus": "active",
        "CreatedAt": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "PlanSelectedAt": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
    }
    save_user(entry)
    return {
        "user_id": entry["UserId"],
        "email": entry["Email"].lower(),
    }


def _select_checks(tier: str) -> list[RouteCheck]:
    if tier == "fast":
        return [check for check in ROUTE_CHECKS if check.fast]
    return list(ROUTE_CHECKS)


def _chunk_checks(checks: list[RouteCheck], batch_size: int) -> list[list[RouteCheck]]:
    if batch_size <= 0:
        batch_size = len(checks) or 1
    return [checks[index:index + batch_size] for index in range(0, len(checks), batch_size)]


def run_qc(tier: str = "fast", batch_size: int = 8) -> dict:
    client = app.test_client()
    qc_user = _ensure_qc_user("sharp")
    with client.session_transaction() as sess:
        sess["user_id"] = qc_user["user_id"]
        sess["user_email"] = qc_user["email"]
    checks = _select_checks(tier)
    if tier == "fast":
        batches = [checks]
    else:
        batches = _chunk_checks(checks, batch_size=batch_size)

    failures: list[dict] = []
    results: list[dict] = []
    batch_reports: list[dict] = []

    for batch_index, batch_checks in enumerate(batches, start=1):
        batch_failures = 0
        batch_results: list[dict] = []
        for check in batch_checks:
            response = client.get(check.path, follow_redirects=True)
            text = response.get_data(as_text=True)
            ok = response.status_code == 200 and any(marker in text for marker in check.markers)
            result = {
                "group": check.group,
                "label": check.label,
                "path": check.path,
                "status_code": response.status_code,
                "ok": ok,
                "content_length": len(text),
                "batch": batch_index,
            }
            results.append(result)
            batch_results.append(result)
            if not ok:
                batch_failures += 1
                failures.append({
                    "group": check.group,
                    "label": check.label,
                    "path": check.path,
                    "status_code": response.status_code,
                    "markers": list(check.markers),
                    "batch": batch_index,
                })
        batch_reports.append({
            "batch": batch_index,
            "route_count": len(batch_checks),
            "failure_count": batch_failures,
            "completed": True,
        })
        if tier != "fast":
            append_qc_run_log(
                f"platform_routes_{tier}_batch",
                {
                    "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "route_count": len(batch_checks),
                    "pass_count": max(len(batch_checks) - batch_failures, 0),
                    "failure_count": batch_failures,
                    "clean": batch_failures == 0,
                    "notes": f"Tier={tier} | Batch={batch_index}/{len(batches)} | Completed=1 | Paths={', '.join(item['label'] for item in batch_results)}",
                },
            )

    group_counts: dict[str, int] = {}
    for result in results:
        group_counts[result["group"]] = group_counts.get(result["group"], 0) + 1

    notes = (
        f"Tier={tier} | "
        f"Batches={len(batch_reports)} | "
        f"Completed={sum(1 for batch in batch_reports if batch['completed'])}/{len(batch_reports)}"
    )
    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "route_count": len(checks),
        "groups": group_counts,
        "failures": failures,
        "failure_count": len(failures),
        "warning_count": 0,
        "results": results,
        "tier": tier,
        "batch_count": len(batch_reports),
        "batches": batch_reports,
        "pass_count": max(len(checks) - len(failures), 0),
        "clean": len(failures) == 0,
        "notes": notes,
    }
    append_qc_run_log(f"platform_routes_{tier}", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bankroll Kings platform smoke routes")
    parser.add_argument("--tier", choices=("fast", "slow", "full"), default="fast")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    report = run_qc(tier=args.tier, batch_size=args.batch_size)
    print("=" * 60)
    print("BANKROLL KINGS PLATFORM SMOKE TEST")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Tier: {report['tier']}")
    print(f"Routes checked: {report['route_count']}")
    print(f"Batches completed: {sum(1 for batch in report['batches'] if batch['completed'])}/{report['batch_count']}")
    print("Groups:")
    for group, count in sorted(report["groups"].items()):
        print(f"  - {group}: {count}")
    print(f"Failures: {report['failure_count']}")
    print()

    if report["tier"] != "fast":
        for batch in report["batches"]:
            print(
                f"[BATCH] {batch['batch']} | routes={batch['route_count']} | failures={batch['failure_count']} | completed={batch['completed']}"
            )
        print()

    if not report["failures"]:
        print("All platform smoke routes passed.")
        return 0

    for failure in report["failures"]:
        print(
            f"[FAIL] batch={failure['batch']} | {failure['group']} | {failure['label']} | {failure['path']} | "
            f"status={failure['status_code']} | markers={', '.join(failure['markers'])}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
