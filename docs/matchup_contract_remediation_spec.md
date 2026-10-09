# Contract Conformance Remediation Specification

**Status: SPEC FOR APPROVAL — no implementation.** Exact, reviewable customer-facing language
replacements for the accepted conformance findings (`docs/matchup_contract_conformance_review.md`)
against the frozen contract (`docs/matchup_page_product_contract.md`). Nothing here is applied.
Scope is **copy / labels / tooltips / explanatory framing / status display only** — no ranking,
selection logic, models, scores, governance states, research, or redesign. Dated 2026-10-09.

**Wording corrections adopted (from review):**
- Do **not** use "model read" for the de-vigged probability — call it "de-vigged price (implied
  probability from the odds)."
- Do **not** use "validated score" or "model read" — no governance record documents one.
- Do **not** use "reliability" / "most reliable" — use the observable fact ("historical hit rate").
- Prefer **"largest model–market difference"** over "edge" / "lean" / "best" for unqualified outputs.
- **Retracted:** the review's phrasing that confidence-sorting "surfaces the most -EV rows first."
  That -EV claim is **not established** and is removed; the correct statement is only that
  confidence here = the de-vigged price restated, not an earned edge.

---

## P1 — Legacy matchup page: remove "Lock" and "Highest Conviction"

### P1.1 — NBA/MLB matchup verdict key
- **Surface:** `/matchup/<matchup>` → `templates/matchup.html:255` (Prop Fits "Verdict key").
- **Current language:** `Lock` (badge) · "highest conviction"
- **Replacement language:** remove the "Lock" badge and its row entirely. Keep the remaining key as
  "Play — implied probability ≥ 70%" and "Pass — implied probability < 70% (no play)".
- **Governance reason:** contract §7/do-not-build — "Lock" is prohibited; "highest conviction"
  asserts unearned affirmative authority (§3).
- **Change type:** copy + presentation (remove a badge/label).
- **Explicit non-change:** the prop grading thresholds and which props show are unchanged; only the
  top verdict label is removed and the metric is renamed (see P4.1).
- **Verification:** grep confirms "Lock" and "highest conviction" no longer in `matchup.html`; page
  renders the two-row key; `git diff` touches only template copy.

### P1.2 — MLB matchup "Best Anchor"
- **Surface:** `/matchup` (MLB) → `templates/mlb_matchup.html:118-121`.
- **Current language:** "**Best Anchor**" / "**Highest reliability** prop currently attached to this
  game."
- **Replacement language:** "**Anchor**" / "Prop with the **highest historical hit rate** attached
  to this game."
- **Governance reason:** §3 — "best"/"reliability" imply earned authority; historical hit rate is an
  observable **Fact**, stated as a fact.
- **Change type:** copy.
- **Explicit non-change:** the anchor-selection logic and the displayed hit-rate % are unchanged.
- **Verification:** grep confirms "Best Anchor"/"reliability" gone; the hit-rate badge still renders.

### P1.3 — Dashboard hit-rate "lock" styling (presentation)
- **Surface:** `templates/dashboard.html:1713` — CSS class `hr-lock` at hit-rate ≥ 80%.
- **Current:** class `hr-lock` (vs `hr-strong`).
- **Replacement:** rename to `hr-high` (and its CSS rule); no "lock" semantics.
- **Governance reason:** §7 — remove "lock" tiering, even as an internal visual cue.
- **Change type:** styling (class rename).
- **Explicit non-change:** the 80% threshold and the displayed hit-rate number are unchanged — only
  the class name/visual tier label.
- **Verification:** grep confirms no `hr-lock`; the cell still shows the same % with styling intact.

---

## P2 — Green Light: lens counts + research-in-progress framing

The page intro already conforms ("Evidence convergence, not a prediction"), and each tier already
renders "{N}+ lenses agree." Only the tier **names** overclaim.

### P2.1 — Tier names
- **Surface:** Green Light tiers — `app.py:30960-30964` (tier assignment + `TIERS` list) surfaced
  in `templates/green_light.html:64-66`.
