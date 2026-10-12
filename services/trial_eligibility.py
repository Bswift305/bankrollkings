"""Trial Eligibility Gate — core store (mocked phase; no live wiring, no provider).

Implements the approved spec (docs/trial_eligibility_gate_spec.md): a private transactional SQLite
store enforcing one-lifetime-trial-per-person, with a versioned domain-separated HMAC keyring,
atomic redemption, recoverable activation, and fail-closed health. The OTP is provider-managed
(Twilio Verify) in production; here a Verifier interface + MockVerifier stand in so the gate is
testable with zero external dependency.

Pure/self-contained: no `app` import. Config comes from env or explicit args:
  TRIAL_DB_PATH    - private sqlite file (default: a data/tracking path)
  TRIAL_KEY_MASTER - keyring: JSON {"1":"secret1","2":"secret2",...} or a bare string (= version 1)

Nothing here changes production behavior; the live /trial route is wired only in the launch phase.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

# --- keyring: versioned, domain-separated ------------------------------------------------
_HKDF_SALT = b"BKtrial/hkdf/v1"
_PURPOSES = ("phone", "email", "ip", "device", "codetoken")  # no 'otp' -- provider-managed
_HASH = hashlib.sha256


def _hkdf(ikm, info, length=32, salt=_HKDF_SALT):
    """RFC 5869 HKDF-SHA256 (extract + expand). Real HKDF, not a single-step HMAC."""
    if isinstance(ikm, str):
        ikm = ikm.encode("utf-8")
    if isinstance(info, str):
        info = info.encode("utf-8")
    prk = hmac.new(salt, ikm, _HASH).digest()                       # extract
    okm, t, i = b"", b"", 0
    while len(okm) < length:                                        # expand
        i += 1
        t = hmac.new(prk, t + info + bytes([i]), _HASH).digest()
        okm += t
    return okm[:length]


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Keyring:
    """All master-secret versions, retained permanently. Per-purpose keys are domain-separated
    (a distinct derived key per purpose), so no two purposes share an HMAC namespace."""

    def __init__(self, versions):
        # versions: {int_version: bytes_secret}
        if not versions:
            raise ValueError("Keyring requires at least one version")
        self.versions = {int(v): (s if isinstance(s, bytes) else str(s).encode("utf-8"))
                         for v, s in versions.items()}
        self.current = max(self.versions)

    @classmethod
    def from_env(cls, env_value=None, allow_dev=False):
        """Load the keyring from TRIAL_KEY_MASTER (JSON {ver:secret} or a bare string = v1).
        FAIL CLOSED: if the secret is absent, raise -- the gate must NEVER run on a silent
        fallback/predictable key in production.

        `allow_dev` is **TEST-FIXTURE ONLY** and application code must never pass it. It is also
        inert unless the test harness explicitly sets `TRIAL_ALLOW_DEV_KEY=1`, so even an accidental
        `allow_dev=True` from app code still fails closed in production."""
        raw = env_value if env_value is not None else os.environ.get("TRIAL_KEY_MASTER", "")
        raw = (raw or "").strip()
        if not raw:
            dev_ok = allow_dev and os.environ.get("TRIAL_ALLOW_DEV_KEY", "").strip() == "1"
            if not dev_ok:
                raise RuntimeError(
                    "TRIAL_KEY_MASTER is not set -- refusing to run the trial gate on a fallback "
                    "key (fail closed). Set the secret in the environment.")
            raw = "dev-only-trial-key-not-for-production"
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return cls({int(k): v for k, v in parsed.items()})
        except (ValueError, TypeError):
            pass
        return cls({1: raw})

    def _derived(self, purpose, version):
        # domain-separated per-purpose key via real HKDF, keyed by the master version secret.
        return _hkdf(self.versions[int(version)], info=b"BKtrial/purpose/" + purpose.encode("ascii"))

    def hmac(self, purpose, value, version=None):
        if purpose not in _PURPOSES:
            raise ValueError(f"unknown purpose {purpose!r}")
        version = self.current if version is None else int(version)
        key = self._derived(purpose, version)
        return hmac.new(key, str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    def all_hmacs(self, purpose, value):
        """(version, hmac) under every retained version -- for dual-read lookups."""
        return [(v, self.hmac(purpose, value, v)) for v in sorted(self.versions)]

    def covers_versions(self, needed_versions):
        return set(int(v) for v in needed_versions).issubset(set(self.versions))


# --- schema ------------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS codes (
  code_id          INTEGER PRIMARY KEY,
  venue_label      TEXT    NOT NULL,
  code_token_hmac  TEXT    NOT NULL UNIQUE,
  code_token_hmac_ver INTEGER NOT NULL,
  trial_days       INTEGER NOT NULL CHECK (trial_days > 0),
  max_redemptions  INTEGER NOT NULL CHECK (max_redemptions > 0),
  times_redeemed   INTEGER NOT NULL DEFAULT 0
                     CHECK (times_redeemed >= 0 AND times_redeemed <= max_redemptions),
  active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);
CREATE TABLE IF NOT EXISTS eligibility (
  eligibility_id   INTEGER PRIMARY KEY,
  account_user_id  TEXT    NOT NULL UNIQUE,
  code_id          INTEGER NOT NULL REFERENCES codes(code_id),
  granted_at       TEXT    NOT NULL,
  expires_at       TEXT    NOT NULL
);
-- Lifetime identity keys are APPEND-ONLY: a correction ADDS a new verified key; originals are
-- never updated or removed, so a replaced phone/email stays searchable and cannot redeem again.
CREATE TABLE IF NOT EXISTS eligibility_keys (
  key_id          INTEGER PRIMARY KEY,
  eligibility_id  INTEGER NOT NULL REFERENCES eligibility(eligibility_id),
  key_type        TEXT    NOT NULL CHECK (key_type IN ('phone','email')),
  key_hmac        TEXT    NOT NULL,
  key_version     INTEGER NOT NULL,
  created_at      TEXT    NOT NULL,
  source          TEXT    NOT NULL CHECK (source IN ('original','correction')),
  UNIQUE(key_type, key_hmac)                     -- one owner per identity; blocks cross-attach + dup races
);
CREATE TABLE IF NOT EXISTS redemptions (
  redemption_id    INTEGER PRIMARY KEY,
  grant_id         TEXT    UNIQUE,
  at               TEXT    NOT NULL,
  code_id          INTEGER REFERENCES codes(code_id),
  account_user_id  TEXT,
  eligibility_id   INTEGER REFERENCES eligibility(eligibility_id),
  outcome          TEXT    NOT NULL CHECK (outcome IN ('granted','denied')),
  deny_reason      TEXT,
  activation_state TEXT    CHECK (activation_state IN ('committed','activated')),
  phone_mask       TEXT, email_mask TEXT,
  device_hmac      TEXT, ip_hmac    TEXT,
  mask_expire_at   TEXT,                           -- masked contact purge boundary (policy: +90d)
  risk_expire_at   TEXT,                           -- IP/device risk purge boundary (policy: +30d)
  CHECK (
    (outcome='granted'
       AND grant_id IS NOT NULL AND account_user_id IS NOT NULL
       AND eligibility_id IS NOT NULL AND activation_state IS NOT NULL
       AND deny_reason IS NULL)
    OR
    (outcome='denied'
       AND grant_id IS NULL AND eligibility_id IS NULL
       AND activation_state IS NULL AND deny_reason IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_grant_elig ON redemptions(eligibility_id) WHERE outcome='granted';
CREATE TABLE IF NOT EXISTS overrides (
  override_id             INTEGER PRIMARY KEY,
  at                      TEXT NOT NULL,
  operator                TEXT NOT NULL,
  reason                  TEXT NOT NULL,
  affected_eligibility_id INTEGER REFERENCES eligibility(eligibility_id),
  action                  TEXT NOT NULL CHECK (action IN ('repair_activation','correct_identity','owner_comp_external')),
  ref                     TEXT    -- idempotency id (e.g. grant_id) so a retry neither duplicates nor loses the audit
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_override_ref ON overrides(action, ref) WHERE ref IS NOT NULL;
"""


