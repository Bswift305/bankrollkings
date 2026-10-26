"""Research Candidate — governed domain contract + validators (SLICE 1, DARK/LOCAL).

Implements the approved design `docs/research_candidate_contract.md` (Rev 2.1): the object
model and lifecycle that turns a human observation into an honestly testable research record.

STRICT BOUNDARY (Slice 1):
  * NO database, table, migration, or on-disk store. The only store here is an in-memory
    object (`InMemoryResearchStore`) for fixtures/tests. Nothing is written to any `data/`
    directory, and this module imports NO `app` symbol and performs NO file or network I/O.
  * NO route, NO UI, NO job, NO automation, NO deployment.
  * NO scoring, NO ranking, NO recommendation, NO betting guidance, NO production behavior.
    A Research Candidate is `RESEARCH_ONLY` (module constant `AUTHORITY`): zero authority. It
    MUST NOT influence the factual boards, Green Light, rankings, tickets, Daily Cards, or any
    governed model — not its score, not its sort order, not its membership.

What Slice 1 covers (reviewer scope): UserObservation; ResearchCandidate; immutable pre-event
thesis + assumptions; eligibility/invalidation conditions; the frozen measurement plan + MEPI;
case states PENDING/PARTIAL/MEASURED/UNMEASURABLE and eligibility-only INVALIDATED; the
immutable EvaluatedFinding incl. INCONCLUSIVE; supersession linkage. Validators enforce: strict
typed inputs with no coercion; tz-aware observation + event clocks; pre-event eligibility; MEPI
never backfilled; measurement failure becomes a counted UNMEASURABLE (never silently excluded);
one game cannot promote a hypothesis into an edge; deterministic canonical serialization + hashes.

The statistical floors of contract §7 (exact MEPI value, power/effective-n, correction method)
are DEFERRED (contract §10 Q3) and NOT implemented here — Slice 1 encodes only the structural
guardrails around them.
"""
from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

# This module grants zero authority. It is referenced in QC to prove nothing here ranks/scores.
AUTHORITY = "RESEARCH_ONLY"

# A purely STRUCTURAL floor: an effect can never be declared from fewer than two independent
# cases ("one game cannot promote a hypothesis into an edge", contract §1/§7). The real
# statistical floors (power, MEPI value, correction) are deferred to a separate analysis (§10 Q3).
STRUCTURAL_MIN_EFFECTIVE_N = 2


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
    """A correction/supersession linkage rule was violated."""


class EvaluationError(ResearchContractError):
    """A family-evaluation guardrail was violated (e.g. an edge from a single case)."""


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
    """Per-case lifecycle (contract §2)."""
    OBSERVED = "OBSERVED"
    MEASUREMENT_DEFINED = "MEASUREMENT_DEFINED"
    OUTCOME_CAPTURED = "OUTCOME_CAPTURED"
    # A candidate frozen AFTER the event (or without the full §3 set) is permanently this —
    # never a graded candidate; it can seed context only.
    DESCRIPTIVE_NOTE = "DESCRIPTIVE_NOTE"


class CaseState(enum.Enum):
    """Descriptive state of ONE case's measurement (contract §4) — NOT a win/loss grade."""
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"
    # event was ELIGIBLE but the endpoint cannot be measured (data does not exist): COUNTED,
    # enters the missingness analysis — it is NOT INVALIDATED (Rev 2.1 #1).
    UNMEASURABLE = "UNMEASURABLE"
    # reserved SOLELY for a frozen pre-event eligibility failure (contract §2).
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
    # bool is a subclass of int in Python; a bool where a number/str is wanted is a coercion bug.
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
    """A strict real number: a float (not int, not bool, not a numeric string)."""
    _reject_bool(value, name)
    if not isinstance(value, float):
        raise TypeStrictError(f"{name}: expected float, got {type(value).__name__} (no coercion)")


def _check_aware(value: Any, name: str) -> None:
    _check_type(value, datetime, name)
    if value.tzinfo is None or value.utcoffset() is None:
        raise TemporalError(f"{name}: datetime must be timezone-aware (naive rejected)")


def _check_nonempty_str(value: Any, name: str) -> None:
    _check_type(value, str, name)
    if not value.strip():
        raise TypeStrictError(f"{name}: must be a non-empty string")


