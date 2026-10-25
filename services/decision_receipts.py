"""Decision Integrity — shared contract library (Phase 2B, Slice 1, Rev 2).

PURE CONTRACT LIBRARY implementing the APPROVED Phase 2A contract
(`docs/decision_integrity_phase2a_contracts.md`, Rev 2.1 + 2.2 + 2.3) faithfully:
the common envelope, the frozen closed vocabularies, grain-specific per-row
identity, governed numeric profiles, strict UTC clocks, the two-digest canonical
hashing (separate `content_hash` and `conclusion_hash`), and a NON-THROWING
structural validator.

Slice-1 subset rule: the closed vocabularies are implemented in FULL (all six
receipt kinds, five authority classes, three replay classes, seven leaves, the
full identity-quality / mechanism / status / semantic-category / change-kind /
grain sets). Only a SUBSET of bodies is constructible in Slice 1
(`SUPPORTED_RECEIPT_KINDS`); the remaining kinds are recognized but marked
not-yet-constructed and the validator rejects a body under them.

Deliberate non-scope (acceptance boundaries): no application / route / template /
builder / cache / database / runtime dir / env flag / production integration; no
network or provider access; no automatic receipt persistence; no transition-kind
implementation; no tamper-evidence CLAIM and no proof GENERATION or verification
(integrity `mechanism`/`proof` validated for STRUCTURE only). Importing this
module performs no filesystem or environment side effects — stdlib only.

Two digests (Phase 2A §4, Rev-2 #1/#2, Rev-2.1 #3):
  * `integrity.content_hash` — the ENTIRE receipt instance (every stored
    envelope+body field, incl. `created_at`/`created_seq`/`conclusion_hash`)
    EXCLUDING only `integrity.content_hash` itself and `integrity.proof`.
  * `conclusion_hash` (top-level envelope field) — the authoritative canonical
    output only, EXCLUDING receipt-instance metadata (`receipt_id`, `created_seq`,
    `created_at`, `integrity`) and itself. Includes universe (w/ version), clocks,
    input_hashes, versions, refs, authority/replay/projection, and the full body
    (rows with reason_code + reason_def_version + params + per-row identity, and
    the AUTHORITATIVE membership ORDERING — list order is preserved, never sorted).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Versioning (structured {major, minor}). Unknown major fails closed; a newer
# minor within a known major is permitted (forward-compatible, additive).
# ---------------------------------------------------------------------------

CONTRACT_MAJOR = 1
CONTRACT_MINOR = 0
_KNOWN_MAJORS = frozenset({1})


@dataclass(frozen=True)
class SchemaVersion:
    major: int
    minor: int


# ---------------------------------------------------------------------------
# Frozen closed vocabularies (Phase 2A §1/§2/§3/§5/§6/§9) — complete.
# ---------------------------------------------------------------------------


class ReceiptKind(Enum):
    LIVE_EVIDENCE = "live_evidence"
    ENTITY_DISPOSITION = "entity_disposition"
    DECISION_TIME = "decision_time"
    CORRECTION = "correction"
    RENDER = "render"
    SOURCE_HEALTH = "source_health"


class AuthorityClass(Enum):
    FACT = "fact"
    DERIVED_CONTEXT = "derived_context"
    DESCRIPTIVE_MISMATCH = "descriptive_mismatch"
    GOVERNED_MODEL = "governed_model"
    USER_THESIS = "user_thesis"


class ReplayClass(Enum):
    EXACT_REPLAY = "EXACT_REPLAY"
    EVIDENCE_EQUIVALENT = "EVIDENCE_EQUIVALENT"
    NON_REPLAYABLE = "NON_REPLAYABLE"


class Leaf(Enum):
    """The closed set of seven terminal leaf dispositions (§2). Every expected
    entity gets EXACTLY ONE. ELIGIBLE/MEMBERS are roll-ups, never a leaf."""
    RENDERED = "RENDERED"
    SUPPRESSED = "SUPPRESSED"
    NONMEMBER = "NONMEMBER"
    EXCLUDED = "EXCLUDED"
    UNAVAILABLE = "UNAVAILABLE"
    INDETERMINATE = "INDETERMINATE"
    FAILED = "FAILED"


_ROLLUP_NAMES = frozenset({"ELIGIBLE", "MEMBERS"})


class StageOutcome(Enum):
    """Decision-grain stage outcomes (reason-code semantic_category=stage_outcome).
    Consumed by calculation, NEVER a presentation leaf."""
    GRADED = "GRADED"
    PUSH = "PUSH"
    VOID = "VOID"
    NO_LINE = "NO_LINE"
    OVERDUE = "OVERDUE"
    MALFORMED = "MALFORMED"
    OUTSIDE_BOUNDARY = "OUTSIDE_BOUNDARY"


_LEAF_NAMES = frozenset(l.value for l in Leaf)
_STAGE_NAMES = frozenset(s.value for s in StageOutcome)
assert _LEAF_NAMES.isdisjoint(_STAGE_NAMES), "leaf/stage value sets overlap"


class IdentityQuality(Enum):
    PROVIDER_ID = "PROVIDER_ID"
    DECLARED_COMPOSITE = "DECLARED_COMPOSITE"
    COMPOSITE_NAME_EVENT = "COMPOSITE_NAME_EVENT"
    ALIAS_RESOLVED = "ALIAS_RESOLVED"
    NAME_ONLY = "NAME_ONLY"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


# R13: these MUST fail closed (leaf UNAVAILABLE/INDETERMINATE; never a graded/
# rendered authoritative conclusion).
_FAIL_CLOSED_IDENTITY = frozenset(
    {IdentityQuality.AMBIGUOUS, IdentityQuality.UNRESOLVED, IdentityQuality.NAME_ONLY}
)
_FAIL_CLOSED_LEAVES = frozenset({Leaf.UNAVAILABLE, Leaf.INDETERMINATE})
# R14: composite keys MUST declare a passed collision test.
_COMPOSITE_IDENTITY = frozenset(
    {IdentityQuality.DECLARED_COMPOSITE, IdentityQuality.COMPOSITE_NAME_EVENT}
)


class IdentityGrain(Enum):
    EVENT = "event"
    TEAM_SIDE = "team_side"
    MARKET_OBS = "market_obs"
    SELECTION = "selection"
    GRADING = "grading"


class SourceUpdatedStatus(Enum):
    """Whether a provider source-update clock is present (§1). The literal string
    'UNKNOWN' is never a clock VALUE — an absent clock is null + UNKNOWN/NOT_PROVIDED."""
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_PROVIDED = "NOT_PROVIDED"


_SOURCE_ABSENT_STATUSES = frozenset(
    {SourceUpdatedStatus.UNKNOWN, SourceUpdatedStatus.NOT_PROVIDED}
)


class IntegrityMechanism(Enum):
    NONE = "none"
    HASH_CHAIN = "hash_chain"
    SIGNED = "signed"
    WORM = "worm"
    ANCHORED = "anchored"
    AUDIT_LOG = "audit_log"


class SemanticCategory(Enum):
    LEAF = "leaf"
    HEALTH = "health"
    STAGE_OUTCOME = "stage_outcome"
    TRANSITION = "transition"


class ChangeKind(Enum):
    REGRADE = "regrade"
    LINE_CORRECTION = "line_correction"
    RESCHEDULE = "reschedule"
    IDENTITY_FIX = "identity_fix"
    RETRACTION = "retraction"


class Projection(Enum):
    INTERNAL = "internal"
    USER_SAFE = "user_safe"


HASH_ALGORITHMS = frozenset({"sha256"})  # P2A-4 allowlist (agility, not free-form)

# Which receipt kinds have a constructible body in Slice 1. The others are part
# of the frozen vocabulary but not yet constructed.
SUPPORTED_RECEIPT_KINDS = frozenset(
    {ReceiptKind.ENTITY_DISPOSITION, ReceiptKind.LIVE_EVIDENCE}
)
NOT_YET_CONSTRUCTED_KINDS = frozenset(ReceiptKind) - SUPPORTED_RECEIPT_KINDS


# ---------------------------------------------------------------------------
# Governed numeric profiles (§4 Number normalization, Rev-2 #5). Each governed
# numeric field declares a profile; the value canonicalizes to a decimal STRING
# at that profile's scale (no implied precision, no -0, ints never floats).
# ---------------------------------------------------------------------------


class NumericProfileError(ValueError):
    pass


def _as_number(value: Union[int, float, str]) -> float:
    if isinstance(value, bool):
        raise NumericProfileError("bool is not a governed number")
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        try:
            f = float(value)
        except ValueError as exc:
            raise NumericProfileError(f"not numeric: {value!r}") from exc
    else:
        raise NumericProfileError(f"uncanonicalizable numeric type: {type(value).__name__}")
    if f != f or f in (float("inf"), float("-inf")):
        raise NumericProfileError("NaN/Inf is not a governed number")
    return f


def _canon_line(value: Union[int, float, str]) -> str:
    f = _as_number(value)
    if abs(round(f * 2) - f * 2) > 1e-9:
        raise NumericProfileError(f"line must be a half-point multiple: {value!r}")
    s = f"{f + 0.0:.2f}"
    return s.replace("-0.00", "0.00")


def _canon_probability(value: Union[int, float, str]) -> str:
    f = _as_number(value)
    if f < 0.0 or f > 1.0:
        raise NumericProfileError(f"probability must be in [0,1]: {value!r}")
    return f"{f:.4f}"


def _canon_price(value: Union[int, float, str]) -> str:
    f = _as_number(value)
    if abs(f - round(f)) > 1e-9:
        raise NumericProfileError(f"price must be an American integer: {value!r}")
    v = int(round(f))
    if abs(v) < 100:
        raise NumericProfileError(f"American price magnitude must be >= 100: {value!r}")
    return f"+{v}" if v > 0 else f"{v}"


def _canon_count(value: Union[int, float, str]) -> str:
    f = _as_number(value)
    if abs(f - round(f)) > 1e-9 or round(f) < 0:
        raise NumericProfileError(f"count must be a non-negative integer: {value!r}")
    return str(int(round(f)))


NUMERIC_PROFILES = {
    "line": _canon_line,
    "probability": _canon_probability,
    "price": _canon_price,
    "count": _canon_count,
}


def canonical_number(value: Union[int, float, str], profile: str) -> str:
    try:
        fn = NUMERIC_PROFILES[profile]
    except KeyError as exc:
        raise NumericProfileError(f"unknown numeric profile: {profile!r}") from exc
    return fn(value)


@dataclass(frozen=True)
class GovernedNumber:
    """A numeric value bound to a governed profile; canonicalizes to a decimal
    string at the profile's scale."""
    value: Union[int, float, str]
    profile: str

    def canonical(self) -> str:
        return canonical_number(self.value, self.profile)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """Grain-specific identity, PER ROW (§5). The envelope carries no identity."""
    grain: IdentityGrain
    base: Dict[str, Any]
    ext: Dict[str, Any]
    identity_quality: IdentityQuality
    collision_tested: bool
    key: str


