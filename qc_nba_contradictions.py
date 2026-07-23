from __future__ import annotations

import argparse
from datetime import datetime

from app import (
    build_featured_nba_top_plays,
    build_live_props_board,
    load_injuries,
    load_return_overrides,
)
from services.nba_contradiction_qc import (
    audit_props,
    build_injury_context_age,
    prop_key,
)
from services.qc_tracking import (
    append_qc_run_log,
    build_warning_history_map,
    update_warning_history,
)


def build_runtime() -> dict:
    def featured_signature(row: dict) -> tuple[str, str, str, str, str, str, str]:
        return (
            *prop_key(row),
            str(row.get("best_book", "")).strip().upper(),
            str(row.get("current_line", row.get("line", ""))).strip(),
        )

    board_all = build_live_props_board(
        postseason_only=True,
        date_filter="all",
        sample_mode="current",
        sort_by="confidence",
        sort_dir="desc",
    )
    board_today = build_live_props_board(
        postseason_only=True,
        date_filter="today",
        sample_mode="current",
        sort_by="confidence",
        sort_dir="desc",
    )
    scored_props = list((board_all or {}).get("props", []))
    featured_props = build_featured_nba_top_plays(list((board_today or {}).get("props", [])), limit=20, min_confidence=70)
    featured_keys = {featured_signature(row) for row in featured_props}

    injuries = load_injuries()
    return_overrides = load_return_overrides()
    freshness_age = build_injury_context_age(injuries, return_overrides)

    for row in scored_props:
        row["_is_featured"] = featured_signature(row) in featured_keys

    return {
        "scored_props": scored_props,
        "featured_props": featured_props,
        "featured_keys": featured_keys,
        "injury_context_age_hours": freshness_age,
        "warning_history_map": build_warning_history_map("nba_contradictions"),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def run_qc() -> dict:
    runtime = build_runtime()
    audit = audit_props(runtime["scored_props"], runtime=runtime)
    report = {
        "checked_at": runtime["checked_at"],
        "scored_prop_count": len(runtime["scored_props"]),
        "featured_prop_count": len(runtime["featured_props"]),
        "pass_count": audit["pass_count"],
        "warning_count": audit["warning_count"],
        "failure_count": audit["failure_count"],
        "warnings": audit["warnings"],
        "failures": audit["failures"],
        "injury_context_age_hours": runtime.get("injury_context_age_hours"),
        "clean": audit["clean"],
    }
    update_warning_history("nba_contradictions", report["warnings"], report["failures"], report["checked_at"])
    # Zero plays means nothing was evaluated -- the absence of failures is not
    # evidence of clean suggestion integrity. Flag it so scorecards can treat
    # it as N/A rather than a vacuous PASS (offseason boards hit this).
    report["unverified"] = int(report.get("featured_prop_count") or 0) == 0
    append_qc_run_log("nba_contradictions", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bankroll Kings NBA contradiction QC")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as blocking.")
    parser.add_argument("--report-only", action="store_true", help="Always exit 0 after reporting.")
    parser.add_argument("--player", type=str, default="", help="Only print issues for one player.")
    args = parser.parse_args()

    report = run_qc()
    player_filter = args.player.strip().lower()

    print("=" * 60)
    print("NBA CONTRADICTION QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Scored props: {report['scored_prop_count']}")
    print(f"Featured props: {report['featured_prop_count']}")
    age = report.get("injury_context_age_hours")
    if age is not None:
        print(f"Injury/return context age: {age:.1f}h")
    print(f"Passes: {report['pass_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    if report.get("unverified"):
        print("Status: UNVERIFIED (0 plays evaluated -- absence of failures is not evidence)")
    else:
        print(f"Clean: {report['clean']}")
    print()

    for label, items in (("FAIL", report["failures"]), ("WARN", report["warnings"])):
        for item in items:
            if player_filter and player_filter not in item.player.lower():
                continue
            featured_label = " | featured" if item.featured else ""
            print(f"[{label}] {item.player} | {item.stat} | {item.rule}{featured_label} | {item.message}")

    if args.report_only:
        return 0
    if report["failure_count"] > 0:
        return 1
    if args.strict and report["warning_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
