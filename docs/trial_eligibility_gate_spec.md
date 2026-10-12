# Trial Eligibility Gate — Specification (v3 + addenda — ARCHITECTURE APPROVED)

**Status: ARCHITECTURE APPROVED (storage + transaction design). Not yet implemented.** Flyers remain
undistributed; Casino/Barbershop codes remain exactly 25 each. SMS-provider **evaluation may begin**
(see `docs/trial_sms_provider_evaluation.md`); purchase/deploy only after that evaluation is
approved. Requirement: **one lifetime trial per person**.

**Four mandatory implementation addenda** (approved; folded into the schema/sections below, marked
**[A1]–[A4]**): (A1) versioned/multi-key code-token lookup; (A2) DB-enforced granted/denied row
invariants; (A3) overrides that cannot issue a second trial; (A4) encrypted keyring backup/restore
with a restore-detection test. No further broad redesign.

---

## 1. Storage schema (complete DDL)

A single private, **untracked** SQLite file at `TRIAL_DB_PATH` (secret; holds redemption records).
Scoped exception to the CSV model (CLAUDE.md §6), justified only by atomicity. Every connection sets
`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000`.

```sql
CREATE TABLE codes (                                    -- venue inventory
  code_id          INTEGER PRIMARY KEY,
  venue_label      TEXT    NOT NULL,
  code_token_hmac  TEXT    NOT NULL UNIQUE,             -- HMAC(domain='codetoken') under code_token_hmac_ver; raw token NEVER stored
  code_token_hmac_ver INTEGER NOT NULL,                 -- [A1] key version; link lookup dual-reads ALL retained code-token versions
  trial_days       INTEGER NOT NULL CHECK (trial_days > 0),
  max_redemptions  INTEGER NOT NULL CHECK (max_redemptions > 0),   -- pilot: 25; zero/unlimited prohibited (§5)
  times_redeemed   INTEGER NOT NULL DEFAULT 0
                     CHECK (times_redeemed >= 0 AND times_redeemed <= max_redemptions),
  active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

CREATE TABLE eligibility (                              -- durable LIFETIME keys; permanent
  eligibility_id   INTEGER PRIMARY KEY,
  phone_hmac       TEXT    NOT NULL UNIQUE,             -- HMAC(domain='phone', E164) under phone_hmac_ver
  phone_hmac_ver   INTEGER NOT NULL,
  email_hmac       TEXT    NOT NULL UNIQUE,             -- HMAC(domain='email', normalized) under email_hmac_ver
  email_hmac_ver   INTEGER NOT NULL,
  account_user_id  TEXT    NOT NULL UNIQUE,
  code_id          INTEGER NOT NULL REFERENCES codes(code_id),
  granted_at       TEXT    NOT NULL,                    -- ISO-8601 UTC
  expires_at       TEXT    NOT NULL
);

CREATE TABLE redemptions (                              -- audit of every attempt + activation state
  redemption_id    INTEGER PRIMARY KEY,
  grant_id         TEXT    UNIQUE,                      -- UUID for granted rows (recovery id); NULL for denied
  at               TEXT    NOT NULL,
  code_id          INTEGER REFERENCES codes(code_id),   -- venue id, NEVER the token
  account_user_id  TEXT,                                -- recovery linkage: which account to activate (§2)
  eligibility_id   INTEGER REFERENCES eligibility(eligibility_id),
  outcome          TEXT    NOT NULL CHECK (outcome IN ('granted','denied')),
  deny_reason      TEXT,
  activation_state TEXT    CHECK (activation_state IN ('committed','activated')),  -- granted rows only
  phone_mask       TEXT, email_mask TEXT,               -- masked display, purged per retention (§7)
  device_hmac      TEXT, ip_hmac    TEXT,               -- risk signals, purged per retention (§4,§7)
  raw_expire_at    TEXT,                                -- when the masked/risk fields are purged
  CHECK (                                               -- [A2] DB-enforced granted/denied invariants
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
CREATE UNIQUE INDEX ux_grant_elig ON redemptions(eligibility_id) WHERE outcome='granted';  -- 1 grant <-> 1 eligibility

CREATE TABLE overrides (                                -- additive, audited; never deletes keys (§11)
  override_id             INTEGER PRIMARY KEY,
  at                      TEXT NOT NULL,
  operator                TEXT NOT NULL,
  reason                  TEXT NOT NULL,
  affected_eligibility_id INTEGER REFERENCES eligibility(eligibility_id),
  action                  TEXT NOT NULL                 -- [A3] no second trial; comps go to a separate entitlement
                            CHECK (action IN ('repair_activation','correct_identity','owner_comp_external'))
);
```

