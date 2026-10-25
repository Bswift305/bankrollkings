"""QC: Decision Integrity shared contract library (Phase 2B, Slice 1, Rev 4).

Proves CONFORMANCE to the approved Phase 2A contract (incl. Rev-2.3a `team` grain).
Pure: imports only the contract library + stdlib (+ a cwd listdir snapshot).

Rev-4 makes the membership hash and cross-receipt binding REAL (not merely counted):
recomputed membership_hash, validated+build-context-bound reconciliation, governed
TEAM identity profiles (a bare name cannot be PROVIDER_ID), float-rejecting governed
numbers, and digest/shape hardening.
"""
from __future__ import annotations

import os
from decimal import Decimal

import services.decision_receipts as dr
from services.decision_receipts import (
    AuthorityClass, Clocks, DecisionStageBatch, DecisionStageRow, EntityDisposition,
    EntityDispositionBatch, GovernedNumber, Identity, IdentityGrain, IdentityQuality,
    Integrity, IntegrityMechanism, Leaf, LiveEvidenceBoard, NumericProfileError,
    Projection, Receipt, ReceiptKind, Refs, ReplayClass, SchemaVersion, SourceUpdatedStatus,
    StageOutcome, Universe, Versions, canonical_number, compute_conclusion_hash,
    compute_content_hash, compute_membership_hash, has_tamper_evidence_metadata,
    reconcile_board, seal_hashes, validate_receipt,
)

UTC = "2026-10-25T12:51:21Z"
KICK = "2026-10-25T13:30:00Z"
DISP_ID = "11111111-1111-4111-8111-111111111111"
BOARD_ID = "22222222-2222-4222-8222-222222222222"
DEC_ID = "33333333-3333-4333-8333-333333333333"
IH = "ab" * 32           # a 64-char lowercase hex digest
HEXH = "cd" * 32         # another valid hex digest placeholder


# --- builders ---------------------------------------------------------------

def _versions(build_id="build-1", config="cfg-1", rules=None):
    return Versions(build_id, config, rules if rules is not None else {"ats_streak": 1})


def _clocks(su=None, st=SourceUpdatedStatus.NOT_PROVIDED):
    return Clocks(bk_captured=UTC, source_updated_status=st, source_updated=su,
                  event_effective=KICK)


def _team_ident(team="PIT"):
    return Identity(grain=IdentityGrain.TEAM, base={"sport": "nfl", "season": 2026},
                    ext={"team": team}, identity_quality=IdentityQuality.DECLARED_COMPOSITE,
                    collision_tested=True, key=f"(nfl,2026,{team})",
                    profile="team:sport+season", profile_version="v1",
                    collision_proof="unique-in-sport-season")


def _provider_team_ident(team="PIT"):
    return Identity(grain=IdentityGrain.TEAM, base={"sport": "nfl", "season": 2026},
                    ext={"provider_namespace": "nflverse", "provider_team_id": team},
                    identity_quality=IdentityQuality.PROVIDER_ID, collision_tested=False,
                    key=f"nflverse:{team}")


def _side_ident(side="HOME"):
    return Identity(grain=IdentityGrain.TEAM_SIDE,
                    base={"sport": "nfl", "season": 2026, "event_id": "401001"},
                    ext={"team_side": side}, identity_quality=IdentityQuality.DECLARED_COMPOSITE,
                    collision_tested=True, key=f"(401001,{side})",
                    profile="team_side:event+side", profile_version="v1",
                    collision_proof="unique-per-event")


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
        clocks=_clocks(), input_hashes=[IH], integrity=Integrity(),
        body=EntityDispositionBatch(_disp_rows() if rows is None else rows),
    )
    base.update(kw)
    return Receipt(**base)


def _counts(batch):
    t = {}
    for r in batch.body.rows:
        t[r.leaf.value] = t.get(r.leaf.value, 0) + 1
    return t


def _board(**kw):
    base = dict(
        receipt_id=BOARD_ID, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id="nfl_ats_wave",
        universe=Universe("team", "nfl_ats_board_2026", "v1"), created_seq=11, created_at=UTC,
        versions=_versions(), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=_clocks(), input_hashes=[IH],
        refs=Refs(entity_dispositions=DISP_ID, source_health="sh-1"),
        body=LiveEvidenceBoard(compute_membership_hash(_batch()), {"RENDERED": 1, "NONMEMBER": 1}, 2),
    )
    base.update(kw)
    return Receipt(**base)


