# PropScore Incident Containment Specification (Final Freeze Candidate)

**Read-only specification. No implementation, no code.** Governing decisions (**final**):
**PropScore v1 → research status `Failed`; operational condition `Quarantined`.** Scope: PropScore v1
only. One explicit, neutral behavior per surface — no options, no implementation-time choices. Dated
2026-10-09.

Governing principle: *a failed mechanism may remain visible as part of the historical record; it may
not continue exercising authority over live customer decisions.* Corollary (this revision): a
replacement that merely swaps one ungoverned authority ordering for another is not containment — the
replacement behavior must be **neutral and observable.**

---

## 1. PropScore removed from ALL live decision surfaces (FROZEN)

Per the frozen contract: **no PropScore value, score, badge, tier, caveated column, or inline ranking
guidance appears on any live decision surface.**

- **NFL props screener (`props.html`):** remove the PropScore display column/value from the rows.
  Default sort frozen to **`player` (A→Z)**; the `prop_score` sort option removed (`props.html:423`);
  `app.py:32194` default `'prop_score'` → `'player'`; the unestablished "-EV" comment at `32192-93`
  deleted. Membership unchanged (same props, no PropScore shown, neutral order).
- **Football method board (`football_method_board.html:544-546, 937-939`):** remove the
  `Prop {{ row.nfl_prop_score }}` cell and `prop_score_detail` from the live rows.
- **NFL Spots, NFL Totals Board, matchup, any live board/card:** no PropScore value, tier, or inline
  guidance (§2–§3, §7).

**PropScore survives ONLY in:** Formula Lab (relabeled research artifact), research archives
(`research/nfl_edge/`), audit records, the preserved scored CSVs, and a future Research Ledger entry.

## 2. NFL Spots — membership & behavior (FROZEN)

- The `sp_top` PropScore section (`app.py:45486-45516`) is **removed**, along with the `≥ 10` floor,
  the `≥ 20` premium tier, and `sp_premium_count`. Nothing re-populates it.
- **Remaining:** the **wind-under** section (§5) and the **injury-change-timing** section. Subtitle
  (`nfl_spots.html:47`) → *"Two situational signals this week — wind-driven passing unders and
  injury-change timing."*

## 3. NFL Totals Board (FROZEN — one neutral behavior)

Replaces the former "NFL Top-20 Board" after the PropScore candidate block (`app.py:44086-44104`) is
removed. **Ordering is neutral/observable — NOT the model's `base`/edge** (ranking by the model edge
would re-create the same ungoverned-authority problem).

- **Name:** **"NFL Totals Board."** No "Top," no "20," no ranked-edge framing.
- **Membership:** game totals only — every scheduled game with a posted total for the week. No props.
- **Ordering (FROZEN, neutral):** **scheduled kickoff time (ascending), then matchup name
  (alphabetical).** The existing `base`/edge is **not** the sort key and is removed as the ordering
  authority.
