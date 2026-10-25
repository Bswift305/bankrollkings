"""Decision Integrity — validator suite (Phase 2B, Slice 2).

Composable, PURE validators (QC tools) over the Slice-1 contract library. Each
returns a `ValidationResult`; none raises on a contract violation; none reads the
filesystem, environment, network, Flask, pandas, or production data. Nothing here
is wired into any surface, route, CI, or runtime.

Covers the Phase 2B validator plan (§Phase 2B step 2):
  1. envelope validity .................... validate_envelope
  2. stage/leaf separation ................ validate_stage_leaf_separation
  3. nested conservation .................. validate_nested_conservation
  4. reason-code governance ............... validate_reason_registry / validate_reason_usage
  5. canonical replay ..................... validate_canonical_replay / replay_equal
  6. identity / collision rules ........... validate_identity_collision
  7. correction lineage ................... validate_correction_lineage
  8. hierarchical references .............. validate_hierarchical_references
  9. count reconciliation ................. validate_count_reconciliation
 10. user-safe projection ................. validate_user_safe_projection

The provisional `transition` envelope is deliberately NOT implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.decision_receipts import (
    ChangeKind, Claim, CorrectionBody, DecisionStageRow, EntityDisposition, EntityDispositionBatch,
    DecisionStageBatch, HealthState, Identity, IdentityQuality, Leaf, LiveEvidenceBoard,
    Projection, ProjectionRoot, Receipt, ReceiptKind, RenderBody, ReplayClass, SemanticCategory,
    SourceHealthBody, StageOutcome, ValidationResult, _LEAF_NAMES, _STAGE_NAMES, _REASON_CODE_RE,
    _dumps, canonical_identity, compute_conclusion_hash, compute_content_hash,
    compute_membership_hash, reconcile_board, validate_receipt,
)

# Governed user-safe claim registry: claim_code -> required governed params.
CLAIM_REGISTRY = {
    "MEMBER_COUNT": ("count",),
    "SORTED": ("sort_rule_id", "sort_rule_version"),
    "EMPTY_STATE": (),
    "HEALTH": ("state",),
}


def _gate(receipts, errs: List[str]) -> bool:
    """Validate every participating receipt before any cross-receipt walk. Returns
    True if all are structurally valid; otherwise appends errors and returns False so
    the caller fails closed (an invalid/unsealed receipt never reconciles)."""
    all_ok = True
    for r in receipts:
        if not isinstance(r, Receipt):
            errs.append("participant is not a Receipt"); all_ok = False; continue
        vr = validate_receipt(r)
        if not vr.ok:
            errs.append(f"{getattr(r, 'receipt_id', '?')}: failed structural validation: {vr.errors}")
            all_ok = False
    return all_ok


def _index_unique(receipts, errs: List[str], *, require_seq_unique: bool = False):
    """Index receipts by id, rejecting duplicate receipt_id (and, when required,
    duplicate created_seq within a surface — P2A-2 monotonic uniqueness)."""
    by_id: Dict[str, Receipt] = {}
    seq_seen: Dict[tuple, str] = {}
    for r in receipts:
        if r.receipt_id in by_id:
            errs.append(f"duplicate receipt_id {r.receipt_id!r}")
        by_id[r.receipt_id] = r
        if require_seq_unique:
            key = (r.surface_id, r.created_seq)
            if key in seq_seen:
                errs.append(f"duplicate created_seq {r.created_seq} on surface {r.surface_id!r} "
                            f"({r.receipt_id} vs {seq_seen[key]})")
            seq_seen[key] = r.receipt_id
    return by_id

MEMBER_LEAF_NAMES = frozenset({"RENDERED", "SUPPRESSED"})
_AUTHORITATIVE_IDENTITY = frozenset({
    IdentityQuality.PROVIDER_ID, IdentityQuality.DECLARED_COMPOSITE,
    IdentityQuality.COMPOSITE_NAME_EVENT, IdentityQuality.ALIAS_RESOLVED,
})
HEALTH_STATES = frozenset({"SYNCHRONIZED", "FAIL_CLOSED", "STALE"})


# ---------------------------------------------------------------------------
# Governed reason-code registry (§3) — the Slice-2 governance object.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReasonCodeDef:
    code: str
    semantic_category: SemanticCategory
    def_version: int
    owner: str
    definition: str
    maps_to: Optional[str] = None      # required iff category in {leaf, health}
    stage: str = ""
    param_fields: Tuple[str, ...] = ()


def _rc(code, cat, owner, definition, maps_to=None, stage="", params=()):
    return ReasonCodeDef(code, cat, 1, owner, definition, maps_to, stage, tuple(params))


REASON_REGISTRY: Dict[str, ReasonCodeDef] = {
    "BELOW_THRESHOLD": _rc("BELOW_THRESHOLD", SemanticCategory.LEAF, "ats-owner",
                           "Eligible team below the cover-streak threshold.", "NONMEMBER", "board",
                           ("threshold",)),
    "QUALIFIED": _rc("QUALIFIED", SemanticCategory.LEAF, "ats-owner",
                     "Admitted member (rendered) meeting the cover-streak threshold.", "RENDERED", "board"),
    "DISPLAY_CAPPED": _rc("DISPLAY_CAPPED", SemanticCategory.LEAF, "ats-owner",
                          "Admitted member withheld by the display cap (counted + disclosed).",
                          "SUPPRESSED", "board"),
    "KNOWN_NON_FBS": _rc("KNOWN_NON_FBS", SemanticCategory.LEAF, "ats-owner",
                         "Out of scope for this surface.", "EXCLUDED", "board"),
    "COVER_SHORT": _rc("COVER_SHORT", SemanticCategory.LEAF, "ats-owner",
                       "Eligible team, streak short of threshold.", "NONMEMBER", "board"),
    "SOURCE_STALE": _rc("SOURCE_STALE", SemanticCategory.HEALTH, "ops-owner",
                        "Sidecar source is stale.", "STALE", "health"),
    "GRADED": _rc("GRADED", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                  "Decision graded against the result.", None, "decision"),
    "PUSH": _rc("PUSH", SemanticCategory.STAGE_OUTCOME, "grade-owner", "Decision pushed.", None, "decision"),
    "VOID": _rc("VOID", SemanticCategory.STAGE_OUTCOME, "grade-owner", "Decision voided.", None, "decision"),
    "NO_LINE": _rc("NO_LINE", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                   "No spread recorded for the decision.", None, "decision"),
    "OVERDUE": _rc("OVERDUE", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                   "Past grace, ungraded.", None, "decision"),
    "MALFORMED": _rc("MALFORMED", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                     "Malformed spread/decision.", None, "decision"),
    "CONFLICT": _rc("CONFLICT", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                    "Conflicting identity/result.", None, "decision"),
    "OUTSIDE_BOUNDARY": _rc("OUTSIDE_BOUNDARY", SemanticCategory.STAGE_OUTCOME, "grade-owner",
                            "Future/within-grace, out of universe.", None, "decision"),
    "SORTED": _rc("SORTED", SemanticCategory.STAGE_OUTCOME, "board-owner",
                  "Board ordering applied.", None, "board", ("sort_rule_id", "sort_rule_version")),
}


def validate_reason_registry(registry: Optional[Dict[str, "ReasonCodeDef"]] = None) -> ValidationResult:
    """R7/R8/R9: codes are stable UPPER_SNAKE identifiers (no interpolated values),
    def_version is int>=1, owner+definition present, maps_to present and valid iff
    the category is leaf/health (and empty otherwise). Defaults to the module
    REASON_REGISTRY; accepts an explicit registry so its negative path is testable."""
    registry = REASON_REGISTRY if registry is None else registry
    errs: List[str] = []
    for code, d in registry.items():
        if not _REASON_CODE_RE.match(code):
            errs.append(f"{code}: invalid code shape (UPPER_SNAKE, no interpolation)")
        if d.code != code:
            errs.append(f"{code}: registry key != def.code {d.code!r}")
        if not isinstance(d.def_version, int) or isinstance(d.def_version, bool) or d.def_version < 1:
            errs.append(f"{code}: def_version must be int >= 1")
        if not d.owner or not d.definition:
            errs.append(f"{code}: owner + definition required")
        if d.semantic_category in (SemanticCategory.LEAF, SemanticCategory.HEALTH):
            if not d.maps_to:
                errs.append(f"{code}: {d.semantic_category.value} code requires maps_to")
            elif d.semantic_category == SemanticCategory.LEAF and d.maps_to not in _LEAF_NAMES:
                errs.append(f"{code}: maps_to {d.maps_to!r} is not a terminal leaf")
            elif d.semantic_category == SemanticCategory.HEALTH and d.maps_to not in HEALTH_STATES:
                errs.append(f"{code}: maps_to {d.maps_to!r} is not a health state")
        else:
            if d.maps_to:
                errs.append(f"{code}: {d.semantic_category.value} code must not set maps_to")
    return ValidationResult(not errs, errs)


def validate_reason_usage(receipt: Receipt) -> ValidationResult:
    """Each row's reason_code is registered; its governed category matches the row's
    context; for a leaf code its `maps_to` equals the row's actual leaf; its
    `reason_def_version` equals the registry's current def_version; and every required
    `param_fields` entry is present in the row's params."""
    errs: List[str] = []
    rows = getattr(receipt.body, "rows", [])
    for i, r in enumerate(rows):
        code = r.reason_code
        d = REASON_REGISTRY.get(code)
        if d is None:
            errs.append(f"rows[{i}]: reason_code {code!r} is not registered")
            continue
        is_leaf_row = isinstance(r, EntityDisposition)
        want = SemanticCategory.LEAF if is_leaf_row else SemanticCategory.STAGE_OUTCOME
        if d.semantic_category != want:
            errs.append(f"rows[{i}]: {code!r} is {d.semantic_category.value}, expected {want.value}")
            continue
        # maps_to must match the row's actual leaf state (presentation/leaf mapping).
        if is_leaf_row and isinstance(r.leaf, Leaf) and d.maps_to != r.leaf.value:
            errs.append(f"rows[{i}]: reason {code!r} maps_to {d.maps_to!r} but the leaf is "
                        f"{r.leaf.value} (mapping mismatch)")
        if r.reason_def_version != d.def_version:
            errs.append(f"rows[{i}]: reason_def_version {r.reason_def_version} != registry "
                        f"def_version {d.def_version} for {code!r}")
        params = r.params or {}
        missing = [p for p in d.param_fields if p not in params]
        if missing:
            errs.append(f"rows[{i}]: {code!r} requires param_fields {missing} (missing)")
    return ValidationResult(not errs, errs)


