"""QC: Research Candidate observation idempotency registry (SCHEMA v3, LOCAL ONLY).

The fourteen adversarial cases from `docs/research_candidate_idempotency_registry_design.md` (Rev 2.1).
Proves the governed `idempotency_registry`: capture is single-transaction, an exact retry is a true
no-op (no sequence consumed), a changed payload conflicts, the fingerprint excludes the server
sequence/clocks and the deferred candidate fields, the DB rejects mismatched kind/id/observer, there is
no observation-supersession path, no cleartext PII in the registry, write-once + v3 gate, concurrency
yields one record + one binding, an unbound observation or a double-bound observation fails closed on
reopen, and only observation_private loses its legacy idempotency_key in v3.

Temp-dir DBs only; no route, flag, boundary, unit file, UI, or deployment.
"""
import inspect
import os
import sqlite3
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc            # noqa: E402
import services.research_candidate_store as rcs     # noqa: E402
import qc_research_candidate_store as sq            # noqa: E402  (fixtures only; tests are __main__-gated)

UTC = timezone.utc
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


def mk(path):
    return rcs.ResearchCandidateStore(path)


def n_obs(store):
    return store.conn.execute("SELECT COUNT(*) FROM observation_private").fetchone()[0]


def n_idem(store):
    return store.conn.execute("SELECT COUNT(*) FROM idempotency_registry").fetchone()[0]


def max_res(store):
    return store.conn.execute("SELECT COALESCE(MAX(record_seq),0) FROM seq_reservation").fetchone()[0]


# 1 =========================================================================
def test_no_nested_transaction():
    print("\n[1] capture_observation runs in ONE transaction; its internals issue no BEGIN")
    cap_src = inspect.getsource(rcs.ResearchCandidateStore.capture_observation)
    res_src = inspect.getsource(rcs.ResearchCandidateStore._reserve_seq_in_txn)
    ins_src = inspect.getsource(rcs.ResearchCandidateStore._insert_observation_in_txn)
    check(cap_src.count("self._begin()") == 1, "capture_observation opens exactly one transaction")
    for nm, s in (("_reserve_seq_in_txn", res_src), ("_insert_observation_in_txn", ins_src)):
        check("self._begin" not in s and 'execute("BEGIN' not in s and 'execute("COMMIT' not in s
              and 'execute("ROLLBACK' not in s, f"{nm} starts/ends no transaction of its own")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        r, _ = sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K")   # must not raise 'transaction within a transaction'
        check(r["status"] == "recorded", "a capture completes within a single BEGIN IMMEDIATE")
        store.close()


# 2 =========================================================================
def test_exact_retry_true_noop():
    print("\n[2] exact retry -> true no-op: no new reservation consumed, no second record")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        r1, _ = sq.cap(store, e, g, "K")
        before = max_res(store)
        r2 = store.capture_observation(observer_id="owner", entity=e, event=g, thesis=sq.THESIS,
                                       sources=sq.SOURCES, idempotency_key="K")
        check(r2["status"] == "noop" and r2["id"] == r1["id"] and r2["record_seq"] == r1["record_seq"],
              "retry returns the ORIGINAL id + seq")
        check(max_res(store) == before, "no new reservation was consumed by the retry")
        check(n_obs(store) == 1 and n_idem(store) == 1, "exactly one observation + one binding")
        store.close()


# 2b ========================================================================
def test_input_coercion_rejected():
    print("\n[2b] capture rejects string-as-sources, non-string/empty source, and non-bool acted")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        before = max_res(store)
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=g, thesis="t", sources="http://x", idempotency_key="k1"),
            "a bare string as sources is rejected (not iterated char by char)")
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=g, thesis="t", sources=[123], idempotency_key="k2"),
            "a non-string source is rejected")
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=g, thesis="t", sources=[""], idempotency_key="k2b"),
            "an empty-string source is rejected")
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=g, thesis="t", acted="false", idempotency_key="k3"),
            "acted='false' (a string) is rejected (no truthy coercion)")
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=g, thesis="t", acted=1, idempotency_key="k4"),
            "acted=1 (an int) is rejected")
        check(max_res(store) == before and n_obs(store) == 0, "no rejected input consumed a reservation")
        store.close()


