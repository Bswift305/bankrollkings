"""QC: Trial Eligibility Gate core (mocked phase). Exercises the SQLite store's one-lifetime-trial
guarantees with zero external dependency. Covers eligibility/uniqueness, hard cap, the atomic
redemption, crash-recovery activation, key rotation (code-token [A1] + phone), DB row invariants
[A2], denial isolation, entitlement authority, and fail-closed keyring health [A4].

Migration, retention purge, and overrides land in a follow-up increment with their own tests.
Exits 0 when all pass.
"""
from __future__ import annotations

import os
import tempfile

from services import trial_eligibility as te


def _mkdb(keyring):
    path = tempfile.mktemp(suffix=".trialdb")
    conn = te.open_conn(path)
    te.init_db(conn)
    return path, conn


def _add_code(conn, keyring, token, label="Casino", days=14, cap=25, active=1):
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO codes(venue_label,code_token_hmac,code_token_hmac_ver,trial_days,max_redemptions,times_redeemed,active)"
        " VALUES (?,?,?,?,?,0,?)",
        (label, keyring.hmac("codetoken", token), keyring.current, days, cap, active),
    )
    conn.execute("COMMIT")


def _person(i):
    return dict(account_user_id=f"u{i}", phone_e164=f"+1555000{i:04d}", email=f"user{i}@example.com")