def _str_tuple(value: Any, name: str) -> tuple:
    """Normalize a sequence of strings to a tuple (container shape, not value coercion)."""
    if isinstance(value, (str, bytes)):
        raise TypeStrictError(f"{name}: expected a sequence of strings, not a single string")
    if not isinstance(value, Sequence):
        raise TypeStrictError(f"{name}: expected a sequence, got {type(value).__name__}")
    out = []
    for i, v in enumerate(value):
        _check_nonempty_str(v, f"{name}[{i}]")
        out.append(v)
    return tuple(out)


def _check_seq_int(value: Any, name: str) -> None:
    _check_type(value, int, name)
    if value < 0:
        raise TypeStrictError(f"{name}: record_seq must be >= 0")


# --------------------------------------------------------------------------- canonical form
def _canonicalize(value: Any) -> Any:
    """Deterministic, JSON-safe projection used for content hashing + serialization."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _canonicalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if hasattr(value, "canonical_dict"):
        return _canonicalize(value.canonical_dict())
    raise TypeStrictError(f"cannot canonicalize value of type {type(value).__name__}")


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, fixed separators, ISO-8601 datetimes."""
    return json.dumps(_canonicalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
    event_effective: datetime  # the event's own clock (kickoff / first pitch), tz-aware

    def __post_init__(self) -> None:
        _check_nonempty_str(self.canonical_id, "event.canonical_id")
        _check_aware(self.event_effective, "event.event_effective")

    def canonical_dict(self) -> dict:
        return {"canonical_id": self.canonical_id,
                "event_effective": self.event_effective.isoformat()}


@dataclass(frozen=True)
class TemporalFacts:
    """The four distinct temporal concepts (contract §3). No clock is substituted for another."""
    observed_at: datetime                      # 1. human-observation clock (tz-aware)
    event_effective: datetime                  # 3. the event's own clock (tz-aware)
    bk_captured: datetime                      # 4. BK ingestion clock (tz-aware)
    record_seq: int                            #    + immutable monotonic ordering key (§6)
    source_updated: Optional[datetime] = None  # 2. provider clock (tz-aware) or null
    source_updated_status: SourceUpdatedStatus = SourceUpdatedStatus.NOT_PROVIDED

    def __post_init__(self) -> None:
        _check_aware(self.observed_at, "observed_at")
        _check_aware(self.event_effective, "event_effective")
        _check_aware(self.bk_captured, "bk_captured")
        _check_seq_int(self.record_seq, "record_seq")
        _check_type(self.source_updated_status, SourceUpdatedStatus, "source_updated_status")
        if self.source_updated_status is SourceUpdatedStatus.PRESENT:
            _check_aware(self.source_updated, "source_updated")
        else:
            # UNKNOWN / NOT_PROVIDED ⇒ null, never backfilled (contract §3 clock 2).
            if self.source_updated is not None:
                raise TemporalError(
                    "source_updated must be None unless source_updated_status is PRESENT "
                    "(never backfill a provider clock)"
                )

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
    """The ONE pre-registered measurement, with direction + numeric MEPI (contract §3/§7)."""
    name: str
    version: str
    direction: Direction
    mepi: float          # minimum effect of practical interest — REQUIRED, frozen, > 0
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


@dataclass(frozen=True)
class BaselineMethod:
    """How 'expected' is computed, incl. predeclared covariates (game script lives here)."""
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
    """Keyed ONLY by the governed family definition — the entity id is NOT part of it (§1)."""
    category: Category
    sub_label: SubLabel
    endpoint_name: str
    endpoint_version: str
    baseline_method: str
    baseline_version: str

    def __post_init__(self) -> None:
        _check_type(self.category, Category, "family.category")
        _check_type(self.sub_label, SubLabel, "family.sub_label")
        for n in ("endpoint_name", "endpoint_version", "baseline_method", "baseline_version"):
            _check_nonempty_str(getattr(self, n), f"family.{n}")

    @property
    def key(self) -> str:
        return "|".join([self.category.value, self.sub_label.value, self.endpoint_name,
                         self.endpoint_version, self.baseline_method, self.baseline_version])

    def canonical_dict(self) -> dict:
        return {"category": self.category.value, "sub_label": self.sub_label.value,
                "endpoint_name": self.endpoint_name, "endpoint_version": self.endpoint_version,
                "baseline_method": self.baseline_method, "baseline_version": self.baseline_version}


# --------------------------------------------------------------------------- UserObservation
@dataclass(frozen=True)
class UserObservation:
    """One human noticing, one case — the subjective seed. Immutable (a change is a correction)."""
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
    acted_journal_ref: Optional[str] = None      # Decision Journal id, by reference only (§8)
    supersedes: Optional[int] = None             # record_seq of the record this corrects
    track_state: CaseTrackState = field(default=CaseTrackState.OBSERVED, init=False)

    def __post_init__(self) -> None:
        _check_nonempty_str(self.observation_id, "observation_id")
        _check_nonempty_str(self.observer, "observer")
        _check_type(self.entity, EntityIdentity, "entity")
        _check_type(self.event, EventIdentity, "event")
        _check_nonempty_str(self.thesis, "thesis")
        _check_aware(self.observed_at, "observed_at")
        _check_aware(self.bk_captured, "bk_captured")
        _check_seq_int(self.record_seq, "record_seq")
        object.__setattr__(self, "sources", _str_tuple(self.sources, "sources"))
        _check_type(self.acted, bool, "acted")
        if self.acted_journal_ref is not None:
            _check_nonempty_str(self.acted_journal_ref, "acted_journal_ref")
        if not self.acted and self.acted_journal_ref is not None:
            raise ResearchContractError("acted_journal_ref present but acted is False")
        if self.supersedes is not None:
            _check_seq_int(self.supersedes, "supersedes")

    def canonical_dict(self) -> dict:
        return {
            "observation_id": self.observation_id, "observer": self.observer,
            "entity": self.entity.canonical_dict(), "event": self.event.canonical_dict(),
            "thesis": self.thesis, "observed_at": self.observed_at.isoformat(),
            "bk_captured": self.bk_captured.isoformat(), "record_seq": self.record_seq,
            "sources": list(self.sources), "acted": self.acted,
            "acted_journal_ref": self.acted_journal_ref, "supersedes": self.supersedes,
            "track_state": self.track_state.value,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self)


# --------------------------------------------------------------------------- ResearchCandidate
@dataclass(frozen=True)
class ResearchCandidate:
    """The testable form, frozen BEFORE the event. Content-hashed; never edited (§3)."""
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
    primary_endpoint: Optional[PrimaryEndpoint] = None  # None ⇒ no frozen numeric MEPI ⇒ seed only
    pre_event_snapshot: Mapping = field(default_factory=dict)
    acted: bool = False
    sources: tuple = ()
    supersedes: Optional[int] = None
    # derived at freeze (object.__setattr__ in __post_init__)
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
        _check_type(self.acted, bool, "acted")
        object.__setattr__(self, "sources", _str_tuple(self.sources, "sources"))
        if self.supersedes is not None:
            _check_seq_int(self.supersedes, "supersedes")
        # the temporal/event clocks must agree between the two value objects
        if self.temporal.event_effective != self.event.event_effective:
            raise TemporalError("temporal.event_effective must equal event.event_effective")

        # --- freeze/eligibility derivation (the source of the record's credibility) ---
        frozen_before = self.temporal.bk_captured < self.event.event_effective
        object.__setattr__(self, "frozen_before_event", frozen_before)

        reasons = []
        if not frozen_before:
            reasons.append("frozen_after_event")           # permanently a descriptive note (§3)
        if not self.entity.is_resolved:
            reasons.append("unresolved_identity")          # held UNKNOWN, ineligible (§6)
        if self.primary_endpoint is None:
            reasons.append("no_frozen_numeric_mepi")       # Rev 2.1 #4 (Case #1)
        object.__setattr__(self, "ineligibility_reasons", tuple(reasons))

        # frozen-after-event is the ONLY permanent descriptive-note condition; the others keep the
        # measurement defined but exclude it from the sample (and can be cured by a superseding
        # pre-event record).
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
                         self.primary_endpoint.version, self.baseline.method, self.baseline.version)

    @property
    def case_identity(self) -> str:
        """(entity, event, candidate contract) — names THIS observation uniquely (§1)."""
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
            "pre_event_snapshot": {str(k): v for k, v in sorted(self.pre_event_snapshot.items())},
            "acted": self.acted, "sources": list(self.sources), "supersedes": self.supersedes,
        }


