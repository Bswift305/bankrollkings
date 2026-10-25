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
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
    TEAM = "team"            # Rev-2.3a: board-universe entity (one per team)
    TEAM_SIDE = "team_side"
    MARKET_OBS = "market_obs"
    SELECTION = "selection"
    GRADING = "grading"


# R14b grain binding: a universe grain implies the identity grain its rows carry.
# Known pilot universes only; unknown universe grains are not bound here.
_UNIVERSE_IDENTITY_GRAIN = {
    "team": IdentityGrain.TEAM,
    "team_side_decision": IdentityGrain.TEAM_SIDE,
}
# Required extension fields per identity grain (§5 + R14b).
_GRAIN_REQUIRED_EXT = {
    IdentityGrain.TEAM: ("team",),
    IdentityGrain.TEAM_SIDE: ("team_side",),
}


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


class HealthState(Enum):
    """The single governed state of record for a source_health receipt. There is no
    second free-form authoritative state."""
    SYNCHRONIZED = "SYNCHRONIZED"
    STALE = "STALE"
    FAIL_CLOSED = "FAIL_CLOSED"


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

# Minimal allowlisted reason-code registry for the NFL ATS pilot (§3). This is the
# Slice-1 subset of the full registry (owner/definition/param_fields and the
# leaf `maps_to` field are deferred to the reason-code registry validator slice);
# it carries the code string and its single semantic_category so a dynamic/
# unregistered code (e.g. `SORTED_BY_STREAK_DESC`) is rejected and a code used in the
# wrong context is caught. Codes are stable UPPER_SNAKE identifiers, no interpolated
# runtime values (R8). SemanticCategory is defined just above.
REASON_CODES: Dict[str, SemanticCategory] = {
    # Board leaves (single-category per §3).
    "BELOW_THRESHOLD": SemanticCategory.LEAF,
    "QUALIFIED": SemanticCategory.LEAF,
    "DISPLAY_CAPPED": SemanticCategory.LEAF,
    "KNOWN_NON_FBS": SemanticCategory.LEAF,
    "COVER_SHORT": SemanticCategory.LEAF,
    # Health.
    "SOURCE_STALE": SemanticCategory.HEALTH,
    # Decision-stage outcomes.
    "GRADED": SemanticCategory.STAGE_OUTCOME,
    "PUSH": SemanticCategory.STAGE_OUTCOME,
    "VOID": SemanticCategory.STAGE_OUTCOME,
    "NO_LINE": SemanticCategory.STAGE_OUTCOME,
    "OVERDUE": SemanticCategory.STAGE_OUTCOME,
    "MALFORMED": SemanticCategory.STAGE_OUTCOME,
    "CONFLICT": SemanticCategory.STAGE_OUTCOME,
    "OUTSIDE_BOUNDARY": SemanticCategory.STAGE_OUTCOME,
    "SORTED": SemanticCategory.STAGE_OUTCOME,
}

# Which receipt kinds have a constructible body. Slice 2 adds correction /
# source_health / render (needed to validate lineage + hierarchical references);
# `decision_time` remains not-yet-constructed and the provisional `transition`
# envelope is deliberately NOT a receipt kind.
SUPPORTED_RECEIPT_KINDS = frozenset({
    ReceiptKind.ENTITY_DISPOSITION, ReceiptKind.LIVE_EVIDENCE,
    ReceiptKind.CORRECTION, ReceiptKind.SOURCE_HEALTH, ReceiptKind.RENDER,
})
NOT_YET_CONSTRUCTED_KINDS = frozenset(ReceiptKind) - SUPPORTED_RECEIPT_KINDS


# ---------------------------------------------------------------------------
# Governed numeric profiles (§4 Number normalization, Rev-2 #5). Each governed
# numeric field declares a profile; the value canonicalizes to a decimal STRING
# at that profile's scale (no implied precision, no -0, ints never floats).
# ---------------------------------------------------------------------------


class NumericProfileError(ValueError):
    pass


def _dec(value: Union[int, str, Decimal]) -> Decimal:
    """Exact Decimal from the ORIGINAL LEXICAL value. A governed authoritative value
    MUST be a `Decimal`, an `int`, or a canonical decimal STRING — a Python `float`
    is REJECTED, because `Decimal(str(float))` cannot recover precision already lost
    to binary before entry (a float is not a lexical decimal)."""
    if isinstance(value, bool):
        raise NumericProfileError("bool is not a governed number")
    if isinstance(value, float):
        raise NumericProfileError(
            "float is not accepted for a governed value — pass Decimal, int, or a "
            "canonical decimal string")
    try:
        if isinstance(value, Decimal):
            d = value
        elif isinstance(value, (int, str)):
            d = Decimal(value)
        else:
            raise NumericProfileError(f"uncanonicalizable numeric type: {type(value).__name__}")
    except (InvalidOperation, ValueError) as exc:
        raise NumericProfileError(f"not a decimal: {value!r}") from exc
    if not d.is_finite():
        raise NumericProfileError("NaN/Inf is not a governed number")
    return d


