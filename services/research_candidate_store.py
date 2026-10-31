"""Research Candidate — local dark-store adapter (SLICE 2B, LOCAL ONLY).

Persists the Slice-1 domain objects of `services/research_candidate.py` into ONE SQLite database
(the Tier-B WAL idiom; see `docs/research_candidate_store_contract.md` Rev 2). This is the 2B scope:
schema + adapter + synthetic-fixture QC ONLY.

GOVERNED STORE PRINCIPLE: the LEDGER itself enforces its guarantees, not merely the Python adapter.
The database enforces, on its own (triggers + composite foreign keys + a durable reservation ledger):
  * write-once records (BEFORE UPDATE AND BEFORE DELETE triggers on every record table + the registry);
  * a global `record_seq` bijection with records — every record INSERT requires a matching
    `record_registry(record_seq, kind, record_id)` row (BEFORE INSERT bind triggers), `record_registry`
    forbids one `(kind, record_id)` under two sequences (UNIQUE), and reopen reconciles the bijection
    in BOTH directions;
  * same-LINEAGE supersession via COMPOSITE self foreign keys ((supersedes, observation_id),
    (supersedes, candidate_id), (supersedes, family_key_str)) — the prior row must belong to the same
    lineage, enforced by SQLite, not Python;
  * exactly-one-current-per-lineage with supersede-the-current-tip, maintained + guarded by triggers
    (the `*_current` tables are written only by triggers), so even direct SQL cannot insert a
    stale/cross-lineage successor or leave a record without its tip transition; reopen reconciles every
    tip against the immutable rows;
  * a DURABLE, monotonic sequence reservation (`seq_reservation`): `next_seq()` reserves persistently,
    so a value is never reissued after a restart and an unclaimed reservation is a persistent,
    intentional GAP; two connections cannot reserve the same value; a claim consumes a reservation.

TWO-TRANSACTION CONTRACT (honest): reservation and claim are SEPARATE transactions.
  1. `next_seq()` reserves the sequence in its OWN committed transaction (claimed=0).
  2. the record write is a SEPARATE transaction that atomically does registry-insert -> claim
     (reservation 0->1) -> record-insert -> trigger-maintained tip; it commits or rolls back as a unit.
  A crash BETWEEN the two leaves a permanent, unclaimed-reservation GAP (never reissued). A crash or
  rollback DURING the record write leaves no registry/claim/record/tip residue.

The Slice-1 `InMemoryResearchStore` replay adds the SEMANTIC checks SQLite cannot express (binding,
summary reconciliation, fail-closed conclusions, pre-event ordering) and verifies every content hash.

PRIVACY: this is PSEUDONYMOUS / LINKABLE data, NOT de-identified. `research_candidate.observation_id`
joins directly to the private row, and a candidate's `content_hash` depends on the observer + thesis
rehydrated from that private row. The account↔observation linkage lives only in `observation_private`;
the research tables carry no observer column but remain LINKABLE to the account via `observation_id`.
True de-identification (a verifiable projection that does not reconstruct deleted PII) is a FUTURE
redesign that must precede any erasure feature; this schema does not provide it.

STRICT 2B BOUNDARY: ONE local SQLite DB; the constructor REQUIRES an explicit path (no default). NO
backup/restore (2C), production path, feature flag, route, UI, job, deployment, or deletion/erasure.
Deletion requests FAIL CLOSED. Idempotency uses a caller-supplied immutable `idempotency_key`.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.research_candidate import (
    BaselineMethod, CandidateOutcome, CaseState, Category, Completeness, Direction, EntityIdentity,
    EvaluatedFinding, EventIdentity, EvidenceBundle, FamilyKey, FamilySummary, FindingStatus,
    InMemoryResearchStore, PrimaryEndpoint, ResearchCandidate, Resolution, SourceUpdatedStatus,
    SubLabel, TemporalFacts, UserObservation, canonical_json, content_hash,
)

SCHEMA_VERSION = 2   # v2 = durable reservation + composite lineage FKs + bind/tip triggers + registry
#                      constraints. v1 stores are structurally incompatible and fail closed on open
#                      (nothing is deployed, so no migration is provided).


# --------------------------------------------------------------------------- errors
class ResearchStoreError(Exception):
    """Base for store-layer errors."""


class SchemaVersionError(ResearchStoreError):
    """The on-disk schema version is not supported (fail closed, no mutation)."""


class IdempotencyConflict(ResearchStoreError):
    """An idempotency_key was reused with DIFFERENT content (fail closed)."""


class SequenceError(ResearchStoreError):
    """A record_seq was not reserved, already claimed, or breaks the ordering."""


class StoreIntegrityError(ResearchStoreError):
    """A content-hash recompute, integrity_check, foreign_key_check, bijection, tip, or allocator/
    registry reconcile failed — the store is disabled (fail closed)."""


class DeletionNotPermitted(ResearchStoreError):
    """Deletion/erasure is undecided (Rev 2 §3.8) — 2B fails closed on any deletion request."""


class CleanupError(ResearchStoreError):
    """A post-publication failure could not be cleaned up DURABLY: an invalid destination (or a sensitive
    temp DB copy) could not be removed/renamed, or was removed but its parent-directory sync was not
    proven durable. The unsafe path is named — surfaced unmistakably rather than swallowed, and durable
    cleanup is never reported unless it actually happened."""


# backward-compatible alias (restore-specific name retained)
RestoreCleanupError = CleanupError


# --------------------------------------------------------------------------- (de)serialize helpers
def _j(obj) -> str:
    return canonical_json(obj)


def _u(text: Optional[str]):
    return None if text is None else json.loads(text)


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _entity(d: dict) -> EntityIdentity:
    return EntityIdentity(d["canonical_id"], d["display"], Resolution(d["resolution"]))


def _event(d: dict) -> EventIdentity:
    return EventIdentity(d["canonical_id"], _dt(d["event_effective"]))


def _temporal(d: dict) -> TemporalFacts:
    return TemporalFacts(
        observed_at=_dt(d["observed_at"]), event_effective=_dt(d["event_effective"]),
        bk_captured=_dt(d["bk_captured"]), record_seq=d["record_seq"],
        source_updated=_dt(d["source_updated"]) if d["source_updated"] else None,
        source_updated_status=SourceUpdatedStatus(d["source_updated_status"]),
    )


def _baseline(d: dict) -> BaselineMethod:
    return BaselineMethod(d["method"], d["version"], tuple(d["covariates"]))


def _endpoint(d: Optional[dict]) -> Optional[PrimaryEndpoint]:
    if d is None:
        return None
    return PrimaryEndpoint(d["name"], d["version"], Direction(d["direction"]), d["mepi"], d["unit"])


def _family_key(d: dict) -> FamilyKey:
    return FamilyKey(Category(d["category"]), SubLabel(d["sub_label"]), d["endpoint_name"],
                     d["endpoint_version"], d["endpoint_contract_hash"], d["baseline_method"],
                     d["baseline_version"])


def _summary(d: dict, fk: FamilyKey) -> FamilySummary:
    return FamilySummary(fk, d["n_candidates"], d["n_eligible"], d["effective_n"], d["n_matched"],
                         d["n_partial"], d["n_pending"], d["n_unmeasurable"], d["n_invalidated"])


def _evidence(d: Optional[dict]) -> Optional[EvidenceBundle]:
    if d is None:
        return None
    return EvidenceBundle(d["effect_estimate"], d["interval_low"], d["interval_high"],
                          d["corrected_interval_low"], d["corrected_interval_high"],
                          d["out_of_sample"], d["sensitivity_analysis_done"], d["missingness_rule"])


# --------------------------------------------------------------------------- schema
_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seq_allocator (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  max_claimed INTEGER NOT NULL
);
-- DURABLE reservation ledger. next_seq() inserts here (unclaimed); a claim flips claimed 0->1 in the
-- record's transaction. A value is never reissued (next = MAX+1), so unclaimed reservations are
-- persistent, intentional GAPS; two connections cannot reserve the same value (serialized writes).
CREATE TABLE IF NOT EXISTS seq_reservation (
  record_seq INTEGER PRIMARY KEY,
  claimed    INTEGER NOT NULL DEFAULT 0 CHECK (claimed IN (0,1))
);
-- authoritative global record ledger: one row per RECORD, bijective with the record tables (enforced
-- by bind triggers + reopen reconcile). UNIQUE(kind,record_id) forbids one record under two sequences.
CREATE TABLE IF NOT EXISTS record_registry (
  record_seq INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('observation','candidate','outcome','finding')),
  record_id  TEXT NOT NULL,
  UNIQUE (kind, record_id)
);

CREATE TABLE IF NOT EXISTS observation_private (
  observation_id   TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  record_seq       INTEGER NOT NULL UNIQUE,
  observer         TEXT NOT NULL,
  entity_json      TEXT NOT NULL,
  event_json       TEXT NOT NULL,
  thesis           TEXT NOT NULL,
  sources_json     TEXT NOT NULL,
  acted            INTEGER NOT NULL CHECK (acted IN (0,1)),
  acted_journal_ref TEXT,
  observed_at      TEXT NOT NULL,
  bk_captured      TEXT NOT NULL,
  content_hash     TEXT NOT NULL
);

-- pseudonymous/linkable research evidence (NO observer column; observer/thesis rejoin via observation_id).
CREATE TABLE IF NOT EXISTS research_candidate (
  candidate_id     TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  record_seq       INTEGER NOT NULL UNIQUE,
  observation_id   TEXT NOT NULL REFERENCES observation_private(observation_id),
  category         TEXT NOT NULL,
  sub_label        TEXT NOT NULL,
  entity_json      TEXT NOT NULL,
  event_json       TEXT NOT NULL,
  temporal_json    TEXT NOT NULL,
  baseline_json    TEXT NOT NULL,
  endpoint_json    TEXT,
  assumptions_json TEXT NOT NULL,
  eligibility_json TEXT NOT NULL,
  invalidation_json TEXT NOT NULL,
  sources_json     TEXT NOT NULL,
  snapshot_json    TEXT NOT NULL,
  acted            INTEGER NOT NULL CHECK (acted IN (0,1)),
  supersedes       INTEGER,
  content_hash     TEXT NOT NULL,
  UNIQUE (record_seq, observation_id),
  FOREIGN KEY (supersedes, observation_id) REFERENCES research_candidate(record_seq, observation_id)
);

CREATE TABLE IF NOT EXISTS candidate_outcome (
  outcome_id       TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  record_seq       INTEGER NOT NULL UNIQUE,
  candidate_id     TEXT NOT NULL REFERENCES research_candidate(candidate_id),
  version          INTEGER NOT NULL,
  case_state       TEXT NOT NULL,
  bk_captured      TEXT NOT NULL,
  observed_value   REAL,
  baseline_value   REAL,
  completeness_json TEXT NOT NULL,
  covariates_json  TEXT NOT NULL,
  descriptive_json TEXT NOT NULL,
  receipt_ref      TEXT,
  invalidation_reason TEXT,
  supersedes       INTEGER,
  content_hash     TEXT NOT NULL,
  UNIQUE (record_seq, candidate_id),
  FOREIGN KEY (supersedes, candidate_id) REFERENCES candidate_outcome(record_seq, candidate_id)
);

CREATE TABLE IF NOT EXISTS evaluated_finding (
  finding_id       TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  record_seq       INTEGER NOT NULL UNIQUE,
  family_key_str   TEXT NOT NULL,
  family_key_json  TEXT NOT NULL,
  status           TEXT NOT NULL,
  summary_json     TEXT NOT NULL,
  endpoint_json    TEXT NOT NULL,
  bk_captured      TEXT NOT NULL,
  evidence_json    TEXT,
  supersedes       INTEGER,
  content_hash     TEXT NOT NULL,
  UNIQUE (record_seq, family_key_str),
  FOREIGN KEY (supersedes, family_key_str) REFERENCES evaluated_finding(record_seq, family_key_str)
);
CREATE INDEX IF NOT EXISTS idx_finding_family ON evaluated_finding(family_key_str);

-- current-tip tables are written ONLY by the triggers below.
CREATE TABLE IF NOT EXISTS candidate_current (
  observation_id TEXT PRIMARY KEY,
  record_seq     INTEGER NOT NULL UNIQUE REFERENCES research_candidate(record_seq)
);
CREATE TABLE IF NOT EXISTS outcome_current (
  candidate_id TEXT PRIMARY KEY,
  record_seq   INTEGER NOT NULL UNIQUE REFERENCES candidate_outcome(record_seq),
  version      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS finding_current (
  family_key_str TEXT PRIMARY KEY,
  record_seq     INTEGER NOT NULL UNIQUE REFERENCES evaluated_finding(record_seq)
);

-- write-once: records + the registry cannot be UPDATEd/DELETEd.
CREATE TRIGGER IF NOT EXISTS observation_private_no_update BEFORE UPDATE ON observation_private
BEGIN SELECT RAISE(ABORT, 'observation_private is immutable'); END;
CREATE TRIGGER IF NOT EXISTS observation_private_no_delete BEFORE DELETE ON observation_private
BEGIN SELECT RAISE(ABORT, 'observation_private is append-only'); END;
CREATE TRIGGER IF NOT EXISTS research_candidate_no_update BEFORE UPDATE ON research_candidate
BEGIN SELECT RAISE(ABORT, 'research_candidate is immutable'); END;
CREATE TRIGGER IF NOT EXISTS research_candidate_no_delete BEFORE DELETE ON research_candidate
BEGIN SELECT RAISE(ABORT, 'research_candidate is append-only'); END;
CREATE TRIGGER IF NOT EXISTS candidate_outcome_no_update BEFORE UPDATE ON candidate_outcome
BEGIN SELECT RAISE(ABORT, 'candidate_outcome is immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_outcome_no_delete BEFORE DELETE ON candidate_outcome
BEGIN SELECT RAISE(ABORT, 'candidate_outcome is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evaluated_finding_no_update BEFORE UPDATE ON evaluated_finding
BEGIN SELECT RAISE(ABORT, 'evaluated_finding is immutable'); END;
CREATE TRIGGER IF NOT EXISTS evaluated_finding_no_delete BEFORE DELETE ON evaluated_finding
BEGIN SELECT RAISE(ABORT, 'evaluated_finding is append-only'); END;
CREATE TRIGGER IF NOT EXISTS record_registry_no_update BEFORE UPDATE ON record_registry
BEGIN SELECT RAISE(ABORT, 'record_registry is immutable'); END;
CREATE TRIGGER IF NOT EXISTS record_registry_no_delete BEFORE DELETE ON record_registry
BEGIN SELECT RAISE(ABORT, 'record_registry is append-only'); END;

-- reservations: may only transition claimed 0->1 (same seq), never un-claim or delete (gaps are permanent),
-- and a claim requires the matching registry row (so a claimed reservation can never be orphaned).
CREATE TRIGGER IF NOT EXISTS seq_reservation_claim_only BEFORE UPDATE ON seq_reservation
WHEN NOT (OLD.claimed = 0 AND NEW.claimed = 1 AND OLD.record_seq = NEW.record_seq)
BEGIN SELECT RAISE(ABORT, 'reservation may only transition 0->1 for the same seq'); END;
CREATE TRIGGER IF NOT EXISTS seq_reservation_claim_needs_registry BEFORE UPDATE ON seq_reservation
WHEN OLD.claimed = 0 AND NEW.claimed = 1
 AND NOT EXISTS (SELECT 1 FROM record_registry r WHERE r.record_seq = NEW.record_seq)
BEGIN SELECT RAISE(ABORT, 'cannot claim a reservation with no matching record_registry row'); END;
CREATE TRIGGER IF NOT EXISTS seq_reservation_no_delete BEFORE DELETE ON seq_reservation
BEGIN SELECT RAISE(ABORT, 'reservations are permanent (intentional gaps)'); END;

-- record<->registry BIND: a record can only be inserted when its matching (seq,kind,id) registry row
-- exists AND its sequence has a CLAIMED reservation (binds record <-> registry <-> reservation).
CREATE TRIGGER IF NOT EXISTS observation_registry_bind BEFORE INSERT ON observation_private
WHEN NOT EXISTS (SELECT 1 FROM record_registry r
                 WHERE r.record_seq=NEW.record_seq AND r.kind='observation' AND r.record_id=NEW.observation_id)
  OR NOT EXISTS (SELECT 1 FROM seq_reservation s WHERE s.record_seq=NEW.record_seq AND s.claimed=1)
BEGIN SELECT RAISE(ABORT, 'observation needs a matching registry row + a claimed reservation'); END;
CREATE TRIGGER IF NOT EXISTS candidate_registry_bind BEFORE INSERT ON research_candidate
WHEN NOT EXISTS (SELECT 1 FROM record_registry r
                 WHERE r.record_seq=NEW.record_seq AND r.kind='candidate' AND r.record_id=NEW.candidate_id)
  OR NOT EXISTS (SELECT 1 FROM seq_reservation s WHERE s.record_seq=NEW.record_seq AND s.claimed=1)
BEGIN SELECT RAISE(ABORT, 'candidate needs a matching registry row + a claimed reservation'); END;
CREATE TRIGGER IF NOT EXISTS outcome_registry_bind BEFORE INSERT ON candidate_outcome
WHEN NOT EXISTS (SELECT 1 FROM record_registry r
                 WHERE r.record_seq=NEW.record_seq AND r.kind='outcome' AND r.record_id=NEW.outcome_id)
  OR NOT EXISTS (SELECT 1 FROM seq_reservation s WHERE s.record_seq=NEW.record_seq AND s.claimed=1)
BEGIN SELECT RAISE(ABORT, 'outcome needs a matching registry row + a claimed reservation'); END;
CREATE TRIGGER IF NOT EXISTS finding_registry_bind BEFORE INSERT ON evaluated_finding
WHEN NOT EXISTS (SELECT 1 FROM record_registry r
                 WHERE r.record_seq=NEW.record_seq AND r.kind='finding' AND r.record_id=NEW.finding_id)
  OR NOT EXISTS (SELECT 1 FROM seq_reservation s WHERE s.record_seq=NEW.record_seq AND s.claimed=1)
BEGIN SELECT RAISE(ABORT, 'finding needs a matching registry row + a claimed reservation'); END;

-- current-tip GUARD + APPLY (DB maintains the tip; cross-lineage/stale/duplicate successors abort).
CREATE TRIGGER IF NOT EXISTS candidate_tip_guard BEFORE INSERT ON research_candidate
WHEN (NEW.supersedes IS NULL AND EXISTS (SELECT 1 FROM candidate_current WHERE observation_id=NEW.observation_id))
  OR (NEW.supersedes IS NOT NULL AND NOT EXISTS (SELECT 1 FROM candidate_current
        WHERE observation_id=NEW.observation_id AND record_seq=NEW.supersedes))
BEGIN SELECT RAISE(ABORT, 'candidate tip violation (first-must-be-sole / supersedes-must-be-current-tip)'); END;
CREATE TRIGGER IF NOT EXISTS candidate_tip_apply_new AFTER INSERT ON research_candidate
WHEN NEW.supersedes IS NULL
BEGIN INSERT INTO candidate_current(observation_id, record_seq) VALUES (NEW.observation_id, NEW.record_seq); END;
CREATE TRIGGER IF NOT EXISTS candidate_tip_apply_super AFTER INSERT ON research_candidate
WHEN NEW.supersedes IS NOT NULL
BEGIN UPDATE candidate_current SET record_seq=NEW.record_seq WHERE observation_id=NEW.observation_id; END;

CREATE TRIGGER IF NOT EXISTS outcome_tip_guard BEFORE INSERT ON candidate_outcome
WHEN (NEW.supersedes IS NULL AND EXISTS (SELECT 1 FROM outcome_current WHERE candidate_id=NEW.candidate_id))
  OR (NEW.supersedes IS NOT NULL AND NOT EXISTS (SELECT 1 FROM outcome_current
        WHERE candidate_id=NEW.candidate_id AND record_seq=NEW.supersedes))
BEGIN SELECT RAISE(ABORT, 'outcome tip violation'); END;
CREATE TRIGGER IF NOT EXISTS outcome_tip_apply_new AFTER INSERT ON candidate_outcome
WHEN NEW.supersedes IS NULL
BEGIN INSERT INTO outcome_current(candidate_id, record_seq, version) VALUES (NEW.candidate_id, NEW.record_seq, NEW.version); END;
CREATE TRIGGER IF NOT EXISTS outcome_tip_apply_super AFTER INSERT ON candidate_outcome
WHEN NEW.supersedes IS NOT NULL
BEGIN UPDATE outcome_current SET record_seq=NEW.record_seq, version=NEW.version WHERE candidate_id=NEW.candidate_id; END;

CREATE TRIGGER IF NOT EXISTS finding_tip_guard BEFORE INSERT ON evaluated_finding
WHEN (NEW.supersedes IS NULL AND EXISTS (SELECT 1 FROM finding_current WHERE family_key_str=NEW.family_key_str))
  OR (NEW.supersedes IS NOT NULL AND NOT EXISTS (SELECT 1 FROM finding_current
        WHERE family_key_str=NEW.family_key_str AND record_seq=NEW.supersedes))
BEGIN SELECT RAISE(ABORT, 'finding tip violation'); END;
CREATE TRIGGER IF NOT EXISTS finding_tip_apply_new AFTER INSERT ON evaluated_finding
WHEN NEW.supersedes IS NULL
BEGIN INSERT INTO finding_current(family_key_str, record_seq) VALUES (NEW.family_key_str, NEW.record_seq); END;
CREATE TRIGGER IF NOT EXISTS finding_tip_apply_super AFTER INSERT ON evaluated_finding
WHEN NEW.supersedes IS NOT NULL
BEGIN UPDATE finding_current SET record_seq=NEW.record_seq WHERE family_key_str=NEW.family_key_str; END;
"""