def supersede_candidate(prior: ResearchCandidate, *, new_temporal: TemporalFacts,
                        primary_endpoint: Optional[PrimaryEndpoint] = None, **overrides: Any
                        ) -> ResearchCandidate:
    """Produce a NEW candidate correcting `prior`, linked by record_seq (§6).

    A corrected candidate is only a *graded* candidate if it is still frozen before the event. In
    particular a numeric MEPI can NEVER be backfilled to rescue a seed after the event (Rev 2.1 #4,
    §5): attempting to add/change the MEPI with a capture at/after the event is a HindsightError.
    """
    _check_type(prior, ResearchCandidate, "prior")
    _check_type(new_temporal, TemporalFacts, "new_temporal")
    if new_temporal.record_seq <= prior.temporal.record_seq:
        raise SupersessionError("a superseding candidate needs a strictly greater record_seq")

    adding_or_changing_mepi = (
        primary_endpoint is not None
        and (prior.primary_endpoint is None or primary_endpoint != prior.primary_endpoint)
    )
    if adding_or_changing_mepi and new_temporal.bk_captured >= new_temporal.event_effective:
        raise HindsightError(
            "MEPI may never be backfilled: a frozen measurement plan cannot be added or changed "
            "with a capture at/after the event (would manufacture pre-registration, §5)"
        )

    base = dict(
        candidate_id=overrides.pop("candidate_id", prior.candidate_id + "+corr"),
        observation_id=prior.observation_id, observer=prior.observer, category=prior.category,
        sub_label=prior.sub_label, entity=overrides.pop("entity", prior.entity),
        event=overrides.pop("event", prior.event), temporal=new_temporal, thesis=prior.thesis,
        baseline=overrides.pop("baseline", prior.baseline), assumptions=prior.assumptions,
        eligibility_conditions=prior.eligibility_conditions,
        invalidation_conditions=prior.invalidation_conditions,
        primary_endpoint=primary_endpoint if primary_endpoint is not None else prior.primary_endpoint,
        pre_event_snapshot=prior.pre_event_snapshot, acted=prior.acted, sources=prior.sources,
        supersedes=prior.temporal.record_seq,
    )
    base.update(overrides)
    return ResearchCandidate(**base)


