"""Prospective shadow-observation store for governed angle models."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.model_registry import registry_entries


SCHEMA_VERSION = 1


def _utc(value):
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ModelObservationStore:
    def __init__(self, path=None):
        raw = path or os.environ.get("MODEL_OBSERVATION_DB_PATH")
        if not raw:
            raw = Path(os.environ.get("BK_RUNTIME_DIR", "/var/lib/bankrollkings")) / "model_observations" / "observations.db"
        self.path = Path(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL CHECK(version > 0));
        CREATE TABLE IF NOT EXISTS observations(
          observation_id TEXT PRIMARY KEY,
          dedup_key TEXT NOT NULL UNIQUE,
          model_id TEXT NOT NULL,
          model_version TEXT NOT NULL,
          sport TEXT NOT NULL,
          event_id TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          market TEXT NOT NULL,
          direction TEXT NOT NULL CHECK(direction IN ('OVER','UNDER')),
          line REAL NOT NULL,
          price INTEGER NOT NULL CHECK(price <= -100 OR price >= 100),
          sportsbook TEXT NOT NULL,
          quote_captured_at TEXT NOT NULL,
          event_start TEXT NOT NULL,
          inputs_json TEXT NOT NULL,
          lineage_json TEXT NOT NULL,
          output_json TEXT NOT NULL,
          status_at_capture TEXT NOT NULL CHECK(status_at_capture IN ('Discovery','Under Review','Qualified')),
          created_at TEXT NOT NULL,
          result_value REAL,
          grade TEXT CHECK(grade IN ('HIT','MISS','PUSH','VOID','DNP','UNGRADED')),
          graded_at TEXT,
          CHECK((grade IS NULL AND graded_at IS NULL) OR (grade IS NOT NULL AND graded_at IS NOT NULL))
        );
        CREATE TRIGGER IF NOT EXISTS observations_decision_immutable
        BEFORE UPDATE ON observations
        WHEN NEW.dedup_key != OLD.dedup_key OR NEW.model_id != OLD.model_id OR
             NEW.model_version != OLD.model_version OR NEW.sport != OLD.sport OR
             NEW.event_id != OLD.event_id OR NEW.entity_id != OLD.entity_id OR
             NEW.market != OLD.market OR NEW.direction != OLD.direction OR NEW.line != OLD.line OR
             NEW.price != OLD.price OR NEW.sportsbook != OLD.sportsbook OR
             NEW.quote_captured_at != OLD.quote_captured_at OR NEW.event_start != OLD.event_start OR
             NEW.inputs_json != OLD.inputs_json OR NEW.lineage_json != OLD.lineage_json OR
             NEW.output_json != OLD.output_json OR NEW.status_at_capture != OLD.status_at_capture OR
             NEW.created_at != OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'decision snapshot is immutable'); END;
        """)
        row = self.conn.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_meta(version) VALUES(?)", (SCHEMA_VERSION,))
        elif row["version"] != SCHEMA_VERSION:
            raise RuntimeError("unsupported model-observation schema")
        self.conn.commit()

    def capture(self, *, dedup_key, model_id, event_id, entity_id, market, direction, line,
                price, sportsbook, quote_captured_at, event_start, inputs, lineage, output):
        entries = {e["model_id"]: e for e in registry_entries()}
        entry = entries.get(model_id)
        if not entry:
            raise ValueError("unknown model_id")
        captured, start = _utc(quote_captured_at), _utc(event_start)
        if captured >= start:
            raise ValueError("observation must be captured before event start")
        if not isinstance(inputs, dict) or not inputs or not isinstance(lineage, dict) or not lineage:
            raise ValueError("inputs and lineage are required")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        oid = str(uuid.uuid4())
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("""INSERT INTO observations VALUES(
              ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)""", (
                oid, str(dedup_key), model_id, entry["version"], entry["sport"], str(event_id),
                str(entity_id), str(market), str(direction).upper(), float(line), int(price),
                str(sportsbook), captured, start, json.dumps(inputs, sort_keys=True),
                json.dumps(lineage, sort_keys=True), json.dumps(output, sort_keys=True),
                entry["status"], now,
            ))
            self.conn.commit()
            return {"status": "captured", "observation_id": oid}
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            if "dedup_key" in str(exc):
                return {"status": "noop", "observation_id": None}
            raise

    def grade(self, observation_id, grade, result_value=None, graded_at=None):
        grade = str(grade or "").upper()
        if grade not in {"HIT", "MISS", "PUSH", "VOID", "DNP", "UNGRADED"}:
            raise ValueError("invalid grade")
        at = _utc(graded_at or datetime.now(timezone.utc).isoformat())
        cur = self.conn.execute(
            "UPDATE observations SET result_value=?, grade=?, graded_at=? WHERE observation_id=? AND grade IS NULL",
            (None if result_value is None else float(result_value), grade, at, str(observation_id)),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