# ---------------------------------------------------------------------------
# 1 envelope · 2 stage/leaf · 3 nested conservation
# ---------------------------------------------------------------------------


def validate_envelope(receipt: Receipt) -> ValidationResult:
    return validate_receipt(receipt)


def validate_stage_leaf_separation(receipt: Receipt) -> ValidationResult:
    errs: List[str] = []
    body = receipt.body
    if isinstance(body, EntityDispositionBatch):
        for i, r in enumerate(body.rows):
            if isinstance(r.leaf, StageOutcome) or (hasattr(r.leaf, "value")
                                                    and r.leaf.value in _STAGE_NAMES):
                errs.append(f"rows[{i}]: stage outcome used as a terminal leaf")
            elif not isinstance(r.leaf, Leaf):
                errs.append(f"rows[{i}]: leaf must be a Leaf")
    elif isinstance(body, DecisionStageBatch):
        for i, r in enumerate(body.rows):
            if isinstance(r.stage_outcome, Leaf) or (hasattr(r.stage_outcome, "value")
                                                     and r.stage_outcome.value in _LEAF_NAMES):
                errs.append(f"rows[{i}]: presentation leaf used as a decision-stage outcome")
            elif not isinstance(r.stage_outcome, StageOutcome):
                errs.append(f"rows[{i}]: stage_outcome must be a StageOutcome")
    else:
        errs.append("stage/leaf separation applies to a disposition/decision batch")
    return ValidationResult(not errs, errs)


