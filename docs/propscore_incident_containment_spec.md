# PropScore Incident Containment Specification

**Read-only specification. No implementation, no code, no redesign, no v2 work.** Translates the
accepted governance decision into exact, reviewable changes. Governing decisions (final, not
recommendations): **PropScore v1 → research status `Failed`; operational condition `Quarantined`.**
Scope is **PropScore v1 only** (a leakage-free v2 is a separate mechanism-statement → preregistration
→ review → authorization → validation trail). Dated 2026-10-09.

Governing principle: *a failed mechanism may remain visible as part of the historical record; it may
not continue exercising authority over live customer decisions.*

> **Note:** several items below change **ranking, filtering, and membership** — that is the point of
> a quarantine, and those changes are documented explicitly (Deliverable 2), not hidden. Implementing
> this spec is a **separate authorized gate**; this document only specifies it.

---

## 1. Ranking & Ordering Containment

| Surface | File:line | Current authority | Proposed post-quarantine behavior |
|---|---|---|---|
| **NFL props screener** | `app.py:32194`; `38469-38471`; `props.html:423` | PropScore is the **default sort** ("Prop Score (best)") and a selectable sort | **Remove PropScore as default**; new default = **`player`** (alphabetical — neutral, observable, no predictive authority). **Remove the `prop_score` sort option** from the NFL dropdown (sorting by it is ranking authority). PropScore may remain a **displayed, caveated column**, not a sort key. *(Also: the internal comment at `32192-93` asserts confidence "ranks the most -EV plays first" — that -EV claim is unestablished and should not be the stated rationale; pick the neutral default on its own merit.)* |
| **NFL Spots "Top PropScore plays"** (`sp_top`) | `app.py:45486-45516` | PropScore **selects** (≥10), **ranks** (desc), **truncates** (top N), **tiers** (premium ≥20) | **Remove the `sp_top` section** from the live surface entirely — its whole existence is PropScore authority. NFL Spots keeps its non-PropScore sections (wind-under → §7; injury-change timing). |
| **NFL Top-20 board** | `app.py:44086-44102`, `44154-44155` | PropScore props are candidates with **`base = prop_score`**, tier **"Validated"**, merged + ranked into the top 20 | **Remove the PropScore candidate block (`44086-44104`).** Props have **no rank key other than `prop_score`**, so they drop from the board; it becomes a **totals board** (wind / QB-out / model totals). Remove the "Validated" tier *as applied to PropScore* (wind "Validated" → §7). |
| **Marketing card generators** | `weekly_cards.py:338-468, 681-753` | PropScore **selects + orders** published `top`/`premium`/`floor`/`hitlist` cards | **Stop generating PropScore-selected cards** (and the "validated/proven edge" captions, §3). Wind-under cards follow §7; no PropScore-ranked card is published. |

## 2. Selection & Membership Containment (stated explicitly)

Removing the gates **changes which plays appear and in what order.** This is expected and intended:

- **Remove `PropScore ≥ 10` floor** (`app.py:45501`, `_NFL_SPOTS_PROPSCORE_FLOOR`): the "Top Plays"
  membership no longer exists as a PropScore set — **the section is removed**, not re-populated. (If
  a future surface shows props, it must do so on a non-leaked basis — out of scope here.)
- **Remove `PropScore ≥ 20` premium gate** (`45510`, `_NFL_SPOTS_PROPSCORE_PREMIUM`): the "premium"
  (★) tier **disappears**; no play is tiered premium by PropScore. `sp_premium_count` → 0 / removed.
- **Remove PropScore ranking authority** (screener default, `sp_top` sort, Top-20 `base`): the NFL
  props screener's **default order changes** (to `player`); the **Top-20 board loses all prop rows**
  and becomes totals-only; any board slot formerly held by a prop is filled by the next totals
  candidate. **Row counts and ordering on these surfaces will visibly change.**
- Net effect, stated plainly: **the NFL "Top PropScore plays" board and the prop rows of the Top-20
  board go away; the props screener stops leading with PropScore.** Nothing is silently preserved as
  authority.

## 3. Customer-Facing Claims — accurate authority, not softer authority

| Surface | Current visible claim | Replacement |
|---|---|---|
| `nfl_board.html:44` | green **"VALID"** badge: "backtested edge (PropScore, wind)" | Remove the PropScore "VALID" badge. (Wind handled in §7.) |
| `nfl_board.html:48` | "**Validated** plays have a real backtested ROI" | Remove — no PropScore play is validated. |
| `nfl_board.html:64` | "a **validated** PropScore play… because one is **proven**" | Remove the PropScore clause; the board is totals-only post-quarantine. |
| `nfl_spots.html:47` | "validated PropScore top plays…" | Remove the PropScore clause from the three-signal subtitle. |
| `nfl_spots.html:77,78,128` | "Validated PropScore", "held out of sample… the validated model", "out-of-sample-confirmed… monotonic both seasons" | Remove with the `sp_top` section (§1). These claims are **refuted** by the clean holdout. |
| `cfb_board.html:45` | "…NFL PropScore and wind-unders **do** [have a backtested edge]" | "…CFB has no backtested edge in our record — every play here is a **model lean, not a proven edge**." (drop the PropScore comparison). |
| `nfl_formula_lab.html:15,31,61` | "PropScore Backtest" framing | Re-label as **research/history** with a caveat (§4): "PropScore v1 — research artifact; its shipped validation was leakage-contaminated and did not survive a clean holdout. Not used for live selection." |
| `weekly_cards.py:13,344,407,417-418,467,752` | "the validated edge", "Our proven edge", "Validated edge (PropScore)" | Remove PropScore cards + captions (§1). |

Accurate replacement vocabulary for PropScore anywhere it is still *shown*: "a prop score
(**research artifact; not validated** — our clean holdout did not confirm it)". No "validated /
proven / out-of-sample-confirmed / premium signal / edge."

