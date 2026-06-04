from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from app import (
    build_mlb_method_board,
    build_mlb_prop_board,
    load_mlb_gamelogs,
    load_mlb_game_market_odds,
    load_mlb_live_props_feed,
    load_mlb_schedule,
)
from services.mlb_contradiction_qc import audit_props, prop_key
from services.qc_tracking import (
    append_qc_run_log,
    build_warning_history_map,
    update_warning_history,
)


def _compact_game_label(value) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _filter_props_to_today(props_df, schedule_df):
    if props_df is None or props_df.empty or schedule_df is None or schedule_df.empty:
        return props_df
    if "Game" not in props_df.columns or "Date" not in schedule_df.columns:
        return props_df
    working_schedule = schedule_df.copy()
    working_schedule["Date"] = pd.to_datetime(working_schedule["Date"], errors="coerce")
    today = pd.Timestamp.now().normalize()
    today_games = working_schedule[working_schedule["Date"].dt.normalize() == today]
    if today_games.empty:
        return props_df
    labels: set[str] = set()
    for _, game in today_games.iterrows():
        away_values = [game.get("Away"), game.get("AwayFull")]
        home_values = [game.get("Home"), game.get("HomeFull")]
        for away in away_values:
            for home in home_values:
                if away and home:
                    labels.add(_compact_game_label(f"{away}@{home}"))
                    labels.add(_compact_game_label(f"{away} @ {home}"))
                    labels.add(_compact_game_label(f"{away} vs {home}"))
                    labels.add(_compact_game_label(f"{away} vs. {home}"))
    if not labels:
        return props_df
    mask = props_df["Game"].apply(_compact_game_label).isin(labels)
    filtered = props_df[mask].copy()
    return filtered if not filtered.empty else props_df


def build_runtime(fast: bool = False) -> dict:
    props_df, refresh_meta = load_mlb_live_props_feed(require_fresh=False)
    odds_df = load_mlb_game_market_odds()
    schedule_df = load_mlb_schedule()
    gamelogs_df = load_mlb_gamelogs()
    date_filter = "today" if fast else "all"
    scoring_props_df = _filter_props_to_today(props_df, schedule_df) if fast else props_df

    scored_props = build_mlb_prop_board(
        scoring_props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter=date_filter,
        cache_namespace="qc_fast" if fast else "default",
    )
    featured_rows = []
    if not fast:
        for method_key in ("market_edge", "floor_plays", "trends"):
            featured_rows.extend(
                build_mlb_method_board(
                    method_key,
                    props_df,
                    odds_df,
                    schedule_df,
                    gamelogs=gamelogs_df,
                    date_filter=date_filter,
                    featured_top_n=10,
                )[:10]
            )
    featured_keys = {prop_key(row) for row in featured_rows}
    for row in scored_props:
        row["_is_featured"] = prop_key(row) in featured_keys

    return {
        "scored_props": scored_props,
        "featured_props": featured_rows,
        "featured_keys": featured_keys,
        "warning_history_map": build_warning_history_map("mlb_contradictions"),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "refresh_meta": refresh_meta,
        "fast": fast,
    }


def run_qc(persist=True, fast: bool = False) -> dict:
    runtime = build_runtime(fast=fast)
    active_props = []
    for row in runtime["scored_props"]:
        verdict = str(row.get("play_verdict", "PLAY") or "PLAY").strip().upper()
        already_demoted = bool(row.get("contradiction_fail_rules")) and verdict == "PASS"
        if already_demoted and not bool(row.get("_is_featured")):
            continue
        active_props.append(row)

    audit = audit_props(active_props, runtime=runtime)
    report = {
        "checked_at": runtime["checked_at"],
        "scored_prop_count": len(active_props),
        "raw_scored_prop_count": len(runtime["scored_props"]),
        "featured_prop_count": len(runtime["featured_props"]),
        "pass_count": audit["pass_count"],
        "warning_count": audit["warning_count"],
        "failure_count": audit["failure_count"],
        "warnings": audit["warnings"],
        "failures": audit["failures"],
        "clean": audit["clean"],
        "notes": (
            f"Props status: {runtime['refresh_meta'].get('status')} | "
            f"Books: {runtime['refresh_meta'].get('book_count', 0)} | "
            f"Rows: {runtime['refresh_meta'].get('row_count', 0)} | "
            f"Active QC rows: {len(active_props)} / Raw board rows: {len(runtime['scored_props'])} | "
            f"Mode: {'fast daily' if runtime.get('fast') else 'full'}"
        ),
    }
    if persist:
        update_warning_history("mlb_contradictions", report["warnings"], report["failures"], report["checked_at"])
        append_qc_run_log("mlb_contradictions", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bankroll Kings MLB contradiction QC")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as blocking.")
    parser.add_argument("--report-only", action="store_true", help="Always exit 0 after reporting.")
    parser.add_argument("--player", type=str, default="", help="Only print issues for one player.")
    parser.add_argument("--fast", action="store_true", help="Check the current live board without rebuilding all featured method boards.")
    args = parser.parse_args()

    report = run_qc(persist=True, fast=args.fast)
    player_filter = args.player.strip().lower()

    print("=" * 60)
    print("MLB CONTRADICTION QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Scored props: {report['scored_prop_count']}")
    print(f"Featured props: {report['featured_prop_count']}")
    print(f"Passes: {report['pass_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
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