def run():
    issues, notes = [], []

    def expect(c, m):
        if not c:
            issues.append(m)

    kr = te.Keyring({1: "k-one"})
    path, conn = _mkdb(kr)
    try:
        _add_code(conn, kr, "CASINO01", cap=25)

        # --- eligibility / uniqueness -------------------------------------------------
        r = te.attempt_redemption(conn, kr, token="CASINO01", **_person(1))
        expect(r.granted, "first redemption should grant")
        # repeat account (same everything)
        expect(te.attempt_redemption(conn, kr, token="CASINO01", **_person(1)).reason == "already_redeemed",
               "repeat account -> already_redeemed")
        # repeat email (new account+phone, same email)
        p = _person(2); p["email"] = _person(1)["email"]
        expect(te.attempt_redemption(conn, kr, token="CASINO01", **p).reason == "already_redeemed",
               "repeat email -> already_redeemed")
        # repeat phone (new account+email, same phone)
        p = _person(3); p["phone_e164"] = _person(1)["phone_e164"]
        expect(te.attempt_redemption(conn, kr, token="CASINO01", **p).reason == "already_redeemed",
               "repeat phone -> already_redeemed")
        # genuinely new person grants
        expect(te.attempt_redemption(conn, kr, token="CASINO01", **_person(4)).granted,
               "new person should grant")

        # denial isolation: a denied attempt consumed no slot and created no eligibility
        tr0 = conn.execute("SELECT times_redeemed FROM codes WHERE code_token_hmac=?",
                           (kr.hmac("codetoken", "CASINO01"),)).fetchone()[0]
        te.attempt_redemption(conn, kr, token="CASINO01", **_person(1))  # repeat -> deny
        tr1 = conn.execute("SELECT times_redeemed FROM codes WHERE code_token_hmac=?",
                           (kr.hmac("codetoken", "CASINO01"),)).fetchone()[0]
        expect(tr0 == tr1, "denied attempt must not consume a slot")
        expect(conn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0] == 2,
               "denied attempts must not create eligibility (2 grants so far)")

        # --- hard cap -----------------------------------------------------------------
        path2, conn2 = _mkdb(kr)
        _add_code(conn2, kr, "SMALL", cap=2)
        expect(te.attempt_redemption(conn2, kr, token="SMALL", **_person(10)).granted, "cap: 1st grants")
        expect(te.attempt_redemption(conn2, kr, token="SMALL", **_person(11)).granted, "cap: 2nd grants")
        last = te.attempt_redemption(conn2, kr, token="SMALL", **_person(12))
        expect(last.reason == "code_exhausted_or_inactive", "cap: 3rd (over cap) denied")
        expect(conn2.execute("SELECT times_redeemed FROM codes").fetchone()[0] == 2,
               "cap: counter stays at max")
        conn2.close(); os.remove(path2) if os.path.exists(path2) else None

        # --- crash-recovery: commit without activation, then recover ------------------
        r4 = conn.execute("SELECT activation_state FROM redemptions WHERE account_user_id='u4' AND outcome='granted'").fetchone()[0]
        expect(r4 == "committed", "grant is committed (not yet activated)")
        # simulate a crash after commit, before activation: reopen and recover
        conn.close()
        conn = te.open_conn(path)
        rec = te.activate(conn, "u4")
        expect(rec is not None, "activation recovers a committed grant")
        expect(te.activate(conn, "u4") is None, "activation is idempotent (no double)")
        expect(conn.execute("SELECT activation_state FROM redemptions WHERE account_user_id='u4'").fetchone()[0] == "activated",
               "grant now activated")

        # --- entitlement authority ----------------------------------------------------
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        expect(te.active_grant_for(conn, "u1", now) is not None, "active grant found for u1")
        far = now + timedelta(days=9999)
        expect(te.active_grant_for(conn, "u1", far) is None, "expired grant is not active")

        # --- [A2] row invariants enforced by the DB CHECK -----------------------------
        bad = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO redemptions(grant_id,at,code_id,account_user_id,eligibility_id,outcome,"
                         "deny_reason,activation_state) VALUES (NULL,'t',1,'x',NULL,'granted',NULL,NULL)")
            conn.execute("COMMIT")
        except Exception:
            bad = True
            conn.execute("ROLLBACK")
        expect(bad, "[A2] malformed granted row must be rejected by CHECK")

        # --- [A1] code-token rotation + phone rotation --------------------------------
        kr2 = te.Keyring({1: "k-one", 2: "k-two"})  # rotate: add v2, retain v1
        # existing flyer token (written under v1) still resolves via dual-read
        expect(te.find_code_by_token(conn, kr2, "CASINO01") is not None,
               "[A1] existing flyer token resolves after rotation")
        expect(te.find_code_by_token(conn, kr2, "WRONGTOKEN") is None, "[A1] wrong token still fails")
        # a v1 recipient stays DENIED under the rotated keyring (phone dual-read)
        expect(te.attempt_redemption(conn, kr2, token="CASINO01", **_person(1)).reason == "already_redeemed",
               "[A1] v1 recipient still denied after rotation")

        # --- [A4] fail-closed keyring health ------------------------------------------
        ok, _ = te.startup_healthy(path, kr2)
        expect(ok, "[A4] healthy with a keyring covering all versions")
        # write a grant under v2 so a v2 version is referenced, then check a keyring missing v2
        te.attempt_redemption(conn, kr2, token="CASINO01", **_person(20))
        ok_missing, reason = te.startup_healthy(path, te.Keyring({1: "k-one"}))
        expect(not ok_missing, "[A4] fail-closed when keyring is missing a referenced version")

        # --- missing production key -> fail closed ------------------------------------
        raised = False
        try:
            te.Keyring.from_env(env_value="")
        except RuntimeError:
            raised = True
        expect(raised, "from_env must FAIL CLOSED when the key is absent")
        # allow_dev is inert unless the test-only env flag is set (app code can't accidentally use it)
        raised_without_flag = False
        try:
            os.environ.pop("TRIAL_ALLOW_DEV_KEY", None)
            te.Keyring.from_env(env_value="", allow_dev=True)
        except RuntimeError:
            raised_without_flag = True
        expect(raised_without_flag, "allow_dev=True must still fail closed without TRIAL_ALLOW_DEV_KEY")
        os.environ["TRIAL_ALLOW_DEV_KEY"] = "1"
        try:
            expect(te.Keyring.from_env(env_value="", allow_dev=True) is not None,
                   "from_env(allow_dev=True) + test flag permits a dev key for tests")
        finally:
            os.environ.pop("TRIAL_ALLOW_DEV_KEY", None)

        # --- projection failure -> activation stays 'committed' -----------------------
        te.attempt_redemption(conn, kr, token="CASINO01", **_person(30))
        boom = []
        def _bad_project(_g):
            boom.append(1)
            raise RuntimeError("projection write failed")
        failed = False
        try:
            te.activate(conn, "u30", project=_bad_project)
        except RuntimeError:
            failed = True
        expect(failed and boom, "projection failure propagates")
        st = conn.execute("SELECT activation_state FROM redemptions WHERE account_user_id='u30'").fetchone()[0]
        expect(st == "committed", "activation must stay 'committed' when projection fails (not marked early)")
        ok_proj = te.activate(conn, "u30", project=lambda g: None)
        expect(ok_proj is not None and
               conn.execute("SELECT activation_state FROM redemptions WHERE account_user_id='u30'").fetchone()[0] == "activated",
               "activation completes only after a successful projection")

        # --- retention boundaries match policy (mask 90d / risk 30d) ------------------
        from datetime import datetime as _dt
        row = conn.execute("SELECT at, mask_expire_at, risk_expire_at FROM redemptions WHERE account_user_id='u30' AND outcome='granted'").fetchone()
        _p = lambda s: _dt.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        expect((_p(row["mask_expire_at"]) - _p(row["at"])).days == te.MASK_RETENTION_DAYS, "masked contact retention = 90d")
        expect((_p(row["risk_expire_at"]) - _p(row["at"])).days == te.RISK_RETENTION_DAYS, "IP/device risk retention = 30d")

        # --- invalid-code auditing ----------------------------------------------------
        before = conn.execute("SELECT COUNT(*) FROM redemptions WHERE deny_reason='invalid_code'").fetchone()[0]
        bad = te.attempt_redemption(conn, kr, token="NOPE-NOT-A-CODE", **_person(31))
        expect(bad.reason == "invalid_code", "invalid code -> denied invalid_code")
        audited = conn.execute("SELECT COUNT(*) FROM redemptions WHERE deny_reason='invalid_code' AND code_id IS NULL").fetchone()[0]
        expect(audited == before + 1, "invalid-code attempt is AUDITED with code_id NULL")

        notes.append("eligibility/uniqueness, cap, crash-recovery, entitlement, [A1]/[A2]/[A4], "
                     "denial-isolation, fail-closed-key, projection-failure, retention-boundaries, "
                     "invalid-code-audit checks executed")
    finally:
        conn.close()
        if os.path.exists(path):
            os.remove(path)
    return issues, notes


