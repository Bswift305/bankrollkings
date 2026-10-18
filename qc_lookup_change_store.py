"""QC for Lookup Phase 1: immutable store + cleared Odds API baseline ingestion."""
from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import pandas as pd

from ingest_lookup_market_changes import ingest_file
from services.lookup_changes import (
    LookupChangeStore,
    ObservedChangeInput,
    StoreUnavailable,
    ValidationError,
)


def _store(tmp: Path) -> LookupChangeStore:
    return LookupChangeStore(tmp / "changes.db")


def _item(**updates) -> ObservedChangeInput:
    base = dict(
        entity_type="player",
        entity_id="nfl:espn:123",
        field="market_quote:nfl:player_rush_yds:draftkings:a@b",
        current_value={"line": 40.5, "over_price": -110, "under_price": -110},
        dataset="odds_api_player_props",
        source="The Odds API",
        source_observation_id="quote-1",
        first_captured_at="2026-10-18T10:00:00Z",
        source_updated_at="2026-10-18T09:59:00-00:00",
        market_relative_timing="unknown",
    )
    base.update(updates)
    return ObservedChangeInput(**base)


def qc_baseline_idempotency_change():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        first = store.ingest_observed(_item())
        again = store.ingest_observed(_item())
        same = store.ingest_observed(_item(source_observation_id="quote-2",
                                           first_captured_at="2026-10-18T10:05:00Z"))
        changed = store.ingest_observed(_item(
            source_observation_id="quote-3",
            first_captured_at="2026-10-18T10:10:00Z",
            current_value={"line": 42.5, "over_price": -115, "under_price": -105},
        ))
        events = store.events_for_entity("player", "nfl:espn:123")
        ok = (first["status"] == "baseline" and again["status"] == "noop" and
              same["status"] == "unchanged" and changed["status"] == "change" and
              len(events) == 1 and events[0]["event_sequence"] == 1)
        return ok, f"statuses={[first['status'], again['status'], same['status'], changed['status']]} events={len(events)}"


def qc_correction_lineage():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        store.ingest_observed(_item())
        changed = store.ingest_observed(_item(
            source_observation_id="quote-2", first_captured_at="2026-10-18T10:10:00Z",
            current_value={"line": 41.5},
        ))
        correction = store.ingest_observed(_item(
            source_observation_id="quote-3", first_captured_at="2026-10-18T10:20:00Z",
            current_value={"line": 42.5}, corrects=changed["change_event_id"],
        ))
        events = store.events_for_entity("player", "nfl:espn:123")
        ok = (correction["status"] == "change" and len(events) == 2 and
              events[1]["corrects"] == events[0]["change_event_id"] and
              events[1]["supersedes"] == events[0]["change_event_id"])
        return ok, f"events={len(events)} correction={correction['status']}"


def qc_immutability():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        store.ingest_observed(_item())
        store.ingest_observed(_item(source_observation_id="quote-2",
                                    first_captured_at="2026-10-18T10:10:00Z",
                                    current_value={"line": 42.5}))
        blocked = 0
        for sql in ("UPDATE observations SET value_json='{}'", "DELETE FROM change_events"):
            try:
                store.conn.execute(sql)
            except sqlite3.IntegrityError:
                blocked += 1
        return blocked == 2, f"blocked={blocked}/2"


def qc_validation_and_lineage_gate():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        rejected = 0
        cases = [
            _item(dataset="nba_com_game_logs"),
            _item(entity_id=""),
            _item(first_captured_at="2026-10-18 10:00"),
            _item(market_relative_timing="true"),
        ]
        for case in cases:
            try:
                store.ingest_observed(case)
            except ValidationError:
                rejected += 1
        return rejected == len(cases), f"rejected={rejected}/{len(cases)}"


def qc_market_relative_tristate():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        result = store.ingest_observed(_item(
            market_relative_timing="true", referenced_quote_id="quote-ref",
            market_comparison_at="2026-10-18T09:58:00Z",
        ))
        return result["status"] == "baseline", f"status={result['status']}"


def qc_concurrent_idempotency():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td:
        path = Path(td) / "changes.db"
        with LookupChangeStore(path):
            pass
        results, errors = [], []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with LookupChangeStore(path) as store:
                    barrier.wait(timeout=5)
                    results.append(store.ingest_observed(_item())["status"])
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        with LookupChangeStore(path) as store:
            counts = store.counts()
        ok = not errors and sorted(results) == ["baseline", "noop"] and counts["observations"] == 1
        return ok, f"results={sorted(results)} errors={errors} counts={counts}"


