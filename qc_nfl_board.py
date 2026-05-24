from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import (
    app,
    build_football_history_lab,
    build_football_history_status,
    build_football_live_games,
    build_football_live_prop_board,
    load_nfl_floor_board,
    load_nfl_game_market_odds,
    load_nfl_props,
    load_nfl_schedule,
)
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


def _contains_all(text: str, snippets: list[str]) -> bool:
    return all(snippet in text for snippet in snippets)


def run_qc() -> dict:
    issues: list[dict] = []
    notes: list[str] = []

    board = load_nfl_floor_board()
    history_lab = build_football_history_lab("nfl")
    history_status = build_football_history_status(history_lab)
    live_odds = load_nfl_game_market_odds()
    live_schedule = load_nfl_schedule()
    live_props = load_nfl_props()
    live_games = build_football_live_games(live_odds, live_schedule, date_filter="all")
    live_prop_rows = build_football_live_prop_board(
        live_props,
        live_odds,
        live_schedule,
        method_key="props",
        date_filter="all",
    )

    if not board.get("available"):
        issues.append({
            "severity": "high",
            "category": "workbook",
            "message": "NFL floor workbook is not available.",
        })

    games = list(board.get("games", []))
    top_plays = list(board.get("top_plays", []))
    if board.get("available") and not games:
        issues.append({
            "severity": "high",
            "category": "workbook",
            "message": "NFL floor workbook loaded but no matchup tabs were parsed.",
        })
    if board.get("available") and not top_plays:
        issues.append({
            "severity": "medium",
            "category": "workbook",
            "message": "NFL floor workbook loaded but no top plays were parsed.",
        })

    if int(history_lab.get("props_history_rows") or 0) <= 0:
        issues.append({
            "severity": "high",
            "category": "history",
            "message": "NFL prop archive is empty.",
        })
    if int(history_lab.get("game_line_history_rows") or 0) <= 0:
        issues.append({
            "severity": "high",
            "category": "history",
            "message": "NFL game-line history is empty.",
        })
    if history_status.get("state") != "ready":
        issues.append({
            "severity": "medium",
            "category": "history",
            "message": f"NFL history status is {history_status.get('state') or 'unknown'}, not ready.",
        })

    if not live_games and not live_prop_rows:
        notes.append(
            f"Live NFL slate is empty right now (schedule {len(live_schedule)}, odds {len(live_odds)}, props {len(live_props)}). "
            "Workbook and historical layers must carry the board until the next live pull."
        )

    with app.test_client() as client:
        qc_user = _ensure_qc_user("sharp")
        with client.session_transaction() as sess:
            sess["user_id"] = qc_user["user_id"]
            sess["user_email"] = qc_user["email"]
        route_expectations = [
            ("/sports/nfl?postseason=1", ["Platform Lens", "Closeout Check"]),
            ("/sports/nfl/game-lines?postseason=1", ["Why This Method Matters", "Historical Coverage"]),
            ("/sports/nfl/totals?postseason=1", ["Why This Method Matters", "Historical Coverage"]),
            ("/sports/nfl/trends?postseason=1", ["Why This Method Matters", "Historical Coverage"]),
            ("/sports/nfl/props?postseason=1", ["Why This Method Matters", "Historical Coverage"]),
        ]
        for route, snippets in route_expectations:
            response = client.get(route)
            body = response.get_data(as_text=True)
            if response.status_code != 200:
                issues.append({
                    "severity": "high",
                    "category": "routes",
                    "message": f"{route} returned {response.status_code}.",
                })
                continue
            if not _contains_all(body, snippets):
                issues.append({
                    "severity": "medium",
                    "category": "routes",
                    "message": f"{route} is missing expected framing text.",
                })

        if games:
            first = games[0]
            sheet = str(first.get("sheet", "")).strip()
            slug = str(first.get("matchup_slug", "")).strip()
            if sheet:
                response = client.get(f"/sports/nfl/matchup/{sheet}?postseason=1")
                if response.status_code != 200:
                    issues.append({
                        "severity": "high",
                        "category": "matchup_route",
                        "message": f"Sheet-based NFL matchup route failed for {sheet}.",
                    })
            if slug:
                response = client.get(f"/sports/nfl/matchup/game/{slug}?postseason=1")
                if response.status_code != 200:
                    issues.append({
                        "severity": "high",
                        "category": "matchup_route",
                        "message": f"Slug-based NFL matchup route failed for {slug}.",
                    })

    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "workbook_games": len(games),
        "workbook_top_plays": len(top_plays),
        "history_props_rows": int(history_lab.get("props_history_rows") or 0),
        "history_line_rows": int(history_lab.get("game_line_history_rows") or 0),
        "live_games": len(live_games),
        "live_prop_rows": len(live_prop_rows),
        "issue_count": len(issues),
        "issues": issues,
        "notes": notes,
    }
    append_qc_run_log("nfl_board", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Workbook matchups: {report['workbook_games']}")
    print(f"Workbook top plays: {report['workbook_top_plays']}")
    print(f"Historical prop rows: {report['history_props_rows']}")
    print(f"Historical game-line rows: {report['history_line_rows']}")
    print(f"Live game rows: {report['live_games']}")
    print(f"Live prop rows: {report['live_prop_rows']}")
    print(f"Issues found: {report['issue_count']}")
    print()
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No blocking NFL QC issues detected.")
        return 0

    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