def open_conn(path):
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)  # manual txn control
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn):
    conn.executescript(_SCHEMA)


# --- helpers -----------------------------------------------------------------------------
def normalize_email(email):
    """Lowercase + trim universally; dot/+tag folding ONLY for an explicit provider allowlist."""
    e = str(email or "").strip().lower()
    if "@" not in e:
        return e
    local, _, domain = e.partition("@")
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def _mask_phone(e164):
    s = str(e164 or "")
    return ("•••-•••-" + s[-4:]) if len(s) >= 4 else "•••"


def _mask_email(email):
    e = str(email or "")
    local, _, domain = e.partition("@")
    return (local[:1] + "***@" + domain) if domain else "***"


# --- verifier interface (provider-managed OTP; mock for tests) ---------------------------
class Verifier:
    def start_verification(self, phone_e164):  # pragma: no cover - interface
        raise NotImplementedError

    def check_verification(self, phone_e164, code):  # pragma: no cover - interface
        raise NotImplementedError


class MockVerifier(Verifier):
    """Stands in for Twilio Verify in tests. `good_code` passes; everything else fails."""
    def __init__(self, good_code="000000"):
        self.good_code = good_code

    def start_verification(self, phone_e164):
        return {"status": "pending", "sid": "VE_mock_" + uuid.uuid4().hex[:12]}

    def check_verification(self, phone_e164, code):
        return {"status": "approved" if code == self.good_code else "denied"}