# 2c ========================================================================
def test_canonical_sources_and_nfc_equivalence():
    print("\n[2c] sources canonicalized ONCE (NFC + sorted-unique); persisted == fingerprinted")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        r1, o1 = sq.cap(store, e, g, "K", sources=("https://x/b", "https://x/a", "https://x/a"))
        check(tuple(o1.sources) == ("https://x/a", "https://x/b"),
              "stored sources are NFC + sorted + de-duplicated (canonical tuple)")
        r2 = store.capture_observation(observer_id="owner", entity=e, event=g, thesis=sq.THESIS,
                                       sources=["https://x/a", "https://x/b", "https://x/b"],
                                       idempotency_key="K")
        check(r2["status"] == "noop" and r2["id"] == r1["id"],
              "a reordered + duplicated sources retry hashes equal -> noop")
        nfc = unicodedata.normalize("NFC", "café")   # café, composed
        nfd = unicodedata.normalize("NFD", "café")  # café, decomposed
        ra, _ = sq.cap(store, sq.ent("q", "Q"), g, "T", thesis=nfc)
        rb = store.capture_observation(observer_id="owner", entity=sq.ent("q", "Q"), event=g,
                                       thesis=nfd, sources=sq.SOURCES, idempotency_key="T")
        check(rb["status"] == "noop" and rb["id"] == ra["id"],
              "an NFD vs NFC thesis hashes equal -> noop (thesis NFC-normalized once)")
        store.close()


# 3b ========================================================================
def test_capture_eligibility_gate():
    print("\n[3b] the sole writer enforces eligibility: unresolved entity / non-future event refused")
    nonres = next(r for r in rc.Resolution if r is not rc.Resolution.RESOLVED)
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        before = max_res(store)
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=rc.EntityIdentity("p", "P", nonres), event=g, thesis="t",
            idempotency_key="k1"), "an unresolved/ambiguous entity is refused")
        past = rc.EventIdentity("gp", datetime.now(UTC) - timedelta(hours=1))
        expect_raises(rcs.ResearchStoreError, lambda: store.capture_observation(
            observer_id="owner", entity=e, event=past, thesis="t", idempotency_key="k2"),
            "an event whose effective time is not in the future is refused")
        check(max_res(store) == before and n_obs(store) == 0,
              "a refused capture consumed NO reservation and wrote no record")
        store.close()


# 3 =========================================================================
def test_clocks_and_seq_excluded():
    print("\n[3] the fingerprint excludes record_seq + capture clocks (two captures hash equal)")
    fp_params = set(inspect.signature(rcs._request_fingerprint).parameters)
    check(fp_params == {"observer_id", "entity", "event", "thesis", "sources", "acted"},
          "fingerprint inputs are exactly the persisted intent (no seq, no clocks)")
    e, g = sq.ent("p", "P"), sq.ev("g")
    fp1 = rcs._request_fingerprint("owner", e, g, sq.THESIS, sq.SOURCES, False)
    fp2 = rcs._request_fingerprint("owner", e, g, sq.THESIS, sq.SOURCES, False)
    check(fp1 == fp2 and len(fp1) == 64, "the fingerprint is stable and a 64-hex digest")


# 4 =========================================================================
def test_different_fingerprint_conflicts():
    print("\n[4] same key + different fingerprint -> 409-equivalent; NO record written")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        sq.cap(store, e, g, "K")
        expect_raises(rcs.IdempotencyConflict,
                      lambda: store.capture_observation(observer_id="owner", entity=e, event=g,
                                                        thesis="CHANGED", sources=sq.SOURCES,
                                                        idempotency_key="K"),
                      "a changed payload under the same key conflicts")
        check(n_obs(store) == 1 and n_idem(store) == 1, "the conflict wrote no new record or binding")
        store.close()


# 5 =========================================================================
def test_two_observers_same_token():
    print("\n[5] two observers may reuse the same opaque token -> independent records")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        ra, _ = sq.cap(store, e, g, "TOKEN", observer="observerA")
        rb, _ = sq.cap(store, e, g, "TOKEN", observer="observerB")
        check(ra["id"] != rb["id"] and ra["status"] == "recorded" and rb["status"] == "recorded",
              "scope includes observer_id -> two distinct observations")
        check(n_obs(store) == 2 and n_idem(store) == 2, "two observations + two bindings")
        store.close()


