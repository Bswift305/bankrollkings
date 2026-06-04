from __future__ import annotations

from datetime import datetime

from app import (
    build_mlb_board_status,
    build_mlb_launch_lab,
    build_mlb_method_board,
    build_mlb_prop_board,
    get_mlb_market_groups,
    get_sport_model_profile,
    get_upcoming_games,
    load_mlb_game_market_odds,
    load_mlb_gamelogs,
    load_mlb_live_props_feed,
    load_mlb_schedule,
    write_runtime_snapshot,
)


def _write_snapshot(snapshot_key: str, payload, meta: dict | None = None) -> None:
    path = write_runtime_snapshot(snapshot_key, payload, meta=meta or {})
    print(f"[SNAPSHOT] {snapshot_key} -> {path.name}", flush=True)


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
        cache_namespace="qc_fast",
        fast_mode=True,
    )
    board_status = build_mlb_board_status(schedule_df, odds_df, props_df, gamelogs_df, upcoming)
    dashboard_payload = {
        "sport_profile": get_sport_model_profile("mlb"),
        "market_groups": get_mlb_market_groups(),
        "refresh_meta": refresh_meta,
        "board_status": board_status,
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
        method_rows = build_mlb_method_board(
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
            "board_status": board_status,
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


def main() -> int:
    print("=" * 60, flush=True)
    print("BANKROLL KINGS - MLB RUNTIME SNAPSHOTS", flush=True)
    print("=" * 60, flush=True)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(flush=True)
    build_mlb_snapshots()
    print()
    print("MLB runtime snapshots refreshed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
