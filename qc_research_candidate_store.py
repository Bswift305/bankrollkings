"""QC: Research Candidate local dark-store adapter (SLICE 2B, synthetic fixtures only).

Proves the 2B/v3 gates of `services/research_candidate_store.py` against the Rev-2.1 contract, with the
emphasis on DB-LEVEL (not adapter-level) enforcement: round-trip, observation idempotency via the
governed registry (`capture_observation`), immutability (UPDATE + DELETE), schema-gate, durable sequence
reservation, replay, record<->registry bijection + bind, composite-lineage supersession, current-tip
maintenance/reconcile, integrity/foreign-key/allocator reconcile, pseudonymous naming. Temp-dir DBs only;
no prod path, flag, backup, route, UI, or job.

v3 note: observations are written ONLY through `capture_observation` (no public raw writer); the server
owns the observation_id / clocks / sequence, and the caller supplies governed intent + an opaque key.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc            # noqa: E402
import services.research_candidate_store as rcs     # noqa: E402

UTC = timezone.utc
# Clocks are anchored to "now" so a captured observation (whose clocks the server sets to capture time)
# is always PRE-event (candidates must freeze before the event); the event sits safely in the future.
NOW = datetime.now(UTC)
OBSERVED = NOW
PRE = NOW
EVENT = NOW + timedelta(days=2)
POST = NOW + timedelta(days=3)
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


def evidence_for(e, g, resolver="nfl_identity_event_adapter"):
    """A valid ResolutionEvidence bound to entity `e` + event `g`, with the SAME current season the store
    derives at capture (so the capture-time season gate passes). resolved_at is fresh each call, which is
    exactly why idempotent retries must ignore it."""
    return rc.ResolutionEvidence(
        resolver_id=resolver, resolver_version="v1", props_sha256="a" * 64, roster_sha256="b" * 64,
        roster_season=rcs._current_nfl_season(datetime.now(UTC)),
        event_id=g.canonical_id, player_id=e.canonical_id, resolved_at=datetime.now(UTC))


def cap(store, e, g, key, observer="owner", thesis=THESIS, sources=SOURCES, acted=False, evidence=None):
    """Capture an observation through the ONLY sanctioned v4 path and return (result, stored obs)."""
    r = store.capture_observation(observer_id=observer, entity=e, event=g, thesis=thesis,
                                  sources=sources, acted=acted,
                                  evidence=evidence or evidence_for(e, g), idempotency_key=key)
    return r, store.load_observation(r["id"])


def cand_for(o, cid, seq, sub=rc.SubLabel.BIRTHDAY):
    """Build a candidate that BINDS to a stored observation `o` (same subject/event/thesis/sources)."""
    return rc.ResearchCandidate(
        candidate_id=cid, observation_id=o.observation_id, observer=o.observer,
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=sub, entity=o.entity, event=o.event,
        temporal=rc.TemporalFacts(o.observed_at, o.event.event_effective, o.bk_captured, seq),
        thesis=o.thesis, baseline=baseline(), assumptions=("player active",),
        eligibility_conditions=("player active",), invalidation_conditions=("player_inactive",),
        primary_endpoint=endpoint(),
        pre_event_snapshot={"expected_target_share": 0.18, "nested": {"x": [1, 2]}}, sources=o.sources)


def measured(oid, cid, seq, observed=0.30):
    return rc.CandidateOutcome(
        outcome_id=oid, candidate_id=cid, version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=seq, observed_endpoint_value=observed, baseline_expected_value=0.18,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        covariates={"game_script": "neutral", "team_pass_volume": 38.0}, descriptive={"yds": 64.0})


def seeded_store(path):
    """Two lineages (obs -> candidate -> measured outcome). Observations are CAPTURED (v3), so their ids
    are server-generated; candidates/outcomes keep deterministic ids (c0/c1/m0/m1). Returns (store, fk)."""
    s = rcs.ResearchCandidateStore(path)
    for i in range(2):
        e, g = ent(f"p{i}", f"P{i}"), ev(f"g{i}")
        _, o = cap(s, e, g, f"obs-{i}")
        s.freeze_candidate(cand_for(o, f"c{i}", s.next_seq()), idempotency_key=f"cand-{i}")
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


def oid_of(store, candidate_id):
    """The server-generated observation id behind a candidate (observations have no fixed ids in v3)."""
    return store.load_candidate(candidate_id).observation_id


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
        oid0 = oid_of(store, "c0")
        o0 = store.load_observation(oid0)
        c0, out0 = store.load_candidate("c0"), store.current_outcome("c0")
        summary = rc.summarize_family(fk, store._memory().family_cases(fk))
        finding = rc.evaluate_family(finding_id="f0", endpoint=endpoint(), summary=summary,
                                     proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                                     record_seq=store.next_seq())
        store.record_finding(finding, idempotency_key="find-0")
        store.close()
        s2 = rcs.ResearchCandidateStore(path)
        ro = s2.load_observation(oid0)
        check(ro is not None and ro.content_hash == o0.content_hash, "observation hash round-trips")
        check(s2.load_candidate("c0").content_hash == c0.content_hash, "candidate hash round-trips")
        check(s2.current_outcome("c0").outcome_id == out0.outcome_id, "current outcome round-trips")
        check(s2.current_finding(fk).content_hash == finding.content_hash, "finding hash round-trips")
        check(s2.replay_validate()["candidates"] == 2, "replay reconstructs + reconciles the ledger")
        s2.close()


# =========================================================================== B idempotency (capture)
def test_idempotency():
    print("\n[B] capture idempotency: exact retry -> noop; same key + different intent -> conflict")
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        r1, _ = cap(store, e, g, "K")
        check(r1["status"] == "recorded", "first capture recorded")
        r2 = store.capture_observation(observer_id="owner", entity=e, event=g, thesis=THESIS,
                                       sources=SOURCES, evidence=evidence_for(e, g), idempotency_key="K")
        check(r2["status"] == "noop" and r2["record_seq"] == r1["record_seq"]
              and r2["id"] == r1["id"], "exact retry (fresh evidence) -> noop (same bound record)")
        expect_raises(rcs.IdempotencyConflict,
                      lambda: store.capture_observation(observer_id="owner", entity=e, event=g,
                                                        thesis="different", sources=SOURCES,
                                                        evidence=evidence_for(e, g), idempotency_key="K"),
                      "same key + different intent -> conflict (fail closed)")
        expect_raises(rcs.ResearchStoreError,
                      lambda: store.capture_observation(observer_id="owner", entity=e, event=g,
                                                        thesis=THESIS, evidence=evidence_for(e, g),
                                                        idempotency_key="  "),
                      "a blank idempotency_key is rejected")
        check(store.conn.execute("SELECT COUNT(*) FROM observation_private").fetchone()[0] == 1,
              "no extra observation row from the noop / conflict / blank-key attempts")
        store.close()


# =========================================================================== C immutability (UPDATE+DELETE)
def test_immutability():
    print("\n[C] records + the registry are write-once: BOTH UPDATE and DELETE abort")
    with tmp() as d:
        store, _ = seeded_with_finding(os.path.join(d, "r.db"))
        for t in ("observation_private", "research_candidate", "candidate_outcome", "evaluated_finding"):
            expect_raises(sqlite3.Error, lambda t=t: store.conn.execute(f"UPDATE {t} SET content_hash='x'"),
                          f"UPDATE on {t} aborts")
            expect_raises(sqlite3.Error, lambda t=t: store.conn.execute(f"DELETE FROM {t}"),
                          f"DELETE on {t} aborts")
        expect_raises(sqlite3.Error, lambda: store.conn.execute("DELETE FROM record_registry"),
                      "DELETE on record_registry aborts")
        expect_raises(sqlite3.Error, lambda: store.conn.execute(
            "UPDATE idempotency_registry SET request_fingerprint='x'"), "UPDATE on idempotency_registry aborts")
        expect_raises(sqlite3.Error, lambda: store.conn.execute("DELETE FROM idempotency_registry"),
                      "DELETE on idempotency_registry aborts")
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


# =========================================================================== E current tips (DB-maintained)
def test_current_tips_db_maintained():
    print("\n[E] current tips are maintained by DB triggers (supersession moves the tip)")
    with tmp() as d:
        store, fk = seeded_store(os.path.join(d, "r.db"))
        oid0 = oid_of(store, "c0")
        c0 = store.load_candidate("c0")
        corr = rc.supersede_candidate(c0, new_temporal=rc.TemporalFacts(OBSERVED, EVENT, PRE,
                                                                        store.next_seq()),
                                      candidate_id="c0b")
        store.freeze_candidate(corr, idempotency_key="cand-0b")
        tip = store.conn.execute("SELECT record_seq FROM candidate_current WHERE observation_id=?",
                                 (oid0,)).fetchone()[0]
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
        _, o = cap(store, ent("p", "P"), ev("g"), "K")
        base = dict(store.conn.execute(
            "SELECT * FROM observation_private WHERE observation_id=?", (o.observation_id,)).fetchone())
        s = store.next_seq()   # reserved, NOT registered
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "observation_private", base,
                      observation_id="o2", record_seq=s),
                      "a record with NO matching registry row is rejected (bind trigger)")
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?,?,?)",
                           (s, "observation", "WRONGID"))
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "observation_private", base,
                      observation_id="o3", record_seq=s),
                      "a registry row with the wrong record_id does not satisfy the bind")
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation', ?)",
            (store.next_seq(), o.observation_id)), "same (kind, record_id) under two sequences -> UNIQUE")
        store.close()
    # orphan registry (no matching record) is detected on reopen
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        cap(store, ent("p", "P"), ev("g"), "K")
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
        oid0 = oid_of(store, "c0")
        c1seq = store.load_candidate("c1").temporal.record_seq
        base = dict(store.conn.execute("SELECT * FROM research_candidate WHERE candidate_id='c0'").fetchone())
        s = store.next_seq()
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?,?,?)",
                           (s, "candidate", "xlin"))
        # bound to o0 but supersedes o1's candidate -> tip-guard / composite lineage FK reject it
        expect_raises(sqlite3.Error, lambda: raw_insert(store, "research_candidate", base,
                      candidate_id="xlin", idempotency_key="xlin-k", record_seq=s, observation_id=oid0,
                      supersedes=c1seq),
                      "a candidate bound to o0 superseding o1's candidate is rejected by the DB")
        # a second CURRENT candidate for one observation is a PK violation on candidate_current
        c0seq = base["record_seq"]
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO candidate_current(observation_id, record_seq) VALUES (?, ?)", (oid0, c0seq)),
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
        oid0 = oid_of(store, "c0")
        c0 = store.load_candidate("c0")
        store.freeze_candidate(rc.supersede_candidate(
            c0, new_temporal=rc.TemporalFacts(OBSERVED, EVENT, PRE, store.next_seq()),
            candidate_id="c0b"), idempotency_key="c0b")       # now c0 superseded, c0b current
        c0seq = c0.temporal.record_seq
        store.conn.execute("UPDATE candidate_current SET record_seq=? WHERE observation_id=?", (c0seq, oid0))
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
    print("\n[AR] durable reservation: distinct values, no reissue of an unclaimed gap, claim-once")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        a = rcs.ResearchCandidateStore(path)
        b = rcs.ResearchCandidateStore(path)
        sa, sb = a.next_seq(), b.next_seq()
        check(sa == 1 and sb == 2, "two connections reserve DISTINCT durable values (operator next_seq)")
        a.close()
        b.close()
    with tmp() as d:
        path = os.path.join(d, "r.db")
        s1 = rcs.ResearchCandidateStore(path)
        reserved = s1.next_seq()            # reserved, never claimed
        s1.close()
        s2 = rcs.ResearchCandidateStore(path)
        check(s2.next_seq() == reserved + 1, "a restart does NOT reissue an unclaimed reservation (durable gap)")
        s2.close()
    # claim mechanics on the candidate path (still two-transaction): unreserved + already-claimed rejected
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        _, o = cap(store, ent("p", "P"), ev("g"), "K")
        expect_raises(rcs.SequenceError,
                      lambda: store.freeze_candidate(cand_for(o, "cx", 10 ** 6), idempotency_key="cx"),
                      "an unreserved record_seq cannot be claimed (candidate path)")
        _, o2 = cap(store, ent("p2", "P2"), ev("g2"), "K2")
        s = store.next_seq()
        store.freeze_candidate(cand_for(o, "c_a", s), idempotency_key="c_a")   # claims s
        before = counts(store)
        expect_raises((rc.SupersessionError, rcs.SequenceError),
                      lambda: store.freeze_candidate(cand_for(o2, "c_b", s), idempotency_key="c_b"),
                      "an already-claimed reservation cannot be claimed again")
        check(counts(store) == before, "a failed claim leaves NO new registry/reservation/record residue")
        store.close()


# =========================================================================== AS pseudonymous + conclusions + guards
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
        raw_insert(store, "observation_private", base, observation_id="tamper",
                   record_seq=s, content_hash="TAMPERED_HASH")
        # bind the tampered observation so the reopen reconcile passes and the HASH check is what fails
        store.conn.execute(
            "INSERT INTO idempotency_registry(record_kind,observer_id,idempotency_key,"
            "request_fingerprint,bound_record_seq,bound_record_id,created_at) "
            "VALUES ('observation', ?, 'tamper-k', ?, ?, 'tamper', ?)",
            (base["observer"], "0" * 64, s, "2026-10-31T00:00:00+00:00"))
        expect_raises(rcs.StoreIntegrityError, store.replay_validate,
                      "a row whose stored content hash does not recompute is detected on replay")
        store.close()


# =========================================================================== AT schema version bump (v1/v2/v3 rejected)
def test_v_prior_schema_rejected():
    print("\n[AT] SCHEMA_VERSION bumped: earlier v1/v2/v3 stores are rejected without mutation")
    check(rcs.SCHEMA_VERSION >= 4, "SCHEMA_VERSION advanced to 4 for the evidence invariant")
    for prior in (1, 2, 3):
        with tmp() as d:
            path = os.path.join(d, "r.db")
            rcs.ResearchCandidateStore(path).close()
            raw = sqlite3.connect(path)
            raw.execute("UPDATE schema_meta SET version=? WHERE id=1", (prior,))
            raw.commit()
            before = [r[0] for r in raw.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
            raw.close()
            expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore(path),
                          f"a v{prior} schema is rejected (fail closed, no migration)")
            raw2 = sqlite3.connect(path)
            after = [r[0] for r in raw2.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
            v = raw2.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
            raw2.close()
            check(before == after and v == prior, f"the rejected v{prior} open mutated nothing")


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


# =========================================================================== AV evidence required + validated
def test_evidence_required_and_validated():
    print("\n[AV] capture REQUIRES a valid ResolutionEvidence; bad evidence fails closed (no reservation)")
    with tmp() as d:
        store = rcs.ResearchCandidateStore(os.path.join(d, "r.db"))
        e, g = ent("p", "P"), ev("g")
        season = rcs._current_nfl_season(datetime.now(UTC))

        def mkev(**over):
            base = dict(resolver_id="nfl_identity_event_adapter", resolver_version="v1",
                        props_sha256="a" * 64, roster_sha256="b" * 64, roster_season=season,
                        event_id=g.canonical_id, player_id=e.canonical_id, resolved_at=datetime.now(UTC))
            base.update(over)
            return rc.ResolutionEvidence(**base)

        def capev(evid, key, sources=SOURCES):
            return store.capture_observation(observer_id="owner", entity=e, event=g, thesis=THESIS,
                                             sources=sources, evidence=evid, idempotency_key=key)
        expect_raises(rcs.ResearchStoreError, lambda: capev(None, "k0"), "evidence=None is rejected")
        expect_raises(rcs.ResearchStoreError, lambda: capev(mkev(resolver_id="rogue"), "k1"),
                      "an unregistered resolver_id is rejected")
        expect_raises(rcs.ResearchStoreError, lambda: capev(mkev(event_id="WRONG"), "k2"),
                      "evidence event id != resolved event -> rejected")
        expect_raises(rcs.ResearchStoreError, lambda: capev(mkev(player_id="WRONG"), "k2b"),
                      "evidence player id != resolved entity -> rejected")
        expect_raises(rcs.ResearchStoreError, lambda: capev(mkev(roster_season=1999), "k3"),
                      "evidence roster_season != current season -> rejected")
        expect_raises(rc.TypeStrictError, lambda: mkev(roster_season=True),
                      "a boolean roster_season is rejected by the frozen object")
        expect_raises(rc.TypeStrictError, lambda: mkev(props_sha256="A" * 64),
                      "an uppercase (non-lowercase-hex) sha is rejected by the frozen object")
        expect_raises(rcs.ResearchStoreError,
                      lambda: capev(mkev(), "k4", sources=("BKRES:forged",)),
                      "an owner source in the reserved namespace is rejected")
        check(store.conn.execute("SELECT COUNT(*) FROM observation_private").fetchone()[0] == 0
              and store.conn.execute("SELECT COALESCE(MAX(record_seq),0) FROM seq_reservation").fetchone()[0] == 0,
              "every rejected capture consumed NO reservation and wrote no record")
        _, o = cap(store, e, g, "ok")
        refs = [s for s in o.sources if s.startswith("bkres:v1:")]
        check(len(refs) == 7, "a successful capture persists the 7 reserved evidence references in sources")
        store.close()


# =========================================================================== AW reopen evidence + fingerprint parity
def test_reopen_evidence_and_fingerprint():
    print("\n[AW] reopen fails closed on incomplete evidence OR an altered intent fingerprint")

    def craft(path, *, drop_season=False, bad_fp=False):
        store = rcs.ResearchCandidateStore(path)
        _, o = cap(store, ent("p", "P"), ev("g"), "K")
        base = dict(store.conn.execute(
            "SELECT * FROM observation_private WHERE observation_id=?", (o.observation_id,)).fetchone())
        srcs = list(rcs._u(base["sources_json"]))
        if drop_season:
            srcs = [s for s in srcs if not s.startswith("bkres:v1:roster-season=")]
        s = store.next_seq()
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation','tamp')", (s,))
        store.conn.execute("UPDATE seq_reservation SET claimed=1 WHERE record_seq=?", (s,))
        raw_insert(store, "observation_private", base, observation_id="tamp", record_seq=s,
                   sources_json=rcs._j(srcs), content_hash="x")
        fp = "0" * 64 if bad_fp else None
        if fp is None:    # recompute the correct fp so ONLY the dropped field is the defect
            owner, _system = rcs._partition_sources(srcs)
            fp = rcs._request_fingerprint(base["observer"], rcs._entity(rcs._u(base["entity_json"])),
                                          rcs._event(rcs._u(base["event_json"])), base["thesis"],
                                          owner, bool(base["acted"]))
        store.conn.execute(
            "INSERT INTO idempotency_registry(record_kind,observer_id,idempotency_key,"
            "request_fingerprint,bound_record_seq,bound_record_id,created_at) "
            "VALUES ('observation','owner','tk',?,?, 'tamp', ?)", (fp, s, "2026-10-31T00:00:00+00:00"))
        store.close()

    with tmp() as d:
        p = os.path.join(d, "r.db")
        craft(p, drop_season=True)
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(p),
                      "an incomplete evidence set (missing a reserved field) fails closed on reopen")
    with tmp() as d:
        p = os.path.join(d, "r.db")
        craft(p, bad_fp=True)
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore(p),
                      "a stored intent whose recomputed fingerprint != the registry's fails closed on reopen")


# =========================================================================== AX calendar advancement
def test_calendar_advancement():
    print("\n[AX] a prior-season observation stays valid when the calendar advances (reopen season-agnostic)")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store = rcs.ResearchCandidateStore(path)
        cap(store, ent("pa", "PA"), ev("ga"), "A")      # captured under the real current season S
        store.close()
        real = rcs._current_nfl_season
        try:
            rcs._current_nfl_season = lambda now: real(now) + 1   # simulate the calendar advancing a year
            s2 = rcs.ResearchCandidateStore(path)                 # reopen: the season-S obs must NOT invalidate
            check(s2.replay_validate()["observations"] == 1, "prior-season observation reopens + replays cleanly")
            cap(s2, ent("pb", "PB"), ev("gb"), "B")               # a new capture requires the advanced season
            check(s2.conn.execute("SELECT COUNT(*) FROM observation_private").fetchone()[0] == 2,
                  "a new-season capture is accepted alongside the retained prior-season one")
            s2.close()
            s3 = rcs.ResearchCandidateStore(path)
            check(s3.replay_validate()["observations"] == 2, "both seasons validate on reopen (no season pinning)")
            s3.close()
        finally:
            rcs._current_nfl_season = real


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE STORE — SLICE 2B/v4 QC (DB-enforced ledger, synthetic fixtures)")
    print("=" * 80)
    for t in (test_round_trip, test_idempotency, test_immutability, test_schema_gate,
              test_current_tips_db_maintained, test_unsupported_schema_zero_mutation,
              test_registry_binding, test_lineage_and_one_current_db_enforced, test_reopen_reconcile,
              test_foreign_key_check_disables_store, test_durable_reservation,
              test_pseudonymous_and_guards, test_replay_and_tamper, test_v_prior_schema_rejected,
              test_reservation_integrity_bidirectional, test_evidence_required_and_validated,
              test_reopen_evidence_and_fingerprint, test_calendar_advancement):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
