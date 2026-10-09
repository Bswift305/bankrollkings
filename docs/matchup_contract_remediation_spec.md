# Contract Conformance Remediation Specification (Rev 3 Final)

**Status: SPEC FOR APPROVAL — no implementation.** Exact customer-facing language replacements for
the accepted conformance findings, against the frozen contract
(`docs/matchup_page_product_contract.md`). Nothing applied. Scope is **copy / labels / tooltips /
explanatory framing / status display only** — no ranking, selection logic, models, scores,
governance states, research, or redesign. Rev 3 (2026-10-09) applies the five final corrections on
top of the nine resolved in Rev 2.

**Guiding principle (Rev 2):** remediation must **eliminate authority language, not replace it with
softer authority language.** Use **observational / mechanical** terms only. "Play," "Lean," "Best,"
"Anchor," "conviction," "reliability," "independent" all imply authority that is not governed; they
are replaced with the observable thing (a market-implied probability, a historical hit rate, a
model–market difference, a configured-lens count).

**Corrections adopted (9):** (1) remove Play/Pass — descriptive labels only; (2) "Anchor" →
"Historical Hit-Rate Leader"; (3) "independent lenses/angles" → "configured lenses" (independence
not demonstrated); (4) drop "high-floor" — describe the actual metric; (5) drop "lean" → "largest
model–market difference"; (6) drop "context lines up" — state the real ordering rule; (7) the
`hr-lock` class rename is **removed** (internal identifier, not customer-visible); (8) verification
is **same IDs / ordering / thresholds / selections**, not rendered-HTML equality; (9) completion
claim narrowed to the identified authority-language findings only — this does **not** establish
product-wide structural conformance.

Also carried: no "model read" / "validated score"; the user-facing number is the **de-vigged
market-implied probability**. The review's unestablished "high implied prob ≈ -EV" claim stays
retracted.