@dataclass(frozen=True)
class Clocks:
    bk_captured: str                         # instant[UTC], required
    source_updated_status: SourceUpdatedStatus
    source_updated: Optional[str] = None     # instant[UTC] | null
    event_effective: Optional[str] = None    # instant[UTC] | null


@dataclass(frozen=True)
class Versions:
    build_id: str
    config_version: str
    rule_versions: Dict[str, int]


@dataclass
class Integrity:
    """`{content_hash, hash_algorithm, mechanism, proof?}` (§1). `tamper_evident`
    is DERIVED (mechanism != none AND proof present), not a stored boolean. This
    library never generates or verifies `proof`; it validates structure only."""
    content_hash: Optional[str] = None
    hash_algorithm: str = "sha256"
    mechanism: IntegrityMechanism = IntegrityMechanism.NONE
    proof: Optional[str] = None


def is_tamper_evident(integ: Integrity) -> bool:
    return integ.mechanism != IntegrityMechanism.NONE and bool(integ.proof)


@dataclass(frozen=True)
class Universe:
    grain: str
    id: str
    version: str


@dataclass(frozen=True)
class Refs:
    entity_dispositions: Optional[str] = None   # batch ref id (§7)
    source_health: Optional[str] = None
    evidence: Optional[str] = None              # render→evidence / board→decision-stage