def rollups(batch: EntityDispositionBatch) -> Dict[str, int]:
    """The nested roll-up counts (§2): Members = RENDERED+SUPPRESSED; Eligible =
    Members + NONMEMBER; Expected = Eligible + EXCLUDED + UNAVAILABLE + INDETERMINATE
    + FAILED."""
    t: Dict[str, int] = {}
    for r in batch.rows:
        if isinstance(r.leaf, Leaf):
            t[r.leaf.value] = t.get(r.leaf.value, 0) + 1
    members = t.get("RENDERED", 0) + t.get("SUPPRESSED", 0)
    eligible = members + t.get("NONMEMBER", 0)
    expected = eligible + t.get("EXCLUDED", 0) + t.get("UNAVAILABLE", 0) \
        + t.get("INDETERMINATE", 0) + t.get("FAILED", 0)
    return {"MEMBERS": members, "ELIGIBLE": eligible, "EXPECTED": expected, "_leaves": t}


def validate_nested_conservation(batch_receipt: Receipt,
                                 board_receipt: Optional[Receipt] = None) -> ValidationResult:
    """Each entity has exactly one leaf; the nested roll-ups partition cleanly
    (Members ⊆ Eligible ⊆ Expected, no leakage); Expected == number of expected
    entities. If a board is given, its expected_count and per-leaf counts must agree."""
    errs: List[str] = []
    body = batch_receipt.body
    if not isinstance(body, EntityDispositionBatch):
        return ValidationResult(False, ["nested conservation requires an EntityDispositionBatch"])
    # Fail closed on any malformed participant before counting.
    participants = [batch_receipt] + ([board_receipt] if board_receipt is not None else [])
    if not _gate(participants, errs):
        return ValidationResult(False, errs)
    seen_ci = set()
    for i, r in enumerate(body.rows):
        # Exactly one leaf per CANONICAL IDENTITY (entity_ref is only a display handle).
        ci = _dumps(canonical_identity(r.identity)) if isinstance(r.identity, Identity) else None
        if ci is not None and ci in seen_ci:
            errs.append(f"rows[{i}]: duplicate canonical identity — exactly one leaf per canonical "
                        "identity, not per display entity_ref")
        if ci is not None:
            seen_ci.add(ci)
        if not isinstance(r.leaf, Leaf):
            errs.append(f"rows[{i}]: non-leaf disposition breaks conservation")
    ru = rollups(body)
    if ru["EXPECTED"] != len(body.rows):
        errs.append(f"nested conservation: EXPECTED {ru['EXPECTED']} != {len(body.rows)} rows")
    if ru["MEMBERS"] > ru["ELIGIBLE"] or ru["ELIGIBLE"] > ru["EXPECTED"]:
        errs.append("nested conservation: Members ⊄ Eligible ⊄ Expected")
    if board_receipt is not None and isinstance(board_receipt.body, LiveEvidenceBoard):
        if board_receipt.body.expected_count != ru["EXPECTED"]:
            errs.append(f"board.expected_count {board_receipt.body.expected_count} != EXPECTED "
                        f"{ru['EXPECTED']}")
        declared = {k: v for k, v in board_receipt.body.per_leaf_counts.items() if v}
        actual = {k: v for k, v in ru["_leaves"].items() if v}
        if declared != actual:
            errs.append(f"board per-leaf counts {declared} != batch tally {actual}")
    return ValidationResult(not errs, errs)


