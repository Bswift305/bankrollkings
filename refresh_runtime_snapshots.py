from __future__ import annotations

import argparse
import inspect
from datetime import datetime

import pandas as pd

from app import (
    app,
    build_market_edge_board,
    build_cross_sport_dashboard_snapshots,
    build_mlb_board_status,
    build_mlb_launch_lab,
    build_mlb_method_board,
    build_mlb_prop_board,
    build_nba_command_center_context,
    build_nfl_dashboard_runtime_bundle,
    build_nfl_filter_state,
    build_ops_status_strip,
    build_wnba_board_status,
    build_wnba_matchup_cards,
    build_wnba_method_board,
    build_wnba_prop_board,
    get_mlb_market_groups,
    get_nfl_market_groups,
    get_sport_model_profile,
    get_upcoming_games,
    get_wnba_market_groups,
    load_mlb_game_market_odds,
    load_mlb_gamelogs,
    load_mlb_live_props_feed,
    load_mlb_schedule,
    load_nfl_floor_board,
    load_wnba_game_market_odds,
    load_wnba_gamelogs,
    load_wnba_live_props_feed,
    load_wnba_schedule,
    write_runtime_snapshot,
)


def _write_snapshot(snapshot_key: str, payload, meta: dict | None = None) -> None:
    path = write_runtime_snapshot(snapshot_key, payload, meta=meta or {})
    print(f"[SNAPSHOT] {snapshot_key} -> {path.name}")


def call_board_builder(builder_fn, *args, **kwargs):
    signature = inspect.signature(builder_fn)
    filtered_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return builder_fn(*args, **filtered_kwargs)


def build_nba_snapshots() -> None:
    for postseason_only, key in ((True, "nba_command_center_postseason"), (False, "nba_command_center_regular")):
        payload = build_nba_command_center_context(postseason_only)
        _write_snapshot(key, payload, meta={"sport": "NBA", "postseason_only": postseason_only})

    props_board = build_market_edge_board(
        postseason_only=True,
        date_filter="today",
        direction_filter="all",
        team_query="",
        player_query="",
        stat_query="",
        sample_mode="current",
        model_debug=False,
        sort_by="confidence",
        sort_dir="desc",
    )
    _write_snapshot(
        "nba_market_edge_postseason_today_current",
        props_board,
        meta={"sport": "NBA", "view": "market_edge", "postseason_only": True},
    )


def build_nba_props_snapshot() -> None:
    from app import build_live_props_board

    board_configs = [
        (None, "nba_props_postseason_today_current", "props"),
        ("floor", "nba_floor_props_postseason_today_current", "floor_props"),
    ]
    for filter_type, snapshot_key, view_name in board_configs:
        board = build_live_props_board(
            filter_type=filter_type,
            postseason_only=True,
            date_filter="today",
            direction_filter="all",
            team_query="",
            player_query="",
            stat_query="",
            sample_mode="current",
            model_debug=False,
            sort_by="confidence",
            sort_dir="desc",
        )
        _write_snapshot(
            snapshot_key,
            board,
            meta={"sport": "NBA", "view": view_name, "postseason_only": True},
        )

def build_nfl_snapshot() -> None:
    board = load_nfl_floor_board()
    runtime = build_nfl_dashboard_runtime_bundle()
    payload = {
        "sport_profile": get_sport_model_profile("nfl"),
        "market_groups": get_nfl_market_groups(),
        "football_methods": [],
        "board": board,
        "filter_state": build_nfl_filter_state({}, board),
        "live_status": {
            **dict(runtime["live_status"]),
            "workbook_available": bool(board.get("available")),
            "workbook_games": len(board.get("games", [])),
        },
        "refresh_meta": runtime["live_refresh_meta"],
        "history_status": runtime["history_status"],
    }
    _write_snapshot("nfl_dashboard", payload, meta={"sport": "NFL"})


