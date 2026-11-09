# Green Light Release 1A — bounded implementation table (2026-11-09)

**Purpose:** the one bounded table required before any 1A product code. It does not redesign anything.

**Sources (controlling, in order):**
1. `PROGRAM_TABLE.md` CONTROLLING ORDER pos 2 (items 1–14, exclusions, acceptance) and the `FetchedAtUTC` contract;
2. `platform_product_doctrine_20261108.md`;
3. `nov7_cross_sport_landing_audit_20261108.md` (recorded 1A acceptance requirements);
4. `green_light_baseline_inventory_20261108.md`.

The 1A question is unchanged: *can the owner safely use Classic Green Light the way it was originally used?*

**Scope boundary:** 1A covers **only the Classic Green Light path** (`build_green_light`, its template, its lens
inputs and its ticket handoff) plus the Matchup Center line-move join (item 4). It also includes the two mandatory
dependencies in §A0. Anything not in §A is **not 1A**.

## Baseline facts (read-only, prod, `d7fbefa`)

**Item 8 — NFL props by clock (2026-11-09 14:30Z):**
- `NFL_Props.csv`: 425 rows, 5 events (DraftKings 191 / FanDuel 173 / BetMGM 61).
- `SourceUpdatedAtUTC`: zone-explicit and valid on **425/425**, all within 6 h, 0 future.
- `EventCommenceAtUTC` valid on 425/425; 0 started; **425/425 eligible** under the deployed `SourceUpdatedAtUTC` rule.
- `LastUpdated`: zone-less on 425/425 (never authority).
- **`FetchedAtUTC`: column absent.** Under the owner contract, 1A adds it to the NFL props writer (per provider response).
  Existing rows display "Observed by BK: unavailable". No backfill.

**Other baseline facts:**
- `2e2adc6` (SGP spread-price containment + `qc_sgp_spread_price_containment.py`): local branch
  `hotfix/sgp-spread-price-containment`, base `b12eec3`; **not in master, not pushed**.
- Classic engine at prod = baseline `9055594` plus the `9057ba1` banner (baseline inventory). The inherited P0s listed
  below are present in it.

## A. REQUIRED 1A — restoration and integrity (the complete 1A build list)

