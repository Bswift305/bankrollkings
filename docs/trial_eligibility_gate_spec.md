# Trial Eligibility Gate — Specification (DRAFT v2, not implemented)

**Status: SPECIFICATION ONLY. No code written. Flyers NOT distributed; Casino/Barbershop codes
stay at 25 each. No SMS provider is to be chosen or purchased until this storage/transaction design
is approved.** Requirement: **one lifetime trial per person**, not 25 activations per venue.

**v2 corrects the v1 flaw:** a cross-process file lock over several CSV/user-file writes is **not**
atomic — a crash after the ledger write but before the counter increment or the access grant leaves
inconsistent state. v2 replaces it with a **private transactional SQLite store** and makes the DB
transaction (with UNIQUE constraints) the authority; the user grant is a recoverable projection of
a committed record.

---

## 1. Storage — one private transactional SQLite database

A single private, **untracked** SQLite file (`TRIAL_DB_PATH`, like `INVITE_CODES_PATH`; it holds
redemption records, so it is a secret). This is a **scoped exception** to the app's CSV/JSON model
(CLAUDE.md §6) — justified solely by the atomicity requirement, not a general DB migration. Tables:

- **`codes`** (inventory): `code_id` PK, `venue_label`, `code_token_hmac` (HMAC of the redeemable
  token — the raw token is **not** stored), `trial_days`, `max_redemptions`, `times_redeemed`,
  `active`.
- **`eligibility`** (the durable lifetime keys): `phone_hmac` **UNIQUE**, `email_hmac` **UNIQUE**,
  `account_user_id` **UNIQUE**, `granted_at`, `expires_at`, `code_id`. One row **only** per
  committed successful grant.
- **`redemptions`** (audit of every attempt, granted or denied): `id` PK, `at`, `code_id` (the
  **venue identifier, never the token**), `outcome` (granted|denied), `deny_reason`,
  `activation_state` (committed|activated), `phone_mask`, `email_mask`, `device_hmac`, `ip_hmac`,
  `expire_raw_at` (retention timestamp for the masked/raw-adjacent fields).
- **`overrides`** (audited manual corrections): `at`, `operator`, `reason`, `affected_key`.

**Constraints are the real guarantee** (req 3): `UNIQUE(phone_hmac)`, `UNIQUE(email_hmac)`,
`UNIQUE(account_user_id)` on `eligibility`, and a **`CHECK(times_redeemed <= max_redemptions)`** plus
the conditional UPDATE below on `codes`. Application checks are a convenience; the DB enforces
correctness even under a race.

---

## 2. The atomic redemption transaction (req 2, 3, 4)

Everything that establishes a grant happens in **one SQLite transaction**:

```
BEGIN IMMEDIATE;
  -- eligibility (constraint-backed, not just a SELECT):
  SELECT 1 FROM eligibility WHERE phone_hmac=? OR email_hmac=? OR account_user_id=?;   -> if hit: ROLLBACK, DENY
  -- hard cap, enforced atomically in SQL:
  UPDATE codes SET times_redeemed = times_redeemed + 1
    WHERE code_id=? AND active=1 AND times_redeemed < max_redemptions;                 -> if 0 rows: ROLLBACK, DENY (cap/inactive)
  -- durable keys; UNIQUE catches any racer that passed the SELECT:
  INSERT INTO eligibility(phone_hmac,email_hmac,account_user_id,granted_at,expires_at,code_id) ...; -> UNIQUE violation: ROLLBACK, DENY
  INSERT INTO redemptions(... outcome='granted', activation_state='committed' ...);
COMMIT;
```

- **One successful grant guaranteed:** the UNIQUE constraints + the conditional `UPDATE` make the
  grant and the cap-decrement atomic and race-safe; the SELECT is an early-out, the constraints are
  the guarantee.
- **Access is granted only AFTER commit** (req 4). The user's trial entitlement is **derived from a
  committed `redemptions` row**, not a separate CSV flag that can diverge:
  - After COMMIT, apply the user-facing trial stamp and set `activation_state='activated'` (idempotent).
  - **Recoverable activation:** if the process crashes after COMMIT but before activation, the row
    stays `committed`; on the user's next authenticated request (and via a recovery sweep), a
    `committed`-not-`activated` redemption for that account is re-applied idempotently. A crash
    **before** COMMIT rolls everything back — no code consumed, no eligibility row, no partial grant.
- A **denied** attempt writes a `redemptions` audit row only; it inserts **no** `eligibility` row and
  **decrements no code** (req 6 of the original ask, req 11 here).

---

## 3. Identity keys — keyed HMAC, phone primary (req 5)

Durable keys are stored as **keyed HMACs**, never plain hashes (a plain SHA-256 of a 10-digit phone
or a common email is trivially brute-forced):

- `phone_hmac = HMAC_SHA256(TRIAL_HMAC_KEY, E.164_phone)` — **PRIMARY**, UNIQUE.
- `email_hmac = HMAC_SHA256(TRIAL_HMAC_KEY, normalized_email)` — UNIQUE (normalization documented
  per provider — lowercase/trim, gmail dot/`+tag` folding).
- `account_user_id` — UNIQUE.
- `TRIAL_HMAC_KEY` is a server secret in the prod `.env` (rotating it is a deliberate, documented
  operation — it resets the dedupe space, so it is not rotated casually).

Both phone and email must be **verified** (§5) before they can key an eligibility row.

## 4. Device / IP — secondary risk signals, NOT lifetime keys (req 7)

