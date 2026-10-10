# Public Test-Drive Readiness Review — 2026-10-10

**Rev 2 (2026-10-10):** accepted with three classification corrections from governance
review — (1) free-account testing moved P1 → **P0-4**; (2) do **not** expose the owner-only
`/test-drive` page, build a tester-facing feedback form instead; (3) visitor access and
mobile are **provisionally passing — a non-owner smoke test is still required** (this review
ran in an owner session). Rev 1 is preserved in git history.

**Purpose:** decide what must be fixed before Bankroll Kings is put in front of real
outside testers (casinos, barbershops, etc.). **Read-only review. No feature changes were
made.** This report proposes fixes; none is authorized here — the fixes are specified in
`docs/field_test_p0_remediation_spec.md` and implemented only after that spec is approved.

**Method:** live inspection of production (`bankrollkings.com`) in an **authenticated owner
session** + mobile viewport (375×812) + source confirmation in `app.py` / `templates/`.
Judged against the agreed promise:

> *"Bankroll Kings brings market information, factual context, transparent research, and
> decision tracking into one place so you can evaluate wagers for yourself"* — **not**
> "come see our winning model."

**Verdict:** the platform is close; the honest surfaces built during PropScore containment
(Green Light, props screener, NFL Totals Context, Daily Card, how-we-analyze) render clean.
The gap is a **small, concentrated launch-readiness gap, not a research or rebuild need.**
Four P0s, all copy / visibility / access — plus one verification P0 that can only run after
the first three land.

---

## Scorecard

| # | Area | Status | Severity |
|---|---|---|---|
| 1 | Mobile usability | **Provisionally passing — non-owner smoke test required** | P0-gated |
| 2 | Visitor access & free signup | **Provisionally passing — non-owner smoke test required** | P0-gated |
| 3 | Authenticated dashboard authority language | **FAIL** | **P0-1** |
| 4 | In-product feedback capture (tester-facing) | **FAIL** | **P0-2** |
| 5 | Positioning / profit-promise tone | **FAIL** | **P0-3** |
| 6 | Full non-owner / free-account journey + tracking | **NOT YET VERIFIED** | **P0-4** |
| 7 | Production rendering / critical errors | PASS (one 404 asset) | P1 |
| 8 | Data freshness signalling | PASS | — |
| 9 | Trust & safety disclosures (21+, RG) | PASS | — |

---

## The P0 set (as reclassified by governance)

### P0-1 · Remove or hide dashboard best-bet, promotion, and hindsight-proof authority from tester-facing views
**Where:** `/dashboard` (first screen after sign-in). `templates/dashboard_overview.html`
"Phase 2 Intelligence" block (lines 241–345) and the cross-sport "best" lane labels built in
`app.py:20996–20999`.

**What renders for a tester today (observed live):**
- Cross-sport cards headed **"MLB · BEST UNDER", "NFL · BEST OVER", "MLB · BEST OVER"** — a
  cross-sport best-bets ranking (on the **do-not-build list**). The lead "BEST UNDER" was a
  **−10000 / 99.0%-implied** favorite — the most heavily-juiced chalk shown as a "best" play.
- **"PROMOTION SIGNALS … PROMOTE HARD"** and a **"PROMOTION QUEUE"** justified by *"a live
  rule signal, a trusted reliability bucket, and current board pressure strong enough to move
  it into review"* — undocumented predictive selection authority the frozen contract forbids.
- **"MISSED WINNERS … A+ … becomes proof for future promotion rules"**
  (`dashboard_overview.html:323`) — hindsight/survivorship accuracy marketing.

**Boundary (governance):** hide these from tester-facing views, but **do not silently delete
the research data or underlying computations.** Preserve them internally until they receive
proper governance treatment. Implementation is therefore visibility/label only.

### P0-2 · Provide a safe tester-facing feedback form without exposing owner controls
**Where:** `/test-drive` (`app.py:36029`) is owner-gated (`is_owner_user` → 403). It contains
internal workflow, feedback statistics, the full feedback log, and reviewer language.

**Decision:** keep `/test-drive` owner-only. Build a **separate tester-facing feedback form**
that captures a note and nothing else — no stats, no other testers' feedback, no owner
controls. The capture backend (`POST /feedback/save`) already exists and is reusable.

### P0-3 · Replace "beat the book / casino" positioning with decision-support language
**Where:** `pricing.html:11` ("…help you bust the casino's ass"), `pricing.html:124` ("Built
to beat the book"), and the All-Access plan definition in `app.py:467–468` ("Built to help
you beat the book, not to gouge you" / "Anyone serious about beating the book"). Pure copy.
(`franchise_hub.html:1524` "gouge on tickets" is in-game GM flavor text — out of scope.)

### P0-4 · Complete the full non-owner / free-account journey on mobile and verify decision tracking
A public test-drive cannot be declared ready until a **real non-owner free account** completes,
on a phone: signup + 21+ attestation → first login → useful landing → navigation to core tools
→ **save and reopen a tracked decision** → submit feedback → logout and return. This review ran
in an owner session, so items 1, 2 and 9 are **provisionally** passing only. The step-by-step
script is in the remediation spec.

---

## P1 — fix soon, not blocking the first test-drive

- **P1-1 · One 404 console error on `/test-drive`** (missing static asset; no visible
  breakage). Identify and fix the asset reference.
- **P1-2 · `/test-drive` tester-path notes still read internally** ("Best place to judge…").
  Harmless; owner-only page. Reword opportunistically.

---

## What is already good (keep as-is)

- **Freshness is surfaced honestly:** dashboard "Run Status" strip shows per-job timestamps
  and "14 green checks, 0 watch items" answering *"did the refresh chain run?"*; boards carry
  live / season-prep labels and prop counts.
- **Disclosures are well distributed:** footer "analytics platform, not a sportsbook —
  entertainment and research only" + Terms/Privacy/Refund/Responsible-Gambling + 1-800-GAMBLER;
  signup requires "I am 21 or older and have reviewed Responsible Gambling"; inline "21+ …
  nothing here is a guaranteed winner or a 'lock'" on `start_here`, `unit_sizing`,
  `how_we_analyze`, and several boards.
- **Free, no-card account exists** (`/pricing`: "Start Here · $0 · No card required") with a
  public "Create Free Account" CTA — a tester can get in without paying.
- **The containment surfaces hold up:** Green Light reads as "configured lenses" with
  observable line-state; NFL Totals Context is totals-only with "No validated betting edge is
  claimed"; props screener has no PropScore column/sort; Daily Card reads "assembled by rule …
  not a graded pick." These are the model for how P0-1 should look.

---

## Recommended authorization sequence

1. Approve the **Field Test P0 Remediation Specification**
   (`docs/field_test_p0_remediation_spec.md`).
2. Implement **P0-1, P0-2, P0-3 only** — copy / label / visibility / one additive feedback
   route. No model, ranking, threshold, schema, or auth-gating changes.
3. Run **P0-4**: the non-owner free-account journey on mobile (verification script in the spec).
4. Fix P1-1/P1-2.
5. Only then schedule casino / barbershop visits. First QR path:
   **Create free account → explore a matchup or market → save a decision → submit feedback.**
   The goal of those visits is to learn whether strangers understand and value the platform —
   **not** whether its selections win that day.

*No changes made. Awaiting approval of the remediation spec before any code edit.*