# ---------------------------------------------------------------------------
# Row records (per-row identity + reason definition)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityDisposition:
    """§2 entity-disposition record for the expected (board) universe."""
    entity_ref: str
    identity: Identity
    leaf: Leaf
    reason_code: str
    reason_def_version: int
    params: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class DecisionStageRow:
    """Decision-grain record carrying a STAGE OUTCOME (never a presentation leaf)."""
    entity_ref: str
    identity: Identity
    stage_outcome: StageOutcome
    reason_code: str
    reason_def_version: int
    params: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Bodies (the Slice-1 subset)
# ---------------------------------------------------------------------------


@dataclass
class EntityDispositionBatch:
    """Body of an `entity_disposition` receipt — the per-entity leaf rows for the
    expected universe. Membership ORDERING (row order) is authoritative."""
    rows: List[EntityDisposition] = field(default_factory=list)


@dataclass
class DecisionStageBatch:
    """Body of the decision-stage evidence (`live_evidence`, grain
    `team_side_decision`) — per-decision stage outcomes."""
    rows: List[DecisionStageRow] = field(default_factory=list)


@dataclass
class LiveEvidenceBoard:
    """Body of the board `live_evidence` receipt (grain `team`): the membership
    hash + per-leaf counts + expected count. Per-row detail lives in the referenced
    entity-disposition batch (§7 R18/R19); counts reconcile (§3/R20)."""
    membership_hash: str
    per_leaf_counts: Dict[str, int]
    expected_count: int


