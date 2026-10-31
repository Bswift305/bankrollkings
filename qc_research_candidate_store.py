"""QC: Research Candidate local dark-store adapter (SLICE 2B, synthetic fixtures only).

Proves the 2B gates of `services/research_candidate_store.py` against the Rev-2 contract, with the
emphasis on DB-LEVEL (not adapter-level) enforcement: round-trip, idempotency, immutability (UPDATE
+ DELETE), schema-gate, durable sequence reservation, replay, record<->registry bijection + bind,
composite-lineage supersession, current-tip maintenance/reconcile, integrity/foreign-key/allocator
reconcile, pseudonymous naming. Temp-dir DBs only; no prod path, flag, backup, route, UI, or job.
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
        check(False, msg + f"  (raised {type(e).__name__}: {e}, expected {exc})")
    else:
        check(False, msg + f"  (no exception, expected {exc})")


def tmp():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


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
        covariates={"game_script": "neutral", "team_pass_volume": 38.0}, descriptive={"yds": 64.0})


def seeded_store(path):
    s = rcs.ResearchCandidateStore(path)
    for i in range(2):
        e, g = ent(f"p{i}", f"P{i}"), ev(f"g{i}")
        s.record_observation(obs(f"o{i}", e, g, s.next_seq()), idempotency_key=f"obs-{i}")
        s.freeze_candidate(cand(f"c{i}", f"o{i}", e, g, s.next_seq()), idempotency_key=f"cand-{i}")
        s.append_outcome(measured(f"m{i}", f"c{i}", s.next_seq()), idempotency_key=f"out-{i}")
    return s, s.load_candidate("c0").family_key


def seeded_with_finding(path):
    store, fk = seeded_store(path)
    summary = rc.summarize_family(fk, store._memory().family_cases(fk))
    store.record_finding(
        rc.evaluate_family(finding_id="f0", endpoint=endpoint(), summary=summary,
                           proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                           record_seq=store.next_seq()), idempotency_key="find-0")
    return store, fk


def raw_insert(store, table, base_row, **overrides):
    """Direct SQL INSERT copying a base row and overriding named columns (adversarial probes)."""
    row = dict(base_row)
    row.update(overrides)
    cols = list(row.keys())
    store.conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                       [row[c] for c in cols])


def counts(store):
    g = lambda t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    return (g("record_registry"), g("observation_private"),
            store.conn.execute("SELECT COUNT(*) FROM seq_reservation WHERE claimed=1").fetchone()[0])


# =========================================================================== A round-trip
def test_round_trip():
    print("\n[A] round-trip: persist -> reopen -> load reproduces content hashes + current tips")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store, fk = seeded_store(path)
        c0, out0 = store.load_candidate("c0"), store.current_outcome("c0")
        summary = rc.summarize_family(fk, store._memory().family_cases(fk))
        finding = rc.evaluate_family(finding_id="f0", endpoint=endpoint(), summary=summary,
                                     proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                                     record_seq=store.next_seq())
        store.record_finding(finding, idempotency_key="find-0")
        store.close()
        s2 = rcs.ResearchCandidateStore(path)
        ro = s2.load_observation("o0")
        check(ro is not None and ro.content_hash == obs("o0", ent("p0", "P0"), ev("g0"),
              ro.record_seq).content_hash, "observation hash round-trips")
        check(s2.load_candidate("c0").content_hash == c0.content_hash, "candidate hash round-trips")
        check(s2.current_outcome("c0").outcome_id == out0.outcome_id, "current outcome round-trips")
        check(s2.current_finding(fk).content_hash == finding.content_hash, "finding hash round-trips")
        check(s2.replay_validate()["candidates"] == 2, "replay reconstructs + reconciles the ledger")
        s2.close()


# =========================================================================== B idempotency
def test_idempotency():
    print("\n[B] idempotency: exact retry -> noop; same key + different content -> conflict")
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        r1 = store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")
        check(r1["status"] == "recorded", "first write recorded")
        r2 = store.record_observation(obs("o", e, g, r1["record_seq"]), idempotency_key="K")
        check(r2["status"] == "noop" and r2["record_seq"] == r1["record_seq"], "exact retry -> noop")
        diff = rc.UserObservation(observation_id="o2", observer="owner", entity=e, event=g,
                                  thesis="different", observed_at=OBSERVED, bk_captured=PRE,
                                  record_seq=store.next_seq(), sources=SOURCES)
        expect_raises(rcs.IdempotencyConflict, lambda: store.record_observation(diff, idempotency_key="K"),
                      "same key + different content -> conflict (fail closed)")
        expect_raises(rcs.ResearchStoreError,
                      lambda: store.record_observation(obs("o3", e, g, 999), idempotency_key="  "),
                      "a blank idempotency_key is rejected")
        store.close()


# =========================================================================== C immutability (UPDATE+DELETE)
def test_immutability():
    print("\n[C] records are write-once: BOTH UPDATE and DELETE abort on every record table")
    with tmp() as d:
        store, _ = seeded_with_finding(os.path.join(d, "r.db"))
        for t in ("observation_private", "research_candidate", "candidate_outcome", "evaluated_finding"):
            expect_raises(sqlite3.Error, lambda t=t: store.conn.execute(f"UPDATE {t} SET content_hash='x'"),
                          f"UPDATE on {t} aborts")
            expect_raises(sqlite3.Error, lambda t=t: store.conn.execute(f"DELETE FROM {t}"),
                          f"DELETE on {t} aborts")
        expect_raises(sqlite3.Error, lambda: store.conn.execute("DELETE FROM record_registry"),
                      "DELETE on record_registry aborts")
        store.close()


# =========================================================================== D schema-gate
def test_schema_gate():
    print("\n[D] an unknown on-disk schema version fails closed")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        rcs.ResearchCandidateStore(path).close()
        raw = sqlite3.connect(path)
        raw.execute("UPDATE schema_meta SET version=999 WHERE id=1")
        raw.commit()
        raw.close()
        expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore(path),
                      "unsupported version raises SchemaVersionError")


# =========================================================================== E round-trip of finding/current
def test_current_tips_db_maintained():
    print("\n[E] current tips are maintained by DB triggers (supersession moves the tip)")
    with tmp() as d:
        store, fk = seeded_store(os.path.join(d, "r.db"))
        c0 = store.load_candidate("c0")
        corr = rc.supersede_candidate(c0, new_temporal=rc.TemporalFacts(OBSERVED, EVENT, PRE,
                                                                        store.next_seq()),
                                      candidate_id="c0b")
        store.freeze_candidate(corr, idempotency_key="cand-0b")
        tip = store.conn.execute("SELECT record_seq FROM candidate_current WHERE observation_id='o0'").fetchone()[0]
        check(tip == corr.temporal.record_seq, "the DB-maintained candidate tip advanced to the successor")
        cases = store._memory().family_cases(fk)
        check(any(c.candidate_id == "c0b" for c, _ in cases)
              and all(c.candidate_id != "c0" for c, _ in cases), "superseded candidate dropped from cases")
        store.close()


# =========================================================================== AK unsupported-schema zero mutation
def test_unsupported_schema_zero_mutation():
    print("\n[AK] an unsupported-schema open mutates NOTHING before failing closed")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        rcs.ResearchCandidateStore(path).close()
        raw = sqlite3.connect(path)
        raw.execute("UPDATE schema_meta SET version=999 WHERE id=1")
        raw.commit()
        before = [r[0] for r in raw.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        raw.close()
        expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore(path), "fails closed")
        raw2 = sqlite3.connect(path)
        after = [r[0] for r in raw2.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        ver = raw2.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        raw2.close()
        check(before == after and ver == 999, "the failed open altered no schema object / version")


# =========================================================================== AM registry<->record bijection + bind
def test_registry_binding():
    print("\n[AM] record<->registry bijection + bind triggers (DB-enforced)")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        e, g = ent("p", "P"), ev("g")
        store.record_observation(obs("o", e, g, store.next_seq()), idempotency_key="K")
        base = dict(store.conn.execute("SELECT * FROM observation_private WHERE observation_id='o'").fetchone())
        s = store.next_seq()   # reserved, NOT registered
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "observation_private", base,
                      observation_id="o2", idempotency_key="k2", record_seq=s),
                      "a record with NO matching registry row is rejected (bind trigger)")
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?,?,?)",
                           (s, "observation", "WRONGID"))
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "observation_private", base,
                      observation_id="o3", idempotency_key="k3", record_seq=s),
                      "a registry row with the wrong record_id does not satisfy the bind")
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation', 'o')",
            (store.next_seq(),)), "same (kind, record_id) under two sequences -> UNIQUE violation")
        store.close()
    # orphan registry (no matching record) is detected on reopen
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        store.record_observation(obs("o", ent("p", "P"), ev("g"), store.next_seq()), idempotency_key="K")
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'candidate', 'ghost')",
                           (store.next_seq(),))
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(path),
                      "an orphan registry row (no matching record) is detected on reopen")


# =========================================================================== AO composite lineage + one-current (DB)
def test_lineage_and_one_current_db_enforced():
    print("\n[AO] cross-lineage/stale supersession + duplicate current rejected by the DB itself")
    with tmp() as d:
        store, _ = seeded_store(os.path.join(d, "r.db"))
        c1seq = store.load_candidate("c1").temporal.record_seq
        base = dict(store.conn.execute("SELECT * FROM research_candidate WHERE candidate_id='c0'").fetchone())
        s = store.next_seq()
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?,?,?)",
                           (s, "candidate", "xlin"))
        # bound to o0 but supersedes o1's candidate -> tip-guard / composite lineage FK reject it
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "research_candidate", base,
                      candidate_id="xlin", idempotency_key="xlin-k", record_seq=s, observation_id="o0",
                      supersedes=c1seq),
                      "a candidate bound to o0 superseding o1's candidate is rejected by the DB")
        # a second CURRENT candidate for one observation is a PK violation on candidate_current
        c0seq = base["record_seq"]
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO candidate_current(observation_id, record_seq) VALUES ('o0', ?)", (c0seq,)),
            "a second current candidate for one observation -> candidate_current PK violation")
        store.close()


# =========================================================================== AP allocator + tip reconcile on reopen
def test_reopen_reconcile():
    print("\n[AP] reopen reconciles allocator<->registry and tips<->rows (fail closed)")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store, _ = seeded_store(path)
        store.conn.execute("UPDATE seq_allocator SET max_claimed=999999 WHERE id=1")
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(path),
                      "allocator max_claimed != MAX(registry) disables the store")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store, _ = seeded_store(path)
        c0 = store.load_candidate("c0")
        store.freeze_candidate(rc.supersede_candidate(
            c0, new_temporal=rc.TemporalFacts(OBSERVED, EVENT, PRE, store.next_seq()),
            candidate_id="c0b"), idempotency_key="c0b")       # now c0 superseded, c0b current
        c0seq = c0.temporal.record_seq
        store.conn.execute("UPDATE candidate_current SET record_seq=? WHERE observation_id='o0'", (c0seq,))
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(path),
                      "a tip pointing at a superseded (non-current) row is detected on reopen")


# =========================================================================== AQ foreign_key_check disables
def test_foreign_key_check_disables_store():
    print("\n[AQ] a foreign_key_check failure disables the store on reopen")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store, _ = seeded_store(path)
        store.conn.execute("PRAGMA foreign_keys=OFF")
        store.conn.execute("INSERT INTO candidate_current(observation_id, record_seq) VALUES ('GHOST', 999999)")
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(path),
                      "an orphaned FK (ghost current-tip) disables the store on reopen")


# =========================================================================== AR durable reservation
def test_durable_reservation():
    print("\n[AR] next_seq durably reserves: no reissue across restart; unclaimed = permanent gap")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        a = rcs.ResearchCandidateStore(path)
        b = rcs.ResearchCandidateStore(path)
        sa, sb = a.next_seq(), b.next_seq()
        check(sa == 1 and sb == 2, "two connections reserve DISTINCT durable values (no shared seq)")
        a.record_observation(obs("oa", ent("pa", "PA"), ev("ga"), sa), idempotency_key="KA")
        # an already-claimed sequence cannot be claimed again (rejected fail-closed by the monotonic
        # replay guard and/or the reservation claimed-flag check).
        expect_raises((rc.SupersessionError, rcs.SequenceError),
                      lambda: a.record_observation(obs("oa2", ent("pa2", "PA2"), ev("ga2"), sa),
                                                   idempotency_key="KA2"),
                      "an already-claimed reservation cannot be claimed again")
        a.close()
        b.close()
    with tmp() as d:
        path = os.path.join(d, "r.db")
        s1 = rcs.ResearchCandidateStore(path)
        reserved = s1.next_seq()            # reserved, never claimed
        s1.close()
        s2 = rcs.ResearchCandidateStore(path)
        check(s2.next_seq() == reserved + 1, "a restart does NOT reissue an unclaimed reservation (durable gap)")
        # a record_seq that was never reserved cannot be claimed
        expect_raises(rcs.SequenceError,
                      lambda: s2.record_observation(obs("ox", ent("px", "PX"), ev("gx"), 10 ** 6),
                                                    idempotency_key="KX"),
                      "an unreserved record_seq cannot be claimed")
        s2.close()
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        before = counts(store)
        expect_raises(rcs.SequenceError,
                      lambda: store.record_observation(obs("o", ent("p", "P"), ev("g"), 500),
                                                       idempotency_key="K"),
                      "a failed write (unreserved seq) is rejected")
        check(counts(store) == before, "a failed write leaves NO registry/reservation/record residue")
        store.close()


# =========================================================================== AS pseudonymous + conclusions + path/deletion
def test_pseudonymous_and_guards():
    print("\n[AS] pseudonymous naming, path safety, deletion + conclusions fail closed")
    doc, src = (rcs.__doc__ or "").lower(), rcs._SCHEMA_SQL.lower()
    check("pseudonymous" in doc and "not de-identified" in doc, "module doc says pseudonymous / linkable")
    check("de-identified research evidence" not in doc and "de-identified research evidence" not in src,
          "the 'de-identified research evidence' overclaim is gone from doc + schema")
    check("pseudonymous" in src or "linkable" in src, "schema comments say pseudonymous/linkable")
    expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore(""), "empty path rejected")
    expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore(":memory:"),
                  "in-memory path rejected")
    with tmp() as d:
        store, fk = seeded_store(os.path.join(d, "r.db"))
        priv = {r["name"] for r in store.conn.execute("PRAGMA table_info(observation_private)")}
        cc = {r["name"] for r in store.conn.execute("PRAGMA table_info(research_candidate)")}
        check("observer" in priv and "observer" not in cc and "thesis" not in cc,
              "observer/thesis live only in the private table (pseudonymous/linkable evidence)")
        expect_raises(rcs.DeletionNotPermitted, lambda: store.delete_observation("o0"), "deletion fails closed")
        summary = rc.summarize_family(fk, store._memory().family_cases(fk))
        expect_raises(rc.EvaluationEngineNotGoverned, lambda: rc.evaluate_family(
            finding_id="fx", endpoint=endpoint(), summary=summary,
            proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=store.next_seq(),
            evidence=rc.EvidenceBundle(0.12, 0.07, 0.17, 0.06, 0.18, True, True, "x")),
            "a SUPPORTED finding cannot be constructed to hand to the store (fail closed)")
        store.close()


# =========================================================================== F replay + tampered hash
def test_replay_and_tamper():
    print("\n[F] replay validates the ledger; a tampered content hash is detected")
    with tmp() as d:
        store, _ = seeded_store(os.path.join(d, "r.db"))
        base = dict(store.conn.execute("SELECT * FROM observation_private LIMIT 1").fetchone())
        s = store.next_seq()
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation', 'tamper')",
                           (s,))
        store.conn.execute("UPDATE seq_reservation SET claimed=1 WHERE record_seq=?", (s,))  # bind needs this
        raw_insert(store, "observation_private", base, observation_id="tamper", idempotency_key="tamper-k",
                   record_seq=s, content_hash="TAMPERED_HASH")
        expect_raises(rcs.StoreIntegrityError, store.replay_validate,
                      "a row whose stored content hash does not recompute is detected on replay")
        store.close()


# =========================================================================== AT schema version bump (v1 rejected)
def test_v1_schema_rejected():
    print("\n[AT] SCHEMA_VERSION bumped: an earlier v1 store is rejected without mutation")
    check(rcs.SCHEMA_VERSION >= 2, "SCHEMA_VERSION advanced past 1 for the incompatible schema change")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        rcs.ResearchCandidateStore(path).close()
        raw = sqlite3.connect(path)
        raw.execute("UPDATE schema_meta SET version=1 WHERE id=1")   # simulate an earlier v1 store
        raw.commit()
        before = [r[0] for r in raw.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        raw.close()
        expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore(path),
                      "a v1 schema is rejected (fail closed, no migration)")
        raw2 = sqlite3.connect(path)
        after = [r[0] for r in raw2.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        v = raw2.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        raw2.close()
        check(before == after and v == 1, "the rejected v1 open mutated nothing")


# =========================================================================== AU reservation integrity bidirectional
def test_reservation_integrity_bidirectional():
    print("\n[AU] a claimed reservation cannot exist without a registry row (trigger + reopen)")
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        s = store.next_seq()   # reserved (claimed=0), NO registry row
        expect_raises(sqlite3.Error,
                      lambda: store.conn.execute("UPDATE seq_reservation SET claimed=1 WHERE record_seq=?", (s,)),
                      "flipping a reservation to claimed with no registry row is rejected immediately")
        # the reverse direction (registry without a claimed reservation) is caught on reopen
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation', 'x')",
                           (store.next_seq(),))
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(os.path.join(d, "r.db")),
                      "a registry row without a claimed reservation is caught on reopen")


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE STORE — SLICE 2B QC (DB-enforced ledger, synthetic fixtures)")
    print("=" * 80)
    for t in (test_round_trip, test_idempotency, test_immutability, test_schema_gate,
              test_current_tips_db_maintained, test_unsupported_schema_zero_mutation,
              test_registry_binding, test_lineage_and_one_current_db_enforced, test_reopen_reconcile,
              test_foreign_key_check_disables_store, test_durable_reservation,
              test_pseudonymous_and_guards, test_replay_and_tamper, test_v1_schema_rejected,
              test_reservation_integrity_bidirectional):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
