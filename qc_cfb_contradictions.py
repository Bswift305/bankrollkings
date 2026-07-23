from __future__ import annotations

from datetime import datetime

from app import (
    build_football_live_prop_board,
    load_ncaaf_game_market_odds,
    load_ncaaf_live_props_feed,
    load_ncaaf_schedule,
)
from services.cfb_contradiction_qc import audit_plays
from services.qc_tracking import (
    append_qc_run_log,
    build_warning_history_map,
    update_warning_history,
)


def build_runtime() -> dict:
    props_df, refresh_meta = load_ncaaf_live_props_feed(require_fresh=True)
    odds_df = load_ncaaf_game_market_odds()
    schedule_df = load_ncaaf_schedule()
    plays = build_football_live_prop_board(
        props_df,
        odds_df,
        schedule_df,
        method_key="props",
        date_filter="all",
        sport_key="ncaaf",
    )
    for idx, play in enumerate(plays):
        play["_is_featured"] = idx < 12
    return {
        "plays": plays,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "refresh_meta": refresh_meta,
        "warning_history_map": build_warning_history_map("cfb_contradictions"),
    }


def run_qc(persist: bool = True) -> dict:
    runtime = build_runtime()
    audit = audit_plays(runtime["plays"], runtime=runtime)
    report = {
        "checked_at": runtime["checked_at"],
        "clean": audit["clean"],
        "pass_count": audit["pass_count"],
        "warning_count": audit["warning_count"],
        "failure_count": audit["failure_count"],
        "featured_prop_count": sum(1 for play in runtime["plays"] if bool(play.get("_is_featured"))),
        "live_prop_rows": len(runtime["plays"]),
        "notes": (
            f"Props status: {runtime['refresh_meta'].get('status')} | "
            f"Books: {runtime['refresh_meta'].get('book_count', 0)} | "
            f"Rows: {runtime['refresh_meta'].get('row_count', 0)}"
        ),
        "warnings": audit["warnings"],
        "failures": audit["failures"],
    }
    if persist:
        update_warning_history("cfb_contradictions", report["warnings"], report["failures"], report["checked_at"])
        # Zero plays means nothing was evaluated -- the absence of failures is not
    # evidence of clean suggestion integrity. Flag it so scorecards can treat
    # it as N/A rather than a vacuous PASS (offseason boards hit this).
    report["unverified"] = int(report.get("featured_prop_count") or 0) == 0
    append_qc_run_log("cfb_contradictions", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("CFB CONTRADICTION QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Live prop rows: {report['live_prop_rows']}")
    print(f"Featured rows audited: {report['featured_prop_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    if report.get("unverified"):
        print("Status: UNVERIFIED (0 plays evaluated -- absence of failures is not evidence)")
    else:
        print(f"Clean: {report['clean']}")
    print(report["notes"])
    print()
    for item in report["failures"]:
        print(f"[FAIL] {item.player} | {item.stat} | {item.rule} | {item.message}")
    for item in report["warnings"]:
        print(f"[WARN] {item.player} | {item.stat} | {item.rule} | {item.message}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