def _exponent(d: Decimal) -> int:
    """Number of fractional digits in the Decimal's representation (>=0)."""
    exp = d.as_tuple().exponent
    return -exp if exp < 0 else 0


def _canon_line(value: Union[int, str, Decimal]) -> str:
    """Half-point profile: value MUST be an exact multiple of 0.5; canonical 2dp."""
    d = _dec(value)
    if (d * 2) != (d * 2).to_integral_value():
        raise NumericProfileError(f"line must be an exact half-point multiple: {value!r}")
    q = d.quantize(Decimal("0.01"))
    return "0.00" if q == 0 else f"{q}"


def _canon_probability(value: Union[int, str, Decimal]) -> str:
    """Fixed 4dp in [0,1]. No silent rounding: MORE than 4 fractional digits is
    rejected (the profile declares no rounding rule)."""
    d = _dec(value)
    if d < 0 or d > 1:
        raise NumericProfileError(f"probability must be in [0,1]: {value!r}")
    if _exponent(d) > 4:
        raise NumericProfileError(f"probability exceeds 4dp with no rounding rule: {value!r}")
    return f"{d.quantize(Decimal('0.0001'))}"


def _canon_price(value: Union[int, str, Decimal]) -> str:
    """American price: an integer with magnitude >= 100; explicit sign."""
    d = _dec(value)
    if d != d.to_integral_value():
        raise NumericProfileError(f"price must be an American integer: {value!r}")
    v = int(d)
    if abs(v) < 100:
        raise NumericProfileError(f"American price magnitude must be >= 100: {value!r}")
    return f"+{v}" if v > 0 else f"{v}"


def _canon_count(value: Union[int, str, Decimal]) -> str:
    """Non-negative integer."""
    d = _dec(value)
    if d != d.to_integral_value() or d < 0:
        raise NumericProfileError(f"count must be a non-negative integer: {value!r}")
    return str(int(d))


NUMERIC_PROFILES = {
    "line": _canon_line,
    "probability": _canon_probability,
    "price": _canon_price,
    "count": _canon_count,
}


def canonical_number(value: Union[int, str, Decimal], profile: str) -> str:
    try:
        fn = NUMERIC_PROFILES[profile]
    except KeyError as exc:
        raise NumericProfileError(f"unknown numeric profile: {profile!r}") from exc
    return fn(value)


@dataclass(frozen=True)
class GovernedNumber:
    """A numeric value bound to a governed profile; canonicalizes to a decimal
    string at the profile's scale."""
    value: Union[int, str, Decimal]
    profile: str

    def canonical(self) -> str:
        return canonical_number(self.value, self.profile)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """Grain-specific identity, PER ROW (§5). The envelope carries no identity.

    Governed identity-profile fields (§5 + R14b) make each quality auditable:
      * `PROVIDER_ID`     → `ext.provider_namespace` + `ext.provider_team_id` (a
        governed provider id, never a bare name).
      * `DECLARED_COMPOSITE` → `profile` + `profile_version` + `collision_proof`
        (+ `collision_tested`), plus the grain's declared components.
      * `ALIAS_RESOLVED`  → `ext.alias_ref` + `ext.alias_version` (curated registry).
      * `NAME_ONLY`/`AMBIGUOUS`/`UNRESOLVED` → a name alone; fails closed (R13)."""
    grain: IdentityGrain
    base: Dict[str, Any]
    ext: Dict[str, Any]
    identity_quality: IdentityQuality
    collision_tested: bool
    key: str
    profile: Optional[str] = None            # DECLARED_COMPOSITE: declared key profile
    profile_version: Optional[str] = None    # DECLARED_COMPOSITE: profile version
    collision_proof: Optional[str] = None    # DECLARED_COMPOSITE: declared collision proof


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


def has_tamper_evidence_metadata(integ: Integrity) -> bool:
    """True iff the DECLARED metadata is structurally complete for tamper-evidence
    (a mechanism other than `none` AND some proof material present). This is NOT a
    verification and does NOT assert `tamper_evident=true` — only a later verifier
    that actually checks the proof may make that claim. The name says 'metadata'
    deliberately: structure present, nothing verified."""
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


@dataclass(frozen=True)
class ProjectionRoot:
    """Immutable, serialized reference binding a user_safe projection to the internal
    root it derives from (so a projection cannot be re-pointed at a different root
    later). Validated against the supplied root by the projection validator."""
    root_receipt_id: str
    root_conclusion_hash: str
    projection_type: str            # "evidence" | "render"


