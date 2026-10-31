"""QC: Research Candidate store backup / restore / validation (SLICE 2C, LOCAL ONLY).

Proves the 2C backup/restore guarantees of `services/research_candidate_store.py`:
  * a consistent `VACUUM INTO` snapshot of a LIVE (WAL) database;
  * full validation (schema version, integrity_check, foreign_key_check, ledger reconciliation,
    hashes, tips, reservations, replay) before accepting a backup OR a restored store;
  * restore ONLY to a new explicit path (never overwrites an existing/live DB);
  * round-trip preservation of records, idempotency, sequence GAPS, current tips, and findings;
  * fail closed on corrupt / truncated / foreign-schema / wrong-version / semantically-inconsistent
    backups, and on validating an empty/nonexistent file.
Reuses the 2B QC fixtures. Temp-dir DBs only; no prod path, flag, route, UI, job, deployment, erasure,
or Decision Journal changes.
"""
import hashlib
import os
import shutil
import sqlite3
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc            # noqa: E402
import services.research_candidate_store as rcs     # noqa: E402
import qc_research_candidate_store as sq            # noqa: E402  (fixtures only; tests are __main__-gated)

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


def seeded_with_gap_and_finding(path):
    """A live store with 2 obs/cand/outcome, a deliberate unclaimed-reservation GAP, and a finding."""
    store, fk = sq.seeded_store(path)
    gap = store.next_seq()                 # reserved, NEVER claimed -> a permanent gap
    summary = rc.summarize_family(fk, store._memory().family_cases(fk))
    store.record_finding(
        rc.evaluate_family(finding_id="f0", endpoint=sq.endpoint(), summary=summary,
                           proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=sq.POST,
                           record_seq=store.next_seq()), idempotency_key="find-0")
    return store, fk, gap


# =========================================================================== A backup + restore round-trip
def test_backup_restore_round_trip():
    print("\n[A] VACUUM INTO backup of a LIVE DB, restore to a NEW path, round-trip preserved")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        restored = os.path.join(d, "restored.db")
        store, fk, gap = seeded_with_gap_and_finding(live)
        c0, out0 = store.load_candidate("c0"), store.current_outcome("c0")
        finding = store.current_finding(fk)
        store.backup(bkp)                                    # consistent snapshot of the live WAL DB
        check(os.path.exists(bkp), "backup snapshot written + accepted (fully validated)")
        rcs.ResearchCandidateStore.restore(bkp, restored)    # restore to a NEW path
        store.close()
        r = rcs.ResearchCandidateStore(restored)
        check(r.load_candidate("c0").content_hash == c0.content_hash, "records preserved (candidate hash)")
        check(r.current_outcome("c0").outcome_id == out0.outcome_id, "current tips preserved (outcome)")
        check(r.current_finding(fk).content_hash == finding.content_hash, "findings preserved")
        res = r.conn.execute("SELECT claimed FROM seq_reservation WHERE record_seq=?", (gap,)).fetchone()
        check(res is not None and int(res["claimed"]) == 0, "the unclaimed-reservation GAP is preserved")
        check(r.next_seq() == gap + 2, "next_seq on the restored store skips the gap (no reissue)")
        noop = r.record_observation(sq.obs("o0", sq.ent("p0", "P0"), sq.ev("g0"), 1), idempotency_key="obs-0")
        check(noop["status"] == "noop", "idempotency preserved (same key+content -> noop) after restore")
        check(r.replay_validate()["candidates"] == 2, "restored store fully replays + reconciles")
        r.close()


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _sidecars(path):
    return [s for s in (path + "-wal", path + "-shm", path + "-journal") if os.path.exists(s)]


# =========================================================================== B atomic no-overwrite publish
def test_never_overwrites():
    print("\n[B] backup + restore publish atomically and NEVER overwrite an existing dest (bytes intact)")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        bkp_digest = _digest(bkp)
        # a pre-existing dest (the race target) is refused by the atomic create-if-absent publish
        expect_raises(rcs.ResearchStoreError, lambda: store.backup(bkp),
                      "backup refuses to overwrite an existing dest (atomic no-overwrite publish)")
        check(_digest(bkp) == bkp_digest, "the existing backup's bytes are untouched after the refused backup")
        existing = os.path.join(d, "occupied.db")
        with open(existing, "wb") as f:
            f.write(b"PRE-EXISTING BYTES")
        occ = _digest(existing)
        expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore.restore(bkp, existing),
                      "restore refuses to overwrite an existing/live DB")
        check(_digest(existing) == occ, "the pre-existing restore target's bytes are untouched")
        check(not _sidecars(existing), "no journal sidecars were created next to the untouched target")
        store.close()