def qc_first_visit_and_render_race():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        store.ingest_observed(_item())
        one = store.ingest_observed(_item(
            source_observation_id="quote-2", first_captured_at="2026-10-18T10:10:00Z",
            current_value={"line": 41.5},
        ))
        first = store.prepare_view("user-a", "player", "nfl:espn:123")
        before = store.watermark_for("user-a", "player", "nfl:espn:123")
        store.commit_rendered_view("user-a", "player", "nfl:espn:123", first["max_rendered_sequence"],
                                   viewed_at="2026-10-18T10:11:00Z")
        seeded = store.watermark_for("user-a", "player", "nfl:espn:123")

        two = store.ingest_observed(_item(
            source_observation_id="quote-3", first_captured_at="2026-10-18T10:20:00Z",
            effective_time="2026-10-17T08:00:00Z",  # delayed/backfilled fact
            current_value={"line": 42.5},
        ))
        pending = store.prepare_view("user-a", "player", "nfl:espn:123")
        # Simulate a failed render: no commit. The event must remain unread.
        pending_again = store.prepare_view("user-a", "player", "nfl:espn:123")
        store.commit_rendered_view("user-a", "player", "nfl:espn:123",
                                   pending_again["max_rendered_sequence"],
                                   viewed_at="2026-10-18T10:21:00Z")
        done = store.prepare_view("user-a", "player", "nfl:espn:123")
        other = store.prepare_view("user-b", "player", "nfl:espn:123")
        ok = (
            first["first_visit"] and first["missed_events"] == [] and before is None and
            seeded["last_seen_sequence"] == one["event_sequence"] and
            [row["event_sequence"] for row in pending["missed_events"]] == [two["event_sequence"]] and
            [row["event_sequence"] for row in pending_again["missed_events"]] == [two["event_sequence"]] and
            done["missed_events"] == [] and other["first_visit"] and other["missed_events"] == []
        )
        return ok, (f"first={first['first_visit']} pending={len(pending['missed_events'])} "
                    f"after_failed={len(pending_again['missed_events'])} done={len(done['missed_events'])}")


def qc_event_arrives_during_render():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        store.ingest_observed(_item())
        first_change = store.ingest_observed(_item(
            source_observation_id="quote-2", first_captured_at="2026-10-18T10:10:00Z",
            current_value={"line": 41.5},
        ))
        prepared = store.prepare_view("user-a", "player", "nfl:espn:123")
        # A new event lands after selection but before the response commits its watermark.
        late = store.ingest_observed(_item(
            source_observation_id="quote-3", first_captured_at="2026-10-18T10:11:00Z",
            current_value={"line": 42.5},
        ))
        store.commit_rendered_view("user-a", "player", "nfl:espn:123",
                                   prepared["max_rendered_sequence"])
        next_view = store.prepare_view("user-a", "player", "nfl:espn:123")
        got = [row["event_sequence"] for row in next_view["missed_events"]]
        ok = prepared["max_rendered_sequence"] == first_change["event_sequence"] and got == [late["event_sequence"]]
        return ok, f"rendered={prepared['max_rendered_sequence']} next_missed={got}"


def qc_minimal_user_state_and_purge():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td, _store(Path(td)) as store:
        store.commit_rendered_view("user-a", "player", "nfl:espn:123", 4)
        store.commit_rendered_view("user-a", "team", "nfl:team:ari", 7)
        store.commit_rendered_view("user-b", "player", "nfl:espn:123", 2)
        columns = [row[1] for row in store.conn.execute("PRAGMA table_info(viewer_watermarks)")]
        removed = store.purge_user_state("user-a")
        remain_a = store.conn.execute(
            "SELECT COUNT(*) FROM viewer_watermarks WHERE user_id='user-a'"
        ).fetchone()[0]
        remain_b = store.conn.execute(
            "SELECT COUNT(*) FROM viewer_watermarks WHERE user_id='user-b'"
        ).fetchone()[0]
        expected = {"user_id", "entity_type", "entity_id", "last_seen_sequence", "last_viewed_at"}
        ok = set(columns) == expected and removed == 2 and remain_a == 0 and remain_b == 1
        return ok, f"columns={columns} removed={removed} remain_a={remain_a} remain_b={remain_b}"