@dataclass(frozen=True)
class Claim:
    """A GOVERNED user-safe claim: a stable code + governed params + the supporting
    receipt ids it derives from. Human prose lives separately in `render_prose` and is
    NOT the governed claim."""
    claim_code: str
    params: Dict[str, Any] = field(default_factory=dict)
    support_refs: tuple = ()


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
    sort_rule_id: Optional[str] = None       # governed ordering rule in force
    sort_rule_version: Optional[str] = None   # its version


@dataclass
class SourceHealthBody:
    """Body of a `source_health` receipt (§7 ref target). ONE governed state of
    record (`state: HealthState`); `synchronized` is derived from it, never a second
    authoritative field. `detail` is non-authoritative metadata and MUST NOT carry a
    `state` key (no second source of truth)."""
    state: HealthState
    checked_at: str                           # instant[UTC]
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def synchronized(self) -> bool:
        return self.state == HealthState.SYNCHRONIZED


@dataclass
class RenderBody:
    """Body of a `render` receipt: it references the board evidence receipt and
    pins that evidence's conclusion + membership hash (forward-only render→evidence,
    Rev-2.1 #2). Render carries no new authoritative conclusion of its own."""
    evidence_ref: str                         # the board live_evidence receipt_id
    conclusion_hash: str                      # the evidence receipt's conclusion_hash
    membership_hash: str                      # the evidence board's membership_hash


@dataclass
class CorrectionBody:
    """Body of a `correction` receipt (§6). The authoritative link is the envelope's
    `supersedes` (receipt_id); `supersedes_seq` (envelope) MUST equal the superseded
    receipt's `created_seq` (R15b, cross-receipt — checked by the lineage validator)."""
    change_kind: ChangeKind
    before: Dict[str, Any]
    after: Optional[Dict[str, Any]] = None    # required unless change_kind == retraction
    cause_clock: Optional[Dict[str, Any]] = None


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
    claims: Optional[List[str]] = None               # user_safe RENDER PROSE only (not governed)
    claim_records: Optional[List["Claim"]] = None    # user_safe GOVERNED claims
    projection_root: Optional["ProjectionRoot"] = None  # user_safe binding to its internal root


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
# Membership hash + hex-digest shape.
# ---------------------------------------------------------------------------

# Members are the admitted entities (§2 roll-up Members = RENDERED + SUPPRESSED).
MEMBER_LEAVES = frozenset({Leaf.RENDERED, Leaf.SUPPRESSED})

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_hex64(s: Any) -> bool:
    return isinstance(s, str) and bool(_HEX64_RE.match(s))


def canonical_identity(idn: Identity) -> Dict[str, Any]:
    """The GOVERNED, presentation-free identity projection used for authoritative
    membership. It contains only governed fields per quality — never the free-form
    display `key` or a display name:
      * PROVIDER_ID → provider namespace + provider entity id;
      * DECLARED_COMPOSITE/COMPOSITE_NAME_EVENT → profile + version + declared
        components (+ event_id for team_side);
      * ALIAS_RESOLVED → alias-registry ref + version + the resolved canonical id.
    A non-authoritative quality (NAME_ONLY/AMBIGUOUS/UNRESOLVED) has no governed
    identity; it falls back to the key only so the projection is total (such rows
    fail closed upstream and are never admitted members)."""
    base = idn.base if isinstance(idn.base, dict) else {}
    ext = idn.ext if isinstance(idn.ext, dict) else {}
    out: Dict[str, Any] = {
        "grain": idn.grain.value if isinstance(idn.grain, IdentityGrain) else None,
        "quality": idn.identity_quality.value if isinstance(idn.identity_quality, IdentityQuality) else None,
        "sport": base.get("sport"), "season": base.get("season"),
    }
    q = idn.identity_quality
    if q == IdentityQuality.PROVIDER_ID:
        out["provider_namespace"] = ext.get("provider_namespace")
        out["provider_entity_id"] = ext.get("provider_team_id") or ext.get("provider_entity_id")
    elif q in _COMPOSITE_IDENTITY:
        out["profile"] = idn.profile
        out["profile_version"] = idn.profile_version
        comps: Dict[str, Any] = {}
        if isinstance(idn.grain, IdentityGrain) and idn.grain in _GRAIN_REQUIRED_EXT:
            for k in _GRAIN_REQUIRED_EXT[idn.grain]:
                comps[k] = ext.get(k)
        if idn.grain == IdentityGrain.TEAM_SIDE:
            out["event_id"] = base.get("event_id")
        out["components"] = comps
    elif q == IdentityQuality.ALIAS_RESOLVED:
        out["alias_ref"] = ext.get("alias_ref")
        out["alias_version"] = ext.get("alias_version")
        out["resolved"] = ext.get("resolved")
    else:
        out["name"] = _norm_str(idn.key) if isinstance(idn.key, str) else None
    return out