def check_migration():
    issues = []
    kr = te.Keyring({1: "k-mig"})
    path, conn = _mkdb(kr)
    try:
        rows = [
            {"Code": "CASINO01", "Label": "Casino", "TrialDays": 14, "MaxRedemptions": 25, "TimesRedeemed": 7, "Active": "1"},
            {"Code": "BARBER01", "Label": "Barbershop", "TrialDays": 14, "MaxRedemptions": 25, "TimesRedeemed": 3, "Active": "1"},
        ]
        res = te.migrate_csv_to_sqlite(conn, kr, rows)
        if not res["ok"]:
            issues.append(f"migration not ok: {res.get('problems')}")
        # both flyer tokens still resolve (URLs preserved) with exact fields
        for r in rows:
            c = te.find_code_by_token(conn, kr, r["Code"])
            if not c:
                issues.append(f"migrated token for {r['Label']} does not resolve")
            elif (c["venue_label"] != r["Label"] or int(c["max_redemptions"]) != 25
                  or int(c["times_redeemed"]) != r["TimesRedeemed"] or int(c["trial_days"]) != 14
                  or int(c["active"]) != 1):
                issues.append(f"migrated fields wrong for {r['Label']}")
        # the raw token is not stored anywhere in the clear
        dump = "".join(str(v) for row in conn.execute("SELECT * FROM codes") for v in row)
        if "CASINO01" in dump or "BARBER01" in dump:
            issues.append("raw token leaked into the codes table")
        # re-migration into a non-empty store is refused
        if te.migrate_csv_to_sqlite(conn, kr, rows)["ok"]:
            issues.append("re-migration into a non-empty store should be refused")
    finally:
        conn.close()
        if os.path.exists(path):
            os.remove(path)

    # forced-failure: second row duplicates the first token -> whole migration rolls back -> 0 codes
    path2, conn2 = _mkdb(kr)
    try:
        bad = [
            {"Code": "DUP", "Label": "A", "TrialDays": 14, "MaxRedemptions": 25, "TimesRedeemed": 0, "Active": "1"},
            {"Code": "DUP", "Label": "B", "TrialDays": 14, "MaxRedemptions": 25, "TimesRedeemed": 0, "Active": "1"},
        ]
        res = te.migrate_csv_to_sqlite(conn2, kr, bad)
        if res["ok"]:
            issues.append("migration with a failing row must not report ok")
        if conn2.execute("SELECT COUNT(*) FROM codes").fetchone()[0] != 0:
            issues.append("a failed migration must leave ZERO codes (atomic rollback)")
    finally:
        conn2.close()
        if os.path.exists(path2):
            os.remove(path2)
    return issues


