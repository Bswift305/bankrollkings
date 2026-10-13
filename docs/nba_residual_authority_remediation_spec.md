# NBA Residual-Authority Remediation Specification (frozen · 2026-10-13)

**Status: SPECIFICATION ONLY. No code changed. Do not implement until approved.** Freezes the eight
rulings on the residual customer-facing authority found in
`docs/nba_p0_residual_authority_addendum.md` (inventory). It is a **separate, reversible commit** —
**never an amendment to `9fcf691`** (Commit C). Companion to `docs/nba_p0_remediation_spec.md`.

**Hard constraints:** every change is **NBA-only**, guarded behind the existing fail-safe
`is_nba_props` flag (default False) or applied on the NBA render path (`render_nba_props_page`).
NFL, NCAAF, WNBA, and MLB output must remain **byte-for-byte unchanged** (they render through
`render_props_screener_page` with `is_nba_props=False`). No ranking/threshold/selection change beyond
the eight rulings. Surface: the authenticated NBA props page (`templates/props.html`, builder
`build_live_props_board`, enrichment, `render_nba_props_page`).

Class key: **COPY** = text only; **BEHAVIORAL** = logic/membership/routing.

---

## R1 — "Edge" → relabel "Market lean gap" (COPY)

**It is a market fact, not a BK edge.** `edge_pct = lean_gap = round(abs(over_rate − under_rate),1)`
(`app.py:5332, 5488, 11915`).

| Location | Current | Replacement (NBA only) |
|---|---|---|
| `props.html:491` | `<th>Edge</th>` | `<th>Market lean gap</th>` (or a short header + the explanatory text below) |
| `props.html:542` | `{{ edge_pct }}%` … label **"Edge"** | value unchanged; label **"Market lean gap"** |
| `props.html:564` | `… Edge {{ edge_pct }}%` | `… Market lean gap {{ edge_pct }}%` |

Explanatory text to attach (tooltip or the glossary row for this column): **"Difference between the
market-implied Over and Under probabilities."** No value, membership, or ordering change.

---

## R2 — "EV" → remove from the NBA board (BEHAVIORAL, presentation)

`ev_pct` is `''` for NBA (`app.py:11916, 12038`); `props.html:537` tests `is not none`, so an empty
string renders a defective "**% EV**".

| Location | Current | Replacement (NBA only) |
|---|---|---|
| `props.html:537–538` | `{% if prop.ev_pct is not none %} … % EV` | For NBA, skip the EV branch entirely (guard the branch on `not is_nba_props`), so the cell falls through to the existing `lean_strength` / Market-lean / book display. |

No membership/ordering change. (Non-NBA keeps EV.)

---

## R3 — "Fair" → relabel "De-vigged market price" (COPY)

`fair_price = prob_to_american_odds(lean_prob/100)` (`app.py:5491`) — the de-vigged market implied
probability as American odds. **Never "fair value."**

| Location | Current | Replacement (NBA only) |
|---|---|---|
| `props.html:564` | `Fair {{ '+' if fair_price>0 }}{{ fair_price }}` | `De-vigged market price {{ '+' if fair_price>0 }}{{ fair_price }}` |

No value/membership/ordering change.

---

## R4 / R5 — Model outputs → retain only under an explicit Legacy label (COPY + BEHAVIORAL)

`model_prob = calibrated_sim_hit_probability` (`app.py:11891, 12446`); `core_model_read` is model
text. These are BK model estimates.

| Location | Current | Replacement (NBA only) |
|---|---|---|
| `props.html:558` | `<summary>Model Read</summary>` | `<summary>Legacy model estimate</summary>` |
| `props.html:562` | `{{ core_model_read }}` | kept, but the Model-Read `<details>` block carries the banner below |
| `props.html:564` | `… Model {{ model_prob }}%` | `… Legacy model {{ model_prob }}%` |

Required banner at the top of the NBA Model-Read `<details>` body: **"Legacy model estimate — not
validated and not used for ordering or selection."** These values must not drive sort/membership
(they do not today; the NBA default order is `tipoff` and no filter uses them). If a clean Legacy
treatment is not wanted for a given field, that field is removed from the NBA row instead; the
computation persists internally either way.

---

## R6 — "Simulation Leaders" → remove the NBA customer leaderboard entirely (BEHAVIORAL)

A ranked "leaders / strongest / most weight" authority; a Legacy label would **not** cure it.

**Exact current wording** (`props.html:329–341`): kicker **"Simulation Leaders"**; note **"The
board's strongest simulation reads … Live Authority reads carry the most weight; use them as
support … not on their own."**; rows list `calibrated_sim_hit_probability`% + `simulation_authority`.

| Location | Current | Replacement (NBA only) |
|---|---|---|
| `props.html:329–341` (the Simulation Leaders `.parlay-surface-soft` div) | rendered for NBA | Guard the **entire block** on `{% if not is_nba_props %}`, so it does not render on the NBA board. The sibling **Team Prior Leaders** (`props.html:316–328`, R8) is a separate div and stays. |

`build_board_intelligence_summary` / `top_sims` (`app.py:4105, 4123`) **stay** — the computation is
preserved internally (and may appear on a future, appropriately labeled research surface). Side panel
only; no main-board membership/ordering change.