# --- code token lookup ([A1] dual-read all versions) -------------------------------------
def find_code_by_token(conn, keyring, token):
    for _v, h in keyring.all_hmacs("codetoken", token):
        row = conn.execute("SELECT * FROM codes WHERE code_token_hmac=?", (h,)).fetchone()
        if row:
            return row
    return None


# --- the atomic redemption ---------------------------------------------------------------
class RedeemResult:
    def __init__(self, outcome, reason=None, grant_id=None, eligibility_id=None, expires_at=None):
        self.outcome = outcome          # 'granted' | 'denied'
        self.reason = reason
        self.grant_id = grant_id
        self.eligibility_id = eligibility_id
        self.expires_at = expires_at

    @property
    def granted(self):
        return self.outcome == "granted"


# Retention policy (spec §7): masked contact 90d, IP/device risk 30d. (Denied-row deletion at
# +180d and ops-log 90d are applied by the purge job from `at`, the authoritative row time.)
MASK_RETENTION_DAYS = 90
RISK_RETENTION_DAYS = 30
DENIED_RETENTION_DAYS = 180


def _write_denied(conn, code_id, reason, phone_mask, email_mask, device_hmac, ip_hmac, now):
    """Denied audit row, in its OWN transaction -- never touches eligibility or the code counter.
    code_id may be NULL (an invalid/unknown code is still audited)."""
    mask_exp = _iso(now + timedelta(days=MASK_RETENTION_DAYS))
    risk_exp = _iso(now + timedelta(days=RISK_RETENTION_DAYS))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO redemptions(grant_id, at, code_id, account_user_id, eligibility_id, outcome,"
            " deny_reason, activation_state, phone_mask, email_mask, device_hmac, ip_hmac,"
            " mask_expire_at, risk_expire_at)"
            " VALUES (NULL,?,?,NULL,NULL,'denied',?,NULL,?,?,?,?,?,?)",
            (_iso(now), code_id, reason, phone_mask, email_mask, device_hmac, ip_hmac, mask_exp, risk_exp),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def attempt_redemption(conn, keyring, *, token, account_user_id, phone_e164, email,
                       device_id=None, ip=None, now=None):
    """One atomic redemption. Caller has already completed email + phone (OTP) verification.
    Returns RedeemResult. On grant, the redemption is committed as activation_state='committed';
    call activate() afterwards (separable so a crash between commit and activation is recoverable).
    """
    now = now or _utcnow()
    email_norm = normalize_email(email)
    phone_mask, email_mask = _mask_phone(phone_e164), _mask_email(email_norm)
    device_hmac = keyring.hmac("device", device_id) if device_id else None
    ip_hmac = keyring.hmac("ip", ip) if ip else None

    code = find_code_by_token(conn, keyring, token)
    if not code:
        _write_denied(conn, None, "invalid_code", phone_mask, email_mask, device_hmac, ip_hmac, now)
        return RedeemResult("denied", "invalid_code")
    code_id = code["code_id"]

    phone_hmacs = [h for _v, h in keyring.all_hmacs("phone", phone_e164)]
    email_hmacs = [h for _v, h in keyring.all_hmacs("email", email_norm)]
    cur_phone_h = keyring.hmac("phone", phone_e164)
    cur_email_h = keyring.hmac("email", email_norm)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # eligibility early-out: search EVERY retained identity key (all versions, incl. corrections)
        # in eligibility_keys, plus the account. The UNIQUE(key_type,key_hmac) below is the guarantee.
        qmarks_p = ",".join("?" * len(phone_hmacs))
        qmarks_e = ",".join("?" * len(email_hmacs))
        hit = conn.execute(
            f"SELECT 1 FROM eligibility_keys WHERE (key_type='phone' AND key_hmac IN ({qmarks_p}))"
            f" OR (key_type='email' AND key_hmac IN ({qmarks_e})) LIMIT 1",
            (*phone_hmacs, *email_hmacs),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM eligibility WHERE account_user_id=? LIMIT 1", (str(account_user_id),)
        ).fetchone()
        if hit:
            conn.execute("ROLLBACK")
            _write_denied(conn, code_id, "already_redeemed", phone_mask, email_mask, device_hmac, ip_hmac, now)
            return RedeemResult("denied", "already_redeemed")

        # hard cap, enforced in SQL (conditional UPDATE)
        cur = conn.execute(
            "UPDATE codes SET times_redeemed = times_redeemed + 1"
            " WHERE code_id=? AND active=1 AND times_redeemed < max_redemptions",
            (code_id,),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            _write_denied(conn, code_id, "code_exhausted_or_inactive", phone_mask, email_mask, device_hmac, ip_hmac, now)
            return RedeemResult("denied", "code_exhausted_or_inactive")

        expires = now + timedelta(days=int(code["trial_days"]))
        mask_exp = _iso(now + timedelta(days=MASK_RETENTION_DAYS))
        risk_exp = _iso(now + timedelta(days=RISK_RETENTION_DAYS))
        cur2 = conn.execute(
            "INSERT INTO eligibility(account_user_id,code_id,granted_at,expires_at) VALUES (?,?,?,?)",
            (str(account_user_id), code_id, _iso(now), _iso(expires)),
        )
        eligibility_id = cur2.lastrowid
        # original identity keys (append-only); UNIQUE(key_type,key_hmac) catches a racer -> deny
        conn.execute(
            "INSERT INTO eligibility_keys(eligibility_id,key_type,key_hmac,key_version,created_at,source)"
            " VALUES (?,?,?,?,?,'original'),(?,?,?,?,?,'original')",
            (eligibility_id, "phone", cur_phone_h, keyring.current, _iso(now),
             eligibility_id, "email", cur_email_h, keyring.current, _iso(now)),
        )
        grant_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO redemptions(grant_id, at, code_id, account_user_id, eligibility_id, outcome,"
            " deny_reason, activation_state, phone_mask, email_mask, device_hmac, ip_hmac,"
            " mask_expire_at, risk_expire_at)"
            " VALUES (?,?,?,?,?,'granted',NULL,'committed',?,?,?,?,?,?)",
            (grant_id, _iso(now), code_id, str(account_user_id), eligibility_id,
             phone_mask, email_mask, device_hmac, ip_hmac, mask_exp, risk_exp),
        )
        conn.execute("COMMIT")
        return RedeemResult("granted", grant_id=grant_id, eligibility_id=eligibility_id,
                            expires_at=_iso(expires))
    except sqlite3.IntegrityError as exc:
        # a racer inserted the same phone/email/account first -> UNIQUE violation -> deny
        conn.execute("ROLLBACK")
        _write_denied(conn, code_id, "already_redeemed", phone_mask, email_mask, device_hmac, ip_hmac, now)
        return RedeemResult("denied", "already_redeemed")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def projection_payload(conn, account_user_id):
    """The complete, unambiguous payload the caller needs to (re)build the user trial stamp from the
    authoritative grant -- so the caller never reconstructs it by guessing: grant_id, redemption_id,
    activation_state, trial_days, expires_at, granted_at, and the code/venue reference (code_id +
    venue_label; the venue id, never the token). Returns None if the account has no granted row."""
    row = conn.execute(
        "SELECT r.grant_id, r.redemption_id, r.activation_state, e.granted_at, e.expires_at,"
        " c.code_id, c.venue_label, c.trial_days"
        " FROM redemptions r JOIN eligibility e ON e.eligibility_id=r.eligibility_id"
        " JOIN codes c ON c.code_id=e.code_id"
        " WHERE r.outcome='granted' AND r.account_user_id=? ORDER BY r.redemption_id DESC LIMIT 1",
        (str(account_user_id),),
    ).fetchone()
    if not row:
        return None
    return {"grant_id": row["grant_id"], "redemption_id": row["redemption_id"],
            "activation_state": row["activation_state"], "account_user_id": str(account_user_id),
            "granted_at": row["granted_at"], "expires_at": row["expires_at"],
            "trial_days": int(row["trial_days"]), "code_id": row["code_id"],
            "venue_label": row["venue_label"], "trial_invite_reference": f"venue:{row['code_id']}"}


def activate(conn, account_user_id, project=None):
    """Recoverable, idempotent. Finds the committed grant for the account, runs `project(payload)`
    (the caller's user-record write) with the FULL projection payload, and marks the row 'activated'
    **only after project() succeeds**. If `project` raises, the row stays 'committed' so a later call
    recovers it. Returns the projection payload (or None if nothing to activate)."""
    payload = projection_payload(conn, account_user_id)
    if not payload or payload["activation_state"] != "committed":
        return None
    if project is not None:
        project(payload)                     # may raise -> we do NOT mark activated (stays committed)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE redemptions SET activation_state='activated'"
            " WHERE redemption_id=? AND activation_state='committed'",
            (payload["redemption_id"],),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    payload["activation_state"] = "activated"
    return payload


def active_grant_for(conn, account_user_id, now=None):
    """Authoritative entitlement: a committed/activated grant whose eligibility hasn't expired."""
    now = now or _utcnow()
    return conn.execute(
        "SELECT r.grant_id, e.expires_at FROM redemptions r JOIN eligibility e"
        " ON e.eligibility_id=r.eligibility_id"
        " WHERE r.outcome='granted' AND r.account_user_id=? AND e.expires_at > ?"
        " ORDER BY r.redemption_id DESC LIMIT 1",
        (str(account_user_id), _iso(now)),
    ).fetchone()


# --- migration: live CSV codes -> SQLite (never logs tokens) -----------------------------
def _parse_active(v):
    return 0 if str(v).strip().lower() in {"0", "false", "no", ""} else 1


def migrate_csv_to_sqlite(conn, keyring, csv_rows):
    """Insert the live venue codes into SQLite, preserving the flyer token (-> same /trial/<token>
    URL), venue label, trial duration, 25-use cap, current redemption count, and active state. The
    raw token is **never logged or returned** -- only its HMAC is stored. Returns a verification dict;
    the caller flips authority to SQLite only when `ok` is True. Idempotent-guard: refuses to run if
    `codes` already has rows (migrate into an empty store)."""
    if conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]:
        return {"ok": False, "inserted": 0, "problems": ["codes table is not empty; refusing to re-migrate"]}
    # ALL rows + verification in ONE transaction: commit only if everything succeeds, else roll back
    # entirely (a partial failure leaves ZERO migrated codes, so the store can be retried cleanly).
    conn.execute("BEGIN IMMEDIATE")
    try:
        for r in csv_rows:
            conn.execute(
                "INSERT INTO codes(venue_label,code_token_hmac,code_token_hmac_ver,trial_days,"
                "max_redemptions,times_redeemed,active) VALUES (?,?,?,?,?,?,?)",
                (str(r["Label"]), keyring.hmac("codetoken", str(r["Code"])), keyring.current,
                 int(r["TrialDays"]), int(r["MaxRedemptions"]), int(r["TimesRedeemed"]),
                 _parse_active(r.get("Active", "1"))),
            )
        # verify within the same txn (our own inserts are visible); reference rows by LABEL, never the token
        problems = []
        for r in csv_rows:
            row = find_code_by_token(conn, keyring, str(r["Code"]))
            if not row:
                problems.append(f"token for '{r['Label']}' did not resolve after migration")
            elif (row["venue_label"] != str(r["Label"])
                  or int(row["max_redemptions"]) != int(r["MaxRedemptions"])
                  or int(row["times_redeemed"]) != int(r["TimesRedeemed"])
                  or int(row["trial_days"]) != int(r["TrialDays"])
                  or int(row["active"]) != _parse_active(r.get("Active", "1"))):
                problems.append(f"field mismatch for '{r['Label']}'")
        if conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0] != len(csv_rows):
            problems.append("row count does not match the source")
        if problems:
            conn.execute("ROLLBACK")
            return {"ok": False, "inserted": 0, "problems": problems}
        conn.execute("COMMIT")
        return {"ok": True, "inserted": len(csv_rows), "count_ok": True, "problems": []}
    except Exception as exc:
        conn.execute("ROLLBACK")
        return {"ok": False, "inserted": 0, "problems": [f"migration failed and rolled back: {type(exc).__name__}"]}