def compute_membership_hash(batch_receipt: Receipt) -> str:
    """The board's membership-hash domain: the ORDERED admitted-member IDENTITIES of
    the referenced disposition batch, in the batch's authoritative order. It hashes
    ONLY the governed `canonical_identity` of each member (RENDERED or SUPPRESSED) —
    NOT the leaf and NOT a display label. So RENDERED↔SUPPRESSED (a presentation
    distinction that belongs to the later render receipt) does not change it, while a
    member's identity, the membership set, or the members' order does. Non-member
    rows (NONMEMBER/EXCLUDED/UNAVAILABLE/INDETERMINATE/FAILED) are excluded."""
    body = batch_receipt.body
    if not isinstance(body, EntityDispositionBatch):
        raise TypeError("membership hash requires an EntityDispositionBatch")
    members = [canonical_identity(r.identity)
               for r in body.rows if isinstance(r.leaf, Leaf) and r.leaf in MEMBER_LEAVES]
    return hashlib.sha256(_dumps(members)).hexdigest()


# ---------------------------------------------------------------------------
# Strict UTC instant validation (§ conventions: instant[UTC]).
# ---------------------------------------------------------------------------

# The approved instant[UTC] form is EXACTLY `YYYY-MM-DDTHH:MM:SSZ` — canonical `Z`,
# second precision, no numeric offset, no fractional seconds (§ Conventions).
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _valid_utc(s: Any) -> bool:
    if not isinstance(s, str) or not _UTC_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return True


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
            or not isinstance(v.minor, int) or isinstance(v.major, bool) \
            or isinstance(v.minor, bool):
        errs.append("schema_version must be {major:int, minor:int} (no booleans)")
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
    # BOTH digests are REQUIRED (§1), MUST be correctly-sized lowercase hex, and MUST
    # match the recomputed canonical digests (non-throwing).
    if integ.content_hash is None:
        errs.append("integrity.content_hash is required (seal the receipt)")
    elif not _is_hex64(integ.content_hash):
        errs.append("integrity.content_hash must be a 64-char lowercase hex digest")
    else:
        try:
            if integ.content_hash != compute_content_hash(receipt):
                errs.append("declared integrity.content_hash does not match canonical content")
        except Exception as exc:  # malformed canonicalization → error, never raise
            errs.append(f"content canonicalization failed: {type(exc).__name__}: {exc}")
    if receipt.conclusion_hash is None:
        errs.append("conclusion_hash is required (seal the receipt)")
    elif not _is_hex64(receipt.conclusion_hash):
        errs.append("conclusion_hash must be a 64-char lowercase hex digest")
    else:
        try:
            if receipt.conclusion_hash != compute_conclusion_hash(receipt):
                errs.append("declared conclusion_hash does not match canonical conclusion")
        except Exception as exc:
            errs.append(f"conclusion canonicalization failed: {type(exc).__name__}: {exc}")


def _valid_resolved_identity(resolved: Any) -> bool:
    """A resolved canonical identity for ALIAS_RESOLVED: a governed mapping carrying
    a non-empty provider namespace + provider entity id (the alias actually resolves
    to a real entity). Format-checked, not merely truthy — a name string or an empty/
    partial map is not a resolved identity."""
    if not isinstance(resolved, dict):
        return False
    ns = resolved.get("provider_namespace")
    eid = resolved.get("provider_entity_id")
    return isinstance(ns, str) and bool(ns.strip()) and isinstance(eid, str) and bool(eid.strip())


