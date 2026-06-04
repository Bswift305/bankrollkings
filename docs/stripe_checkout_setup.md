# Stripe Checkout Setup

Bankroll Kings currently supports a safe demo membership flow and a hosted-link Stripe mode.

## Local Setup

Copy:

- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.example](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.example)

to:

- `C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\.env.local`

Then fill in the real values there. The app now loads `.env` and `.env.local` automatically at startup.

## Required Environment Variables

Set all checkout URLs:

- `STRIPE_PRO_MONTHLY_URL`
- `STRIPE_PRO_ANNUAL_URL`
- `STRIPE_NBA_PASS_MONTHLY_URL`
- `STRIPE_NBA_PASS_ANNUAL_URL`
- `STRIPE_WNBA_PASS_MONTHLY_URL`
- `STRIPE_WNBA_PASS_ANNUAL_URL`
- `STRIPE_MLB_PASS_MONTHLY_URL`
- `STRIPE_MLB_PASS_ANNUAL_URL`
- `STRIPE_NFL_PASS_MONTHLY_URL`
- `STRIPE_NFL_PASS_ANNUAL_URL`
- `STRIPE_CFB_PASS_MONTHLY_URL`
- `STRIPE_CFB_PASS_ANNUAL_URL`
- `STRIPE_CBB_PASS_MONTHLY_URL`
- `STRIPE_CBB_PASS_ANNUAL_URL`
- `STRIPE_SHARP_MONTHLY_URL`
- `STRIPE_SHARP_ANNUAL_URL`
- `STRIPE_ELITE_MONTHLY_URL`
- `STRIPE_ELITE_ANNUAL_URL`

Set the billing portal URL:

- `STRIPE_BILLING_PORTAL_URL`

Optional, for the future API-backed portal session flow:

- `STRIPE_BILLING_PORTAL_CONFIG_ID`

## Modes

- `demo`
  - no checkout URLs configured
  - pricing page clearly says no real charge should be assumed
- `partial`
  - some checkout URLs configured, but not all
  - or some checkout URLs still point to Stripe test links such as `https://buy.stripe.com/test_...`
  - or payment links are configured but the billing portal only has a Stripe `bpc_...` configuration ID and no URL/session flow yet
  - this is a QC failure state
- `live`
  - all required checkout URLs configured with production Stripe payment links
  - billing portal configured

## Launch Link Count

The app expects 18 hosted checkout links:

- 6 single-sport passes x monthly/annual = 12 links
- 3 platform plans x monthly/annual = 6 links

If Stripe only shows the six sport-pass products with monthly and annual prices, the remaining links to create are:

- Bankroll Kings Pro - $29/month
- Bankroll Kings Pro - $299/year
- Bankroll Kings Sharp - $79/month
- Bankroll Kings Sharp - $799/year
- Bankroll Kings Elite - $149/month
- Bankroll Kings Elite - $1,499/year

Paste those production payment links into:

- `STRIPE_PRO_MONTHLY_URL`
- `STRIPE_PRO_ANNUAL_URL`
- `STRIPE_SHARP_MONTHLY_URL`
- `STRIPE_SHARP_ANNUAL_URL`
- `STRIPE_ELITE_MONTHLY_URL`
- `STRIPE_ELITE_ANNUAL_URL`

## Recommended Verification

1. Open [pricing](http://localhost:5000/pricing)
2. Confirm the membership flow status says `Stripe checkout is fully configured.`
3. Click each plan:
   - Pro Monthly
   - Pro Annual
   - NBA Pass Monthly
   - NBA Pass Annual
   - WNBA Pass Monthly
   - WNBA Pass Annual
   - MLB Pass Monthly
   - MLB Pass Annual
   - NFL Pass Monthly
   - NFL Pass Annual
   - CFB Pass Monthly
   - CFB Pass Annual
   - CBB Pass Monthly
   - CBB Pass Annual
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
