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
    corr_seq = fx.correction(batch, supersedes_seq=999)
    bad(V.validate_correction_lineage([batch, corr_seq]), "R15b",
        "correction lineage invalid: supersedes_seq != superseded created_seq rejected")
    corr_order = fx.correction(batch, created_seq=50)
    bad(V.validate_correction_lineage([batch, corr_order]), "R16",
        "correction lineage invalid: created_seq not after superseded rejected")
    corr_missing = fx.correction(batch, supersedes="ffffffff-ffff-4fff-8fff-ffffffffffff")
    bad(V.validate_correction_lineage([batch, corr_missing]), "unknown receipt_id",
        "correction lineage invalid: supersedes an unknown receipt rejected")

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

    # === 9. count reconciliation ===
    good(V.validate_count_reconciliation(brd, batch), "count reconciliation valid")
    cr_bad = fx.board(batch); cr_bad.body.per_leaf_counts = {"RENDERED": 5}; fx.reseal(cr_bad)
    bad(V.validate_count_reconciliation(cr_bad, batch), "",
        "count reconciliation invalid: wrong counts rejected")

    # === 10. user-safe projection ===
    good(V.validate_user_safe_projection(us, brd), "user-safe projection valid")
    us_ih = fx.user_safe(brd, input_hashes=["ab" * 32]);
    bad(V.validate_user_safe_projection(us_ih, brd), "input_hashes",
        "user-safe invalid: carries input_hashes rejected")
    us_noclaims = fx.user_safe(brd, claims=None)
    bad(V.validate_user_safe_projection(us_noclaims, brd), "claims",
        "user-safe invalid: missing claims rejected")
    us_surface = fx.user_safe(brd, surface_id="other_surface")
    bad(V.validate_user_safe_projection(us_surface, brd), "surface",
        "user-safe invalid: surface mismatch with root rejected")

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