| # | Requirement | Source | Acceptance evidence (QC / fixture / receipt) |
|---|---|---|---|
| A0.1 | Integrate the `2e2adc6` patch **equivalently** onto `d7fbefa` (home spread leg unpriced; QC 15/15) **before** any 1A change gives game-line legs an event/kickoff identity. This is a **new integration commit** on the current base; the old SHA is never claimed to have landed unchanged | audit P0 spread-price; "mandatory inclusion"; owner 2026-11-09 | `git patch-id` equivalence to `2e2adc6`; `qc_sgp_spread_price_containment.py` on the 1A branch with the same behaviour (15/15, order reversal, mutation) |
| A0.2 | NFL props writer emits **`FetchedAtUTC`** = UTC instant of the successful provider response containing the row; one value per response; never derived; preserved through normalization and atomic publish | `FetchedAtUTC` contract (owner 2026-11-07/08) | Schema / provenance / malformed / zone-less / future / same-response QCs; acceptance on the **next normal scheduled fetch** (no paid manual fetch) |
| A1 | **Identity before evidence (cross-event overwrite P0):** game scripts keyed `(EventId, team)`; opponent from the same event; prop lookup `(EventId, player, market, book)`; mismatch makes the lens **abstain**, never fall back | audit P0, requirements 1–6; doctrine 1 | Adversarial QC: same team today and next week, file orders reversed, results identical; rendered opponent/spread/kickoff/player/offer round-trip to one `EventId`; 11-of-28 replay fixed |
| A2 | Concentration name-key collision (St. Brown ↔ A.J. Brown): resolve by canonical player identity or **abstain** | audit Coaching/Concentration; doctrine 1 | Fixture: St. Brown no longer shows A.J. Brown's data; ambiguous `F.Last` keys abstain |
| A3 | Started events excluded from **actionability** (governed `EventCommenceAtUTC`); stays visible as CONTEXT ONLY | item 1; least-restrictive rule; O-2 is not a dependency | Started-event fixture → not executable, not ticketable, labelled |
| A4 | Tiered player availability: **UNAVAILABLE** (OUT/IR/PUP/suspended/officially inactive) / **REVIEW REQUIRED** (questionable/doubtful/conflict) / **AVAILABILITY PASSED** (absent from official report + roster/event bound + no contradicting transaction). Official inactive list is the final override; a book quote never overrides unavailability | item 2; owner correction 2026-11-08 | Tier fixtures incl. the Bijan/London/Chase Brown 11-08 cases |
| A5 | NFL injury join repaired (identity-bound) and the injury timestamp **zone-labelled** | item 3; audit "unlabelled injury timestamp" | Join fixture; rendered time carries ET/UTC |
| A6 | Line-movement join repaired (team-name + `spread_first`/`spread_open` mismatch) and completed/non-current events excluded — Classic path + Matchup Center only | item 4 | Join fixture; completed-event exclusion |
| A7 | Same-offer binding: sportsbook, line, side, price, `SourceUpdatedAtUTC`, `FetchedAtUTC` from **one row**; no cross-row/cross-book carry; FanDuel row labelled as FanDuel | item 5; owner decision (FanDuel + best governed quote bound to one offer) | Binding QC; order-reversal |
| A8 | Both clocks shown, never merged: **Book updated** (`SourceUpdatedAtUTC`) and **Observed by BK** (`FetchedAtUTC`, or "unavailable") | item 6 | Render fixture; neither ever substitutes for the other |
| A9 | Eligibility keeps the deployed `SourceUpdatedAtUTC` 6 h rule; `FetchedAtUTC` informational (L3 not in 1A) | item 7; contract | Fixture: `FetchedAtUTC` never changes eligibility |
| A10 | Least-restrictive truthful states: each item gets research visibility / lens eligibility / offer executability / handoff eligibility as **AVAILABLE · CONTEXT ONLY · REVIEW REQUIRED · UNAVAILABLE**. Suppress only what missing evidence invalidates. Hard suppression only for legal/data-rights, unresolved identity, or unsafe/dishonest actions | item 9; 1A acceptance requirement; doctrine 8 | The **14-condition behavior matrix** (stale quote … started event) implemented as a table-driven QC: one fixture per condition and column |
| A11 | Stale/invalid evidence suppressed as support but kept as dated context: static Coaching (2023–25 staff, INVALID for changed staff), static "locked role" text (10-09 file), unverified Concentration notes, each with as-of/provenance | item 9; audit provenance | Fixtures: ATL Coaching = CONTEXT ONLY/not counted; Bijan count reproduces 2 |
| A12 | No unregistered model output on Classic; models never select or order visible games | item 10; DIC-1.0 R7 | Static scan + render QC |
| A13 | **Visibility independent of candidate selection (owner-approved 2026-11-09):** every eligible game in kickoff order. **Every identity-resolved player-market row in the NFL props data Classic consumes stays discoverable**, including rows the candidate generator skips. **No popularity, value, model, lens-count or recommendation gate may control visibility.** "Classic universe" means the governed data Classic already receives. It is not a candidate filter | item 11; doctrine §3b.2; owner clarification 2026-11-09 | **Coverage reconciliation:** identity-resolved player-market rows available to Classic → rows rendered or discoverable → every exclusion with its exact reason → **zero** exclusions based only on popularity, value, model output or generator selection |
| A14 | **Direction symmetry (owner-approved 2026-11-09):** every displayed player-market threshold shows **over, under and push history**, including the active directional streak. **Missing under odds affects executability only, never trend visibility.** Trend calculations exist without an executable price | doctrine §3b.1; owner clarification 2026-11-09 | Fixtures: **Bijan** (96.5; 145/86/61/63/76; under 4/5; active under streak 4); a lesser-known player; an active over streak; an active under streak; a whole-number push; short history; bye/missing game; multiple books with different lines |
| A15 | Wording: `Model %` → **Market-implied probability** (a price translation); remove unsupported Confidence; correct AP-poll wording; Matchup label says **opponent-adjusted** | item 12 | Copy QC (forbidden-term list) |
| A16 | Evidence vocabulary on the lens/evidence panel: Supporting / Contradicting / Missing / Unknown / Conflicting / Disqualifying / Not applicable, never collapsed | doctrine §3b.3 | Render fixture per term |
| A17 | All-overs warning on the Green Light ticket-building path | item 13 | Existing `analyze_saved_parlay` warning appears on the GL path |
| A18 | All existing legal, licensing, provenance, freshness and ticket-safety protections retained (D4 kickoff gate, quote contracts, `17b5e69` quote-time authority) | item 14 | Existing QC suite unchanged and green |
| A19 | Classic stays explicitly accessible (`?view=classic`); **no default-route switch** in 1A | item 14 / exclusions | Route QC |
| A20 | Doctrine-conformance matrix in the 1A acceptance package (identity, visibility, evidence, eligibility, actionability, user decision) | doctrine §3b.4 / §4 | Matrix document plus the QC references above |