# --------------------------------------------------------------------------- CandidateOutcome
@dataclass(frozen=True)
class CandidateOutcome:
    """One measured data point, appended AFTER the event. Append-only, versioned (§4).

    It attaches to the candidate; it NEVER touches a frozen field. There is deliberately no
    per-case 'hit'/'miss' label — a single case is a measured/partial/pending/unmeasurable/
    invalidated data point, never a verdict.
    """
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
    descriptive: Mapping = field(default_factory=dict)   # secondary outcomes — never the endpoint
    measurement_receipt_ref: Optional[str] = None        # Decision-Integrity receipt id, by ref (§8)
    invalidation_reason: Optional[str] = None            # required iff case_state==INVALIDATED
    supersedes: Optional[int] = None

    def __post_init__(self) -> None:
        _check_nonempty_str(self.outcome_id, "outcome_id")
        _check_nonempty_str(self.candidate_id, "candidate_id")
        _check_type(self.version, int, "version")
        if self.version < 1:
            raise TypeStrictError("version must be >= 1")
        _check_type(self.case_state, CaseState, "case_state")
        _check_aware(self.bk_captured, "bk_captured")
        _check_seq_int(self.record_seq, "record_seq")
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
        if self.measurement_receipt_ref is not None:
            _check_nonempty_str(self.measurement_receipt_ref, "measurement_receipt_ref")
        if self.supersedes is not None:
            _check_seq_int(self.supersedes, "supersedes")
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
            # event was ELIGIBLE but endpoint cannot be measured — counted, no backfill (Rev 2.1 #1)
            if self.observed_endpoint_value is not None:
                raise EligibilityError("UNMEASURABLE must not carry a measured endpoint value")
            if not self.invalidation_reason:
                raise EligibilityError("UNMEASURABLE requires a stated unmeasurable reason")
        elif st is CaseState.INVALIDATED:
            if not self.invalidation_reason:
                raise EligibilityError("INVALIDATED requires an eligibility-failure reason")
        # the cross-check against the candidate's FROZEN conditions is done at attach time
        # (validate_invalidation_against_candidate) because a bare outcome does not hold them.

    def validate_invalidation_against_candidate(self, candidate: "ResearchCandidate") -> None:
        """INVALIDATED is reserved SOLELY for a frozen pre-event eligibility failure (§2).

        It must NOT encode a measurement failure (that is UNMEASURABLE) nor an outcome-correlated
        downstream condition (that is a covariate) — both would be selection bias (§2/§5.5).
        """
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
        return self.case_state in (CaseState.MEASURED, CaseState.PARTIAL)

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
            "completeness": {str(k): v.value for k, v in sorted(self.completeness.items())},
            "covariates": {str(k): _canonicalize(v) for k, v in sorted(self.covariates.items())},
            "descriptive": {str(k): _canonicalize(v) for k, v in sorted(self.descriptive.items())},
            "measurement_receipt_ref": self.measurement_receipt_ref,
            "invalidation_reason": self.invalidation_reason, "supersedes": self.supersedes,
        }


