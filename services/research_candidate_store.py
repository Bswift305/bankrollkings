"""Research Candidate — local dark-store adapter (SLICE 2B, LOCAL ONLY).

Persists the Slice-1 domain objects of `services/research_candidate.py` into ONE SQLite database
(the Tier-B WAL idiom; see `docs/research_candidate_store_contract.md` Rev 2). This is the 2B scope:
schema + adapter + synthetic-fixture QC ONLY.

STRICT 2B BOUNDARY (reviewer, Rev 2 §4):
  * ONE local SQLite DB with logically separated TABLES — private account/observation linkage vs
    de-identified research evidence vs the sequence allocator + schema metadata.
  * The constructor REQUIRES an explicit db path. There is NO default: it never falls back to the
    checkout, OneDrive, `data/`, or a production runtime path.
  * NO backup/restore system (that is 2C), NO production path, NO feature flag, NO route, NO UI, NO
    job, NO deployment, NO deletion/erasure implementation. Deletion requests FAIL CLOSED.
  * The store adds NO authority/scoring/logic beyond the Slice-1 domain layer. Semantic invariants
    (binding, lineage, fail-closed conclusions, summary reconciliation, strict monotonic record_seq)
    are validated by replaying through the Slice-1 `InMemoryResearchStore`; the DB adds storage-level
    enforcement on top (write-once triggers, UNIQUE idempotency keys, FKs, a persisted allocator).

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
    """The on-disk schema version is not the one this code supports (fail closed)."""


class IdempotencyConflict(ResearchStoreError):
    """An idempotency_key was reused with DIFFERENT content (fail closed, not a silent overwrite)."""


class SequenceError(ResearchStoreError):
    """A record_seq would break the store-wide strictly-monotonic ordering."""


class StoreIntegrityError(ResearchStoreError):
    """A stored row failed its content-hash recomputation or an integrity check."""


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
_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seq_allocator (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  max_claimed INTEGER NOT NULL
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

-- de-identified research evidence (NO observer column; observer/thesis are joined from the private table)
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
  supersedes       INTEGER,
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
  supersedes       INTEGER,
  content_hash     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finding_family ON evaluated_finding(family_key_str);

-- write-once: records are immutable; corrections are NEW rows, never UPDATEs (only seq_allocator mutates).
CREATE TRIGGER IF NOT EXISTS observation_private_immutable BEFORE UPDATE ON observation_private
BEGIN SELECT RAISE(ABORT, 'observation_private is immutable'); END;
CREATE TRIGGER IF NOT EXISTS research_candidate_immutable BEFORE UPDATE ON research_candidate
BEGIN SELECT RAISE(ABORT, 'research_candidate is immutable'); END;
CREATE TRIGGER IF NOT EXISTS candidate_outcome_immutable BEFORE UPDATE ON candidate_outcome
BEGIN SELECT RAISE(ABORT, 'candidate_outcome is immutable'); END;
CREATE TRIGGER IF NOT EXISTS evaluated_finding_immutable BEFORE UPDATE ON evaluated_finding
BEGIN SELECT RAISE(ABORT, 'evaluated_finding is immutable'); END;
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
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init()
        row = self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()
        self._max_allocated = int(row["max_claimed"])

    # schema ----------------------------------------------------------------
    def _init(self) -> None:
        self.conn.executescript(_SCHEMA_SQL)
        row = self.conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_meta(id, version) VALUES (1, ?)", (SCHEMA_VERSION,))
        elif int(row["version"]) != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported schema version {row['version']} (expected {SCHEMA_VERSION}) — fail closed"
            )
        if self.conn.execute("SELECT 1 FROM seq_allocator WHERE id=1").fetchone() is None:
            self.conn.execute("INSERT INTO seq_allocator(id, max_claimed) VALUES (1, 0)")
        ic = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ic != "ok":
            raise StoreIntegrityError(f"integrity_check failed: {ic}")

    # sequence --------------------------------------------------------------
    def next_seq(self) -> int:
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        self._max_allocated = max(self._max_allocated, maxc) + 1
        return self._max_allocated

    def _claim_seq(self, seq: int) -> None:
        maxc = int(self.conn.execute("SELECT max_claimed FROM seq_allocator WHERE id=1").fetchone()[0])
        if seq <= maxc:
            raise SequenceError(f"record_seq {seq} must be > max_claimed {maxc} (strict monotonic)")
        self.conn.execute("UPDATE seq_allocator SET max_claimed=? WHERE id=1", (seq,))
        if seq > self._max_allocated:
            self._max_allocated = seq

    # transactions ----------------------------------------------------------
    def _begin(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    # idempotency -----------------------------------------------------------
    def _idem(self, table: str, key: str, new_hash: str):
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["content_hash"] == new_hash:
            return row                                   # exact retry -> caller returns noop
        raise IdempotencyConflict(
            f"idempotency_key {key!r} reused with different content on {table} (fail closed)"
        )

    # replay / in-memory validation (Rev 2 §3.9, decision 6) ----------------
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
                case_state=CaseState(r["case_state"]),
                bk_captured=_dt(r["bk_captured"]), record_seq=r["record_seq"],
                observed_endpoint_value=r["observed_value"], baseline_expected_value=r["baseline_value"],
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
        """Replay stored rows in record_seq order through the Slice-1 engine. This both reconstructs
        current state for validating the next write AND proves the stored ledger is consistent
        (ids, hashes, supersession links, current tips)."""
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
            self._memory().record_observation(obs)      # validate via Slice-1 semantics
            self._claim_seq(obs.record_seq)
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
            self._claim_seq(cand.temporal.record_seq)
            self.conn.execute(
                "INSERT INTO research_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cand.candidate_id, idempotency_key, cand.temporal.record_seq, cand.observation_id,
                 cand.category.value, cand.sub_label.value, _j(cand.entity), _j(cand.event),
                 _j(cand.temporal), _j(cand.baseline),
                 _j(cand.primary_endpoint) if cand.primary_endpoint else None,
                 _j(list(cand.assumptions)), _j(list(cand.eligibility_conditions)),
                 _j(list(cand.invalidation_conditions)), _j(list(cand.sources)),
                 _j(cand.pre_event_snapshot), int(cand.acted), cand.supersedes, cand.content_hash))
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": cand.candidate_id, "record_seq": cand.temporal.record_seq}
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
            self._claim_seq(outcome.record_seq)
            self.conn.execute(
                "INSERT INTO candidate_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (outcome.outcome_id, idempotency_key, outcome.record_seq, outcome.candidate_id,
                 outcome.version, outcome.case_state.value, outcome.bk_captured.isoformat(),
                 outcome.observed_endpoint_value, outcome.baseline_expected_value,
                 _j(outcome.completeness), _j(outcome.covariates), _j(outcome.descriptive),
                 outcome.measurement_receipt_ref, outcome.invalidation_reason, outcome.supersedes,
                 content_hash(outcome)))
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
            self._memory().record_finding(finding)      # reconciles summary + requires a real family
            self._claim_seq(finding.record_seq)
            self.conn.execute(
                "INSERT INTO evaluated_finding VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (finding.finding_id, idempotency_key, finding.record_seq, finding.family_key.key,
                 _j(finding.family_key), finding.status.value, _j(finding.summary),
                 _j(finding.endpoint), finding.bk_captured.isoformat(),
                 _j(finding.evidence) if finding.evidence else None, finding.supersedes,
                 finding.content_hash))
            self.conn.execute("COMMIT")
            return {"status": "recorded", "id": finding.finding_id, "record_seq": finding.record_seq}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # reads -----------------------------------------------------------------
    def load_observation(self, observation_id: str) -> Optional[UserObservation]:
        obs, _, _, _ = self._revive_all()
        return obs.get(observation_id)

    def load_candidate(self, candidate_id: str) -> Optional[ResearchCandidate]:
        _, cands, _, _ = self._revive_all()
        return next((c for c in cands if c.candidate_id == candidate_id), None)

    def current_outcome(self, candidate_id: str) -> Optional[CandidateOutcome]:
        return self._memory().current_outcome(candidate_id)

    def current_finding(self, family_key: FamilyKey) -> Optional[EvaluatedFinding]:
        return self._memory().current_finding(family_key)

    # deletion is NOT implemented in 2B (Rev 2 §3.8 / decision 3, 8) --------
    def delete_observation(self, *_a, **_k):
        raise DeletionNotPermitted(
            "deletion/erasure is undecided and unimplemented in 2B — a future approved erasure is a "
            "privileged transaction producing an erasure receipt, never an ordinary repository delete"
        )

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