def build_wnba_snapshots() -> None:
    props_df, refresh_meta = load_wnba_live_props_feed(require_fresh=True)
    odds_df = load_wnba_game_market_odds()
    schedule_df = load_wnba_schedule()
    gamelogs_df = load_wnba_gamelogs()
    upcoming = get_upcoming_games(schedule_df, days=7)
    top_props = call_board_builder(
        build_wnba_prop_board,
        props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter="today",
        stat_filter="",
        direction_filter="all",
        search_query="",
        fast_mode=True,
    )
    dashboard_payload = {
        "sport_profile": get_sport_model_profile("wnba"),
        "market_groups": get_wnba_market_groups(),
        "refresh_meta": refresh_meta,
        "board_status": build_wnba_board_status(schedule_df, odds_df, props_df, upcoming),
        "upcoming": upcoming,
        "top_props": top_props[:80],
        "matchup_cards": build_wnba_matchup_cards(odds_df, schedule_df),
        "date_filter": "today",
        "stat_filter": "",
        "direction_filter": "all",
        "search_query": "",
    }
    dashboard_payload["board_status"]["gamelog_rows"] = int(len(gamelogs_df))
    dashboard_payload["board_status"]["trend_ready"] = not gamelogs_df.empty
    _write_snapshot("wnba_dashboard_today", dashboard_payload, meta={"sport": "WNBA"})

    method_rows = call_board_builder(
        build_wnba_method_board,
        "market_edge",
        props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter="today",
        stat_filter="",
        direction_filter="all",
        search_query="",
        fast_mode=True,
    )
    method_payload = {
        "sport_profile": get_sport_model_profile("wnba"),
        "refresh_meta": refresh_meta,
        "matchup_cards": build_wnba_matchup_cards(odds_df, schedule_df),
        "rows": method_rows[:100],
        "date_filter": "today",
        "stat_filter": "",
        "direction_filter": "all",
        "search_query": "",
        "method_key": "market_edge",
    }
    _write_snapshot("wnba_market_edge_today", method_payload, meta={"sport": "WNBA", "view": "market_edge"})


def build_mlb_snapshots() -> None:
    props_df, refresh_meta = load_mlb_live_props_feed(require_fresh=True)
    odds_df = load_mlb_game_market_odds()
    schedule_df = load_mlb_schedule()
    gamelogs_df = load_mlb_gamelogs()
    upcoming = get_upcoming_games(schedule_df, days=7)
    top_props = call_board_builder(
        build_mlb_prop_board,
        props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter="today",
        stat_filter="",
        direction_filter="all",
        search_query="",
    )
    dashboard_payload = {
        "sport_profile": get_sport_model_profile("mlb"),
        "market_groups": get_mlb_market_groups(),
        "refresh_meta": refresh_meta,
        "board_status": build_mlb_board_status(schedule_df, odds_df, props_df, gamelogs_df, upcoming),
        "mlb_launch_lab": build_mlb_launch_lab(),
        "upcoming": upcoming,
        "top_props": top_props[:80],
        "date_filter": "today",
        "stat_filter": "",
        "direction_filter": "all",
        "search_query": "",
        "summary_cards": [
            {"label": "Board Rows", "value": len(top_props), "note": "props matching the current filter set"},
            {
                "label": "Clean Plays",
                "value": sum(1 for row in top_props if str(row.get("play_verdict") or "PLAY").upper() == "PLAY"),
                "note": "rows that are not currently downgraded by simple guardrails",
            },
            {
                "label": "Multi-Book",
                "value": sum(1 for row in top_props if int(row.get("book_count") or 0) >= 2),
                "note": "rows with at least two books confirming the market",
            },
        ],
        "stat_options": sorted({str(row.get("stat") or "").strip() for row in top_props if str(row.get("stat") or "").strip()}),
    }
    _write_snapshot("mlb_dashboard_today", dashboard_payload, meta={"sport": "MLB"})

    for method_key, snapshot_key in (("props", "mlb_props_today"), ("market_edge", "mlb_market_edge_today")):
        method_rows = call_board_builder(
            build_mlb_method_board,
            method_key,
            props_df,
            odds_df,
            schedule_df,
            gamelogs=gamelogs_df,
            date_filter="today",
            stat_filter="",
            direction_filter="all",
            search_query="",
            featured_top_n=12,
            fast_mode=True,
        )
        method_payload = {
            "sport_profile": get_sport_model_profile("mlb"),
            "refresh_meta": refresh_meta,
            "board_status": build_mlb_board_status(schedule_df, odds_df, props_df, gamelogs_df, upcoming),
            "rows": method_rows[:80],
            "date_filter": "today",
            "stat_filter": "",
            "direction_filter": "all",
            "search_query": "",
            "method_key": method_key,
            "summary_cards": [
                {"label": "Rows", "value": len(method_rows), "note": "props matching this method and filter set"},
                {
                    "label": "Play Rows",
                    "value": sum(1 for row in method_rows if str(row.get("play_verdict") or "PLAY").upper() == "PLAY"),
                    "note": "rows that still read as clean plays after lightweight guardrails",
                },
                {
                    "label": "Trend Ready",
                    "value": sum(1 for row in method_rows if str(row.get("trend_note") or "").strip()),
                    "note": "rows with real recent-form support from MLB game logs",
                },
            ],
            "stat_options": sorted({str(row.get("stat") or "").strip() for row in method_rows if str(row.get("stat") or "").strip()}),
        }
        _write_snapshot(snapshot_key, method_payload, meta={"sport": "MLB", "view": method_key, "fast_mode": True})


