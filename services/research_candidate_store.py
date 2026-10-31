"""Research Candidate — local dark-store adapter (SLICE 2B, LOCAL ONLY).

Persists the Slice-1 domain objects of `services/research_candidate.py` into ONE SQLite database
(the Tier-B WAL idiom; see `docs/research_candidate_store_contract.md` Rev 2). This is the 2B scope:
schema + adapter + synthetic-fixture QC ONLY.

GOVERNED STORE PRINCIPLE (reviewer round 2): the LEDGER itself must enforce its guarantees, not only
the Python adapter. The database therefore enforces, on its own: write-once records (`BEFORE UPDATE`
AND `BEFORE DELETE` triggers), a global strictly-unique `record_seq` across every record kind
(`record_registry` PRIMARY KEY), same-table `supersedes` foreign keys, and exactly-one-current-per-
lineage with supersede-the-current-tip (transactional `*_current` tables). The Slice-1
`InMemoryResearchStore` replay adds the *semantic* checks SQLite cannot express (binding, summary
reconciliation, fail-closed conclusions, pre-event ordering).

PRIVACY (corrected, reviewer round 2): this is **pseudonymous / linkable** data, NOT de-identified.
`research_candidate.observation_id` joins directly to the private row, and a candidate's domain
`content_hash` depends on the observer and thesis rehydrated from that private row. The account↔
observation linkage lives only in `observation_private`; the research tables carry no observer column
and hold the measurement — but they remain *linkable* to the account via `observation_id`. True
de-identification (an evidence projection/hash that stays verifiable without reconstructing deleted
PII) is a FUTURE redesign that must precede any erasure feature; this schema does not provide it.

STRICT 2B BOUNDARY (reviewer, Rev 2 §4):
  * ONE local SQLite DB; the constructor REQUIRES an explicit path (no default: never the checkout,
    OneDrive, `data/`, or a production runtime path).
  * NO backup/restore (2C), production path, feature flag, route, UI, job, deployment, or deletion/
    erasure implementation. Deletion requests FAIL CLOSED.

Idempotency (Rev 2 §5): every append takes a caller-supplied immutable `idempotency_key`. Exact retry
(same key + same content_hash) is a no-op returning the existing record; same key + different content
is a conflict (fail closed); a genuine correction is a NEW record with its own key + explicit supersedes.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from services.research_candidate import (
    BaselineMethod, CandidateOutcome, CaseState, Category, Completeness, Direction, EntityIdentity,
    EvaluatedFinding, EventIdentity, EvidenceBundle, FamilyKey, FamilySummary, FindingStatus,
    InMemoryResearchStore, PrimaryEndpoint, ResearchCandidate, Resolution, SourceUpdatedStatus,
    SubLabel, TemporalFacts, UserObservation, canonical_json, content_hash,
)

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- errors
class ResearchStoreError(Exception):
    """Base for store-layer errors."""


class SchemaVersionError(ResearchStoreError):
    """The on-disk schema version is not the one this code supports (fail closed, no mutation)."""


class IdempotencyConflict(ResearchStoreError):
    """An idempotency_key was reused with DIFFERENT content (fail closed, not a silent overwrite)."""


class SequenceError(ResearchStoreError):
    """A record_seq would break the store-wide strictly-monotonic/unique ordering."""


class StoreIntegrityError(ResearchStoreError):
    """A stored row failed a content-hash recomputation, integrity_check, foreign_key_check, or the
    allocator/registry reconcile — the store is disabled (fail closed)."""


class DeletionNotPermitted(ResearchStoreError):
    """Deletion/erasure is undecided (Rev 2 §3.8) — 2B fails closed on any deletion request."""


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
# DB-ENFORCED: global record_seq uniqueness (record_registry PK), same-table supersedes FKs, one
# current per lineage (*_current PK + supersede-the-tip UPDATE guard), write-once (UPDATE+DELETE
# triggers). The *_current pointer tables are the only mutable record-domain tables.
_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seq_allocator (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  max_claimed INTEGER NOT NULL
);
-- the authoritative global sequence ledger: every record of every kind registers its record_seq here
-- in the SAME transaction, so a record_seq is unique ACROSS tables, not merely per table.
CREATE TABLE IF NOT EXISTS record_registry (
  record_seq INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL CHECK (kind IN ('observation','candidate','outcome','finding')),
  record_id  TEXT NOT NULL
);

-- private: account/observation linkage + the observer's authored text (the ONLY place these live)
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

-- pseudonymous/linkable research evidence: NO observer column; observer/thesis rejoin from the private
-- row via observation_id (so this is LINKABLE, not de-identified).
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
  supersedes       INTEGER REFERENCES research_candidate(record_seq),
  content_hash     TEXT NOT NULL
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
  supersedes       INTEGER REFERENCES candidate_outcome(record_seq),
  content_hash     TEXT NOT NULL
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
  supersedes       INTEGER REFERENCES evaluated_finding(record_seq),
  content_hash     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finding_family ON evaluated_finding(family_key_str);

-- exactly-one-current-per-lineage, maintained transactionally. The PRIMARY KEY enforces one current;
-- a supersession UPDATE must match the prior current tip (WHERE record_seq = supersedes AND lineage),
-- so cross-lineage / non-tip supersession has no row to update.
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

-- write-once: records cannot be UPDATEd or DELETEd (corrections are NEW rows). Only the allocator and
-- the *_current pointer tables are mutable.
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
"""


