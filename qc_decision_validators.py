"""QC: Decision Integrity validator suite over frozen NFL ATS fixtures
(Phase 2B, Slice 2).

Pure/deterministic: imports only the contract library, the validator suite, the
frozen fixtures, and stdlib (+ a cwd listdir snapshot). No filesystem/env/network/
Flask/pandas/production reads; nothing is wired to a surface, CI, or runtime.

Each of the ten validator areas is exercised with a VALID fixture (must pass) and at
least one deliberately-INVALID variant (must fail with a specific error).
"""
from __future__ import annotations

import os

from services.decision_receipts import (
    ChangeKind, CorrectionBody, EntityDisposition, Identity, IdentityGrain, IdentityQuality,
    Leaf, LiveEvidenceBoard, RenderBody, StageOutcome, compute_content_hash, compute_conclusion_hash,
)
import services.nfl_ats_fixtures as fx
import services.decision_validators as V
from services.decision_validators import ReasonCodeDef
from services.decision_receipts import SemanticCategory


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    def good(res, label):
        (checks if res.ok else failures).append(label if res.ok else f"{label}  -> {res.errors}")

    def bad(res, substr, label):
        hit = (not res.ok) and any(substr in e for e in res.errors)
        (checks if hit else failures).append(label if hit else f"{label}  -> {res.errors}")

    # Canonical valid scenario.
    batch = fx.dispositions_batch()
    brd = fx.board(batch)
    sh = fx.source_health()
    rnd = fx.render(brd)
    dec = fx.decision_stage()
    corr = fx.correction(batch)
    us = fx.user_safe(brd)

    # === 1. envelope validity ===
    for r, name in ((batch, "batch"), (brd, "board"), (sh, "source_health"),
                    (rnd, "render"), (dec, "decision"), (corr, "correction"), (us, "user_safe")):
        good(V.validate_envelope(r), f"envelope valid: {name}")
    bad_env = fx.dispositions_batch(); bad_env.created_at = "nope"; fx.reseal(bad_env)
    bad(V.validate_envelope(bad_env), "created_at", "envelope invalid: bad created_at rejected")

    # === 2. stage/leaf separation ===
    good(V.validate_stage_leaf_separation(batch), "stage/leaf valid: board batch")
    good(V.validate_stage_leaf_separation(dec), "stage/leaf valid: decision batch")
    slx = fx.dispositions_batch(rows=[EntityDisposition("PHI", fx.team_identity("PHI"),
          StageOutcome.GRADED, "GRADED", 1)])
    bad(V.validate_stage_leaf_separation(slx), "stage outcome used as a terminal leaf",
        "stage/leaf invalid: stage outcome as leaf rejected")

    # === 3. nested conservation ===
    good(V.validate_nested_conservation(batch, brd), "nested conservation valid (Members<=Eligible<=Expected)")
    ru = V.rollups(batch.body)
    ok(ru["MEMBERS"] == 3 and ru["ELIGIBLE"] == 5 and ru["EXPECTED"] == 5,
       "nested roll-ups computed correctly (3/5/5)")
    nc_bad = fx.board(batch); nc_bad.body.expected_count = 4; fx.reseal(nc_bad)
    bad(V.validate_nested_conservation(batch, nc_bad), "expected_count",
        "nested conservation invalid: wrong expected_count rejected")
    dup_ci = fx.dispositions_batch(rows=[
        EntityDisposition("PHI", fx.team_identity("PHI"), Leaf.NONMEMBER, "BELOW_THRESHOLD", 1,
                          {"threshold": fx.GovernedNumber(3, "count")}),
        EntityDisposition("PHI-ALT", fx.team_identity("PHI"), Leaf.RENDERED, "QUALIFIED", 1)])
    bad(V.validate_nested_conservation(dup_ci), "duplicate canonical identity",
        "nested conservation invalid: same governed identity under two entity_refs rejected")

    # === 4. reason-code governance ===
    good(V.validate_reason_registry(), "reason registry is internally consistent")
    good(V.validate_reason_usage(batch), "reason usage valid: board batch")
    good(V.validate_reason_usage(dec), "reason usage valid: decision batch")
    bad_reg = {"SORTED_BY_STREAK_DESC": ReasonCodeDef("SORTED_BY_STREAK_DESC",
               SemanticCategory.LEAF, 1, "o", "d", maps_to=None)}
    bad(V.validate_reason_registry(bad_reg), "requires maps_to",
        "reason registry invalid: leaf code without maps_to rejected")
    unreg = fx.dispositions_batch(rows=[EntityDisposition("PHI", fx.team_identity("PHI"),
            Leaf.NONMEMBER, "MADE_UP_CODE", 1)])
    bad(V.validate_reason_usage(unreg), "not registered",
        "reason usage invalid: unregistered code rejected")
    miscat = fx.dispositions_batch(rows=[EntityDisposition("PHI", fx.team_identity("PHI"),
             Leaf.NONMEMBER, "GRADED", 1)])
    bad(V.validate_reason_usage(miscat), "expected leaf",
        "reason usage invalid: stage_outcome code on a leaf row rejected")
    maps_mismatch = fx.dispositions_batch(rows=[EntityDisposition("PHI", fx.team_identity("PHI"),
        Leaf.RENDERED, "BELOW_THRESHOLD", 1, {"threshold": fx.GovernedNumber(3, "count")})])
    bad(V.validate_reason_usage(maps_mismatch), "mapping mismatch",
        "reason usage invalid: maps_to (NONMEMBER) != actual leaf (RENDERED) rejected")
    wrong_ver = fx.dispositions_batch(rows=[EntityDisposition("NYG", fx.team_identity("NYG"),
        Leaf.NONMEMBER, "BELOW_THRESHOLD", 2, {"threshold": fx.GovernedNumber(3, "count")})])
    bad(V.validate_reason_usage(wrong_ver), "reason_def_version",
        "reason usage invalid: wrong reason_def_version rejected")
    missing_param = fx.dispositions_batch(rows=[EntityDisposition("NYG", fx.team_identity("NYG"),
        Leaf.NONMEMBER, "BELOW_THRESHOLD", 1)])  # BELOW_THRESHOLD requires 'threshold'
    bad(V.validate_reason_usage(missing_param), "requires param_fields",
        "reason usage invalid: missing required reason param rejected")

    # === 5. canonical replay ===
    good(V.validate_canonical_replay(brd), "canonical replay valid: sealed board reproduces")
    rp_bad = fx.board(batch); rp_bad.conclusion_hash = "0" * 64
    bad(V.validate_canonical_replay(rp_bad), "conclusion_hash does not reproduce",
        "canonical replay invalid: wrong conclusion_hash rejected")
    brd2 = fx.board(fx.dispositions_batch())  # identical rebuild
    ok(V.replay_equal(brd, brd2), "replay_equal: two identical rebuilds are replay-equal")
    moved = fx.dispositions_batch(rows=list(reversed(fx._default_rows())))
    ok(not V.replay_equal(brd, fx.board(moved)),
       "replay_equal: reordered members are NOT replay-equal")

    # === 6. identity / collision ===
    good(V.validate_identity_collision(batch), "identity/collision valid: board batch")
    name_only = fx.dispositions_batch(rows=[EntityDisposition("PHI", Identity(IdentityGrain.TEAM,
                {"sport": "nfl", "season": 2026}, {}, IdentityQuality.NAME_ONLY, False, "PHI"),
                Leaf.RENDERED, "QUALIFIED", 1)])
    bad(V.validate_identity_collision(name_only), "authoritative identity",
        "identity/collision invalid: NAME_ONLY admitted as a member rejected (R12/R13)")

    # === 7. correction lineage ===
    good(V.validate_correction_lineage([batch, corr]), "correction lineage valid")
    # supersedes_seq < created_seq (passes the envelope) but != the superseded
    # created_seq (100) -> the lineage R15b equality check fires.
    corr_seq = fx.correction(batch, supersedes_seq=50)
    bad(V.validate_correction_lineage([batch, corr_seq]), "R15b",
        "correction lineage invalid: supersedes_seq != superseded created_seq rejected (R15b)")
    # created_seq not after the superseded receipt: enforced by the envelope ordering
    # rule (supersedes_seq must be < created_seq), so the gate fails closed.
    corr_order = fx.correction(batch, created_seq=50)
    bad(V.validate_correction_lineage([batch, corr_order]), "must be < this created_seq",
        "correction lineage invalid: created_seq not after superseded rejected (envelope ordering)")
    corr_missing = fx.correction(batch, supersedes="ffffffff-ffff-4fff-8fff-ffffffffffff")
    bad(V.validate_correction_lineage([batch, corr_missing]), "unknown receipt_id",
        "correction lineage invalid: supersedes an unknown receipt rejected")
    mal = fx.dispositions_batch(); mal.created_at = "nope"; fx.reseal(mal)
    bad(V.validate_correction_lineage([mal, corr]), "failed structural validation",
        "correction lineage: a malformed participant fails closed")
    dup_id = fx.dispositions_batch(receipt_id=batch.receipt_id)  # same id as batch
    bad(V.validate_correction_lineage([batch, dup_id, corr]), "duplicate receipt_id",
        "correction lineage: duplicate receipt_id rejected")
    dup_seq = fx.decision_stage(created_seq=100)  # same surface + created_seq as batch (100)
    bad(V.validate_correction_lineage([batch, dup_seq, corr]), "duplicate created_seq",
        "correction lineage: duplicate created_seq on a surface rejected")

    # === 8. hierarchical references ===
    good(V.validate_hierarchical_references([batch, brd, sh, rnd]), "hierarchical refs valid")
    rnd_bad = fx.render(brd); rnd_bad.body = RenderBody(brd.receipt_id, "0" * 64,
                                                        brd.body.membership_hash); fx.reseal(rnd_bad)
    bad(V.validate_hierarchical_references([batch, brd, sh, rnd_bad]),
        "render conclusion_hash != evidence", "hierarchical refs invalid: render hash mismatch rejected")
    bad(V.validate_hierarchical_references([batch, brd, rnd]), "source_health ref does not resolve",
        "hierarchical refs invalid: unresolved source_health rejected")
    back = fx.board(batch); back.refs = fx.Refs(entity_dispositions=batch.receipt_id,
            source_health=sh.receipt_id, evidence=rnd.receipt_id); fx.reseal(back)
    bad(V.validate_hierarchical_references([batch, back, sh, rnd]),
        "MUST NOT reference a render", "hierarchical refs invalid: evidence back-ref to render rejected")
    mal_b = fx.board(batch); mal_b.created_at = "nope"; fx.reseal(mal_b)
    bad(V.validate_hierarchical_references([batch, mal_b, sh]), "failed structural validation",
        "hierarchical refs: a malformed participant fails closed")
    dup_hid = fx.source_health(receipt_id=batch.receipt_id)  # id collides with the batch
    bad(V.validate_hierarchical_references([batch, dup_hid, brd, sh, rnd]), "duplicate receipt_id",
        "hierarchical refs: duplicate receipt_id rejected")

    # === 9. count reconciliation ===
    good(V.validate_count_reconciliation(brd, batch), "count reconciliation valid")
    cr_bad = fx.board(batch); cr_bad.body.per_leaf_counts = {"RENDERED": 5}; fx.reseal(cr_bad)
    bad(V.validate_count_reconciliation(cr_bad, batch), "",
        "count reconciliation invalid: wrong counts rejected")

    # === 10. user-safe projection (stripping + SUPPORT) ===
    graph = [batch, sh]
    good(V.validate_user_safe_projection(us, brd, graph), "user-safe projection valid (supported)")
    us_ih = fx.user_safe(brd, input_hashes=["ab" * 32])
    bad(V.validate_user_safe_projection(us_ih, brd, graph), "input_hashes",
        "user-safe invalid: carries input_hashes rejected")
    us_noclaims = fx.user_safe(brd, claims=None)
    bad(V.validate_user_safe_projection(us_noclaims, brd, graph), "claims",
        "user-safe invalid: missing claims rejected")
    us_surface = fx.user_safe(brd, surface_id="other_surface")
    bad(V.validate_user_safe_projection(us_surface, brd, graph), "surface",
        "user-safe invalid: surface mismatch with root rejected")
    us_forge_m = fx.user_safe(brd)
    us_forge_m.body = LiveEvidenceBoard("0" * 64, dict(us_forge_m.body.per_leaf_counts),
                                        us_forge_m.body.expected_count); fx.reseal(us_forge_m)
    bad(V.validate_user_safe_projection(us_forge_m, brd, graph), "membership_hash is not supported",
        "user-safe invalid: forged membership_hash rejected")
    us_forge_c = fx.user_safe(brd)
    us_forge_c.body = LiveEvidenceBoard(brd.body.membership_hash,
                                        {"RENDERED": 3, "SUPPRESSED": 1, "NONMEMBER": 2}, 6)
    fx.reseal(us_forge_c)
    bad(V.validate_user_safe_projection(us_forge_c, brd, graph), "counts are not supported",
        "user-safe invalid: forged (inflated) counts rejected")
    us_forge_e = fx.user_safe(brd)
    us_forge_e.body = LiveEvidenceBoard(brd.body.membership_hash,
                                        dict(brd.body.per_leaf_counts), 99); fx.reseal(us_forge_e)
    # expected_count is compared at the support layer AND enforced by the envelope
    # conservation gate (counts must sum to expected_count), which fires first here.
    bad(V.validate_user_safe_projection(us_forge_e, brd, graph), "expected_count",
        "user-safe invalid: forged expected_count rejected (conservation gate)")
    # projection-root binding
    us_noroot = fx.user_safe(brd, projection_root=None)
    bad(V.validate_user_safe_projection(us_noroot, brd, graph), "MUST carry a serialized projection_root",
        "user-safe invalid: missing projection_root rejected")
    us_subst = fx.user_safe(brd, projection_root=fx.ProjectionRoot("deadbeef-0000-4000-8000-000000000000",
               brd.conclusion_hash, "evidence"))
    bad(V.validate_user_safe_projection(us_subst, brd, graph), "substituted root",
        "user-safe invalid: substituted projection_root receipt_id rejected")
    us_wrongh = fx.user_safe(brd, projection_root=fx.ProjectionRoot(brd.receipt_id, "0" * 64, "evidence"))
    bad(V.validate_user_safe_projection(us_wrongh, brd, graph), "root_conclusion_hash",
        "user-safe invalid: wrong projection_root conclusion_hash rejected")
    # invented / unsupported governed claims
    us_badcount = fx.user_safe(brd, claim_records=[fx.Claim("MEMBER_COUNT", {"count": 9}, (brd.receipt_id,))])
    bad(V.validate_user_safe_projection(us_badcount, brd, graph), "MEMBER_COUNT 9 not derivable",
        "user-safe invalid: invented member-count claim rejected")
    us_badsort = fx.user_safe(brd, claim_records=[fx.Claim("SORTED",
                 {"sort_rule_id": "x", "sort_rule_version": "1"}, ())])
    bad(V.validate_user_safe_projection(us_badsort, brd, graph), "SORTED must cite the root",
        "user-safe invalid: sort claim with no supporting root rejected")
    us_unrclaim = fx.user_safe(brd, claim_records=[fx.Claim("MEMBER_COUNT", {"count": 3},
                  ("b0000000-0000-4000-8000-0000000000ff",))])
    bad(V.validate_user_safe_projection(us_unrclaim, brd, graph), "is not reachable from the root",
        "user-safe invalid: claim citing an unreachable support receipt rejected")
    # governed health state (even with zero rendered members)
    sh_fc = fx.source_health(state=fx.HealthState.FAIL_CLOSED)
    bad(V.validate_user_safe_projection(us, brd, [batch, sh_fc]), "forged health claim",
        "user-safe invalid: presents rendered members on a FAIL_CLOSED source rejected")
    us_health_mismatch = fx.user_safe(brd, claim_records=[fx.Claim("HEALTH", {"state": "SYNCHRONIZED"},
                         (fx.SH_ID,))])
    bad(V.validate_user_safe_projection(us_health_mismatch, brd, [batch, sh_fc]),
        "HEALTH state", "user-safe invalid: HEALTH claim not matching governed state rejected")
    other = fx.dispositions_batch(receipt_id="b0000000-0000-4000-8000-0000000000ff")
    us_unreach = fx.user_safe(brd)
    us_unreach.refs = fx.Refs(entity_dispositions=other.receipt_id, source_health=fx.SH_ID)
    fx.reseal(us_unreach)
    bad(V.validate_user_safe_projection(us_unreach, brd, [batch, sh, other]),
        "not reachable from its root",
        "user-safe invalid: references an existing-but-unreachable receipt rejected")

    # === source-health one governed state of record ===
    for st in (fx.HealthState.SYNCHRONIZED, fx.HealthState.STALE, fx.HealthState.FAIL_CLOSED):
        good(V.validate_envelope(fx.source_health(state=st)), f"source_health state {st.value} is valid")
    contradiction = fx.source_health()
    contradiction.body = fx.SourceHealthBody(fx.HealthState.SYNCHRONIZED, fx.BK_AT,
                                             {"state": "FAIL_CLOSED"}); fx.reseal(contradiction)
    bad(V.validate_envelope(contradiction), "second authoritative 'state'",
        "source_health invalid: contradictory second state in detail rejected")

    # === purity ===
    before = set(os.listdir("."))
    _ = fx.board(); _ = V.validate_envelope(brd)
    ok(set(os.listdir(".")) == before, "running the suite creates no file in cwd")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 74)
    print("DECISION INTEGRITY VALIDATOR SUITE QC (Phase 2B, Slice 2)")
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
