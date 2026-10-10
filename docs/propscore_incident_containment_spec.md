# PropScore Incident Containment Specification (Final Freeze Candidate)

**Read-only specification. No implementation, no code.** Governing decisions (**final**):
**PropScore v1 → research status `Failed`; operational condition `Quarantined`.** Scope: PropScore v1
only. One behavior per surface, frozen — no options, no implementation-time choices. Dated 2026-10-09.

Governing principle: *a failed mechanism may remain visible as part of the historical record; it may
not continue exercising authority over live customer decisions.*

> Final-candidate changes vs Rev 2: (1) PropScore is removed from **all live decision rows**, not
> just from sorting — no caveated column anywhere live; it survives only in research/history
> surfaces. (2) Green Light ordering tie-breaks frozen to neutral fields (no `opp_score`). (3) NFL
> Totals Board fully defined. (4) Marketing handling fully stated (generators / existing assets /
> recurrence). (5) Wind-under interim wording frozen.

---

## 1. PropScore removed from ALL live decision surfaces (FROZEN — the core rule)

Per the frozen contract ("Failed mechanisms do not appear as live signals"): **no PropScore value,
score, badge, tier, or caveated column appears on any live decision surface.** This means:

- **NFL props screener (`props.html`):** remove the PropScore **display column/value** from the
  rows (not just the sort). Default sort frozen to **`player` (A→Z)**; the `prop_score` sort option
  removed from the dropdown (`props.html:423`); `app.py:32194` default `'prop_score'` → `'player'`;
  the unestablished "-EV" comment at `32192-93` deleted. Row membership unchanged (same props, no
  PropScore shown, new neutral order).
- **Football method board (`football_method_board.html:544-546, 937-939`):** remove the
  `Prop {{ row.nfl_prop_score }}` cell and `prop_score_detail` from the live rows.
- **NFL Spots, NFL Totals Board, matchup, any live board/card:** no PropScore value or tier (see
  §2–§4).

**PropScore survives ONLY in (history / reproducibility, §8):** the **Formula Lab** (relabeled
research artifact), research archives (`research/nfl_edge/`), audit records, the preserved scored
CSVs, and a future Research Ledger entry.

## 2. NFL Spots — membership & behavior (FROZEN)

- The "Top PropScore plays" section (`sp_top`, `app.py:45486-45516`) is **removed** from the live
  page, along with the `PropScore ≥ 10` floor and `PropScore ≥ 20` premium tier and
  `sp_premium_count`. Nothing re-populates it.
- **Remaining on NFL Spots:** the **wind-under** section (§5 language) and the **injury-change-timing**
  section. Subtitle (`nfl_spots.html:47`) → *"Two situational signals this week — wind-driven passing
  unders and injury-change timing."*

## 3. NFL Totals Board (FROZEN — full definition)

Replaces the former "NFL Top-20 Board" after the PropScore candidate block (`app.py:44086-44104`) is
removed.

- **Name:** **"NFL Totals Board."** No "Top," no "20," no ranked-edge framing.
- **Membership:** **game totals only** — every qualifying game-total candidate for the week from the
  existing totals block (wind-under / QB-out / model-total leans). **No props.**
- **Ordering:** the existing totals `base` (wind / QB-out / model), **descending** — relabeled as
  **model leans**, not "top/validated" plays. The wind tier label per §5.
- **Row limit:** **no fixed cap and no padding** — show exactly the qualifying game totals for the
  week (typically ~12–16). The former `cands[:20]` "20" cap/identity is dropped.
- **When fewer than 20 exist** (the normal case): the board simply shows that many rows. There is no
  "fill to 20," no "top 20," no implied completeness or ranking authority.

## 4. Marketing assets (FROZEN — three parts)

- **Generators that stop producing PropScore content:** in `marketing/generators/weekly_cards.py`,
  the PropScore-selected card builders (`top` / `premium` / `floor` / `hitlist`, lines ~338-468,
  681-753) **no longer produce published output**, and no caption uses "validated / proven edge."
- **Existing assets:** already-generated PropScore "validated edge" card images are **retired from
  the active marketing set** (moved to an archive folder, not redistributed). Already-distributed
  external copies cannot be recalled, but none is reused going forward.
- **Recurrence prevention:** the PropScore card builders are **guarded off** (produce nothing)
  pending a governed basis; a card may use "validated" **only** if a governance record supports the
  claim. No future card selects or ranks by a `Failed`/`Quarantined` mechanism.

## 5. Wind-under — interim language (FROZEN)