# ---------------------------------------------------------------------------
# Receipt envelope (common to all six kinds, §1)
# ---------------------------------------------------------------------------


@dataclass
class Receipt:
    receipt_id: str
    receipt_kind: ReceiptKind
    schema_version: SchemaVersion
    surface_id: str
    universe: Universe
    created_seq: int
    created_at: str                       # instant[UTC]
    versions: Versions
    replay_class: ReplayClass
    authority_class: AuthorityClass
    projection: Projection
    body: Any
    integrity: Integrity = field(default_factory=Integrity)
    conclusion_hash: Optional[str] = None  # top-level, separate from integrity
    clocks: Optional[Clocks] = None
    input_hashes: Optional[List[str]] = None
    supersedes: Optional[str] = None       # authoritative ref: superseded receipt_id
    supersedes_seq: Optional[int] = None   # convenience: superseded created_seq
    refs: Optional[Refs] = None
    disclosures: Optional[List[str]] = None
    claims: Optional[List[str]] = None     # user_safe only


# ---------------------------------------------------------------------------
# Canonicalization — deterministic primitive tree + stable bytes.
# ---------------------------------------------------------------------------


def _norm_str(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _to_primitive(obj: Any) -> Any:
    """Canonical primitive tree. Strings NFC; GovernedNumber → governed decimal
    string; enums → value; bare floats are REJECTED (every numeric must declare a
    governed profile — no implied precision). dict keys/list order preserved
    (membership ordering is authoritative); dict key ordering is applied at dump."""
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, GovernedNumber):
        return obj.canonical()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        raise ValueError("bare float is not canonicalizable; use a GovernedNumber")
    if isinstance(obj, str):
        return _norm_str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_primitive(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {_norm_str(str(k)): _to_primitive(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_primitive(v) for v in obj]
    raise TypeError(f"uncanonicalizable type: {type(obj).__name__}")


def _dumps(tree: Any) -> bytes:
    return json.dumps(
        tree, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


# Receipt-instance metadata excluded from the conclusion (R3b) + the conclusion
# field itself.
_CONCLUSION_EXCLUDE_TOP = ("receipt_id", "created_seq", "created_at", "integrity",
                           "conclusion_hash")


def canonical_content_bytes(receipt: Receipt) -> bytes:
    """Whole instance EXCEPT integrity.content_hash and integrity.proof."""
    tree = _to_primitive(receipt)
    integ = tree.get("integrity")
    if isinstance(integ, dict):
        integ.pop("content_hash", None)
        integ.pop("proof", None)
    return _dumps(tree)


def canonical_conclusion_bytes(receipt: Receipt) -> bytes:
    """Authoritative canonical output only: the whole instance minus receipt-
    instance metadata (receipt_id, created_seq, created_at, integrity) and the
    conclusion_hash field itself. Universe version, clocks, versions, refs,
    authority/replay/projection, and the full body (reason codes, reason_def_version,
    params, per-row identity, and membership ORDER) are all included."""
    tree = _to_primitive(receipt)
    for key in _CONCLUSION_EXCLUDE_TOP:
        tree.pop(key, None)
    return _dumps(tree)


def compute_content_hash(receipt: Receipt) -> str:
    return hashlib.sha256(canonical_content_bytes(receipt)).hexdigest()


def compute_conclusion_hash(receipt: Receipt) -> str:
    return hashlib.sha256(canonical_conclusion_bytes(receipt)).hexdigest()


def seal_hashes(receipt: Receipt) -> Receipt:
    """Populate `conclusion_hash` then `integrity.content_hash` from the canonical
    forms (plain digests — NOT a tamper-evidence proof; never sets `proof`).
    Conclusion is computed first because content covers the conclusion_hash field."""
    receipt.conclusion_hash = compute_conclusion_hash(receipt)
    receipt.integrity.content_hash = compute_content_hash(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Strict UTC instant validation (§ conventions: instant[UTC]).
# ---------------------------------------------------------------------------

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


def _valid_utc(s: Any) -> bool:
    if not isinstance(s, str) or not _UTC_RE.match(s):
        return False
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


# ---------------------------------------------------------------------------
# Structural validator (NON-THROWING).
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


def _check_version(v: SchemaVersion, errs: List[str]) -> None:
    if not isinstance(v, SchemaVersion) or not isinstance(v.major, int) \
            or not isinstance(v.minor, int) or isinstance(v.major, bool):
        errs.append("schema_version must be {major:int, minor:int}")
        return
    if v.major not in _KNOWN_MAJORS:
        errs.append(f"unknown schema major {v.major} (fail closed)")
    if v.minor < 0:
        errs.append("schema_version.minor must be >= 0")


def _check_clocks(c: Clocks, errs: List[str]) -> None:
    if not _valid_utc(c.bk_captured):
        errs.append("clocks.bk_captured must be a tz-aware UTC instant")
    if not isinstance(c.source_updated_status, SourceUpdatedStatus):
        errs.append("clocks.source_updated_status must be a SourceUpdatedStatus")
        return
    if c.source_updated is None:
        if c.source_updated_status not in _SOURCE_ABSENT_STATUSES:
            errs.append("null source_updated requires status UNKNOWN/NOT_PROVIDED")
    else:
        if c.source_updated_status != SourceUpdatedStatus.PRESENT:
            errs.append("present source_updated requires status PRESENT")
        if not _valid_utc(c.source_updated):
            errs.append("clocks.source_updated must be a tz-aware UTC instant "
                        "(no literal 'UNKNOWN', no naive/offset time)")
    if c.event_effective is not None and not _valid_utc(c.event_effective):
        errs.append("clocks.event_effective must be a tz-aware UTC instant")


def _check_versions(v: Versions, errs: List[str]) -> None:
    if not isinstance(v, Versions):
        errs.append("versions must be a Versions {build_id, config_version, rule_versions}")
        return
    if not v.build_id or not isinstance(v.build_id, str):
        errs.append("versions.build_id required")
    if not v.config_version or not isinstance(v.config_version, str):
        errs.append("versions.config_version required")
    if not isinstance(v.rule_versions, dict) or \
            any(not isinstance(x, int) or isinstance(x, bool) for x in v.rule_versions.values()):
        errs.append("versions.rule_versions must map to integers")


def _check_integrity(receipt: Receipt, errs: List[str]) -> None:
    integ = receipt.integrity
    if not isinstance(integ, Integrity):
        errs.append("integrity must be an Integrity")
        return
    if integ.hash_algorithm not in HASH_ALGORITHMS:
        errs.append(f"integrity.hash_algorithm not allowlisted: {integ.hash_algorithm!r}")
    if not isinstance(integ.mechanism, IntegrityMechanism):
        errs.append("integrity.mechanism must be an IntegrityMechanism")
    else:
        # Structure only: mechanism and proof presence must agree. No verification.
        if integ.mechanism == IntegrityMechanism.NONE and integ.proof:
            errs.append("integrity.mechanism=none must not carry a proof")
        if integ.mechanism != IntegrityMechanism.NONE and not integ.proof:
            errs.append(f"integrity.mechanism={integ.mechanism.value} requires proof material "
                        "(structure only; not verified)")
    # Validate DECLARED digests against recomputed canonical digests (non-throwing).
    try:
        if integ.content_hash is not None and integ.content_hash != compute_content_hash(receipt):
            errs.append("declared integrity.content_hash does not match canonical content")
    except Exception as exc:  # malformed canonicalization → validation error, never raise
        errs.append(f"content canonicalization failed: {type(exc).__name__}: {exc}")
    try:
        if receipt.conclusion_hash is None:
            errs.append("conclusion_hash is required (seal the receipt)")
        elif receipt.conclusion_hash != compute_conclusion_hash(receipt):
            errs.append("declared conclusion_hash does not match canonical conclusion")
    except Exception as exc:
        errs.append(f"conclusion canonicalization failed: {type(exc).__name__}: {exc}")


def _check_identity(idn: Identity, where: str, errs: List[str]) -> None:
    if not isinstance(idn, Identity):
        errs.append(f"{where}: identity must be an Identity record")
        return
    if not isinstance(idn.grain, IdentityGrain):
        errs.append(f"{where}: identity.grain must be an IdentityGrain")
    if not isinstance(idn.identity_quality, IdentityQuality):
        errs.append(f"{where}: identity.identity_quality must be an IdentityQuality")
    if not idn.key or not isinstance(idn.key, str):
        errs.append(f"{where}: identity.key required")
    if isinstance(idn.identity_quality, IdentityQuality) \
            and idn.identity_quality in _COMPOSITE_IDENTITY and not idn.collision_tested:
        errs.append(f"{where}: {idn.identity_quality.value} requires collision_tested=true (R14)")


def _check_reason(code: str, def_version: int, where: str, errs: List[str]) -> None:
    if not isinstance(code, str) or not _REASON_CODE_RE.match(code or ""):
        errs.append(f"{where}: reason_code must be UPPER_SNAKE with no interpolated value "
                    f"(got {code!r})")
    if not isinstance(def_version, int) or isinstance(def_version, bool) or def_version < 1:
        errs.append(f"{where}: reason_def_version must be an int >= 1")


def _check_entity_disposition_batch(b: EntityDispositionBatch, errs: List[str]) -> None:
    seen = set()
    for i, r in enumerate(b.rows):
        w = f"rows[{i}]"
        if not r.entity_ref:
            errs.append(f"{w}: entity_ref required")
        # Exactly-one: no duplicate entity across the batch (R4).
        if r.entity_ref in seen:
            errs.append(f"{w}: duplicate entity_ref {r.entity_ref!r} — an entity MUST carry "
                        "exactly one leaf (R4)")
        seen.add(r.entity_ref)
        # Firewall: leaf must be a Leaf; a stage outcome / roll-up used as a leaf is rejected.
        if isinstance(r.leaf, StageOutcome) or (
                isinstance(r.leaf, Enum) and r.leaf.value in _STAGE_NAMES):
            errs.append(f"{w}: stage outcome used as a terminal leaf")
        elif isinstance(r.leaf, str) and r.leaf in _ROLLUP_NAMES:
            errs.append(f"{w}: roll-up {r.leaf!r} is not a terminal leaf (R5)")
        elif not isinstance(r.leaf, Leaf):
            errs.append(f"{w}: leaf must be a Leaf")
        _check_reason(r.reason_code, r.reason_def_version, w, errs)
        _check_identity(r.identity, w, errs)
        # R13 fail-closed identity → only UNAVAILABLE/INDETERMINATE.
        if isinstance(r.identity, Identity) and isinstance(r.leaf, Leaf) \
                and r.identity.identity_quality in _FAIL_CLOSED_IDENTITY \
                and r.leaf not in _FAIL_CLOSED_LEAVES:
            errs.append(f"{w}: identity {r.identity.identity_quality.value} must fail closed "
                        "(leaf UNAVAILABLE/INDETERMINATE), not " + r.leaf.value)
        _check_params(r.params, w, errs)


def _check_decision_stage_batch(b: DecisionStageBatch, errs: List[str]) -> None:
    seen = set()
    for i, r in enumerate(b.rows):
        w = f"rows[{i}]"
        if not r.entity_ref:
            errs.append(f"{w}: entity_ref required")
        if r.entity_ref in seen:
            errs.append(f"{w}: duplicate entity_ref {r.entity_ref!r} — exactly one stage "
                        "outcome per decision")
        seen.add(r.entity_ref)
        # Firewall (other direction): a presentation leaf used as a stage outcome is rejected.
        if isinstance(r.stage_outcome, Leaf) or (
                isinstance(r.stage_outcome, Enum) and r.stage_outcome.value in _LEAF_NAMES):
            errs.append(f"{w}: presentation leaf used as a decision-stage outcome")
        elif not isinstance(r.stage_outcome, StageOutcome):
            errs.append(f"{w}: stage_outcome must be a StageOutcome")
        _check_reason(r.reason_code, r.reason_def_version, w, errs)
        _check_identity(r.identity, w, errs)
        if isinstance(r.identity, Identity) and isinstance(r.stage_outcome, StageOutcome) \
                and r.identity.identity_quality in _FAIL_CLOSED_IDENTITY \
                and r.stage_outcome == StageOutcome.GRADED:
            errs.append(f"{w}: GRADED asserted under fail-closed identity "
                        f"{r.identity.identity_quality.value}")
        _check_params(r.params, w, errs)


def _check_params(params: Optional[Dict[str, Any]], where: str, errs: List[str]) -> None:
    if params is None:
        return
    if not isinstance(params, dict):
        errs.append(f"{where}: params must be a map")
        return
    for k, v in params.items():
        if isinstance(v, GovernedNumber):
            try:
                v.canonical()
            except NumericProfileError as exc:
                errs.append(f"{where}: params[{k!r}] violates numeric profile: {exc}")
        elif isinstance(v, float):
            errs.append(f"{where}: params[{k!r}] is a bare float — wrap in a GovernedNumber")


def _check_board(b: LiveEvidenceBoard, receipt: Receipt, errs: List[str]) -> None:
    if not b.membership_hash:
        errs.append("board.membership_hash required")
    if not isinstance(b.per_leaf_counts, dict):
        errs.append("board.per_leaf_counts must be a map")
        return
    for k, n in b.per_leaf_counts.items():
        if k not in _LEAF_NAMES:
            errs.append(f"board.per_leaf_counts key {k!r} is not a leaf")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(f"board.per_leaf_counts[{k!r}] must be a non-negative int")
    total = sum(n for n in b.per_leaf_counts.values() if isinstance(n, int))
    if isinstance(b.expected_count, int) and total != b.expected_count:
        errs.append(f"board conservation: per-leaf counts sum to {total} != expected_count "
                    f"{b.expected_count} (R20)")
    # §7 R18: a board MUST reference its disposition batch + source_health.
    if receipt.refs is None or not receipt.refs.entity_dispositions:
        errs.append("board live_evidence MUST reference an entity_dispositions batch (refs, R18)")
    if receipt.refs is None or not receipt.refs.source_health:
        errs.append("board live_evidence MUST reference a source_health receipt (refs, R18)")


def _check_projection(receipt: Receipt, errs: List[str]) -> None:
    if receipt.projection != Projection.USER_SAFE:
        return
    # R22: user_safe MUST NOT carry internal-only fields.
    if receipt.input_hashes:
        errs.append("user_safe projection must not carry input_hashes (internal-only)")
    if receipt.integrity.proof:
        errs.append("user_safe projection must not carry integrity.proof (internal-only)")
    if not receipt.claims:
        errs.append("user_safe projection must carry claims (§8)")


def _check_supersession(receipt: Receipt, errs: List[str]) -> None:
    is_corr = receipt.receipt_kind == ReceiptKind.CORRECTION
    if is_corr and (not receipt.supersedes or receipt.supersedes_seq is None):
        errs.append("a correction MUST carry supersedes (receipt_id) + supersedes_seq")
    if receipt.supersedes_seq is not None:
        if not isinstance(receipt.supersedes_seq, int) or isinstance(receipt.supersedes_seq, bool):
            errs.append("supersedes_seq must be an int (the superseded receipt's created_seq)")
        elif receipt.supersedes_seq >= receipt.created_seq:
            errs.append("supersedes_seq (superseded created_seq) must be < this created_seq")


def _check_replay(receipt: Receipt, errs: List[str]) -> None:
    if not isinstance(receipt.replay_class, ReplayClass):
        errs.append("replay_class must be a ReplayClass")
        return
    if receipt.replay_class != ReplayClass.NON_REPLAYABLE and not receipt.input_hashes:
        errs.append(f"replay_class={receipt.replay_class.value} requires input_hashes")


def validate_receipt(receipt: Receipt) -> ValidationResult:
    """Structural validation only. NON-THROWING: any malformed value (including an
    uncanonicalizable field hit during hash recomputation) is converted into a
    validation error; this function never raises for contract violations."""
    errs: List[str] = []
    try:
        if not isinstance(receipt, Receipt):
            return ValidationResult(False, ["not a Receipt"])

        for name, typ in (
            ("receipt_id", str), ("receipt_kind", ReceiptKind), ("surface_id", str),
            ("universe", Universe), ("created_seq", int), ("created_at", str),
            ("authority_class", AuthorityClass), ("projection", Projection),
        ):
            if not isinstance(getattr(receipt, name), typ) or (
                    typ is int and isinstance(getattr(receipt, name), bool)):
                errs.append(f"{name} must be a {typ.__name__}")

        if isinstance(receipt.receipt_id, str) and not receipt.receipt_id.strip():
            errs.append("receipt_id must be non-empty")
        if isinstance(receipt.surface_id, str) and not receipt.surface_id.strip():
            errs.append("surface_id must be non-empty")
        if isinstance(receipt.created_at, str) and not _valid_utc(receipt.created_at):
            errs.append("created_at must be a tz-aware UTC instant")
        if isinstance(receipt.universe, Universe) and not receipt.universe.version:
            errs.append("universe.version required")

        _check_version(receipt.schema_version, errs)
        _check_versions(receipt.versions, errs)
        _check_replay(receipt, errs)
        if receipt.clocks is not None:
            _check_clocks(receipt.clocks, errs)
        _check_projection(receipt, errs)
        _check_supersession(receipt, errs)

        # Kind / body.
        if isinstance(receipt.receipt_kind, ReceiptKind) \
                and receipt.receipt_kind in NOT_YET_CONSTRUCTED_KINDS:
            errs.append(f"receipt_kind {receipt.receipt_kind.value} is recognized but "
                        "not-yet-constructed in Slice 1")
        elif isinstance(receipt.body, EntityDispositionBatch):
            if receipt.receipt_kind != ReceiptKind.ENTITY_DISPOSITION:
                errs.append("EntityDispositionBatch requires receipt_kind=entity_disposition")
            _check_entity_disposition_batch(receipt.body, errs)
        elif isinstance(receipt.body, LiveEvidenceBoard):
            if receipt.receipt_kind != ReceiptKind.LIVE_EVIDENCE:
                errs.append("LiveEvidenceBoard requires receipt_kind=live_evidence")
            _check_board(receipt.body, receipt, errs)
        elif isinstance(receipt.body, DecisionStageBatch):
            if receipt.receipt_kind != ReceiptKind.LIVE_EVIDENCE:
                errs.append("DecisionStageBatch requires receipt_kind=live_evidence "
                            "(decision-stage evidence)")
            _check_decision_stage_batch(receipt.body, errs)
        else:
            errs.append(f"unsupported body type: {type(receipt.body).__name__}")

        _check_integrity(receipt, errs)
    except Exception as exc:  # last-resort guard — the API never raises
        errs.append(f"validation aborted on malformed input: {type(exc).__name__}: {exc}")

    return ValidationResult(not errs, errs)


def reconcile_board(board_receipt: Receipt, batch_receipt: Receipt) -> ValidationResult:
    """Cross-receipt conservation (§3/R20): the board's per-leaf counts MUST equal
    the referenced entity-disposition batch's actual per-leaf tallies, and the
    board MUST reference that batch. Non-throwing."""
    errs: List[str] = []
    try:
        if not isinstance(board_receipt.body, LiveEvidenceBoard):
            return ValidationResult(False, ["board_receipt is not a LiveEvidenceBoard"])
        if not isinstance(batch_receipt.body, EntityDispositionBatch):
            return ValidationResult(False, ["batch_receipt is not an EntityDispositionBatch"])
        if board_receipt.refs is None or \
                board_receipt.refs.entity_dispositions != batch_receipt.receipt_id:
            errs.append("board does not reference this entity_dispositions batch")
        tally: Dict[str, int] = {}
        for r in batch_receipt.body.rows:
            if isinstance(r.leaf, Leaf):
                tally[r.leaf.value] = tally.get(r.leaf.value, 0) + 1
        declared = {k: v for k, v in board_receipt.body.per_leaf_counts.items() if v}
        actual = {k: v for k, v in tally.items() if v}
        if declared != actual:
            errs.append(f"board per-leaf counts {declared} != batch tally {actual}")
    except Exception as exc:
        errs.append(f"reconcile aborted: {type(exc).__name__}: {exc}")
    return ValidationResult(not errs, errs)


__all__ = [
    "CONTRACT_MAJOR", "CONTRACT_MINOR", "SchemaVersion",
    "ReceiptKind", "SUPPORTED_RECEIPT_KINDS", "NOT_YET_CONSTRUCTED_KINDS",
    "AuthorityClass", "ReplayClass", "Leaf", "StageOutcome", "IdentityQuality",
    "IdentityGrain", "SourceUpdatedStatus", "IntegrityMechanism", "SemanticCategory",
    "ChangeKind", "Projection", "HASH_ALGORITHMS",
    "NumericProfileError", "NUMERIC_PROFILES", "canonical_number", "GovernedNumber",
    "Identity", "Clocks", "Versions", "Integrity", "is_tamper_evident", "Universe", "Refs",
    "EntityDisposition", "DecisionStageRow",
    "EntityDispositionBatch", "DecisionStageBatch", "LiveEvidenceBoard",
    "Receipt",
    "canonical_content_bytes", "canonical_conclusion_bytes",
    "compute_content_hash", "compute_conclusion_hash", "seal_hashes",
    "ValidationResult", "validate_receipt", "reconcile_board",
]