# ---------------------------------------------------------------------------
# 5 canonical replay · 6 identity/collision
# ---------------------------------------------------------------------------


def validate_canonical_replay(receipt: Receipt) -> ValidationResult:
    """EXACT_REPLAY semantics: the declared conclusion_hash and content_hash MUST
    equal the canonical recomputation from the receipt's own fields."""
    errs: List[str] = []
    try:
        if receipt.conclusion_hash != compute_conclusion_hash(receipt):
            errs.append("conclusion_hash does not reproduce under canonical replay")
        if receipt.integrity.content_hash != compute_content_hash(receipt):
            errs.append("content_hash does not reproduce under canonical replay")
    except Exception as exc:
        errs.append(f"replay canonicalization failed: {type(exc).__name__}: {exc}")
    return ValidationResult(not errs, errs)


def replay_equal(r1: Receipt, r2: Receipt) -> bool:
    """Two receipts are replay-equal iff their canonical CONCLUSIONS match (even when
    receipt_id / created_seq / created_at / content_hash differ)."""
    try:
        return compute_conclusion_hash(r1) == compute_conclusion_hash(r2)
    except Exception:
        return False


def validate_identity_collision(receipt: Receipt) -> ValidationResult:
    """R12/R13/R14 at the row grain: an admitted member MUST use an authoritative
    identity quality; fail-closed qualities may not be admitted; composite keys MUST
    be collision_tested."""
    errs: List[str] = []
    rows = getattr(receipt.body, "rows", [])
    for i, r in enumerate(rows):
        idn: Identity = r.identity
        admitted = isinstance(r, EntityDisposition) and isinstance(r.leaf, Leaf) \
            and r.leaf.value in MEMBER_LEAF_NAMES
        graded = isinstance(r, DecisionStageRow) and r.stage_outcome == StageOutcome.GRADED
        if (admitted or graded) and idn.identity_quality not in _AUTHORITATIVE_IDENTITY:
            errs.append(f"rows[{i}]: an authoritative row requires an authoritative identity "
                        f"(got {idn.identity_quality.value}) — R12/R13 fail closed")
        if idn.identity_quality in (IdentityQuality.DECLARED_COMPOSITE,
                                    IdentityQuality.COMPOSITE_NAME_EVENT) and not idn.collision_tested:
            errs.append(f"rows[{i}]: composite identity requires collision_tested=true (R14)")
    return ValidationResult(not errs, errs)