def build_public_home_snapshots() -> None:
    for postseason_only in (True, False):
        build_cross_sport_dashboard_snapshots(postseason_only=postseason_only)
        print(f"[CACHE] cross_sport_dashboard_snapshots::{int(postseason_only)}")


def prewarm_expensive_pages() -> None:
    routes = [
        "/dashboard",
        "/sports/wnba/market-edge",
        "/sports/mlb/market-edge",
        "/parlay",
        "/candidate-review",
        "/injuries",
    ]
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "43e532a80a5241628a2730cbecc6781a"
        sess["user_email"] = "codex_sharp_test@bankrollkings.local"
        sess["display_name"] = "Test Sharp"
    for route in routes:
        response = client.get(route)
        print(f"[PREWARM] {route} -> {response.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh runtime snapshots for one or more app areas.")
    parser.add_argument(
        "--sports",
        default="nba,nfl,wnba,mlb,public",
        help="Comma-separated snapshot groups: nba,nfl,wnba,mlb,public. Default: all.",
    )
    parser.add_argument("--skip-prewarm", action="store_true", help="Skip route prewarm requests.")
    args = parser.parse_args()
    groups = {item.strip().lower() for item in args.sports.split(",") if item.strip()}
    valid_groups = {"nba", "nfl", "wnba", "mlb", "public"}
    unknown_groups = groups - valid_groups
    if unknown_groups:
        print(f"[FAIL] Unsupported snapshot group(s): {', '.join(sorted(unknown_groups))}")
        return 2
    if not groups:
        groups = valid_groups

    print("=" * 60)
    print("BANKROLL KINGS - RUNTIME SNAPSHOT REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Groups: {', '.join(sorted(groups)).upper()}")
    print()
    if "nba" in groups:
        build_nba_snapshots()
        build_nba_props_snapshot()
    if "nfl" in groups:
        build_nfl_snapshot()
    if "wnba" in groups:
        build_wnba_snapshots()
    if "mlb" in groups:
        build_mlb_snapshots()
    if "public" in groups:
        build_public_home_snapshots()
    if not args.skip_prewarm:
        prewarm_expensive_pages()
    print()
    print("Runtime snapshots refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