# (table, kind, id column) for the bijection reconcile
_RECORD_TABLES = (("observation_private", "observation", "observation_id"),
                  ("research_candidate", "candidate", "candidate_id"),
                  ("candidate_outcome", "outcome", "outcome_id"),
                  ("evaluated_finding", "finding", "finding_id"))
# (record table, lineage col, tip table)
_TIP_TABLES = (("research_candidate", "observation_id", "candidate_current"),
               ("candidate_outcome", "candidate_id", "outcome_current"),
               ("evaluated_finding", "family_key_str", "finding_current"))


# --------------------------------------------------------------------------- the store
class ResearchCandidateStore:
    """A durable mirror of the Slice-1 domain objects in ONE SQLite DB. Local-only (2B)."""

    def __init__(self, db_path: str, *, create: bool = True) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise ResearchStoreError("db_path is required (2B: no default path, tests pass a temp dir)")
        if db_path == ":memory:":
            raise ResearchStoreError("db_path must be a real file path, not an in-memory DB")
        # create=False (used to VALIDATE a backup/restore target) requires an EXISTING valid v2 store;
        # it never creates schema, so a truncated/empty/foreign file fails closed instead of being
        # silently initialized.
        self.db_path = db_path
        if create:
            self.conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
        else:
            # VALIDATION open: the file must already exist (create nothing) and is opened READ-ONLY
            # (mode=ro) so validating a backup never writes bytes, mtime, or journal sidecars.
            if not os.path.isfile(db_path):
                raise SchemaVersionError("no store file at this path (validation creates nothing)")
            uri = Path(db_path).resolve().as_uri() + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            if create:
                self.conn.execute("PRAGMA foreign_keys=ON")
            self._init(create=create)
        except Exception:
            self.conn.close()
            raise

    # schema ----------------------------------------------------------------
    def _init(self, *, create: bool) -> None:
        has_meta = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
        if has_meta is not None:
            row = self.conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
            if row is None or int(row["version"]) != SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"unsupported schema version {None if row is None else row['version']} "
                    f"(expected {SCHEMA_VERSION}) — fail closed, no mutation")
            if create:   # a validation open (create=False) stays read-only — never flips the file to WAL
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=FULL")
        elif not create:
            # validation/restore-target open: refuse anything that is not already a v2 store.
            raise SchemaVersionError(
                "no research-candidate schema present (empty / truncated / foreign file) — fail closed")
        else:
            other = self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            if other:
                raise SchemaVersionError("database has a foreign schema; refusing to initialize over it")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.executescript(_SCHEMA_SQL)
            self.conn.execute("INSERT INTO schema_meta(id, version) VALUES (1, ?)", (SCHEMA_VERSION,))
            self.conn.execute("INSERT INTO seq_allocator(id, max_claimed) VALUES (1, 0)")
        self._check_integrity()

    def _check_integrity(self) -> None:
        ic = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ic != "ok":
            raise StoreIntegrityError(f"integrity_check failed: {ic}")
        fk = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise StoreIntegrityError(f"foreign_key_check failed: {[tuple(r) for r in fk]}")
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        maxr = int(self.conn.execute(
            "SELECT COALESCE(MAX(record_seq), 0) FROM record_registry").fetchone()[0])
        if maxc != maxr:
            raise StoreIntegrityError(f"allocator max_claimed {maxc} != registry max {maxr}")
        # record<->registry bijection, BOTH directions
        for table, kind, idcol in _RECORD_TABLES:
            orphan_rec = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} t WHERE NOT EXISTS (SELECT 1 FROM record_registry r "
                f"WHERE r.record_seq=t.record_seq AND r.kind=? AND r.record_id=t.{idcol})", (kind,)
            ).fetchone()[0]
            if orphan_rec:
                raise StoreIntegrityError(f"{table}: {orphan_rec} row(s) with no matching registry entry")
            orphan_reg = self.conn.execute(
                f"SELECT COUNT(*) FROM record_registry r WHERE r.kind=? AND NOT EXISTS "
                f"(SELECT 1 FROM {table} t WHERE t.record_seq=r.record_seq AND t.{idcol}=r.record_id)",
                (kind,)).fetchone()[0]
            if orphan_reg:
                raise StoreIntegrityError(f"registry: {orphan_reg} '{kind}' row(s) with no matching record")
        # claimed reservations <-> registry rows, BOTH directions (no orphan on either side)
        bad_res = self.conn.execute(
            "SELECT COUNT(*) FROM record_registry r WHERE NOT EXISTS "
            "(SELECT 1 FROM seq_reservation s WHERE s.record_seq=r.record_seq AND s.claimed=1)"
        ).fetchone()[0]
        if bad_res:
            raise StoreIntegrityError(f"{bad_res} registry row(s) without a claimed reservation")
        orphan_claim = self.conn.execute(
            "SELECT COUNT(*) FROM seq_reservation s WHERE s.claimed=1 AND NOT EXISTS "
            "(SELECT 1 FROM record_registry r WHERE r.record_seq=s.record_seq)"
        ).fetchone()[0]
        if orphan_claim:
            raise StoreIntegrityError(f"{orphan_claim} claimed reservation(s) with no registry row")
        maxres = int(self.conn.execute(
            "SELECT COALESCE(MAX(record_seq), 0) FROM seq_reservation").fetchone()[0])
        if maxres < maxc:
            raise StoreIntegrityError(f"reservation max {maxres} < claimed max {maxc}")
        # tip reconcile: the current (non-superseded) rows must equal the tip rows, both directions
        for table, lineage, tip in _TIP_TABLES:
            stale = self.conn.execute(
                f"SELECT COUNT(*) FROM {tip} c WHERE NOT EXISTS (SELECT 1 FROM {table} t "
                f"WHERE t.record_seq=c.record_seq AND t.{lineage}=c.{lineage} AND NOT EXISTS "
                f"(SELECT 1 FROM {table} s WHERE s.supersedes=t.record_seq))").fetchone()[0]
            if stale:
                raise StoreIntegrityError(f"{tip}: {stale} tip(s) not pointing at a current row")
            missing = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} t WHERE NOT EXISTS "
                f"(SELECT 1 FROM {table} s WHERE s.supersedes=t.record_seq) AND NOT EXISTS "
                f"(SELECT 1 FROM {tip} c WHERE c.record_seq=t.record_seq AND c.{lineage}=t.{lineage})"
            ).fetchone()[0]
            if missing:
                raise StoreIntegrityError(f"{table}: {missing} current row(s) with no tip entry")

    # durable sequence reservation -----------------------------------------
    def next_seq(self) -> int:
        """DURABLY reserve the next record_seq (persists across restarts; never reissued). Two
        connections serialize on BEGIN IMMEDIATE and receive distinct values. An unclaimed reservation
        is a permanent, intentional GAP."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            n = int(self.conn.execute(
                "SELECT COALESCE(MAX(record_seq), 0) FROM seq_reservation").fetchone()[0]) + 1
            self.conn.execute("INSERT INTO seq_reservation(record_seq, claimed) VALUES (?, 0)", (n,))
            self.conn.execute("COMMIT")
            return n
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _claim_seq(self, seq: int, kind: str, record_id: str) -> None:
        res = self.conn.execute("SELECT claimed FROM seq_reservation WHERE record_seq=?", (seq,)).fetchone()
        if res is None:
            raise SequenceError(f"record_seq {seq} was not reserved via next_seq()")
        if int(res["claimed"]) != 0:
            raise SequenceError(f"record_seq {seq} is already claimed")
        self.conn.execute("INSERT INTO record_registry(record_seq, kind, record_id) VALUES (?,?,?)",
                          (seq, kind, record_id))
        self.conn.execute("UPDATE seq_reservation SET claimed=1 WHERE record_seq=?", (seq,))
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        if seq > maxc:
            self.conn.execute("UPDATE seq_allocator SET max_claimed=? WHERE id=1", (seq,))

    # transactions ----------------------------------------------------------
    def _begin(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def _idem(self, table: str, key: str, new_hash: str):
        row = self.conn.execute(f"SELECT * FROM {table} WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["content_hash"] == new_hash:
            return row
        raise IdempotencyConflict(
            f"idempotency_key {key!r} reused with different content on {table} (fail closed)")

    # replay / in-memory semantic validation --------------------------------
    def _revive_all(self):
        obs = {}
        for r in self.conn.execute("SELECT * FROM observation_private"):
            o = UserObservation(
                observation_id=r["observation_id"], observer=r["observer"],
                entity=_entity(_u(r["entity_json"])), event=_event(_u(r["event_json"])),
                thesis=r["thesis"], observed_at=_dt(r["observed_at"]), bk_captured=_dt(r["bk_captured"]),
                record_seq=r["record_seq"], sources=tuple(_u(r["sources_json"])), acted=bool(r["acted"]),
                acted_journal_ref=r["acted_journal_ref"])
            _verify(o.content_hash, r["content_hash"], "observation", r["observation_id"])
            obs[o.observation_id] = o
        cands = []
        for r in self.conn.execute("SELECT * FROM research_candidate"):
            parent = obs[r["observation_id"]]
            c = ResearchCandidate(
                candidate_id=r["candidate_id"], observation_id=r["observation_id"],
                observer=parent.observer, category=Category(r["category"]),
                sub_label=SubLabel(r["sub_label"]), entity=_entity(_u(r["entity_json"])),
                event=_event(_u(r["event_json"])), temporal=_temporal(_u(r["temporal_json"])),
                thesis=parent.thesis, baseline=_baseline(_u(r["baseline_json"])),
                assumptions=tuple(_u(r["assumptions_json"])),
                eligibility_conditions=tuple(_u(r["eligibility_json"])),
                invalidation_conditions=tuple(_u(r["invalidation_json"])),
                primary_endpoint=_endpoint(_u(r["endpoint_json"])),
                pre_event_snapshot=_u(r["snapshot_json"]), acted=bool(r["acted"]),
                sources=tuple(_u(r["sources_json"])), supersedes=r["supersedes"])
            _verify(c.content_hash, r["content_hash"], "candidate", r["candidate_id"])
            cands.append(c)
        outs = []
        for r in self.conn.execute("SELECT * FROM candidate_outcome"):
            o = CandidateOutcome(
                outcome_id=r["outcome_id"], candidate_id=r["candidate_id"], version=r["version"],
                case_state=CaseState(r["case_state"]), bk_captured=_dt(r["bk_captured"]),
                record_seq=r["record_seq"], observed_endpoint_value=r["observed_value"],
                baseline_expected_value=r["baseline_value"],
                completeness={k: Completeness(v) for k, v in _u(r["completeness_json"]).items()},
                covariates=_u(r["covariates_json"]), descriptive=_u(r["descriptive_json"]),
                measurement_receipt_ref=r["receipt_ref"], invalidation_reason=r["invalidation_reason"],
                supersedes=r["supersedes"])
            _verify(content_hash(o), r["content_hash"], "outcome", r["outcome_id"])
            outs.append(o)
        finds = []
        for r in self.conn.execute("SELECT * FROM evaluated_finding"):
            fk = _family_key(_u(r["family_key_json"]))
            f = EvaluatedFinding(
                finding_id=r["finding_id"], family_key=fk, status=FindingStatus(r["status"]),
                summary=_summary(_u(r["summary_json"]), fk), endpoint=_endpoint(_u(r["endpoint_json"])),
                bk_captured=_dt(r["bk_captured"]), record_seq=r["record_seq"],
                evidence=_evidence(_u(r["evidence_json"])), supersedes=r["supersedes"])
            _verify(f.content_hash, r["content_hash"], "finding", r["finding_id"])
            finds.append(f)
        return obs, cands, outs, finds

    def _memory(self) -> InMemoryResearchStore:
        obs, cands, outs, finds = self._revive_all()
        records = ([(o.record_seq, 0, "obs", o) for o in obs.values()]
                   + [(c.temporal.record_seq, 1, "cand", c) for c in cands]
                   + [(o.record_seq, 2, "out", o) for o in outs]
                   + [(f.record_seq, 3, "find", f) for f in finds])
        records.sort(key=lambda t: (t[0], t[1]))
        mem = InMemoryResearchStore()
        for _, _, kind, obj in records:
            if kind == "obs":
                mem.record_observation(obj)
            elif kind == "cand":
                mem.freeze_candidate(obj)
            elif kind == "out":
                mem.append_outcome(obj)
            else:
                mem.record_finding(obj)
        return mem

    def replay_validate(self) -> dict:
        mem = self._memory()
        self._check_integrity()
        return {"observations": len(mem.observations), "candidates": len(mem.candidates),
                "max_claimed": int(self.conn.execute(
                    "SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])}

    # writes (triggers maintain tips + bind registry; no Python tip maintenance) --------
    def record_observation(self, obs: UserObservation, *, idempotency_key: str) -> dict:
        return self._write("observation_private", idempotency_key, obs.content_hash, "observation_id",
                           lambda: self._memory().record_observation(obs),
                           lambda: self._claim_seq(obs.record_seq, "observation", obs.observation_id),
                           lambda: self.conn.execute(
                               "INSERT INTO observation_private VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (obs.observation_id, idempotency_key, obs.record_seq, obs.observer,
                                _j(obs.entity), _j(obs.event), obs.thesis, _j(list(obs.sources)),
                                int(obs.acted), obs.acted_journal_ref, obs.observed_at.isoformat(),
                                obs.bk_captured.isoformat(), obs.content_hash)),
                           obs.observation_id, obs.record_seq)

    def freeze_candidate(self, cand: ResearchCandidate, *, idempotency_key: str) -> dict:
        seq = cand.temporal.record_seq
        return self._write("research_candidate", idempotency_key, cand.content_hash, "candidate_id",
                           lambda: self._memory().freeze_candidate(cand),
                           lambda: self._claim_seq(seq, "candidate", cand.candidate_id),
                           lambda: self.conn.execute(
                               "INSERT INTO research_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (cand.candidate_id, idempotency_key, seq, cand.observation_id,
                                cand.category.value, cand.sub_label.value, _j(cand.entity),
                                _j(cand.event), _j(cand.temporal), _j(cand.baseline),
                                _j(cand.primary_endpoint) if cand.primary_endpoint else None,
                                _j(list(cand.assumptions)), _j(list(cand.eligibility_conditions)),
                                _j(list(cand.invalidation_conditions)), _j(list(cand.sources)),
                                _j(cand.pre_event_snapshot), int(cand.acted), cand.supersedes,
                                cand.content_hash)),
                           cand.candidate_id, seq)

    def append_outcome(self, outcome: CandidateOutcome, *, idempotency_key: str) -> dict:
        return self._write("candidate_outcome", idempotency_key, content_hash(outcome), "outcome_id",
                           lambda: self._memory().append_outcome(outcome),
                           lambda: self._claim_seq(outcome.record_seq, "outcome", outcome.outcome_id),
                           lambda: self.conn.execute(
                               "INSERT INTO candidate_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (outcome.outcome_id, idempotency_key, outcome.record_seq,
                                outcome.candidate_id, outcome.version, outcome.case_state.value,
                                outcome.bk_captured.isoformat(), outcome.observed_endpoint_value,
                                outcome.baseline_expected_value, _j(outcome.completeness),
                                _j(outcome.covariates), _j(outcome.descriptive),
                                outcome.measurement_receipt_ref, outcome.invalidation_reason,
                                outcome.supersedes, content_hash(outcome))),
                           outcome.outcome_id, outcome.record_seq)

    def record_finding(self, finding: EvaluatedFinding, *, idempotency_key: str) -> dict:
        return self._write("evaluated_finding", idempotency_key, finding.content_hash, "finding_id",
                           lambda: self._memory().record_finding(finding),
                           lambda: self._claim_seq(finding.record_seq, "finding", finding.finding_id),
                           lambda: self.conn.execute(
                               "INSERT INTO evaluated_finding VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (finding.finding_id, idempotency_key, finding.record_seq,
                                finding.family_key.key, _j(finding.family_key), finding.status.value,
                                _j(finding.summary), _j(finding.endpoint),
                                finding.bk_captured.isoformat(),
                                _j(finding.evidence) if finding.evidence else None, finding.supersedes,
                                finding.content_hash)),
                           finding.finding_id, finding.record_seq)

    def _write(self, table, key, new_hash, idcol, validate, claim, insert, rid, seq) -> dict:
        _check_key(key)
        self._begin()
        try:
            hit = self._idem(table, key, new_hash)
            if hit is not None:
                self.conn.execute("ROLLBACK")
                return {"status": "noop", "id": hit[idcol] if idcol in hit.keys() else rid,
                        "record_seq": hit["record_seq"]}
            validate()            # Slice-1 semantic invariants (binding, reconcile, fail-closed, ...)
            claim()               # this txn: registry INSERT -> reservation claim (0->1) + allocator
            insert()              # record INSERT fires bind + tip triggers; rollback undoes ALL of it
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": rid, "record_seq": seq}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # reads -----------------------------------------------------------------
    def load_observation(self, observation_id: str) -> Optional[UserObservation]:
        return self._revive_all()[0].get(observation_id)

    def load_candidate(self, candidate_id: str) -> Optional[ResearchCandidate]:
        return next((c for c in self._revive_all()[1] if c.candidate_id == candidate_id), None)

    def current_outcome(self, candidate_id: str) -> Optional[CandidateOutcome]:
        return self._memory().current_outcome(candidate_id)

    def current_finding(self, family_key: FamilyKey) -> Optional[EvaluatedFinding]:
        return self._memory().current_finding(family_key)

    # backup / validate / restore (2C, LOCAL ONLY) -------------------------
    # Own implementation of the proven Tier-B pattern (VACUUM INTO consistent snapshot of a live WAL
    # DB -> full validation -> 0600). It does NOT import, modify, or extract Decision Journal code.
    @staticmethod
    def validate_store(path: str) -> dict:
        """FULL validation of an existing store file (used to accept a backup or a restored store):
        opens it with create=False (schema version + integrity_check + foreign_key_check + ledger
        reconcile + reservation/tip reconcile in `_init`/`_check_integrity`), then replays every record
        in record_seq order through the Slice-1 engine and re-verifies every content hash. Raises
        (SchemaVersionError / StoreIntegrityError / a domain error) and fails closed on any problem."""
        s = ResearchCandidateStore(path, create=False)
        try:
            return s.replay_validate()
        finally:
            s.close()

    def backup(self, dest_path: str) -> str:
        """Crash-safe, no-overwrite backup of this (possibly live, WAL) DB. `VACUUM INTO` writes a
        consistent snapshot to a same-directory TEMP path (never the final path, so an interrupted
        VACUUM cannot leave an apparently-final partial backup); the temp is fully validated, fsynced
        and locked down (0600 — POSIX-enforced, Windows best-effort), then published atomically with a
        create-if-absent hard link that refuses to overwrite an existing dest. `VACUUM INTO` never
        modifies the source."""
        if not isinstance(dest_path, str) or not dest_path.strip():
            raise ResearchStoreError("backup dest_path is required")
        tmp = _tmp_beside(dest_path)
        published = False
        try:
            self.conn.execute("VACUUM INTO ?", (tmp,))
            ResearchCandidateStore.validate_store(tmp)          # accept only a fully-valid snapshot
            _fsync_file(tmp)
            _lock_down(tmp)
            _link_no_overwrite(tmp, dest_path)                  # atomic create-if-absent (no overwrite)
            published = True                                    # OWNERSHIP the instant the link succeeds
            _fsync_dir(os.path.dirname(os.path.abspath(dest_path)))   # directory-durable publish (POSIX)
        except Exception as exc:
            # clean up the temp copy AND (if owned) the destination, aggregating every failure.
            _finish_cleanup(exc, [tmp, dest_path] if published else [tmp])
        _cleanup_temp_or_raise(tmp)           # success: surface a temp-cleanup failure (sensitive DB copy)
        return dest_path

    @staticmethod
    def restore(backup_path: str, dest_path: str) -> str:
        """Restore a VALIDATED backup to a NEW explicit path. The backup is fully validated FIRST (fail
        closed on corrupt/truncated/foreign/wrong-version/semantically-inconsistent), copied to a
        same-dir temp (fsynced, locked down), then PUBLISHED atomically with a create-if-absent hard
        link that never overwrites an existing/live DB. The restored store is re-validated; if that
        fails, the just-published dest is removed (quarantined) — a PRE-EXISTING dest is never touched."""
        if not isinstance(dest_path, str) or not dest_path.strip():
            raise ResearchStoreError("restore dest_path is required")
        ResearchCandidateStore.validate_store(backup_path)      # fail closed on a bad backup, before any copy
        tmp = _tmp_beside(dest_path)
        published = False
        try:
            shutil.copyfile(backup_path, tmp)
            _fsync_file(tmp)
            _lock_down(tmp)
            _link_no_overwrite(tmp, dest_path)
            published = True                                    # OWNERSHIP the instant the link succeeds
            _fsync_dir(os.path.dirname(os.path.abspath(dest_path)))   # directory-durable publish (POSIX)
            ResearchCandidateStore.validate_store(dest_path)    # the restored store must validate too
        except Exception as exc:
            # clean up the temp copy AND (if owned) the just-published destination, aggregating every
            # failure; a pre-existing dest is never owned (link refused) so it is never touched.
            _finish_cleanup(exc, [tmp, dest_path] if published else [tmp])
        _cleanup_temp_or_raise(tmp)           # success: surface a temp-cleanup failure (sensitive DB copy)
        return dest_path

    # deletion NOT implemented in 2B ---------------------------------------
    def delete_observation(self, *_a, **_k):
        raise DeletionNotPermitted(
            "deletion/erasure is undecided and unimplemented in 2B — a future approved erasure is a "
            "privileged transaction producing an erasure receipt, and requires an evidence projection "
            "that stays verifiable without reconstructing deleted PII (this schema does not provide it)")

    erase = delete_observation

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _tmp_beside(dest_path: str) -> str:
    """A unique, non-existent temp path in the SAME directory as dest (atomic publish needs same fs)."""
    d = os.path.dirname(os.path.abspath(dest_path)) or "."
    return os.path.join(d, f".{os.path.basename(dest_path)}.{uuid.uuid4().hex}.tmp")


def _fsync_file(path: str) -> None:
    # O_RDWR (not O_RDONLY): on Windows os.fsync requires a writable handle. We only flush, never write.
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: str) -> None:
    """Make a directory entry (a just-published or just-removed name) durable. POSIX only: Windows does
    NOT support fsync on a directory handle, so there it is a documented no-op (best-effort)."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _try_cleanup(path: str) -> tuple:
    """Dispose of one sensitive path (an invalid published dest or a temp DB copy) DURABLY. Removes it,
    else atomically renames it to a clearly ORPHAN name; on POSIX then fsyncs the parent dir so the
    removal/rename is durable. Returns (status, detail) and NEVER raises:
      * ("removed", ...)      -> gone and (POSIX) directory-durable — nothing left behind;
      * ("quarantined", path) -> could not remove but RENAMED to the given observable ORPHAN path;
      * ("failed", detail)    -> could neither remove nor rename, OR removed/renamed but the parent-dir
                                 sync failed (so disposal is NOT proven durable) — an unsafe path remains.
    Quarantined/failed are both surfaced by the caller; durable disposal is reported only as 'removed'."""
    if not os.path.lexists(path):
        return ("removed", f"{path} (already absent)")
    renamed = None
    try:
        os.remove(path)
    except OSError:
        try:
            renamed = path + f".ORPHAN-{uuid.uuid4().hex}"
            os.replace(path, renamed)
        except OSError:
            return ("failed", f"could not remove or rename; UNSAFE file remains at {path}")
    try:
        _fsync_dir(os.path.dirname(os.path.abspath(path)))
    except OSError:
        tgt = renamed or path
        return ("failed", f"{'renamed to ' + renamed if renamed else path + ' removed'} but the "
                          f"parent-directory sync failed, so disposal is NOT proven durable: {tgt}")
    if renamed:
        return ("quarantined", renamed)
    return ("removed", f"{path} removed")