def _check_identity(idn: Identity, expected_grain: Optional[IdentityGrain],
                    where: str, errs: List[str]) -> None:
    if not isinstance(idn, Identity):
        errs.append(f"{where}: identity must be an Identity record")
        return
    if not isinstance(idn.grain, IdentityGrain):
        errs.append(f"{where}: identity.grain must be an IdentityGrain")
    elif expected_grain is not None and idn.grain != expected_grain:
        errs.append(f"{where}: identity.grain {idn.grain.value} does not match the universe's "
                    f"bound grain {expected_grain.value} (R14b)")
    if not isinstance(idn.identity_quality, IdentityQuality):
        errs.append(f"{where}: identity.identity_quality must be an IdentityQuality")
    if not idn.key or not isinstance(idn.key, str):
        errs.append(f"{where}: identity.key required")
    if not isinstance(idn.base, dict) or not idn.base.get("sport") or not idn.base.get("season"):
        errs.append(f"{where}: identity.base must carry sport + season")
    ext = idn.ext if isinstance(idn.ext, dict) else {}
    q = idn.identity_quality
    # Per-quality governed identity profiles (§5 + R14b) — makes each quality auditable
    # so a bare team name cannot masquerade as a PROVIDER_ID.
    if q == IdentityQuality.PROVIDER_ID:
        if not ext.get("provider_namespace") or not ext.get("provider_team_id"):
            errs.append(f"{where}: PROVIDER_ID requires ext.provider_namespace + "
                        "ext.provider_team_id (a bare name is NAME_ONLY)")
    elif q in _COMPOSITE_IDENTITY:
        if not idn.collision_tested:
            errs.append(f"{where}: {q.value} requires collision_tested=true (R14)")
        if not idn.profile or not idn.profile_version or not idn.collision_proof:
            errs.append(f"{where}: {q.value} requires profile + profile_version + collision_proof")
        # grain-declared components
        if isinstance(idn.grain, IdentityGrain) and idn.grain in _GRAIN_REQUIRED_EXT \
                and any(k not in ext for k in _GRAIN_REQUIRED_EXT[idn.grain]):
            errs.append(f"{where}: {idn.grain.value} {q.value} must declare components "
                        f"{list(_GRAIN_REQUIRED_EXT[idn.grain])}")
    elif q == IdentityQuality.ALIAS_RESOLVED:
        if not ext.get("alias_ref") or not ext.get("alias_version"):
            errs.append(f"{where}: ALIAS_RESOLVED requires ext.alias_ref + ext.alias_version")
        resolved = ext.get("resolved")
        if not _valid_resolved_identity(resolved):
            errs.append(f"{where}: ALIAS_RESOLVED requires a nonempty governed ext.resolved "
                        "canonical identity {provider_namespace, provider_entity_id} "
                        "(provenance alone is not an identity)")


def _check_reason(code: str, def_version: int, expected_category: "SemanticCategory",
                  where: str, errs: List[str]) -> None:
    # Shape: stable UPPER_SNAKE identifier (R8). This alone does NOT prove the code
    # is non-dynamic (e.g. SORTED_BY_STREAK_DESC is well-shaped) — the registry does.
    if not isinstance(code, str) or not _REASON_CODE_RE.match(code or ""):
        errs.append(f"{where}: reason_code has an invalid code shape (UPPER_SNAKE only): {code!r}")
    elif code not in REASON_CODES:
        errs.append(f"{where}: reason_code {code!r} is not in the allowlisted registry "
                    "(dynamic/unregistered codes are rejected, R8)")
    elif REASON_CODES[code] != expected_category:
        errs.append(f"{where}: reason_code {code!r} is a {REASON_CODES[code].value} code used "
                    f"where a {expected_category.value} is required")
    if not isinstance(def_version, int) or isinstance(def_version, bool) or def_version < 1:
        errs.append(f"{where}: reason_def_version must be an int >= 1")


def _check_entity_disposition_batch(b: EntityDispositionBatch, receipt: Receipt,
                                    errs: List[str]) -> None:
    # The board/expected universe disposition batch binds to the `team` grain (R14b).
    if receipt.universe.grain != "team":
        errs.append("entity_disposition board batch MUST use universe.grain 'team' (R14b)")
    seen, seen_ci = set(), set()
    for i, r in enumerate(b.rows):
        w = f"rows[{i}]"
        if not r.entity_ref:
            errs.append(f"{w}: entity_ref required")
        # Exactly-one leaf per CANONICAL IDENTITY (R4) — entity_ref is only a display
        # handle, so the same governed team under two refs is still a duplicate.
        if r.entity_ref in seen:
            errs.append(f"{w}: duplicate entity_ref {r.entity_ref!r} — an entity MUST carry "
                        "exactly one leaf (R4)")
        seen.add(r.entity_ref)
        if isinstance(r.identity, Identity):
            ci = _dumps(canonical_identity(r.identity))
            if ci in seen_ci:
                errs.append(f"{w}: duplicate canonical identity — exactly one leaf per canonical "
                            "identity (R4), not per display entity_ref")
            seen_ci.add(ci)
        # Firewall: leaf must be a Leaf; a stage outcome / roll-up used as a leaf is rejected.
        if isinstance(r.leaf, StageOutcome) or (
                isinstance(r.leaf, Enum) and r.leaf.value in _STAGE_NAMES):
            errs.append(f"{w}: stage outcome used as a terminal leaf")
        elif isinstance(r.leaf, str) and r.leaf in _ROLLUP_NAMES:
            errs.append(f"{w}: roll-up {r.leaf!r} is not a terminal leaf (R5)")
        elif not isinstance(r.leaf, Leaf):
            errs.append(f"{w}: leaf must be a Leaf")
        _check_reason(r.reason_code, r.reason_def_version, SemanticCategory.LEAF, w, errs)
        _check_identity(r.identity, IdentityGrain.TEAM, w, errs)
        # R13 fail-closed identity → only UNAVAILABLE/INDETERMINATE.
        if isinstance(r.identity, Identity) and isinstance(r.leaf, Leaf) \
                and r.identity.identity_quality in _FAIL_CLOSED_IDENTITY \
                and r.leaf not in _FAIL_CLOSED_LEAVES:
            errs.append(f"{w}: identity {r.identity.identity_quality.value} must fail closed "
                        "(leaf UNAVAILABLE/INDETERMINATE), not " + r.leaf.value)
        _check_params(r.params, w, errs)