## 4. Historical Preservation

**Remains visible (history intact):**
- `calculate_nfl_prop_score.py` (the computation) and the scored CSVs — unchanged.
- `validate_nfl_prop_score_oos.py` — the clean holdout that found the inversion (this is the record).
- `research/nfl_edge/FINDINGS.md`, `PRODUCT_SPEC.md` — kept as archive; a short header note added that
  the PropScore "OOS" claim was later shown leakage-contaminated (pointer to the validator). *(Header
  note is documentation, not a model/finding change.)*
- **Formula Lab** — kept, re-labeled as a research/backtest artifact with the caveat above.
- A future **Research Ledger** entry: PropScore v1 → Failed / Quarantined, with this lineage.

**Removed from authority:**
- Live **ranking** (screener default + option; `sp_top` sort; Top-20 prop base).
- Live **filtering** (≥10 floor).
- Live **prioritization / tiering** (≥20 premium; "Validated" tier).
- Live **"validated / proven"** messaging (§3).

## 5. Green Light Exception Resolution

These assert discovery of an **unpriced edge** on **Under-Review** lenses → **nonconforming.** Replace
with observable line-state language:

| File:line | Current | Nonconforming? | Replacement (observable) |
|---|---|---|---|
| `green_light.html:48` | "the number hasn't **caught up**" | Yes — implies the market is lagging a correct signal | "the **line is unchanged or softer since it opened**" |
| `green_light.html:56` | "the number hasn't **moved to price it in**" | Yes | "the **line hasn't moved since open**" |
| `green_light.html:83` | badge "**Eligible** / Priced in" | Yes — "eligible" implies an actionable edge | badge "**Line unmoved** / **Line moved**" |
| `green_light.html:92` | "'eligible' only means the number hasn't yet moved to it" | Partly (disclaimer) — rephrase to match | "'line unmoved' means the posted number has not moved since open — **not** that the play will hit" |
| `app.py:30837-30843, 30849-30850` gate notes/docstring | "market already moved to it" / "not priced" / "convergence not yet priced" | Yes (internal, drives the badge) | describe as **line moved / line unchanged since open** (observable), no "priced/unpriced" |
| `app.py:30957-30958` | ranks **eligible (unpriced) first** | Selection choice beyond copy | Keep the ordering if desired, but **re-describe** it as "line-unmoved first" (observable), not "unpriced edge first". *(Any change to the ordering itself is a separate decision; the contract issue is the claim, which the relabeling resolves.)* |

## 6. Visual Authority Cue Resolution (what the customer sees)

Treat all elevated "lock" presentation as authority and neutralize it:

| File:line | Rendered cue | Treatment |
|---|---|---|
| `matchup.html:330` | gold **blue→copper gradient** badge for `is_lock` | Render with the **plain `grade-badge`** (no gradient) — identical to the non-lock branch. |
| `smart_picks_v2.html:885-886` | gold gradient **+ literal word "Lock"** appended | Remove the gradient **and the word "Lock"**; show the neutral value only. **(Literal "Lock" is do-not-build — treat as a hard item.)** |
| `smart_picks_v2.html:928` | `lock_reason` note | Remove or neutralize the "lock" framing. |
| `parlay.html:160-161` | **🔒 emoji** + accent fill on lock legs | Remove the 🔒 and the accent fill; neutral leg styling. |
| `parlay_formula.html:579` | lock badge **glow** (box-shadow) | Remove the glow; neutral badge. |

*(`is_lock` = `confidence ≥ 80`, `app.py:26249` — an NBA/general flag, not PropScore. The threshold
and flag are untouched; only the **visual elevation** is removed, so no tier reads as earned
conviction.)*

## 7. Wind-Under Authority Language — **Option A (chosen)**

**Decision recorded: Option A — immediate bounded replacement.** Leaving a live "validated edge"
claim while deferring is worse than a bounded, honest statement now; and wind-under is mechanistically
independent of the PropScore leak, so a bounded factual statement is defensible today.

| File:line | Current | Replacement |
|---|---|---|
| `football_method_board.html:331` | "~55%, our **one validated totals edge**" | "**Wind-under historical backtest: ~55% in the documented sample. Governance status not yet assigned.**" |
| `football_method_board.html:357` | "Wind-under rows are highlighted — **the validated edge**." | "Wind-under rows are highlighted — **historical backtest ~55%; governance status not yet assigned.**" |
| `nfl_board.html:44` / Top-20 wind tier | wind totals tier **"Validated"** (`app.py:44139`) | Re-label the wind tier **"Backtest ~55% (not yet governed)"** — not "Validated". |
| `how_we_analyze.html:127,133` | "a **validated edge**" as a generic tier label | Lower priority (generic, not wind-specific). If the "validated edge" *category* is kept, it needs ≥1 governed member; otherwise rename the category. Defer this generic-category question to the Governance Source gate. |

*(Wind-under's eventual governance status — and whether "validated" can ever return — is adjudicated
by the Governance Source gate, which will create the registry that can document it.)*

---

## Methodological boundary

This specification concerns **PropScore v1 only.** The accepted evidence establishes that v1's
shipped validation is invalid as authority evidence, its dominant leaked component reverses on a
clean holdout, and quarantine is justified. It does **not** establish that every leakage-free
formulation fails. A corrected **PropScore v2** is a separate trail (mechanism statement →
preregistration → review → authorization → validation).

## Deliverable status

Exact behavioral changes (§1–2), customer-facing changes (§3), preservation rules (§4), Green Light
handling (§5), visual-lock handling (§6), and wind-under handling (§7) are all specified. **No fixes,
no code, no implementation.** Implementing this spec is a separate authorized gate.
