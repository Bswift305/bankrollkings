"""QC for Lookup Phase 2 UI + successful-render watermark behavior."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import app as web
from services.lookup_changes import LookupChangeStore, ObservedChangeInput


ENTITY = "nfl:espn:123"


def _item(source_id: str, captured: str, line: float):
    return ObservedChangeInput(
        entity_type="player", entity_id=ENTITY,
        field="market_quote:nfl:player_rush_yds:draftkings:a@b",
        current_value={"line": line, "over_price": -110, "under_price": -110,
                       "book": "DraftKings", "game": "A@B", "stat": "Rush Yds"},
        dataset="odds_api_player_props", source="The Odds API",
        source_observation_id=source_id, first_captured_at=captured,
        source_updated_raw="2026-10-18 05:00", market_relative_timing="unknown",
    )


def _player_context():
    return {
        "query": "Runner One", "status": "ok",
        "player": {"player": "Runner One", "team": "ARI", "pos": "RB", "player_id": "123"},
        "candidates": [], "matchup": "A @ B", "feed_ts": "2026-10-18 05:00",
        "markets": [], "surfaces": {},
    }


def _render():
    old_testing = web.app.testing
    web.app.testing = True
    try:
        with web.app.test_client() as client:
            response = client.get("/tools/player-check?q=Runner+One")
            return response.get_data(as_text=True)
    finally:
        web.app.testing = old_testing


def _user():
    return {"user_id": "user-a", "email": "owner@example.test", "plan": "all_access",
            "role": "owner", "is_admin": True}


def qc_phase2_route_and_watermark():
    with tempfile.TemporaryDirectory(prefix="lookup_view_qc_") as td:
        db = Path(td) / "changes.db"
        with LookupChangeStore(db) as store:
            store.ingest_observed(_item("q1", "2026-10-18T10:00:00Z", 40.5))
            first_event = store.ingest_observed(_item("q2", "2026-10-18T10:10:00Z", 42.5))
        env = {"LOOKUP_CHANGE_ENABLED": "1", "LOOKUP_CHANGE_DB_PATH": str(db)}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(web, "evaluate_nfl_player", return_value=_player_context()), \
             mock.patch.object(web, "get_current_user", return_value=_user()), \
             mock.patch.object(web, "is_owner_user", return_value=True), \
             mock.patch.object(web, "_card_prefs_uid", return_value="user-a"):
            first_html = _render()
            with LookupChangeStore(db) as store:
                first_mark = store.watermark_for("user-a", "player", ENTITY)
                second_event = store.ingest_observed(_item("q3", "2026-10-18T10:20:00Z", 43.5))
            second_html = _render()
            with LookupChangeStore(db) as store:
                second_mark = store.watermark_for("user-a", "player", ENTITY)
        checks = {
            "heading": "What&rsquo;s Changed?" in first_html,
            "first-baseline": "This is your first view" in first_html,
            "source-clocks": "Book Updated 2026-10-18 05:00 (tz unknown)" in first_html and
                             "Feed Captured 2026-10-18T10:10:00Z" in first_html,
            "significance-abstains": "Unavailable until a named Model Registry contract" in first_html,
            "first-watermark": first_mark and first_mark["last_seen_sequence"] == first_event["event_sequence"],
            "missed": "Since your last successful view" in second_html and "42.5 to 43.5" in second_html,
            "second-watermark": second_mark and second_mark["last_seen_sequence"] == second_event["event_sequence"],
        }
        return all(checks.values()), str(checks)


def qc_failed_render_does_not_advance():
    with tempfile.TemporaryDirectory(prefix="lookup_view_qc_") as td:
        db = Path(td) / "changes.db"
        with LookupChangeStore(db) as store:
            store.ingest_observed(_item("q1", "2026-10-18T10:00:00Z", 40.5))
            one = store.ingest_observed(_item("q2", "2026-10-18T10:10:00Z", 42.5))
            store.commit_rendered_view("user-a", "player", ENTITY, one["event_sequence"])
            two = store.ingest_observed(_item("q3", "2026-10-18T10:20:00Z", 43.5))
        env = {"LOOKUP_CHANGE_ENABLED": "1", "LOOKUP_CHANGE_DB_PATH": str(db)}
        failed = False
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(web, "evaluate_nfl_player", return_value=_player_context()), \
             mock.patch.object(web, "get_current_user", return_value=_user()), \
             mock.patch.object(web, "is_owner_user", return_value=True), \
             mock.patch.object(web, "_card_prefs_uid", return_value="user-a"), \
             mock.patch.object(web, "render_template", side_effect=RuntimeError("render failed")):
            try:
                _render()
            except RuntimeError:
                failed = True
        with LookupChangeStore(db) as store:
            mark = store.watermark_for("user-a", "player", ENTITY)
            pending = store.prepare_view("user-a", "player", ENTITY)["missed_events"]
        ok = failed and mark["last_seen_sequence"] == one["event_sequence"] and \
             [row["event_sequence"] for row in pending] == [two["event_sequence"]]
        return ok, f"failed={failed} watermark={mark} pending={len(pending)}"


def qc_flag_off_is_dark():
    with tempfile.TemporaryDirectory(prefix="lookup_view_qc_") as td:
        missing = Path(td) / "must-not-exist.db"
        env = {"LOOKUP_CHANGE_ENABLED": "0", "LOOKUP_CHANGE_DB_PATH": str(missing)}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(web, "evaluate_nfl_player", return_value=_player_context()), \
             mock.patch.object(web, "get_current_user", return_value=_user()), \
             mock.patch.object(web, "is_owner_user", return_value=True), \
             mock.patch.object(web, "_card_prefs_uid", return_value="user-a"):
            html = _render()
        visible = "What&rsquo;s Changed?" in html
        ok = not visible and not missing.exists()
        return ok, f"module_visible={visible} db_exists={missing.exists()}"


CHECKS = [
    ("route + first/missed watermark", qc_phase2_route_and_watermark),
    ("failed render preserves unread", qc_failed_render_does_not_advance),
    ("flag off stays dark", qc_flag_off_is_dark),
]


def main():
    failures = 0
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += int(not ok)
    print(f"Lookup Change Views QC: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