def _finish_cleanup(primary_exc: BaseException, paths: list) -> None:
    """ERROR-PATH disposal: clean up EVERY path (temp copy + any owned destination), collecting all
    cleanup problems rather than stopping at the first. If any path was not cleanly, durably removed
    (failed OR quarantined-to-ORPHAN), raise a single CleanupError naming every affected path, chained
    from the original operation error. Otherwise re-raise the original error. Never silent."""
    unsafe = []
    for p in paths:
        status, detail = _try_cleanup(p)
        if status != "removed":
            unsafe.append(f"[{status}] {detail}")
    if unsafe:
        raise CleanupError(
            "operation failed AND cleanup left unsafe path(s): " + "; ".join(unsafe)) from primary_exc
    raise primary_exc


def _cleanup_temp_or_raise(tmp: str) -> None:
    """SUCCESS-PATH temp disposal: a sensitive temp DB copy that is not cleanly, durably removed
    (failed OR only quarantined) is surfaced as CleanupError naming it — never silently abandoned."""
    status, detail = _try_cleanup(tmp)
    if status != "removed":
        raise CleanupError(f"operation completed but the temp DB copy was not cleanly removed: [{status}] {detail}")


def _lock_down(path: str) -> None:
    """0600: ENFORCED + verified on POSIX; BEST-EFFORT on Windows (chmod does not set NTFS ACLs)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        if os.name != "nt":
            raise ResearchStoreError("could not set backup permissions to 0600")
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode != 0o600:
            raise ResearchStoreError(f"backup permissions not 0600 (got {oct(mode)})")


def _link_no_overwrite(tmp: str, dest_path: str) -> None:
    """Atomic create-if-absent publish — ONLY the hard link. It fails (FileExistsError -> ResearchStoreError)
    if dest already exists, so a destination created in a race is NEVER overwritten (unlike os.replace).
    The caller marks ownership IMMEDIATELY after this returns and fsyncs the directory separately, so a
    post-link fsync failure still triggers cleanup of the just-created destination."""
    try:
        os.link(tmp, dest_path)
    except FileExistsError:
        raise ResearchStoreError("dest already exists; refusing to overwrite (atomic no-overwrite publish)")


def _check_key(key) -> None:
    if not isinstance(key, str) or not key.strip():
        raise ResearchStoreError("idempotency_key is required and must be a non-empty string")


def _verify(recomputed: str, stored: str, kind: str, rid: str) -> None:
    if recomputed != stored:
        raise StoreIntegrityError(f"{kind} {rid}: content hash mismatch (corruption/tamper)")


__all__ = [
    "SCHEMA_VERSION", "ResearchCandidateStore", "ResearchStoreError", "SchemaVersionError",
    "IdempotencyConflict", "SequenceError", "StoreIntegrityError", "DeletionNotPermitted",
    "CleanupError", "RestoreCleanupError",
]
