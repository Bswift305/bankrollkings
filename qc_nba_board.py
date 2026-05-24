from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app import (
    apply_current_team_context,
    build_live_props_board,
    load_canonical_live_props,
    load_current_team_overrides,
    load_gamelogs,
    load_playoff_gamelogs,
    load_playoff_results,
    load_player_snapshot,
    load_props,
    load_schedule,
)
from services.qc_tracking import append_qc_run_log


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _safe_ts(series) -> pd.Timestamp | None:
    try:
        parsed = pd.to_datetime(series, errors="coerce")
        if parsed.empty:
            return None
        value = parsed.max()
        if pd.isna(value):
            return None
        return value
    except Exception:
        return None


def _load_live_props():
    board = build_live_props_board(
        postseason_only=True,
        date_filter="today",
        sample_mode="current",
        sort_by="confidence",
        sort_dir="desc",
    )
    if isinstance(board, dict):
        return list(board.get("props", []))
    return list(board or [])


def run_qc() -> dict:
    today = pd.Timestamp(datetime.now().date())
    issues: list[dict] = []

    playoff_logs = load_playoff_gamelogs()
    playoff_results = load_playoff_results()
    gamelogs = load_gamelogs()
    schedule = load_schedule()
    props_df = load_props()
    live_props = _load_live_props()

    playoff_log_max = _safe_ts(playoff_logs["Date"]) if not playoff_logs.empty and "Date" in playoff_logs.columns else None
    playoff_results_max = _safe_ts(playoff_results["Date"]) if not playoff_results.empty and "Date" in playoff_results.columns else None
    schedule_max = _safe_ts(schedule["Date"]) if not schedule.empty and "Date" in schedule.columns else None
    active_teams = {
        str(p.get("team", "")).strip()
        for p in (live_props or [])
        if str(p.get("team", "")).strip()
    }
    expected_playoff_log_max = playoff_results_max
    if active_teams and not playoff_results.empty and {"Away", "Home", "Date"}.issubset(playoff_results.columns):
        active_results = playoff_results[
            playoff_results["Away"].astype(str).isin(active_teams)
            | playoff_results["Home"].astype(str).isin(active_teams)
        ].copy()
        active_results_max = _safe_ts(active_results["Date"]) if not active_results.empty else None
        if active_results_max is not None:
            expected_playoff_log_max = active_results_max

    if playoff_log_max is None:
        issues.append({
            "severity": "high",
            "category": "data_freshness",
            "message": "Playoff player logs are missing.",
        })
    elif expected_playoff_log_max is not None and playoff_log_max < expected_playoff_log_max:
        issues.append({
            "severity": "high",
            "category": "data_freshness",
            "message": (
                f"Playoff player logs only run through {playoff_log_max.strftime('%Y-%m-%d')} "
                f"while the active-slate teams have results through {expected_playoff_log_max.strftime('%Y-%m-%d')}."
            ),
        })
    elif playoff_log_max < (today - timedelta(days=2)):
        issues.append({
            "severity": "high",
            "category": "data_freshness",
            "message": f"Playoff player logs are stale through {playoff_log_max.strftime('%Y-%m-%d')}.",
        })

    if playoff_results_max is None:
        issues.append({
            "severity": "high",
            "category": "data_freshness",
            "message": "Playoff results are missing.",
        })
    elif playoff_results_max < (today - timedelta(days=2)):
        issues.append({
            "severity": "medium",
            "category": "data_freshness",
            "message": f"Playoff results are stale through {playoff_results_max.strftime('%Y-%m-%d')}.",
        })

    if schedule_max is None or schedule_max < today:
        issues.append({
            "severity": "high",
            "category": "schedule",
            "message": "Upcoming NBA schedule does not include today or later.",
        })

    resolved_props = props_df.copy()
    if not props_df.empty:
        resolved_props = apply_current_team_context(
            props_df,
            gamelogs,
            load_player_snapshot(),
            load_current_team_overrides(),
        )
    canonical_props = load_canonical_live_props(
        gamelogs,
        load_player_snapshot(),
        load_current_team_overrides(),
    )
    if not resolved_props.empty and "Team" in resolved_props.columns:
        missing_team_mask = resolved_props["Team"].isna() | resolved_props["Team"].astype(str).str.strip().eq("")
        missing_team_count = int(missing_team_mask.sum())
        if missing_team_count:
            issues.append({
                "severity": "medium",
                "category": "props_data",
                "message": f"{missing_team_count} resolved prop rows are still missing team mapping.",
            })

    if not canonical_props.empty:
        dup_mask = canonical_props.duplicated(subset=["Player", "Stat", "Game"], keep=False)
        dup_rows = canonical_props.loc[dup_mask, ["Player", "Stat", "Game"]].drop_duplicates()
        for _, dup in dup_rows.iterrows():
            issues.append({
                "severity": "high",
                "category": "duplicate_prop_row",
                "message": (
                    f"{dup.get('Player')} {dup.get('Stat')} still has duplicate canonical rows for "
                    f"{dup.get('Game')}."
                ),
            })

    for row in live_props:
        confidence = float(row.get("confidence", 0) or 0)
        over_streak = int(row.get("over_streak", 0) or 0)
        under_streak = int(row.get("under_streak", 0) or 0)
        current_run_side = str(row.get("current_run_side", "") or "").strip().lower()
        current_streak = int(row.get("current_streak", 0) or 0)
        direction = str(row.get("direction", "") or "").upper()
        public_trend_note = str(row.get("public_trend_note", "") or "").strip()
        guardrail_tags = {str(tag).strip().upper() for tag in (row.get("guardrail_tags") or []) if tag}
        situations = {str(tag).strip().upper() for tag in (row.get("situations") or []) if tag}
        live_line_games = int(row.get("live_line_games", 0) or 0)
        play_verdict = str(row.get("play_verdict", "PLAY") or "PLAY").strip().upper()

        expected_run_side = "over" if over_streak > 0 else "under" if under_streak > 0 else "flat"
        expected_run_len = max(over_streak, under_streak)

        if current_run_side != expected_run_side or current_streak != expected_run_len:
            issues.append({
                "severity": "high",
                "category": "streak_sync",
                "message": (
                    f"{row.get('player')} {row.get('stat')} has row streak {current_run_side}:{current_streak} "
                    f"but over/under streaks imply {expected_run_side}:{expected_run_len}."
                ),
            })

        if current_run_side in {"over", "under"} and current_streak >= 3 and not public_trend_note:
            issues.append({
                "severity": "medium",
                "category": "trend_note_missing",
                "message": f"{row.get('player')} {row.get('stat')} is on a {current_run_side} run of {current_streak} with no public trend note.",
            })

        if current_run_side == "over" and current_streak >= 3 and f"{current_streak}" not in public_trend_note:
            issues.append({
                "severity": "medium",
                "category": "trend_note_mismatch",
                "message": f"{row.get('player')} {row.get('stat')} over streak is {current_streak}, but the trend note does not match it cleanly.",
            })

        if current_run_side == "under" and current_streak >= 3 and f"{current_streak}" not in public_trend_note:
            issues.append({
                "severity": "medium",
                "category": "trend_note_mismatch",
                "message": f"{row.get('player')} {row.get('stat')} under streak is {current_streak}, but the trend note does not match it cleanly.",
            })

        run_conflict = (
            (direction == "OVER" and current_run_side == "under") or
            (direction == "UNDER" and current_run_side == "over")
        )
        if confidence >= 75 and run_conflict and current_streak >= 2:
            issues.append({
                "severity": "high",
                "category": "top_play_conflict",
                "message": (
                    f"{row.get('player')} {row.get('stat')} {direction} is still {confidence:.1f}% "
                    f"despite a {current_run_side} streak of {current_streak}."
                ),
            })

        if confidence >= 80 and "RUN CONFLICT" in guardrail_tags:
            issues.append({
                "severity": "high",
                "category": "guardrail_failure",
                "message": f"{row.get('player')} {row.get('stat')} remained elite after a run conflict tag.",
            })

        if confidence >= 80 and {"L5 FADE", "STREAK-"} & situations and direction == "OVER":
            issues.append({
                "severity": "medium",
                "category": "trend_tension",
                "message": f"{row.get('player')} {row.get('stat')} OVER is elite while carrying fade tags.",
            })

        if confidence >= 80 and live_line_games < 8:
            issues.append({
                "severity": "medium",
                "category": "sample_depth",
                "message": f"{row.get('player')} {row.get('stat')} is elite on only {live_line_games} current-sample games.",
            })

        if (
            play_verdict == "PLAY"
            and current_run_side in {"over", "under"}
            and current_streak >= 4
            and run_conflict
            and {"ROLE DOWN", "SHOT VOL-", "MIN-", "L5 FADE", "COLD"} & situations
        ):
            issues.append({
                "severity": "high",
                "category": "verdict_leak",
                "message": f"{row.get('player')} {row.get('stat')} is still marked PLAY despite a hard recent-series conflict.",
            })

    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "playoff_log_max": playoff_log_max.strftime("%Y-%m-%d") if playoff_log_max is not None else "",
        "playoff_results_max": playoff_results_max.strftime("%Y-%m-%d") if playoff_results_max is not None else "",
        "schedule_max": schedule_max.strftime("%Y-%m-%d") if schedule_max is not None else "",
        "live_prop_rows": len(live_props),
        "issue_count": len(issues),
        "issues": issues,
    }
    append_qc_run_log("nba_board", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NBA QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Playoff logs through: {report['playoff_log_max'] or 'missing'}")
    print(f"Playoff results through: {report['playoff_results_max'] or 'missing'}")
    print(f"Schedule through: {report['schedule_max'] or 'missing'}")
    print(f"Live prop rows checked: {report['live_prop_rows']}")
    print(f"Issues found: {report['issue_count']}")
    print()
    if not report["issues"]:
        print("No blocking NBA QC issues detected.")
        return 0

    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
