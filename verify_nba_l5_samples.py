from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import (
    build_current_team_map,
    build_live_props_board,
    get_player_analysis_logs,
    load_gamelogs,
    load_player_snapshot,
    load_playoff_gamelogs,
)
from services.qc_tracking import append_qc_run_log


def run_verification(limit: int = 3) -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gamelogs = load_gamelogs()
    playoff_logs = load_playoff_gamelogs()
    player_snapshot = load_player_snapshot()
    current_team_map = build_current_team_map(gamelogs, player_snapshot)
    board = build_live_props_board(
        postseason_only=True,
        date_filter="today",
        sample_mode="current",
        sort_by="confidence",
        sort_dir="desc",
    )
    props = list((board or {}).get("props", []))

    player_rows = []
    seen: set[tuple[str, str]] = set()

    def _candidate_pairs():
        board_pairs = []
        for row in props:
            player = str(row.get("player", "")).strip()
            team = str(row.get("team", "")).strip().upper()
            if player and team:
                board_pairs.append((player, team))
        if board_pairs:
            return board_pairs
        if playoff_logs.empty or "Player" not in playoff_logs.columns:
            return []
        fallback_pairs = []
        temp = playoff_logs.copy()
        if "Team" in temp.columns:
            grouped = temp.dropna(subset=["Player", "Team"]).groupby(["Player", "Team"]).size().reset_index(name="Games")
            grouped = grouped[(grouped["Games"] > 0) & (grouped["Games"] < 5)]
            for _, rec in grouped.iterrows():
                fallback_pairs.append((str(rec["Player"]).strip(), str(rec["Team"]).strip().upper()))
        return fallback_pairs

    for player, team in _candidate_pairs():
        if (player, team) in seen:
            continue
        seen.add((player, team))
        player_playoff = playoff_logs[playoff_logs["Player"].astype(str) == player].copy() if not playoff_logs.empty else pd.DataFrame()
        if team and not player_playoff.empty and "Team" in player_playoff.columns:
            subset = player_playoff[player_playoff["Team"].astype(str).str.upper() == team].copy()
            if not subset.empty:
                player_playoff = subset
        playoff_count = int(len(player_playoff))
        if playoff_count == 0 or playoff_count >= 5:
            continue

        active_logs, context = get_player_analysis_logs(
            player,
            gamelogs,
            current_team_map=current_team_map,
            sample_mode="current",
            postseason_logs=playoff_logs,
            postseason_only=True,
        )
        if active_logs.empty:
            continue
        sample_dates = []
        if "Date" in active_logs.columns:
            sample_dates = [
                value.strftime("%Y-%m-%d")
                for value in pd.to_datetime(active_logs["Date"], errors="coerce").dropna().head(5)
            ]
        playoff_dates = set()
        if "Date" in player_playoff.columns:
            playoff_dates = {
                value.strftime("%Y-%m-%d")
                for value in pd.to_datetime(player_playoff["Date"], errors="coerce").dropna()
            }
        non_playoff_dates = [date for date in sample_dates if date not in playoff_dates]

        player_rows.append({
            "player": player,
            "team": team,
            "playoff_games": playoff_count,
            "active_sample_games": int(len(active_logs)),
            "sample_label": context.get("sample_label"),
            "used_current_sample": bool(context.get("used_current_sample")),
            "sample_dates": sample_dates,
            "non_playoff_dates": non_playoff_dates,
        })
        if len(player_rows) >= limit:
            break

    failures = [
        f"{row['player']} {row['team']} includes non-playoff dates {row['non_playoff_dates']}"
        for row in player_rows
        if row["non_playoff_dates"]
    ]
    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": max(len(player_rows) - len(failures), 0),
        "warning_count": 0,
        "failure_count": len(failures),
        "notes": f"Verified {len(player_rows)} sub-5-game playoff samples.",
        "rows": player_rows,
        "failures": failures,
    }
    append_qc_run_log("nba_l5_verify", report)
    return report


def main() -> int:
    report = run_verification()
    print("=" * 60)
    print("NBA L5 SAMPLE VERIFY")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(report["notes"])
    for row in report.get("rows", []):
        print(
            f"{row['player']} ({row['team']}): playoff_games={row['playoff_games']} "
            f"active_sample_games={row['active_sample_games']} sample={row['sample_label']} "
            f"dates={row['sample_dates']}"
        )
    for failure in report.get("failures", []):
        print(f"[FAIL] {failure}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