# --------------------------------------------------------------------------- the store
class ResearchCandidateStore:
    """A durable mirror of the Slice-1 domain objects in ONE SQLite DB. Local-only (2B)."""

    def __init__(self, db_path: str) -> None:
        # Rev 2 §3.7/decision 7: an explicit path is REQUIRED; no silent default anywhere.
        if not isinstance(db_path, str) or not db_path.strip():
            raise ResearchStoreError("db_path is required (2B: no default path, tests pass a temp dir)")
        if db_path == ":memory:":
            raise ResearchStoreError("db_path must be a real file path, not an in-memory DB")
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        try:
            # session-only pragmas first (no file mutation); WAL is deferred into _init so an
            # UNSUPPORTED database is never written to before it fails closed.
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self._init()
            row = self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()
            self._max_allocated = int(row["max_claimed"])
        except Exception:
            self.conn.close()   # never leave a connection open on a failed init (reviewer #1)
            raise

    # schema ----------------------------------------------------------------
    def _init(self) -> None:
        has_meta = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
        if has_meta is not None:
            # EXISTING db — validate the version BEFORE any DDL/WAL mutation (reviewer #1).
            row = self.conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
            if row is None or int(row["version"]) != SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"unsupported schema version {None if row is None else row['version']} "
                    f"(expected {SCHEMA_VERSION}) — fail closed, no mutation"
                )
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
        else:
            # NEW db — refuse to initialize over a foreign non-empty database (no mutation).
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
            raise StoreIntegrityError(
                f"allocator max_claimed {maxc} != registry max {maxr} (reconcile failure)")

    # sequence --------------------------------------------------------------
    def next_seq(self) -> int:
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        self._max_allocated = max(self._max_allocated, maxc) + 1
        return self._max_allocated

    def _claim_seq(self, seq: int, kind: str, record_id: str) -> None:
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        if seq <= maxc:
            raise SequenceError(f"record_seq {seq} must be > max_claimed {maxc} (strict monotonic)")
        # the registry PK is the DB-level global-uniqueness backstop (across all record kinds).
        self.conn.execute("INSERT INTO record_registry(record_seq, kind, record_id) VALUES (?,?,?)",
                          (seq, kind, record_id))
        self.conn.execute("UPDATE seq_allocator SET max_claimed=? WHERE id=1", (seq,))
        if seq > self._max_allocated:
            self._max_allocated = seq

    # current-tip maintenance (DB-enforced one-current + supersede-the-tip) --
    def _advance_tip(self, table: str, key_col: str, key_val, new_seq: int,
                     supersedes: Optional[int], extra_cols=(), extra_vals=()) -> None:
        if supersedes is None:
            cols = (key_col, "record_seq") + tuple(extra_cols)
            vals = (key_val, new_seq) + tuple(extra_vals)
            placeholders = ",".join("?" for _ in cols)
            self.conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({placeholders})", vals)
        else:
            sets = "record_seq=?" + "".join(f", {c}=?" for c in extra_cols)
            cur = self.conn.execute(
                f"UPDATE {table} SET {sets} WHERE {key_col}=? AND record_seq=?",
                (new_seq, *extra_vals, key_val, supersedes))
            if cur.rowcount != 1:
                raise SequenceError(
                    f"{table}: supersedes {supersedes} is not the current tip of {key_col}={key_val!r} "
                    f"(cross-lineage or stale supersession)")

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

    # replay / in-memory validation (Rev 2 §3.9) ----------------------------
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
        """Replay stored rows in record_seq order through the Slice-1 engine — validates the SEMANTIC
        invariants (binding, summary reconciliation, fail-closed conclusions) the DB cannot express,
        reconstructs current state for the next write, and verifies every row's content hash."""
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

    # writes ----------------------------------------------------------------
    def record_observation(self, obs: UserObservation, *, idempotency_key: str) -> dict:
        _check_key(idempotency_key)
        self._begin()
        try:
            hit = self._idem("observation_private", idempotency_key, obs.content_hash)
            if hit is not None:
                self.conn.execute("ROLLBACK")
                return {"status": "noop", "id": hit["observation_id"], "record_seq": hit["record_seq"]}
            self._memory().record_observation(obs)
            self._claim_seq(obs.record_seq, "observation", obs.observation_id)
            self.conn.execute(
                "INSERT INTO observation_private VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (obs.observation_id, idempotency_key, obs.record_seq, obs.observer,
                 _j(obs.entity), _j(obs.event), obs.thesis, _j(list(obs.sources)), int(obs.acted),
                 obs.acted_journal_ref, obs.observed_at.isoformat(), obs.bk_captured.isoformat(),
                 obs.content_hash))
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": obs.observation_id, "record_seq": obs.record_seq}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def freeze_candidate(self, cand: ResearchCandidate, *, idempotency_key: str) -> dict:
        _check_key(idempotency_key)
        self._begin()
        try:
            hit = self._idem("research_candidate", idempotency_key, cand.content_hash)
            if hit is not None:
                self.conn.execute("ROLLBACK")
                return {"status": "noop", "id": hit["candidate_id"], "record_seq": hit["record_seq"]}
            self._memory().freeze_candidate(cand)
            seq = cand.temporal.record_seq
            self._claim_seq(seq, "candidate", cand.candidate_id)
            self.conn.execute(
                "INSERT INTO research_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cand.candidate_id, idempotency_key, seq, cand.observation_id, cand.category.value,
                 cand.sub_label.value, _j(cand.entity), _j(cand.event), _j(cand.temporal),
                 _j(cand.baseline), _j(cand.primary_endpoint) if cand.primary_endpoint else None,
                 _j(list(cand.assumptions)), _j(list(cand.eligibility_conditions)),
                 _j(list(cand.invalidation_conditions)), _j(list(cand.sources)),
                 _j(cand.pre_event_snapshot), int(cand.acted), cand.supersedes, cand.content_hash))
            self._advance_tip("candidate_current", "observation_id", cand.observation_id, seq,
                              cand.supersedes)
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": cand.candidate_id, "record_seq": seq}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def append_outcome(self, outcome: CandidateOutcome, *, idempotency_key: str) -> dict:
        _check_key(idempotency_key)
        self._begin()
        try:
            hit = self._idem("candidate_outcome", idempotency_key, content_hash(outcome))
            if hit is not None:
                self.conn.execute("ROLLBACK")
                return {"status": "noop", "id": hit["outcome_id"], "record_seq": hit["record_seq"]}
            self._memory().append_outcome(outcome)
            self._claim_seq(outcome.record_seq, "outcome", outcome.outcome_id)
            self.conn.execute(
                "INSERT INTO candidate_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (outcome.outcome_id, idempotency_key, outcome.record_seq, outcome.candidate_id,
                 outcome.version, outcome.case_state.value, outcome.bk_captured.isoformat(),
                 outcome.observed_endpoint_value, outcome.baseline_expected_value,
                 _j(outcome.completeness), _j(outcome.covariates), _j(outcome.descriptive),
                 outcome.measurement_receipt_ref, outcome.invalidation_reason, outcome.supersedes,
                 content_hash(outcome)))
            self._advance_tip("outcome_current", "candidate_id", outcome.candidate_id,
                              outcome.record_seq, outcome.supersedes, ("version",), (outcome.version,))
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": outcome.outcome_id, "record_seq": outcome.record_seq}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def record_finding(self, finding: EvaluatedFinding, *, idempotency_key: str) -> dict:
        _check_key(idempotency_key)
        self._begin()
        try:
            hit = self._idem("evaluated_finding", idempotency_key, finding.content_hash)
            if hit is not None:
                self.conn.execute("ROLLBACK")
                return {"status": "noop", "id": hit["finding_id"], "record_seq": hit["record_seq"]}
            self._memory().record_finding(finding)
            self._claim_seq(finding.record_seq, "finding", finding.finding_id)
            self.conn.execute(
                "INSERT INTO evaluated_finding VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (finding.finding_id, idempotency_key, finding.record_seq, finding.family_key.key,
                 _j(finding.family_key), finding.status.value, _j(finding.summary),
                 _j(finding.endpoint), finding.bk_captured.isoformat(),
                 _j(finding.evidence) if finding.evidence else None, finding.supersedes,
                 finding.content_hash))
            self._advance_tip("finding_current", "family_key_str", finding.family_key.key,
                              finding.record_seq, finding.supersedes)
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": finding.finding_id, "record_seq": finding.record_seq}
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

    # deletion is NOT implemented in 2B (Rev 2 §3.8 / decisions 3, 8) -------
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


def _check_key(key) -> None:
    if not isinstance(key, str) or not key.strip():
        raise ResearchStoreError("idempotency_key is required and must be a non-empty string")


def _verify(recomputed: str, stored: str, kind: str, rid: str) -> None:
    if recomputed != stored:
        raise StoreIntegrityError(f"{kind} {rid}: content hash mismatch (corruption/tamper)")


__all__ = [
    "SCHEMA_VERSION", "ResearchCandidateStore", "ResearchStoreError", "SchemaVersionError",
    "IdempotencyConflict", "SequenceError", "StoreIntegrityError", "DeletionNotPermitted",
]
