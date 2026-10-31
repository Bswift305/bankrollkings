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
import os
import shutil
import sqlite3
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


# =========================================================================== B never overwrite / needs new path
def test_never_overwrites():
    print("\n[B] backup needs a new file; restore never overwrites an existing/live DB")
    with tmp() as d:
        live = os.path.join(d, "live.db")
        bkp = os.path.join(d, "snap.db")
        store, _, _ = seeded_with_gap_and_finding(live)
        store.backup(bkp)
        expect_raises(rcs.ResearchStoreError, lambda: store.backup(bkp),
                      "backup refuses an existing dest (VACUUM INTO needs a new file)")
        expect_raises(rcs.ResearchStoreError, lambda: rcs.ResearchCandidateStore.restore(bkp, live),
                      "restore refuses to overwrite an existing/live DB")
        store.close()


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
    for t in (test_backup_restore_round_trip, test_never_overwrites, test_fail_closed_bad_backups,
              test_fail_closed_semantic, test_no_journal_coupling):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