**Constraints are the guarantee** (not app checks): `UNIQUE` on `phone_hmac`, `email_hmac`,
`account_user_id`, `code_token_hmac`, `grant_id`, and the granted↔eligibility index; `CHECK`s for
nonnegative/capped counters, valid `active`, positive caps; `foreign_keys=ON`.

---

## 2. Entitlement authority + recovery linkage (corrections 1, 2)

- **The committed SQLite grant is authoritative.** A user is on a trial iff a `redemptions` row with
  `outcome='granted'` exists for their `account_user_id` whose joined `eligibility.expires_at` is in
  the future. The user-file `TrialExpiresAt`/`TrialInviteCode` is a **compatibility projection**,
  rebuildable from the grant — never an independent source of truth.
- **Recovery linkage:** every granted redemption carries `grant_id` (UNIQUE UUID), `account_user_id`,
  and `eligibility_id` (FK). Recovery = `SELECT ... FROM redemptions WHERE outcome='granted' AND
  activation_state='committed' AND account_user_id=?` → re-apply the user stamp idempotently and set
  `activation_state='activated'`. An access check that finds a committed grant but a missing
  projection recovers it on the spot. No grant exists without a committed row; no ineligibility
  exists without a grant.

---

## 3. The atomic redemption transaction (unchanged architecture)

```
BEGIN IMMEDIATE;
  SELECT 1 FROM eligibility WHERE phone_hmac IN (<all key versions>) OR email_hmac IN (...) OR account_user_id=?;  -- early-out
     -> hit: ROLLBACK, then write a denied audit row in a SEPARATE txn (§10); DENY
  UPDATE codes SET times_redeemed = times_redeemed + 1
    WHERE code_id=? AND active=1 AND times_redeemed < max_redemptions;                 -- 0 rows -> ROLLBACK; denied audit; DENY
  INSERT INTO eligibility(...);                                                         -- UNIQUE catches a racer -> ROLLBACK; denied audit; DENY
  INSERT INTO redemptions(grant_id, account_user_id, eligibility_id, outcome='granted', activation_state='committed', ...);
COMMIT;
-- only AFTER commit: project the user stamp + set activation_state='activated' (idempotent, recoverable per §2)
```

Access is granted only after COMMIT. A crash before COMMIT rolls everything back (no slot, no
eligibility, still eligible); a crash after COMMIT re-activates via §2.

---

## 4. Device / IP — secondary risk signals, never lifetime keys (correction 7 of v2)
`device_hmac` / `ip_hmac` live on `redemptions` only, as abuse flags and IP-velocity inputs. A
device or IP match **alone never denies** (families, shared/public devices, venue Wi-Fi are
legitimate); they only corroborate another identity key or raise an owner-review flag, and they are
**purged on the retention schedule** (§7), never permanent.

---

## 5. Keyed, DOMAIN-SEPARATED, VERSIONED HMACs (corrections 3, 4)

- **Domain separation (correction 4):** one master secret `TRIAL_KEY_MASTER` (prod `.env`); each
  purpose uses its **own derived key** via HKDF: `K_purpose_v = HKDF(TRIAL_KEY_MASTER_v, info=purpose)`
  for `purpose ∈ {phone, email, ip, device, codetoken, otp}`. No two purposes share a namespace;
  phone and email HMACs can never collide or cross-check.
- **Versioning + rotation that NEVER resets eligibility (correction 3):** the keyring retains **all
  versions permanently** (`{v → master_v}`). A lookup for an incoming phone/email computes candidate
  HMACs under **every retained version** and checks `eligibility` against all of them (dual-read), so
  a recipient keyed under v1 stays ineligible forever even after rotating to v2. New rows are written
  under the current version (`phone_hmac_ver`). Rotation = add v+1; **old versions are never
  removed**, and no raw PII is needed because dedupe uses the stored HMAC values across versions. (An
  optional re-HMAC backfill may run only for rows where raw is still transiently available; it is not
  relied upon — dual-read across all versions is the permanent mechanism.) **Rotating the key never
  makes a previous recipient eligible again.**
- **[A1] Code tokens are versioned and multi-key-read the same way.** `codes.code_token_hmac_ver`
  records the version a code was written under; a `/trial/<token>` lookup computes the token HMAC
  under **every retained code-token key version** and matches against `code_token_hmac`. So rotating
  the master key **never invalidates an existing flyer** — the same printed token keeps resolving.

