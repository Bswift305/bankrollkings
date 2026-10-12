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
_HKDF_SALT = b"BKtrial/v1/"
_PURPOSES = ("phone", "email", "ip", "device", "codetoken")  # no 'otp' -- provider-managed


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
    def from_env(cls, env_value=None):
        raw = env_value if env_value is not None else os.environ.get("TRIAL_KEY_MASTER", "")
        raw = (raw or "").strip()
        if not raw:
            # dev/test fallback: a deterministic ephemeral key (NEVER used in prod; prod sets the env)
            raw = "dev-only-trial-key-not-for-production"
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return cls({int(k): v for k, v in parsed.items()})
        except (ValueError, TypeError):
            pass
        return cls({1: raw})

    def _derived(self, purpose, version):
        secret = self.versions[int(version)]
        # domain-separated subkey: HMAC(master_version, "BKtrial/<purpose>")
        return hmac.new(secret, _HKDF_SALT + purpose.encode("ascii"), hashlib.sha256).digest()

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
  phone_hmac       TEXT    NOT NULL UNIQUE,
  phone_hmac_ver   INTEGER NOT NULL,
  email_hmac       TEXT    NOT NULL UNIQUE,
  email_hmac_ver   INTEGER NOT NULL,
  account_user_id  TEXT    NOT NULL UNIQUE,
  code_id          INTEGER NOT NULL REFERENCES codes(code_id),
  granted_at       TEXT    NOT NULL,
  expires_at       TEXT    NOT NULL
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
  raw_expire_at    TEXT,
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
  action                  TEXT NOT NULL CHECK (action IN ('repair_activation','correct_identity','owner_comp_external'))
);
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


def _write_denied(conn, code_id, reason, phone_mask, email_mask, device_hmac, ip_hmac, now):
    """Denied audit row, in its OWN transaction -- never touches eligibility or the code counter."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO redemptions(grant_id, at, code_id, account_user_id, eligibility_id, outcome,"
            " deny_reason, activation_state, phone_mask, email_mask, device_hmac, ip_hmac, raw_expire_at)"
            " VALUES (NULL,?,?,NULL,NULL,'denied',?,NULL,?,?,?,?,?)",
            (_iso(now), code_id, reason, phone_mask, email_mask, device_hmac, ip_hmac, None),
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
        return RedeemResult("denied", "invalid_code")
    code_id = code["code_id"]

    phone_hmacs = [h for _v, h in keyring.all_hmacs("phone", phone_e164)]
    email_hmacs = [h for _v, h in keyring.all_hmacs("email", email_norm)]
    cur_phone_h = keyring.hmac("phone", phone_e164)
    cur_email_h = keyring.hmac("email", email_norm)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # eligibility early-out (dual-read all versions + account)
        qmarks_p = ",".join("?" * len(phone_hmacs))
        qmarks_e = ",".join("?" * len(email_hmacs))
        hit = conn.execute(
            f"SELECT 1 FROM eligibility WHERE phone_hmac IN ({qmarks_p}) OR email_hmac IN ({qmarks_e})"
            " OR account_user_id=? LIMIT 1",
            (*phone_hmacs, *email_hmacs, str(account_user_id)),
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
        raw_expire = now + timedelta(days=90)  # masked/risk retention (§7)
        cur2 = conn.execute(
            "INSERT INTO eligibility(phone_hmac,phone_hmac_ver,email_hmac,email_hmac_ver,"
            "account_user_id,code_id,granted_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (cur_phone_h, keyring.current, cur_email_h, keyring.current,
             str(account_user_id), code_id, _iso(now), _iso(expires)),
        )
        eligibility_id = cur2.lastrowid
        grant_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO redemptions(grant_id, at, code_id, account_user_id, eligibility_id, outcome,"
            " deny_reason, activation_state, phone_mask, email_mask, device_hmac, ip_hmac, raw_expire_at)"
            " VALUES (?,?,?,?,?,'granted',NULL,'committed',?,?,?,?,?)",
            (grant_id, _iso(now), code_id, str(account_user_id), eligibility_id,
             phone_mask, email_mask, device_hmac, ip_hmac, _iso(raw_expire)),
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


def activate(conn, account_user_id):
    """Idempotent, recoverable: mark committed grants for this account 'activated' and return the
    grant to project onto the user record. Safe to call repeatedly (recovery after a crash)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT redemption_id, grant_id, eligibility_id FROM redemptions"
            " WHERE outcome='granted' AND activation_state='committed' AND account_user_id=?"
            " ORDER BY redemption_id LIMIT 1",
            (str(account_user_id),),
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        conn.execute("UPDATE redemptions SET activation_state='activated' WHERE redemption_id=?",
                     (row["redemption_id"],))
        conn.execute("COMMIT")
        return {"grant_id": row["grant_id"], "eligibility_id": row["eligibility_id"]}
    except Exception:
        conn.execute("ROLLBACK")
        raise


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
        for tbl, col in (("eligibility", "phone_hmac_ver"), ("eligibility", "email_hmac_ver"),
                         ("codes", "code_token_hmac_ver")):
            for r in conn.execute(f"SELECT DISTINCT {col} AS v FROM {tbl}"):
                if r["v"] is not None:
                    vers.add(int(r["v"]))
        if not keyring.covers_versions(vers):
            return False, "keyring missing a referenced version"
        return True, "ok"
    finally:
        conn.close()
