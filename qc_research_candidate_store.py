"""QC: Research Candidate local dark-store adapter (SLICE 2B, synthetic fixtures only).

Proves the 2B gates of `services/research_candidate_store.py` against the Rev-2 contract
(`docs/research_candidate_store_contract.md`): round-trip, idempotency, immutability, schema-gate,
sequence, replay — plus the privacy split, explicit-path safety, and deletion-fail-closed guards.
Uses a temporary directory for every DB; no production path, flag, backup, route, UI, or job.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc            # noqa: E402
import services.research_candidate_store as rcs     # noqa: E402

UTC = timezone.utc
OBSERVED = datetime(2026, 10, 25, 11, 0, 0, tzinfo=UTC)
PRE = datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC)
EVENT = datetime(2026, 10, 25, 17, 30, 0, tzinfo=UTC)
POST = datetime(2026, 10, 25, 21, 0, 0, tzinfo=UTC)
THESIS = "usage may rise"
SOURCES = ("https://example.test/bio",)

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def expect_raises(exc, fn, msg):
    try:
        fn()
    except exc:
        check(True, msg)
    except Exception as e:  # noqa: BLE001
        check(False, msg + f"  (raised {type(e).__name__}: {e}, expected {exc.__name__})")
    else:
        check(False, msg + f"  (no exception, expected {exc.__name__})")


def endpoint():
    return rc.PrimaryEndpoint("target_share_lift", "v1", rc.Direction.INCREASE, 0.05, "frac")


def baseline():
    return rc.BaselineMethod("role_matchup_expected_usage", "v1", ("game_script", "team_pass_volume"))


def ent(cid, name):
    return rc.EntityIdentity(cid, name)


def ev(cid):
    return rc.EventIdentity(cid, EVENT)


def obs(oid, e, g, seq):
    return rc.UserObservation(observation_id=oid, observer="owner", entity=e, event=g, thesis=THESIS,
                              observed_at=OBSERVED, bk_captured=PRE, record_seq=seq, sources=SOURCES)


def cand(cid, oid, e, g, seq, sub=rc.SubLabel.BIRTHDAY):
    return rc.ResearchCandidate(
        candidate_id=cid, observation_id=oid, observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=sub, entity=e, event=g,
        temporal=rc.TemporalFacts(OBSERVED, g.event_effective, PRE, seq), thesis=THESIS,
        baseline=baseline(), assumptions=("player active",), eligibility_conditions=("player active",),
        invalidation_conditions=("player_inactive",), primary_endpoint=endpoint(),
        pre_event_snapshot={"expected_target_share": 0.18, "nested": {"x": [1, 2]}}, sources=SOURCES)


def measured(oid, cid, seq, observed=0.30):
    return rc.CandidateOutcome(
        outcome_id=oid, candidate_id=cid, version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=seq, observed_endpoint_value=observed, baseline_expected_value=0.18,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        covariates={"game_script": "neutral", "team_pass_volume": 38.0},
        descriptive={"receiving_yards": 64.0})


def seeded_store(path):
    """A store with a 2-case BIRTHDAY family (distinct entities), both MEASURED -> returns (store, fk)."""
    s = rcs.ResearchCandidateStore(path)
    for i in range(2):
        e, g = ent(f"p{i}", f"P{i}"), ev(f"g{i}")
        s.record_observation(obs(f"o{i}", e, g, s.next_seq()), idempotency_key=f"obs-{i}")
        s.freeze_candidate(cand(f"c{i}", f"o{i}", e, g, s.next_seq()), idempotency_key=f"cand-{i}")
        s.append_outcome(measured(f"m{i}", f"c{i}", s.next_seq()), idempotency_key=f"out-{i}")
    return s, s.load_candidate("c0").family_key


# =========================================================================== A round-trip
def test_round_trip():
    print("\n[A] round-trip: persist -> reopen -> load reproduces content hashes + current tips")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        path = os.path.join(d, "research.db")
        store, fk = seeded_store(path)
        c0 = store.load_candidate("c0")
        out0 = store.current_outcome("c0")
        summary = rc.summarize_family(fk, store._memory().family_cases(fk))
        finding = rc.evaluate_family(finding_id="f0", endpoint=endpoint(), summary=summary,
                                     proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                                     record_seq=store.next_seq())
        store.record_finding(finding, idempotency_key="find-0")
        store.close()
        # a FRESH process/connection against the same file
        store2 = rcs.ResearchCandidateStore(path)
        ro = store2.load_observation("o0")
        check(ro is not None and ro.observer == "owner"
              and ro.content_hash == obs("o0", ent("p0", "P0"), ev("g0"), ro.record_seq).content_hash,
              "observation hash round-trips")
        check(store2.load_candidate("c0").content_hash == c0.content_hash, "candidate hash round-trips")
        check(store2.current_outcome("c0").outcome_id == out0.outcome_id, "current outcome round-trips")
        rf = store2.current_finding(fk)
        check(rf is not None and rf.content_hash == finding.content_hash, "finding hash round-trips")
        check(store2.replay_validate()["candidates"] == 2, "replay reconstructs the full ledger")
        store2.close()


# =========================================================================== B idempotency
def test_idempotency():
    print("\n[B] idempotency: exact retry -> noop; same key + different content -> conflict")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        r1 = store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")
        check(r1["status"] == "recorded", "first write recorded")
        r2 = store.record_observation(obs("o", e, g, r1["record_seq"]), idempotency_key="K")
        check(r2["status"] == "noop" and r2["record_seq"] == r1["record_seq"],
              "exact retry (same key + same content) is a noop returning the existing record")
        diff = rc.UserObservation(observation_id="o2", observer="owner", entity=e, event=g,
                                  thesis="a DIFFERENT thesis", observed_at=OBSERVED, bk_captured=PRE,
                                  record_seq=store.next_seq(), sources=SOURCES)
        expect_raises(rcs.IdempotencyConflict,
                      lambda: store.record_observation(diff, idempotency_key="K"),
                      "same key + different content is a conflict (fail closed)")
        expect_raises(rcs.ResearchStoreError,
                      lambda: store.record_observation(obs("o3", e, g, 999), idempotency_key="  "),
                      "a blank idempotency_key is rejected")
        store.close()


# =========================================================================== C immutability
def test_immutability():
    print("\n[C] stored records are write-once (BEFORE UPDATE triggers abort)")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")
        expect_raises(sqlite3.Error,
                      lambda: store.conn.execute("UPDATE observation_private SET observer='x' WHERE observation_id='o'"),
                      "a direct UPDATE of an observation row is aborted by the immutability trigger")
        store.freeze_candidate(cand("c", "o", e, g, store.next_seq()), idempotency_key="KC")
        expect_raises(sqlite3.Error,
                      lambda: store.conn.execute("UPDATE research_candidate SET content_hash='x' WHERE candidate_id='c'"),
                      "a direct UPDATE of a candidate row is aborted")
        store.close()


# =========================================================================== D schema-gate
def test_schema_gate():
    print("\n[D] an unknown on-disk schema version fails closed")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        store.conn.execute("UPDATE schema_meta SET version=999 WHERE id=1")   # schema_meta is mutable
        store.close()
        expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore(path),
                      "reopening with an unsupported schema version raises SchemaVersionError")


# =========================================================================== E sequence
def test_sequence():
    print("\n[E] store-wide record_seq is strictly monotonic + persisted; next_seq reserves")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        a, b = store.next_seq(), store.next_seq()
        check(a == 1 and b == 2, "two consecutive next_seq() reserve distinct increasing values")
        e, g = ent("p", "P"), ev("g")
        store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")  # claims 3
        # a candidate with a non-increasing record_seq is rejected (via the Slice-1 replay guard)
        expect_raises(rc.SupersessionError,
                      lambda: store.freeze_candidate(cand("c", "o", e, g, 2), idempotency_key="KC"),
                      "a record_seq <= max_claimed is rejected")
        store.close()
        store2 = rcs.ResearchCandidateStore(path)   # allocator persisted across reopen
        check(store2.next_seq() > 3, "next_seq() after reopen advances beyond the persisted max_claimed")
        store2.close()


# =========================================================================== F replay + corruption
def test_replay_and_corruption():
    print("\n[F] replay validates the ledger; a tampered content hash is detected")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        path = os.path.join(d, "r.db")
        store, fk = seeded_store(path)
        # supersede c0 pre-event; replay must keep exactly one current candidate in the lineage.
        c0 = store.load_candidate("c0")
        corr = rc.supersede_candidate(c0, new_temporal=rc.TemporalFacts(OBSERVED, EVENT, PRE,
                                                                        store.next_seq()),
                                      candidate_id="c0b")
        store.freeze_candidate(corr, idempotency_key="cand-0b")
        cases = store._memory().family_cases(fk)
        check(sum(1 for c, _ in cases if c.candidate_id == "c0") == 0
              and any(c.candidate_id == "c0b" for c, _ in cases),
              "replay drops the superseded candidate and keeps the current one")
        # inject a row whose stored content_hash is wrong -> replay/load fails closed.
        row = dict(store.conn.execute("SELECT * FROM observation_private LIMIT 1").fetchone())
        store.conn.execute(
            "INSERT INTO observation_private VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("bogus", "bogus-key", 10 ** 9, row["observer"], row["entity_json"], row["event_json"],
             row["thesis"], row["sources_json"], row["acted"], row["acted_journal_ref"],
             row["observed_at"], row["bk_captured"], "TAMPERED_HASH"))
        expect_raises(rcs.StoreIntegrityError, store.replay_validate,
                      "a row with a mismatched content hash is detected on replay")
        store.close()


# =========================================================================== G privacy split
def test_privacy_split():
    print("\n[G] the research tables hold no observer; identity lives only in the private table")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")
        store.freeze_candidate(cand("c", "o", e, g, store.next_seq()), idempotency_key="KC")
        priv_cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(observation_private)")}
        cand_cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(research_candidate)")}
        check("observer" in priv_cols, "observer lives in observation_private")
        check("observer" not in cand_cols and "thesis" not in cand_cols,
              "research_candidate carries neither observer nor thesis")
        reloaded = store.load_candidate("c")
        check(reloaded.observer == "owner" and reloaded.thesis == THESIS,
              "observer/thesis are rejoined from the private table on load (and the hash verifies)")
        store.close()


# =========================================================================== H path safety
def test_path_safety():
    print("\n[H] the constructor requires an explicit real path (no silent default)")
    expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore(""),
                  "an empty db_path is rejected")
    expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore("   "),
                  "a whitespace db_path is rejected")
    expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore(":memory:"),
                  "an in-memory db_path is rejected (must be a real file)")


# =========================================================================== I deletion fail-closed
def test_deletion_fail_closed():
    print("\n[I] deletion/erasure fails closed in 2B")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        expect_raises(rcs.DeletionNotPermitted, lambda: store.delete_observation("o"),
                      "delete_observation fails closed (no erasure in 2B)")
        expect_raises(rcs.DeletionNotPermitted, lambda: store.erase("o"),
                      "erase fails closed")
        store.close()


# =========================================================================== J conclusions stay closed
def test_store_only_persists_inconclusive():
    print("\n[J] the store can only ever persist INCONCLUSIVE findings (conclusions fail closed)")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        store, fk = seeded_store(os.path.join(d, "r.db"))
        summary = rc.summarize_family(fk, store._memory().family_cases(fk))
        expect_raises(rc.EvaluationEngineNotGoverned, lambda: rc.evaluate_family(
            finding_id="fx", endpoint=endpoint(), summary=summary,
            proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=store.next_seq(),
            evidence=rc.EvidenceBundle(0.12, 0.07, 0.17, 0.06, 0.18, True, True, "x")),
            "a SUPPORTED finding cannot even be constructed to hand to the store")
        store.close()


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE STORE — SLICE 2B QC (local SQLite adapter, synthetic fixtures)")
    print("=" * 80)
    for t in (test_round_trip, test_idempotency, test_immutability, test_schema_gate, test_sequence,
              test_replay_and_corruption, test_privacy_split, test_path_safety,
              test_deletion_fail_closed, test_store_only_persists_inconclusive):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