# ---------------------------------------------------------------------------
# 7 correction lineage · 8 hierarchical references · 9 count reconciliation
# ---------------------------------------------------------------------------


def validate_correction_lineage(receipts: Sequence[Receipt]) -> ValidationResult:
    """R15/R15b/R16/R17. Each correction resolves its envelope `supersedes` to a
    receipt in the set; envelope.supersedes_seq AND body.supersedes_seq equal the
    superseded receipt's created_seq; the correction's created_seq is strictly later;
    the chain is walkable with no cycle and each receipt is superseded at most once."""
    errs: List[str] = []
    if not _gate(receipts, errs):
        return ValidationResult(False, errs)
    by_id = _index_unique(receipts, errs, require_seq_unique=True)
    if errs:
        return ValidationResult(False, errs)  # duplicate id / seq → fail before walking
    superseded_by: Dict[str, str] = {}
    for r in receipts:
        if r.receipt_kind != ReceiptKind.CORRECTION:
            continue
        if not isinstance(r.body, CorrectionBody):
            errs.append(f"{r.receipt_id}: correction kind with a non-correction body")
            continue
        if not r.supersedes or r.supersedes not in by_id:
            errs.append(f"{r.receipt_id}: correction supersedes an unknown receipt_id "
                        f"{r.supersedes!r}")
            continue
        target = by_id[r.supersedes]
        if r.supersedes in superseded_by:
            errs.append(f"{r.supersedes}: superseded by more than one correction")
        superseded_by[r.supersedes] = r.receipt_id
        if r.supersedes_seq != target.created_seq:
            errs.append(f"{r.receipt_id}: envelope.supersedes_seq {r.supersedes_seq} != superseded "
                        f"created_seq {target.created_seq} (R15b)")
        if r.body.change_kind != ChangeKind.RETRACTION and r.body.after is None:
            errs.append(f"{r.receipt_id}: non-retraction correction missing 'after'")
        if r.created_seq <= target.created_seq:
            errs.append(f"{r.receipt_id}: created_seq {r.created_seq} must be > superseded "
                        f"{target.created_seq} (R16)")
    # Cycle / walkability.
    for start in list(superseded_by.values()):
        seen, cur = set(), start
        while cur in by_id and by_id[cur].supersedes:
            if cur in seen:
                errs.append(f"supersedes chain has a cycle at {cur}")
                break
            seen.add(cur)
            cur = by_id[cur].supersedes
    return ValidationResult(not errs, errs)


