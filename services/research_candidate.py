"""Research Candidate — governed domain contract + validators (SLICE 1, DARK/LOCAL).

Implements the approved design `docs/research_candidate_contract.md` (Rev 2.1): the object
model and lifecycle that turns a human observation into an honestly testable research record.

STRICT BOUNDARY (Slice 1):
  * NO database, table, migration, or on-disk store. The only store here is an in-memory
    object (`InMemoryResearchStore`) for fixtures/tests. Nothing is written to any `data/`
    directory, and this module imports NO `app` symbol and performs NO file or network I/O.
  * NO route, NO UI, NO job, NO automation, NO deployment.
  * NO scoring, NO ranking, NO recommendation, NO betting guidance, NO production behavior.
    A Research Candidate is `RESEARCH_ONLY` (module constant `AUTHORITY`): zero authority.

GOVERNANCE PRINCIPLE (reviewer round 2): the OBJECTS must be incapable of representing an
invalid authoritative state. Invariants live in `__post_init__`, not only in helper functions,
so a direct constructor call cannot bypass `evaluate_family`/`summarize_family`.

Hardening applied (reviewer rounds 1-2):
  r1.1  governed mappings are deep-frozen (caller mutation cannot change a record);
  r1.2  pre-event ordering `observed_at <= bk_captured < event_effective`; outcome not before event;
  r1.3  candidate is bound to its observation's subject;
  r1.4  candidate supersession has an explicit allow-list;
  r1.5  candidate storage is append-only;
  r1.6  only MEASURED enters the matched sample / effective-n; PARTIAL counted separately;
  r1.7/r2.1  evaluation is bound to the FULL frozen endpoint contract via a content hash in the
             family identity (not just name/version);
  r1.8  SUPPORTED is direction-aware;
  r1.9/r2.B canonical numeric safety: NaN/inf rejected; `canonical_json` itself rejects non-string
             mapping keys recursively (no reliance on callers entering through `_deep_freeze`);
  r2.2  `FamilySummary` self-validates (non-neg ints, effective_n<=n_matched, bucket sum==n_eligible,
         n_eligible<=n_candidates) — fabricated summaries cannot exist;
  r2.3  `EvaluatedFinding.__post_init__` enforces the full evaluation invariants — direct
         construction cannot produce SUPPORTED without evidence or a mismatched family/summary;
  r2.4  candidate supersession is lineage-bound (same observation, prior must be current) and no
         outcome may attach to a superseded candidate;
  r2.5  `summarize_family` validates each (candidate, outcome) pair binds the same candidate_id;
  r2.A  subject/schedule corrections removed from the candidate allow-list (they need governed
         observation supersession, a later slice);
  r2.C  `record_seq` is governed store-wide (unique across observations/candidates/outcomes/findings).

The statistical FLOORS of contract §7 (exact MEPI value, power/effective-n, correction method)
are DEFERRED (contract §10 Q3) and NOT implemented here — only their structural guardrails are.
"""
from __future__ import annotations

import enum
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

AUTHORITY = "RESEARCH_ONLY"
STRUCTURAL_MIN_EFFECTIVE_N = 2  # one game cannot promote a hypothesis into an edge (§1/§7)


# --------------------------------------------------------------------------- errors
class ResearchContractError(Exception):
    """Base for every contract violation. Validators raise a subclass — never coerce."""


class TypeStrictError(ResearchContractError):
    """A value had the wrong type (incl. a coercion attempt such as str-as-number)."""


class TemporalError(ResearchContractError):
    """A datetime was naive, or a required temporal ordering did not hold."""


class EligibilityError(ResearchContractError):
    """An eligibility/invalidation rule was violated (incl. outcome-correlated exclusion)."""


class HindsightError(ResearchContractError):
    """A hindsight-prohibition rule was violated (MEPI backfill, endpoint substitution)."""


class SupersessionError(ResearchContractError):
    """A correction/supersession/storage linkage rule was violated."""


class EvaluationError(ResearchContractError):
    """A family-summary or family-evaluation invariant was violated."""


class EvaluationEngineNotGoverned(EvaluationError):
    """An evaluated CONCLUSION (SUPPORTED/UNSUPPORTED) was requested, but the governed numeric
    §7 engine and evidence-provenance layer are deferred (contract §10 Q3/Q8). Slice 1 fails
    closed: only INCONCLUSIVE may be constructed. The enum keeps SUPPORTED/UNSUPPORTED for the
    future contract, but they cannot be created until a separately approved engine derives and
    receipts the effect/interval/correction/out-of-sample/sensitivity/missingness evidence."""


class BindingError(ResearchContractError):
    """A candidate's frozen subject does not match its referenced observation."""


# --------------------------------------------------------------------------- enums
class Category(enum.Enum):
    PLAYER_MILESTONE_USAGE = "PLAYER_MILESTONE_USAGE"


class SubLabel(enum.Enum):
    BIRTHDAY = "BIRTHDAY"
    REVENGE_GAME = "REVENGE_GAME"
    RECORD_CHASE = "RECORD_CHASE"
    CONTRACT_INCENTIVE = "CONTRACT_INCENTIVE"
    HOMECOMING = "HOMECOMING"