**Rev 3 corrections (5):** (a) remove residual "plays" recommendation nouns → "markets" / "market
entries"; (b) resolve the matchup "Play" *column* — it renders `prop.direction` (OVER/UNDER), i.e.
the **side**, so its header becomes "Side" (no deferred decision); (c) "real hit rates" →
"displayed historical hit rates"; (d) "high historical hit rate" → the actual rule ("higher
displayed historical hit rates at the current number"); (e) "de-vigged price" → "de-vigged
market-implied probability" (the display is a probability).

---

## P1 — Legacy matchup page: remove verdict authority

### P1.1 — NBA/NFL matchup verdicts (key, badges, column)
- **Surface:** `/matchup/<matchup>` → `templates/matchup.html`: verdict key (`:254-257`), per-prop
  badges (`:331` "{N}% Lock", `:333` "{N}% Play"), and the "Verdict" column header (`:261`).
- **Current language:** `Lock` = "highest conviction"; `Play` = "confidence ≥ 70%"; `Pass` =
  "confidence < 70% (no play)"; badges "{N}% Lock" / "{N}% Play"; column "Verdict".
- **Replacement language:** drop the Lock/Play/Pass verdict words entirely. Key heading "Verdict
  key:" → "Market-implied probability:" with two descriptive rows — "≥ 70% market-implied" and
  "< 70% market-implied". Badges "{N}% Lock" / "{N}% Play" → "{N}% market-implied". Column header
  "Verdict" → "Market-implied %". The separate 6th column headed "Play" (`matchup.html:270`) renders
  `prop.direction` (OVER/UNDER) — it is the **side**, so rename its header "Play" → "Side"; its cell
  (OVER/UNDER) is unchanged.
- **Governance reason:** §3/§7 — "Lock" is do-not-build; "Play"/"Pass"/"conviction" are
  recommendation verdicts with no governed authority. The number is the de-vigged market-implied
  probability, so show it as such and stop there.
- **Change type:** copy / labels.
- **Explicit non-change:** the 70% threshold, the implied-probability computation, which props
  display, and column order are unchanged — only the words.
- **Verification:** grep shows no "Lock" / "Play" / "Pass" / "conviction" labels remain in
  `matchup.html`; the prop set has the **same IDs, same ordering, same thresholds, same
  selections**. The 6th "Play" column is **resolved**: it renders `prop.direction` (OVER/UNDER), so
  its header becomes "Side" and the cell is unchanged — no deferred decision.

### P1.2 — MLB matchup "Best Anchor"
- **Surface:** `templates/mlb_matchup.html:118-121`.
- **Current language:** "Best Anchor" / "Highest reliability prop currently attached to this game."
- **Replacement language:** "**Historical Hit-Rate Leader**" / "Prop with the **highest displayed
  historical hit rate** attached to this game."
- **Governance reason:** §3 — "best"/"reliability" imply earned authority; historical hit rate is an
  observable Fact.
- **Change type:** copy.
- **Explicit non-change:** the anchor-selection logic and the displayed hit-rate % are unchanged.
- **Verification:** grep shows "Best Anchor"/"reliability" gone; **same prop ID / hit-rate value**.

*(Removed in Rev 2: the former P1.3 `hr-lock` → `hr-high` class rename — an internal identifier, not
customer-visible; the contract governs customer meaning, not class names.)*

---

## P2 — Green Light: configured-lens counts + research-in-progress

### P2.1 — Tier names
- **Surface:** tiers in `app.py:30960-30964` surfaced in `templates/green_light.html:64-66`.
- **Current language:** "Highest conviction" (≥4) · "Strong context" (3) · "Worth investigating"
  (2) · "Single-lens idea" (1); subtext "{N}+ lenses agree".
- **Replacement language:** "4+ configured lenses point the same way" · "3 configured lenses" ·
  "2 configured lenses" · "1 configured lens". Subtext → "{N}+ configured lenses point the same
  way".
- **Governance reason:** §3/§6 — lenses are Under Review; "conviction"/"context" translate a *count*
  into a confidence claim, and "independent" asserts independence not demonstrated. A **count of
  configured lenses** is the observable fact.
- **Change type:** copy (label strings) + the template `ti` mapping keys updated to match.
- **Explicit non-change:** the convergence counting, the market gate, tier ordering, and which plays
  appear per tier are unchanged — only display names.
- **Verification:** grep shows the four conviction/context names gone; tiers render by configured-
  lens count; **each tier holds the same play IDs in the same order** as before.

### P2.2 — Intro wording + research-in-progress line
- **Surface:** `templates/green_light.html:48` page-subtitle.
- **Current language:** "…how many **independent lenses** point the same way…" (ends "Evidence
  convergence, not a prediction.")
- **Replacement language:** "independent lenses" → "**configured lenses**"; append one sentence:
  "These lenses are **Under Review** — convergence is a count of configured angles that point the
  same way, **not a graded edge** yet."
- **Governance reason:** §3/§6 — drop the undemonstrated independence claim; disclose Under-Review.
- **Change type:** copy (framing).
- **Explicit non-change:** no logic; wording only.
- **Verification:** grep shows "independent" removed from the subtitle and the Under-Review sentence
  present.

---

## P3 — Daily Card: assembled by rule; describe the real metric

### P3.1 — Subtitle
- **Surface:** `templates/daily_cards.html:49`.
- **Current language:** "the **strongest** 3,4,5-leg tickets… mostly **high-floor** legs that
  reliably clear the number, plus one plus-money swing… Cross-game, **best of the board**, every
  leg with a real reason. **The finished ticket, on arrival.**"
- **Replacement language:** "3, 4, and 5-leg tickets **assembled by rule** from this slate:
  cross-game legs (one per game), weighted toward props with **higher displayed historical hit rates
  at the current number**, plus one plus-money leg for upside. **Options assembled for you — not a
  graded pick.**"
- **Governance reason:** §6 — "strongest/best of the board/finished ticket" imply governed
  selection; §4/#4 — "high-floor" is an undefined/ungoverned term, so state the actual metric
  (historical hit rate at the number).
- **Change type:** copy.
- **Explicit non-change:** the assembly rule (cross-game, high-hit-rate + one plus-money leg), the
  legs chosen, and the honest build footnote at `:94` are unchanged.
- **Verification:** grep shows "strongest"/"high-floor"/"best of the board"/"finished ticket" gone;
  the cards contain the **same leg IDs in the same order**.

### P3.2 — Leg-swap tooltip
- **Surface:** `templates/daily_cards.html:87` swap button `title`.
- **Current language:** "Swap this leg for the next-**best** alternate"
- **Replacement language:** "Swap this leg for the next alternate **by the same rule**"
- **Governance reason:** §6 — "best" implies ranking authority.
- **Change type:** copy (tooltip).
- **Explicit non-change:** the swap order is unchanged.
- **Verification:** tooltip text updated; **swap order identical**.

---

## P4 — Confidence terminology → market-implied probability

### P4.1 — Free-tier feature copy
- **Surface:** `app.py:453` (plan features list).
- **Current language:** "Top 3 **highest-confidence** props per sport with hit rates"
- **Replacement language:** "Top 3 props by **de-vigged market-implied probability**, with
  **displayed historical hit rates**"
- **Governance reason:** §3/§4 — "highest-confidence" implies earned ranking; the number is the
  de-vigged market-implied probability (not a "model read" or "validated score").
- **Change type:** copy.
- **Explicit non-change:** which props the dashboard shows is unchanged.
- **Verification:** grep shows "highest-confidence" gone from the features list.

### P4.2 — /market-edge sort control
- **Surface:** `templates/smart_picks_v2.html:583`.
- **Current language:** "Highest Confidence" (sort)
- **Replacement language:** "De-vigged market-implied probability"
- **Governance reason:** §3/§4 — the sort key is the de-vigged market-implied probability, not a
  governed confidence or a validated score.
- **Change type:** copy (control label).
- **Explicit non-change:** **the sort orders by the identical underlying value** — label only. No
  default-sort change (that would be a ranking change, out of scope).
- **Verification:** grep shows the label; for a fixed dataset the **row ordering is identical** (same
  IDs in the same order).

---

## P5 — Board headlines: mechanical ordering language, no judgment words

### P5.1 — CFB board
- **Surface:** `templates/cfb_board.html:33`.
- **Current language:** "The model's **best** spread & total plays across this week's slate, **ranked
  by edge.** … Candidates, not locks."
- **Replacement language:** "This week's spread and total **markets** where the model's number
  **differs most from the posted number** (largest model–market difference). Opponent-adjusted strength is a
  **Baseline — no validated edge** — context, not a graded pick. We surface and rank the options;
  you bring the eye test. Candidates, not locks."
- **Governance reason:** §3 — opponent-adjusted strength is **Baseline** (Audit #1: no demonstrated
  edge); "best/edge/lean" exceed that. Use the mechanical difference.
- **Change type:** copy.
- **Explicit non-change:** the ordering (by model–market difference) and which games show are
  unchanged.
- **Verification:** grep shows "best"/"ranked by edge"/"lean" gone; **same game IDs, same order**.

### P5.2 — NFL top board
- **Surface:** `templates/nfl_board.html:35`.
- **Current language:** "The **best plays** across every market — props, totals, wind, injury spots
  — ranked by how strong the **evidence** is. … Candidates, not locks."
- **Replacement language:** "**Market entries** across props, totals, wind, and injury spots —
  ranked by **displayed historical hit rate** (default; sortable). Status-labeled; **not a graded
  edge**. … Candidates, not locks."
- **Governance reason:** §3/#6 — state the real ordering rule (the board's default sort is
  `hit_pct`, an observable fact), not "best plays / how strong the evidence is."
- **Change type:** copy.
- **Explicit non-change:** the default `hit_pct` sort and the rows shown are unchanged.
- **Verification:** grep shows "best plays" gone; default ordering still by `hit_pct`; **same
  IDs/order**.

### P5.3 — NFL game-line board
- **Surface:** `templates/nfl_game_board.html:36`.
- **Current language:** "ranked **best to worst by the model's edge** vs the posted number …
  Candidates, not locks."
- **Replacement language:** "ranked by the **largest model–market difference** vs the posted number
  (**not a validated edge**) … Candidates, not locks."
- **Governance reason:** §3/#5 — NFL game-line model edge is not documented Qualified; drop
  "edge/lean", use the mechanical difference.
- **Change type:** copy.
- **Explicit non-change:** ordering by the model–market difference and contents unchanged.
- **Verification:** grep shows "the model's edge" replaced; **same ordering**.

---

## Scope of this remediation (narrowed)

This specification addresses **only the identified authority-language findings** above. It does
**not** establish product-wide structural conformance with the frozen contract — surfaces not
listed here were not re-inventoried in this pass.

## Approval-standard check (Rev 3 Final)

Against the five approval standards:

1. **No remaining recommendation language** — verified by scan: every residual match for
   play / lock / best / lean / anchor / reliability / high-floor / real-hit / de-vigged-price
   appears only in the guiding-principle word list, the corrections log, a "Current language"
   quote, a finding header, or a governance/non-change explanation — **never in a replacement.**
2. **Every replacement is observational or mechanical** — market-implied probability, displayed
   historical hit rate, configured-lens count, largest model–market difference, OVER/UNDER side,
   "markets" / "market entries."
3. **No implementation-time decisions remain** — the Play column is resolved to "Side" (it renders
   `prop.direction`); nothing is deferred.
4. **IDs / ordering / thresholds / selections unchanged** — each item's "explicit non-change" pins
   what stays fixed; change type is copy / label / tooltip / framing only.
5. **Completion claim limited** — see "Scope of this remediation (narrowed)" above; this addresses
   the identified authority-language findings only, not product-wide structural conformance.

*Note: Rev 3 (commit c1f2dae) already incorporated all five Rev-3 corrections; this Final pass
verified them against the approval standards and changed no replacement text — only this check and
the title.*

## Approval question

If these exact changes are implemented — **copy, labels, tooltips, and framing only, with every
ranking, threshold, and selection unchanged** — will the live product align with the frozen contract
**on the identified authority-language findings**? If yes, open the remediation implementation gate
(suggested order P1 → P2 → P3 → P4 → P5). If no, revise this spec. No customer-facing copy is changed
until this spec is approved.