# --- retention purge (eligibility is NEVER deleted) --------------------------------------
def purge_expired(conn, now=None):
    """Enforce the retention policy: null IP/device risk at 30d, null masks at 90d, delete denied
    rows at 180d. Lifetime `eligibility` rows are NEVER touched; granted redemptions are never
    deleted. Returns the counts affected."""
    now = now or _utcnow()
    ni = _iso(now)
    conn.execute("BEGIN IMMEDIATE")
    try:
        # inclusive boundaries: at exactly the frozen 30/90/180-day mark the record is purged.
        risk = conn.execute(
            "UPDATE redemptions SET device_hmac=NULL, ip_hmac=NULL"
            " WHERE risk_expire_at IS NOT NULL AND risk_expire_at <= ?"
            " AND (device_hmac IS NOT NULL OR ip_hmac IS NOT NULL)", (ni,)).rowcount
        masks = conn.execute(
            "UPDATE redemptions SET phone_mask=NULL, email_mask=NULL"
            " WHERE mask_expire_at IS NOT NULL AND mask_expire_at <= ?"
            " AND (phone_mask IS NOT NULL OR email_mask IS NOT NULL)", (ni,)).rowcount
        cutoff = _iso(now - timedelta(days=DENIED_RETENTION_DAYS))
        denied = conn.execute(
            "DELETE FROM redemptions WHERE outcome='denied' AND at <= ?", (cutoff,)).rowcount
        conn.execute("COMMIT")
        return {"risk_nulled": risk, "masks_nulled": masks, "denied_deleted": denied}
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- overrides: additive, audited, never a second trial ---------------------------------
OVERRIDE_ACTIONS = ("repair_activation", "correct_identity", "owner_comp_external")


