from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import (
    build_market_edge_board,
    build_mlb_board_status,
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

    board = build_live_props_board(
        filter_type=None,
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
        "nba_props_postseason_today_current",
        board,
        meta={"sport": "NBA", "view": "props", "postseason_only": True},
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
    top_props = build_wnba_prop_board(
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

    method_rows = build_wnba_method_board(
        "market_edge",
        props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter="today",
        stat_filter="",
        direction_filter="all",
        search_query="",
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
    top_props = build_mlb_prop_board(
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

    method_rows = build_mlb_method_board(
        "market_edge",
        props_df,
        odds_df,
        schedule_df,
        gamelogs=gamelogs_df,
        date_filter="today",
        stat_filter="",
        direction_filter="all",
        search_query="",
        featured_top_n=12,
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
        "method_key": "market_edge",
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
    _write_snapshot("mlb_market_edge_today", method_payload, meta={"sport": "MLB", "view": "market_edge"})


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - RUNTIME SNAPSHOT REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    build_nba_snapshots()
    build_nba_props_snapshot()
    build_nfl_snapshot()
    build_wnba_snapshots()
    build_mlb_snapshots()
    print()
    print("Runtime snapshots refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
