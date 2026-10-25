"""QC: Decision Integrity shared contract library (Phase 2B, Slice 1, Rev 3).

Proves CONFORMANCE to the approved Phase 2A contract (incl. Rev-2.3a `team` grain).
Pure: imports only the contract library + stdlib. Touches no app/route/data/network
(beyond a cwd listdir snapshot for the purity check).

Rev-3 adds fixtures for the six follow-up findings: the `team` identity grain +
grain binding; tamper-evidence metadata (no verified claim); exact-`Z` UTC incl. a
`+00:00` rejection; exact-Decimal numeric profiles with boundary/excess-precision
fixtures; an allowlisted reason-code registry (dynamic code rejected); and the
envelope/cross-grain checks (UUID receipt_id, positive created_seq, nonempty
universe fields, decision/board grain binding, board↔batch context match, and
NON_REPLAYABLE prohibited for factual/governed-model authority).
"""
from __future__ import annotations

import os

import services.decision_receipts as dr
from services.decision_receipts import (
    AuthorityClass, Clocks, DecisionStageBatch, DecisionStageRow, EntityDisposition,
    EntityDispositionBatch, GovernedNumber, Identity, IdentityGrain, IdentityQuality,
    Integrity, IntegrityMechanism, Leaf, LiveEvidenceBoard, NumericProfileError,
    Projection, Receipt, ReceiptKind, Refs, ReplayClass, SchemaVersion, SourceUpdatedStatus,
    StageOutcome, Universe, Versions, canonical_number, compute_conclusion_hash,
    compute_content_hash, has_tamper_evidence_metadata, reconcile_board, seal_hashes,
    validate_receipt,
)

UTC = "2026-10-25T12:51:21Z"
KICK = "2026-10-25T13:30:00Z"
DISP_ID = "11111111-1111-4111-8111-111111111111"
BOARD_ID = "22222222-2222-4222-8222-222222222222"
DEC_ID = "33333333-3333-4333-8333-333333333333"


# --- builders ---------------------------------------------------------------

def _versions(build_id="build-1"):
    return Versions(build_id, "cfg-1", {"ats_streak": 1})


def _clocks(su=None, st=SourceUpdatedStatus.NOT_PROVIDED):
    return Clocks(bk_captured=UTC, source_updated_status=st, source_updated=su,
                  event_effective=KICK)


def _team_ident(team="PIT"):
    return Identity(grain=IdentityGrain.TEAM, base={"sport": "nfl", "season": 2026},
                    ext={"team": team}, identity_quality=IdentityQuality.DECLARED_COMPOSITE,
                    collision_tested=True, key=f"(nfl,2026,{team})")


def _side_ident(side="HOME"):
    return Identity(grain=IdentityGrain.TEAM_SIDE,
                    base={"sport": "nfl", "season": 2026, "event_id": "401001"},
                    ext={"team_side": side}, identity_quality=IdentityQuality.DECLARED_COMPOSITE,
                    collision_tested=True, key=f"(401001,{side})")


def _disp_rows():
    return [
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("NO", _team_ident("NO"), Leaf.RENDERED, "QUALIFIED", 1),
    ]


def _batch(rows=None, **kw):
    base = dict(
        receipt_id=DISP_ID, receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
        schema_version=SchemaVersion(1, 0), surface_id="nfl_ats_wave",
        universe=Universe("team", "nfl_ats_board_2026", "v1"), created_seq=10, created_at=UTC,
        versions=_versions(), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=_clocks(), input_hashes=["h-in-1"], integrity=Integrity(),
        body=EntityDispositionBatch(_disp_rows() if rows is None else rows),
    )
    base.update(kw)
    return Receipt(**base)