def _audit_override(conn, now, operator, reason, affected_eligibility_id, action, ref, idempotent=False):
    verb = "INSERT OR IGNORE INTO" if idempotent else "INSERT INTO"
    conn.execute(
        f"{verb} overrides(at, operator, reason, affected_eligibility_id, action, ref)"
        " VALUES (?,?,?,?,?,?)",
        (_iso(now), str(operator), str(reason), affected_eligibility_id, action, ref),
    )


def apply_override(conn, operator, reason, action, *, account_user_id=None,
                   affected_eligibility_id=None, keyring=None, correct=None, project=None, now=None):
    """Audited, additive override. It can **never** create a second trial eligibility row. `keyring`
    is an explicit argument (not hidden in `correct`).
    - `repair_activation`: re-run activate() (projection repair; no new eligibility). Idempotent and
      recoverable: the audit is keyed by the grant_id (`ref`), so a retry neither duplicates nor
      loses the audit.
    - `correct_identity`: fix identity on an EXISTING eligibility row (`correct` = {'phone_e164':..}
      and/or {'email':..}, at least one), recomputing the HMAC under the current version. The update
      AND its audit commit in **one transaction** (no unaudited correction on a crash).
    - `owner_comp_external`: record an owner comp handled by a SEPARATE entitlement mechanism;
      writes no trial eligibility.
    """
    if action not in OVERRIDE_ACTIONS:
        raise ValueError(f"override action must be one of {OVERRIDE_ACTIONS}")
    if not str(operator).strip() or not str(reason).strip():
        raise ValueError("override requires a non-empty operator and reason")
    now = now or _utcnow()
    result = {"action": action}

    if action == "repair_activation":
        # Reject when there is no committed OR activated grant to repair -- never audit a repair of
        # nothing (ref must not be NULL).
        pp = projection_payload(conn, account_user_id)
        if not pp:
            raise ValueError("repair_activation: no committed or activated grant found for this account")
        payload = activate(conn, account_user_id, project=project) or pp  # activate() is idempotent
        conn.execute("BEGIN IMMEDIATE")
        try:
            _audit_override(conn, now, operator, reason, affected_eligibility_id, action,
                            pp["grant_id"], idempotent=True)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        result["projection"] = payload
        return result

    if action == "correct_identity":
        if not affected_eligibility_id:
            raise ValueError("correct_identity requires affected_eligibility_id")
        if keyring is None:
            raise ValueError("correct_identity requires an explicit keyring argument")
        if not correct or not any(k in correct for k in ("phone_e164", "email")):
            raise ValueError("correct_identity requires at least one corrected field (phone_e164/email)")
        # APPEND the corrected key(s) + audit in ONE transaction. Originals are never touched, so a
        # replaced phone/email stays searchable. UNIQUE(key_type,key_hmac) rejects attaching an
        # identity already owned by any eligibility (incl. another), and blocks duplicate-key races.
        conn.execute("BEGIN IMMEDIATE")
        try:
            if "phone_e164" in correct:
                conn.execute(
                    "INSERT INTO eligibility_keys(eligibility_id,key_type,key_hmac,key_version,created_at,source)"
                    " VALUES (?,?,?,?,?,'correction')",
                    (affected_eligibility_id, "phone", keyring.hmac("phone", correct["phone_e164"]),
                     keyring.current, _iso(now)))
            if "email" in correct:
                conn.execute(
                    "INSERT INTO eligibility_keys(eligibility_id,key_type,key_hmac,key_version,created_at,source)"
                    " VALUES (?,?,?,?,?,'correction')",
                    (affected_eligibility_id, "email", keyring.hmac("email", normalize_email(correct["email"])),
                     keyring.current, _iso(now)))
            _audit_override(conn, now, operator, reason, affected_eligibility_id, action, None)
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            raise ValueError("correct_identity: that identity is already attached to an eligibility record")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return result

    # owner_comp_external: no trial eligibility; audit only (single txn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        _audit_override(conn, now, operator, reason, affected_eligibility_id, action, None)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    result["external_comp"] = True
    return result


def startup_healthy(path, keyring):
    """Fail-closed health check: the DB must be present, pass integrity_check, and the keyring must
    cover every version referenced by *_hmac_ver. Returns (ok, reason)."""
    if not os.path.exists(path):
        return False, "trial db missing"
    try:
        conn = open_conn(path)
    except Exception as exc:
        return False, f"cannot open: {exc}"
    try:
        ic = conn.execute("PRAGMA integrity_check").fetchone()
        if not ic or str(ic[0]).lower() != "ok":
            return False, "integrity_check failed"
        vers = set()
        for tbl, col in (("eligibility_keys", "key_version"), ("codes", "code_token_hmac_ver")):
            for r in conn.execute(f"SELECT DISTINCT {col} AS v FROM {tbl}"):
                if r["v"] is not None:
                    vers.add(int(r["v"]))
        if not keyring.covers_versions(vers):
            return False, "keyring missing a referenced version"
        return True, "ok"
    finally:
        conn.close()
