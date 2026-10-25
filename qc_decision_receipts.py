"""QC: Decision Integrity shared contract library (Phase 2B, Slice 1, Rev 2).

Proves CONFORMANCE to the approved Phase 2A contract — not merely that the code
is self-consistent. Pure: imports only the contract library + stdlib. Touches no
app/route/data/network/filesystem (beyond a cwd listdir snapshot for the purity
check).

Invalid fixtures are provided for every blocking finding:
  (1) frozen enums exact + not-yet-constructed kinds rejected;
  (2) complete envelope (required fields enforced; conclusion_hash separate);
  (3) per-row identity (validated per row, not per batch);
  (4) exactly-one leaf (duplicate entity_ref) + board conservation + reconcile;
  (5) complete authoritative conclusion subtree (reason/version/params/identity/
      universe.version/membership-order change it; receipt-instance metadata does not);
  (6) governed numeric profiles (line/probability/price/count, decimal-string);
  (7) strict UTC clocks (reject 'yesterday'/'UNKNOWN'/naive/offset);
  (8) integrity hash_algorithm + mechanism structure (tamper_evident derived);
  (9) validator is non-throwing on malformed input.
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
    compute_content_hash, is_tamper_evident, reconcile_board, seal_hashes, validate_receipt,
)

UTC = "2026-10-25T12:51:21Z"
KICK = "2026-10-25T13:30:00Z"


# --- builders ---------------------------------------------------------------

def _versions():
    return Versions("build-1", "cfg-1", {"ats_streak": 1})


def _clocks(su=None, st=SourceUpdatedStatus.NOT_PROVIDED):
    return Clocks(bk_captured=UTC, source_updated_status=st, source_updated=su,
                  event_effective=KICK)


def _ident(q=IdentityQuality.PROVIDER_ID, grain=IdentityGrain.TEAM_SIDE, key="PIT", tested=False):
    return Identity(grain=grain, base={"sport": "nfl", "season": 2026, "event_id": "401001"},
                    ext={}, identity_quality=q, collision_tested=tested, key=key)


def _disp_rows():
    return [
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1),
    ]


def _batch(rows=None, **kw):
    base = dict(
        receipt_id="disp-1", receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
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
        receipt_id="board-1", receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id="nfl_ats_wave",
        universe=Universe("team", "nfl_ats_board_2026", "v1"), created_seq=11, created_at=UTC,
        versions=_versions(), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=_clocks(), input_hashes=["h-in-1"],
        refs=Refs(entity_dispositions="disp-1", source_health="sh-1"),
        body=LiveEvidenceBoard("m1", {"RENDERED": 1, "NONMEMBER": 1}, 2),
    )
    base.update(kw)
    return Receipt(**base)


def _dec_rows():
    return [
        DecisionStageRow("(401001, HOME)",
                         _ident(IdentityQuality.DECLARED_COMPOSITE, key="(401001, HOME)", tested=True),
                         StageOutcome.GRADED, "GRADED", 1),
        DecisionStageRow("(401001, AWAY)",
                         _ident(IdentityQuality.DECLARED_COMPOSITE, key="(401001, AWAY)", tested=True),
                         StageOutcome.NO_LINE, "NO_LINE", 1),
    ]


def _decision(rows=None, **kw):
    base = dict(
        receipt_id="dec-1", receipt_kind=ReceiptKind.LIVE_EVIDENCE,
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
        (checks if cond else failures).append(label)

    def valid(receipt, label):
        seal_hashes(receipt)
        r = validate_receipt(receipt)
        ok(r.ok, f"{label}" + ("" if r.ok else f"  -> {r.errors}"))

    def invalid(receipt, substr, label):
        r = validate_receipt(receipt)   # unsealed; non-throwing
        ok((not r.ok) and any(substr in e for e in r.errors),
           f"{label}" + ("" if (not r.ok) and any(substr in e for e in r.errors)
                         else f"  -> {r.errors}"))

    # --- (1) frozen enums are EXACTLY the approved closed vocabularies -------
    ok({k.value for k in ReceiptKind} == {"live_evidence", "entity_disposition",
        "decision_time", "correction", "render", "source_health"},
       "receipt_kind = exactly the six approved kinds")
    ok({a.value for a in AuthorityClass} == {"fact", "derived_context",
        "descriptive_mismatch", "governed_model", "user_thesis"},
       "authority_class = exactly the five approved classes")
    ok({r.value for r in ReplayClass} == {"EXACT_REPLAY", "EVIDENCE_EQUIVALENT",
        "NON_REPLAYABLE"}, "replay_class = exactly the three approved classes")
    ok({l.value for l in Leaf} == {"RENDERED", "SUPPRESSED", "NONMEMBER", "EXCLUDED",
        "UNAVAILABLE", "INDETERMINATE", "FAILED"}, "leaf = exactly the seven approved leaves")
    ok({q.value for q in IdentityQuality} == {"PROVIDER_ID", "DECLARED_COMPOSITE",
        "COMPOSITE_NAME_EVENT", "ALIAS_RESOLVED", "NAME_ONLY", "AMBIGUOUS", "UNRESOLVED"},
       "identity_quality = exactly the seven approved values")
    ok({s.value for s in SourceUpdatedStatus} == {"PRESENT", "UNKNOWN", "NOT_PROVIDED"},
       "source_updated_status = {PRESENT, UNKNOWN, NOT_PROVIDED}")
    ok({m.value for m in IntegrityMechanism} == {"none", "hash_chain", "signed", "worm",
        "anchored", "audit_log"}, "integrity mechanism = exactly the six approved values")
    ok({c.value for c in dr.SemanticCategory} == {"leaf", "health", "stage_outcome", "transition"},
       "semantic_category = {leaf, health, stage_outcome, transition}")
    ok({c.value for c in dr.ChangeKind} == {"regrade", "line_correction", "reschedule",
        "identity_fix", "retraction"}, "change_kind = exactly the five approved values")
    ok({g.value for g in IdentityGrain} == {"event", "team_side", "market_obs", "selection",
        "grading"}, "identity grain = exactly the five approved grains")
    ok(dr.NOT_YET_CONSTRUCTED_KINDS == {ReceiptKind.DECISION_TIME, ReceiptKind.CORRECTION,
        ReceiptKind.RENDER, ReceiptKind.SOURCE_HEALTH}, "four kinds marked not-yet-constructed")
    invalid(_batch(receipt_kind=ReceiptKind.CORRECTION), "not-yet-constructed",
            "a not-yet-constructed kind with a body is rejected")

    # --- (2) complete envelope ----------------------------------------------
    valid(_batch(), "valid entity_disposition receipt passes")
    valid(_board(), "valid board live_evidence receipt passes")
    valid(_decision(), "valid decision-stage live_evidence receipt passes")
    b = _batch(); seal_hashes(b)
    ok(b.conclusion_hash and b.integrity.content_hash
       and b.conclusion_hash != b.integrity.content_hash,
       "conclusion_hash is a separate top-level digest, distinct from content_hash")
    invalid(_batch(created_at="2026-10-25"), "created_at must be a tz-aware UTC",
            "missing/invalid created_at is rejected")
    invalid(_batch(versions=Versions("", "cfg", {})), "versions.build_id required",
            "incomplete versions is rejected")
    invalid(_batch(universe=Universe("team", "id", "")), "universe.version required",
            "missing universe.version is rejected")
    invalid(_batch(replay_class=ReplayClass.EVIDENCE_EQUIVALENT, input_hashes=None),
            "requires input_hashes", "replay_class != NON_REPLAYABLE requires input_hashes")
    ok(validate_receipt(seal_hashes(_batch(replay_class=ReplayClass.NON_REPLAYABLE,
       input_hashes=None))).ok, "NON_REPLAYABLE without input_hashes is allowed")

    # --- (3) per-row identity (not a single batch identity) ------------------
    mixed = _batch(rows=[
        EntityDisposition("PIT", _ident(IdentityQuality.PROVIDER_ID, key="PIT"),
                          Leaf.NONMEMBER, "BELOW_THRESHOLD", 1),
        EntityDisposition("NO", _ident(IdentityQuality.AMBIGUOUS, key="NO"),
                          Leaf.RENDERED, "SORTED", 1),  # bad: ambiguous must fail closed
    ])
    r = validate_receipt(mixed)
    ok((not r.ok) and any("rows[1]" in e and "fail closed" in e for e in r.errors)
       and not any("rows[0]" in e for e in r.errors),
       "identity is validated PER ROW (row 1 fails closed; row 0 is fine)")
    invalid(_batch(rows=[EntityDisposition("x", _ident(IdentityQuality.DECLARED_COMPOSITE,
            key="x", tested=False), Leaf.RENDERED, "SORTED", 1)]),
            "collision_tested", "composite identity without a passed collision test is rejected")

    # --- (4) exactly-one leaf + conservation + reconcile ---------------------
    invalid(_batch(rows=[
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1),
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.RENDERED, "SORTED", 1)]),
        "duplicate entity_ref", "duplicate entity_ref (two leaves) is rejected (R4)")
    invalid(_board(body=LiveEvidenceBoard("m1", {"RENDERED": 1, "NONMEMBER": 1}, 5)),
            "conservation", "board per-leaf counts that do not sum to expected_count are rejected")
    invalid(_board(refs=Refs(entity_dispositions=None, source_health="sh-1")),
            "entity_dispositions batch", "board missing its entity_dispositions ref is rejected")
    good_board = seal_hashes(_board())
    good_batch = seal_hashes(_batch())
    ok(reconcile_board(good_board, good_batch).ok,
       "reconcile_board: board counts reconcile against the referenced batch tally")
    bad_recon = seal_hashes(_board(body=LiveEvidenceBoard("m1", {"RENDERED": 2}, 2)))
    ok(not reconcile_board(bad_recon, good_batch).ok,
       "reconcile_board: mismatched counts are rejected")

    # --- firewall BOTH directions -------------------------------------------
    invalid(_batch(rows=[EntityDisposition("x", _ident(key="x"), StageOutcome.GRADED, "GRADED", 1)]),
            "stage outcome used as a terminal leaf", "stage outcome used as a leaf is rejected")
    invalid(_decision(rows=[DecisionStageRow("x", _ident(IdentityQuality.DECLARED_COMPOSITE,
            key="x", tested=True), Leaf.RENDERED, "SORTED", 1)]),
            "presentation leaf used as a decision-stage outcome",
            "presentation leaf used as a stage outcome is rejected")
    invalid(_batch(rows=[EntityDisposition("x", _ident(key="x"), "ELIGIBLE", "SORTED", 1)]),
            "roll-up", "a roll-up (ELIGIBLE) used as a leaf is rejected (R5)")
    invalid(_batch(rows=[EntityDisposition("x", _ident(key="x"), Leaf.NONMEMBER,
            "SORTED_BY_streak_desc", 1)]), "UPPER_SNAKE",
            "an interpolated reason_code is rejected (R8)")

    # --- (5) complete authoritative conclusion subtree -----------------------
    c0 = compute_conclusion_hash(_batch())
    k0 = compute_content_hash(_batch())
    # conclusion CHANGES on each authoritative field:
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "COVER_SHORT", 1),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1)])) != c0,
       "conclusion_hash changes when a reason_code changes (BELOW_THRESHOLD->other)")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 2),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1)])) != c0,
       "conclusion_hash changes when a reason_def_version changes")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(4, "count")}),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1)])) != c0,
       "conclusion_hash changes when a governed param changes")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _ident(IdentityQuality.ALIAS_RESOLVED, key="PIT"),
                          Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1)])) != c0,
       "conclusion_hash changes when identity_quality changes")
    ok(compute_conclusion_hash(_batch(universe=Universe("team", "nfl_ats_board_2026", "v2"))) != c0,
       "conclusion_hash changes when universe.version changes")
    ok(compute_conclusion_hash(_batch(rows=list(reversed(_disp_rows())))) != c0,
       "conclusion_hash changes when membership ORDER changes (authoritative)")
    # conclusion is STABLE under receipt-instance metadata (R3b):
    ok(compute_conclusion_hash(_batch(created_seq=999)) == c0,
       "conclusion_hash is stable under created_seq")
    ok(compute_conclusion_hash(_batch(created_at="2026-01-01T00:00:00Z")) == c0,
       "conclusion_hash is stable under created_at")
    ok(compute_conclusion_hash(_batch(receipt_id="other")) == c0,
       "conclusion_hash is stable under receipt_id")
    ok(compute_conclusion_hash(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED,
       proof="sig"))) == c0, "conclusion_hash is stable under integrity")
    # content tracks stored fields:
    ok(compute_content_hash(_batch(created_seq=999)) != k0,
       "content_hash changes when created_seq changes")
    ok(compute_content_hash(_batch(created_at="2026-01-01T00:00:00Z")) != k0,
       "content_hash changes when created_at changes")
    # EXACT_REPLAY example: two rebuilds share conclusion_hash, differ in content.
    r1 = seal_hashes(_batch(receipt_id="a", created_seq=10))
    r2 = seal_hashes(_batch(receipt_id="b", created_seq=11))
    ok(r1.conclusion_hash == r2.conclusion_hash
       and r1.integrity.content_hash != r2.integrity.content_hash,
       "two rebuilds share conclusion_hash but differ in content_hash (Rev-2 #1)")

    # --- (6) governed numeric profiles ---------------------------------------
    ok(canonical_number(3, "line") == "3.00" and canonical_number(3.0, "line") == "3.00"
       and canonical_number("3.00", "line") == "3.00" and canonical_number(-3.5, "line") == "-3.50",
       "line profile -> canonical half-point decimal string")
    ok(canonical_number(-110, "price") == "-110" and canonical_number(150, "price") == "+150",
       "price profile -> American integer string with sign")
    ok(canonical_number(0.5, "probability") == "0.5000" and canonical_number(1, "count") == "1",
       "probability (fixed dp) and count (integer) profiles")
    ok(compute_conclusion_hash(_batch(rows=[
        EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": GovernedNumber(3, "count")}),
        EntityDisposition("NO", _ident(key="NO"), Leaf.RENDERED, "SORTED", 1)])) == c0,
       "GovernedNumber int 3 and the baseline canonicalize identically (profile collapse)")
    for bad, prof in ((3.3, "line"), (1.5, "probability"), (50, "price"), (-1, "count")):
        try:
            canonical_number(bad, prof)
            ok(False, f"out-of-profile {bad!r}/{prof} should raise")
        except NumericProfileError:
            ok(True, f"out-of-profile {bad!r}/{prof} raises NumericProfileError")
    invalid(_batch(rows=[EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"threshold": GovernedNumber(3.3, "line")})]),
            "numeric profile", "a param violating its numeric profile is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", _ident(key="PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"raw": 0.5})]), "bare float",
            "a bare float param (no governed profile) is rejected")

    # --- (7) strict UTC clocks ----------------------------------------------
    for bad in ("yesterday", "UNKNOWN", "2026-10-25 12:00:00", "2026-10-25T12:00:00",
                "2026-10-25T12:00:00+05:00"):
        invalid(_batch(clocks=_clocks().__class__(bk_captured=bad,
                source_updated_status=SourceUpdatedStatus.NOT_PROVIDED,
                source_updated=None, event_effective=KICK)),
                "bk_captured must be a tz-aware UTC", f"clock {bad!r} is rejected")
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

    # --- (8) integrity algorithm + mechanism structure ----------------------
    invalid(_batch(integrity=Integrity(hash_algorithm="md5")), "hash_algorithm not allowlisted",
            "a non-allowlisted hash_algorithm is rejected")
    invalid(_batch(integrity=Integrity(mechanism=IntegrityMechanism.NONE, proof="x")),
            "mechanism=none must not carry a proof", "mechanism=none with a proof is rejected")
    invalid(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED)),
            "requires proof material", "mechanism=signed without proof material is rejected")
    signed = seal_hashes(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED, proof="sig")))
    ok(validate_receipt(signed).ok and is_tamper_evident(signed.integrity),
       "mechanism=signed + proof: valid and tamper_evident is derived true")
    ok(not is_tamper_evident(_batch().integrity),
       "mechanism=none: tamper_evident is derived false (no claim from a name alone)")
    tampered = seal_hashes(_batch()); tampered.integrity.content_hash = "0" * 64
    ok(not validate_receipt(tampered).ok, "a declared content_hash mismatch is rejected")
    tconc = seal_hashes(_batch()); tconc.conclusion_hash = "0" * 64
    ok(not validate_receipt(tconc).ok, "a declared conclusion_hash mismatch is rejected")
    # self-hash exclusion:
    p = seal_hashes(_batch()); base_c = compute_content_hash(p)
    p.integrity.content_hash = "deadbeef" * 8
    ok(compute_content_hash(p) == base_c, "self-hash exclusion: stored content_hash excluded")
    p.integrity = Integrity(mechanism=IntegrityMechanism.SIGNED, proof="sig",
                            content_hash="deadbeef" * 8)
    ok(compute_content_hash(p) != base_c, "a real stored field (mechanism/proof-less change) is in content")
    # user_safe projection:
    invalid(_batch(projection=Projection.USER_SAFE, input_hashes=["x"],
            replay_class=ReplayClass.NON_REPLAYABLE, claims=["c"]),
            "must not carry input_hashes", "user_safe carrying input_hashes is rejected")
    ok(validate_receipt(seal_hashes(_batch(projection=Projection.USER_SAFE, input_hashes=None,
       replay_class=ReplayClass.NON_REPLAYABLE, claims=["PIT is a NONMEMBER (cover_streak 2)"]))).ok,
       "a valid user_safe projection (no input_hashes/proof, has claims) passes")

    # --- supersession --------------------------------------------------------
    ok(validate_receipt(seal_hashes(_batch(created_seq=10, supersedes_seq=4))).ok,
       "supersedes_seq < created_seq is valid")
    invalid(_batch(created_seq=10, supersedes_seq=10), "must be < this created_seq",
            "supersedes_seq == created_seq is rejected")

    # --- (9) non-throwing validator ------------------------------------------
    try:
        r = validate_receipt(_batch(rows=[EntityDisposition("PIT", _ident(key="PIT"),
            Leaf.NONMEMBER, "BELOW_THRESHOLD", 1, {"raw": 0.5})]))
        ok(not r.ok, "validate_receipt is NON-THROWING on an uncanonicalizable (bare-float) field")
    except Exception as exc:
        ok(False, f"validate_receipt raised instead of returning errors: {exc!r}")
    try:
        r = validate_receipt(_batch(created_seq="not-an-int"))
        ok(not r.ok, "validate_receipt is NON-THROWING on a type-wrong field")
    except Exception as exc:
        ok(False, f"validate_receipt raised: {exc!r}")

    # --- purity + determinism ------------------------------------------------
    before = set(os.listdir("."))
    x = _board(); h1, h2 = compute_content_hash(x), compute_content_hash(x)
    ok(set(os.listdir(".")) == before, "building + hashing creates no file in cwd")
    ok(h1 == h2, "content_hash is deterministic across calls")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("DECISION INTEGRITY CONTRACT LIBRARY QC (Phase 2B, Slice 1, Rev 2)")
    print("=" * 72)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"\n{len(r['checks'])} passed, {len(r['failures'])} failed")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