## 6. Verification + OTP security + both flows (v2 §5, retained)
Both the **new-account signup** path and the **logged-in free user at `/trial/<code>`** pass through
the same gate (verify email → verify phone OTP → §3 transaction); the current immediate grant
(`app.py:39557`) is removed. OTP: 6-digit, **10-min expiry**, **max 5 attempts** then lockout,
**resend cooldown ≥30 s** + daily resend cap, stored **HMAC-hashed** (purpose `otp`), **bound to the
session + account/phone**, **rate-limited** per phone and per IP, **non-enumerating** responses. SMS
verifies **control of a phone number, not a human** — numbers can be shared/recycled/replaced; it
deters abuse, not a perfect human identity.

## 7. PII minimization + EXACT retention (corrections 6, 9)
- **Permanent:** the lifetime eligibility HMAC keys (`phone_hmac`, `email_hmac`, `account_user_id`)
  and the `overrides` audit. Nothing reversible is permanent.
- **Purged on schedule** (a daily job nulls/deletes expired fields; never touches `eligibility`):

  | Data | Retention |
  |---|---|
  | Masked contact (`phone_mask`, `email_mask`) | **90 days** |
  | IP / device risk (`ip_hmac`, `device_hmac`) | **30 days** |
  | Denied-attempt audit rows (`outcome='denied'`) | **180 days** |
  | Operational logs (gate activity) | **90 days** |
  | Lifetime eligibility HMAC records | **permanent** |

- **No raw** phone/email/IP or redeemable token is stored: only HMACs + masks. `codes` stores
  `code_token_hmac`, never the token.

## 8. Denial auditing + overrides (corrections 10, 11)
- **Denial (correction 10):** the grant transaction **rolls back** on any deny; the denied-attempt
  audit row is written in a **separate transaction** that touches only `redemptions`
  (`outcome='denied'`, no `eligibility_id`, no `codes` decrement) — a denial never creates
  eligibility or consumes capacity.
- **Overrides (correction 11 + [A3]):** additive and audited (operator identity + exact reason), and
  **narrowly scoped — an override can never issue a second promotional trial** (that would break the
  lifetime rule and collide with the UNIQUE account/identity constraints). The only permitted actions
  are: **`repair_activation`** (re-apply a failed activation/projection for an *already-committed*
  grant — no new eligibility row), **`correct_identity`** (fix incorrectly-associated identity data
  on an existing record), and **`owner_comp_external`** (record an owner-authorized comp via a
  **separate entitlement mechanism**, not the trial path — it grants access outside this gate and
  writes no trial `eligibility` row). Overrides **never delete** original lifetime keys.

## 9. Live-code migration + rollback (correction 7)
One-time migration of the two private CSV codes (`INVITE_CODES_PATH`) into SQLite, preserving the
**same flyer URLs** (same `/trial/<token>` tokens), **venue labels**, **25-use limits**, **current
`TimesRedeemed`**, and **active status**:
1. For each CSV row: compute `code_token_hmac` (purpose `codetoken`, under the current version) —
   **never log or print the raw token** (token-nondisclosure check); insert `codes(venue_label,
   code_token_hmac, code_token_hmac_ver, trial_days, max_redemptions=25, times_redeemed=<current>,
   active)`.
2. **Verify:** row count matches; each flyer token resolves (HMAC lookup finds its row); counts, caps,
   labels, active match the CSV exactly.
3. **Flip authority:** set `TRIAL_STORE=sqlite`; redemption now reads/writes SQLite. The CSV becomes
   a read-only archive and **ceases to be an authority**.
4. **Rollback:** until step 2 passes, the CSV stays authoritative; any failed check reverts
   `TRIAL_STORE` to CSV with no data loss. The raw tokens remain only in the flyers/QR (unchanged);
   migration asserts no token was written to logs or the DB in the clear.

## 10. Database operations — fail closed (correction 12)
- **File permissions:** `0600`, owner-only, private path (`TRIAL_DB_PATH`).
- **Concurrency:** WAL mode; `busy_timeout=5000`; `BEGIN IMMEDIATE` for the redemption write.
- **Integrity:** `foreign_keys=ON` on every connection; `PRAGMA integrity_check` on startup.
- **Backup/restore:** scheduled `sqlite3 .backup` (hot backup) of `TRIAL_DB_PATH` to a private
  location; documented restore; backups carry the same `0600`/secret handling.