- **Current language:** "Highest conviction" (≥4 lenses) · "Strong context" (3) · "Worth
  investigating" (2) · "Single-lens idea" (1).
- **Replacement language:** "4+ lenses agree" · "3 lenses agree" · "2 lenses agree" · "1 lens".
  (The "{N}+ lenses agree" subtext already present becomes redundant and may be dropped to avoid
  repetition — presentation only.)
- **Governance reason:** §3/§6 — the lenses are **Under Review**; "conviction" translates a *count*
  into a *confidence* claim it hasn't earned. A count is a fact; "conviction" is not.
- **Change type:** copy (label strings) + the template's `ti` mapping keys updated to match.
- **Explicit non-change:** the convergence counting, the market gate, tier ordering, and which plays
  appear are all unchanged — only the tier display names.
- **Verification:** grep confirms the four "conviction/context/investigating/idea" names gone; tiers
  render by lens count; the number and order of plays in each tier are byte-identical to before.

### P2.2 — Research-in-progress disclosure line
- **Surface:** `templates/green_light.html` page-subtitle (after the existing intro).
- **Current language:** (none — intro ends at "Evidence convergence, not a prediction.")
- **Replacement language:** add one sentence: "These lenses are **Under Review** — convergence is a
  count of independent angles that agree, **not a graded edge** yet."
- **Governance reason:** §6 — Green Light must read as research-in-progress until its lenses earn
  Qualified.
- **Change type:** copy (explanatory framing).
- **Explicit non-change:** no logic; a sentence is added.
- **Verification:** the subtitle contains the Under-Review sentence; no other change.

---

## P3 — Daily Card: assembled by rule, not "best"

### P3.1 — Subtitle
- **Surface:** `/tools/daily-card` → `templates/daily_cards.html:49` (page-subtitle).
- **Current language:** "the **strongest** 3, 4, and 5-leg tickets from this slate: mostly
  high-floor legs that reliably clear the number, plus one plus-money swing for payout. Cross-game,
  **best of the board**, every leg with a real reason. **The finished ticket, on arrival.**"
- **Replacement language:** "3, 4, and 5-leg tickets **assembled by rule** from this slate:
  cross-game legs (one per game), weighted toward **high-floor** props that have historically
  cleared the number, plus one plus-money **swing**. **Options assembled for you — not a graded
  pick.**"
- **Governance reason:** §6 — "strongest / best of the board / finished ticket" imply governed
  selection authority that doesn't exist; Daily Card is a rule-based assembly.
- **Change type:** copy.
- **Explicit non-change:** the assembly rule (cross-game, high-floor + one swing), the legs chosen,
  and the honest build footnote at `:94` are all unchanged.
- **Verification:** grep confirms "strongest"/"best of the board"/"finished ticket" gone; the cards
  and their legs are identical to before.

### P3.2 — Leg-swap tooltip
- **Surface:** `templates/daily_cards.html:87` swap button `title`.
- **Current language:** "Swap this leg for the next-**best** alternate"
- **Replacement language:** "Swap this leg for the next alternate by the same rule"
- **Governance reason:** §6 — "best" implies ranking authority; it's the next option by the assembly
  rule.
- **Change type:** copy (tooltip).
- **Explicit non-change:** the swap logic/order is unchanged.
- **Verification:** tooltip text updated; swap behavior identical.

---

## P4 — Confidence terminology (customer-facing label + sort label)

### P4.1 — Matchup verdict metric
- **Surface:** `templates/matchup.html:256-257` (the "Play/Pass" rows of the verdict key).
- **Current language:** "confidence ≥ 70%" / "confidence < 70% (no play)"
- **Replacement language:** "implied probability ≥ 70%" / "implied probability < 70% (no play)"
- **Governance reason:** §3/§4 — "confidence" reads as earned conviction; the number is the de-vigged
  price (implied probability), a restatement of the market, not a governed edge.
- **Change type:** copy (label).
- **Explicit non-change:** the 70% threshold and the Play/Pass assignment are unchanged.
- **Verification:** grep confirms "confidence" replaced with "implied probability" in the key.