def check_purge():
    from datetime import datetime, timezone, timedelta
    issues = []
    kr = te.Keyring({1: "k-purge"})
    path, conn = _mkdb(kr)
    try:
        _add_code(conn, kr, "C", cap=25)
        now = datetime.now(timezone.utc)
        dd = lambda n: now - timedelta(days=n)
        # risk boundary (30d): exactly 30 -> nulled; 29 -> kept
        te.attempt_redemption(conn, kr, token="C", now=dd(30), device_id="dR30", ip="1.0.0.30", **_person(30))
        te.attempt_redemption(conn, kr, token="C", now=dd(29), device_id="dR29", ip="1.0.0.29", **_person(29))
        # mask boundary (90d): exactly 90 -> nulled; 89 -> kept
        te.attempt_redemption(conn, kr, token="C", now=dd(90), device_id="dM90", ip="1.0.0.90", **_person(90))
        te.attempt_redemption(conn, kr, token="C", now=dd(89), device_id="dM89", ip="1.0.0.89", **_person(89))
        # denied boundary (180d): exactly 180 -> deleted; 179 -> kept
        te.attempt_redemption(conn, kr, token="BAD", now=dd(180), **_person(180))
        te.attempt_redemption(conn, kr, token="BAD", now=dd(179), **_person(179))
        elig_before = conn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0]

        te.purge_expired(conn, now=now)

        def _row(acct):
            return conn.execute("SELECT ip_hmac, device_hmac, phone_mask FROM redemptions WHERE account_user_id=? AND outcome='granted'", (acct,)).fetchone()
        # risk: exactly 30 nulled, mask kept; 29 risk kept
        r30 = _row("u30")
        if r30["ip_hmac"] is not None or r30["device_hmac"] is not None:
            issues.append("purge: risk not nulled at EXACTLY 30d (<= boundary)")
        if r30["phone_mask"] is None:
            issues.append("purge: mask wrongly nulled at 30d")
        if _row("u29")["ip_hmac"] is None:
            issues.append("purge: risk wrongly nulled at 29d (before boundary)")
        # mask: exactly 90 nulled; 89 kept
        if _row("u90")["phone_mask"] is not None:
            issues.append("purge: mask not nulled at EXACTLY 90d (<= boundary)")
        if _row("u89")["phone_mask"] is None:
            issues.append("purge: mask wrongly nulled at 89d (before boundary)")
        # denied rows carry account_user_id=NULL, so identify by timestamp: 180d deleted, 179d kept
        denied_ats = [r["at"] for r in conn.execute("SELECT at FROM redemptions WHERE outcome='denied'").fetchall()]
        if te._iso(dd(180)) in denied_ats:
            issues.append("purge: denied row not deleted at EXACTLY 180d (<= boundary)")
        if te._iso(dd(179)) not in denied_ats:
            issues.append("purge: denied row wrongly deleted at 179d (before boundary)")
        # eligibility NEVER deleted
        if conn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0] != elig_before:
            issues.append("purge: eligibility must never be deleted")
    finally:
        conn.close()
        if os.path.exists(path):
            os.remove(path)
    return issues


