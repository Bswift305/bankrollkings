# PropScore / Authority Incident Containment Specification (Rev 2 — frozen)

**Read-only specification. No implementation, no code.** Governing decisions (**final**):
**PropScore v1 → research status `Failed`; operational condition `Quarantined`.** Scope: PropScore v1
only. Rev 2 removes every implementation-time choice — **one behavior per surface, frozen.** Dated
2026-10-09.

Governing principle: *a failed mechanism may remain visible as part of the historical record; it may
not continue exercising authority over live customer decisions.*

> Rev 2 changes vs Rev 1: every "may / if desired / option" is replaced by a single frozen behavior;
> the NFL-props default, Top-20 identity, Green Light ordering, marketing handling, and the
> Failed-mechanism live-page rule are now decided, not deferred.

---

## 1. NFL props screener — ordering (FROZEN)

- **Default sort becomes `player` (A→Z).** Chosen because it is neutral and observable and exercises
  zero predictive authority. (Not `confidence` — it restates the de-vigged price; not `prop_score` —
  quarantined.)
- **The `prop_score` sort option is removed** from the NFL sort dropdown (`props.html:423`). Sorting
  by it is ranking authority.
- `app.py:32194` default changes from `'prop_score'` to `'player'`; the internal "-EV" comment at
  `32192-93` is deleted (that claim is unestablished).
- **Membership is unchanged on this surface** — the screener never *filtered* by PropScore, it only
  *ordered* by it. Same props, new default order.

## 2. NFL Spots — membership & behavior (FROZEN)

- **The "Top PropScore plays" section (`sp_top`, `app.py:45486-45516`) is removed** from the live
  page. Its entire basis is PropScore selection/ranking/tiering.
- **The `PropScore ≥ 10` floor and `PropScore ≥ 20` premium tier are removed** with it; nothing
  re-populates the section — it is gone, not re-based. `sp_premium_count` is removed.
- **What remains on NFL Spots:** the **wind-under** section (language per §7) and the
  **injury-change-timing** section. The page subtitle (`nfl_spots.html:47`) is rewritten to:
  *"Two situational signals this week — wind-driven passing unders and injury-change timing."* (drops
  "validated PropScore top plays").

## 3. NFL Top-20 board — identity & ordering (FROZEN)

- **The PropScore candidate block (`app.py:44086-44104`) is removed.** Prop rows have no rank key
  other than `prop_score`, so **they drop entirely; the board becomes totals-only** (wind / QB-out /
  model totals from block 2).
- **The board is renamed "NFL Totals Board."** The "Top-20" framing is dropped — it is no longer a
  cross-market ranked-by-edge top-20.
- **Row count:** show the totals candidates that exist, **up to 20, with no padding** (the existing
  `cands[:20]` slice stays; it simply has fewer candidates). If fewer than 20 totals qualify, show
  fewer.
- **Ordering of remaining rows:** unchanged — the existing totals `base` (wind / QB-out / model).
  The wind tier label is handled in §7. (The totals surface's own model-lean conformance is a
  separate, pre-existing matter, not part of this incident.)

## 4. Marketing assets (FROZEN)

- **`weekly_cards.py` no longer emits PropScore-selected cards** (`top` / `premium` / `floor` /
  `hitlist`) and **no longer emits "validated / proven edge" captions.** The generator code is
  **retained in source** (history/reproducibility) but **not invoked for published output.**
- Any wind-under card uses §7 language.

## 5. Customer-facing claims (FROZEN)

Strip every PropScore authority claim; replace with the accurate label. Where PropScore is still
*shown* (Formula Lab, any residual display), the single frozen label is:
**"PropScore v1 — research artifact; not validated (our clean holdout did not confirm it). Not used
for live selection."**

| Surface | Current | Frozen replacement |
|---|---|---|
| `nfl_board.html:44` | "VALID" badge "backtested edge (PropScore, wind)" | Remove the PropScore "VALID" badge (wind per §7). |
| `nfl_board.html:48` | "Validated plays have a real backtested ROI" | Remove. |
| `nfl_board.html:64` | "a validated PropScore play… proven" | Remove the PropScore clause (board is totals-only, §3). |
| `nfl_spots.html:47,77,78,128` | "validated PropScore", "held out of sample", "out-of-sample-confirmed… monotonic" | Removed with `sp_top` (§2). |
| `cfb_board.html:45` | "…NFL PropScore… do [have a backtested edge]" | "CFB has no backtested edge in our record — every play here is a **model lean, not a proven edge**." |
| `nfl_formula_lab.html:15,31,61` | "PropScore Backtest" | Relabel to the frozen research-artifact label above. |
| `weekly_cards.py:13,344,407,417-418,467,752` | "the validated edge / Our proven edge" | Removed with the PropScore cards (§4). |

