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
        expect(te.Keyring.from_env(env_value="", allow_dev=True) is not None,
               "from_env(allow_dev=True) permits a dev key for tests")

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


def main() -> int:
    issues, notes = run()
    print("=" * 60)
    print("TRIAL ELIGIBILITY GATE QC (core, mocked)")
    print("=" * 60)
    for n in notes:
        print(f"[NOTE] {n}")
    if not issues:
        print("All core gate checks passed.")
        return 0
    for m in issues:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
