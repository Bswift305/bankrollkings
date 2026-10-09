# Contract Conformance Review — live surfaces vs the frozen contract

**Read-only inventory.** No code, UI, wording, governance, or research changes were made. This
checks current customer-facing authority language against the frozen Matchup Page Product Contract
(`docs/matchup_page_product_contract.md`). Remediation entries are **proposals only** — not
implemented. Reviewed 2026-10-09.

## Baseline: the product is mostly conforming

Worth stating first, because it scopes the problem. The honesty ethos is already deep in the live
surfaces: the CFB/NFL boards, favorites, situational, totals, wave, first-half, best-lines and
tracker surfaces repeatedly self-label *"spots, not locks," "candidates, not locks," "context, not
a lock," "the market prices streaks," "not a claim of positive EV," "value-shaped swing, not a
lock."* `best-lines` even states *"not a model edge or bet recommendation."* Those are conforming.
The nonconformances below are **concentrated**, not systemic — mostly tier/headline labels and a
legacy badge, not the body copy.

## 1. Nonconforming Claims

| Surface | Exact language | Underlying status | Why it conflicts |
|---|---|---|---|
| `/matchup/<matchup>` (`matchup.html:255`) | **"Lock"** badge + "highest conviction" | — (NBA/MLB legacy, unaudited) | "Lock" is on the doctrine §7 **do-not-build list**; "highest conviction" asserts authority no mechanism has earned. Hard violation. |
| Green Light (`app.py:30960`, `green_light.html`) | tier **"Highest conviction"** / "Strong context" | lenses **Under Review** (none Qualified) | Translates a lens *count* into a *confidence* claim; implies affirmative authority the Under Review lenses don't have (contract §3, §6). |
| Daily Card (`daily_cards.html:49`) | "the **strongest** 3,4,5-leg tickets… **best of the board**… The finished ticket" | no Qualified selection mechanism | "strongest"/"best of the board" imply governed **selection authority** that does not exist (contract §6). |
| Free-tier feature copy (`app.py:453`) | "Top 3 **highest-confidence** props… with hit rates" | confidence = de-vigged price restated; not Qualified | "highest-confidence" implies earned ranking authority; the board's confidence is the priced number, so it reads as an edge claim it isn't. |
| `/market-edge` sort (`smart_picks_v2.html:583`) | **"Highest Confidence"** sort control | de-vigged price; not Qualified | Presents "confidence" as a quality ranking; sorting by it surfaces the most-priced (often most -EV) rows first — authority the mechanism hasn't earned. |
| CFB board (`cfb_board.html:33,61`) | "the model's **best** spread & total plays, **ranked by edge**" | opponent-adjusted strength = **Baseline** (no demonstrated edge, Audit #1) | "best plays / ranked by edge" exceeds **Baseline**; the body honestly says "candidates, not locks… no validated edge," but the headline claims edge. Headline/body mismatch. |
| NFL Top-20 board (`app.py:44071,44167`) | "the **best** plays across every market, **ranked by edge**" | board signals Under Review / not documented Qualified | Same as CFB: "best/edge" headline exceeds the governed status of the underlying signals. |

Minor / structural (not text claims, noted for completeness):

- `dashboard.html:1713` — CSS class `hr-lock` applied at hit-rate ≥ 80% (vs `hr-strong`). A visual
  "lock" *tier cue*; the class name isn't shown, but the 80% → "lock" styling implies a lock tier.

## 2. Green Light Assessment

- **What it is today:** a convergence *assembly* — it counts how many independent NFL lenses agree
  on a play and gates by the market. Its page intro is **conforming**: *"It does not rank plays by
  'goodness' or spit out a score… Evidence convergence, not a prediction."*
- **Authority it actually has:** none earned. Its lenses (Opportunity, Matchup, Game Identity,
  Coaching, Concentration) are **Under Review** — attribution is still accruing; none is Qualified.
- **Phrases that imply more authority than it has:** the **tier labels** — "**Highest conviction**"
  (≥4 lenses) and "**Strong context**" (3). "Conviction" is a confidence claim; the honest content
  is a *count of agreeing lenses*, not a graded confidence. This is the §6 nonconformance: the
  engine may stay visible, but the tier language must read as research-in-progress.

## 3. Daily Card Assessment

- **What it is today:** a user-convenience **assembly** of 3/4/5-leg tickets from the board pools.
- **The rule that actually constructs it:** cross-game (one leg per game, low correlation),
  weighted toward high-**floor** legs (real historical hit rate at the number) plus one plus-money
  **swing**; payout assumes independence. The build footnote (`daily_cards.html:94`) states this
  **honestly** ("value-shaped swing, not a lock," floors are real hit rates, not projections).
- **Phrases that imply governed selection authority:** the subtitle — "**strongest** 3,4,5-leg
  tickets," "**best of the board**," "The finished ticket, on arrival." "Strongest/best" imply a
  governed *selection*; the card is assembled by the stated rule, not a Qualified selector.

## 4. Additional Surface Audit

Checked board/tool surfaces against Fact / Context / Baseline / Under Review / Legacy / Failed /
Qualified:

- **Conforming:** best-lines (Fact, explicit "not a model edge"); cfb-favorites / situational /
  totals / big-favorites / first-half / wave / football-method-board (all self-label "context /
  spots, not locks," cite samples and break-even); bet-tracker (CLV honesty); cfb-101 ("context
  isn't a lock"). These correctly present as Fact/Context/Baseline.
- **Headline overclaim** (body conforming): **cfb_board** and **NFL Top-20** — "best plays / ranked
  by edge" in the headline vs Baseline/Under-Review reality (see §1).
- **Authority-word-as-ranking:** `/market-edge` "Highest Confidence" and the free-tier
  "highest-confidence props" copy (see §1).
- **Hard violation:** the legacy `/matchup` "Lock" badge (see §1).
- Did **not** find "sharp"/"steam"/"smart money" authority labels in customer copy (good — those
  words appear only in *educational* "what this is / isn't" explanations).

## 5. Remediation Candidates (proposals only — not implemented)

| Surface | Current | Proposed |
|---|---|---|
| matchup.html | "Lock" badge · "highest conviction" | "Most reliable prop attached to this game" (fact), **remove the "Lock" badge** |
| Green Light tiers | "Highest conviction" / "Strong context" | "4 lenses agree · research in progress" / "3 lenses agree" (count-based, no confidence claim) |
| Green Light page | (intro already conforming) | add one line: "Lenses are **Under Review** — convergence is not yet a graded edge." |
| Daily Card subtitle | "the strongest… best of the board… The finished ticket" | "cards **assembled by rule**: cross-game, high-floor legs + one swing — options, not a graded pick" |
| Free-tier copy | "Top 3 highest-confidence props" | "Top 3 props by model read (de-vigged price) + real hit rates" |
| /market-edge sort | "Highest Confidence" | "Market Read (de-vigged price)" — and default-sort by the validated score, not confidence |
| cfb_board headline | "best spread & total plays, ranked by edge" | "model leans vs the number (Baseline — no validated edge), ranked by model gap" |
| NFL Top-20 headline | "best plays… ranked by edge" | "top model reads across markets (status-labeled), ranked by model gap" |
| dashboard hit-rate | `hr-lock` at ≥80% | rename the tier cue to `hr-high` (no "lock" semantics) |

## Recommendation (no authorization requested here)

The gap between the frozen contract and the live product is **small and language-level**, not
structural. The single hard violation is the legacy `/matchup` "Lock" badge; the rest are
tier/headline labels that translate counts or priced numbers into confidence/edge claims. When a
remediation gate is opened, the highest-priority item is the "Lock" badge, then the Green Light and
Daily Card framing (the two surfaces the contract names), then the board headlines and sort labels.
No remediation is implemented in this review.
