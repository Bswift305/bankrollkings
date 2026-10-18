"""Immutable change-event storage for Lookup Phase 1.

This module implements the storage contract in ``docs/lookup_change_first_spec.md``.
It has no Flask dependency and no presentation or ranking behavior.  Phase 1 only
accepts observed facts from an explicit dataset allowlist; the first observation is
a baseline and later value changes create immutable events.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
ALLOWED_DATASETS = {"odds_api_player_props"}
ENTITY_TYPES = {"player", "team", "game"}
RELIABILITY_STATES = {"confirmed", "preliminary"}
MARKET_TIMING_STATES = {"true", "false", "unknown"}


class LookupChangeError(Exception):
    """Base exception for the Lookup change-event store."""


class ValidationError(LookupChangeError):
    """An observation violates the frozen Phase-1 contract."""


class StoreUnavailable(LookupChangeError):
    """The event store cannot be opened or fails integrity checks."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_timestamp(value: str | None, *, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValidationError("a timezone-aware UTC timestamp is required")
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"invalid timestamp: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"timestamp has unknown timezone: {text}")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(parts: Iterable[Any]) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def resolve_db_path() -> Path:
    configured = str(os.environ.get("LOOKUP_CHANGE_DB_PATH", "") or "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return root / "BankrollKings" / "lookup" / "changes.db"
    return Path("/var/lib/bankrollkings/lookup/changes.db")


@dataclass(frozen=True)
class ObservedChangeInput:
    entity_type: str
    entity_id: str
    field: str
    current_value: Any
    dataset: str
    source: str
    source_observation_id: str
    first_captured_at: str
    source_updated_at: str | None = None
    source_updated_raw: str | None = None
    effective_time: str | None = None
    reliability_state: str = "confirmed"
    comparison_window: str | None = None
    explanation: str | None = None
    market_relative_timing: str = "unknown"
    referenced_quote_id: str | None = None
    market_comparison_at: str | None = None
    corrects: str | None = None


SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
  observation_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('player','team','game')),
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  dataset TEXT NOT NULL,
  source TEXT NOT NULL,
  source_observation_id TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_updated_at TEXT,
  source_updated_raw TEXT,
  first_captured_at TEXT NOT NULL,
  effective_time TEXT,
  reliability_state TEXT NOT NULL CHECK (reliability_state IN ('confirmed','preliminary')),
  created_at TEXT NOT NULL,
  UNIQUE(dataset, source_observation_id)
);
CREATE INDEX IF NOT EXISTS ix_observation_stream
  ON observations(entity_type, entity_id, field, first_captured_at);

CREATE TABLE IF NOT EXISTS stream_heads (
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  dataset TEXT NOT NULL,
  observation_id TEXT NOT NULL REFERENCES observations(observation_id),
  value_json TEXT NOT NULL,
  first_captured_at TEXT NOT NULL,
  PRIMARY KEY(entity_type, entity_id, field, dataset)
);