- **Model read is context, not rank:** each row may *show* the model total read (e.g. "model 44.1 vs
  posted 47") as **labeled context**, which does not reorder the board.
- **Row limit:** none — show every game with a posted total (no `[:20]` cap, no padding).
- **Wind rows:** labeled per §5 ("Backtest ~55% (not yet governed)"), not "Validated."

## 4. Marketing assets (FROZEN — five explicit parts)

In `marketing/generators/weekly_cards.py`:
1. **Disabled generator modes:** the PropScore-selected card modes (`top`, `premium`, `floor`,
   `hitlist` — lines ~338-468, 681-753) are **disabled** (the mode functions are not callable for
   published output).
2. **Dispatch removed:** these modes are **removed from the generator's dispatch/entry list**, so a
   routine run produces none of them.
3. **Publishing prevented:** no PropScore-selected card and no "validated / proven edge" caption is
   produced or published by any path.
4. **Archived assets identified:** existing PropScore "validated edge" images in
   `marketing/content_pack*/` and `marketing/weekly_cards/` are **identified and moved to an archive
   folder**, out of the active/redistributed set. (Already-distributed external copies can't be
   recalled; none is reused.)
5. **Historical records preserved:** the generator source and the archived images are **kept** (not
   deleted) for history/reproducibility.

## 5. Wind-under — interim language (FROZEN)

| Surface | Frozen wording |
|---|---|
| `football_method_board.html:331` | **"Wind-under historical backtest: approximately 55% in the documented sample. Governance status not yet assigned."** |
| `football_method_board.html:357` | "Wind-under rows are highlighted — **historical backtest approximately 55% in the documented sample; governance status not yet assigned.**" |
| NFL Totals Board wind tier (`app.py:44139`) | tier label **"Backtest ~55% (not yet governed)"**. |

## 6. Green Light — ordering + labels (FROZEN)

**Line-state is informational only; it exercises no ordering authority.**

- **Ordering (`app.py:30957-30958`), frozen to:** **configured-lens count (descending), then game
  identifier, then player, then stat (ascending).** `eligible` **and** `opp_score` are **removed**
  from the sort key.
- **Labels match the actual observation (not coarse "moved/unmoved").** `green_light.html:83` badge
  and the gate notes (`app.py:30837-30843`) surface the observed fact, one of:
  - **"Line +X since open"** (number moved up X)
  - **"Line −X since open"** (number moved down X)
  - **"Over price shortened by X"** (price tightened since open)
  - **"No material move or price-shortening since open"**
  These are observable facts, not interpretations; no "caught up / priced in / unpriced edge."
- **Copy:** `:48` "the number hasn't caught up" → **"the line is unchanged or softer since it
  opened"**; `:56` "hasn't moved to price it in" → **"the line hasn't moved since open"**; `:92`
  → **"a flat or softer line since open is an observation, not a prediction that the play will hit."**

## 7. Customer-facing claims (FROZEN)

| Surface | Current | Frozen action |
|---|---|---|
| `nfl_board.html:44,48,64` | "VALID" badge, "Validated plays… backtested ROI", "validated PropScore… proven" | Remove all PropScore validated/proven language (board is totals-only, §3). |
| `nfl_spots.html:47,77,78,128` | "validated PropScore", "held out of sample", "out-of-sample-confirmed… monotonic" | Removed with `sp_top` (§2). |
| `cfb_board.html:33,45` | "best spread & total plays… model lean… NFL PropScore… do" | Replace the framing with exactly: **"CFB markets are ordered by displayed model–market difference. No validated betting edge is claimed."** No "play," no "lean," no PropScore comparison. |
| `nfl_formula_lab.html:15,31,61` | "PropScore Backtest" | Relabel: **"PropScore v1 — research artifact; shipped validation was leakage-contaminated and did not survive a clean holdout; not used for live selection."** |
| `how_we_analyze.html:127,133` | "a **validated edge**, a model lean, or a situational spot… every play is tiered by how much evidence backs it" | The "validated edge" **category cannot remain live** (no Qualified mechanism exists). Replace with: **"We tier each play by how much evidence backs it — a documented backtest result, a model estimate, or a situational note — and show that status openly. No play is labeled a validated edge unless a governance record supports that claim."** |
| `weekly_cards.py` captions | "the validated edge / Our proven edge" | Removed with the cards (§4). |

## 8. Treatment of Failed mechanisms on live pages (FROZEN policy)

A mechanism with status `Failed` + condition `Quarantined` (PropScore v1, and any future one):
- **May** appear **only** in research/history surfaces (Formula Lab, research archives, audit
  records, preserved CSVs, the future Research Ledger) as a **labeled research artifact** linking to
  its lineage.
- **May not** appear on any live decision surface in any form (column, value, badge, tier, caveated
  label, inline guidance), and may not be a sort key, default sort, filter, threshold, tier,
  selection input, or board/card candidate; may not carry "validated / proven / edge / premium /
  trusted / top signal" language; may not gate a premium surface.
- **Computation + artifacts preserved** (not deleted): `calculate_nfl_prop_score.py`, scored CSVs,
  `validate_nfl_prop_score_oos.py`, `research/nfl_edge/FINDINGS.md` / `PRODUCT_SPEC.md` (each gains a
  one-line header pointer to the validator).

## 9. Visual lock cues (FROZEN — one rule)

**One treatment: `is_lock` produces NO visual elevation — a lock renders identically to a non-lock
row, with no special word, color, gradient, icon, or glow.** Concretely:

| Surface | Rendered cue | Frozen treatment |
|---|---|---|
| `matchup.html:330` | gold blue→copper gradient badge | Plain `grade-badge`, no gradient. |
| `smart_picks_v2.html:885-886` | gold gradient + literal "Lock" | Remove the gradient and the word "Lock"; neutral value only. |
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
Nine sections, one explicit neutral behavior each — no alternatives, no implementation-time choices.
**No fixes, no code, no implementation.** Implementing this spec is a separate authorized gate.
