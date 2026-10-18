from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from app import (
    load_candidate_archive,
    load_nba_review_gamelogs,
    load_wnba_gamelogs,
    load_mlb_gamelogs,
    load_nfl_gamelogs,
    load_ncaaf_gamelogs,
    write_all_prop_results_snapshot_for_sport,
    _nfl_expected_completed_week,
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


def _nfl_gamelog_stale(gl):
    """Stale-input guard: the NFL grader resolves current-season prop candidates against this
    gamelog, so if the gamelog does not reach the resolved current season it CANNOT grade them.
    Grading anyway would replace the published record with a stale-resolved snapshot. Returns a
    reason string when stale (caller skips the NFL write + fails), '' when safe."""
    try:
        _, expected_season = _nfl_expected_completed_week()
        if not expected_season:
            return ""
        gl_max = (pd.to_numeric(gl.get("Season"), errors="coerce").max()
                  if (gl is not None and not gl.empty and "Season" in gl.columns) else None)
        if gl_max is None or pd.isna(gl_max):
            return f"NFL gamelog empty / no Season column (expected current season {int(expected_season)})"
        if int(gl_max) < int(expected_season):
            return (f"NFL gamelog max season {int(gl_max)} < expected current season "
                    f"{int(expected_season)} -- rebuild NFL_GameLogs.csv (fold in the weekly parquet)")
        return ""
    except Exception:
        return ""  # never block grading on a check error


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh all-prop result snapshots.")
    parser.add_argument(
        "--sport",
        default="all",
        help="Sport to refresh: nba, wnba, mlb, nfl, ncaaf, or all. Default: all.",
    )
    args = parser.parse_args()
    requested_sport = str(args.sport or "all").strip().upper()
    if requested_sport != "ALL" and requested_sport not in SPORT_LOGS:
        print(f"[FAIL] Unsupported sport: {args.sport}")
        return 2

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archive_df = load_candidate_archive()
    total_rows = 0
    total_resolved = 0
    print("=" * 70)
    print("BANKROLL KINGS - ALL AVAILABLE PROP RESULTS")
    print("=" * 70)
    print(f"Checked at: {checked_at}")

    selected_logs = SPORT_LOGS if requested_sport == "ALL" else {requested_sport: SPORT_LOGS[requested_sport]}
    stale_failures = []
    for sport, loader in selected_logs.items():
        gl = loader()
        # Stale-input guard: a stale NFL gamelog must NOT be graded against current props (it would
        # publish a stale-resolved snapshot). Skip the write (preserve the prior record) and fail.
        if sport == "NFL":
            reason = _nfl_gamelog_stale(gl)
            if reason:
                print(f"[FAIL] {sport}: {reason}; skipping NFL grade (prior {sport}_AllPropResults.csv preserved).")
                stale_failures.append(sport)
                continue
        gamelog_map = {sport: gl}
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
            "clean": not stale_failures,
            "pass_count": total_rows,
            "warning_count": 0,
            "failure_count": len(stale_failures),
            "notes": (f"Wrote {total_rows} full-board prop result rows; {total_resolved} resolved. "
                      f"Floor index rows={floor_rows}, resolved={floor_resolved}."
                      + (f" SKIPPED (stale gamelog): {', '.join(stale_failures)}." if stale_failures else "")),
        },
    )
    if stale_failures:
        print(f"[FAIL] Stale-gamelog guard tripped for: {', '.join(stale_failures)} (nonzero exit).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