def _board_for(batch, **kw):
    kw.setdefault("refs", Refs(entity_dispositions=batch.receipt_id, source_health="sh-1"))
    kw["body"] = LiveEvidenceBoard(compute_membership_hash(batch), _counts(batch),
                                   len(batch.body.rows))
    return _board(**kw)


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
        projection=Projection.INTERNAL, clocks=_clocks(), input_hashes=[IH],
        integrity=Integrity(), body=DecisionStageBatch(_dec_rows() if rows is None else rows),
    )
    base.update(kw)
    return Receipt(**base)


def _row(team, leaf, reason):
    return EntityDisposition(team, _team_ident(team), leaf, reason, 1)


# --- harness ----------------------------------------------------------------

def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    def valid(receipt, label):
        seal_hashes(receipt)
        r = validate_receipt(receipt)
        (checks if r.ok else failures).append(label if r.ok else f"{label}  -> {r.errors}")

    def invalid(receipt, substr, label):
        r = validate_receipt(receipt)
        good = (not r.ok) and any(substr in e for e in r.errors)
        (checks if good else failures).append(label if good else f"{label}  -> {r.errors}")

    # --- enums + grain binding + valid receipts ------------------------------
    ok({g.value for g in IdentityGrain} == {"event", "team", "team_side", "market_obs",
        "selection", "grading"}, "identity grain = six grains incl. 'team'")
    valid(_batch(), "valid entity_disposition (team grain) receipt passes")
    valid(_board(), "valid board live_evidence receipt passes")
    valid(_decision(), "valid decision-stage (team_side grain) receipt passes")
    invalid(_batch(rows=[EntityDisposition("PIT", _side_ident("HOME"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1)]), "does not match the universe's bound grain",
            "board row with team_side identity rejected (R14b)")
    invalid(_decision(rows=[DecisionStageRow("x", _team_ident("PIT"), StageOutcome.GRADED,
            "GRADED", 1)]), "does not match the universe's bound grain",
            "decision row with team identity rejected (R14b)")

    # --- (3) governed TEAM identity profiles (bare name != PROVIDER_ID) ------
    ok(validate_receipt(seal_hashes(_batch(rows=[_row("PIT", Leaf.NONMEMBER, "BELOW_THRESHOLD")],
       ))).ok, "DECLARED_COMPOSITE team identity (profile+version+proof) passes")
    valid(_batch(rows=[EntityDisposition("PIT", _provider_team_ident("PIT"), Leaf.NONMEMBER,
          "BELOW_THRESHOLD", 1)]), "valid PROVIDER_ID team identity (namespace+id) passes")
    invalid(_batch(rows=[EntityDisposition("PIT", Identity(IdentityGrain.TEAM,
            {"sport": "nfl", "season": 2026}, {}, IdentityQuality.PROVIDER_ID, False,
            "Pittsburgh Steelers"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)]),
            "PROVIDER_ID requires ext.provider_namespace",
            "a bare team name labeled PROVIDER_ID is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", Identity(IdentityGrain.TEAM,
            {"sport": "nfl", "season": 2026}, {"team": "PIT"}, IdentityQuality.DECLARED_COMPOSITE,
            True, "(nfl,2026,PIT)"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)]),
            "requires profile + profile_version + collision_proof",
            "DECLARED_COMPOSITE without profile/version/proof is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", Identity(IdentityGrain.TEAM,
            {"sport": "nfl", "season": 2026}, {"team": "PIT"}, IdentityQuality.DECLARED_COMPOSITE,
            False, "(nfl,2026,PIT)", "p", "v1", "proof"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)]),
            "collision_tested=true", "DECLARED_COMPOSITE without collision_tested is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", Identity(IdentityGrain.TEAM,
            {"sport": "nfl", "season": 2026}, {}, IdentityQuality.ALIAS_RESOLVED, False,
            "PIT"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)]),
            "ALIAS_RESOLVED requires ext.alias_ref", "ALIAS_RESOLVED without registry ref is rejected")

    # --- (1) membership_hash = ordered admitted-member identities only -------
    from services.decision_receipts import compute_membership_hash as _mh
    b_rendered = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED"), _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    b_suppressed = _batch(rows=[_row("A", Leaf.SUPPRESSED, "QUALIFIED"), _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    ok(_mh(b_rendered) == _mh(b_suppressed),
       "RENDERED<->SUPPRESSED does NOT change membership_hash (presentation, not membership)")
    b_AB = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED"), _row("B", Leaf.RENDERED, "QUALIFIED")])
    b_BA = _batch(rows=[_row("B", Leaf.RENDERED, "QUALIFIED"), _row("A", Leaf.RENDERED, "QUALIFIED")])
    ok(_mh(b_AB) != _mh(b_BA), "member ORDER changes membership_hash")
    b_A = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED")])
    b_C = _batch(rows=[_row("C", Leaf.RENDERED, "QUALIFIED")])
    ok(_mh(b_A) != _mh(b_AB), "ADDING a member changes membership_hash")
    ok(_mh(b_AB) != _mh(b_A), "REMOVING a member changes membership_hash")
    ok(_mh(b_A) != _mh(b_C), "REPLACING a member changes membership_hash")
    # Non-member reorder must not change it.
    b_n1 = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED"), _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD"),
                        _row("C", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    b_n2 = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED"), _row("C", Leaf.NONMEMBER, "BELOW_THRESHOLD"),
                        _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    ok(_mh(b_n1) == _mh(b_n2), "NON-member reorder does NOT change membership_hash")

    # (2) membership identity is the GOVERNED profile, never a display label.
    gov = _team_ident("A")  # key "(nfl,2026,A)"
    disp = Identity(IdentityGrain.TEAM, {"sport": "nfl", "season": 2026}, {"team": "A"},
                    IdentityQuality.DECLARED_COMPOSITE, True, "A DIFFERENT DISPLAY LABEL",
                    "team:sport+season", "v1", "unique-in-sport-season")
    b_gov = _batch(rows=[EntityDisposition("A", gov, Leaf.RENDERED, "QUALIFIED", 1)])
    b_disp = _batch(rows=[EntityDisposition("A", disp, Leaf.RENDERED, "QUALIFIED", 1)])
    ok(_mh(b_gov) == _mh(b_disp),
       "membership_hash ignores the display key (governed identity only)")
    b_realdiff = _batch(rows=[EntityDisposition("A", _team_ident("Z"), Leaf.RENDERED, "QUALIFIED", 1)])
    ok(_mh(b_gov) != _mh(b_realdiff),
       "membership_hash changes when the GOVERNED component (team) changes")

    # (2b) ALIAS_RESOLVED must carry a governed RESOLVED canonical identity.
    def _alias(team="PIT", resolved_id="PIT", key=None, resolved="ok"):
        ext = {"team": team, "alias_ref": "alias-registry/nfl-teams", "alias_version": "2026.1"}
        if resolved == "ok":
            ext["resolved"] = {"provider_namespace": "nflverse", "provider_entity_id": resolved_id}
        elif resolved == "blank":
            ext["resolved"] = {"provider_namespace": "", "provider_entity_id": ""}
        elif resolved == "null":
            ext["resolved"] = None
        # resolved == "missing" -> key absent entirely
        return Identity(IdentityGrain.TEAM, {"sport": "nfl", "season": 2026}, ext,
                        IdentityQuality.ALIAS_RESOLVED, False, key or f"alias:{team}")

    valid(_batch(rows=[EntityDisposition("PIT", _alias(), Leaf.RENDERED, "QUALIFIED", 1)]),
          "ALIAS_RESOLVED with a governed resolved identity passes")
    invalid(_batch(rows=[EntityDisposition("PIT", _alias(resolved="missing"), Leaf.RENDERED, "QUALIFIED", 1)]),
            "nonempty governed ext.resolved", "ALIAS_RESOLVED with missing resolved is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", _alias(resolved="null"), Leaf.RENDERED, "QUALIFIED", 1)]),
            "nonempty governed ext.resolved", "ALIAS_RESOLVED with null resolved is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", _alias(resolved="blank"), Leaf.RENDERED, "QUALIFIED", 1)]),
            "nonempty governed ext.resolved", "ALIAS_RESOLVED with blank resolved is rejected")
    b_al1 = _batch(rows=[EntityDisposition("PIT", _alias(key="display-ONE"), Leaf.RENDERED, "QUALIFIED", 1)])
    b_al2 = _batch(rows=[EntityDisposition("PIT", _alias(key="display-TWO"), Leaf.RENDERED, "QUALIFIED", 1)])
    ok(_mh(b_al1) == _mh(b_al2),
       "ALIAS_RESOLVED: changing only the display key does NOT change membership_hash")
    b_al3 = _batch(rows=[EntityDisposition("PIT", _alias(resolved_id="CLE"), Leaf.RENDERED, "QUALIFIED", 1)])
    ok(_mh(b_al1) != _mh(b_al3),
       "ALIAS_RESOLVED: changing the RESOLVED canonical identity DOES change membership_hash")

    # reconcile still binds membership end-to-end.
    b_a = _batch(rows=[_row("A", Leaf.RENDERED, "QUALIFIED"), _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    b_b = _batch(rows=[_row("B", Leaf.RENDERED, "QUALIFIED"), _row("P", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    ok(reconcile_board(seal_hashes(_board_for(b_a)), seal_hashes(b_a)).ok,
       "reconcile ok when membership_hash matches the batch's ordered members")
    ok(not reconcile_board(seal_hashes(_board_for(b_a)), seal_hashes(b_b)).ok,
       "reconcile: same counts, different member -> membership mismatch rejected")

    # --- (2) reconcile validates inputs + full build context -----------------
    dup = _batch(rows=[_row("X", Leaf.RENDERED, "QUALIFIED"), _row("X", Leaf.NONMEMBER, "BELOW_THRESHOLD")])
    rr = reconcile_board(seal_hashes(_board_for(dup)), seal_hashes(dup))
    ok((not rr.ok) and any("structural validation" in e for e in rr.errors),
       "reconcile REJECTS a structurally invalid (duplicate) batch (never clean)")
    ok(not reconcile_board(seal_hashes(_board_for(_batch())),
       seal_hashes(_batch(surface_id="other"))).ok, "reconcile: surface mismatch rejected")
    ok(not reconcile_board(seal_hashes(_board_for(_batch())),
       seal_hashes(_batch(versions=_versions(build_id="build-2")))).ok,
       "reconcile: build_id mismatch rejected")
    ok(not reconcile_board(seal_hashes(_board_for(_batch())),
       seal_hashes(_batch(versions=_versions(config="cfg-2")))).ok,
       "reconcile: config_version mismatch rejected")
    ok(not reconcile_board(seal_hashes(_board_for(_batch())),
       seal_hashes(_batch(versions=_versions(rules={"ats_streak": 2})))).ok,
       "reconcile: rule_versions mismatch rejected")
    ok(not reconcile_board(seal_hashes(_board_for(_batch())),
       seal_hashes(_batch(universe=Universe("team", "other_universe", "v1")))).ok,
       "reconcile: universe mismatch rejected")

    # --- (4) governed numbers reject Python floats ---------------------------
    ok(canonical_number(Decimal("0.5"), "probability") == "0.5000"
       and canonical_number("0.5", "probability") == "0.5000"
       and canonical_number(3, "count") == "3", "Decimal / int / decimal-string accepted")
    for bad in (3.0, 0.5, -3.5):
        try:
            canonical_number(bad, "line")
            ok(False, f"float {bad} should be rejected")
        except NumericProfileError:
            ok(True, f"float {bad} rejected by canonical_number (precision may be pre-lost)")
    invalid(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"x": GovernedNumber(3.0, "line")})]),
            "float is not accepted", "a GovernedNumber wrapping a float is rejected")
    invalid(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"), Leaf.NONMEMBER,
            "BELOW_THRESHOLD", 1, {"raw": 0.5})]), "bare float",
            "a bare float param is rejected")
    for bad, prof in (("3.3", "line"), ("0.12345", "probability"), ("50", "price"), ("-1", "count")):
        try:
            canonical_number(bad, prof)
            ok(False, f"out-of-profile {bad}/{prof} should raise")
        except NumericProfileError:
            ok(True, f"out-of-profile {bad}/{prof} raises (exact decimal, no silent rounding)")
    ok(canonical_number("-110", "price") == "-110" and canonical_number("150", "price") == "+150"
       and canonical_number("3.50", "line") == "3.50" and canonical_number("1", "probability") == "1.0000",
       "canonical decimal strings per profile")

    # --- reason-code registry + firewall -------------------------------------
    invalid(_batch(rows=[_row("x", Leaf.NONMEMBER, "SORTED_BY_streak_desc")]), "invalid code shape",
            "a reason_code with invalid shape (lowercase) is rejected")
    invalid(_batch(rows=[_row("x", Leaf.NONMEMBER, "SORTED_BY_STREAK_DESC")]),
            "not in the allowlisted registry", "a well-shaped but UNREGISTERED code is rejected (R8)")
    invalid(_batch(rows=[_row("x", Leaf.NONMEMBER, "GRADED")]),
            "stage_outcome code used where a leaf is required",
            "a stage_outcome reason on a board leaf row is rejected")
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), StageOutcome.GRADED, "GRADED", 1)]),
            "stage outcome used as a terminal leaf", "stage outcome used as a leaf is rejected")
    invalid(_decision(rows=[DecisionStageRow("x", _side_ident("HOME"), Leaf.RENDERED, "QUALIFIED", 1)]),
            "presentation leaf used as a decision-stage outcome",
            "presentation leaf used as a stage outcome is rejected")
    invalid(_batch(rows=[EntityDisposition("x", _team_ident("x"), "ELIGIBLE", "QUALIFIED", 1)]),
            "roll-up", "a roll-up (ELIGIBLE) used as a leaf is rejected (R5)")

    # --- (2) tamper-evidence metadata only -----------------------------------
    signed = seal_hashes(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED, proof="sig")))
    ok(validate_receipt(signed).ok and has_tamper_evidence_metadata(signed.integrity),
       "has_tamper_evidence_metadata: structurally complete")
    ok(not has_tamper_evidence_metadata(_batch().integrity) and not hasattr(dr, "is_tamper_evident"),
       "no verified tamper claim (metadata-only; is_tamper_evident removed)")

    # --- exact-Z UTC ---------------------------------------------------------
    for bad in ("yesterday", "UNKNOWN", "2026-10-25T12:00:00", "2026-10-25T12:00:00+05:00",
                "2026-10-25T12:00:00+00:00", "2026-10-25T12:00:00.000Z"):
        invalid(_batch(clocks=Clocks(bk_captured=bad,
                source_updated_status=SourceUpdatedStatus.NOT_PROVIDED, source_updated=None,
                event_effective=KICK)), "bk_captured must be a tz-aware UTC",
                f"clock {bad!r} rejected (exact Z only)")

    # --- hardening -----------------------------------------------------------
    invalid(_batch(schema_version=SchemaVersion(1, True)), "no booleans",
            "boolean schema_version.minor is rejected")
    invalid(_batch(receipt_id="disp-1"), "opaque UUID", "a non-UUID receipt_id is rejected")
    invalid(_batch(created_seq=0), "positive", "created_seq <= 0 is rejected")
    invalid(_board(body=LiveEvidenceBoard(HEXH, {"RENDERED": 1, "NONMEMBER": 1}, -1)),
            "non-negative, non-boolean", "negative expected_count is rejected")
    invalid(_board(body=LiveEvidenceBoard(HEXH, {"RENDERED": 1, "NONMEMBER": 1}, True)),
            "non-negative, non-boolean", "boolean expected_count is rejected")
    invalid(_board(body=LiveEvidenceBoard("not-hex", {"RENDERED": 1, "NONMEMBER": 1}, 2)),
            "membership_hash must be a 64-char", "non-hex membership_hash is rejected")
    invalid(_batch(input_hashes=["h-in-1"]), "input_hashes must be a list of 64-char",
            "non-hex input_hashes entry is rejected")
    phash = seal_hashes(_batch()); phash.integrity.content_hash = "z" * 64
    ok(not validate_receipt(phash).ok, "a non-hex declared content_hash is rejected")
    invalid(_board(body=LiveEvidenceBoard(HEXH, {"RENDERED": 1, "NONMEMBER": 1}, 5)),
            "conservation", "board per-leaf counts not summing to expected_count are rejected")
    invalid(_board(refs=Refs(entity_dispositions=None, source_health="sh-1")),
            "entity_dispositions batch", "board missing its entity_dispositions ref is rejected")
    invalid(_batch(rows=[_row("PIT", Leaf.NONMEMBER, "BELOW_THRESHOLD"),
            _row("PIT", Leaf.RENDERED, "QUALIFIED")]), "duplicate entity_ref",
            "duplicate entity_ref is rejected (R4)")
    invalid(_batch(universe=Universe("team", "", "v1")), "universe.id required",
            "empty universe.id is rejected")
    invalid(_batch(replay_class=ReplayClass.NON_REPLAYABLE, input_hashes=None,
            authority_class=AuthorityClass.FACT), "MUST NOT be NON_REPLAYABLE",
            "factual authority may not be NON_REPLAYABLE")

    # --- conclusion subtree + two digests ------------------------------------
    c0 = compute_conclusion_hash(_batch())
    k0 = compute_content_hash(_batch())
    ok(compute_conclusion_hash(_batch(rows=[_row("PIT", Leaf.NONMEMBER, "COVER_SHORT"),
       _row("NO", Leaf.RENDERED, "QUALIFIED")])) != c0, "conclusion changes on reason_code")
    ok(compute_conclusion_hash(_batch(universe=Universe("team", "nfl_ats_board_2026", "v2"))) != c0,
       "conclusion changes on universe.version")
    ok(compute_conclusion_hash(_batch(rows=list(reversed(_disp_rows())))) != c0,
       "conclusion changes on membership ORDER")
    ok(compute_conclusion_hash(_batch(created_seq=999)) == c0
       and compute_conclusion_hash(_batch(created_at="2020-01-01T00:00:00Z")) == c0
       and compute_conclusion_hash(_batch(receipt_id=BOARD_ID)) == c0,
       "conclusion stable under receipt-instance metadata")
    ok(compute_content_hash(_batch(created_seq=999)) != k0, "content changes on created_seq")
    r1 = seal_hashes(_batch(receipt_id=DISP_ID, created_seq=10))
    r2 = seal_hashes(_batch(receipt_id=BOARD_ID, created_seq=11))
    ok(r1.conclusion_hash == r2.conclusion_hash
       and r1.integrity.content_hash != r2.integrity.content_hash,
       "two rebuilds share conclusion_hash but differ in content_hash")
    ok(seal_hashes(_batch()).conclusion_hash != seal_hashes(_batch()).integrity.content_hash,
       "conclusion_hash and content_hash are separate digests")

    # --- integrity + non-throwing + purity -----------------------------------
    invalid(_batch(integrity=Integrity(hash_algorithm="md5")), "hash_algorithm not allowlisted",
            "a non-allowlisted hash_algorithm is rejected")
    invalid(_batch(integrity=Integrity(mechanism=IntegrityMechanism.SIGNED)),
            "requires proof material", "mechanism=signed without proof is rejected")
    tampered = seal_hashes(_batch()); tampered.integrity.content_hash = "0" * 64
    ok(not validate_receipt(tampered).ok, "a declared content_hash mismatch is rejected")
    # (3) content_hash is REQUIRED — conclusion_hash alone must not pass.
    conc_only = _batch(); conc_only.conclusion_hash = compute_conclusion_hash(conc_only)
    invalid(conc_only, "integrity.content_hash is required",
            "a receipt with conclusion_hash but no content_hash is rejected")
    cont_only = _batch(); cont_only.integrity.content_hash = compute_content_hash(cont_only)
    invalid(cont_only, "conclusion_hash is required",
            "a receipt with content_hash but no conclusion_hash is rejected")
    try:
        r = validate_receipt(_batch(rows=[EntityDisposition("PIT", _team_ident("PIT"),
            Leaf.NONMEMBER, "BELOW_THRESHOLD", 1, {"raw": 0.5})]))
        ok(not r.ok, "validate_receipt is NON-THROWING on a bare-float field")
    except Exception as exc:
        ok(False, f"validate_receipt raised: {exc!r}")
    before = set(os.listdir("."))
    x = _board(); h1, h2 = compute_content_hash(x), compute_content_hash(x)
    ok(set(os.listdir(".")) == before, "building + hashing creates no file in cwd")
    ok(h1 == h2, "content_hash is deterministic")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 74)
    print("DECISION INTEGRITY CONTRACT LIBRARY QC (Phase 2B, Slice 1, Rev 4)")
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
