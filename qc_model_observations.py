"""QC for prospective model shadow observations."""
import sqlite3
import tempfile
from pathlib import Path

from services.model_observations import ModelObservationStore


def _capture(store, **overrides):
    row = dict(dedup_key="q1", model_id="nfl_qb_rushing_yards", event_id="game-1",
               entity_id="espn:123", market="rushing_yards", direction="OVER", line=35.5,
               price=-110, sportsbook="Book", quote_captured_at="2026-10-18T10:00:00Z",
               event_start="2026-10-18T20:00:00Z",
               inputs={"qb_rush_attempts_l5": 7.2, "opponent_qb_rush_allowed": 31.4},
               lineage={"player": "nflverse", "market": "odds_api_player_props"},
               output={"kind": "contextual_alignment", "value": "abstain"})
    row.update(overrides)
    return store.capture(**row)


def qc_capture_idempotency_and_grade():
    with tempfile.TemporaryDirectory() as td, ModelObservationStore(Path(td) / "o.db") as store:
        one = _capture(store)
        two = _capture(store)
        graded = store.grade(one["observation_id"], "PUSH", 35.5, "2026-10-19T01:00:00Z")
        twice = store.grade(one["observation_id"], "HIT", 40, "2026-10-19T01:01:00Z")
        row = store.conn.execute("SELECT * FROM observations").fetchone()
        ok = one["status"] == "captured" and two["status"] == "noop" and graded and not twice and row["grade"] == "PUSH"
        return ok, f"one={one['status']} two={two['status']} grade={row['grade']}"


def qc_prestart_and_lineage_required():
    rejected = 0
    with tempfile.TemporaryDirectory() as td, ModelObservationStore(Path(td) / "o.db") as store:
        for changes in ({"quote_captured_at": "2026-10-18T21:00:00Z"}, {"lineage": {}}, {"model_id": "unknown"}):
            try:
                _capture(store, dedup_key=str(changes), **changes)
            except ValueError:
                rejected += 1
    return rejected == 3, f"rejected={rejected}/3"


def qc_snapshot_is_immutable():
    with tempfile.TemporaryDirectory() as td, ModelObservationStore(Path(td) / "o.db") as store:
        oid = _capture(store)["observation_id"]
        blocked = False
        try:
            store.conn.execute("UPDATE observations SET line=99 WHERE observation_id=?", (oid,))
            store.conn.commit()
        except sqlite3.IntegrityError:
            store.conn.rollback(); blocked = True
        line = store.conn.execute("SELECT line FROM observations WHERE observation_id=?", (oid,)).fetchone()[0]
    return blocked and line == 35.5, f"blocked={blocked} line={line}"


CHECKS = [("idempotency + push grade", qc_capture_idempotency_and_grade),
          ("prestart + lineage required", qc_prestart_and_lineage_required),
          ("decision snapshot immutable", qc_snapshot_is_immutable)]


def main():
    fails = 0
    for label, fn in CHECKS:
        try: ok, detail = fn()
        except Exception as exc: ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}"); fails += int(not ok)
    print(f"Model Observations QC: {len(CHECKS)-fails}/{len(CHECKS)} passed")
    return 1 if fails else 0


if __name__ == "__main__": raise SystemExit(main())