| Surface | Frozen wording |
|---|---|
| `football_method_board.html:331` | **"Wind-under historical backtest: approximately 55% in the documented sample. Governance status not yet assigned."** |
| `football_method_board.html:357` | "Wind-under rows are highlighted — **historical backtest approximately 55% in the documented sample; governance status not yet assigned.**" |
| NFL Totals Board wind tier (`app.py:44139`) | tier label **"Backtest ~55% (not yet governed)"** — not "Validated". |
| `how_we_analyze.html:127,133` generic "validated edge" category | wording retained as a defined label; its membership question is recorded as **deferred to the Governance Source gate** (not silent). |

## 6. Green Light — ordering (FROZEN behavioral decision)

**Line-state is informational only; it exercises no ordering authority.**

- **`app.py:30957-30958` sort key is frozen to:** **configured-lens count (descending), then game
  identifier, then player name, then stat (all ascending, neutral tie-breaks).** **`eligible` is
  removed** from the key; **`opp_score` is removed** from the key (both are Under-Review concepts and
  may not grant ordering authority).
- **Display only:** `green_light.html:83` badge shows **"Line unmoved" / "Line moved"** — neutral,
  non-prioritizing.
- **Copy (observable, no mispricing claim):**
  - `:48` "the number hasn't caught up" → **"the line is unchanged or softer since it opened"**
  - `:56` "the number hasn't moved to price it in" → **"the line hasn't moved since open"**
  - `:92` "'eligible' only means the number hasn't yet moved to it" → **"'line unmoved' means the
    posted number has not moved since open — not that the play will hit"**
  - `app.py:30837-30843, 30849-30850` gate notes/docstring → **line moved / line unchanged since
    open** (observable); no "priced / unpriced / caught up."

## 7. Customer-facing claim removals (FROZEN)

Strip every PropScore authority claim:

| Surface | Current | Frozen action |
|---|---|---|
| `nfl_board.html:44,48,64` | "VALID" badge, "Validated plays… backtested ROI", "validated PropScore… proven" | Remove all PropScore validated/proven language (board is totals-only, §3). |
| `nfl_spots.html:47,77,78,128` | "validated PropScore", "held out of sample", "out-of-sample-confirmed… monotonic" | Removed with `sp_top` (§2). |
| `cfb_board.html:45` | "…NFL PropScore… do [have a backtested edge]" | "CFB has no backtested edge in our record — every play here is a **model lean, not a proven edge**." |
| `nfl_formula_lab.html:15,31,61` | "PropScore Backtest" | Relabel: **"PropScore v1 — research artifact; shipped validation was leakage-contaminated and did not survive a clean holdout; not used for live selection."** (Formula Lab is a research surface, §8.) |
| `weekly_cards.py` captions | "the validated edge / Our proven edge" | Removed with the cards (§4). |

## 8. Treatment of Failed mechanisms on live pages (FROZEN policy)

A mechanism with status `Failed` + condition `Quarantined` (PropScore v1, and any future one):

- **May** appear **only** in research/history surfaces — Formula Lab, research archives, audit
  records, preserved CSVs, the future Research Ledger — as a **labeled research artifact** linking to
  its lineage.
- **May not** appear on any **live decision surface**, in any form (no column, value, badge, tier,
  caveated label), and may not be a sort key, default sort, filter, threshold, tier, selection input,
  or board/card candidate; may not carry "validated / proven / edge / premium / trusted / top
  signal" language; may not gate a premium surface.
- **Computation + artifacts preserved** (not deleted): `calculate_nfl_prop_score.py`, scored CSVs,
  `validate_nfl_prop_score_oos.py`, `research/nfl_edge/FINDINGS.md` / `PRODUCT_SPEC.md` (each gains a
  one-line header pointer to the validator).

## 9. Visual lock cues (FROZEN)

| Surface | Rendered cue | Frozen treatment |
|---|---|---|
| `matchup.html:330` | gold blue→copper gradient badge (`is_lock`) | Plain `grade-badge`, no gradient. |
| `smart_picks_v2.html:885-886` | gold gradient **+ literal "Lock"** | Remove the gradient **and the word "Lock"**; neutral value only. |
| `smart_picks_v2.html:928` | `lock_reason` note | Remove the "lock" framing. |
| `parlay.html:160-161` | 🔒 emoji + accent fill | Remove the 🔒 and the accent fill; neutral styling. |
| `parlay_formula.html:579` | lock badge glow | Remove the glow; neutral badge. |

(`is_lock` = `confidence ≥ 80`, `app.py:26249`; flag/threshold untouched — only the visual elevation
removed.)

---

## Methodological boundary
PropScore v1 only. A corrected **v2** is a separate trail (mechanism statement → preregistration →
review → authorization → validation).

## Status
Nine sections, one frozen behavior each, no alternatives or implementation-time choices. **No fixes,
no code, no implementation.** Implementing this spec is a separate authorized gate.