# --------------------------------------------------------------------------- family evaluation
@dataclass(frozen=True)
class FamilySummary:
    family_key: FamilyKey
    n_candidates: int
    n_eligible: int
    effective_n: int           # distinct entities among matched-sample cases (independence proxy)
    n_matched: int
    n_pending: int
    n_unmeasurable: int
    n_invalidated: int

    def canonical_dict(self) -> dict:
        d = {"family_key": self.family_key.key}
        d.update({k: getattr(self, k) for k in
                  ("n_candidates", "n_eligible", "effective_n", "n_matched",
                   "n_pending", "n_unmeasurable", "n_invalidated")})
        return d


def summarize_family(family_key: FamilyKey,
                     cases: Sequence[tuple]) -> FamilySummary:
    """cases: sequence of (ResearchCandidate, current CandidateOutcome | None)."""
    _check_type(family_key, FamilyKey, "family_key")
    n_candidates = n_eligible = n_matched = n_pending = n_unmeasurable = n_invalidated = 0
    matched_entities = set()
    for cand, outcome in cases:
        _check_type(cand, ResearchCandidate, "case candidate")
        if cand.family_key is None or cand.family_key.key != family_key.key:
            raise EvaluationError("a case does not belong to this family key")
        n_candidates += 1
        if not cand.eligible_for_sample:
            continue
        n_eligible += 1
        if outcome is None:
            n_pending += 1
            continue
        _check_type(outcome, CandidateOutcome, "case outcome")
        if outcome.case_state is CaseState.INVALIDATED:
            n_invalidated += 1
        elif outcome.counts_in_matched_sample:
            n_matched += 1
            matched_entities.add(cand.entity.canonical_id)
        elif outcome.case_state is CaseState.PENDING:
            n_pending += 1
        elif outcome.case_state is CaseState.UNMEASURABLE:
            n_unmeasurable += 1
    return FamilySummary(family_key, n_candidates, n_eligible, len(matched_entities),
                         n_matched, n_pending, n_unmeasurable, n_invalidated)


@dataclass(frozen=True)
class EvidenceBundle:
    """The structural evidence a SUPPORTED/UNSUPPORTED resolution must carry (contract §7).

    Slice 1 enforces the PRESENCE and internal consistency of these fields, not the numeric
    floors (deferred, §10 Q3). Statistical significance alone can never produce SUPPORTED.
    """
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


