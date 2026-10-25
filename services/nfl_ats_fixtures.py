"""Frozen, synthetic NFL ATS fixtures for the Decision Integrity validator suite
(Phase 2B, Slice 2).

PURE and DETERMINISTIC: every value is hard-coded here. This module reads NO live
artifact, no filesystem, no environment, no network — the scenario is modeled on the
*shape* of the audited `build_nfl_ats_wave` contract, not its current data. Builders
return sealed `Receipt`s; callers mutate copies to produce invalid variants.
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional

from services.decision_receipts import (
    AuthorityClass, Claim, Clocks, CorrectionBody, DecisionStageBatch, DecisionStageRow,
    EntityDisposition, EntityDispositionBatch, GovernedNumber, HealthState, Identity, IdentityGrain,
    IdentityQuality, Integrity, IntegrityMechanism, Leaf, LiveEvidenceBoard, Projection,
    ProjectionRoot, Receipt, ReceiptKind, Refs, RenderBody, ReplayClass, SchemaVersion,
    SourceHealthBody, SourceUpdatedStatus, StageOutcome, Universe, Versions, ChangeKind,
    compute_content_hash, compute_conclusion_hash, compute_membership_hash, seal_hashes,
)

SURFACE = "nfl_ats_wave"
UNI_BOARD = Universe("team", "nfl_ats_board_2026", "v1")
UNI_DEC = Universe("team_side_decision", "nfl_ats_decisions_2026", "v1")
BK_AT = "2026-10-26T13:05:00Z"
KICK = "2026-10-26T17:00:00Z"
IH = ["ab" * 32, "cd" * 32]

BATCH_ID = "a0000000-0000-4000-8000-000000000001"
BOARD_ID = "a0000000-0000-4000-8000-000000000002"
SH_ID = "a0000000-0000-4000-8000-000000000003"
RENDER_ID = "a0000000-0000-4000-8000-000000000004"
DEC_ID = "a0000000-0000-4000-8000-000000000005"
CORR_ID = "a0000000-0000-4000-8000-000000000006"
USERSAFE_ID = "a0000000-0000-4000-8000-000000000007"


def _versions(build_id="build-nfl-ats-2026w8", config="cfg-1", rules=None):
    return Versions(build_id, config, rules if rules is not None else {"ats_streak": 1, "sort": 1})


def _clocks():
    return Clocks(bk_captured=BK_AT, source_updated_status=SourceUpdatedStatus.NOT_PROVIDED,
                  source_updated=None, event_effective=KICK)


def team_identity(team: str) -> Identity:
    return Identity(IdentityGrain.TEAM, {"sport": "nfl", "season": 2026}, {"team": team},
                    IdentityQuality.DECLARED_COMPOSITE, True, f"(nfl,2026,{team})",
                    "team:sport+season", "v1", "unique-in-sport-season")


def provider_team_identity(team: str) -> Identity:
    return Identity(IdentityGrain.TEAM, {"sport": "nfl", "season": 2026},
                    {"provider_namespace": "nflverse", "provider_team_id": team},
                    IdentityQuality.PROVIDER_ID, False, f"nflverse:{team}")


def side_identity(event_id: str, side: str) -> Identity:
    return Identity(IdentityGrain.TEAM_SIDE, {"sport": "nfl", "season": 2026, "event_id": event_id},
                    {"team_side": side}, IdentityQuality.DECLARED_COMPOSITE, True,
                    f"({event_id},{side})", "team_side:event+side", "v1", "unique-per-event")


# Canonical board membership: PHI, DAL rendered; SF suppressed (display-capped);
# NYG, WAS nonmembers. Members=3, Eligible=5, Expected=5.
def _default_rows() -> List[EntityDisposition]:
    return [
        EntityDisposition("PHI", team_identity("PHI"), Leaf.RENDERED, "QUALIFIED", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("DAL", team_identity("DAL"), Leaf.RENDERED, "QUALIFIED", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("SF", team_identity("SF"), Leaf.SUPPRESSED, "DISPLAY_CAPPED", 1),
        EntityDisposition("NYG", team_identity("NYG"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("WAS", team_identity("WAS"), Leaf.NONMEMBER, "COVER_SHORT", 1),
    ]


def dispositions_batch(rows: Optional[List[EntityDisposition]] = None,
                       receipt_id: str = BATCH_ID, **kw) -> Receipt:
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=100, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=list(IH),
        integrity=Integrity(), body=EntityDispositionBatch(rows if rows is not None else _default_rows()),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def _counts(batch: Receipt):
    t = {}
    for r in batch.body.rows:
        t[r.leaf.value] = t.get(r.leaf.value, 0) + 1
    return t


def board(batch: Optional[Receipt] = None, receipt_id: str = BOARD_ID, **kw) -> Receipt:
    batch = batch or dispositions_batch()
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=101, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=list(IH),
        refs=Refs(entity_dispositions=batch.receipt_id, source_health=SH_ID),
        body=LiveEvidenceBoard(compute_membership_hash(batch), _counts(batch), len(batch.body.rows),
                               sort_rule_id="streak_desc_team_asc", sort_rule_version="1"),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def source_health(receipt_id: str = SH_ID, state: HealthState = HealthState.SYNCHRONIZED,
                  **kw) -> Receipt:
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.SOURCE_HEALTH,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=99, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=None,
        body=SourceHealthBody(state, BK_AT, {"checked_rows": 5}),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def render(board_receipt: Optional[Receipt] = None, receipt_id: str = RENDER_ID, **kw) -> Receipt:
    board_receipt = board_receipt or board()
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.RENDER,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=102, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=None,
        refs=Refs(evidence=board_receipt.receipt_id),
        body=RenderBody(board_receipt.receipt_id, board_receipt.conclusion_hash,
                        board_receipt.body.membership_hash),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def decision_stage(receipt_id: str = DEC_ID, **kw) -> Receipt:
    rows = [
        DecisionStageRow("(401010, HOME)", side_identity("401010", "HOME"), StageOutcome.GRADED, "GRADED", 1),
        DecisionStageRow("(401010, AWAY)", side_identity("401010", "AWAY"), StageOutcome.NO_LINE, "NO_LINE", 1),
    ]
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_DEC,
        created_seq=90, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=list(IH),
        integrity=Integrity(), body=DecisionStageBatch(rows),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def correction(target: Optional[Receipt] = None, receipt_id: str = CORR_ID, **kw) -> Receipt:
    target = target or dispositions_batch()
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.CORRECTION,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=200, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=None,
        supersedes=target.receipt_id, supersedes_seq=target.created_seq,
        body=CorrectionBody(ChangeKind.REGRADE, {"leaf": "NONMEMBER"}, {"leaf": "RENDERED"}),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def user_safe(root: Optional[Receipt] = None, receipt_id: str = USERSAFE_ID, **kw) -> Receipt:
    root = root or board()
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=103, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
        projection=Projection.USER_SAFE, clocks=_clocks(), input_hashes=None,
        refs=Refs(entity_dispositions=BATCH_ID, source_health=SH_ID),
        # Human prose = rendering only (not the governed claim).
        claims=["3 teams on active 3+ ATS cover streaks", "sorted by active cover streak"],
        # Immutable binding to the internal root this projection derives from.
        projection_root=ProjectionRoot(root.receipt_id, root.conclusion_hash, "evidence"),
        # Governed claim records.
        claim_records=[
            Claim("MEMBER_COUNT", {"count": 3}, (root.receipt_id,)),
            Claim("SORTED", {"sort_rule_id": "streak_desc_team_asc", "sort_rule_version": "1"},
                  (root.receipt_id,)),
            Claim("HEALTH", {"state": "SYNCHRONIZED"}, (SH_ID,)),
        ],
        body=LiveEvidenceBoard(root.body.membership_hash, {"RENDERED": 2, "SUPPRESSED": 1,
                               "NONMEMBER": 2}, 5),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def user_safe_render(brd: Optional[Receipt] = None, rnd: Optional[Receipt] = None,
                     receipt_id: str = "a0000000-0000-4000-8000-000000000008", **kw) -> Receipt:
    """A user-safe RENDER projection: its root is a render receipt whose evidence
    chain resolves to the board `brd`."""
    brd = brd or board()
    rnd = rnd or render(brd)
    base = dict(
        receipt_id=receipt_id, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=SURFACE, universe=UNI_BOARD,
        created_seq=104, created_at=BK_AT, versions=_versions(),
        replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
        projection=Projection.USER_SAFE, clocks=_clocks(), input_hashes=None,
        refs=Refs(entity_dispositions=BATCH_ID, source_health=SH_ID, evidence=brd.receipt_id),
        claims=["rendered board for the client"],
        projection_root=ProjectionRoot(rnd.receipt_id, rnd.conclusion_hash, "render"),
        claim_records=[
            Claim("RENDER_COMPLETE", {}, (rnd.receipt_id,)),
            Claim("HEALTH", {"state": "SYNCHRONIZED"}, (SH_ID,)),
        ],
        body=LiveEvidenceBoard(brd.body.membership_hash, dict(brd.body.per_leaf_counts),
                               brd.body.expected_count),
    )
    base.update(kw)
    return seal_hashes(Receipt(**base))


def reseal(receipt: Receipt) -> Receipt:
    """Re-seal after a structural mutation so digests are self-consistent again."""
    receipt.conclusion_hash = compute_conclusion_hash(receipt)
    receipt.integrity.content_hash = compute_content_hash(receipt)
    return receipt


__all__ = [
    "SURFACE", "UNI_BOARD", "UNI_DEC", "BK_AT", "KICK",
    "BATCH_ID", "BOARD_ID", "SH_ID", "RENDER_ID", "DEC_ID", "CORR_ID", "USERSAFE_ID",
    "team_identity", "provider_team_identity", "side_identity",
    "dispositions_batch", "board", "source_health", "render", "decision_stage",
    "correction", "user_safe", "user_safe_render", "reseal",
]
