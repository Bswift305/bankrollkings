from __future__ import annotations

from datetime import datetime

from app import (
    load_candidate_archive,
    load_nba_review_gamelogs,
    summarize_featured_candidate_archive,
    write_featured_results_snapshot,
)
from services.qc_tracking import append_qc_run_log


def main() -> int:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archive_df = load_candidate_archive()
    gamelog_map = {"NBA": load_nba_review_gamelogs()}
    snapshot = write_featured_results_snapshot(archive_df=archive_df, gamelog_map=gamelog_map)
    summary = summarize_featured_candidate_archive(archive_df, gamelog_map=gamelog_map)

    report = {
        "checked_at": checked_at,
        "clean": True,
        "pass_count": int(len(snapshot)),
        "warning_count": 0,
        "failure_count": 0,
        "scored_prop_count": 0,
        "featured_prop_count": int(summary.get("totals", {}).get("candidates", 0) or 0),
        "notes": (
            f"Wrote {len(snapshot)} featured result rows. "
            f"Resolved {summary.get('totals', {}).get('resolved', 0)} of "
            f"{summary.get('totals', {}).get('candidates', 0)} archived featured plays."
        ),
    }
    append_qc_run_log("nba_featured_results", report)

    totals = summary.get("totals", {})
    print("=" * 60)
    print("NBA FEATURED RESULTS SNAPSHOT")
    print("=" * 60)
    print(f"Checked at: {checked_at}")
    print(f"Rows written: {len(snapshot)}")
    print(f"Candidates: {totals.get('candidates', 0)}")
    print(f"Resolved: {totals.get('resolved', 0)}")
    print(f"Hits: {totals.get('hits', 0)}")
    print(f"Misses: {totals.get('misses', 0)}")
    print(f"Pushes: {totals.get('pushes', 0)}")
    print(f"Pending: {totals.get('pending', 0)}")
    print(f"Hit rate: {totals.get('hit_rate')}")
    print(f"Avg CLV line: {totals.get('avg_clv_line')}")
    print(f"Avg CLV price pct: {totals.get('avg_clv_price_pct')}")
    print(f"Positive CLV rate: {totals.get('positive_clv_rate')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
