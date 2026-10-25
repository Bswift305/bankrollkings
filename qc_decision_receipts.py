"""QC: Decision Integrity shared contract library (Phase 2B, Slice 1).

Focused structural + canonicalization + hashing QC for `services/decision_receipts.py`.
Pure: imports only the contract library + stdlib. Touches no app/route/data/network.

Covers the Slice-1 acceptance tests:
  - unknown major fails closed; a newer minor within a known major is permitted;
  - validator rejects a stage outcome used as a terminal leaf AND a presentation
    leaf used as a decision-stage outcome (both directions);
  - content_hash changes when a stored field changes; conclusion_hash is stable
    under receipt-instance metadata and changes when a conclusion row changes;
  - canonicalization: ordering, Unicode (NFC vs NFD), null semantics, numeric
    profiles (int vs float), self-hash exclusion;
  - declared integrity metadata validated (mismatch rejected); tamper_evident
    requires proof (shape only); user_safe must not carry proof;
  - identity fail-closed (GRADED/RENDERED under AMBIGUOUS rejected; DECLARED_COMPOSITE
    requires profile + version); supersession ordering;
  - building + hashing writes no file to cwd; hashing is deterministic.
"""
from __future__ import annotations

import os

from services.decision_receipts import (
    AuthorityClass, BoardDisposition, BoardReceipt, Clocks, DecisionOutcome,
    DecisionStageReceipt, Identity, IdentityQuality, Integrity, Projection,
    ReplayClass, SchemaVersion, SourceUpdatedStatus, StageOutcome,
    TerminalDisposition, Universe, compute_conclusion_hash, compute_content_hash,
    seal_hashes, validate_receipt,
)


# --- builders ---------------------------------------------------------------

def _clocks(source_updated=None, status=SourceUpdatedStatus.NOT_PROVIDED):
    return Clocks(bk_captured="2026-10-25T12:51:21Z", source_updated_status=status,
                  source_updated=source_updated, event_effective="2026-10-25T13:30:00Z")


def _ident(quality=IdentityQuality.DECLARED_COMPOSITE, key="(401001, HOME)"):
    return Identity(quality=quality, key=key, profile="game_id+team_side",
                    profile_version="v1", collision_proof="declared")


def _decision(outcomes=None, **kw):
    base = dict(
        receipt_id="dec-1", schema_version=SchemaVersion(1, 0),
        surface_id="nfl_ats_wave",
        universe=Universe("team_side_decision", "nfl_ats_decisions_2026", "v1"),
        authority_class=AuthorityClass.FACT, replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        projection=Projection.INTERNAL, clocks=_clocks(), identity=_ident(),
        created_seq=10, integrity=Integrity(),
    )
    base.update(kw)
    r = DecisionStageReceipt(**base)
    r.outcomes = outcomes if outcomes is not None else [
        DecisionOutcome("(401001, HOME)", StageOutcome.GRADED, "GRADED"),
        DecisionOutcome("(401001, AWAY)", StageOutcome.NO_LINE, "NO_LINE"),
    ]
    return r


def _board(dispositions=None, **kw):
    base = dict(
        receipt_id="board-1", schema_version=SchemaVersion(1, 0),
        surface_id="nfl_ats_wave",
        universe=Universe("team", "nfl_ats_board_2026", "v1"),
        authority_class=AuthorityClass.FACT, replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        projection=Projection.INTERNAL, clocks=_clocks(),
        identity=Identity(IdentityQuality.PROVIDER_ID, "Pittsburgh Steelers"),
        created_seq=11, integrity=Integrity(), decision_stage_ref="dec-1",
    )
    base.update(kw)
    r = BoardReceipt(**base)
    r.dispositions = dispositions if dispositions is not None else [
        BoardDisposition("Pittsburgh Steelers", TerminalDisposition.NONMEMBER, "BELOW_THRESHOLD"),
        BoardDisposition("New Orleans Saints", TerminalDisposition.RENDERED, "SORTED"),
    ]
    return r