**Evidence vs offer (owner 2026-11-09):**
- Trend calculations may exist without an executable price.
- An executable offer requires the exact book, market, selection, side, line, price and both timestamps.
- No inferred under prices. No reconstructed spread prices.

**What 1A does NOT yet provide (owner 2026-11-09).** 1A restores a complete, direction-neutral view of the governed
data Classic already receives. Later releases expand the threshold and market universe. 1A does not provide:
- arbitrary user thresholds;
- BK Milestones;
- new or unsupported market families;
- a universal cross-sport explorer;
- Green Light Specials;
- automated recommendations.

**No paid manual fetches.** `FetchedAtUTC` is validated with synthetic fixtures and the next normal scheduled
publication.

**1A exclusions (unchanged from `PROGRAM_TABLE`):**
- no new scoring or confidence; no automatic picks; no new lenses;
- no game-centric redesign; no new cross-page navigation;
- no ticket-storage expansion; no CFB restoration; no Green Light Next;
- no default-route switch;
- no universal props explorer, BK Milestones or user thresholds (§C).

**1A gate and receipt:**
- built from post-`d7fbefa` master;
- full offline gate plus exact-SHA Linux gate;
- deployed as the only candidate on owner approval;
- **signed-in production receipt** proving the repaired Classic view has no started events or unavailable players
  executable, truthful same-offer pricing and both clocks, current eligible evidence, and the convergence workflow
  intact. The signed-in walkthrough is the owner's; CTP does not touch signed-in routes.
- **Stop for owner acceptance.**

## B. 1B — activation (not 1A)

- `/tools/green-light` renders repaired Classic; `?view=classic` stays compatible; `?view=workspace` keeps the
  workspace.
- Navigation points to the supported default; bookmarks keep working; cache versioning prevents the old default
  persisting.
- Decision vocabulary Green Light / Watch / Pass / Revisit as **user** states, never system verdicts.
- Neither experience is deleted. Separately gated and deployed. Release 1 closes only after 1B passes.

## C. Later platform capabilities (must be ordered explicitly; not 1A or 1B)

- **BK Milestones:** window-switchable threshold maps with sample size.
- **User-defined thresholds** ("Higgins 100").
- **Universal direction-neutral props/market explorer** across all governed players and markets.
- **Distribution views:** median, range, volatility, percentiles labelled as history.
- **Trust-dimension display** and evidence-stability classes.
- **Cross-market views.**
- **Change timelines.**
- **Green Light Specials**, as governed pricing situations only.
- **Decision Journal enablement** and the learning loop.
- **Market adapter** matching thresholds to alternate lines.
- **L3:** `FetchedAtUTC` participating in eligibility.

## D. Inherited obligations outside Green Light (recorded; each owned elsewhere)

| Item | Owner / attach |
|---|---|
| I-1 CFBD quota latch; O-5 allowance/reset contract | P1-6 / consolidated `bk-daily` |
| I-2 MLB/WNBA off-season handling | P1-6 (F2v2/F6) |
| I-3 NBA board QC `postseason_only` / playoff assumptions / team mapping; O-4 NBA results rights + producer | NBA season readiness / P1-6 |
| I-4 14 legacy QCs need the governed runner for heartbeat containment | QC maintenance |
| I-5 Signed-in prewarm path unverified | Performance / prewarm |
| O-1 CFB Eastern-date grading; O-2 prime-time live-score date | P1-6 / data integrity (O-2 explicitly **not** a 1A dependency) |
| O-3 cross-surface football freshness (Slate Pulse, Best Lines, `_format_game_market_odds` drops `LastUpdated`) | L1/L2 family (P1-4) |
| Spread **writer** repair (keep both outcomes and their sides; 6 requirements) — 1A carries only the containment `2e2adc6` | Own release |
| Neutral-site venue contract (Classic lenses do not read venue) | Own release |
| NFL intra-day refresh windows (~65–345 credits/week) | Owner cost decision |
| ATS source auditability (nflverse `spread_line` not retained) | Data-integrity |
| Workspace regressions (Daily-Card ticket under "Green Light", "validated" wording) | Out of 1A; 1B leaves the workspace at its alternate entry |

## Build order inside 1A (one branch from current `master` = `d7fbefa`)

A0.1 → A0.2 → A1/A2 (identity) → A3–A9 (eligibility, availability, joins, offer binding, clocks) → A10/A11 (state
matrix, evidence suppression) → A12–A17 (visibility, symmetry, wording, vocabulary, warning) → A18–A20 (protections,
route, conformance matrix) → offline gate → exact-SHA Linux gate → owner deploy decision.

**Anything not in §A needs its own `PROGRAM_TABLE` entry before it is built.**