def _check_decision_stage_batch(b: DecisionStageBatch, receipt: Receipt,
                                errs: List[str]) -> None:
    # The decision universe binds to the `team_side` grain + the decision universe (R14b).
    if receipt.universe.grain != "team_side_decision":
        errs.append("decision-stage batch MUST use universe.grain 'team_side_decision' (R14b)")
    seen, seen_ci = set(), set()
    for i, r in enumerate(b.rows):
        w = f"rows[{i}]"
        if not r.entity_ref:
            errs.append(f"{w}: entity_ref required")
        if r.entity_ref in seen:
            errs.append(f"{w}: duplicate entity_ref {r.entity_ref!r} — exactly one stage "
                        "outcome per decision")
        seen.add(r.entity_ref)
        if isinstance(r.identity, Identity):
            ci = _dumps(canonical_identity(r.identity))
            if ci in seen_ci:
                errs.append(f"{w}: duplicate canonical identity — exactly one stage outcome per "
                            "canonical identity, not per display entity_ref")
            seen_ci.add(ci)
        # Firewall (other direction): a presentation leaf used as a stage outcome is rejected.
        if isinstance(r.stage_outcome, Leaf) or (
                isinstance(r.stage_outcome, Enum) and r.stage_outcome.value in _LEAF_NAMES):
            errs.append(f"{w}: presentation leaf used as a decision-stage outcome")
        elif not isinstance(r.stage_outcome, StageOutcome):
            errs.append(f"{w}: stage_outcome must be a StageOutcome")
        _check_reason(r.reason_code, r.reason_def_version, SemanticCategory.STAGE_OUTCOME, w, errs)
        _check_identity(r.identity, IdentityGrain.TEAM_SIDE, w, errs)
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
    if not _is_hex64(b.membership_hash):
        errs.append("board.membership_hash must be a 64-char lowercase hex digest")
    if not isinstance(b.per_leaf_counts, dict):
        errs.append("board.per_leaf_counts must be a map")
        return
    for k, n in b.per_leaf_counts.items():
        if k not in _LEAF_NAMES:
            errs.append(f"board.per_leaf_counts key {k!r} is not a leaf")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(f"board.per_leaf_counts[{k!r}] must be a non-negative int")
    if not isinstance(b.expected_count, int) or isinstance(b.expected_count, bool) \
            or b.expected_count < 0:
        errs.append("board.expected_count must be a non-negative, non-boolean integer")
    total = sum(n for n in b.per_leaf_counts.values() if isinstance(n, int) and not isinstance(n, bool))
    if isinstance(b.expected_count, int) and not isinstance(b.expected_count, bool) \
            and total != b.expected_count:
        errs.append(f"board conservation: per-leaf counts sum to {total} != expected_count "
                    f"{b.expected_count} (R20)")
    # §7 R18: a board MUST reference its disposition batch + source_health.
    if receipt.refs is None or not receipt.refs.entity_dispositions:
        errs.append("board live_evidence MUST reference an entity_dispositions batch (refs, R18)")
    if receipt.refs is None or not receipt.refs.source_health:
        errs.append("board live_evidence MUST reference a source_health receipt (refs, R18)")


def _check_source_health(b: SourceHealthBody, errs: List[str]) -> None:
    if not isinstance(b.state, HealthState):
        errs.append("source_health.state must be a HealthState (the one governed state)")
    if not _valid_utc(b.checked_at):
        errs.append("source_health.checked_at must be a tz-aware UTC instant")
    if not isinstance(b.detail, dict):
        errs.append("source_health.detail must be a map")
    elif "state" in b.detail:
        errs.append("source_health.detail MUST NOT carry a second authoritative 'state' "
                    "(one governed state of record only)")


def _check_render(b: RenderBody, receipt: Receipt, errs: List[str]) -> None:
    if not b.evidence_ref or not str(b.evidence_ref).strip():
        errs.append("render.evidence_ref required (the board evidence receipt_id)")
    if not _is_hex64(b.conclusion_hash):
        errs.append("render.conclusion_hash must be a 64-char lowercase hex digest")
    if not _is_hex64(b.membership_hash):
        errs.append("render.membership_hash must be a 64-char lowercase hex digest")
    # Forward-only render→evidence: the envelope ref MUST point at the same evidence.
    if receipt.refs is None or receipt.refs.evidence != b.evidence_ref:
        errs.append("render receipt MUST reference its evidence receipt (refs.evidence == "
                    "body.evidence_ref)")


