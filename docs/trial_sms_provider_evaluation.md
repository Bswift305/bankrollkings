# SMS Provider Evaluation — Trial Eligibility Gate (for approval before purchase)

**Status: EVALUATION ONLY. No account opened, nothing purchased or deployed.** Companion to
`docs/trial_eligibility_gate_spec.md` (architecture approved). Per the ruling, this returns a
recommendation, expected operating cost, required credentials, and the implementation sequence —
for approval **before** any provider is purchased or deployed.

The gate uses SMS to verify **control of a phone number** (the primary identity key). The provider
must deliver an OTP reliably in the US, support rate-limiting/retry, and let us keep responses
**non-enumerating** (§6 of the spec).

---

## 1. Recommendation — Twilio Verify (for the pilot)

**Recommended: Twilio Verify.** Rationale:
- **Purpose-built OTP.** It owns the OTP lifecycle — generation, send, retry, expiry, attempt
  limiting, channel fallback, and fraud signals (Fraud Guard / Verify rate limits) — so we are not
  hand-rolling security-critical OTP logic on raw SMS. That directly serves spec §6 (expiry, attempt
  limit, resend cooldown, rate limits) and lowers the chance of a verification-layer bug.
- **Deliverability + compliance** are managed (sender, retries, carrier handling).
- **Cost is negligible at pilot volume** (§2) — the usual argument against Verify (its per-
  verification platform fee) doesn't bite at 2×25 redemptions.
- Clean API behind a thin adapter, so the gate's verifier stays swappable (mock → Twilio → something
  else) without touching the transaction core.

**Not recommended for the pilot, noted for scale:** building OTP ourselves on **raw SMS** (AWS End
User Messaging/SNS ≈ $0.006/SMS, or **Plivo** — no verification fee, US SMS ≈ $0.0077). These are
cheaper per message but push the entire OTP security surface (expiry, attempt caps, enumeration,
fraud) onto us. Revisit only if trial volume grows enough that Twilio Verify's **$0.05/successful
verification** platform fee dominates (see §2).

---

## 2. Expected operating cost

**Twilio Verify, US SMS (confirm on Twilio's own pricing page before purchase):**
- **~$0.05 per *successful* verification** (platform fee) **+ ~$0.0083 SMS** + ~$0.0035–0.005
  carrier surcharge ≈ **~$0.058–0.062 per successful verification**. Failed attempts incur the SMS/
  channel cost but **not** the $0.05 fee.

**Pilot (2 venues × 25 = 50 legitimate grants max):**
- 50 successful verifications ≈ **~$3**. Add retries + repelled abuse attempts (each ~$0.01 SMS):
  even a few hundred attempts keeps the pilot **well under ~$20 total**. Cost is not a selection
  factor here.

**At scale (future, not the pilot):** the $0.05/verification fee dominates — e.g. ~**$5,800 per
100k** successful verifications. If volume ever approaches that, re-evaluate raw-SMS OTP (AWS End
User Messaging / Plivo) where the per-unit cost is ~$0.006–0.008 with no platform fee.

**One-time / regulatory:** US A2P messaging requires **10DLC brand + campaign registration** (or a
**verified toll-free** number). Expect small registration fees and **lead time** (campaign vetting
can take days). This applies to *any* US SMS provider, not just Twilio.

---

## 3. Required credentials (all secrets → prod `.env` via SSM, never committed)

- **Twilio Account SID** + an **API Key SID/Secret** (preferred over the raw Auth Token).
- A **Verify Service SID** (the configured Verify service).
- A **sending sender**: a phone number (A2P 10DLC-registered) or a **verified toll-free** number.
- **10DLC brand + campaign** (or toll-free verification) completed for the sending number.
- App config: `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`,
  `TWILIO_VERIFY_SERVICE_SID` in the prod `.env` (SSM-managed, like the other provider keys).
- **Independent of the gate's own secrets:** `TRIAL_KEY_MASTER` (the HMAC keyring) and
  `TRIAL_DB_PATH` are ours and are **not** provider credentials.

---

## 4. Implementation sequence (build first, provider second, launch last)

1. **Build the gate with OTP MOCKED** — the full approved spec (SQLite store + DDL with the four
   addenda, atomic transaction, versioned/domain-separated keyring, CSV→SQLite migration path,
   retention purge, fail-closed startup). All **§12 mocked tests green**. *No provider needed.*
2. **Provision Twilio** — account, Verify service, sending number, **10DLC/toll-free registration**;
   load credentials to prod `.env` via SSM. (Start the 10DLC registration early — it has lead time.)
3. **Wire the Twilio Verify adapter** behind the verifier interface (swap the mock) and run
   **real-provider staging tests**: OTP delivery, retry, expiry, attempt-lockout, resend cooldown,
   per-phone/IP rate limits, and non-enumerating responses.
4. **Migration verification** — run the CSV→SQLite migration in staging: counts/labels/25-caps/
   active/flyer-URLs preserved, token never logged/stored in clear, rollback proven.
5. **Production one-device redemption test** — one real end-to-end grant on a single device/number;
   confirm the committed-grant authority, the recoverable activation, and the ledger entry.
6. **Only then unpause flyers.** Until every step passes, flyers stay down and codes stay at 25.

---

## 5. Decision asked of the director
- Approve **Twilio Verify** for the pilot (or direct an alternative).
- Confirm sender choice: **toll-free verified** (simpler, often faster to approve for low volume) vs
  **10DLC** (standard A2P) — recommend **toll-free verified** for a low-volume pilot.
- Approve starting the (free) build in step 1 now; purchase/registration (step 2) begins on your go.

*No account, purchase, or deployment will happen before approval. Flyers remain undistributed; codes
remain at 25.*

Sources: [Twilio Verify pricing & alternatives (2026)](https://www.authgear.com/post/twilio-verify-pricing-and-alternatives), [Best OTP service providers 2026](https://www.authgear.com/post/best-otp-service-providers/), [Twilio Verify — what 100k verifications cost](https://www.engagelab.com/blog/twilio-verify-pricing-what-100-000-verifications-really-cost)