def check_overrides():
    import threading
    issues = []
    kr = te.Keyring({1: "k-ovr"})
    path, conn = _mkdb(kr)
    try:
        _add_code(conn, kr, "C", cap=25)
        te.attempt_redemption(conn, kr, token="C", **_person(1))   # u1: phone +15550000001, user1@example.com
        te.attempt_redemption(conn, kr, token="C", **_person(2))   # a second eligibility for cross-attach test
        elig0 = conn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0]
        eid = conn.execute("SELECT eligibility_id FROM eligibility WHERE account_user_id='u1'").fetchone()[0]

        # invalid action rejected
        try:
            te.apply_override(conn, "owner", "x", "grant_free_trial"); issues.append("invalid action should raise")
        except ValueError:
            pass
        # repair_activation idempotent (twice -> one audit); and rejects when no grant exists
        te.apply_override(conn, "owner", "fix", "repair_activation", account_user_id="u1", project=lambda p: None)
        te.apply_override(conn, "owner", "fix2", "repair_activation", account_user_id="u1", project=lambda p: None)
        if conn.execute("SELECT COUNT(*) FROM overrides WHERE action='repair_activation'").fetchone()[0] != 1:
            issues.append("repair_activation audit must be idempotent (one per grant)")
        try:
            te.apply_override(conn, "owner", "nothing", "repair_activation", account_user_id="nobody")
            issues.append("repair_activation with no grant must raise (never audit ref=NULL)")
        except ValueError:
            pass

        # correct_identity APPENDS new phone+email keys (originals untouched)
        te.apply_override(conn, "owner", "changed contacts", "correct_identity",
                          affected_eligibility_id=eid, keyring=kr,
                          correct={"phone_e164": "+15559998888", "email": "corrected1@example.com"})
        # correct_identity requires at least one field
        try:
            te.apply_override(conn, "owner", "noop", "correct_identity", affected_eligibility_id=eid, keyring=kr, correct={})
            issues.append("correct_identity with no field should raise")
        except ValueError:
            pass
        te.apply_override(conn, "owner", "vip comp", "owner_comp_external", account_user_id="u9")

        # invariants: no new eligibility; every override audited (repair=1, correct=1, comp=1)
        if conn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0] != elig0:
            issues.append("override must NEVER create a second trial eligibility row")
        if conn.execute("SELECT COUNT(*) FROM overrides").fetchone()[0] != 3:
            issues.append("every override must be audited")

        # the FIVE required dedupe proofs (original keys never deleted) ----------------
        def _denied(phone, email):
            return te.attempt_redemption(conn, kr, token="C", account_user_id="nu"+phone[-4:], phone_e164=phone, email=email).reason == "already_redeemed"
        if not _denied("+15550000001", "fresh-a@x.com"):
            issues.append("ORIGINAL phone must remain denied after correction")
        if not _denied("+15559998888", "fresh-b@x.com"):
            issues.append("CORRECTED phone must be denied")
        if not _denied("+15557000001", "user1@example.com"):
            issues.append("ORIGINAL email must remain denied after correction")
        if not _denied("+15557000002", "corrected1@example.com"):
            issues.append("CORRECTED email must be denied")

        # a correction cannot attach an identity already owned by ANOTHER eligibility
        eid2 = conn.execute("SELECT eligibility_id FROM eligibility WHERE account_user_id='u2'").fetchone()[0]
        try:
            te.apply_override(conn, "owner", "steal phone", "correct_identity",
                              affected_eligibility_id=eid2, keyring=kr, correct={"phone_e164": "+15550000001"})
            issues.append("correct_identity must reject attaching an identity owned by another eligibility")
        except ValueError:
            pass

        # concurrent corrections of the same new key cannot duplicate it
        before = conn.execute("SELECT COUNT(*) FROM eligibility_keys WHERE key_hmac=?", (kr.hmac("phone", "+15557770000"),)).fetchone()[0]
        results, barrier = [], threading.Barrier(2)
        lock = threading.Lock()
        def _corr():
            c = te.open_conn(path)
            try:
                barrier.wait()
                try:
                    te.apply_override(c, "owner", "race", "correct_identity", affected_eligibility_id=eid, keyring=kr, correct={"phone_e164": "+15557770000"})
                    with lock: results.append("ok")
                except ValueError:
                    with lock: results.append("rejected")
            finally:
                c.close()
        ts = [threading.Thread(target=_corr) for _ in range(2)]
        for t in ts: t.start()
        for t in ts: t.join()
        after = conn.execute("SELECT COUNT(*) FROM eligibility_keys WHERE key_hmac=?", (kr.hmac("phone", "+15557770000"),)).fetchone()[0]
        if after - before != 1 or results.count("ok") != 1:
            issues.append(f"concurrent corrections must add the key exactly once (added={after-before}, results={results})")
    finally:
        conn.close()
        if os.path.exists(path):
            os.remove(path)
    return issues