def validate_hierarchical_references(receipts: Sequence[Receipt]) -> ValidationResult:
    """§7 R18/R19 + Rev-2.1 #2. A board live_evidence references an
    entity_dispositions batch + a source_health receipt (both resolvable, right kind).
    A render references a live_evidence receipt and pins its conclusion/membership
    hashes. Links are forward-only render→evidence→{dispositions, source_health};
    evidence MUST NOT back-reference a render; no cycles."""
    errs: List[str] = []
    if not _gate(receipts, errs):
        return ValidationResult(False, errs)
    by_id = _index_unique(receipts, errs)
    if errs:
        return ValidationResult(False, errs)  # duplicate receipt_id → fail before walking
    edges: Dict[str, List[str]] = {}
    for r in receipts:
        outs: List[str] = []
        if r.receipt_kind == ReceiptKind.LIVE_EVIDENCE and isinstance(r.body, LiveEvidenceBoard):
            refs = r.refs
            if refs is None or not refs.entity_dispositions:
                errs.append(f"{r.receipt_id}: board missing entity_dispositions ref (R18)")
            elif refs.entity_dispositions not in by_id \
                    or by_id[refs.entity_dispositions].receipt_kind != ReceiptKind.ENTITY_DISPOSITION:
                errs.append(f"{r.receipt_id}: entity_dispositions ref does not resolve to a batch")
            else:
                outs.append(refs.entity_dispositions)
            if refs is None or not refs.source_health:
                errs.append(f"{r.receipt_id}: board missing source_health ref (R18)")
            elif refs.source_health not in by_id \
                    or by_id[refs.source_health].receipt_kind != ReceiptKind.SOURCE_HEALTH:
                errs.append(f"{r.receipt_id}: source_health ref does not resolve to a source_health receipt")
            else:
                outs.append(refs.source_health)
            if refs is not None and getattr(refs, "evidence", None):
                errs.append(f"{r.receipt_id}: an evidence board MUST NOT reference a render (forward-only)")
        elif r.receipt_kind == ReceiptKind.RENDER and isinstance(r.body, RenderBody):
            ev = r.body.evidence_ref
            if r.refs is None or r.refs.evidence != ev:
                errs.append(f"{r.receipt_id}: render refs.evidence must equal body.evidence_ref")
            if ev not in by_id or by_id[ev].receipt_kind != ReceiptKind.LIVE_EVIDENCE:
                errs.append(f"{r.receipt_id}: render evidence_ref does not resolve to a live_evidence receipt")
            else:
                evr = by_id[ev]
                if r.body.conclusion_hash != evr.conclusion_hash:
                    errs.append(f"{r.receipt_id}: render conclusion_hash != evidence conclusion_hash")
                if isinstance(evr.body, LiveEvidenceBoard) \
                        and r.body.membership_hash != evr.body.membership_hash:
                    errs.append(f"{r.receipt_id}: render membership_hash != evidence membership_hash")
                outs.append(ev)
        edges[r.receipt_id] = outs
    # Cycle detection over the reference graph.
    WHITE, GREY, BLACK = 0, 1, 2
    color = {rid: WHITE for rid in edges}

    def dfs(n: str) -> bool:
        color[n] = GREY
        for m in edges.get(n, []):
            if color.get(m) == GREY:
                return True
            if color.get(m) == WHITE and dfs(m):
                return True
        color[n] = BLACK
        return False

    for rid in edges:
        if color[rid] == WHITE and dfs(rid):
            errs.append(f"reference graph has a cycle through {rid}")
            break
    return ValidationResult(not errs, errs)


def validate_count_reconciliation(board_receipt: Receipt, batch_receipt: Receipt) -> ValidationResult:
    return reconcile_board(board_receipt, batch_receipt)


# ---------------------------------------------------------------------------
# 10 user-safe projection
# ---------------------------------------------------------------------------

def _reachable_from(root: Receipt, by_id: Dict[str, Receipt]) -> set:
    """Forward-reachable internal receipt ids from a root, following refs
    (board→{entity_dispositions, source_health}; render→evidence)."""
    out, stack = set(), [root.receipt_id]
    while stack:
        rid = stack.pop()
        r = by_id.get(rid)
        if r is None or r.refs is None:
            continue
        for nxt in (r.refs.entity_dispositions, r.refs.source_health, r.refs.evidence):
            if nxt and nxt in by_id and nxt not in out:
                out.add(nxt)
                stack.append(nxt)
    return out