## 6. Green Light — ordering (FROZEN behavioral decision)

**Line-state becomes INFORMATIONAL ONLY; it no longer exercises ordering authority.**

- **`app.py:30957-30958`:** the sort key changes from `(eligible, convergence, opp_score)` to
  **`(convergence, opp_score)`** — plays order by the observable **configured-lens count**, then
  opp_score. `eligible` is **removed from the sort key.** (Lenses are Under Review; ordering
  unpriced-first granted them edge authority.)
- **Display:** the badge (`green_light.html:83`) still *shows* line-state but as a neutral,
  non-prioritizing label: **"Line unmoved" / "Line moved."**
- **Copy (observable, no mispricing claim):**
  - `:48` "the number hasn't caught up" → **"the line is unchanged or softer since it opened"**
  - `:56` "the number hasn't moved to price it in" → **"the line hasn't moved since open"**
  - `:92` "'eligible' only means the number hasn't yet moved to it" → **"'line unmoved' means the
    posted number has not moved since open — not that the play will hit"**
  - `app.py:30837-30843, 30849-30850` gate notes/docstring → describe **line moved / line unchanged
    since open** (observable); no "priced / unpriced / caught up."

## 7. Wind-under — interim language (FROZEN: Option A)

| Surface | Frozen replacement |
|---|---|
| `football_method_board.html:331` | **"Wind-under historical backtest: approximately 55% in the documented sample. Governance status not yet assigned."** |
| `football_method_board.html:357` | "Wind-under rows are highlighted — **historical backtest ~55% in the documented sample; governance status not yet assigned.**" |
| Top-20/Totals wind tier (`app.py:44139`) | tier label **"Backtest ~55% (not yet governed)"** (not "Validated"). |
| `how_we_analyze.html:127,133` generic "validated edge" category | Keep the category wording for now **only** as a defined label; its membership question is **deferred to the Governance Source gate** (recorded; not left silent). |

## 8. Treatment of Failed mechanisms on live pages (FROZEN policy)

A mechanism with research status `Failed` + operational condition `Quarantined` (PropScore v1, and
any future one):

- **May** appear as a **labeled research artifact** (the §5 label) in research/history surfaces
  (Formula Lab) and the future Research Ledger, linking to its lineage record.
- **May not** be a sort key, default sort, filter, threshold, tier, selection input, or board/card
  candidate; **may not** carry "validated / proven / edge / premium / trusted / top signal" language;
  **may not** gate a premium surface.
- **Computation and artifacts are preserved** (not deleted): `calculate_nfl_prop_score.py`, the
  scored CSVs, `validate_nfl_prop_score_oos.py`, and `research/nfl_edge/FINDINGS.md` /
  `PRODUCT_SPEC.md` (each gains a one-line header pointer to the validator). History intact; authority
  removed.

## 9. Visual lock cues (FROZEN)

| Surface | Rendered cue | Frozen treatment |
|---|---|---|
| `matchup.html:330` | gold blue→copper gradient badge (`is_lock`) | Plain `grade-badge`, no gradient — identical to the non-lock branch. |
| `smart_picks_v2.html:885-886` | gold gradient **+ literal "Lock"** | Remove the gradient **and the word "Lock"**; show the neutral value only. |
| `smart_picks_v2.html:928` | `lock_reason` note | Remove the "lock" framing. |
| `parlay.html:160-161` | 🔒 emoji + accent fill | Remove the 🔒 and the accent fill; neutral leg styling. |
| `parlay_formula.html:579` | lock badge glow | Remove the glow; neutral badge. |

(`is_lock` = `confidence ≥ 80`, `app.py:26249` — an NBA/general flag, not PropScore. The flag and
threshold are untouched; only the visual elevation is removed.)

---

## Methodological boundary

PropScore v1 only. The accepted evidence does not establish that every leakage-free formulation
fails; a corrected **v2** is a separate trail (mechanism statement → preregistration → review →
authorization → validation).

## Status

Nine frozen behaviors (§1–§9), no alternatives, no implementation-time choices. **No fixes, no code,
no implementation.** Implementing this spec is a separate authorized gate.
