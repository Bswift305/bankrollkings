from __future__ import annotations

from datetime import datetime

from app import (
    load_candidate_archive,
    load_nba_review_gamelogs,
    load_wnba_gamelogs,
    load_mlb_gamelogs,
    load_nfl_gamelogs,
    load_ncaaf_gamelogs,
    write_all_prop_results_snapshot_for_sport,
)
from build_floor_play_index import build_floor_play_index
from services.qc_tracking import append_qc_run_log


SPORT_LOGS = {
    "NBA": load_nba_review_gamelogs,
    "WNBA": load_wnba_gamelogs,
    "MLB": load_mlb_gamelogs,
    "NFL": load_nfl_gamelogs,
    "NCAAF": load_ncaaf_gamelogs,
}


def main() -> int:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archive_df = load_candidate_archive()
    total_rows = 0
    total_resolved = 0
    print("=" * 70)
    print("BANKROLL KINGS - ALL AVAILABLE PROP RESULTS")
    print("=" * 70)
    print(f"Checked at: {checked_at}")

    for sport, loader in SPORT_LOGS.items():
        gamelog_map = {sport: loader()}
        snapshot = write_all_prop_results_snapshot_for_sport(
            sport,
            archive_df=archive_df,
            gamelog_map=gamelog_map,
        )
        rows = int(len(snapshot))
        resolved = 0
        if rows and "OutcomeState" in snapshot.columns:
            resolved = int(snapshot["OutcomeState"].isin(["Hit", "Miss", "Push"]).sum())
        total_rows += rows
        total_resolved += resolved
        print(f"{sport}: rows={rows} resolved={resolved}")

    floor_index = build_floor_play_index()
    floor_rows = 0
    floor_resolved = 0
    if floor_index is not None and not floor_index.empty and "IsFloorPlay" in floor_index.columns:
        floor = floor_index[floor_index["IsFloorPlay"].astype(bool)].copy()
        floor_rows = int(len(floor))
        if "OutcomeState" in floor.columns:
            floor_resolved = int(floor["OutcomeState"].isin(["Hit", "Miss"]).sum())
    print(f"Floor index: rows={floor_rows} resolved={floor_resolved}")

    append_qc_run_log(
        "all_prop_results",
        {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": total_rows,
            "warning_count": 0,
            "failure_count": 0,
            "notes": f"Wrote {total_rows} full-board prop result rows; {total_resolved} resolved. Floor index rows={floor_rows}, resolved={floor_resolved}.",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
