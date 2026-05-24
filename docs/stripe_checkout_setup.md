# Stripe Checkout Setup

Bankroll Kings currently supports a safe demo membership flow and a hosted-link Stripe mode.

## Local Setup

Copy:

- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.example](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.example)

to:

- `C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.local`

Then fill in the real values there. The app now loads `.env` and `.env.local` automatically at startup.

## Required Environment Variables

Set all four checkout URLs:

- `STRIPE_PRO_MONTHLY_URL`
- `STRIPE_PRO_ANNUAL_URL`
- `STRIPE_SHARP_MONTHLY_URL`
- `STRIPE_SHARP_ANNUAL_URL`
- `STRIPE_ELITE_MONTHLY_URL`
- `STRIPE_ELITE_ANNUAL_URL`

Set the billing portal URL:

- `STRIPE_BILLING_PORTAL_URL`

## Modes

- `demo`
  - no checkout URLs configured
  - pricing page clearly says no real charge should be assumed
- `partial`
  - some checkout URLs configured, but not all
  - this is a QC failure state
- `live`
  - all required checkout URLs configured
  - billing portal configured

## Recommended Verification

1. Open [pricing](http://localhost:5000/pricing)
2. Confirm the membership flow status says `Stripe checkout is fully configured.`
3. Click each plan:
   - Pro Monthly
   - Pro Annual
   - Sharp Monthly
   - Sharp Annual
   - Elite Monthly
   - Elite Annual
4. Confirm each redirects to the intended Stripe destination
5. Open `/billing` as a paid user and confirm it redirects to the billing portal

## QC

Run:

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_checkout_readiness.py
```

Expected:

- `demo` -> warning
- `partial` -> failure
- `live` -> clean