# --- checks -----------------------------------------------------------------

def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # 1) happy path: both receipts valid; sealing then validating stays valid.
    d, b = _decision(), _board()
    ok(validate_receipt(d).ok, "valid decision-stage receipt passes")
    ok(validate_receipt(b).ok, "valid board receipt passes")
    seal_hashes(d); seal_hashes(b)
    ok(validate_receipt(d).ok, "sealed decision receipt still valid (declared hashes match)")
    ok(validate_receipt(b).ok, "sealed board receipt still valid (declared hashes match)")

    # 2) version: unknown major fails closed; newer minor within known major OK.
    ok(not validate_receipt(_decision(schema_version=SchemaVersion(2, 0))).ok,
       "unknown major (2.0) fails closed")
    ok(not validate_receipt(_decision(schema_version=SchemaVersion(0, 9))).ok,
       "major 0 fails closed")
    ok(validate_receipt(_decision(schema_version=SchemaVersion(1, 7))).ok,
       "newer minor (1.7) within known major is permitted")

    # 3) stage/terminal firewall — BOTH directions.
    bad_board = _board(dispositions=[
        BoardDisposition("Pittsburgh Steelers", StageOutcome.GRADED, "GRADED")])  # type: ignore[arg-type]
    ok(not validate_receipt(bad_board).ok, "stage outcome used as terminal leaf is rejected")
    bad_dec = _decision(outcomes=[
        DecisionOutcome("(401001, HOME)", TerminalDisposition.RENDERED, "SORTED")])  # type: ignore[arg-type]
    ok(not validate_receipt(bad_dec).ok, "presentation leaf used as decision-stage outcome is rejected")

    # 4) hashing: content vs conclusion. Baselines are UNSEALED so each check
    # isolates the field under test (content_hash includes integrity.conclusion_hash,
    # so a sealed baseline would confound order/metadata comparisons).
    c_content = compute_content_hash(_board())
    c_concl = compute_conclusion_hash(_board())
    # (a) metadata-only change: content changes, conclusion stable.
    meta = _board(clocks=_clocks(source_updated="2026-10-25T10:00:00Z",
                                 status=SourceUpdatedStatus.PROVIDED), created_seq=99)
    ok(compute_content_hash(meta) != c_content, "content_hash changes on a stored-field change")
    ok(compute_conclusion_hash(meta) == c_concl,
       "conclusion_hash is stable under receipt-instance metadata change")
    # (b) conclusion-row change: both change.
    changed = _board(dispositions=[
        BoardDisposition("Pittsburgh Steelers", TerminalDisposition.RENDERED, "SORTED"),
        BoardDisposition("New Orleans Saints", TerminalDisposition.RENDERED, "SORTED")])
    ok(compute_conclusion_hash(changed) != c_concl, "conclusion_hash changes when a disposition changes")
    ok(compute_content_hash(changed) != c_content, "content_hash changes when a disposition changes")

    # 5) canonicalization.
    # ordering: member rows are a set — insertion order must not matter.
    rev = _board(dispositions=list(reversed(_board().dispositions)))
    ok(compute_content_hash(rev) == c_content, "content_hash is independent of member-row order")
    ok(compute_conclusion_hash(rev) == c_concl, "conclusion_hash is independent of member-row order")
    # Unicode: NFC vs NFD of the same name hash equal (normalized to NFC).
    nfc = _board(dispositions=[BoardDisposition("Monté", TerminalDisposition.RENDERED, "SORTED")])
    nfd = _board(dispositions=[BoardDisposition("Monté", TerminalDisposition.RENDERED, "SORTED")])
    ok(compute_conclusion_hash(nfc) == compute_conclusion_hash(nfd),
       "Unicode NFC/NFD normalize to the same canonical hash")
    # null semantics: null source_updated requires NOT_PROVIDED/UNRESOLVED; present requires PROVIDED.
    ok(not validate_receipt(_decision(clocks=_clocks(
        source_updated=None, status=SourceUpdatedStatus.PROVIDED))).ok,
       "null source_updated with PROVIDED status is rejected")
    ok(not validate_receipt(_decision(clocks=_clocks(
        source_updated="2026-10-25T10:00:00Z", status=SourceUpdatedStatus.NOT_PROVIDED))).ok,
       "present source_updated with NOT_PROVIDED status is rejected")
    ok(not validate_receipt(_decision(clocks=_clocks(
        source_updated="UNKNOWN", status=SourceUpdatedStatus.PROVIDED))).ok,
       "literal 'UNKNOWN' clock value is rejected")
    # numeric profile: int vs float are distinct canonical forms (via disclosures probe).
    int_r = _board(disclosures=[1]); float_r = _board(disclosures=[1.0])
    ok(compute_content_hash(int_r) != compute_content_hash(float_r),
       "numeric profile: int 1 and float 1.0 canonicalize differently")
    # self-hash exclusion: mutating the STORED content_hash must not change the recomputed one.
    probe = _board(); seal_hashes(probe); recomputed = compute_content_hash(probe)
    probe.integrity.content_hash = "deadbeef" * 8
    ok(compute_content_hash(probe) == recomputed,
       "self-hash exclusion: stored integrity.content_hash is excluded from content_hash")
    probe.integrity.proof = "tamper-seal-placeholder"
    ok(compute_content_hash(probe) == recomputed,
       "self-hash exclusion: integrity.proof is excluded from content_hash")

    # 6) declared integrity metadata validation.
    tampered = _board(); seal_hashes(tampered)
    tampered.integrity.content_hash = "0" * 64
    ok(not validate_receipt(tampered).ok, "declared content_hash mismatch is rejected")
    te = _board(integrity=Integrity(tamper_evident=True)); seal_hashes(te)
    ok(not validate_receipt(te).ok, "tamper_evident=true without proof is rejected (shape)")
    us = _board(projection=Projection.USER_SAFE, integrity=Integrity(proof="x"))
    ok(not validate_receipt(us).ok, "user_safe projection carrying integrity.proof is rejected")

    # 7) identity fail-closed.
    ok(not validate_receipt(_decision(
        identity=Identity(IdentityQuality.AMBIGUOUS, "?"),
        outcomes=[DecisionOutcome("x", StageOutcome.GRADED, "GRADED")])).ok,
       "GRADED under AMBIGUOUS identity fails closed")
    ok(not validate_receipt(_board(
        identity=Identity(IdentityQuality.UNRESOLVED, "?"),
        dispositions=[BoardDisposition("x", TerminalDisposition.RENDERED, "SORTED")])).ok,
       "RENDERED under UNRESOLVED identity fails closed")
    ok(not validate_receipt(_decision(
        identity=Identity(IdentityQuality.DECLARED_COMPOSITE, "(401001, HOME)"))).ok,
       "DECLARED_COMPOSITE without profile/version is rejected")

    # 8) supersession ordering.
    ok(validate_receipt(_decision(created_seq=10, supersedes_seq=4)).ok,
       "supersedes_seq < created_seq is valid")
    ok(not validate_receipt(_decision(created_seq=10, supersedes_seq=10)).ok,
       "supersedes_seq == created_seq is rejected")

    # 9) purity: build + hash writes no file to cwd; hashing is deterministic.
    before = set(os.listdir("."))
    x = _board(); h1 = compute_content_hash(x); h2 = compute_content_hash(x)
    after = set(os.listdir("."))
    ok(before == after, "building + hashing creates no file in cwd")
    ok(h1 == h2, "content_hash is deterministic across calls")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 68)
    print("DECISION INTEGRITY CONTRACT LIBRARY QC (Phase 2B, Slice 1)")
    print("=" * 68)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"\n{len(r['checks'])} passed, {len(r['failures'])} failed")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