def _members(board_body: LiveEvidenceBoard) -> int:
    return board_body.per_leaf_counts.get("RENDERED", 0) + board_body.per_leaf_counts.get("SUPPRESSED", 0)


def _reachable_health_state(reachable: set, by_id: Dict[str, Receipt]) -> Optional[str]:
    for rid in reachable:
        r = by_id.get(rid)
        if r is not None and r.receipt_kind == ReceiptKind.SOURCE_HEALTH \
                and isinstance(r.body, SourceHealthBody) and isinstance(r.body.state, HealthState):
            return r.body.state.value
    return None


def _validate_claims(user_safe: Receipt, root_internal: Receipt, by_id: Dict[str, Receipt],
                     reachable: set, errs: List[str]) -> None:
    """Every GOVERNED claim carries a registered code + required params, cites only
    reachable support receipts, and is DERIVABLE from the root/reference graph.
    Human prose (`claims`) is rendering only and is not validated here."""
    records = user_safe.claim_records
    if not records:
        errs.append("user_safe MUST carry governed claim_records (prose `claims` is not a claim)")
        return
    allowed = {root_internal.receipt_id} | reachable
    root_board = root_internal.body if isinstance(root_internal.body, LiveEvidenceBoard) else None
    health_state = _reachable_health_state(reachable, by_id)
    for i, c in enumerate(records):
        if not isinstance(c, Claim):
            errs.append(f"claim_records[{i}] is not a governed Claim"); continue
        if c.claim_code not in CLAIM_REGISTRY:
            errs.append(f"claim_records[{i}]: unregistered claim_code {c.claim_code!r}"); continue
        missing = [p for p in CLAIM_REGISTRY[c.claim_code] if p not in c.params]
        if missing:
            errs.append(f"claim_records[{i}] ({c.claim_code}): missing params {missing}")
        for ref in c.support_refs:
            if ref not in allowed:
                errs.append(f"claim_records[{i}] ({c.claim_code}): support ref {ref!r} is not "
                            "reachable from the root")
        # Derivation from the governed graph.
        if c.claim_code == "MEMBER_COUNT" and root_board is not None and "count" in c.params:
            if c.params["count"] != _members(root_board):
                errs.append(f"claim_records[{i}] MEMBER_COUNT {c.params['count']} not derivable "
                            f"(root members={_members(root_board)})")
        elif c.claim_code == "EMPTY_STATE" and root_board is not None:
            if _members(root_board) != 0:
                errs.append(f"claim_records[{i}] EMPTY_STATE not derivable (root has members)")
        elif c.claim_code == "SORTED":
            if root_internal.receipt_id not in c.support_refs:
                errs.append(f"claim_records[{i}] SORTED must cite the root board as support")
        elif c.claim_code == "HEALTH":
            if health_state is None:
                errs.append(f"claim_records[{i}] HEALTH has no reachable source_health to support it")
            elif c.params.get("state") != health_state:
                errs.append(f"claim_records[{i}] HEALTH state {c.params.get('state')!r} != governed "
                            f"source-health state {health_state!r}")