class Direction(enum.Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class SourceUpdatedStatus(enum.Enum):
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_PROVIDED = "NOT_PROVIDED"


class Resolution(enum.Enum):
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


class Completeness(enum.Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"


class CaseTrackState(enum.Enum):
    OBSERVED = "OBSERVED"
    MEASUREMENT_DEFINED = "MEASUREMENT_DEFINED"
    OUTCOME_CAPTURED = "OUTCOME_CAPTURED"
    DESCRIPTIVE_NOTE = "DESCRIPTIVE_NOTE"


class CaseState(enum.Enum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"
    UNMEASURABLE = "UNMEASURABLE"
    INVALIDATED = "INVALIDATED"


class FamilyState(enum.Enum):
    SAMPLE_ACCUMULATING = "SAMPLE_ACCUMULATING"
    EVALUATED = "EVALUATED"


class FindingStatus(enum.Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


# --------------------------------------------------------------------------- strict helpers
def _reject_bool(value: Any, name: str) -> None:
    if isinstance(value, bool):
        raise TypeStrictError(f"{name}: bool is not an accepted value here (no coercion)")


def _check_type(value: Any, typ: type, name: str) -> None:
    if typ in (int, float):
        _reject_bool(value, name)
    if not isinstance(value, typ):
        raise TypeStrictError(
            f"{name}: expected {typ.__name__}, got {type(value).__name__} (no coercion)"
        )


def _check_real(value: Any, name: str) -> None:
    _reject_bool(value, name)
    if not isinstance(value, float):
        raise TypeStrictError(f"{name}: expected float, got {type(value).__name__} (no coercion)")
    if not math.isfinite(value):
        raise TypeStrictError(f"{name}: non-finite float (NaN/inf) is not allowed")


def _check_nonneg_int(value: Any, name: str) -> None:
    _check_type(value, int, name)
    if value < 0:
        raise TypeStrictError(f"{name}: must be a non-negative integer")


def _check_aware(value: Any, name: str) -> None:
    _check_type(value, datetime, name)
    if value.tzinfo is None or value.utcoffset() is None:
        raise TemporalError(f"{name}: datetime must be timezone-aware (naive rejected)")


def _check_nonempty_str(value: Any, name: str) -> None:
    _check_type(value, str, name)
    if not value.strip():
        raise TypeStrictError(f"{name}: must be a non-empty string")


def _str_tuple(value: Any, name: str) -> tuple:
    if isinstance(value, (str, bytes)):
        raise TypeStrictError(f"{name}: expected a sequence of strings, not a single string")
    if not isinstance(value, Sequence):
        raise TypeStrictError(f"{name}: expected a sequence, got {type(value).__name__}")
    out = []
    for i, v in enumerate(value):
        _check_nonempty_str(v, f"{name}[{i}]")
        out.append(v)
    return tuple(out)


def _deep_freeze(value: Any, name: str) -> Any:
    """Deep-copy + freeze a governed value into an immutable structure (r1.1, r1.9)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeStrictError(f"{name}: non-finite float (NaN/inf) is not allowed")
        return value
    if isinstance(value, (int, str)) or isinstance(value, enum.Enum) or isinstance(value, datetime):
        return value
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeStrictError(
                    f"{name}: mapping keys must be strings (no key coercion), got {type(k).__name__}"
                )
            out[k] = _deep_freeze(v, f"{name}.{k}")
        return MappingProxyType(out)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v, f"{name}[]") for v in value)
    raise TypeStrictError(f"{name}: cannot freeze value of type {type(value).__name__}")


# --------------------------------------------------------------------------- canonical form
def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeStrictError("non-finite float cannot be canonicalized")
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            # canonical_json must itself reject non-string keys, recursively (r2.B) — never rely
            # on the value having passed through _deep_freeze.
            if not isinstance(k, str):
                raise TypeStrictError(
                    f"canonicalize: mapping keys must be strings (no key coercion), "
                    f"got {type(k).__name__}"
                )
            out[k] = _canonicalize(v)
        return {k: out[k] for k in sorted(out)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if hasattr(value, "canonical_dict"):
        return _canonicalize(value.canonical_dict())
    raise TypeStrictError(f"cannot canonicalize value of type {type(value).__name__}")


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, fixed separators, ISO-8601 datetimes, NEVER NaN/Infinity, and
    string keys only (rejects non-string keys recursively, independent of _deep_freeze)."""
    return json.dumps(_canonicalize(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- value objects
@dataclass(frozen=True)
class EntityIdentity:
    canonical_id: str
    display: str
    resolution: Resolution = Resolution.RESOLVED

    def __post_init__(self) -> None:
        _check_nonempty_str(self.canonical_id, "entity.canonical_id")
        _check_nonempty_str(self.display, "entity.display")
        _check_type(self.resolution, Resolution, "entity.resolution")

    @property
    def is_resolved(self) -> bool:
        return self.resolution is Resolution.RESOLVED

    def canonical_dict(self) -> dict:
        return {"canonical_id": self.canonical_id, "display": self.display,
                "resolution": self.resolution.value}


@dataclass(frozen=True)
class EventIdentity:
    canonical_id: str
    event_effective: datetime

    def __post_init__(self) -> None:
        _check_nonempty_str(self.canonical_id, "event.canonical_id")
        _check_aware(self.event_effective, "event.event_effective")

    def canonical_dict(self) -> dict:
        return {"canonical_id": self.canonical_id,
                "event_effective": self.event_effective.isoformat()}


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_RESOLVER_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")


@dataclass(frozen=True)
class ResolutionEvidence:
    """Governed, non-forgeable provenance of a resolved observation (adapter Step-2 contract). It records
    HOW an owner's board selection was resolved to authoritative identity/event — the resolver + the exact
    artifact fingerprints + the bound ids + the resolution instant — so a stored observation can be audited
    and replayed. Strict + frozen: formats are validated here; the STORE additionally validates the
    registered resolver id, the player/event binding, and capture-time current-season equality, and is the
    only thing that serializes this into reserved references. It carries NO authority."""
    resolver_id: str
    resolver_version: str
    props_sha256: str
    roster_sha256: str
    roster_season: int
    event_id: str
    player_id: str
    resolved_at: datetime

    def __post_init__(self) -> None:
        _check_nonempty_str(self.resolver_id, "resolver_id")
        _check_nonempty_str(self.resolver_version, "resolver_version")
        if not _RESOLVER_VERSION_RE.match(self.resolver_version):
            raise TypeStrictError(r"resolver_version must match ^v\d+(\.\d+)*$")
        for nm, h in (("props_sha256", self.props_sha256), ("roster_sha256", self.roster_sha256)):
            _check_nonempty_str(h, nm)
            if not _HEX64_RE.match(h):
                raise TypeStrictError(f"{nm} must be 64 lowercase hex characters")
        _check_type(self.roster_season, int, "roster_season")   # _check_type rejects bool
        _check_nonempty_str(self.event_id, "event_id")
        _check_nonempty_str(self.player_id, "player_id")
        _check_aware(self.resolved_at, "resolved_at")
        if self.resolved_at.utcoffset().total_seconds() != 0:
            raise TemporalError("resolved_at must be UTC (zero offset)")

    def canonical_dict(self) -> dict:
        return {
            "resolver_id": self.resolver_id, "resolver_version": self.resolver_version,
            "props_sha256": self.props_sha256, "roster_sha256": self.roster_sha256,
            "roster_season": self.roster_season, "event_id": self.event_id,
            "player_id": self.player_id, "resolved_at": self.resolved_at.isoformat(),
        }


@dataclass(frozen=True)
class TemporalFacts:
    observed_at: datetime
    event_effective: datetime
    bk_captured: datetime
    record_seq: int
    source_updated: Optional[datetime] = None
    source_updated_status: SourceUpdatedStatus = SourceUpdatedStatus.NOT_PROVIDED

    def __post_init__(self) -> None:
        _check_aware(self.observed_at, "observed_at")
        _check_aware(self.event_effective, "event_effective")
        _check_aware(self.bk_captured, "bk_captured")
        _check_nonneg_int(self.record_seq, "record_seq")
        _check_type(self.source_updated_status, SourceUpdatedStatus, "source_updated_status")
        if self.source_updated_status is SourceUpdatedStatus.PRESENT:
            _check_aware(self.source_updated, "source_updated")
        elif self.source_updated is not None:
            raise TemporalError("source_updated must be None unless status is PRESENT (no backfill)")
        if self.bk_captured < self.observed_at:
            raise TemporalError("bk_captured must be >= observed_at (capture-before-observation)")

    @property
    def frozen_before_event(self) -> bool:
        return self.observed_at <= self.bk_captured < self.event_effective

    def canonical_dict(self) -> dict:
        return {
            "observed_at": self.observed_at.isoformat(),
            "event_effective": self.event_effective.isoformat(),
            "bk_captured": self.bk_captured.isoformat(),
            "record_seq": self.record_seq,
            "source_updated": self.source_updated.isoformat() if self.source_updated else None,
            "source_updated_status": self.source_updated_status.value,
        }


@dataclass(frozen=True)
class PrimaryEndpoint:
    name: str
    version: str
    direction: Direction
    mepi: float
    unit: str

    def __post_init__(self) -> None:
        _check_nonempty_str(self.name, "primary_endpoint.name")
        _check_nonempty_str(self.version, "primary_endpoint.version")
        _check_type(self.direction, Direction, "primary_endpoint.direction")
        _check_real(self.mepi, "primary_endpoint.mepi")
        if self.mepi <= 0.0:
            raise HindsightError("primary_endpoint.mepi must be a positive numeric MEPI")
        _check_nonempty_str(self.unit, "primary_endpoint.unit")

    def canonical_dict(self) -> dict:
        return {"name": self.name, "version": self.version, "direction": self.direction.value,
                "mepi": self.mepi, "unit": self.unit}

    @property
    def contract_hash(self) -> str:
        """sha256 over the COMPLETE endpoint contract (name+version+direction+mepi+unit)."""
        return content_hash(self)


@dataclass(frozen=True)
class BaselineMethod:
    method: str
    version: str
    covariates: tuple = ()

    def __post_init__(self) -> None:
        _check_nonempty_str(self.method, "baseline.method")
        _check_nonempty_str(self.version, "baseline.version")
        object.__setattr__(self, "covariates", _str_tuple(self.covariates, "baseline.covariates"))

    def canonical_dict(self) -> dict:
        return {"method": self.method, "version": self.version, "covariates": list(self.covariates)}


@dataclass(frozen=True)
class FamilyKey:
    """Keyed by the governed family definition — entity id is NOT part of it (§1). The endpoint is
    pinned by its COMPLETE contract hash (r2.1), so same name/version with a different direction,
    MEPI or unit is a DIFFERENT family (different question), never a silent substitution."""
    category: Category
    sub_label: SubLabel
    endpoint_name: str
    endpoint_version: str
    endpoint_contract_hash: str
    baseline_method: str
    baseline_version: str

    def __post_init__(self) -> None:
        _check_type(self.category, Category, "family.category")
        _check_type(self.sub_label, SubLabel, "family.sub_label")
        for n in ("endpoint_name", "endpoint_version", "endpoint_contract_hash",
                  "baseline_method", "baseline_version"):
            _check_nonempty_str(getattr(self, n), f"family.{n}")

    @property
    def key(self) -> str:
        return "|".join([self.category.value, self.sub_label.value, self.endpoint_name,
                         self.endpoint_version, self.endpoint_contract_hash,
                         self.baseline_method, self.baseline_version])

    def canonical_dict(self) -> dict:
        return {"category": self.category.value, "sub_label": self.sub_label.value,
                "endpoint_name": self.endpoint_name, "endpoint_version": self.endpoint_version,
                "endpoint_contract_hash": self.endpoint_contract_hash,
                "baseline_method": self.baseline_method, "baseline_version": self.baseline_version}


# --------------------------------------------------------------------------- UserObservation
@dataclass(frozen=True)
class UserObservation:
    observation_id: str
    observer: str
    entity: EntityIdentity
    event: EventIdentity
    thesis: str
    observed_at: datetime
    bk_captured: datetime
    record_seq: int
    sources: tuple = ()
    acted: bool = False
    acted_journal_ref: Optional[str] = None
    track_state: CaseTrackState = field(default=CaseTrackState.OBSERVED, init=False)

    def __post_init__(self) -> None:
        # NOTE: observation supersession/correction is DEFERRED (contract §10 Q4), so no
        # `supersedes` field exists on UserObservation — Slice 1 does not expose a fake
        # correction contract (r2-round3 #4). A correction is a governed future slice.
        _check_nonempty_str(self.observation_id, "observation_id")
        _check_nonempty_str(self.observer, "observer")
        _check_type(self.entity, EntityIdentity, "entity")
        _check_type(self.event, EventIdentity, "event")
        _check_nonempty_str(self.thesis, "thesis")
        _check_aware(self.observed_at, "observed_at")
        _check_aware(self.bk_captured, "bk_captured")
        if self.bk_captured < self.observed_at:
            raise TemporalError("bk_captured must be >= observed_at (capture-before-observation)")
        _check_nonneg_int(self.record_seq, "record_seq")
        object.__setattr__(self, "sources", _str_tuple(self.sources, "sources"))
        _check_type(self.acted, bool, "acted")
        if self.acted_journal_ref is not None:
            _check_nonempty_str(self.acted_journal_ref, "acted_journal_ref")
        if not self.acted and self.acted_journal_ref is not None:
            raise ResearchContractError("acted_journal_ref present but acted is False")

    def canonical_dict(self) -> dict:
        return {
            "observation_id": self.observation_id, "observer": self.observer,
            "entity": self.entity.canonical_dict(), "event": self.event.canonical_dict(),
            "thesis": self.thesis, "observed_at": self.observed_at.isoformat(),
            "bk_captured": self.bk_captured.isoformat(), "record_seq": self.record_seq,
            "sources": list(self.sources), "acted": self.acted,
            "acted_journal_ref": self.acted_journal_ref, "track_state": self.track_state.value,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self)


# --------------------------------------------------------------------------- ResearchCandidate
@dataclass(frozen=True)
class ResearchCandidate:
    candidate_id: str
    observation_id: str
    observer: str
    category: Category
    sub_label: SubLabel
    entity: EntityIdentity
    event: EventIdentity
    temporal: TemporalFacts
    thesis: str
    baseline: BaselineMethod
    assumptions: tuple
    eligibility_conditions: tuple
    invalidation_conditions: tuple
    primary_endpoint: Optional[PrimaryEndpoint] = None
    pre_event_snapshot: Mapping = field(default_factory=dict)
    acted: bool = False
    sources: tuple = ()
    supersedes: Optional[int] = None
    frozen_before_event: bool = field(default=False, init=False)
    track_state: CaseTrackState = field(default=CaseTrackState.MEASUREMENT_DEFINED, init=False)
    ineligibility_reasons: tuple = field(default=(), init=False)
    content_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        _check_nonempty_str(self.candidate_id, "candidate_id")
        _check_nonempty_str(self.observation_id, "observation_id")
        _check_nonempty_str(self.observer, "observer")
        _check_type(self.category, Category, "category")
        _check_type(self.sub_label, SubLabel, "sub_label")
        _check_type(self.entity, EntityIdentity, "entity")
        _check_type(self.event, EventIdentity, "event")
        _check_type(self.temporal, TemporalFacts, "temporal")
        _check_nonempty_str(self.thesis, "thesis")
        _check_type(self.baseline, BaselineMethod, "baseline")
        object.__setattr__(self, "assumptions", _str_tuple(self.assumptions, "assumptions"))
        object.__setattr__(self, "eligibility_conditions",
                           _str_tuple(self.eligibility_conditions, "eligibility_conditions"))
        object.__setattr__(self, "invalidation_conditions",
                           _str_tuple(self.invalidation_conditions, "invalidation_conditions"))
        if self.primary_endpoint is not None:
            _check_type(self.primary_endpoint, PrimaryEndpoint, "primary_endpoint")
        if not isinstance(self.pre_event_snapshot, Mapping):
            raise TypeStrictError("pre_event_snapshot: expected a mapping")
        object.__setattr__(self, "pre_event_snapshot",
                           _deep_freeze(dict(self.pre_event_snapshot), "pre_event_snapshot"))
        _check_type(self.acted, bool, "acted")
        object.__setattr__(self, "sources", _str_tuple(self.sources, "sources"))
        if self.supersedes is not None:
            _check_nonneg_int(self.supersedes, "supersedes")
        if self.temporal.event_effective != self.event.event_effective:
            raise TemporalError("temporal.event_effective must equal event.event_effective")

        frozen_before = self.temporal.frozen_before_event
        object.__setattr__(self, "frozen_before_event", frozen_before)
        reasons = []
        if not frozen_before:
            reasons.append("frozen_after_event")
        if not self.entity.is_resolved:
            reasons.append("unresolved_identity")
        if self.primary_endpoint is None:
            reasons.append("no_frozen_numeric_mepi")
        object.__setattr__(self, "ineligibility_reasons", tuple(reasons))
        object.__setattr__(
            self, "track_state",
            CaseTrackState.DESCRIPTIVE_NOTE if not frozen_before else CaseTrackState.MEASUREMENT_DEFINED,
        )
        object.__setattr__(self, "content_hash", content_hash(self))

    @property
    def eligible_for_sample(self) -> bool:
        return not self.ineligibility_reasons

    @property
    def family_key(self) -> Optional[FamilyKey]:
        if self.primary_endpoint is None:
            return None
        return FamilyKey(self.category, self.sub_label, self.primary_endpoint.name,
                         self.primary_endpoint.version, self.primary_endpoint.contract_hash,
                         self.baseline.method, self.baseline.version)

    @property
    def case_identity(self) -> str:
        return "|".join([self.entity.canonical_id, self.event.canonical_id, self.content_hash])

    def canonical_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id, "observation_id": self.observation_id,
            "observer": self.observer, "category": self.category.value,
            "sub_label": self.sub_label.value, "entity": self.entity.canonical_dict(),
            "event": self.event.canonical_dict(), "temporal": self.temporal.canonical_dict(),
            "thesis": self.thesis, "baseline": self.baseline.canonical_dict(),
            "assumptions": list(self.assumptions),
            "eligibility_conditions": list(self.eligibility_conditions),
            "invalidation_conditions": list(self.invalidation_conditions),
            "primary_endpoint": self.primary_endpoint.canonical_dict() if self.primary_endpoint else None,
            "pre_event_snapshot": {k: _canonicalize(v) for k, v in self.pre_event_snapshot.items()},
            "acted": self.acted, "sources": list(self.sources), "supersedes": self.supersedes,
        }


# subject/schedule corrections need governed OBSERVATION supersession (a later slice), so they are
# NOT in this allow-list — only the measurement plan/baseline may be corrected pre-event (r2.A).
_SUPERSEDE_ALLOWED = frozenset({"candidate_id", "baseline", "primary_endpoint"})


def supersede_candidate(prior: ResearchCandidate, *, new_temporal: TemporalFacts,
                        **changes: Any) -> ResearchCandidate:
    """Produce a NEW candidate correcting `prior`, linked by record_seq (§6). Only the explicit
    allow-list {candidate_id, baseline, primary_endpoint} may change; any other key is rejected.
    A numeric MEPI may NEVER be backfilled post-event (Rev 2.1 #4, §5)."""
    _check_type(prior, ResearchCandidate, "prior")
    _check_type(new_temporal, TemporalFacts, "new_temporal")
    unknown = set(changes) - _SUPERSEDE_ALLOWED
    if unknown:
        raise SupersessionError(f"supersede_candidate: fields not in the allow-list: {sorted(unknown)}")
    if new_temporal.record_seq <= prior.temporal.record_seq:
        raise SupersessionError("a superseding candidate needs a strictly greater record_seq")

    new_endpoint = changes.get("primary_endpoint", prior.primary_endpoint)
    new_baseline = changes.get("baseline", prior.baseline)
    adding_or_changing_mepi = (new_endpoint is not None
                               and (prior.primary_endpoint is None
                                    or new_endpoint != prior.primary_endpoint))
    changing_plan = adding_or_changing_mepi or (new_baseline != prior.baseline)
    # the WHOLE frozen measurement plan (endpoint/MEPI AND baseline) is pre-registration; none of
    # it may be backfilled with a capture at/after the event (r2-round3 hindsight check, §5).
    if changing_plan and new_temporal.bk_captured >= new_temporal.event_effective:
        raise HindsightError(
            "the frozen measurement plan (endpoint/MEPI or baseline) cannot be added or changed "
            "with a capture at/after the event (would manufacture pre-registration, §5)"
        )

    return ResearchCandidate(
        candidate_id=changes.get("candidate_id", prior.candidate_id + "+corr"),
        observation_id=prior.observation_id, observer=prior.observer, category=prior.category,
        sub_label=prior.sub_label, entity=prior.entity, event=prior.event, temporal=new_temporal,
        thesis=prior.thesis, baseline=changes.get("baseline", prior.baseline),
        assumptions=prior.assumptions, eligibility_conditions=prior.eligibility_conditions,
        invalidation_conditions=prior.invalidation_conditions, primary_endpoint=new_endpoint,
        pre_event_snapshot=dict(prior.pre_event_snapshot), acted=prior.acted, sources=prior.sources,
        supersedes=prior.temporal.record_seq,
    )


def bind_candidate_to_observation(candidate: ResearchCandidate, observation: UserObservation) -> None:
    """A candidate must not claim an observation id while changing its subject (r1.3)."""
    if candidate.observation_id != observation.observation_id:
        raise BindingError("candidate.observation_id does not reference this observation")
    mismatches = []
    if candidate.observer != observation.observer:
        mismatches.append("observer")
    if candidate.entity != observation.entity:
        mismatches.append("entity")
    if candidate.event != observation.event:
        mismatches.append("event")
    if candidate.thesis != observation.thesis:
        mismatches.append("thesis")
    if candidate.acted != observation.acted:
        mismatches.append("acted")
    if not set(observation.sources).issubset(set(candidate.sources)):
        mismatches.append("sources(lineage)")
    if mismatches:
        raise BindingError(
            f"candidate does not match its observation on: {mismatches} "
            f"(bind the subject, or record a governed correction instead)"
        )


# --------------------------------------------------------------------------- CandidateOutcome
@dataclass(frozen=True)
class CandidateOutcome:
    outcome_id: str
    candidate_id: str
    version: int
    case_state: CaseState
    bk_captured: datetime
    record_seq: int
    observed_endpoint_value: Optional[float] = None
    baseline_expected_value: Optional[float] = None
    completeness: Mapping = field(default_factory=dict)
    covariates: Mapping = field(default_factory=dict)
    descriptive: Mapping = field(default_factory=dict)
    measurement_receipt_ref: Optional[str] = None
    invalidation_reason: Optional[str] = None
    supersedes: Optional[int] = None

    def __post_init__(self) -> None:
        _check_nonempty_str(self.outcome_id, "outcome_id")
        _check_nonempty_str(self.candidate_id, "candidate_id")
        _check_type(self.version, int, "version")
        if self.version < 1:
            raise TypeStrictError("version must be >= 1")
        _check_type(self.case_state, CaseState, "case_state")
        _check_aware(self.bk_captured, "bk_captured")
        _check_nonneg_int(self.record_seq, "record_seq")
        if self.observed_endpoint_value is not None:
            _check_real(self.observed_endpoint_value, "observed_endpoint_value")
        if self.baseline_expected_value is not None:
            _check_real(self.baseline_expected_value, "baseline_expected_value")
        for nm, m in (("completeness", self.completeness), ("covariates", self.covariates),
                      ("descriptive", self.descriptive)):
            if not isinstance(m, Mapping):
                raise TypeStrictError(f"{nm}: expected a mapping")
        for k, v in self.completeness.items():
            _check_type(v, Completeness, f"completeness[{k}]")
        object.__setattr__(self, "completeness", _deep_freeze(dict(self.completeness), "completeness"))
        object.__setattr__(self, "covariates", _deep_freeze(dict(self.covariates), "covariates"))
        object.__setattr__(self, "descriptive", _deep_freeze(dict(self.descriptive), "descriptive"))
        if self.measurement_receipt_ref is not None:
            _check_nonempty_str(self.measurement_receipt_ref, "measurement_receipt_ref")
        if self.supersedes is not None:
            _check_nonneg_int(self.supersedes, "supersedes")
        self._validate_case_state()

    def _validate_case_state(self) -> None:
        st = self.case_state
        both_present = (self.observed_endpoint_value is not None
                        and self.baseline_expected_value is not None)
        any_unresolved = any(v is not Completeness.COMPLETE for v in self.completeness.values())
        if st is CaseState.MEASURED:
            if not both_present:
                raise EligibilityError("MEASURED requires observed + baseline endpoint values")
            if not self.completeness or any_unresolved:
                raise EligibilityError("MEASURED requires every variable COMPLETE")
            if self.invalidation_reason is not None:
                raise EligibilityError("MEASURED must not carry an invalidation_reason")
        elif st is CaseState.PARTIAL:
            if not any_unresolved:
                raise EligibilityError("PARTIAL requires at least one PARTIAL/PENDING variable")
            if self.invalidation_reason is not None:
                raise EligibilityError("PARTIAL must not carry an invalidation_reason")
        elif st is CaseState.PENDING:
            if self.observed_endpoint_value is not None:
                raise EligibilityError("PENDING must not carry a measured endpoint value")
            if self.invalidation_reason is not None:
                raise EligibilityError("PENDING must not carry an invalidation_reason")
        elif st is CaseState.UNMEASURABLE:
            if self.observed_endpoint_value is not None:
                raise EligibilityError("UNMEASURABLE must not carry a measured endpoint value")
            if not self.invalidation_reason:
                raise EligibilityError("UNMEASURABLE requires a stated unmeasurable reason")
        elif st is CaseState.INVALIDATED:
            if not self.invalidation_reason:
                raise EligibilityError("INVALIDATED requires an eligibility-failure reason")

    def validate_invalidation_against_candidate(self, candidate: "ResearchCandidate") -> None:
        if self.case_state is not CaseState.INVALIDATED:
            return
        reason = self.invalidation_reason
        frozen = set(candidate.eligibility_conditions) | set(candidate.invalidation_conditions)
        if reason not in frozen:
            raise EligibilityError(
                f"INVALIDATED reason {reason!r} is not one of the candidate's FROZEN pre-event "
                f"eligibility/invalidation conditions"
            )
        if reason in set(candidate.baseline.covariates):
            raise EligibilityError(
                f"INVALIDATED reason {reason!r} is a predeclared covariate — outcome-correlated "
                f"exclusion is prohibited (it is a covariate, not an invalidation)"
            )

    @property
    def lift(self) -> Optional[float]:
        if self.observed_endpoint_value is None or self.baseline_expected_value is None:
            return None
        return self.observed_endpoint_value - self.baseline_expected_value

    @property
    def counts_in_matched_sample(self) -> bool:
        return self.case_state is CaseState.MEASURED

    @property
    def counts_in_partial(self) -> bool:
        return self.case_state is CaseState.PARTIAL

    @property
    def counts_in_missingness(self) -> bool:
        return self.case_state in (CaseState.PENDING, CaseState.UNMEASURABLE)

    def canonical_dict(self) -> dict:
        return {
            "outcome_id": self.outcome_id, "candidate_id": self.candidate_id,
            "version": self.version, "case_state": self.case_state.value,
            "bk_captured": self.bk_captured.isoformat(), "record_seq": self.record_seq,
            "observed_endpoint_value": self.observed_endpoint_value,
            "baseline_expected_value": self.baseline_expected_value,
            "completeness": {k: v.value for k, v in self.completeness.items()},
            "covariates": {k: _canonicalize(v) for k, v in self.covariates.items()},
            "descriptive": {k: _canonicalize(v) for k, v in self.descriptive.items()},
            "measurement_receipt_ref": self.measurement_receipt_ref,
            "invalidation_reason": self.invalidation_reason, "supersedes": self.supersedes,
        }


# --------------------------------------------------------------------------- family summary
@dataclass(frozen=True)
class FamilySummary:
    """A self-validating count of a family's cases (r2.2). An inconsistent or fabricated summary
    CANNOT be constructed, so it cannot be passed to an evaluation to manufacture a finding."""
    family_key: FamilyKey
    n_candidates: int
    n_eligible: int
    effective_n: int           # distinct entities among MEASURED cases only
    n_matched: int             # MEASURED only
    n_partial: int
    n_pending: int
    n_unmeasurable: int
    n_invalidated: int

    def __post_init__(self) -> None:
        _check_type(self.family_key, FamilyKey, "family_key")
        for n in ("n_candidates", "n_eligible", "effective_n", "n_matched", "n_partial",
                  "n_pending", "n_unmeasurable", "n_invalidated"):
            _check_nonneg_int(getattr(self, n), n)
        if self.effective_n > self.n_matched:
            raise EvaluationError("effective_n cannot exceed n_matched")
        bucket_sum = (self.n_matched + self.n_partial + self.n_pending
                      + self.n_unmeasurable + self.n_invalidated)
        if bucket_sum != self.n_eligible:
            raise EvaluationError(
                f"state buckets ({bucket_sum}) must sum to n_eligible ({self.n_eligible})"
            )
        if self.n_eligible > self.n_candidates:
            raise EvaluationError("n_eligible cannot exceed n_candidates")

    def canonical_dict(self) -> dict:
        d = {"family_key": self.family_key.key}
        d.update({k: getattr(self, k) for k in
                  ("n_candidates", "n_eligible", "effective_n", "n_matched", "n_partial",
                   "n_pending", "n_unmeasurable", "n_invalidated")})
        return d


def summarize_family(family_key: FamilyKey, cases: Sequence[tuple]) -> FamilySummary:
    """cases: sequence of (ResearchCandidate, current CandidateOutcome | None)."""
    _check_type(family_key, FamilyKey, "family_key")
    n_candidates = n_eligible = n_matched = n_partial = n_pending = n_unmeasurable = n_invalidated = 0
    matched_entities = set()
    for cand, outcome in cases:
        _check_type(cand, ResearchCandidate, "case candidate")
        if cand.family_key is None or cand.family_key.key != family_key.key:
            raise EvaluationError("a case does not belong to this family key")
        if outcome is not None:
            _check_type(outcome, CandidateOutcome, "case outcome")
            if outcome.candidate_id != cand.candidate_id:
                raise EvaluationError(
                    "case/outcome pairing mismatch: outcome.candidate_id != candidate.candidate_id"
                )
        n_candidates += 1
        if not cand.eligible_for_sample:
            continue
        n_eligible += 1
        if outcome is None:
            n_pending += 1
            continue
        if outcome.case_state is CaseState.INVALIDATED:
            n_invalidated += 1
        elif outcome.counts_in_matched_sample:
            n_matched += 1
            matched_entities.add(cand.entity.canonical_id)
        elif outcome.counts_in_partial:
            n_partial += 1
        elif outcome.case_state is CaseState.PENDING:
            n_pending += 1
        elif outcome.case_state is CaseState.UNMEASURABLE:
            n_unmeasurable += 1
    return FamilySummary(family_key, n_candidates, n_eligible, len(matched_entities),
                         n_matched, n_partial, n_pending, n_unmeasurable, n_invalidated)


@dataclass(frozen=True)
class EvidenceBundle:
    effect_estimate: float
    interval_low: float
    interval_high: float
    corrected_interval_low: float
    corrected_interval_high: float
    out_of_sample: bool
    sensitivity_analysis_done: bool
    missingness_rule: str

    def __post_init__(self) -> None:
        for n in ("effect_estimate", "interval_low", "interval_high",
                  "corrected_interval_low", "corrected_interval_high"):
            _check_real(getattr(self, n), n)
        _check_type(self.out_of_sample, bool, "out_of_sample")
        _check_type(self.sensitivity_analysis_done, bool, "sensitivity_analysis_done")
        _check_nonempty_str(self.missingness_rule, "missingness_rule")
        if self.interval_low > self.interval_high:
            raise EvaluationError("interval_low must be <= interval_high")
        if self.corrected_interval_low > self.corrected_interval_high:
            raise EvaluationError("corrected_interval_low must be <= corrected_interval_high")

    def canonical_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "effect_estimate", "interval_low", "interval_high", "corrected_interval_low",
            "corrected_interval_high", "out_of_sample", "sensitivity_analysis_done",
            "missingness_rule")}


def _require_supported(endpoint: PrimaryEndpoint, ev: EvidenceBundle) -> None:
    """NON-AUTHORITATIVE SPECIFICATION — refuses on its own (reviewer note, Slice-1 close).

    This is reference text for a FUTURE governed engine, not a usable check. It is unreachable in
    Slice 1 (constructing SUPPORTED/UNSUPPORTED already fails closed in EvaluatedFinding), and it is
    deliberately NOT independently activatable: removing the fail-closed exception elsewhere must
    NOT turn this into a working evaluator. The eventual numeric engine MUST arrive as its own
    versioned policy with an evidence-provenance contract — so this stub raises unconditionally.

    Intended future bar (direction-aware, for reference only): INCREASE requires effect >= MEPI with
    the corrected interval clearing both zero and the MEPI; DECREASE mirrors it on the upper bound;
    out-of-sample performance and a sensitivity analysis are required; statistical significance
    alone never yields SUPPORTED (§7)."""
    raise EvaluationEngineNotGoverned(
        "_require_supported is non-authoritative specification code and cannot be used to grade an "
        "evidence bundle — the governed numeric engine must arrive with its own versioned policy "
        "and evidence-provenance contract (not by removing a fail-closed exception)"
    )


@dataclass(frozen=True)
class EvaluatedFinding:
    """The verdict over a matched sample. IMMUTABLE and self-validating (r2.3): the constructor
    enforces the full evaluation invariants, so direct construction cannot produce a mismatched
    family/summary or an endpoint that does not match the family's frozen contract. Still
    RESEARCH_ONLY (§7).

    FAIL CLOSED (r3): because the governed numeric engine + evidence provenance are deferred, an
    evaluated CONCLUSION cannot be constructed — only `INCONCLUSIVE` is representable. Requesting
    `SUPPORTED`/`UNSUPPORTED` raises `EvaluationEngineNotGoverned`."""
    finding_id: str
    family_key: FamilyKey
    status: FindingStatus
    summary: FamilySummary
    endpoint: PrimaryEndpoint
    bk_captured: datetime
    record_seq: int
    evidence: Optional[EvidenceBundle] = None
    supersedes: Optional[int] = None
    authority: str = field(default=AUTHORITY, init=False)
    content_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        _check_nonempty_str(self.finding_id, "finding_id")
        _check_type(self.family_key, FamilyKey, "family_key")
        _check_type(self.status, FindingStatus, "status")
        _check_type(self.summary, FamilySummary, "summary")
        _check_type(self.endpoint, PrimaryEndpoint, "endpoint")
        _check_aware(self.bk_captured, "bk_captured")
        _check_nonneg_int(self.record_seq, "record_seq")
        if self.supersedes is not None:
            _check_nonneg_int(self.supersedes, "supersedes")
        if self.evidence is not None:
            _check_type(self.evidence, EvidenceBundle, "evidence")

        # family identity binding — the finding, its summary and its endpoint must all agree.
        if self.family_key.key != self.summary.family_key.key:
            raise EvaluationError("finding.family_key must equal summary.family_key")
        if self.endpoint.contract_hash != self.family_key.endpoint_contract_hash:
            raise EvaluationError(
                "endpoint contract does not match the family identity (no endpoint substitution)"
            )
        # FAIL CLOSED: an evaluated conclusion cannot be constructed until the governed numeric
        # engine + evidence provenance exist (contract §10 Q3/Q8). Caller-supplied EvidenceBundle
        # values are unverified, so two cases plus a hand-built bundle must NOT yield SUPPORTED.
        # Only INCONCLUSIVE is representable in Slice 1 (the structural floor, direction-aware bar
        # and evidence checks live in the future engine, see `_require_supported`).
        if self.status is not FindingStatus.INCONCLUSIVE:
            raise EvaluationEngineNotGoverned(
                f"cannot construct an evaluated conclusion ({self.status.value}) in Slice 1 — the "
                f"governed numeric evaluation engine and evidence provenance are deferred; only "
                f"INCONCLUSIVE is permitted"
            )
        object.__setattr__(self, "content_hash", content_hash(self))

    def canonical_dict(self) -> dict:
        return {
            "finding_id": self.finding_id, "family_key": self.family_key.key,
            "status": self.status.value, "summary": self.summary.canonical_dict(),
            "endpoint": self.endpoint.canonical_dict(),
            "bk_captured": self.bk_captured.isoformat(), "record_seq": self.record_seq,
            "evidence": self.evidence.canonical_dict() if self.evidence else None,
            "supersedes": self.supersedes, "authority": self.authority,
        }


def evaluate_family(*, finding_id: str, endpoint: PrimaryEndpoint, summary: FamilySummary,
                    proposed_status: FindingStatus, bk_captured: datetime, record_seq: int,
                    evidence: Optional[EvidenceBundle] = None,
                    supersedes: Optional[int] = None) -> EvaluatedFinding:
    """Ergonomic factory. All governance lives in `EvaluatedFinding.__post_init__`, so this is a
    thin constructor call — a direct `EvaluatedFinding(...)` is equally safe (r2.3)."""
    return EvaluatedFinding(
        finding_id=finding_id, family_key=summary.family_key, status=proposed_status,
        summary=summary, endpoint=endpoint, bk_captured=bk_captured, record_seq=record_seq,
        evidence=evidence, supersedes=supersedes,
    )


# --------------------------------------------------------------------------- in-memory store
class InMemoryResearchStore:
    """Isolated, process-local store for fixtures/tests ONLY. Writes NOTHING to disk.

    `record_seq` is governed STORE-WIDE (r2.C): it is unique across observations, candidates,
    outcomes and findings, giving one immutable monotonic ordering key for the whole store.
    """

    def __init__(self) -> None:
        self._max_claimed = 0        # highest record_seq actually stored (strict monotonic claim)
        self._max_allocated = 0      # highest record_seq handed out by next_seq OR claimed
        self.observations: dict = {}
        self.candidates: dict = {}
        self._candidate_by_seq: dict = {}
        self._superseded_candidate_seqs: set = set()
        self._current_by_obs: dict = {}         # observation_id -> current ResearchCandidate
        self._outcome_versions: dict = {}
        self._finding_versions: dict = {}

    def next_seq(self) -> int:
        # ALLOCATING (r3 #3): reserves and returns a fresh sequence strictly above everything seen,
        # so two consecutive calls never return the same value; preserves strict monotonicity when
        # an externally supplied sequence has advanced the maximum.
        self._max_allocated = max(self._max_allocated, self._max_claimed) + 1
        return self._max_allocated

    def _claim_seq(self, seq: int) -> None:
        # store-wide record_seq is strictly MONOTONIC among CLAIMED records: every new record, of
        # any kind, must carry a sequence greater than every sequence claimed before it.
        if seq <= self._max_claimed:
            raise SupersessionError(
                f"record_seq {seq} must be strictly greater than the max claimed "
                f"({self._max_claimed}) — store-wide monotonic ordering"
            )
        self._max_claimed = seq
        if seq > self._max_allocated:
            self._max_allocated = seq

    # observations -----------------------------------------------------------
    def record_observation(self, obs: UserObservation) -> UserObservation:
        _check_type(obs, UserObservation, "obs")
        if obs.observation_id in self.observations:
            raise SupersessionError("observation_id already recorded; corrections supersede by id")
        self._claim_seq(obs.record_seq)
        self.observations[obs.observation_id] = obs
        return obs

    # candidates -------------------------------------------------------------
    def freeze_candidate(self, cand: ResearchCandidate) -> ResearchCandidate:
        _check_type(cand, ResearchCandidate, "cand")
        obs = self.observations.get(cand.observation_id)
        if obs is None:
            raise ResearchContractError("cannot freeze a candidate for an unknown observation")
        bind_candidate_to_observation(cand, obs)
        if cand.candidate_id in self.candidates:
            raise SupersessionError("duplicate candidate_id (storage is append-only)")
        # exactly ONE current candidate per observation lineage (r2-round3 #2): a second candidate
        # for an observation that already has one MUST supersede the current one.
        current = self._current_by_obs.get(cand.observation_id)
        if current is not None and cand.supersedes is None:
            raise SupersessionError(
                "a second candidate in this observation lineage must supersede the current one"
            )
        prior = None
        if cand.supersedes is not None:
            prior = self._candidate_by_seq.get(cand.supersedes)
            if prior is None:
                raise SupersessionError("superseded candidate record_seq is unknown")
            if prior.observation_id != cand.observation_id:
                raise SupersessionError("supersession must stay within the same observation lineage")
            if not self.is_current_candidate(prior):
                raise SupersessionError("can only supersede the current candidate in the lineage")
            if current is not None and prior.temporal.record_seq != current.temporal.record_seq:
                raise SupersessionError("must supersede the CURRENT candidate of the lineage")
            if cand.temporal.record_seq <= prior.temporal.record_seq:
                raise SupersessionError("a superseding candidate needs a greater record_seq")
            # a post-event / ineligible correction must NOT silently replace an eligible candidate
            # and drop it from the evaluated family (r2-round3 hindsight check).
            if prior.eligible_for_sample and not cand.eligible_for_sample:
                raise SupersessionError(
                    "an ineligible (e.g. post-event) correction cannot supersede an eligible "
                    "candidate — that would silently remove it from the evaluated family"
                )
        self._claim_seq(cand.temporal.record_seq)
        if prior is not None:
            self._superseded_candidate_seqs.add(prior.temporal.record_seq)
        self.candidates[cand.candidate_id] = cand
        self._candidate_by_seq[cand.temporal.record_seq] = cand
        self._current_by_obs[cand.observation_id] = cand
        return cand

    def is_current_candidate(self, cand: ResearchCandidate) -> bool:
        return cand.temporal.record_seq not in self._superseded_candidate_seqs

    # outcomes ---------------------------------------------------------------
    def append_outcome(self, outcome: CandidateOutcome) -> CandidateOutcome:
        _check_type(outcome, CandidateOutcome, "outcome")
        cand = self.candidates.get(outcome.candidate_id)
        if cand is None:
            raise ResearchContractError("cannot attach an outcome to an unknown candidate")
        if not self.is_current_candidate(cand):
            raise SupersessionError("cannot attach an outcome to a superseded candidate")
        if outcome.bk_captured < cand.event.event_effective:
            raise TemporalError("outcome bk_captured precedes the event (not yet effective)")
        outcome.validate_invalidation_against_candidate(cand)
        chain = self._outcome_versions.setdefault(outcome.candidate_id, [])
        if chain:
            prior = chain[-1]
            if outcome.version != prior.version + 1:
                raise SupersessionError("outcome version must increment by exactly 1")
            if outcome.supersedes != prior.record_seq:
                raise SupersessionError("a new outcome version must supersede the prior record_seq")
            if outcome.record_seq <= prior.record_seq:
                raise SupersessionError("a superseding outcome needs a greater record_seq")
        else:
            if outcome.version != 1:
                raise SupersessionError("first outcome version must be 1")
            if outcome.supersedes is not None:
                raise SupersessionError("first outcome version supersedes nothing")
        self._claim_seq(outcome.record_seq)
        chain.append(outcome)
        return outcome

    def current_outcome(self, candidate_id: str) -> Optional[CandidateOutcome]:
        chain = self._outcome_versions.get(candidate_id)
        return chain[-1] if chain else None

    def outcome_history(self, candidate_id: str) -> tuple:
        return tuple(self._outcome_versions.get(candidate_id, ()))

    # findings ---------------------------------------------------------------
    def record_finding(self, finding: EvaluatedFinding) -> EvaluatedFinding:
        _check_type(finding, EvaluatedFinding, "finding")
        # FINDING PROVENANCE (r2-round3 #3): a self-consistent summary is not enough — it must be
        # the summary the store's OWN current family cases produce right now. Recompute and require
        # exact equality, so a hand-built finding about a fabricated/unknown/empty family is rejected.
        cases = self.family_cases(finding.family_key)
        # a finding requires a family that actually exists here — an invented research family (no
        # stored candidate) is different from a genuinely empty rendered board (r3 #2).
        if not cases:
            raise EvaluationError(
                "no stored candidate in this family — a finding cannot be recorded for a "
                "nonexistent/invented research family"
            )
        recomputed = summarize_family(finding.family_key, cases)
        if content_hash(recomputed) != content_hash(finding.summary):
            raise EvaluationError(
                "finding.summary does not match the store's current family cases "
                "(finding provenance: counts must be derived from the stored cases)"
            )
        chain = self._finding_versions.setdefault(finding.family_key.key, [])
        if chain:
            prior = chain[-1]
            if finding.supersedes != prior.record_seq:
                raise SupersessionError("a re-evaluation must supersede the prior finding record_seq")
            if finding.record_seq <= prior.record_seq:
                raise SupersessionError("a superseding finding needs a greater record_seq")
        else:
            if finding.supersedes is not None:
                raise SupersessionError("first finding supersedes nothing")
        self._claim_seq(finding.record_seq)
        chain.append(finding)
        return finding

    def current_finding(self, family_key: FamilyKey) -> Optional[EvaluatedFinding]:
        chain = self._finding_versions.get(family_key.key)
        return chain[-1] if chain else None

    def family_cases(self, family_key: FamilyKey) -> list:
        out = []
        for cand in self.candidates.values():
            if not self.is_current_candidate(cand):
                continue
            fk = cand.family_key
            if fk is not None and fk.key == family_key.key:
                out.append((cand, self.current_outcome(cand.candidate_id)))
        return out


__all__ = [
    "AUTHORITY", "STRUCTURAL_MIN_EFFECTIVE_N",
    "ResearchContractError", "TypeStrictError", "TemporalError", "EligibilityError",
    "HindsightError", "SupersessionError", "EvaluationError", "EvaluationEngineNotGoverned",
    "BindingError",
    "Category", "SubLabel", "Direction", "SourceUpdatedStatus", "Resolution", "Completeness",
    "CaseTrackState", "CaseState", "FamilyState", "FindingStatus",
    "EntityIdentity", "EventIdentity", "ResolutionEvidence", "TemporalFacts", "PrimaryEndpoint", "BaselineMethod",
    "FamilyKey", "UserObservation", "ResearchCandidate", "supersede_candidate",
    "bind_candidate_to_observation", "CandidateOutcome", "FamilySummary", "summarize_family",
    "EvidenceBundle", "EvaluatedFinding", "evaluate_family", "InMemoryResearchStore",
    "canonical_json", "content_hash",
]
