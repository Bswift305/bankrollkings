# Trial Eligibility Gate — Specification (DRAFT, not implemented)

**Status: SPECIFICATION ONLY. No code written. Flyers NOT distributed; Casino/Barbershop codes
stay at 25 each.** Produced in response to the corrected requirement: **one lifetime trial per
person**, not 25 activations per venue. Return for approval; implementation also waits on one
external decision (the SMS provider, §8).

**The requirement (restated):** a single human may redeem the no-card trial **once, ever**.
Creating another account — new email, deleted-and-recreated account — must **not** yield a second
trial. The venue code cap (`MaxRedemptions=25`) protects total inventory; it does **not** enforce
per-person uniqueness, so public distribution is paused until this gate exists.

---

## 1. Current flow and the gap (grounded in code)

`/trial/<code>` → `trial_redeem()` (`app.py:39545`) validates only `invite_code_redeemable()`
(Active + under the per-code cap), grants `all_access`, and `consume_invite_code()`
(`app.py:10815`) increments `TimesRedeemed`. The invite store
(`INVITE_CODE_COLUMNS = Code, Label, TrialDays, MaxRedemptions, TimesRedeemed, Active`) has **no
per-person dimension**. No email verification, no phone, no device/IP signal, no ledger.

**Consequence:** one person with N emails consumes up to N of a shared code's 25 redemptions. The
cap limits the blast radius to 25; it does not stop repeat-trial abuse by one person.

**What already exists to build on:** transactional email via SMTP (`send_email`, `.env SMTP_*`,
`app.py:568`). **What does not exist:** any SMS/phone capability, any email-verification token
flow, and any `Phone`/`EmailVerified`/`PhoneVerified`/`DeviceId` user fields.

---

## 2. Identity keys — one lifetime trial per each (phone primary)

A redemption is denied if **any** of these already appears in the permanent ledger (§3):

| Key | Normalization | Role |
|---|---|---|
| **Verified phone** (E.164) | digits → E.164; one trial per number | **PRIMARY** — email is too easy to replace |
| **Normalized email** | lowercase, trim, strip dots/`+tags` for gmail-class providers (documented per-provider) | strong secondary |
| **Account** (`UserId`) | the signed-in account | a given account trials once |
| **Device / browser id** | a durable first-party id (§6) | supporting signal |
| **Durable person-eligibility record** | the ledger row joining the above | the system of record |

Phone and email must both be **verified** (§4) before activation. Account and device are
additional keys; IP is a monitoring signal only (§6), never a sole identity test.

---

## 3. The permanent redemption ledger (account-independent)

A single **append-only** store, independent of the Users file, at a private untracked path
(`TRIAL_LEDGER_PATH`, mirroring `INVITE_CODES_PATH` — never committed; contains contact PII, so it
is a secret). **Append-only**: rows are never rewritten or deleted, so deleting or recreating an
account cannot reset eligibility.

Each row (one per redemption **grant**, plus optional denied-attempt audit rows):
`RedeemedAt, PhoneE164, PhoneHash, EmailNorm, EmailHash, UserId, DeviceId, IpHash, Code, TrialDays,
ExpiresAt, Outcome (granted|denied), DenyReason, OverrideBy`.

- Eligibility is checked against **PhoneE164 / EmailNorm / UserId / DeviceId**, never `UserId`
  alone — so a new account with a reused phone or email is caught.
- Store hashes (`PhoneHash`, `EmailHash`, `IpHash`) alongside the values so a future hardening can
  drop the raw PII without losing the dedupe keys.
- Expiry does **not** remove eligibility: a lifetime trial is once-ever, so an **expired** prior
  grant still denies a second (test §9.6).

---

## 4. Verification before activation

- **Email:** a token flow built on the existing SMTP (`send_email`). Account is not trial-eligible
  until the email is confirmed. Buildable now.
- **SMS (primary):** an OTP to the mobile number via an SMS provider. Account is not trial-eligible
  until the phone is confirmed. **Provider-gated — see §8** (no SMS infrastructure exists today).
- Order: verify email → verify phone → eligibility check → atomic redemption (§5). Nothing grants
  a trial before both verifications succeed.

---

## 5. Atomic redemption (one slot, no races)

Eligibility check + code-cap check + ledger insert + counter increment are **one atomic
operation**, under a single lock (a cross-process file lock on the ledger, since storage is
CSV/JSON on one box — not a multi-writer DB):