def validate_user_safe_projection(user_safe: Receipt, root_internal: Receipt,
                                  internal_graph: Sequence[Receipt] = ()) -> ValidationResult:
    """R21/R22 root-and-reference, strengthened to prove SUPPORT (not just stripping):
      * every participant is structurally valid (fail closed);
      * projection=user_safe; root + graph are internal; shares root surface/universe;
      * strips internal-only material (input_hashes, integrity.proof); carries claims;
      * its referenced ids are an allowlisted subset reachable from the root within
        the internal graph (an existing-but-unreachable reference fails);
      * its projected per-leaf counts and membership_hash EQUAL the root board's (it
        cannot add entities, dispositions, or members);
      * a health claim is supported: if the reachable source_health is not
        synchronized, the projection may not present rendered members."""
    errs: List[str] = []
    if not _gate([user_safe, root_internal, *internal_graph], errs):
        return ValidationResult(False, errs)
    by_id = _index_unique([root_internal, *internal_graph], errs)
    if errs:
        return ValidationResult(False, errs)

    if user_safe.projection != Projection.USER_SAFE:
        errs.append("projection must be user_safe")
    if root_internal.projection != Projection.INTERNAL:
        errs.append("root receipt must be an internal projection")
    for ref in internal_graph:
        if ref.projection != Projection.INTERNAL:
            errs.append(f"internal_graph receipt {ref.receipt_id} must be internal")
    if user_safe.surface_id != root_internal.surface_id:
        errs.append("user_safe surface_id must match its internal root")
    if user_safe.universe != root_internal.universe:
        errs.append("user_safe universe must match its internal root")
    if user_safe.input_hashes:
        errs.append("user_safe MUST NOT carry input_hashes (internal-only)")
    if user_safe.integrity.proof:
        errs.append("user_safe MUST NOT carry integrity.proof (internal-only)")

    # Immutable projection-root binding: the receipt itself records its root, so it
    # cannot be re-pointed at a different root by the caller.
    pr = user_safe.projection_root
    if not isinstance(pr, ProjectionRoot):
        errs.append("user_safe MUST carry a serialized projection_root reference")
    else:
        if pr.root_receipt_id != root_internal.receipt_id:
            errs.append(f"projection_root.root_receipt_id {pr.root_receipt_id!r} != supplied root "
                        f"{root_internal.receipt_id!r} (substituted root)")
        if pr.root_conclusion_hash != root_internal.conclusion_hash:
            errs.append("projection_root.root_conclusion_hash != the root's conclusion_hash")
        if pr.projection_type not in ("evidence", "render"):
            errs.append(f"projection_root.projection_type {pr.projection_type!r} invalid")

    # Reachability: referenced ids must be the root or reachable from it.
    reachable = {root_internal.receipt_id} | _reachable_from(root_internal, by_id)
    refs = user_safe.refs
    if refs is not None:
        for rid in (refs.entity_dispositions, refs.source_health, refs.evidence):
            if rid and rid not in reachable:
                errs.append(f"user_safe references {rid!r} which is not reachable from its root")

    # Support: the projection cannot assert more than the root board supports.
    if isinstance(user_safe.body, LiveEvidenceBoard) and isinstance(root_internal.body, LiveEvidenceBoard):
        if user_safe.body.membership_hash != root_internal.body.membership_hash:
            errs.append("user_safe membership_hash is not supported by the internal root (forged)")
        if user_safe.body.per_leaf_counts != root_internal.body.per_leaf_counts:
            errs.append("user_safe per-leaf counts are not supported by the internal root (forged)")
        if user_safe.body.expected_count != root_internal.body.expected_count:
            errs.append("user_safe expected_count is not supported by the internal root (forged)")

    # Governed claims: registered, parameterized, supported, and derivable.
    _validate_claims(user_safe, root_internal, by_id, reachable, errs)

    # Health support (governed state): an unsynchronized reachable source_health
    # forbids presenting rendered members, even when a board shows zero members.
    hs = _reachable_health_state(reachable, by_id)
    if hs is not None and hs != HealthState.SYNCHRONIZED.value \
            and isinstance(user_safe.body, LiveEvidenceBoard) \
            and user_safe.body.per_leaf_counts.get("RENDERED", 0) > 0:
        errs.append("user_safe presents rendered members on a non-synchronized source "
                    "(forged health claim)")
    return ValidationResult(not errs, errs)


__all__ = [
    "ReasonCodeDef", "REASON_REGISTRY", "CLAIM_REGISTRY", "HEALTH_STATES", "rollups",
    "validate_reason_registry", "validate_reason_usage",
    "validate_envelope", "validate_stage_leaf_separation", "validate_nested_conservation",
    "validate_canonical_replay", "replay_equal", "validate_identity_collision",
    "validate_correction_lineage", "validate_hierarchical_references",
    "validate_count_reconciliation", "validate_user_safe_projection",
]