# 6 =========================================================================
def test_db_rejects_mismatch():
    print("\n[6] the DB rejects mismatched (seq/kind/id) FK, observer, and non-observation kind")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        _, o = sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K")
        seq = store.conn.execute("SELECT record_seq FROM observation_private WHERE observation_id=?",
                                 (o.observation_id,)).fetchone()[0]
        # (a) composite FK: a bound_record_seq with no record_registry row
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO idempotency_registry VALUES ('observation','owner','ka','%s',999999,'x',?)"
            % ("0" * 64), ("2026-10-31T00:00:00+00:00",)),
            "a registry row whose (seq,kind,id) is not in record_registry -> FK error")
        # (b) observer-bind trigger: correct (seq,id) but a different observer
        expect_raises(sqlite3.Error, lambda: store.conn.execute(
            "INSERT INTO idempotency_registry VALUES ('observation','SOMEONE_ELSE','kb',?,?,?,?)",
            ("0" * 64, seq, o.observation_id, "2026-10-31T00:00:00+00:00")),
            "a registry row whose observer != observation_private.observer -> trigger abort")
        # (c) CHECK: record_kind other than 'observation'
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO idempotency_registry VALUES ('candidate','owner','kc',?,?,?,?)",
            ("0" * 64, seq, o.observation_id, "2026-10-31T00:00:00+00:00")),
            "record_kind != 'observation' -> CHECK abort")
        store.close()


# 7 =========================================================================
def test_no_observation_supersession():
    print("\n[7] no observation-supersession path; a new key makes a DISTINCT observation")
    check("supersedes" not in rc.UserObservation.__dataclass_fields__,
          "UserObservation exposes no 'supersedes' field")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        e, g = sq.ent("p", "P"), sq.ev("g")
        r1, _ = sq.cap(store, e, g, "K1")
        r2, _ = sq.cap(store, e, g, "K2")      # same intent, new key -> a new, independent observation
        check(r1["id"] != r2["id"] and n_obs(store) == 2, "a new key is a distinct observation, not a correction")
        store.close()


# 8 =========================================================================
def test_invisible_field_rejection():
    print("\n[8] capture + fingerprint take NO category/sub_label (deferred candidate fields)")
    cap_params = set(inspect.signature(rcs.ResearchCandidateStore.capture_observation).parameters)
    check("category" not in cap_params and "sub_label" not in cap_params,
          "capture_observation has no category/sub_label parameters")
    fp_params = set(inspect.signature(rcs._request_fingerprint).parameters)
    check("category" not in fp_params and "sub_label" not in fp_params,
          "the fingerprint excludes category/sub_label")


# 9 =========================================================================
def test_no_cleartext_pii():
    print("\n[9] the registry stores an opaque key, a digest, ids + a timestamp — no email/thesis")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K", observer="pseudo-uuid-123",
               thesis="SECRET_THESIS_TEXT")
        row = dict(store.conn.execute("SELECT * FROM idempotency_registry").fetchone())
        blob = "||".join(str(v) for v in row.values())
        check("SECRET_THESIS_TEXT" not in blob, "no cleartext thesis in the registry row")
        check("@" not in row["observer_id"] and row["observer_id"] == "pseudo-uuid-123",
              "observer_id is the pseudonymous account id, never an email")
        check(len(row["request_fingerprint"]) == 64 and all(c in "0123456789abcdef"
              for c in row["request_fingerprint"]), "request_fingerprint is a 64-hex digest")
        store.close()