@dataclass(frozen=True)
class EvaluatedFinding:
    """The verdict over a matched sample of eligible cases. Immutable; still RESEARCH_ONLY (§7).

    INCONCLUSIVE is an immutable finding — it does NOT rewind the family; a later evaluation
    creates a new superseding finding as more cases accumulate (Rev 2.1 #2).
    """
    finding_id: str
    family_key: FamilyKey
    status: FindingStatus
    summary: FamilySummary
    endpoint_mepi: float
    endpoint_direction: Direction
    bk_captured: datetime
    record_seq: int
    evidence: Optional[EvidenceBundle] = None
    supersedes: Optional[int] = None
    authority: str = field(default=AUTHORITY, init=False)   # always RESEARCH_ONLY
    content_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        _check_nonempty_str(self.finding_id, "finding_id")
        _check_type(self.family_key, FamilyKey, "family_key")
        _check_type(self.status, FindingStatus, "status")
        _check_type(self.summary, FamilySummary, "summary")
        _check_real(self.endpoint_mepi, "endpoint_mepi")
        _check_type(self.endpoint_direction, Direction, "endpoint_direction")
        _check_aware(self.bk_captured, "bk_captured")
        _check_seq_int(self.record_seq, "record_seq")
        if self.supersedes is not None:
            _check_seq_int(self.supersedes, "supersedes")
        object.__setattr__(self, "content_hash", content_hash(self))

    def canonical_dict(self) -> dict:
        return {
            "finding_id": self.finding_id, "family_key": self.family_key.key,
            "status": self.status.value, "summary": self.summary.canonical_dict(),
            "endpoint_mepi": self.endpoint_mepi, "endpoint_direction": self.endpoint_direction.value,
            "bk_captured": self.bk_captured.isoformat(), "record_seq": self.record_seq,
            "evidence": self.evidence.canonical_dict() if self.evidence else None,
            "supersedes": self.supersedes, "authority": self.authority,
        }


def evaluate_family(*, finding_id: str, endpoint: PrimaryEndpoint, summary: FamilySummary,
                    proposed_status: FindingStatus, bk_captured: datetime, record_seq: int,
                    evidence: Optional[EvidenceBundle] = None,
                    supersedes: Optional[int] = None) -> EvaluatedFinding:
    """Resolve a family to an immutable EvaluatedFinding under the structural guardrails (§7).

    Guardrails enforced in Slice 1:
      * one game cannot promote a hypothesis into an edge — SUPPORTED/UNSUPPORTED is impossible
        below STRUCTURAL_MIN_EFFECTIVE_N independent cases; such a family resolves INCONCLUSIVE;
      * SUPPORTED/UNSUPPORTED must carry a complete EvidenceBundle (effect + uncertainty +
        out-of-sample + sensitivity + missingness rule); significance alone never SUPPORTED;
      * SUPPORTED additionally requires the effect in the frozen direction AND >= the frozen MEPI,
        with the CORRECTED interval clearing both zero and the MEPI.
    """
    _check_type(endpoint, PrimaryEndpoint, "endpoint")
    _check_type(summary, FamilySummary, "summary")
    _check_type(proposed_status, FindingStatus, "proposed_status")

    def _finding(status: FindingStatus, ev: Optional[EvidenceBundle]) -> EvaluatedFinding:
        return EvaluatedFinding(
            finding_id=finding_id, family_key=summary.family_key, status=status, summary=summary,
            endpoint_mepi=endpoint.mepi, endpoint_direction=endpoint.direction,
            bk_captured=bk_captured, record_seq=record_seq, evidence=ev, supersedes=supersedes,
        )

    if summary.effective_n < STRUCTURAL_MIN_EFFECTIVE_N:
        if proposed_status is not FindingStatus.INCONCLUSIVE:
            raise EvaluationError(
                f"effective_n={summary.effective_n} < {STRUCTURAL_MIN_EFFECTIVE_N}: a family below "
                f"the structural floor can only be INCONCLUSIVE (one game cannot make an edge)"
            )
        return _finding(FindingStatus.INCONCLUSIVE, None)

    if proposed_status is FindingStatus.INCONCLUSIVE:
        return _finding(FindingStatus.INCONCLUSIVE, evidence)

    if evidence is None:
        raise EvaluationError(f"{proposed_status.value} requires a complete EvidenceBundle")

    if proposed_status is FindingStatus.SUPPORTED:
        signed = evidence.effect_estimate if endpoint.direction is Direction.INCREASE \
            else -evidence.effect_estimate
        if signed < endpoint.mepi:
            raise EvaluationError(
                "SUPPORTED requires the effect in the frozen direction AND >= the frozen MEPI"
            )
        if not (evidence.corrected_interval_low > 0.0):
            raise EvaluationError("SUPPORTED requires the corrected interval to clear zero")
        clears_mepi = (evidence.corrected_interval_low > endpoint.mepi
                       if endpoint.direction is Direction.INCREASE
                       else -evidence.corrected_interval_high > endpoint.mepi)
        if not clears_mepi:
            raise EvaluationError("SUPPORTED requires the corrected interval to clear the MEPI")
        if not evidence.out_of_sample:
            raise EvaluationError("SUPPORTED requires out-of-sample performance")
        if not evidence.sensitivity_analysis_done:
            raise EvaluationError("SUPPORTED requires a sensitivity analysis")
        return _finding(FindingStatus.SUPPORTED, evidence)

    # UNSUPPORTED — recorded with equal weight; still needs the evidence bundle present.
    return _finding(FindingStatus.UNSUPPORTED, evidence)