def qc_schema_migration_and_future_refusal():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td:
        path = Path(td) / "changes.db"
        with LookupChangeStore(path) as store:
            store.conn.execute("DROP TABLE viewer_watermarks")
            store.conn.execute("UPDATE schema_meta SET version=1 WHERE id=1")
        with LookupChangeStore(path) as migrated:
            version = migrated.conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
            table = migrated.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='viewer_watermarks'"
            ).fetchone()
            migrated.conn.execute("UPDATE schema_meta SET version=99 WHERE id=1")
        refused = False
        try:
            LookupChangeStore(path)
        except StoreUnavailable:
            refused = True
        return version == 2 and bool(table) and refused, f"migrated={version} table={bool(table)} refused={refused}"


def qc_file_ingestion_and_ambiguity():
    with tempfile.TemporaryDirectory(prefix="lookup_qc_") as td:
        root = Path(td)
        roster = root / "roster.csv"
        props = root / "props.csv"
        pd.DataFrame([
            {"PlayerID": "123", "Player": "Runner One"},
            {"PlayerID": "124", "Player": "Runner Two"},
        ]).to_csv(roster, index=False)
        pd.DataFrame([
            {"Player": "Runner One", "Stat": "Rush Yds", "MarketKey": "player_rush_yds",
             "Line": 40.5, "Game": "A@B", "Book": "DraftKings", "LastUpdated": "2026-10-18 05:00",
             "OverOdds": -110, "UnderOdds": -110},
            # Same player/book/market/game, simultaneous alternate line: both rows must abstain.
            {"Player": "Runner Two", "Stat": "Rush Yds", "MarketKey": "player_rush_yds",
             "Line": 30.5, "Game": "C@D", "Book": "FanDuel", "LastUpdated": "2026-10-18 05:00",
             "OverOdds": -105, "UnderOdds": -115},
            {"Player": "Runner Two", "Stat": "Rush Yds", "MarketKey": "player_rush_yds",
             "Line": 35.5, "Game": "C@D", "Book": "FanDuel", "LastUpdated": "2026-10-18 05:00",
             "OverOdds": 120, "UnderOdds": -140},
            {"Player": "Unknown Player", "Stat": "Rush Yds", "MarketKey": "player_rush_yds",
             "Line": 10.5, "Game": "E@F", "Book": "BetMGM", "LastUpdated": "2026-10-18 05:00",
             "OverOdds": -110, "UnderOdds": -110},
        ]).to_csv(props, index=False)
        with _store(root) as store:
            first = ingest_file(store, props, roster, captured_at="2026-10-18T12:00:00Z")
            second = ingest_file(store, props, roster, captured_at="2026-10-18T12:05:00Z")
            changed_props = pd.read_csv(props)
            changed_props.loc[0, "Line"] = 41.5
            changed_props.loc[0, "LastUpdated"] = "2026-10-18 05:10"
            changed_props.to_csv(props, index=False)
            third = ingest_file(store, props, roster, captured_at="2026-10-18T12:10:00Z")
            counts = store.counts()
            events = store.events_for_entity("player", "nfl:espn:123")
        ok = (first.get("baseline") == 1 and first.get("ambiguous_alt_line") == 2 and
              first.get("unresolved_identity") == 1 and second.get("noop") == 1 and
              third.get("change") == 1 and counts == {"observations": 2, "events": 1} and
              len(events) == 1 and events[0]["source_updated_at"] is None and
              events[0]["source_updated_raw"] == "2026-10-18 05:10")
        return ok, f"first={first} second={second} third={third} counts={counts}"


CHECKS = [
    ("baseline / idempotency / change", qc_baseline_idempotency_change),
    ("correction lineage", qc_correction_lineage),
    ("append-only immutability", qc_immutability),
    ("validation + dataset gate", qc_validation_and_lineage_gate),
    ("market-relative tri-state", qc_market_relative_tristate),
    ("concurrent idempotency", qc_concurrent_idempotency),
    ("first visit + failed render", qc_first_visit_and_render_race),
    ("view/update race", qc_event_arrives_during_render),
    ("minimal user state + purge", qc_minimal_user_state_and_purge),
    ("schema migration + future refusal", qc_schema_migration_and_future_refusal),
    ("file ingestion + ambiguity abstention", qc_file_ingestion_and_ambiguity),
]


def main() -> int:
    failures = 0
    for label, check in CHECKS:
        try:
            ok, detail = check()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += int(not ok)
    print(f"Lookup Change Store QC: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