# 10 ========================================================================
def test_write_once_and_v3_gate():
    print("\n[10] the registry is write-once; a v2 store is rejected with no migration/mutation")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K")
        expect_raises(sqlite3.Error,
                      lambda: store.conn.execute("UPDATE idempotency_registry SET idempotency_key='z'"),
                      "UPDATE on the registry aborts")
        expect_raises(sqlite3.Error, lambda: store.conn.execute("DELETE FROM idempotency_registry"),
                      "DELETE on the registry aborts")
        store.close()
    with tmp() as d:
        path = os.path.join(d, "r.db")
        mk(path).close()
        raw = sqlite3.connect(path)
        raw.execute("UPDATE schema_meta SET version=2 WHERE id=1")
        raw.commit()
        before = [r[0] for r in raw.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        raw.close()
        expect_raises(rcs.SchemaVersionError, lambda: mk(path), "a v2 store is rejected (no migration)")
        raw2 = sqlite3.connect(path)
        after = [r[0] for r in raw2.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql")]
        v = raw2.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        raw2.close()
        check(before == after and v == 2, "the rejected v2 open mutated nothing")


# 11 ========================================================================
def test_concurrency_one_record():
    print("\n[11] two GENUINELY concurrent connections (barrier) race one scope/key/fingerprint")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        mk(path).close()                      # create the schema once (no create-race between workers)
        barrier = threading.Barrier(2)
        results, errors = {}, {}

        def worker(name):
            try:
                st = mk(path)                 # own connection, opened in this thread
                try:
                    barrier.wait(timeout=10)  # both threads call capture at the same instant
                    results[name] = st.capture_observation(
                        observer_id="owner", entity=sq.ent("p", "P"), event=sq.ev("g"),
                        thesis=sq.THESIS, sources=sq.SOURCES, idempotency_key="K")
                finally:
                    st.close()
            except Exception as ex:  # noqa: BLE001
                errors[name] = f"{type(ex).__name__}: {ex}"

        ta, tb = threading.Thread(target=worker, args=("a",)), threading.Thread(target=worker, args=("b",))
        ta.start(); tb.start(); ta.join(); tb.join()
        check(not errors, f"no worker errored ({errors})")
        if len(results) == 2:
            ra, rb = results["a"], results["b"]
            check(sorted([ra["status"], rb["status"]]) == ["noop", "recorded"],
                  "exactly one caller recorded and the other no-oped")
            check(ra["id"] == rb["id"] and ra["record_seq"] == rb["record_seq"],
                  "both callers return the identical bound id + sequence")
        v = mk(path)
        check(n_obs(v) == 1 and n_idem(v) == 1, "exactly one observation + one binding after the race")
        check(max_res(v) == 1, "exactly one reservation was consumed (the no-op consumed none)")
        v.close()


# 12 ========================================================================
def test_unbound_observation_fails_closed():
    print("\n[12] a direct-SQL observation with no registry binding fails closed on reopen")
    with tmp() as d:
        path = os.path.join(d, "r.db")
        store = mk(path)
        sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K")             # one properly bound observation
        store._begin()
        try:
            seq = store._reserve_seq_in_txn()
            now = datetime.now(UTC)
            ghost = rc.UserObservation(observation_id="ghost", observer="owner",
                                       entity=sq.ent("pg", "PG"), event=sq.ev("gg"), thesis="t",
                                       observed_at=now, bk_captured=now, record_seq=seq, sources=())
            store._insert_observation_in_txn(ghost)                  # record + registry, but NO idempotency row
            store.conn.execute("COMMIT")
        except Exception:
            store.conn.execute("ROLLBACK")
            raise
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: mk(path),
                      "an observation with no idempotency binding disables the store on reopen")


# 13 ========================================================================
def test_two_keys_one_observation():
    print("\n[13] a second binding for one observation -> UNIQUE(bound_record_seq) violation")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        _, o = sq.cap(store, sq.ent("p", "P"), sq.ev("g"), "K")
        seq = store.conn.execute("SELECT record_seq FROM observation_private WHERE observation_id=?",
                                 (o.observation_id,)).fetchone()[0]
        expect_raises(sqlite3.IntegrityError, lambda: store.conn.execute(
            "INSERT INTO idempotency_registry VALUES ('observation','owner','OTHER',?,?,?,?)",
            ("0" * 64, seq, o.observation_id, "2026-10-31T00:00:00+00:00")),
            "a second key binding the same observation seq -> UNIQUE(bound_record_seq) violation")
        store.close()


# 14 ========================================================================
def test_legacy_key_scope():
    print("\n[14] v3 drops observation_private.idempotency_key ONLY; others keep theirs")
    with tmp() as d:
        store = mk(os.path.join(d, "r.db"))
        def cols(t):
            return {r["name"] for r in store.conn.execute(f"PRAGMA table_info({t})")}
        check("idempotency_key" not in cols("observation_private"),
              "observation_private has NO idempotency_key column in v3")
        for t in ("research_candidate", "candidate_outcome", "evaluated_finding"):
            check("idempotency_key" in cols(t), f"{t} keeps its idempotency_key column unchanged")
        store.close()


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE — IDEMPOTENCY REGISTRY (schema v3) — 14 adversarial cases")
    print("=" * 80)
    for t in (test_no_nested_transaction, test_exact_retry_true_noop, test_input_coercion_rejected,
              test_canonical_sources_and_nfc_equivalence, test_capture_eligibility_gate,
              test_clocks_and_seq_excluded, test_different_fingerprint_conflicts,
              test_two_observers_same_token, test_db_rejects_mismatch, test_no_observation_supersession,
              test_invisible_field_rejection, test_no_cleartext_pii, test_write_once_and_v3_gate,
              test_concurrency_one_record, test_unbound_observation_fails_closed,
              test_two_keys_one_observation, test_legacy_key_scope):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