def _check_correction(b: CorrectionBody, receipt: Receipt, errs: List[str]) -> None:
    if not isinstance(b.change_kind, ChangeKind):
        errs.append("correction.change_kind must be a ChangeKind")
    if not isinstance(b.before, dict):
        errs.append("correction.before must be a map")
    if isinstance(b.change_kind, ChangeKind) and b.change_kind != ChangeKind.RETRACTION \
            and b.after is None:
        errs.append("correction.after is required unless change_kind == retraction")
    # The envelope's supersedes (receipt_id) + supersedes_seq are required for a
    # correction (enforced in _check_supersession); R15b equality is cross-receipt
    # and is checked by validate_correction_lineage.


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
    if receipt.input_hashes is not None:
        if not isinstance(receipt.input_hashes, list) \
                or any(not _is_hex64(h) for h in receipt.input_hashes):
            errs.append("input_hashes must be a list of 64-char lowercase hex digests")
    # A factual or governed-model authority must be reproducible — it may not be
    # NON_REPLAYABLE (Constitution §8/§9).
    if receipt.replay_class == ReplayClass.NON_REPLAYABLE \
            and receipt.authority_class in (AuthorityClass.FACT, AuthorityClass.GOVERNED_MODEL):
        errs.append(f"authority_class={receipt.authority_class.value} MUST NOT be NON_REPLAYABLE")


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

        # receipt_id MUST be an opaque UUID (P2A-1), not a human slug.
        if isinstance(receipt.receipt_id, str):
            try:
                uuid.UUID(receipt.receipt_id)
            except (ValueError, AttributeError, TypeError):
                errs.append("receipt_id must be an opaque UUID (P2A-1)")
        if isinstance(receipt.surface_id, str) and not receipt.surface_id.strip():
            errs.append("surface_id must be non-empty")
        if isinstance(receipt.created_seq, int) and not isinstance(receipt.created_seq, bool) \
                and receipt.created_seq <= 0:
            errs.append("created_seq must be a positive integer")
        if isinstance(receipt.created_at, str) and not _valid_utc(receipt.created_at):
            errs.append("created_at must be a tz-aware UTC instant (YYYY-MM-DDTHH:MM:SSZ)")
        if isinstance(receipt.universe, Universe):
            if not receipt.universe.grain or not receipt.universe.grain.strip():
                errs.append("universe.grain required")
            if not receipt.universe.id or not receipt.universe.id.strip():
                errs.append("universe.id required")
            if not receipt.universe.version or not receipt.universe.version.strip():
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
                        "not-yet-constructed")
        elif isinstance(receipt.body, EntityDispositionBatch):
            if receipt.receipt_kind != ReceiptKind.ENTITY_DISPOSITION:
                errs.append("EntityDispositionBatch requires receipt_kind=entity_disposition")
            _check_entity_disposition_batch(receipt.body, receipt, errs)
        elif isinstance(receipt.body, LiveEvidenceBoard):
            if receipt.receipt_kind != ReceiptKind.LIVE_EVIDENCE:
                errs.append("LiveEvidenceBoard requires receipt_kind=live_evidence")
            _check_board(receipt.body, receipt, errs)
        elif isinstance(receipt.body, DecisionStageBatch):
            if receipt.receipt_kind != ReceiptKind.LIVE_EVIDENCE:
                errs.append("DecisionStageBatch requires receipt_kind=live_evidence "
                            "(decision-stage evidence)")
            _check_decision_stage_batch(receipt.body, receipt, errs)
        elif isinstance(receipt.body, SourceHealthBody):
            if receipt.receipt_kind != ReceiptKind.SOURCE_HEALTH:
                errs.append("SourceHealthBody requires receipt_kind=source_health")
            _check_source_health(receipt.body, errs)
        elif isinstance(receipt.body, RenderBody):
            if receipt.receipt_kind != ReceiptKind.RENDER:
                errs.append("RenderBody requires receipt_kind=render")
            _check_render(receipt.body, receipt, errs)
        elif isinstance(receipt.body, CorrectionBody):
            if receipt.receipt_kind != ReceiptKind.CORRECTION:
                errs.append("CorrectionBody requires receipt_kind=correction")
            _check_correction(receipt.body, receipt, errs)
        else:
            errs.append(f"unsupported body type: {type(receipt.body).__name__}")

        _check_integrity(receipt, errs)
    except Exception as exc:  # last-resort guard — the API never raises
        errs.append(f"validation aborted on malformed input: {type(exc).__name__}: {exc}")

    return ValidationResult(not errs, errs)