CREATE TABLE IF NOT EXISTS change_events (
  event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  change_event_id TEXT NOT NULL UNIQUE,
  dedup_key TEXT NOT NULL UNIQUE,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('player','team','game')),
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  change_class TEXT NOT NULL CHECK (change_class = 'observed'),
  prior_value_json TEXT NOT NULL,
  current_value_json TEXT NOT NULL,
  dataset TEXT NOT NULL,
  source TEXT NOT NULL,
  source_observation_id TEXT NOT NULL,
  observation_id TEXT NOT NULL REFERENCES observations(observation_id),
  source_updated_at TEXT,
  source_updated_raw TEXT,
  first_captured_at TEXT NOT NULL,
  effective_time TEXT,
  reliability_state TEXT NOT NULL CHECK (reliability_state IN ('confirmed','preliminary')),
  comparison_window TEXT NOT NULL,
  explanation TEXT NOT NULL,
  market_relative_timing TEXT NOT NULL CHECK (market_relative_timing IN ('true','false','unknown')),
  referenced_quote_id TEXT,
  market_comparison_at TEXT,
  corrects TEXT REFERENCES change_events(change_event_id),
  supersedes TEXT REFERENCES change_events(change_event_id),
  derivation_version TEXT,
  derived_meta_json TEXT,
  created_at TEXT NOT NULL,
  CHECK (derivation_version IS NULL),
  CHECK (derived_meta_json IS NULL),
  CHECK ((market_relative_timing = 'unknown') OR
         (referenced_quote_id IS NOT NULL AND market_comparison_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_change_entity_sequence
  ON change_events(entity_type, entity_id, event_sequence);

CREATE TRIGGER IF NOT EXISTS observations_no_update
BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS observations_no_delete
BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON change_events BEGIN SELECT RAISE(ABORT, 'change events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON change_events BEGIN SELECT RAISE(ABORT, 'change events are immutable'); END;
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


class LookupChangeStore:
    """The sole write boundary for immutable Lookup observations and events."""

    def __init__(self, path: str | Path | None = None, *, auto_init: bool = True):
        self.path = Path(path) if path else resolve_db_path()
        try:
            if auto_init:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(self.path.parent, 0o700)
            self.conn = _connect(self.path)
            if auto_init:
                self.conn.executescript(SCHEMA_SQL)
                self.conn.execute(
                    "INSERT OR IGNORE INTO schema_meta(id,version,applied_at) VALUES(1,?,?)",
                    (SCHEMA_VERSION, utc_now()),
                )
                if os.name != "nt":
                    os.chmod(self.path, 0o600)
            self._health_check()
        except (OSError, sqlite3.Error) as exc:
            raise StoreUnavailable("Lookup change store unavailable") from exc

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "LookupChangeStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _health_check(self) -> None:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise StoreUnavailable("Lookup change store failed integrity_check")
        meta = self.conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
        if not meta or int(meta[0]) != SCHEMA_VERSION:
            raise StoreUnavailable("Lookup change store schema mismatch")

    @staticmethod
    def _validate(item: ObservedChangeInput) -> dict[str, Any]:
        entity_type = str(item.entity_type or "").strip().lower()
        entity_id = str(item.entity_id or "").strip()
        field = str(item.field or "").strip()
        dataset = str(item.dataset or "").strip()
        source = str(item.source or "").strip()
        source_observation_id = str(item.source_observation_id or "").strip()
        if entity_type not in ENTITY_TYPES:
            raise ValidationError("invalid entity_type")
        if not entity_id or not field or not source or not source_observation_id:
            raise ValidationError("stable entity_id, field, source, and source_observation_id are required")
        if dataset not in ALLOWED_DATASETS:
            raise ValidationError(f"dataset is not cleared for Phase 1: {dataset}")
        if item.reliability_state not in RELIABILITY_STATES:
            raise ValidationError("invalid reliability_state")
        if item.market_relative_timing not in MARKET_TIMING_STATES:
            raise ValidationError("invalid market_relative_timing")
        if item.market_relative_timing != "unknown" and (
            not item.referenced_quote_id or not item.market_comparison_at
        ):
            raise ValidationError("known market-relative timing requires a quote id and comparison time")
        first_captured = _utc_timestamp(item.first_captured_at, required=True)
        source_updated = _utc_timestamp(item.source_updated_at)
        effective = _utc_timestamp(item.effective_time)
        comparison_at = _utc_timestamp(item.market_comparison_at)
        current_json = _canonical_json(item.current_value)
        if current_json == "null":
            raise ValidationError("unknown current_value cannot create an observation")
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field": field,
            "dataset": dataset,
            "source": source,
            "source_observation_id": source_observation_id,
            "first_captured_at": first_captured,
            "source_updated_at": source_updated,
            "source_updated_raw": str(item.source_updated_raw or "").strip() or None,
            "effective_time": effective,
            "reliability_state": item.reliability_state,
            "current_json": current_json,
            "market_relative_timing": item.market_relative_timing,
            "referenced_quote_id": item.referenced_quote_id,
            "market_comparison_at": comparison_at,
            "corrects": item.corrects,
            "comparison_window": str(item.comparison_window or "").strip(),
            "explanation": str(item.explanation or "").strip(),
        }

    def ingest_observed(self, item: ObservedChangeInput) -> dict[str, Any]:
        """Insert one observation; return baseline/noop/change without rewriting history."""
        value = self._validate(item)
        observation_id = str(uuid.uuid4())
        now = utc_now()
        with _transaction(self.conn):
            existing = self.conn.execute(
                "SELECT observation_id FROM observations WHERE dataset=? AND source_observation_id=?",
                (value["dataset"], value["source_observation_id"]),
            ).fetchone()
            if existing:
                return {"status": "noop", "observation_id": existing[0], "change_event_id": None}

            head = self.conn.execute(
                """SELECT observation_id,value_json,first_captured_at FROM stream_heads
                   WHERE entity_type=? AND entity_id=? AND field=? AND dataset=?""",
                (value["entity_type"], value["entity_id"], value["field"], value["dataset"]),
            ).fetchone()
            self.conn.execute(
                """INSERT INTO observations(
                     observation_id,entity_type,entity_id,field,dataset,source,source_observation_id,
                     value_json,source_updated_at,source_updated_raw,first_captured_at,effective_time,
                     reliability_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (observation_id, value["entity_type"], value["entity_id"], value["field"],
                 value["dataset"], value["source"], value["source_observation_id"],
                 value["current_json"], value["source_updated_at"], value["source_updated_raw"],
                 value["first_captured_at"], value["effective_time"], value["reliability_state"], now),
            )
            self.conn.execute(
                """INSERT INTO stream_heads(entity_type,entity_id,field,dataset,observation_id,
                     value_json,first_captured_at) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(entity_type,entity_id,field,dataset) DO UPDATE SET
                     observation_id=excluded.observation_id,value_json=excluded.value_json,
                     first_captured_at=excluded.first_captured_at""",
                (value["entity_type"], value["entity_id"], value["field"], value["dataset"],
                 observation_id, value["current_json"], value["first_captured_at"]),
            )
            if head is None or head["value_json"] == value["current_json"]:
                return {
                    "status": "baseline" if head is None else "unchanged",
                    "observation_id": observation_id,
                    "change_event_id": None,
                }

            if value["corrects"]:
                corrected = self.conn.execute(
                    """SELECT entity_type,entity_id,field FROM change_events
                       WHERE change_event_id=?""", (value["corrects"],),
                ).fetchone()
                if not corrected or tuple(corrected) != (
                    value["entity_type"], value["entity_id"], value["field"]
                ):
                    raise ValidationError("corrects must reference an event in the same stream")

            comparison_window = value["comparison_window"] or (
                f'{head["first_captured_at"]} -> {value["first_captured_at"]}'
            )
            explanation = value["explanation"] or "The captured market quote changed."
            dedup_key = _sha256((value["entity_id"], value["field"], "observed",
                                 value["source_observation_id"]))
            event_id = str(uuid.uuid4())
            self.conn.execute(
                """INSERT INTO change_events(
                     change_event_id,dedup_key,entity_type,entity_id,field,change_class,
                     prior_value_json,current_value_json,dataset,source,source_observation_id,
                     observation_id,source_updated_at,source_updated_raw,first_captured_at,effective_time,
                     reliability_state,comparison_window,explanation,market_relative_timing,
                     referenced_quote_id,market_comparison_at,corrects,supersedes,
                     derivation_version,derived_meta_json,created_at)
                   VALUES(?,?,?,?,?,'observed',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)""",
                (event_id, dedup_key, value["entity_type"], value["entity_id"], value["field"],
                 head["value_json"], value["current_json"], value["dataset"], value["source"],
                 value["source_observation_id"], observation_id, value["source_updated_at"],
                 value["source_updated_raw"], value["first_captured_at"], value["effective_time"],
                 value["reliability_state"], comparison_window, explanation,
                 value["market_relative_timing"], value["referenced_quote_id"],
                 value["market_comparison_at"], value["corrects"], value["corrects"], now),
            )
            sequence = self.conn.execute(
                "SELECT event_sequence FROM change_events WHERE change_event_id=?", (event_id,)
            ).fetchone()[0]
            return {"status": "change", "observation_id": observation_id,
                    "change_event_id": event_id, "event_sequence": int(sequence)}

    def events_for_entity(self, entity_type: str, entity_id: str, *, after_sequence: int = 0) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM change_events WHERE entity_type=? AND entity_id=?
               AND event_sequence>? ORDER BY event_sequence""",
            (entity_type, entity_id, int(after_sequence)),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        return {
            "observations": int(self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]),
            "events": int(self.conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]),
        }
