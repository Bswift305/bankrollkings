from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import (
    build_current_team_map,
    build_head_to_head_summary,
    build_live_props_board,
    get_player_analysis_logs,
    load_live_props_feed,
    load_gamelogs,
    load_playoff_gamelogs,
    load_schedule,
    get_upcoming_games,
    normalize_team_for_filter,
)
from services.qc_tracking import append_qc_run_log


def _normalize_date_set(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "Date" not in df.columns:
        return set()
    values = pd.to_datetime(df["Date"], errors="coerce").dropna()
    return {value.strftime("%Y-%m-%d") for value in values}


def run_source_audit() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gamelogs = load_gamelogs()
    playoff_logs = load_playoff_gamelogs()
    _, props_refresh_meta = load_live_props_feed(require_fresh=False)
    board = build_live_props_board(
        postseason_only=True,
        date_filter="today",
        sample_mode="current",
        sort_by="confidence",
        sort_dir="desc",
    )
    scored_props = list((board or {}).get("props", []))
    current_team_map = build_current_team_map(gamelogs)

    failures: list[str] = []
    warnings: list[str] = []

    if not props_refresh_meta.get("has_live_props"):
        failures.append("Live props feed is unavailable during source audit.")
    elif props_refresh_meta.get("is_stale"):
        failures.append(
            f"Live props feed is stale at {props_refresh_meta.get('age_hours')}h old during source audit."
        )

    matchup_groups: dict[tuple[str, str], list[dict]] = {}
    for row in scored_props:
        team = str(row.get("team", "")).strip().upper()
        opponent = str(row.get("opponent", "")).strip().upper()
        if not team or not opponent:
            continue
        key = tuple(sorted([team, opponent]))
        matchup_groups.setdefault(key, []).append(row)

    matchup_audits = []
    for key, rows in matchup_groups.items():
        team_a, team_b = key
        summary = build_head_to_head_summary(gamelogs, team_a, team_b, allow_regular_fallback=False)
        completed_games = int(len((summary or {}).get("games", []) or []))
        derived_next_game = completed_games + 1 if completed_games > 0 else 0
        observed_numbers = sorted({
            int(row.get("series_game_number", 0) or 0)
            for row in rows
            if int(row.get("series_game_number", 0) or 0) > 0
        })
        if len(observed_numbers) > 1:
            failures.append(
                f"{team_a} vs {team_b}: inconsistent series_game_number values {observed_numbers} on the same board."
            )
        elif observed_numbers and derived_next_game and observed_numbers[0] != derived_next_game:
            failures.append(
                f"{team_a} vs {team_b}: board shows game {observed_numbers[0]} but playoff results derive game {derived_next_game}."
            )
        elif not observed_numbers:
            warnings.append(f"{team_a} vs {team_b}: no series_game_number present on current props.")
        matchup_audits.append({
            "matchup": f"{team_a} vs {team_b}",
            "completed_games": completed_games,
            "derived_next_game": derived_next_game,
            "observed_series_game_numbers": observed_numbers,
        })

    schedule = load_schedule()
    if schedule is not None and not schedule.empty:
        upcoming = get_upcoming_games(schedule, days=7)
        for game in upcoming.get("today", []):
            away = normalize_team_for_filter(game.get("Away"))
            home = normalize_team_for_filter(game.get("Home"))
            playoff_only_summary = build_head_to_head_summary(
                gamelogs,
                away,
                home,
                allow_regular_fallback=False,
            )
            if not playoff_only_summary.get("games") and playoff_only_summary.get("status") not in {
                f"{away} and {home} open the series at 0-0.",
                f"{home} and {away} open the series at 0-0.",
            }:
                failures.append(
                    f"{away} vs {home}: postseason-only summary is not cleanly resetting to 0-0 when playoff rows are missing."
                )

    player_failures = 0
    player_audits = []
    seen_players: set[tuple[str, str]] = set()
    for row in scored_props:
        player = str(row.get("player", "")).strip()
        team = str(row.get("team", "")).strip().upper()
        if not player or (player, team) in seen_players:
            continue
        seen_players.add((player, team))

        active_logs, context = get_player_analysis_logs(
            player,
            gamelogs,
            current_team_map=current_team_map,
            sample_mode="current",
            postseason_logs=playoff_logs,
            postseason_only=True,
        )
        player_playoff_logs = playoff_logs[playoff_logs["Player"].astype(str) == player].copy() if not playoff_logs.empty else pd.DataFrame()
        if team and not player_playoff_logs.empty and "Team" in player_playoff_logs.columns:
            team_subset = player_playoff_logs[player_playoff_logs["Team"].astype(str).str.upper() == team].copy()
            if not team_subset.empty:
                player_playoff_logs = team_subset
        if player_playoff_logs.empty:
            continue

        active_dates = _normalize_date_set(active_logs)
        playoff_dates = _normalize_date_set(player_playoff_logs)
        if active_dates and not active_dates.issubset(playoff_dates):
            failures.append(
                f"{player} {team}: postseason L5/current sample contains non-playoff dates {sorted(active_dates - playoff_dates)}."
            )
            player_failures += 1
        if len(player_playoff_logs) < 5 and len(active_logs) > len(player_playoff_logs):
            failures.append(
                f"{player} {team}: active playoff sample length {len(active_logs)} exceeds playoff log count {len(player_playoff_logs)}."
            )
            player_failures += 1

        player_audits.append({
            "player": player,
            "team": team,
            "playoff_log_count": int(len(player_playoff_logs)),
            "active_sample_count": int(len(active_logs)),
            "used_current_sample": bool(context.get("used_current_sample")),
            "sample_label": context.get("sample_label"),
        })

    report = {
        "checked_at": checked_at,
        "route_count": 0,
        "pass_count": max(len(scored_props) - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "scored_prop_count": len(scored_props),
        "notes": (
            f"Props status: {props_refresh_meta.get('status')} | "
            f"Audited {len(matchup_audits)} playoff matchups, "
            f"{len(player_audits)} player playoff samples, "
            f"{player_failures} player sample failures."
        ),
        "clean": len(failures) == 0,
        "matchup_audits": matchup_audits,
        "player_audits": player_audits,
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("nba_sources", report)
    return report


def main() -> int:
    report = run_source_audit()
    print("=" * 60)
    print("NBA SOURCE AUDIT")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Scored props: {report['scored_prop_count']}")
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