### P4.2 — Free-tier feature copy
- **Surface:** `app.py:453` (plan features list, customer-facing).
- **Current language:** "Top 3 **highest-confidence** props per sport with hit rates"
- **Replacement language:** "Top 3 props by **implied probability (de-vigged price)**, with real hit
  rates"
- **Governance reason:** §3/§4 — "highest-confidence" implies earned ranking; the number is the
  de-vigged price. (No "model read," no "validated score.")
- **Change type:** copy.
- **Explicit non-change:** which props the dashboard shows is unchanged.
- **Verification:** grep confirms "highest-confidence" gone from the features list.

### P4.3 — /market-edge sort control
- **Surface:** `templates/smart_picks_v2.html:583` (sort button).
- **Current language:** "**Highest Confidence**" (sort)
- **Replacement language:** "**Implied probability (de-vigged price)**"
- **Governance reason:** §3/§4 — the sort key is the de-vigged price, not a governed confidence or a
  validated score.
- **Change type:** copy (control label).
- **Explicit non-change:** **the sort still orders by the identical underlying value** — only the
  button label changes. No ranking/selection logic change. No new default sort is specified here
  (changing the default would be a ranking change, out of scope).
- **Verification:** grep confirms the label; the sort order for a given dataset is byte-identical.

---

## P5 — Board headlines: drop "best / edge" where governance doesn't support them

### P5.1 — CFB board
- **Surface:** `templates/cfb_board.html:33` (page-subtitle).
- **Current language:** "The model's **best** spread & total plays across this week's slate, **ranked
  by edge.** We surface and rank the options; you bring the eye test. Candidates, not locks."
- **Replacement language:** "The model's spread & total **leans** vs the posted number this week,
  ranked by the **largest model–market difference**. Opponent-adjusted strength is a **Baseline
  (no validated edge)** — context, not a graded pick. We surface and rank the options; you bring the
  eye test. Candidates, not locks."
- **Governance reason:** §3 — opponent-adjusted strength is **Baseline** (Audit #1: no demonstrated
  edge); "best plays / edge" exceeds that.
- **Change type:** copy.
- **Explicit non-change:** the ranking (by model–market gap) and which games show are unchanged —
  only the headline words.
- **Verification:** grep confirms "best"/"ranked by edge" gone from the subtitle; same games, same
  order.

### P5.2 — NFL top board
- **Surface:** `templates/nfl_board.html:35` (page-subtitle).
- **Current language:** "The **best plays** across every market — props, totals, wind, injury spots
  — ranked by how strong the **evidence** is. … Candidates, not locks."
- **Replacement language:** "Plays across every market — props, totals, wind, injury spots — ranked
  by how much **context lines up** (status-labeled; no play here is a graded edge yet). … Candidates,
  not locks."
- **Governance reason:** §3 — the underlying signals are Under Review / not documented Qualified;
  "best plays" overclaims.
- **Change type:** copy.
- **Explicit non-change:** ranking and contents unchanged.
- **Verification:** grep confirms "best plays" gone; same rows/order.

### P5.3 — NFL game-line board
- **Surface:** `templates/nfl_game_board.html:36` (page-subtitle).
- **Current language:** "ranked **best to worst by the model's edge** vs the posted number … 
  Candidates, not locks."
- **Replacement language:** "ranked by the **largest model–market difference** vs the posted number
  (a model **lean**, not a validated edge) … Candidates, not locks."
- **Governance reason:** §3 — NFL game-line model edge is not documented Qualified.
- **Change type:** copy.
- **Explicit non-change:** ranking by the model–market gap and contents unchanged.
- **Verification:** grep confirms "the model's edge" replaced; same order.

---

## Approval question

If these exact changes are implemented — **copy, labels, tooltips, framing, and one class rename
only, with every ranking and selection unchanged** — will the live product align with the frozen
contract? If yes, open the remediation implementation gate (suggested order P1 → P2 → P3 → P4 → P5).
If no, revise this spec. No customer-facing copy is changed until this spec is approved.