- `device_hmac` and `ip_hmac` are stored on `redemptions` as **risk signals**, never as UNIQUE
  eligibility keys. A device or IP match **alone never denies** — families and public/shared devices
  are legitimate, and venue Wi-Fi shares one IP.
- They **raise an abuse flag** for owner review (and feed IP **velocity** rate-limiting) only, and
  only matter when they **corroborate** another identity key. IP is time-limited (§6), never an
  automatic lifetime denial.

## 5. Verification + OTP security (req 8, 9, 10)

Both flows — **new-account signup** and the **logged-in free user at `/trial/<code>`** — pass
through the **same** gate: verify email → verify phone (OTP) → eligibility transaction (§2). The
current `/trial/<code>` immediate grant for logged-in free users (`app.py:39557`) is removed; no
path grants a trial before both verifications and a committed redemption.

**OTP security (frozen):** 6-digit code; **expires** in 10 minutes; **max 5 verify attempts** then
lockout; **resend cooldown** (≥30 s) + a daily resend cap; the OTP is stored **HMAC-hashed**, never
plaintext; it is **bound to the session + the account/phone** it was issued for; **rate-limited** per
phone and per IP; and responses are **non-enumerating** ("if that number can receive texts, a code
was sent" — never reveal whether a number/email is already registered or already redeemed).

**SMS is control-of-number, not identity (req 10):** SMS verification proves control of a phone
number at a point in time — not one biological person forever. Numbers can be shared, recycled, or
replaced. It **materially deters** ordinary repeat-trial abuse; it does not guarantee human
uniqueness. The product promise is calibrated to that bar.

## 6. PII minimization + retention (req 6)

- The permanent, lifetime-relevant data is the **HMAC keys** only. Raw phone, normalized email, raw
  IP, and the redeemable token are **not** retained indefinitely.
- `redemptions` keeps minimal **masked display** values (`•••-•••-1234`, `j***@domain`) for owner
  reporting, with an `expire_raw_at` **retention policy** — a scheduled purge nulls the masked/adjacent
  fields after N days, leaving the HMAC keys for lifetime dedupe.
- The **code identifier / venue label** is stored, never the redeemable token (only its HMAC lives on
  `codes` for validation).

## 7. Denial, owner reporting, manual override (req 11)

- **Denial message (frozen):** *"A trial has already been redeemed using this account or verified
  contact information."* — non-enumerating.
- **Only a committed successful grant** creates lifetime ineligibility (req 11). Denied or abandoned
  attempts (failed OTP, bailed flow) write audit rows but **never** an `eligibility` row — they do
  **not** poison a phone or email.
- **Owner reporting:** owner-gated view of `redemptions`/`overrides` — grants, denials by reason,
  device/IP velocity flags, per-code usage.
- **Manual override:** an explicit, authorized-operator action (writes an `overrides` row + the
  `eligibility` adjustment) for legitimate corrections (e.g., a tester who changed phones). Audited;
  never automatic.

## 8. External dependency — deferred until this design is approved

SMS is the primary control and no SMS capability exists. **Provider selection and purchase are
deferred** until this storage/transaction design is approved — otherwise we risk paying for SMS
while the redemption record can still become inconsistent. Twilio Verify remains a reasonable
candidate (purpose-built OTP) to evaluate **after** approval. Email verification runs on the existing
SMTP (`send_email`); email alone is insufficient.

## 9. Tests — concurrency AND crash-recovery (req 12)

Using the SQLite store + a **mocked** OTP/email verifier (real providers in staging before launch):

**Eligibility / uniqueness**
1. Repeat account (new account, same phone/email) → DENY; no code consumed.
2. Repeat email (same normalized email) → DENY.
3. Repeat phone (same E.164) → DENY.
4. New email, **reused phone** → DENY (phone primary; UNIQUE catches it).
5. Shared-IP / shared-device legitimacy: distinct verified phones from one IP/device → all granted
   (flag raised, no block).

**Concurrency**
6. Simultaneous final redemption (two requests for a code's last slot) → exactly one grant, one
   deny; `times_redeemed` increments exactly once (UNIQUE + conditional UPDATE).
7. Simultaneous same-phone from two sessions → exactly one eligibility row (UNIQUE constraint).

**Crash-recovery (partial failure at every transition)**
8. Crash **before COMMIT** (after the conditional UPDATE / after the eligibility INSERT) → full
   rollback: no code consumed, no eligibility row, person still eligible.
9. Crash **after COMMIT, before activation** → redemption is `committed`; recovery idempotently
   activates on next access; no double grant, cap not over-consumed.
10. Crash during the **user-plan projection** write → re-derivable from the committed row; never a
    grant without a committed redemption, never ineligibility without a grant.

**Lifetime semantics**
11. Expired prior trial → DENY (one lifetime trial; expiry never resets eligibility).
12. Denied/abandoned attempt then a later genuine attempt by the same person → the earlier denial
    did **not** create ineligibility; the genuine attempt proceeds.

**Authorized override**
13. Operator override grants/corrects eligibility and is audited (`overrides.operator`).

## 10. Non-goals / boundaries
- Governs the **trial** grant only — no change to paid checkout or founder logic.
- Codes stay `MaxRedemptions=25` for the pilot (the DB cap still bounds inventory).
- No claim of perfect human identity (§5, req 10).
- SQLite is scoped to this gate; it is not a general migration of the CSV/JSON data model.

*End of revised specification (v2). Awaiting approval of the storage/transaction design **before**
choosing or purchasing an SMS provider. Flyers remain undistributed; codes remain at 25.*
