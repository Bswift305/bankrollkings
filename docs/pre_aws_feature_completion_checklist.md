# Pre-AWS Feature Completion Checklist

Last updated: `2026-05-30`

This checklist exists to answer one question:

> What still needs to feel product-complete before we shift energy into AWS?

It is intentionally focused on feature flow, access behavior, UX clarity, and testing. It is **not** the infrastructure checklist.

## Current Snapshot

### Already in a good place

- `SECRET_KEY` now comes from environment configuration.
- Stripe checkout is fully configured in local env and QC reports `live`.
- Shared legal draft pages now exist:
  - `/terms`
  - `/privacy`
  - `/refund-policy`
  - `/responsible-gambling`
- Core sports are live:
  - NBA
  - WNBA
  - MLB
  - NFL
- Sport passes now include:
  - NBA
  - WNBA
  - MLB
  - NFL
  - CFB
  - CBB

### Why we should pause AWS

- The app is still changing quickly at the product layer.
- Access, pricing, and universal navigation just expanded again.
- CFB / CBB passes now exist in pricing, but those user flows still need real validation.
- We should stabilize what the user experiences before hardening where it runs.

## Tier 1: Must Finish Before AWS

### 1. Pass and access validation

Status:
- `Completed on 2026-05-30`

Goal:
- Confirm every new pass unlocks the correct surfaces and only the correct surfaces.

Must verify:
- `NBA Pass` unlocks NBA-only paid surfaces.
- `WNBA Pass` unlocks WNBA-only paid surfaces.
- `MLB Pass` unlocks MLB-only paid surfaces.
- `NFL Pass` unlocks NFL-only paid surfaces.
- `CFB Pass` unlocks `ncaaf` surfaces.
- `CBB Pass` unlocks both:
  - `ncaamb`
  - `ncaawb`

Open work:
- Test route gating for the two new plans:
  - `cfb_pass`
  - `cbb_pass`
- Verify the pricing CTAs, signup flow, checkout flow, and post-checkout redirect all keep the correct plan.

Definition of done:
- A plan-by-plan matrix exists and is tested.
- No pass accidentally gets all-sport access.
- No pass gets blocked from its intended sport.

Completed proof:
- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_plan_access_matrix.py](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_plan_access_matrix.py)
- Result: `70 checks, 0 failures`

### 2. Universal tools flow review

Status:
- `Completed on 2026-05-30`

Goal:
- Make sure the shared tools layer is honest and usable across sports.

Must verify:
- `/tools/props`
- `/tools/market-edge`
- `/tools/matchup-lens`
- `/tools/injuries`
- `/tools/trends`
- `/tools/parlay`

Open work:
- Confirm each tool hub behaves as a true cross-sport selector.
- Confirm each sport handoff lands on the intended page.
- Confirm no universal tool silently falls back to NBA-only behavior.

Definition of done:
- Every universal tool is either truly universal or clearly labeled as a handoff.
- No “looks universal, secretly NBA-only” behavior remains.

Completed proof:
- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_universal_tool_hubs.py](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_universal_tool_hubs.py)
- Result: `16 checks, 0 failures`
- College hoops now appears in:
  - `Today`
  - `Matchup Lens`
  - `Props`
  - `Market Edge`
  - `Injuries`
  - `Trends`
  - `Parlay`

### 3. Checkout and membership regression pass

Status:
- `Completed on 2026-05-30`

Goal:
- Validate the product after the pricing expansion.

Must verify:
- Anonymous user -> pricing -> signup -> checkout redirect
- Existing free user -> upgrade flow
- Paid user -> `/billing`
- Cancel flow -> `/checkout/cancel`
- Success flow -> `/checkout/success`

Open work:
- Run one clean manual pass through all bundle plans.
- Run one clean manual pass through at least one sport pass from each class:
  - pro bundle
  - single-sport pass
  - college pass

Definition of done:
- No broken redirects.
- No stale pricing copy.
- No plan mismatch after checkout success.

Completed proof:
- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_membership_regression.py](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\qc_membership_regression.py)
- Result: `14 checks, 0 failures`
- Fixed during this pass:
  - sport-pass users can now reach `/billing`
  - anonymous checkout redirects now preserve the requested plan instead of defaulting the gate copy to `pro`

### 4. Visual trust walk

Status:
- `Still open`

Goal:
- Confirm the pages read honestly to a real user.

Must review:
- home
- pricing
- dashboard
- props
- market edge
- parlay
- player page
- matchup page
- injuries page
- sport dashboards

Open work:
- Confirm risky rows visibly look risky.
- Confirm `CONFLICTED`, `PASS`, injury, and fragile-under states are obvious.
- Confirm the new legal footer does not visually break layouts.
- Confirm no empty state feels like a bug when it is actually a clean/no-data state.

Definition of done:
- Manual pass completed with no misleading premium-looking weak plays.

## Tier 2: Should Finish Before AWS

### 5. CFB and CBB product truth pass

Status:
- `Partially completed on 2026-05-30`

Goal:
- Make sure the new passes do not overpromise immature products.

Open work:
- Review pricing copy for `CFB Pass` and `CBB Pass`.
- Confirm the sport pages honestly reflect current maturity.
- Confirm under-construction or thin-data pages are not presented as fully finished premium labs.

Definition of done:
- The paid offer matches the current depth of the product.

Current note:
- `CFB Pass` now maps to real college-football routes.
- `CBB Pass` now unlocks both `ncaamb` and `ncaawb`.
- CBB is still a `watch`-status expansion workflow in the universal hubs, which is honest but still needs a product copy review.

### 6. Daily refresh and scorecard sanity pass

Status:
- `Mostly completed on 2026-05-30`

Goal:
- Make sure the app is stable after the latest pricing and route changes.

Open work:
- Run:
  - `py run_all_scorecards.py`
  - `py run_prelaunch_scorecard.py`
  - `py qc_checkout_readiness.py`
- Confirm the latest route and access behavior did not create regressions.

Definition of done:
- Checkout remains `live`.
- Scorecards remain clean enough to continue.

Current result:
- Checkout readiness: `live`
- Prelaunch scorecard: `GO`
- Remaining watches:
  - `Visual Trust`
  - `Sport-Specific Launch Questions`
- `run_all_scorecards.py` exceeded the local timeout window in this environment, so the broad runner itself still deserves a separate long-run verification pass.

### 7. Repo checkpoint before infrastructure

Status:
- `Still open`

Goal:
- Freeze a known-good application state before AWS work starts.

Open work:
- Review `git status`
- Create a checkpoint commit
- Create or move onto a launch branch

Definition of done:
- We can deploy a known application state instead of a moving target.

## Tier 3: Can Wait Until After AWS

These are important, but they are not good reasons to delay first deployment if Tier 1 and Tier 2 are done:

- app.py service extraction
- Redis integration
- Postgres migration
- deeper derivatives buildout
- official event-level tendency feeds
- full mobile polish across every page

## Recommended Execution Order

1. Pass and access validation
2. Universal tools flow review
3. Checkout and membership regression pass
4. Visual trust walk
5. CFB and CBB product truth pass
6. Daily refresh and scorecard sanity pass
7. Repo checkpoint
8. AWS

## Review Decision

We are **not blocked by missing infrastructure ideas**.

We are currently blocked by:

- needing a manual visual trust walk
- needing a final CFB/CBB product-truth review
- needing a repo checkpoint before deployment work

Once those are done, AWS becomes the right next move.
