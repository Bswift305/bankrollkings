from __future__ import annotations

from datetime import datetime

from app import (
    app,
    build_football_history_lab,
    build_football_history_status,
    build_ncaaf_current_season_context,
    build_football_live_games,
    build_football_live_prop_board,
    load_ncaaf_game_market_odds,
    load_ncaaf_props,
    load_ncaaf_schedule,
)
from qc_platform_routes import _ensure_qc_user
from services.qc_tracking import append_qc_run_log


def _contains_all(text: str, snippets: list[str]) -> bool:
    return all(snippet in text for snippet in snippets)


def run_qc() -> dict:
    issues: list[dict] = []
    notes: list[str] = []

    current_context = build_ncaaf_current_season_context()
    history_lab = build_football_history_lab("ncaaf")
    history_status = build_football_history_status(history_lab)
    live_odds = load_ncaaf_game_market_odds()
    live_schedule = load_ncaaf_schedule()
    live_props = load_ncaaf_props()
    live_games = build_football_live_games(live_odds, live_schedule, date_filter="all")
    live_prop_rows = build_football_live_prop_board(
        live_props,
        live_odds,
        live_schedule,
        method_key="props",
        date_filter="all",
    )

    if current_context.get("state") != "ready":
        issues.append({
            "severity": "high",
            "category": "current_context",
            "message": f"CFB current-season context is {current_context.get('state') or 'unknown'}, not ready.",
        })

    if int((current_context.get("coverage_summary") or {}).get("ok") or 0) <= 0:
        issues.append({
            "severity": "high",
            "category": "rosters",
            "message": "No clean ESPN CFB roster responses are available.",
        })

    if int((current_context.get("coverage_summary") or {}).get("error") or 0) > 0:
        issues.append({
            "severity": "medium",
            "category": "rosters",
            "message": f"{current_context['coverage_summary']['error']} CFB roster pulls errored on the last refresh.",
        })

    if not current_context.get("team_signals"):
        issues.append({
            "severity": "medium",
            "category": "signals",
            "message": "CFB team signals are empty.",
        })

    if int(history_lab.get("props_history_rows") or 0) == 0 and int(history_lab.get("game_line_history_rows") or 0) == 0:
        notes.append("CFB historical datasets are still empty; current roster, returning production, and portal layers are carrying the sport for now.")

    if not live_games and not live_prop_rows:
        notes.append(
            f"Live CFB slate is empty right now (schedule {len(live_schedule)}, odds {len(live_odds)}, props {len(live_props)})."
        )

    with app.test_client() as client:
        # These are paid/gated routes -- without an authenticated QC session every
        # request 401s and reports as a false HIGH routes failure, so the board QC
        # could never come back clean. Mirror qc_cfb_readiness, which authenticates.
        qc_user = _ensure_qc_user("sharp")
        with client.session_transaction() as sess:
            sess["user_id"] = qc_user["user_id"]
            sess["user_email"] = qc_user["email"]
        # Markers must be what these routes ACTUALLY render, not aspirational text.
        # "Platform Lens" lives on other page types (game_lines/matchup), never on
        # the NCAAF command board -- it was a wrong expectation, not a regression.
        # /sports/ncaaf/props is the shared props SCREENER (render_props_screener_
        # page -> props.html), so it renders board decision columns, not the
        # method-board "Plain-English Verdict" marker -- same correction as the
        # qc_cfb_readiness props check (commit ad57615).
        route_expectations = [
            ("/sports/ncaaf?postseason=1", ["Roster & Continuity", "Historical Coverage"]),
            ("/sports/ncaaf/game-lines?postseason=1", ["Market Read", "Historical Coverage"]),
            ("/sports/ncaaf/totals?postseason=1", ["Matchup Read", "Historical Coverage"]),
            ("/sports/ncaaf/trends?postseason=1", ["Trend Read", "Historical Coverage"]),
            ("/sports/ncaaf/props?postseason=1", ["Market", "Confidence", "Player"]),
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

    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "context_state": current_context.get("state") or "",
        "roster_ok": int((current_context.get("coverage_summary") or {}).get("ok") or 0),
        "team_signals": len(current_context.get("team_signals") or []),
        "history_props_rows": int(history_lab.get("props_history_rows") or 0),
        "history_line_rows": int(history_lab.get("game_line_history_rows") or 0),
        "history_state": history_status.get("state") or "",
        "live_games": len(live_games),
        "live_prop_rows": len(live_prop_rows),
        "issue_count": len(issues),
        "issues": issues,
        "notes": notes,
    }
    append_qc_run_log("cfb_board", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS CFB QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Current context: {report['context_state']}")
    print(f"Roster coverage ok: {report['roster_ok']}")
    print(f"Team signals: {report['team_signals']}")
    print(f"Historical prop rows: {report['history_props_rows']}")
    print(f"Historical game-line rows: {report['history_line_rows']}")
    print(f"History state: {report['history_state']}")
    print(f"Live game rows: {report['live_games']}")
    print(f"Live prop rows: {report['live_prop_rows']}")
    print(f"Issues found: {report['issue_count']}")
    print()
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No blocking CFB QC issues detected.")
        return 0

    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