def _board(**kw):
    base = dict(
        receipt_id=BOARD_ID, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id="nfl_ats_wave",
        universe=Universe("team", "nfl_ats_board_2026", "v1"), created_seq=11, created_at=UTC,
        versions=_versions(), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=_clocks(), input_hashes=["h-in-1"],
        refs=Refs(entity_dispositions=DISP_ID, source_health="sh-1"),
        body=LiveEvidenceBoard("m1", {"RENDERED": 1, "NONMEMBER": 1}, 2),
    )
    base.update(kw)
    return Receipt(**base)


def _dec_rows():
    return [
        DecisionStageRow("(401001, HOME)", _side_ident("HOME"), StageOutcome.GRADED, "GRADED", 1),
        DecisionStageRow("(401001, AWAY)", _side_ident("AWAY"), StageOutcome.NO_LINE, "NO_LINE", 1),
    ]


def _decision(rows=None, **kw):
    base = dict(
        receipt_id=DEC_ID, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id="nfl_ats_wave",
        universe=Universe("team_side_decision", "nfl_ats_decisions_2026", "v1"),
        created_seq=9, created_at=UTC, versions=_versions(),
        replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=["h-in-1"],
        integrity=Integrity(), body=DecisionStageBatch(_dec_rows() if rows is None else rows),
    )
    base.update(kw)
    return Receipt(**base)


# --- harness ----------------------------------------------------------------