- **[A4] Keyring backup/restore (critical):** a restored DB is useless for identity/token matching
  without **every historical HMAC master version**. The **keyring** (all master versions, all
  purpose-derived keys) is backed up **encrypted** (separate secret/KMS, never in plaintext beside
  the DB), versioned alongside each DB backup. Restore **verifies** both the DB `integrity_check`
  **and** that the keyring holds every version referenced by `*_hmac_ver` columns; a restore missing a
  key version **fails closed**. An acceptance test proves an **old recipient stays detectable
  (DENIED) after a full DB + keyring backup→restore** (§12).
- **Corruption + availability — FAIL CLOSED:** a startup check fails closed if the eligibility DB is
  missing, unreadable, or fails `integrity_check`. When the DB is unavailable, the trial endpoint
  **denies all redemptions** (and logs an owner alert) — it must **never** fall back to the old
  ungated grant path. No trial is granted without a healthy authoritative store.

## 11. External dependency — evaluation in progress
Architecture is approved, so **SMS-provider evaluation may begin** (deliverable:
`docs/trial_sms_provider_evaluation.md` — recommendation, operating cost, required credentials,
implementation sequence). **Purchase/deploy only after that evaluation is approved.** Email
verification runs on the existing SMTP; email alone is insufficient.

## 12. Tests
Using the SQLite store + a mocked OTP/email verifier (real providers in staging before launch):

- **Eligibility/uniqueness:** repeat account; repeat email; repeat phone; new email + reused phone;
  shared-IP/shared-device legitimacy (distinct phones → all granted, flag only).
- **Cap semantics (correction 5):** 26th distinct person on a 25-code → DENY; zero/unlimited
  `max_redemptions` rejected by the schema.
- **Concurrency:** simultaneous final redemption → exactly one grant, `times_redeemed` +1 once;
  simultaneous same-phone → exactly one eligibility row (UNIQUE).
- **Crash-recovery (every transition):** crash before COMMIT → full rollback; crash after COMMIT
  before activation → idempotent recovery via `grant_id`/`account_user_id`; crash during projection →
  re-derivable, no double grant, cap not over-consumed.
- **Key rotation (correction 3):** a v1 recipient is still DENIED after rotating to v2 (dual-read);
  new grants written under v2.
- **[A1] Code-token rotation:** after a master rotation, an **existing flyer token still resolves** to
  its code (lookup dual-reads all `code_token_hmac_ver`); a wrong token still fails.
- **[A2] Row invariants:** attempts to insert a malformed granted row (missing `grant_id`/account/
  eligibility/activation, or with a `deny_reason`) and a malformed denied row (with grant/eligibility/
  activation set, or missing `deny_reason`) are **rejected by the DB CHECK**.
- **[A3] Override cannot issue a second trial:** an override never creates a second trial
  `eligibility` row (UNIQUE still holds); `repair_activation` re-applies an existing committed grant;
  `owner_comp_external` grants via the separate entitlement and writes no trial eligibility.
- **[A4] Keyring restore detection:** full DB + encrypted keyring backup→restore, then an old
  recipient is still **DENIED**; a restore missing a key version **fails closed** (no grants).
- **Migration (correction 7):** counts/labels/caps/active/URLs preserved; token never logged/stored
  in clear; rollback restores CSV authority with no loss.
- **Fail-closed (correction 12):** DB unavailable/corrupt → `/trial/<code>` denies all, never grants
  ungated.
- **Denial isolation (correction 10):** a denied attempt consumes no slot and creates no eligibility;
  the audit row is in its own transaction.
- **Override (correction 11):** override is additive + audited; original lifetime keys remain intact.
- **Entitlement authority (corrections 1,2):** committed grant drives access; a wiped user-file
  projection is recovered from the committed grant.

## 13. Launch gate (per the ruling)
Launch requires, in order: **(a)** mocked automated tests (§12) green; **(b)** real-provider
**staging** tests (OTP delivery, retry, rate limits); **(c)** **migration verification** (counts/
labels/caps/active/URLs preserved, token-nondisclosure, rollback proven); **(d)** a **production
one-device redemption test** (one real end-to-end grant). Flyers stay paused until all pass.

## 14. Non-goals / boundaries
Governs the **trial** grant only (no checkout/founder change). Codes stay exactly 25 (pilot).
SQLite is scoped to this gate, not a general migration. No claim of perfect human identity.

*End of specification (v3 + the four approved addenda [A1]–[A4]). Architecture approved;
implementation may begin only with the addenda in the checklist. SMS-provider evaluation is the next
deliverable (no purchase/deploy until it is approved). Flyers remain undistributed; codes remain at
25.*
