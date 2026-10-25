"""Decision Integrity — shared contract library (Phase 2B, Slice 1).

PURE CONTRACT LIBRARY. This module defines the receipt contracts from
`docs/decision_integrity_phase2a_contracts.md` as code, plus deterministic
canonical serialization, content/conclusion hashing, and a STRUCTURAL validator.

Deliberate non-scope (Slice 1 acceptance boundaries):
  * No application / route / template / builder / cache / database / runtime dir /
    environment flag / production integration is imported or touched here.
  * No network or provider access.
  * No automatic receipt persistence — nothing here writes a receipt anywhere.
  * No transition-kind implementation.
  * No tamper-evidence CLAIM and no proof GENERATION. `integrity.proof` is validated
    for shape only (never produced, never verified) — see `validate_receipt`.
  * Importing this module performs NO filesystem or environment side effects: it
    imports only the stdlib (dataclasses, enum, hashlib, json, unicodedata, typing)
    and defines types/functions. It reads no file and no environment variable.

Two universes, kept rigorously distinct (Rev 2.3):
  * DECISION-STAGE receipt  — grain `team_side_decision`. Supporting stage evidence
    consumed by calculation, NEVER rendered. Carries STAGE OUTCOMES only.
  * BOARD receipt           — grain `team`. The terminal-disposition universe; each
    expected entity gets exactly one TERMINAL DISPOSITION. References the
    decision-stage receipt as evidence.

Hashing (Rev 2.1 #3, P2A-1/P2A-4):
  * `content_hash`    — SHA-256 over the canonical form of the ENTIRE instance
    EXCEPT `integrity.content_hash` and `integrity.proof` (self-reference + the
    tamper seal are excluded). Any change to a stored field changes it.
  * `conclusion_hash` — SHA-256 over the canonical form of the CONCLUSION subtree
    only (universe grain+id and the sorted conclusion rows). Receipt-instance
    metadata (clocks, seq, id, projection, classes) does NOT change it.
  * `content_hash` and `conclusion_hash` are SEPARATE and independent.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Versioning (structured {major, minor}, Rev-2.1). Unknown major fails closed;
# a newer minor within a known major is permitted (forward-compatible).
# ---------------------------------------------------------------------------

CONTRACT_MAJOR = 1
CONTRACT_MINOR = 0
_KNOWN_MAJORS = frozenset({1})


@dataclass(frozen=True)
class SchemaVersion:
    major: int
    minor: int

    def as_dict(self) -> Dict[str, int]:
        return {"major": self.major, "minor": self.minor}


# ---------------------------------------------------------------------------
# Enums. Stage outcomes and terminal dispositions are DISJOINT by construction
# (distinct types AND disjoint value sets) so one can never masquerade as the
# other — the validator enforces both directions.
# ---------------------------------------------------------------------------


class ReceiptKind(Enum):
    DECISION_STAGE = "decision_stage"
    BOARD = "board"


class StageOutcome(Enum):
    """Decision-grain stage outcomes. NEVER rendered to a user."""
    GRADED = "GRADED"
    PUSH = "PUSH"
    VOID = "VOID"
    NO_LINE = "NO_LINE"
    OVERDUE = "OVERDUE"
    MALFORMED = "MALFORMED"
    OUTSIDE_BOUNDARY = "OUTSIDE_BOUNDARY"


class TerminalDisposition(Enum):
    """Board-grain terminal dispositions. The user-facing leaf registry."""
    RENDERED = "RENDERED"
    SUPPRESSED = "SUPPRESSED"
    NONMEMBER = "NONMEMBER"
    UNAVAILABLE = "UNAVAILABLE"
    INDETERMINATE = "INDETERMINATE"
    FAILED = "FAILED"
    EXCLUDED = "EXCLUDED"


# Disjointness guard (checked at import; a pure assertion, no side effect).
_STAGE_NAMES = frozenset(o.value for o in StageOutcome)
_TERMINAL_NAMES = frozenset(d.value for d in TerminalDisposition)
assert _STAGE_NAMES.isdisjoint(_TERMINAL_NAMES), "stage/terminal value sets overlap"


class IdentityQuality(Enum):
    PROVIDER_ID = "PROVIDER_ID"
    DECLARED_COMPOSITE = "DECLARED_COMPOSITE"
    COMPOSITE_NAME_EVENT = "COMPOSITE_NAME_EVENT"
    ALIAS_RESOLVED = "ALIAS_RESOLVED"
    NAME_ONLY = "NAME_ONLY"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


# Identity qualities that MUST fail closed — a receipt with such identity may not
# assert a graded stage outcome or a RENDERED terminal disposition (Constitution
# R13 / §6: curated-exact only, never fuzzy).
_FAIL_CLOSED_IDENTITY = frozenset(
    {IdentityQuality.NAME_ONLY, IdentityQuality.AMBIGUOUS, IdentityQuality.UNRESOLVED}
)


class Projection(Enum):
    INTERNAL = "internal"
    USER_SAFE = "user_safe"


class AuthorityClass(Enum):
    FACT = "fact"
    CALCULATED = "calculated"
    RESEARCH_ONLY = "research_only"


class ReplayClass(Enum):
    EVIDENCE_EQUIVALENT = "EVIDENCE_EQUIVALENT"
    DETERMINISTIC_RECOMPUTE = "DETERMINISTIC_RECOMPUTE"


class SourceUpdatedStatus(Enum):
    """Why/whether a provider source-update clock is present. The literal string
    'UNKNOWN' is NOT a member — an absent clock is null + NOT_PROVIDED/UNRESOLVED
    (Rev-2.1 #5), never a magic string."""
    PROVIDED = "PROVIDED"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNRESOLVED = "UNRESOLVED"


_SOURCE_ABSENT_STATUSES = frozenset(
    {SourceUpdatedStatus.NOT_PROVIDED, SourceUpdatedStatus.UNRESOLVED}
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Universe:
    grain: str          # "team_side_decision" (decision) | "team" (board)
    id: str             # e.g. "nfl_ats_decisions_2026" / "nfl_ats_board_2026"
    version: str


@dataclass(frozen=True)
class Clocks:
    """Three-clock capture (Rev-2.1 #5). `bk_captured` is a BK observation/check
    clock and is required. `source_updated` is the provider source-update clock;
    when the provider exposes none it is None and `source_updated_status` says so
    (the check clock is NEVER substituted for it). `event_effective` is the
    real-world event time (e.g. kickoff)."""
    bk_captured: str
    source_updated_status: SourceUpdatedStatus
    source_updated: Optional[str] = None
    event_effective: Optional[str] = None


@dataclass(frozen=True)
class Identity:
    quality: IdentityQuality
    key: str                                   # canonical key string for the grain
    profile: Optional[str] = None              # DECLARED_COMPOSITE: key profile
    profile_version: Optional[str] = None      # DECLARED_COMPOSITE: profile version
    collision_proof: Optional[str] = None      # DECLARED_COMPOSITE: declared proof


@dataclass
class Integrity:
    """Declared integrity metadata. The library computes `content_hash` /
    `conclusion_hash` deterministically; it NEVER produces `proof` (the tamper
    seal) and makes no tamper-evidence claim. `tamper_evident` here is a DECLARED
    flag whose only library-enforced consequence is structural: if True, `proof`
    must be present (its validity is out of scope)."""
    content_hash: Optional[str] = None
    conclusion_hash: Optional[str] = None
    proof: Optional[str] = None
    tamper_evident: bool = False


@dataclass(frozen=True)
class DecisionOutcome:
    """One decision-grain record: a stage outcome, never a presentation leaf."""
    entity_ref: str
    stage_outcome: StageOutcome
    reason_code: str


@dataclass(frozen=True)
class BoardDisposition:
    """One board-grain record: a terminal disposition, never a stage outcome."""
    entity_ref: str
    disposition: TerminalDisposition
    reason_code: str


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass
class _Envelope:
    receipt_id: str                 # caller-supplied (no auto-generation here)
    schema_version: SchemaVersion
    surface_id: str
    universe: Universe
    authority_class: AuthorityClass
    replay_class: ReplayClass
    projection: Projection
    clocks: Clocks
    identity: Identity
    created_seq: int
    integrity: Integrity = field(default_factory=Integrity)
    supersedes_seq: Optional[int] = None   # the SUPERSEDED receipt's created_seq
    disclosures: Optional[List[str]] = None


@dataclass
class DecisionStageReceipt(_Envelope):
    kind: ReceiptKind = ReceiptKind.DECISION_STAGE
    outcomes: List[DecisionOutcome] = field(default_factory=list)


@dataclass
class BoardReceipt(_Envelope):
    kind: ReceiptKind = ReceiptKind.BOARD
    dispositions: List[BoardDisposition] = field(default_factory=list)
    # The board receipt references the decision-stage receipt as evidence.
    decision_stage_ref: Optional[str] = None


Receipt = Any  # DecisionStageReceipt | BoardReceipt


# ---------------------------------------------------------------------------
# Canonicalization — deterministic primitive tree + stable bytes.
# ---------------------------------------------------------------------------

_CONTENT_EXCLUDE: Tuple[Tuple[str, str], ...] = (
    ("integrity", "content_hash"),   # self-reference
    ("integrity", "proof"),          # the tamper seal
)


def _norm_str(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _to_primitive(obj: Any) -> Any:
    """Recursively convert dataclasses / enums / scalars to a canonical primitive
    tree. Strings are NFC-normalized. Numbers keep their int-vs-float profile.
    NaN/Inf are rejected (not canonicalizable)."""
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError("NaN/Inf is not canonicalizable")
        return obj
    if isinstance(obj, str):
        return _norm_str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        out: Dict[str, Any] = {}
        for f in fields(obj):
            out[f.name] = _to_primitive(getattr(obj, f.name))
        return out
    if isinstance(obj, dict):
        return {_norm_str(str(k)): _to_primitive(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_primitive(v) for v in obj]
    raise TypeError(f"uncanonicalizable type: {type(obj).__name__}")


def _drop_path(tree: Dict[str, Any], parent: str, key: str) -> None:
    sub = tree.get(parent)
    if isinstance(sub, dict):
        sub.pop(key, None)


def _dumps(tree: Any) -> bytes:
    # sort_keys gives deterministic dict ordering; ensure_ascii=False keeps NFC
    # utf-8 bytes; allow_nan=False forbids NaN/Inf; compact separators.
    return json.dumps(
        tree, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def canonical_content_bytes(receipt: Receipt) -> bytes:
    """Canonical bytes of the whole instance EXCEPT integrity.content_hash and
    integrity.proof (self-hash exclusion). The member-row collections (outcomes /
    dispositions) are semantically sets, so they are sorted deterministically —
    content_hash is independent of their insertion order."""
    tree = _to_primitive(receipt)
    for parent, key in _CONTENT_EXCLUDE:
        _drop_path(tree, parent, key)
    for list_field in ("outcomes", "dispositions"):
        rows = tree.get(list_field)
        if isinstance(rows, list):
            tree[list_field] = sorted(rows, key=_dumps)
    return _dumps(tree)


def _conclusion_rows(receipt: Receipt) -> List[List[str]]:
    if isinstance(receipt, DecisionStageReceipt):
        rows = [[_norm_str(o.entity_ref), o.stage_outcome.value] for o in receipt.outcomes]
    elif isinstance(receipt, BoardReceipt):
        rows = [[_norm_str(d.entity_ref), d.disposition.value] for d in receipt.dispositions]
    else:
        raise TypeError("unknown receipt kind")
    # Deterministic multiset ordering, independent of insertion order.
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def canonical_conclusion_bytes(receipt: Receipt) -> bytes:
    """Canonical bytes of the CONCLUSION subtree only: universe grain+id and the
    sorted conclusion rows. Excludes all instance metadata, so clocks/seq/id/
    projection/classes do not perturb the conclusion hash."""
    tree = {
        "kind": receipt.kind.value,
        "universe": {"grain": _norm_str(receipt.universe.grain),
                     "id": _norm_str(receipt.universe.id)},
        "conclusion": _conclusion_rows(receipt),
    }
    return _dumps(tree)


def compute_content_hash(receipt: Receipt) -> str:
    return hashlib.sha256(canonical_content_bytes(receipt)).hexdigest()


def compute_conclusion_hash(receipt: Receipt) -> str:
    return hashlib.sha256(canonical_conclusion_bytes(receipt)).hexdigest()


def seal_hashes(receipt: Receipt) -> Receipt:
    """Populate integrity.content_hash and integrity.conclusion_hash in place from
    the canonical forms. This is a plain digest (NOT a tamper-evidence proof): it
    does not set `proof` and makes no tamper claim. Returns the same receipt."""
    receipt.integrity.conclusion_hash = compute_conclusion_hash(receipt)
    receipt.integrity.content_hash = compute_content_hash(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Structural validator
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


def _check_version(v: SchemaVersion, errs: List[str]) -> None:
    if not isinstance(v.major, int) or not isinstance(v.minor, int):
        errs.append("schema_version.major/minor must be integers")
        return
    if v.major not in _KNOWN_MAJORS:
        errs.append(f"unknown schema major {v.major} (fail closed)")
    if v.minor < 0:
        errs.append("schema_version.minor must be >= 0")
    # A newer minor within a known major is permitted (forward-compatible) — no error.


def _check_clocks(c: Clocks, errs: List[str]) -> None:
    if not isinstance(c.bk_captured, str) or not c.bk_captured.strip():
        errs.append("clocks.bk_captured is required and must be a non-empty string")
    if not isinstance(c.source_updated_status, SourceUpdatedStatus):
        errs.append("clocks.source_updated_status must be a SourceUpdatedStatus")
        return
    if c.source_updated is None:
        if c.source_updated_status not in _SOURCE_ABSENT_STATUSES:
            errs.append("source_updated is null but status is not NOT_PROVIDED/UNRESOLVED")
    else:
        if not isinstance(c.source_updated, str) or not c.source_updated.strip():
            errs.append("source_updated, when present, must be a non-empty string")
        if c.source_updated_status != SourceUpdatedStatus.PROVIDED:
            errs.append("source_updated is present but status is not PROVIDED")
        if isinstance(c.source_updated, str) and c.source_updated.strip().upper() == "UNKNOWN":
            errs.append("literal 'UNKNOWN' is not a valid clock value (use null + status)")


def _check_identity(idn: Identity, errs: List[str]) -> None:
    if not isinstance(idn.quality, IdentityQuality):
        errs.append("identity.quality must be an IdentityQuality")
        return
    if not isinstance(idn.key, str) or not idn.key.strip():
        errs.append("identity.key is required and must be a non-empty string")
    if idn.quality == IdentityQuality.DECLARED_COMPOSITE:
        if not idn.profile or not idn.profile_version:
            errs.append("DECLARED_COMPOSITE identity requires profile + profile_version")


def _check_integrity(receipt: Receipt, errs: List[str]) -> None:
    integ = receipt.integrity
    if not isinstance(integ, Integrity):
        errs.append("integrity must be an Integrity")
        return
    # Validate DECLARED hashes against the recomputed canonical hashes. This is
    # integrity-metadata validation, not proof generation.
    if integ.content_hash is not None:
        if integ.content_hash != compute_content_hash(receipt):
            errs.append("declared integrity.content_hash does not match canonical content")
    if integ.conclusion_hash is not None:
        if integ.conclusion_hash != compute_conclusion_hash(receipt):
            errs.append("declared integrity.conclusion_hash does not match canonical conclusion")
    # Tamper-evidence: shape only. If declared tamper_evident, a proof must be
    # present. The library neither produces nor verifies the proof.
    if integ.tamper_evident and not integ.proof:
        errs.append("tamper_evident is declared true but integrity.proof is absent")


def _has_fail_closed_identity(receipt: Receipt) -> bool:
    return receipt.identity.quality in _FAIL_CLOSED_IDENTITY


def _check_decision_stage(receipt: DecisionStageReceipt, errs: List[str]) -> None:
    if receipt.universe.grain != "team_side_decision":
        errs.append("decision-stage receipt must use universe.grain 'team_side_decision'")
    for i, o in enumerate(receipt.outcomes):
        # Reject a presentation leaf used as a decision-stage outcome (both
        # directions of the stage/terminal firewall).
        if isinstance(o.stage_outcome, TerminalDisposition) or (
            isinstance(o.stage_outcome, Enum) and o.stage_outcome.value in _TERMINAL_NAMES
        ):
            errs.append(f"outcomes[{i}]: terminal disposition used as a decision-stage outcome")
            continue
        if not isinstance(o.stage_outcome, StageOutcome):
            errs.append(f"outcomes[{i}].stage_outcome must be a StageOutcome")
            continue
        if _has_fail_closed_identity(receipt) and o.stage_outcome == StageOutcome.GRADED:
            errs.append(f"outcomes[{i}]: GRADED asserted under fail-closed identity "
                        f"({receipt.identity.quality.value})")


def _check_board(receipt: BoardReceipt, errs: List[str]) -> None:
    if receipt.universe.grain != "team":
        errs.append("board receipt must use universe.grain 'team'")
    if not receipt.decision_stage_ref or not str(receipt.decision_stage_ref).strip():
        errs.append("board receipt must reference the decision-stage receipt "
                    "(decision_stage_ref)")
    for i, d in enumerate(receipt.dispositions):
        # Reject a stage outcome used as a terminal leaf.
        if isinstance(d.disposition, StageOutcome) or (
            isinstance(d.disposition, Enum) and d.disposition.value in _STAGE_NAMES
        ):
            errs.append(f"dispositions[{i}]: stage outcome used as a terminal leaf")
            continue
        if not isinstance(d.disposition, TerminalDisposition):
            errs.append(f"dispositions[{i}].disposition must be a TerminalDisposition")
            continue
        if _has_fail_closed_identity(receipt) and d.disposition == TerminalDisposition.RENDERED:
            errs.append(f"dispositions[{i}]: RENDERED asserted under fail-closed identity "
                        f"({receipt.identity.quality.value})")


def _check_projection(receipt: Receipt, errs: List[str]) -> None:
    if receipt.projection == Projection.USER_SAFE and receipt.integrity.proof is not None:
        # A user-safe projection must not carry internal-only tamper material.
        errs.append("user_safe projection must not contain integrity.proof (internal-only)")


def _check_supersession(receipt: Receipt, errs: List[str]) -> None:
    if receipt.supersedes_seq is None:
        return
    if not isinstance(receipt.supersedes_seq, int):
        errs.append("supersedes_seq must be an int (the superseded receipt's created_seq)")
        return
    if receipt.supersedes_seq >= receipt.created_seq:
        errs.append("supersedes_seq (superseded created_seq) must be < this created_seq")


def validate_receipt(receipt: Receipt) -> ValidationResult:
    """Structural validation only. Returns a ValidationResult; never raises for a
    contract violation (it raises only on a genuinely uncanonicalizable value via
    the hash checks, which indicates a malformed instance)."""
    errs: List[str] = []

    if not isinstance(receipt, (DecisionStageReceipt, BoardReceipt)):
        return ValidationResult(False, ["unknown receipt type"])
    if not isinstance(receipt.kind, ReceiptKind):
        errs.append("kind must be a ReceiptKind")

    for name, typ in (
        ("schema_version", SchemaVersion), ("surface_id", str), ("universe", Universe),
        ("authority_class", AuthorityClass), ("replay_class", ReplayClass),
        ("projection", Projection), ("clocks", Clocks), ("identity", Identity),
        ("created_seq", int), ("receipt_id", str),
    ):
        if not isinstance(getattr(receipt, name), typ):
            errs.append(f"{name} must be a {typ.__name__}")

    if isinstance(receipt.receipt_id, str) and not receipt.receipt_id.strip():
        errs.append("receipt_id must be non-empty")
    if isinstance(receipt.surface_id, str) and not receipt.surface_id.strip():
        errs.append("surface_id must be non-empty")

    if isinstance(receipt.schema_version, SchemaVersion):
        _check_version(receipt.schema_version, errs)
    if isinstance(receipt.clocks, Clocks):
        _check_clocks(receipt.clocks, errs)
    if isinstance(receipt.identity, Identity):
        _check_identity(receipt.identity, errs)

    if isinstance(receipt, DecisionStageReceipt):
        if receipt.kind != ReceiptKind.DECISION_STAGE:
            errs.append("DecisionStageReceipt.kind must be DECISION_STAGE")
        _check_decision_stage(receipt, errs)
    elif isinstance(receipt, BoardReceipt):
        if receipt.kind != ReceiptKind.BOARD:
            errs.append("BoardReceipt.kind must be BOARD")
        _check_board(receipt, errs)

    _check_projection(receipt, errs)
    _check_supersession(receipt, errs)
    _check_integrity(receipt, errs)

    return ValidationResult(not errs, errs)


__all__ = [
    "CONTRACT_MAJOR", "CONTRACT_MINOR", "SchemaVersion",
    "ReceiptKind", "StageOutcome", "TerminalDisposition", "IdentityQuality",
    "Projection", "AuthorityClass", "ReplayClass", "SourceUpdatedStatus",
    "Universe", "Clocks", "Identity", "Integrity",
    "DecisionOutcome", "BoardDisposition",
    "DecisionStageReceipt", "BoardReceipt",
    "canonical_content_bytes", "canonical_conclusion_bytes",
    "compute_content_hash", "compute_conclusion_hash", "seal_hashes",
    "ValidationResult", "validate_receipt",
]
