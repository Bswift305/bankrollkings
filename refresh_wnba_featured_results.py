from __future__ import annotations

from datetime import datetime

from app import (
    load_candidate_archive,
    load_wnba_gamelogs,
    summarize_featured_candidate_archive,
    write_featured_results_snapshot_for_sport,
)
from services.qc_tracking import append_qc_run_log


def main() -> int:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archive_df = load_candidate_archive()
    gamelog_map = {"WNBA": load_wnba_gamelogs()}
    snapshot = write_featured_results_snapshot_for_sport("WNBA", archive_df=archive_df, gamelog_map=gamelog_map)
    sport_archive = archive_df.copy()
    if archive_df is not None and not archive_df.empty and "Sport" in archive_df.columns:
        sport_archive = archive_df[archive_df["Sport"].astype(str).str.upper() == "WNBA"].copy()
    summary = summarize_featured_candidate_archive(
        sport_archive,
        gamelog_map=gamelog_map,
    )

    report = {
        "checked_at": checked_at,
        "clean": True,
        "pass_count": int(len(snapshot)),
        "warning_count": 0,
        "failure_count": 0,
        "featured_prop_count": int(summary.get("totals", {}).get("candidates", 0) or 0),
        "notes": (
            f"Wrote {len(snapshot)} WNBA featured result rows. "
            f"Resolved {summary.get('totals', {}).get('resolved', 0)} of "
            f"{summary.get('totals', {}).get('candidates', 0)} archived featured plays."
        ),
    }
    append_qc_run_log("wnba_featured_results", report)
    print("=" * 60)
    print("WNBA FEATURED RESULTS SNAPSHOT")
    print("=" * 60)
    print(f"Checked at: {checked_at}")
    print(f"Rows written: {len(snapshot)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