def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label if cond else f"{label}")

    def valid(receipt, label):
        seal_hashes(receipt)
        r = validate_receipt(receipt)
        (checks if r.ok else failures).append(label if r.ok else f"{label}  -> {r.errors}")

    def invalid(receipt, substr, label):
        r = validate_receipt(receipt)
        good = (not r.ok) and any(substr in e for e in r.errors)
        (checks if good else failures).append(label if good else f"{label}  -> {r.errors}")

    # --- (1) frozen enums exact (incl. Rev-2.3a team grain) ------------------
    ok({k.value for k in ReceiptKind} == {"live_evidence", "entity_disposition",
        "decision_time", "correction", "render", "source_health"}, "receipt_kind = six kinds")
    ok({a.value for a in AuthorityClass} == {"fact", "derived_context",
        "descriptive_mismatch", "governed_model", "user_thesis"}, "authority_class = five classes")
    ok({r.value for r in ReplayClass} == {"EXACT_REPLAY", "EVIDENCE_EQUIVALENT",
        "NON_REPLAYABLE"}, "replay_class = three classes")
    ok({l.value for l in Leaf} == {"RENDERED", "SUPPRESSED", "NONMEMBER", "EXCLUDED",
        "UNAVAILABLE", "INDETERMINATE", "FAILED"}, "leaf = seven leaves")
    ok({g.value for g in IdentityGrain} == {"event", "team", "team_side", "market_obs",
        "selection", "grading"}, "identity grain = six grains incl. Rev-2.3a 'team'")
    ok({q.value for q in IdentityQuality} == {"PROVIDER_ID", "DECLARED_COMPOSITE",
        "COMPOSITE_NAME_EVENT", "ALIAS_RESOLVED", "NAME_ONLY", "AMBIGUOUS", "UNRESOLVED"},
       "identity_quality = seven values")
    ok({s.value for s in SourceUpdatedStatus} == {"PRESENT", "UNKNOWN", "NOT_PROVIDED"},
       "source_updated_status = three values")
    ok({m.value for m in IntegrityMechanism} == {"none", "hash_chain", "signed", "worm",
        "anchored", "audit_log"}, "integrity mechanism = six values")
    ok(dr.NOT_YET_CONSTRUCTED_KINDS == {ReceiptKind.DECISION_TIME, ReceiptKind.CORRECTION,
        ReceiptKind.RENDER, ReceiptKind.SOURCE_HEALTH}, "four kinds not-yet-constructed")
    invalid(_batch(receipt_kind=ReceiptKind.CORRECTION), "not-yet-constructed",
            "a not-yet-constructed kind with a body is rejected")

    # --- valid receipts + grain binding --------------------------------------
    valid(_batch(), "valid entity_disposition (team grain) receipt passes")
    valid(_board(), "valid board live_evidence receipt passes")
    valid(_decision(), "valid decision-stage (team_side grain) receipt passes")
    invalid(_batch(rows=[EntityDisposition("PIT", _side_ident("HOME"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1)]), "does not match the universe's bound grain",
            "board row with team_side identity is rejected (R14b grain binding)")
    invalid(_decision(rows=[DecisionStageRow("x", _team_ident("PIT"), StageOutcome.GRADED,
            "GRADED", 1)]), "does not match the universe's bound grain",
            "decision row with team identity is rejected (R14b grain binding)")
    invalid(_batch(universe=Universe("team_side_decision", "x", "v1")),
            "universe.grain 'team'", "entity_disposition batch under the wrong universe grain is rejected")
    invalid(_decision(universe=Universe("team", "x", "v1")),
            "universe.grain 'team_side_decision'", "decision batch under the wrong universe grain is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", Identity(IdentityGrain.TEAM,
            {"sport": "nfl", "season": 2026}, {}, IdentityQuality.DECLARED_COMPOSITE, True,
            "(nfl,2026,PIT)"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)]),
            "ext must carry ['team']", "team identity missing its required ext.team is rejected")

    # --- (2) tamper-evidence METADATA only (no verified claim) ---------------
    signed = seal_hashes(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED, proof="sig")))
    ok(validate_receipt(signed).ok and has_tamper_evidence_metadata(signed.integrity),
       "has_tamper_evidence_metadata: structurally complete (mechanism+proof present)")
    ok(not has_tamper_evidence_metadata(_batch().integrity),
       "has_tamper_evidence_metadata false for mechanism=none (no claim from a name alone)")
    ok(not hasattr(dr, "is_tamper_evident"),
       "no is_tamper_evident() — a name+string must not assert verified tamper-evidence")

    # --- (3) exact-Z UTC (reject +00:00, offsets, naive, fractional) ---------
    for bad in ("yesterday", "UNKNOWN", "2026-10-25 12:00:00", "2026-10-25T12:00:00",
                "2026-10-25T12:00:00+05:00", "2026-10-25T12:00:00+00:00",
                "2026-10-25T12:00:00.000Z"):
        invalid(_batch(clocks=Clocks(bk_captured=bad,
                source_updated_status=SourceUpdatedStatus.NOT_PROVIDED,
                source_updated=None, event_effective=KICK)),
                "bk_captured must be a tz-aware UTC", f"clock {bad!r} is rejected (exact Z only)")
    invalid(_batch(clocks=Clocks(bk_captured=UTC, source_updated_status=SourceUpdatedStatus.PRESENT,
            source_updated="UNKNOWN", event_effective=KICK)),
            "source_updated must be a tz-aware UTC", "literal 'UNKNOWN' source_updated is rejected")
    invalid(_batch(clocks=Clocks(bk_captured=UTC, source_updated_status=SourceUpdatedStatus.PRESENT,
            source_updated=None)), "null source_updated requires status",
            "status PRESENT with null source_updated is rejected")
    invalid(_batch(clocks=Clocks(bk_captured=UTC, source_updated_status=SourceUpdatedStatus.NOT_PROVIDED,
            source_updated=UTC)), "present source_updated requires status PRESENT",
            "status NOT_PROVIDED with a present source_updated is rejected")
    ok(validate_receipt(seal_hashes(_batch(clocks=Clocks(bk_captured=UTC,
       source_updated_status=SourceUpdatedStatus.PRESENT, source_updated=UTC,
       event_effective=KICK)))).ok, "a fully valid PRESENT clock set passes")

    # --- (4) exact-Decimal numeric profiles ----------------------------------
    ok(canonical_number("3", "line") == "3.00" and canonical_number(3.0, "line") == "3.00"
       and canonical_number("3.50", "line") == "3.50" and canonical_number("-3.5", "line") == "-3.50"
       and canonical_number("0", "line") == "0.00", "line -> exact half-point decimal string")
    ok(canonical_number("-110", "price") == "-110" and canonical_number("150", "price") == "+150"
       and canonical_number("100", "price") == "+100", "price -> American integer string with sign")
    ok(canonical_number("0.5", "probability") == "0.5000" and canonical_number("0", "probability") == "0.0000"
       and canonical_number("1", "probability") == "1.0000", "probability -> fixed 4dp")
    ok(canonical_number("3", "count") == "3" and canonical_number("0", "count") == "0", "count -> integer")
    for bad, prof in (("3.3", "line"), ("1.5", "probability"), ("-0.01", "probability"),
                      ("0.12345", "probability"), ("50", "price"), ("110.5", "price"),
                      ("-1", "count"), ("2.5", "count")):
        try:
            canonical_number(bad, prof)
            ok(False, f"out-of-profile {bad}/{prof} should raise")
        except NumericProfileError:
            ok(True, f"out-of-profile {bad}/{prof} raises (exact decimal, no silent rounding)")
    ok(canonical_number("0.5000", "probability") == "0.5000",
       "probability at exactly 4dp is accepted (no excess precision)")
    invalid(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"p": GovernedNumber("0.12345", "probability")})]),
            "numeric profile", "a param exceeding 4dp (no rounding rule) is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"raw": 0.5})]), "bare float", "a bare float param is rejected")

    # --- (5) allowlisted reason-code registry (dynamic code rejected) --------
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), Leaf.NONMEMBER,
            "SORTED_BY_streak_desc", 1)]), "invalid code shape",
            "a reason_code with invalid shape (lowercase) is rejected")
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), Leaf.NONMEMBER,
            "SORTED_BY_STREAK_DESC", 1)]), "not in the allowlisted registry",
            "a well-shaped but UNREGISTERED dynamic code is rejected (R8)")
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), Leaf.NONMEMBER, "GRADED", 1)]),
            "is a stage_outcome code used where a leaf is required",
            "a stage_outcome reason used on a board leaf row is rejected (category)")
    invalid(_decision(rows=[DecisionStageRow("x", _side_ident("HOME"), StageOutcome.GRADED,
            "BELOW_THRESHOLD", 1)]), "is a leaf code used where a stage_outcome is required",
            "a leaf reason used on a decision-stage row is rejected (category)")

    # --- firewall BOTH directions + roll-up ----------------------------------
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), StageOutcome.GRADED, "GRADED", 1)]),
            "stage outcome used as a terminal leaf", "stage outcome used as a leaf is rejected")
    invalid(_decision(rows=[DecisionStageRow("x", _side_ident("HOME"), Leaf.RENDERED, "QUALIFIED", 1)]),
            "presentation leaf used as a decision-stage outcome",
            "presentation leaf used as a stage outcome is rejected")
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), "ELIGIBLE", "QUALIFIED", 1)]),
            "roll-up", "a roll-up (ELIGIBLE) used as a leaf is rejected (R5)")

    # --- (6) envelope + cross-grain -----------------------------------------
    invalid(_batch(receipt_id="disp-1"), "opaque UUID", "a non-UUID receipt_id is rejected (P2A-1)")
    invalid(_batch(created_seq=0), "created_seq must be a positive",
            "created_seq <= 0 is rejected")
    invalid(_batch(universe=Universe("", "id", "v1")), "universe.grain required",
            "empty universe.grain is rejected")
    invalid(_batch(universe=Universe("team", "", "v1")), "universe.id required",
            "empty universe.id is rejected")
    invalid(_batch(universe=Universe("team", "id", "")), "universe.version required",
            "empty universe.version is rejected")
    invalid(_batch(replay_class=ReplayClass.NON_REPLAYABLE, input_hashes=None,
            authority_class=AuthorityClass.FACT), "MUST NOT be NON_REPLAYABLE",
            "factual authority may not be NON_REPLAYABLE")
    invalid(_batch(replay_class=ReplayClass.NON_REPLAYABLE, input_hashes=None,
            authority_class=AuthorityClass.GOVERNED_MODEL), "MUST NOT be NON_REPLAYABLE",
            "governed_model authority may not be NON_REPLAYABLE")
    ok(validate_receipt(seal_hashes(_batch(replay_class=ReplayClass.NON_REPLAYABLE,
       input_hashes=None, authority_class=AuthorityClass.USER_THESIS))).ok,
       "NON_REPLAYABLE is allowed for a non-factual authority (user_thesis)")

    # --- exactly-one + conservation + reconcile ------------------------------
    invalid(_batch(rows=[
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1),
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.RENDERED, "QUALIFIED", 1)]),
        "duplicate entity_ref", "duplicate entity_ref (two leaves) is rejected (R4)")
    invalid(_board(body=LiveEvidenceBoard("m1", {"RENDERED": 1, "NONMEMBER": 1}, 5)),
            "conservation", "board per-leaf counts not summing to expected_count are rejected")
    invalid(_board(refs=Refs(entity_dispositions=None, source_health="sh-1")),
            "entity_dispositions batch", "board missing its entity_dispositions ref is rejected")
    ok(reconcile_board(seal_hashes(_board()), seal_hashes(_batch())).ok,
       "reconcile_board: board counts reconcile against the referenced batch tally")
    ok(not reconcile_board(seal_hashes(_board()), seal_hashes(_batch(surface_id="other"))).ok,
       "reconcile_board: surface mismatch between board and batch is rejected")
    ok(not reconcile_board(seal_hashes(_board()),
       seal_hashes(_batch(versions=_versions("build-2")))).ok,
       "reconcile_board: build_id mismatch between board and batch is rejected")
    ok(not reconcile_board(seal_hashes(_board(body=LiveEvidenceBoard("m1", {"RENDERED": 2}, 2))),
       seal_hashes(_batch())).ok, "reconcile_board: count mismatch is rejected")

    # --- complete authoritative conclusion subtree ---------------------------
    c0 = compute_conclusion_hash(_batch())
    k0 = compute_content_hash(_batch())
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER, "COVER_SHORT", 1),
        EntityDisposition("NO", _team_ident("NO"), Leaf.RENDERED, "QUALIFIED", 1)])) != c0,
       "conclusion_hash changes when a reason_code changes")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 2),
        EntityDisposition("NO", _team_ident("NO"), Leaf.RENDERED, "QUALIFIED", 1)])) != c0,
       "conclusion_hash changes when a reason_def_version changes")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(4, "count")}),
        EntityDisposition("NO", _team_ident("NO"), Leaf.RENDERED, "QUALIFIED", 1)])) != c0,
       "conclusion_hash changes when a governed param changes")
    ok(compute_conclusion_hash(_batch(universe=Universe("team", "nfl_ats_board_2026", "v2"))) != c0,
       "conclusion_hash changes when universe.version changes")
    ok(compute_conclusion_hash(_batch(rows=list(reversed(_disp_rows())))) != c0,
       "conclusion_hash changes when membership ORDER changes (authoritative)")
    ok(compute_conclusion_hash(_batch(created_seq=999)) == c0
       and compute_conclusion_hash(_batch(created_at="2020-01-01T00:00:00Z")) == c0
       and compute_conclusion_hash(_batch(receipt_id=BOARD_ID)) == c0
       and compute_conclusion_hash(_batch(integrity=Integrity(
           mechanism=IntegrityMechanism.SIGNED, proof="sig"))) == c0,
       "conclusion_hash is stable under receipt-instance metadata (seq/created_at/id/integrity)")
    ok(compute_content_hash(_batch(created_seq=999)) != k0
       and compute_content_hash(_batch(created_at="2020-01-01T00:00:00Z")) != k0,
       "content_hash changes when a stored metadata field changes")
    r1 = seal_hashes(_batch(receipt_id=DISP_ID, created_seq=10))
    r2 = seal_hashes(_batch(receipt_id=BOARD_ID, created_seq=11))
    ok(r1.conclusion_hash == r2.conclusion_hash
       and r1.integrity.content_hash != r2.integrity.content_hash,
       "two rebuilds share conclusion_hash but differ in content_hash (Rev-2 #1)")

    # --- integrity structure + self-hash exclusion ---------------------------
    invalid(_batch(integrity=Integrity(hash_algorithm="md5")), "hash_algorithm not allowlisted",
            "a non-allowlisted hash_algorithm is rejected")
    invalid(_batch(integrity=Integrity(mechanism=IntegrityMechanism.NONE, proof="x")),
            "mechanism=none must not carry a proof", "mechanism=none with a proof is rejected")
    invalid(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED)),
            "requires proof material", "mechanism=signed without proof material is rejected")
    tampered = seal_hashes(_batch()); tampered.integrity.content_hash = "0" * 64
    ok(not validate_receipt(tampered).ok, "a declared content_hash mismatch is rejected")
    tconc = seal_hashes(_batch()); tconc.conclusion_hash = "0" * 64
    ok(not validate_receipt(tconc).ok, "a declared conclusion_hash mismatch is rejected")
    p = seal_hashes(_batch()); base_c = compute_content_hash(p)
    p.integrity.content_hash = "deadbeef" * 8
    ok(compute_content_hash(p) == base_c, "self-hash exclusion: stored content_hash excluded")
    ok(b_sep := (seal_hashes(_batch()).conclusion_hash
                 != seal_hashes(_batch()).integrity.content_hash),
       "conclusion_hash and content_hash are separate digests")

    # --- user_safe projection + supersession ---------------------------------
    invalid(_batch(projection=Projection.USER_SAFE, input_hashes=["x"],
            replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.USER_THESIS,
            claims=["c"]), "must not carry input_hashes", "user_safe carrying input_hashes is rejected")
    ok(validate_receipt(seal_hashes(_batch(projection=Projection.USER_SAFE, input_hashes=None,
       replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.USER_THESIS,
       claims=["PIT is a NONMEMBER (cover_streak 2)"]))).ok,
       "a valid user_safe projection passes")
    ok(validate_receipt(seal_hashes(_batch(created_seq=10, supersedes_seq=4))).ok,
       "supersedes_seq < created_seq is valid")
    invalid(_batch(created_seq=10, supersedes_seq=10), "must be < this created_seq",
            "supersedes_seq == created_seq is rejected")

    # --- non-throwing validator + purity -------------------------------------
    try:
        r = validate_receipt(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"),
            Leaf.NONMEMBER, "BELOW_THRESHOLD", 1, {"raw": 0.5})]))
        ok(not r.ok, "validate_receipt is NON-THROWING on an uncanonicalizable (bare-float) field")
    except Exception as exc:
        ok(False, f"validate_receipt raised: {exc!r}")
    try:
        r = validate_receipt(_batch(created_seq="not-an-int"))
        ok(not r.ok, "validate_receipt is NON-THROWING on a type-wrong field")
    except Exception as exc:
        ok(False, f"validate_receipt raised: {exc!r}")
    before = set(os.listdir("."))
    x = _board(); h1, h2 = compute_content_hash(x), compute_content_hash(x)
    ok(set(os.listdir(".")) == before, "building + hashing creates no file in cwd")
    ok(h1 == h2, "content_hash is deterministic across calls")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 74)
    print("DECISION INTEGRITY CONTRACT LIBRARY QC (Phase 2B, Slice 1, Rev 3)")
    print("=" * 74)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"\n{len(r['checks'])} passed, {len(r['failures'])} failed")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
