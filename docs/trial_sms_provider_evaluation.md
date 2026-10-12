# SMS Provider Evaluation — Trial Eligibility Gate (corrected)

**Status: EVALUATION, corrected. Provider = Twilio Verify (approved). No account upgraded, nothing
purchased or deployed.** Companion to `docs/trial_eligibility_gate_spec.md` (architecture approved).
The gate uses SMS to verify **control of a phone number** (the primary identity key).

---

## 1. Provider — Twilio Verify (approved)

**Twilio Verify**, used in its standard form:
- **Twilio generates and validates the OTP** (Verify service). We never generate, store, or validate
  the code ourselves — we start a verification and check its status.
- **Managed sender pool.** Verify provides its own managed numbers; **verification-only traffic does
  not require buying a sender or registering an A2P 10DLC campaign** (Twilio directs verification
  traffic through Verify rather than A2P 10DLC). So there is **no toll-free vs 10DLC decision** for
  the baseline integration.
- Twilio's own delivery, retry, and fraud controls **supplement — they do not replace** our
  application-level controls (resend cooldown, daily cap, per-phone/IP velocity limits, and the
  non-enumerating UI in spec §6).

**Trial-account caveat:** a Twilio **trial** account can send verification messages only to
**pre-verified** destination numbers. Sending to arbitrary field testers requires an **upgraded
(paid) account**. This is why production credentials/upgrade are procured only after the mocked gate
and automated tests pass (§4).

---

## 2. Operating cost (official model)

Official US Twilio Verify pricing:
- **$0.05 per *successful* verification** + **$0.0083 per US SMS attempt.**
- **Carrier/tax and other variable fees can apply; they vary and are not quoted here** (confirm the
  exact line items on Twilio's invoice/pricing page — no surcharge figure is invented).
- Failed attempts incur the per-SMS cost but **not** the $0.05 success fee.

**Pilot (2 venues × 25 = 50 successful verifications max):**
- 50 successful one-message verifications ≈ **$2.92** before retries, taxes, and variable fees.
- With retries and repelled abuse attempts, a pilot budget **below ~$20** remains reasonable.

**At scale (future, not the pilot):** the $0.05/verification success fee dominates (e.g. ~$2,500 per
50k successful verifications, before SMS/variable). If volume ever grows that far, re-evaluate then;
it does not affect the pilot.

---

## 3. Required credentials (baseline)

All secrets → prod `.env` via SSM, never committed:
- **`TWILIO_ACCOUNT_SID`**
- **`TWILIO_API_KEY_SID`** + **`TWILIO_API_KEY_SECRET`** (preferred over the raw Auth Token)
- **`TWILIO_VERIFY_SERVICE_SID`** (the configured Verify service)

**Not** baseline credentials: a dedicated sender number, a toll-free number, or a 10DLC brand/
campaign — Verify's managed pool covers the baseline. The gate's own secrets (`TRIAL_KEY_MASTER`
keyring, `TRIAL_DB_PATH`) are ours and are separate from the provider credentials.

---

## 4. Implementation sequence (build mocked first; procure later)

1. **Build the gate with OTP MOCKED** — the full approved spec (SQLite store + DDL with addenda
   [A1]–[A4], atomic transaction, versioned/domain-separated keyring, CSV→SQLite migration path,
   retention purge, fail-closed startup) behind a verifier **interface** whose mock stands in for
   Twilio. All **spec §12 mocked tests green**. *No Twilio account, no credentials, no cost.* — **this
   phase is cleared to begin now.**
2. **Procure Twilio (only after step 1 passes):** create + **upgrade** the account (so it can text
   arbitrary testers), create the Verify service, load the three credentials to prod `.env` via SSM.
3. **Wire the Twilio Verify adapter** (swap the mock) and run **real-provider staging tests**: start-
   verification, check-verification, retry, our resend cooldown + daily cap, per-phone/IP velocity,
   and non-enumerating responses.
4. **Migration verification** — CSV→SQLite in staging: counts/labels/25-caps/active/flyer-URLs
   preserved, token never logged/stored in clear, rollback proven.
5. **Production one-device redemption test** — one real end-to-end grant on a single device/number.
6. **Only then unpause flyers.** Until every step passes, flyers stay down and codes stay at 25.

---

## 5. Decisions / status
- **Twilio Verify** — approved. **No sender/10DLC/toll-free decision** (managed pool).
- **Cleared now:** the free, mocked build + automated tests (step 1).
- **Waits for your go:** account upgrade + production credentials (step 2), real-provider staging,
  migration, prod one-device test, and unpausing flyers.

*No account upgrade, purchase, or deployment before those gates. Flyers undistributed; codes at 25.*

Sources (official Twilio): [Twilio Verify pricing](https://www.twilio.com/en-us/verify/pricing) ·
[Verify API](https://www.twilio.com/docs/verify/api) ·
[Verification API prerequisites](https://www.twilio.com/docs/verify/api/verification) ·
[A2P 10DLC guidance](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