# --------------------------------------------------------------------------- in-memory store
class InMemoryResearchStore:
    """Isolated, process-local store for fixtures/tests ONLY. Writes NOTHING to disk."""

    def __init__(self) -> None:
        self._seq = 0
        self.observations: dict = {}
        self.candidates: dict = {}
        self._outcome_versions: dict = {}   # candidate_id -> list[CandidateOutcome] (append-only)
        self._finding_versions: dict = {}   # family key str -> list[EvaluatedFinding]

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # observations -----------------------------------------------------------
    def record_observation(self, obs: UserObservation) -> UserObservation:
        _check_type(obs, UserObservation, "obs")
        if obs.observation_id in self.observations:
            raise SupersessionError("observation_id already recorded; corrections supersede by id")
        self.observations[obs.observation_id] = obs
        return obs

    # candidates -------------------------------------------------------------
    def freeze_candidate(self, cand: ResearchCandidate) -> ResearchCandidate:
        _check_type(cand, ResearchCandidate, "cand")
        if cand.observation_id not in self.observations:
            raise ResearchContractError("cannot freeze a candidate for an unknown observation")
        self.candidates[cand.candidate_id] = cand
        return cand

    # outcomes (append-only version chain, exactly one current) --------------
    def append_outcome(self, outcome: CandidateOutcome) -> CandidateOutcome:
        _check_type(outcome, CandidateOutcome, "outcome")
        cand = self.candidates.get(outcome.candidate_id)
        if cand is None:
            raise ResearchContractError("cannot attach an outcome to an unknown candidate")
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
        chain.append(outcome)
        return outcome

    def current_outcome(self, candidate_id: str) -> Optional[CandidateOutcome]:
        chain = self._outcome_versions.get(candidate_id)
        return chain[-1] if chain else None

    def outcome_history(self, candidate_id: str) -> tuple:
        return tuple(self._outcome_versions.get(candidate_id, ()))

    # findings (append-only, one current, INCONCLUSIVE never rewinds) --------
    def record_finding(self, finding: EvaluatedFinding) -> EvaluatedFinding:
        _check_type(finding, EvaluatedFinding, "finding")
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
        chain.append(finding)
        return finding

    def current_finding(self, family_key: FamilyKey) -> Optional[EvaluatedFinding]:
        chain = self._finding_versions.get(family_key.key)
        return chain[-1] if chain else None

    def family_cases(self, family_key: FamilyKey) -> list:
        """(candidate, current outcome) pairs for every candidate mapping to this family."""
        out = []
        for cand in self.candidates.values():
            fk = cand.family_key
            if fk is not None and fk.key == family_key.key:
                out.append((cand, self.current_outcome(cand.candidate_id)))
        return out


__all__ = [
    "AUTHORITY", "STRUCTURAL_MIN_EFFECTIVE_N",
    "ResearchContractError", "TypeStrictError", "TemporalError", "EligibilityError",
    "HindsightError", "SupersessionError", "EvaluationError",
    "Category", "SubLabel", "Direction", "SourceUpdatedStatus", "Resolution", "Completeness",
    "CaseTrackState", "CaseState", "FamilyState", "FindingStatus",
    "EntityIdentity", "EventIdentity", "TemporalFacts", "PrimaryEndpoint", "BaselineMethod",
    "FamilyKey", "UserObservation", "ResearchCandidate", "supersede_candidate",
    "CandidateOutcome", "FamilySummary", "summarize_family", "EvidenceBundle",
    "EvaluatedFinding", "evaluate_family", "InMemoryResearchStore",
    "canonical_json", "content_hash",
]
