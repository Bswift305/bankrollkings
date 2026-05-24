from __future__ import annotations

from datetime import datetime

from app import SERIES_CONFIG, load_playoff_results, load_schedule, normalize_team_for_filter
from services.qc_tracking import append_qc_run_log


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    configured_matchups = {frozenset(config["teams"]) for config in SERIES_CONFIG.values()}
    failures: list[str] = []
    warnings: list[str] = []

    playoff_results = load_playoff_results()
    if playoff_results is not None and not playoff_results.empty and {"Away", "Home", "SeriesId"}.issubset(playoff_results.columns):
        for _, row in playoff_results.iterrows():
            teams = frozenset({
                normalize_team_for_filter(row.get("Away")),
                normalize_team_for_filter(row.get("Home")),
            })
            series_id = str(row.get("SeriesId", "")).strip()
            if teams not in configured_matchups:
                failures.append(f"Missing SERIES_CONFIG matchup for playoff results pair {sorted(teams)}.")
            elif series_id and series_id not in SERIES_CONFIG:
                failures.append(f"Missing SERIES_CONFIG id '{series_id}' found in playoff results.")

    schedule = load_schedule()
    if schedule is not None and not schedule.empty and {"Away", "Home"}.issubset(schedule.columns):
        upcoming_pairs = {
            frozenset({
                normalize_team_for_filter(row.get("Away")),
                normalize_team_for_filter(row.get("Home")),
            })
            for _, row in schedule.iterrows()
            if str(row.get("Away", "")).strip() and str(row.get("Home", "")).strip()
        }
        for teams in sorted(upcoming_pairs, key=lambda item: sorted(item)):
            if teams not in configured_matchups:
                warnings.append(f"Upcoming matchup {sorted(teams)} is not represented in SERIES_CONFIG.")

    report = {
        "checked_at": checked_at,
        "pass_count": max(len(configured_matchups) - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "clean": len(failures) == 0,
        "notes": f"Configured series: {len(configured_matchups)} | playoff result rows: {0 if playoff_results is None else len(playoff_results)}",
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("nba_series_mappings", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("NBA SERIES MAPPING QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    print()
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