# =========================================================================== B2 read-only validation
def test_validation_is_read_only():
    print("\n[B2] validating a backup is READ-ONLY: creates nothing; bytes/size/mtime/sidecars unchanged")
    with tmp() as d:
        missing = os.path.join(d, "missing.db")
        expect_raises(rcs.SchemaVersionError, lambda: rcs.ResearchCandidateStore.validate_store(missing),
                      "validating a nonexistent path fails closed")
        check(not os.path.exists(missing), "validating a nonexistent path created NOTHING")
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        store.close()
        before = (_digest(bkp), os.path.getsize(bkp), os.stat(bkp).st_mtime_ns, _sidecars(bkp))
        rcs.ResearchCandidateStore.validate_store(bkp)      # a full, read-only validation pass
        after = (_digest(bkp), os.path.getsize(bkp), os.stat(bkp).st_mtime_ns, _sidecars(bkp))
        check(before == after and not _sidecars(bkp),
              "validation left the backup's bytes/size/mtime unchanged and created no sidecars")


# =========================================================================== B3 post-publish validation quarantine
def test_post_publish_validation_quarantines():
    print("\n[B3] a FAILED post-publish validation removes the just-published dest (never a pre-existing one)")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        dest = os.path.join(d, "restored.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        store.close()
        real = rcs.ResearchCandidateStore.validate_store
        state = {"n": 0}

        def flaky(path):
            state["n"] += 1
            if state["n"] >= 2:          # pass the pre-copy backup check; fail the post-publish dest check
                raise rcs.StoreIntegrityError("forced post-publication validation failure")
            return real(path)

        rcs.ResearchCandidateStore.validate_store = staticmethod(flaky)
        try:
            expect_raises(rcs.StoreIntegrityError,
                          lambda: rcs.ResearchCandidateStore.restore(bkp, dest),
                          "a forced post-publication validation failure raises")
        finally:
            rcs.ResearchCandidateStore.validate_store = real
        check(not os.path.exists(dest), "the just-published dest was quarantined (removed) on validation failure")


# =========================================================================== B4 permissions (0600)
def test_permissions():
    print("\n[B4] backup permissions: 0600 enforced on POSIX; best-effort on Windows (ACL limitation)")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        store.close()
        if os.name != "nt":
            check(stat.S_IMODE(os.stat(bkp).st_mode) == 0o600, "backup file is 0600 on POSIX")
        else:
            check(os.path.exists(bkp), "backup exists (0600 is best-effort on Windows ACLs)")


# =========================================================================== B5 directory durability
def test_directory_fsync_after_publish():
    print("\n[B5] the parent directory is fsynced AFTER publication (durable name), not before")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        dest = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        calls = []
        real = rcs._fsync_dir

        def spy(p):
            calls.append((os.path.abspath(p), os.path.exists(dest)))   # record dir + whether dest exists yet
            return real(p)

        rcs._fsync_dir = spy
        try:
            store.backup(dest)
        finally:
            rcs._fsync_dir = real
            store.close()
        check(any(p == os.path.abspath(d) and existed for p, existed in calls),
              "_fsync_dir was invoked on the parent dir AFTER the dest was published (dest already existed)")


def _blow(*_a, **_k):
    raise OSError("forced OS failure")


# =========================================================================== B6 error-path cleanup aggregation
def test_error_path_cleanup_aggregates():
    print("\n[B6] a failed restore where temp+dest cleanup ALSO fail -> one CleanupError naming ALL, chained")
    check(issubclass(rcs.CleanupError, rcs.ResearchStoreError), "CleanupError is a dedicated store error")
    with tmp() as d:
        live, bkp, dest = (os.path.join(d, n) for n in ("live.db", "snap.db", "restored.db"))
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        store.close()
        real_validate = rcs.ResearchCandidateStore.validate_store
        real_rm, real_rp = os.remove, os.replace
        n = {"c": 0}

        def flaky(path):
            n["c"] += 1
            if n["c"] >= 2:                       # pass the pre-copy backup check; fail post-publish dest
                raise rcs.StoreIntegrityError("forced post-publication validation failure")
            return real_validate(path)

        rcs.ResearchCandidateStore.validate_store = staticmethod(flaky)
        rcs.os.remove = _blow                     # force removal AND rename to fail for temp AND dest
        rcs.os.replace = _blow
        try:
            try:
                rcs.ResearchCandidateStore.restore(bkp, dest)
                check(False, "expected CleanupError")
            except rcs.CleanupError as e:
                msg = str(e)
                check(dest in msg, "the aggregated CleanupError names the unsafe destination")
                check(".tmp" in msg, "the aggregated CleanupError also names the unsafe temp copy")
                check(isinstance(e.__cause__, rcs.StoreIntegrityError),
                      "the original operation error is retained as the cause")
            except Exception as e:  # noqa: BLE001
                check(False, f"expected CleanupError, got {type(e).__name__}: {e}")
        finally:
            rcs.ResearchCandidateStore.validate_store = real_validate
            rcs.os.remove, rcs.os.replace = real_rm, real_rp


# =========================================================================== B7 post-link fsync failure (not durable)
def test_post_link_fsync_failure():
    print("\n[B7] post-link dir-fsync failure -> cleanup can't prove durable -> CleanupError names dest+temp")
    real_fsd = rcs._fsync_dir
    try:
        with tmp() as d:
            live, bkp, dest = (os.path.join(d, n) for n in ("live.db", "snap.db", "restored.db"))
            store, _, _ = seeded_with_gap_and_finding(live)   # clean backup with real fsync
            store.backup(bkp)
            store.close()
            rcs._fsync_dir = _blow                            # now every dir-fsync fails
            try:
                rcs.ResearchCandidateStore.restore(bkp, dest)
                check(False, "expected CleanupError")
            except rcs.CleanupError as e:
                check(dest in str(e) and "durable" in str(e).lower(),
                      "CleanupError reports non-durable disposal and names the dest")
                check(isinstance(e.__cause__, OSError), "the original (dir-fsync) error is the cause")
            except Exception as e:  # noqa: BLE001
                check(False, f"expected CleanupError, got {type(e).__name__}: {e}")
            check(not os.path.exists(dest), "the dest was actually removed (just not proven durable)")
    finally:
        rcs._fsync_dir = real_fsd


# =========================================================================== B8 _try_cleanup unit (3 outcomes)
def test_try_cleanup_outcomes():
    print("\n[B8] _try_cleanup: durable-removed vs failed(no-remove/rename) vs failed(not-durable)")
    with tmp() as d:
        p = os.path.join(d, "f.db")
        open(p, "wb").close()
        status, _ = rcs._try_cleanup(p)
        check(status == "removed" and not os.path.exists(p), "a clean removal reports 'removed'")
        open(p, "wb").close()
        real_rm, real_rp = os.remove, os.replace
        rcs.os.remove, rcs.os.replace = _blow, _blow
        try:
            status, detail = rcs._try_cleanup(p)
        finally:
            rcs.os.remove, rcs.os.replace = real_rm, real_rp
        check(status == "failed" and p in detail, "neither remove nor rename -> 'failed' names the path")
        os.remove(p)
        open(p, "wb").close()
        real_fsd = rcs._fsync_dir
        rcs._fsync_dir = _blow
        try:
            status, detail = rcs._try_cleanup(p)
        finally:
            rcs._fsync_dir = real_fsd
        check(status == "failed" and "durable" in detail.lower(),
              "removed-but-dir-sync-failed -> 'failed' (not proven durable)")
        check(not os.path.exists(p), "the file was actually removed")


# =========================================================================== B10 existing-only backup
def test_backup_existing_only():
    print("\n[B10] backup_existing opens an EXISTING store read-only and never initializes one")
    with tmp() as d:
        live, snap = os.path.join(d, "live.db"), os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.close()
        before = _digest(live)                                      # quiescent (post-checkpoint) bytes
        rcs.ResearchCandidateStore.backup_existing(live, snap)      # read-only VACUUM INTO works
        check(os.path.exists(snap), "backup_existing produced a validated snapshot")
        check(_digest(live) == before, "the live store was not mutated by the read-only backup")
        rcs.ResearchCandidateStore.validate_store(snap)             # the snapshot fully validates
        check(True, "the snapshot passes full validation")
    with tmp() as d:
        missing = os.path.join(d, "missing.db")
        out = os.path.join(d, "out.db")
        expect_raises(rcs.SchemaVersionError,
                      lambda: rcs.ResearchCandidateStore.backup_existing(missing, out),
                      "backup_existing on a MISSING live store fails closed (never initializes one)")
        check(not os.path.exists(missing) and not os.path.exists(out),
              "no live or snapshot DB was created by the failed backup")
    with tmp() as d:
        live, out = os.path.join(d, "live.db"), os.path.join(d, "out.db")
        rcs.ResearchCandidateStore(live).close()
        raw = sqlite3.connect(live)
        raw.execute("UPDATE schema_meta SET version=999 WHERE id=1")
        raw.commit()
        raw.close()
        expect_raises(rcs.SchemaVersionError,
                      lambda: rcs.ResearchCandidateStore.backup_existing(live, out),
                      "backup_existing on a WRONG-VERSION live store fails closed")
        check(not os.path.exists(out), "no snapshot produced from a wrong-version live store")


# =========================================================================== C fail closed on bad backups
def test_fail_closed_bad_backups():
    print("\n[C] validation fails closed on corrupt/truncated/foreign/wrong-version/empty backups")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        store.close()

        corrupt = os.path.join(d, "corrupt.db")
        shutil.copyfile(bkp, corrupt)
        sz = os.path.getsize(corrupt)
        with open(corrupt, "r+b") as f:       # overwrite every page past the first -> live b-tree corruption
            f.seek(1024)
            f.write(b"\xff" * (sz - 1024))
        expect_raises((rcs.StoreIntegrityError, sqlite3.DatabaseError),
                      lambda: rcs.ResearchCandidateStore.validate_store(corrupt), "corrupt backup rejected")

        trunc = os.path.join(d, "trunc.db")
        shutil.copyfile(bkp, trunc)
        with open(trunc, "r+b") as f:
            f.truncate(1536)
        expect_raises((rcs.StoreIntegrityError, sqlite3.DatabaseError),
                      lambda: rcs.ResearchCandidateStore.validate_store(trunc), "truncated backup rejected")

        foreign = os.path.join(d, "foreign.db")
        fr = sqlite3.connect(foreign)
        fr.execute("CREATE TABLE junk(x)")
        fr.execute("INSERT INTO junk VALUES (1)")
        fr.commit()
        fr.close()
        expect_raises(rcs.SchemaVersionError,
                      lambda: rcs.ResearchCandidateStore.validate_store(foreign), "foreign-schema backup rejected")

        wrongv = os.path.join(d, "wrongv.db")
        shutil.copyfile(bkp, wrongv)
        w = sqlite3.connect(wrongv)
        w.execute("UPDATE schema_meta SET version=99 WHERE id=1")
        w.commit()
        w.close()
        expect_raises(rcs.SchemaVersionError,
                      lambda: rcs.ResearchCandidateStore.validate_store(wrongv), "wrong-version backup rejected")

        expect_raises(rcs.SchemaVersionError,
                      lambda: rcs.ResearchCandidateStore.validate_store(os.path.join(d, "nope.db")),
                      "an empty/nonexistent file is not a valid store")
        # restore also fails closed on a bad backup (validated FIRST, before any copy)
        expect_raises((rcs.StoreIntegrityError, sqlite3.DatabaseError),
                      lambda: rcs.ResearchCandidateStore.restore(corrupt, os.path.join(d, "out.db")),
                      "restore fails closed on a corrupt backup (no restored file produced)")
        check(not os.path.exists(os.path.join(d, "out.db")), "no restored file left behind after a failed restore")


# =========================================================================== D semantically inconsistent
def test_fail_closed_semantic():
    print("\n[D] a semantically inconsistent backup (tampered content hash) is rejected")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        # tamper: a row that passes bind (registry + claimed reservation) but whose stored hash is wrong
        s = store.next_seq()
        store.conn.execute("INSERT INTO record_registry(record_seq,kind,record_id) VALUES (?, 'observation', 'tamper')", (s,))
        store.conn.execute("UPDATE seq_reservation SET claimed=1 WHERE record_seq=?", (s,))
        base = dict(store.conn.execute("SELECT * FROM observation_private LIMIT 1").fetchone())
        sq.raw_insert(store, "observation_private", base, observation_id="tamper", idempotency_key="tamper-k",
                      record_seq=s, content_hash="TAMPERED")
        store.close()
        expect_raises(rcs.StoreIntegrityError, lambda: rcs.ResearchCandidateStore.validate_store(live),
                      "a tampered (hash-mismatch) store fails validation (would never be accepted as a backup)")


# =========================================================================== E no Decision Journal coupling
def test_no_journal_coupling():
    print("\n[E] 2C adds its own backup/restore — no Decision Journal import or coupling")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "services", "research_candidate_store.py"), encoding="utf-8").read()
    check("decision_journal" not in src and "import decision_journal" not in src,
          "the store module does not import or reference decision_journal")
    for name in ("backup", "restore", "validate_store"):
        check(hasattr(rcs.ResearchCandidateStore, name), f"own {name}() exists on the store")


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE STORE — SLICE 2C QC (backup / restore / validation, local-only)")
    print("=" * 80)
    for t in (test_backup_restore_round_trip, test_never_overwrites, test_validation_is_read_only,
              test_post_publish_validation_quarantines, test_permissions, test_directory_fsync_after_publish,
              test_error_path_cleanup_aggregates, test_post_link_fsync_failure,
              test_try_cleanup_outcomes, test_backup_existing_only, test_fail_closed_bad_backups,
              test_fail_closed_semantic, test_no_journal_coupling):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