def check_concurrency():
    """Real races using two independent SQLite connections/threads."""
    import threading
    issues = []

    def _race(setup, attempts):
        kr = te.Keyring({1: "k-conc"})
        path, conn = _mkdb(kr)
        setup(conn, kr)
        conn.close()
        results, barrier = [], threading.Barrier(len(attempts))
        lock = threading.Lock()

        def worker(person_kwargs):
            c = te.open_conn(path)
            try:
                barrier.wait()
                r = te.attempt_redemption(c, kr, token="C", **person_kwargs)
                with lock:
                    results.append(r)
            finally:
                c.close()

        threads = [threading.Thread(target=worker, args=(a,)) for a in attempts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        vconn = te.open_conn(path)
        try:
            granted = sum(1 for r in results if r.granted)
            times = vconn.execute("SELECT times_redeemed FROM codes").fetchone()[0]
            elig = vconn.execute("SELECT COUNT(*) FROM eligibility").fetchone()[0]
        finally:
            vconn.close()
            if os.path.exists(path):
                os.remove(path)
        return granted, times, elig

    # 1) two people competing for the FINAL slot (cap=1)
    g, times, elig = _race(lambda c, k: _add_code(c, k, "C", cap=1),
                           [_person(1), _person(2)])
    if g != 1 or times != 1 or elig != 1:
        issues.append(f"final-slot race: expected exactly one grant/increment, got grants={g} times={times} elig={elig}")

    # 2) two accounts simultaneously using the SAME phone
    p_a = dict(account_user_id="uA", phone_e164="+15551110000", email="a@x.com")
    p_b = dict(account_user_id="uB", phone_e164="+15551110000", email="b@x.com")
    g2, _t2, elig2 = _race(lambda c, k: _add_code(c, k, "C", cap=25), [p_a, p_b])
    if g2 != 1 or elig2 != 1:
        issues.append(f"same-phone race: expected exactly one grant/eligibility, got grants={g2} elig={elig2}")

    return issues


def main() -> int:
    issues, notes = run()
    issues += check_migration()
    issues += check_purge()
    issues += check_overrides()
    issues += check_concurrency()
    print("=" * 60)
    print("TRIAL ELIGIBILITY GATE QC (core + increment, mocked)")
    print("=" * 60)
    for n in notes:
        print(f"[NOTE] {n}")
    print("[NOTE] migration, retention-purge, overrides, and threaded concurrency checks executed")
    if not issues:
        print("All gate checks passed.")
        return 0
    for m in issues:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