```
with trial_ledger_lock():            # cross-process; serializes all redemptions
    if ledger_has(phone|email|user|device):   -> DENY (no code consumed)
    if not invite_code_redeemable(code):      -> DENY (cap/inactive; no code consumed)
    append_ledger(granted row)                # permanent
    consume_invite_code(code)                 # increment TimesRedeemed
    grant_trial(user, TrialDays)              # stamp all_access + ExpiresAt
# commit all-or-nothing; a crash mid-way leaves no partial grant
```

- **Simultaneous final redemption:** two requests racing for a code's last slot — the lock
  serializes them; exactly one appends + consumes, the other sees the cap exhausted and is denied
  (test §9.5).
- **Repeat attempt consumes nothing:** a denial for an already-redeemed person does **not**
  increment any code counter (requirement 6).

---

## 6. Secondary abuse signals (supporting, not identity)

- **Device / browser id:** a durable first-party identifier (e.g., a signed httpOnly cookie minted
  on first visit, plus optional client fingerprint), recorded in the ledger and checked as a key.
  Clearable by a determined abuser, hence supporting — not the identity test.
- **IP velocity:** rate-limit redemptions per IP over a window and flag bursts for owner review.
  **Do not hard-block on a shared IP** — casino/barbershop Wi-Fi legitimately shares one IP, so IP
  is a *monitoring + rate-limit* signal that raises a review flag, never an automatic denial of a
  verified phone.

---

## 7. Denial, owner reporting, manual override

- **Denial message (frozen):** *"A trial has already been redeemed using this account or verified
  contact information."* (No detail that would help an abuser enumerate which key matched.)
- **Owner reporting:** an owner-gated view of the ledger — redemptions, denials by reason, IP/device
  velocity flags, per-code usage — for monitoring the pilot.
- **Manual override:** an explicit, authorized-operator action to grant or correct eligibility for a
  legitimate case (e.g., a tester who changed phones), written to the ledger with `OverrideBy` so
  every override is audited. Never automatic.

---

## 8. External dependency — the one decision that gates implementation

**SMS is the primary control and no SMS capability exists in the codebase.** Standing it up
requires a **provider decision + account + API credentials + per-message budget**: e.g. Twilio,
AWS SNS, MessageBird, or Vonage. This is an operator decision + procurement (credentials set in the
prod `.env` via SSM, like the other secrets) — it cannot be chosen or provisioned from code.

- Until a provider is chosen and credentials are live, the gate **cannot** meet "SMS-verified
  mobile required," so it is **not** passable and flyers stay undistributed.
- Email verification runs on the existing SMTP, but email alone is explicitly insufficient (the
  director: "email alone is too easy to replace").

**Recommended provider:** Twilio Verify (purpose-built OTP, handles delivery/retry/fraud, simplest
integration) — but the choice and budget are the director's. Please confirm the provider.

---

## 9. Automated tests (must all pass before the gate is "passed")

Using the ledger + a **mocked** SMS/email verifier (real provider in staging before launch):
1. **Repeat account** — same person, new account, same phone/email → DENY; no code consumed.
2. **Repeat email** — same normalized email, second attempt → DENY.
3. **Repeat phone** — same E.164, second attempt → DENY.
4. **New email, reused phone** — fresh email but a phone already in the ledger → DENY (phone is
   primary).
5. **Simultaneous final redemption** — two concurrent requests for a code's last slot → exactly one
   grant, one deny; `TimesRedeemed` increments exactly once.
6. **Expired prior trial** — a prior grant that has since expired → DENY (one lifetime trial).
7. **Authorized operator override** — an override grants eligibility and is audited (`OverrideBy`).
8. **Shared-IP legitimacy** — multiple distinct verified phones from one IP (venue Wi-Fi) → all
   granted (IP raises a review flag but does not block), while IP velocity still rate-limits bursts.

---

## 10. Phasing

- **Buildable now (for review, pre-SMS):** ledger + account-independent eligibility, atomic
  redemption, email-verification token flow, device-id capture, IP velocity + flags, denial message,
  owner reporting + manual override, and the full test harness with SMS mocked.
- **Gated on §8:** SMS OTP verification (primary control). The gate is **not passable** — and
  flyers stay undistributed — until SMS is live and all §9 tests pass against the real providers in
  staging.

## 11. Non-goals / boundaries
- No change to the paid checkout or founder logic; this governs the **trial** grant only.
- Codes stay at `MaxRedemptions=25` for the pilot (the cap still bounds total inventory).
- No claim of perfect human identity — SMS + a permanent ledger stops *ordinary* repeat-trial abuse
  while preserving the no-card offer; that is the stated bar.

*End of specification. Awaiting approval + the §8 SMS-provider decision before implementation.
Flyers remain undistributed; codes remain at 25.*
