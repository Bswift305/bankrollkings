# Stripe Checkout Setup

> **Single-plan era (2026-06-12).** Bankroll Kings sells **one paid plan: All Access,
> $19.99/mo, monthly only**, plus a founders promo. The old multi-tier system
> (Pro / Sharp / Elite + six sport passes, 18 payment links) is GONE — any
> `STRIPE_PRO_*`, `STRIPE_SHARP_*`, `STRIPE_ELITE_*`, and `STRIPE_*_PASS_*` env
> vars are **dead** (the app no longer reads them). Source of truth for the model:
> `docs/PROJECT_MAP.md` § "Membership & pricing".

The app supports a safe **demo** membership flow and a hosted-link **Stripe** mode.
If the two All Access URLs below are unset, checkout silently runs in demo mode
(auto-activates, founder logic still works) — so production must have them set.

## The plan

| Plan | Price | Stripe env var | What to build in Stripe |
|---|---|---|---|
| **All Access (standard)** | **$19.99/mo** recurring | `STRIPE_ALL_ACCESS_MONTHLY_URL` | A Payment Link on a $19.99/mo recurring price |
| **All Access (founders)** | **$10/mo for the first 12 months**, then rolls to $19.99 | `STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL` | A Payment Link on the **same** $19.99 price, with a **$9.99-off-for-12-months coupon** attached |

Price points live in code and must match Stripe:
- Standard `monthly_price: 19.99` — `app.py` (`PRICING_TIERS`, the `all_access` entry).
- Founders `FOUNDER_PROMO` in `app.py`: `slots: 100`, `monthly_price: 10`,
  `duration_months: 12`.

## Required environment variables

```
STRIPE_ALL_ACCESS_MONTHLY_URL=          # standard $19.99/mo payment link
STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL=  # same price + founders coupon ($10/mo yr 1)
STRIPE_BILLING_PORTAL_URL=              # hosted billing portal (manage/cancel)
STRIPE_SECRET_KEY=                      # for webhooks / API-backed flows
STRIPE_WEBHOOK_SECRET=                  # signing secret for the activation webhook
```

Optional (future API-backed portal session flow):
- `STRIPE_BILLING_PORTAL_CONFIG_ID` (a `bpc_...` id; not a substitute for the URL)

## Build it on Stripe

1. **Product + standard price** — one product "Bankroll Kings All Access" with a
   recurring **$19.99/month** price.
2. **Standard Payment Link** — a hosted Payment Link on that $19.99 price →
   `STRIPE_ALL_ACCESS_MONTHLY_URL`.
3. **Founders coupon** — a coupon for **$9.99 off, repeating for 12 months**.
   **Set `max_redemptions = 100`** on the coupon. This is the hard backstop against
   concurrent checkouts overshooting the 100-slot cap (`FOUNDER_PROMO['slots']`).
   Slots are also reserved app-side (`FounderOffer=1`) and consumed on activation
   (`IsFounder=1`), but the coupon cap is the money-side guardrail.
4. **Founders Payment Link** — a *second* Payment Link on the **same $19.99 price**,
   with that coupon attached/auto-applied → `STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL`.
5. **Billing portal** — configure the Stripe customer billing portal and paste its
   URL into `STRIPE_BILLING_PORTAL_URL`.

> **Changing the price later:** Stripe prices are immutable. Create a *new* price,
> point a *new* Payment Link at it, swap the env var URL, **and** update the matching
> number in `app.py` (`monthly_price` and/or `FOUNDER_PROMO`) so the displayed
> pricing matches what Stripe charges.

## Where to set the variables

- **Local dev:** copy `.env.example` → `.env.local` and fill in real values. The app
  loads `.env` then `.env.local` at startup.
- **Production (live site):** edit **`/opt/bankrollkings/.env`** on the EC2 box
  (`ssh -i ~/.ssh/bankroll-key.pem ubuntu@32.195.123.245`). The systemd unit
  `bankrollkings.service` loads it via `EnvironmentFile=/opt/bankrollkings/.env`.
  After editing, **restart** the service so gunicorn re-reads the environment:
  ```bash
  sudo systemctl restart bankrollkings
  ```
  (A reload/HUP will NOT pick up env changes — preload_app forks inherit the old
  environment. See PROJECT_MAP § 2.) The two `STRIPE_ALL_ACCESS_*` keys are new in
  the single-plan era — older prod `.env` files predate them and must have them
  added. Dead `STRIPE_PRO_*/SHARP_*/ELITE_*/_PASS_*` keys can be left in place
  (ignored) or cleaned out.

## Modes

- **demo** — neither All Access URL configured. Pricing page makes clear no real
  charge should be assumed; checkout auto-activates.
- **partial** — exactly one of the two URLs set, or a URL still points at a Stripe
  **test** link (`https://buy.stripe.com/test_...`), or the billing portal has only a
  `bpc_...` config id and no URL. **This is a QC failure state.**
- **live** — both All Access URLs configured with production payment links and the
  billing portal URL set.

## Verify

1. Open `/pricing`. Confirm the membership flow status reads
   **"Stripe checkout is fully configured."**
2. Click **Get All Access** → confirm it redirects to the $19.99 Stripe link.
3. Confirm the **founders** call-to-action shows **$10/mo**, a live
   remaining-slot count, and redirects to the founders (coupon) link.
4. Open `/billing` as a paid user → confirm it redirects to the billing portal.

## QC

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_checkout_readiness.py
```

Expected: `demo` → warning, `partial` → failure, `live` → clean. The same check
feeds the Prelaunch Scorecard's "Pricing And Membership Boundary" section.
Founder-flow and plan-access regressions are covered by
`qc_membership_regression.py` and `qc_plan_access_matrix.py`.