def reconcile_board(board_receipt: Receipt, batch_receipt: Receipt) -> ValidationResult:
    """Cross-receipt binding (§3/§7, R18/R20). Both receipts MUST first pass their
    own structural validation — reconcile NEVER returns clean on a malformed or
    duplicate-bearing input. Then the board and its referenced batch MUST share the
    complete governed build context (schema major, build_id, config_version,
    rule_versions, surface, universe), the board MUST reference the batch, the board's
    per-leaf counts MUST equal the batch's actual tally, AND the board's
    `membership_hash` MUST equal the hash recomputed from the batch's ordered members.
    Non-throwing."""
    errs: List[str] = []
    try:
        if not isinstance(board_receipt.body, LiveEvidenceBoard):
            return ValidationResult(False, ["board_receipt is not a LiveEvidenceBoard"])
        if not isinstance(batch_receipt.body, EntityDispositionBatch):
            return ValidationResult(False, ["batch_receipt is not an EntityDispositionBatch"])
        # Gate: neither receipt may be malformed (a duplicate/invalid batch cannot
        # silently reconcile).
        vb = validate_receipt(board_receipt)
        vt = validate_receipt(batch_receipt)
        if not vb.ok:
            errs.append(f"board failed structural validation: {vb.errors}")
        if not vt.ok:
            errs.append(f"batch failed structural validation: {vt.errors}")
        if errs:
            return ValidationResult(False, errs)

        if board_receipt.refs is None or \
                board_receipt.refs.entity_dispositions != batch_receipt.receipt_id:
            errs.append("board does not reference this entity_dispositions batch")
        # Complete governed build context.
        if board_receipt.surface_id != batch_receipt.surface_id:
            errs.append("board and batch surface_id differ")
        if board_receipt.universe != batch_receipt.universe:
            errs.append("board and batch universe differ")
        if board_receipt.schema_version.major != batch_receipt.schema_version.major:
            errs.append("board and batch schema major differ")
        bv, tv = board_receipt.versions, batch_receipt.versions
        if isinstance(bv, Versions) and isinstance(tv, Versions):
            if bv.build_id != tv.build_id:
                errs.append("board and batch build_id differ")
            if bv.config_version != tv.config_version:
                errs.append("board and batch config_version differ")
            if bv.rule_versions != tv.rule_versions:
                errs.append("board and batch rule_versions differ")
        # Count reconciliation (§3/R20).
        tally: Dict[str, int] = {}
        for r in batch_receipt.body.rows:
            if isinstance(r.leaf, Leaf):
                tally[r.leaf.value] = tally.get(r.leaf.value, 0) + 1
        declared = {k: v for k, v in board_receipt.body.per_leaf_counts.items() if v}
        actual = {k: v for k, v in tally.items() if v}
        if declared != actual:
            errs.append(f"board per-leaf counts {declared} != batch tally {actual}")
        # Membership-hash binding (real, not merely counted).
        if board_receipt.body.membership_hash != compute_membership_hash(batch_receipt):
            errs.append("board membership_hash does not match the batch's ordered members")
    except Exception as exc:
        errs.append(f"reconcile aborted: {type(exc).__name__}: {exc}")
    return ValidationResult(not errs, errs)


__all__ = [
    "CONTRACT_MAJOR", "CONTRACT_MINOR", "SchemaVersion",
    "ReceiptKind", "SUPPORTED_RECEIPT_KINDS", "NOT_YET_CONSTRUCTED_KINDS",
    "AuthorityClass", "ReplayClass", "Leaf", "StageOutcome", "IdentityQuality",
    "IdentityGrain", "SourceUpdatedStatus", "IntegrityMechanism", "SemanticCategory",
    "ChangeKind", "Projection", "HASH_ALGORITHMS", "HealthState",
    "Decimal", "NumericProfileError", "NUMERIC_PROFILES", "canonical_number", "GovernedNumber",
    "Identity", "Clocks", "Versions", "Integrity", "has_tamper_evidence_metadata",
    "Universe", "Refs", "ProjectionRoot", "Claim", "REASON_CODES",
    "EntityDisposition", "DecisionStageRow",
    "EntityDispositionBatch", "DecisionStageBatch", "LiveEvidenceBoard",
    "SourceHealthBody", "RenderBody", "CorrectionBody",
    "Receipt",
    "canonical_content_bytes", "canonical_conclusion_bytes",
    "compute_content_hash", "compute_conclusion_hash", "compute_membership_hash",
    "canonical_identity", "MEMBER_LEAVES", "seal_hashes",
    "ValidationResult", "validate_receipt", "reconcile_board",
]