---

## R7 — "Best Over/Under Plays (70%+)" → remove the confidence gate and the framing (BEHAVIORAL)

The only membership item. Current `/sports/nba/props/overs|unders` (reached from
`dashboard.html:1760` and the `/props/overs|unders` redirects) set `filter_type ∈ {overs,unders}`,
and `build_live_props_board` gates membership to
**`direction == OVER/UNDER` AND `confidence >= 70` AND `play_verdict == 'PLAY'`**
(`app.py:38416–38419`); the card title reads **"Best Over Plays (70%+)" / "Best Under Plays (70%+)"**
(`props.html:409–410`).

**Replacement (NBA only), in `render_nba_props_page`:** coerce the legacy view to the ordinary board
with **only the factual direction filter** applied —
- `filter_type == 'overs'` → `filter_type = None`, `direction_filter = 'over'`
- `filter_type == 'unders'` → `filter_type = None`, `direction_filter = 'under'`

so no confidence gate and no `play_verdict` gate are applied — exactly the ordinary NBA board that
`?direction=over` / `?direction=under` already produces. The title falls through to the ordinary
board title (no "Best … Plays (70%+)").

**Legacy-URL handling:** `/sports/nba/props/overs`, `/sports/nba/props/unders`, and the
`/props/overs`, `/props/unders` redirects all resolve to the direction-filtered ordinary board. The
title guard `props.html:409–410` is additionally made `… and not is_nba_props` (defense in depth);
after coercion `filter_type` is never `overs`/`unders` on the NBA path, so the branch is dead for NBA.

**Mandatory proof (as directed):** a test must show that for a fixed candidate set, the coerced board
equals **`direction`-filtered only**, i.e.:
1. its row set = `{ rows with that direction }` — identical to `?direction=over|under` with no other
   filter; and
2. the rows it **adds back** versus the old gate are **exactly** those with `confidence < 70` (or
   `play_verdict != 'PLAY'`) in that direction — nothing else changes; and
3. the normal Over/Under **direction** filters remain available and still exclude the opposite side
   (no OVER rows on the unders board, no UNDER rows on the overs board).

---

## R8 — Team Prior Leaders → keep (no change)

`props.html:316–328`, fed by `board_intelligence.top_priors`. Already captioned "context for the
row, not a pick by itself." **Keep as-is, provided it affects neither membership nor ordering** — it
does not (a side panel; `top_priors` is not a board filter or sort key). No change; this line is here
only to record that it was reviewed and ruled conformant.

---

## NBA-only guards (summary)

| Ruling | Mechanism | Non-NBA effect |
|---|---|---|
| R1, R3 | `is_nba_props` conditional swaps the label text | none (keep "Edge"/"Fair") |
| R2 | `is_nba_props` guards the EV branch off | none (keep EV) |
| R4/R5 | `is_nba_props` swaps the summary + adds the Legacy banner | none (keep "Model Read") |
| R6 | `{% if not is_nba_props %}` around the Simulation Leaders div | none (keep the block) |
| R7 | `render_nba_props_page` coerces `overs`/`unders` filter_type (NBA render path only) | none (only NBA has these tabs/links) |

No change touches `render_props_screener_page`, `get_sort_params`, or any non-NBA route.

---

## Verification (to run before close)

1. **`qc_nba_commit_c_guard.py` extended (or a sibling QC):** render `props.html` for both views ×
   all five sports and assert, for NBA: label is "Market lean gap" not "Edge", "De-vigged market
   price" not "Fair", summary is "Legacy model estimate" with the banner, no "% EV", no Simulation
   Leaders block; and for NFL/NCAAF/WNBA/MLB (explicit-False **and** omitted flag): "Edge", "Fair",
   "Model Read", EV, and the Simulation Leaders block all still present (unchanged).
2. **R7 membership proof:** the three assertions in R7 above, via `build_live_props_board` on a fixed
   candidate set (or `render_nba_props_page` through the test client) — coerced board = direction-only;
   added-back rows = exactly the sub-70 / non-PLAY rows; opposite direction still excluded.
3. **Route smoke:** `/sports/nba/props/overs` and `/unders` return 200 and are byte-identical to
   `/sports/nba/props?direction=over|under`.
4. **Live production visual check (authenticated):** NBA page shows the relabels and no Simulation
   Leaders / no "Best … Plays"; NFL/MLB/WNBA/CFB pages unchanged. (Covers Commit C + this commit
   together, per the ruling.)

---

## Rollback

One reversible commit. `git revert <sha>` restores every item above (labels, EV, Model-Read summary,
the Simulation Leaders block, and the `overs`/`unders` gate) with no effect on `9fcf691` or any
non-NBA sport. No data migration, no snapshot/schema change, nothing stateful — a pure
template + render-path change.

---

## Out of scope / not changed

- `9fcf691` (Commit C) — not amended.
- Non-NBA sports — unchanged.
- `build_board_intelligence_summary`, `build_featured_nba_top_plays`, and the model/sim computations
  — preserved internally; only their NBA customer presentation changes.
- Nothing is implemented in this spec.
