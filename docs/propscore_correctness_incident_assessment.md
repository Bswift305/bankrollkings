# PropScore Correctness Incident Assessment

**Read-only assessment. No fixes, no implementation, no governance-state change, no new research.**
Recommends; does not decide. Scope exactly as authorized. Dated 2026-10-09.

**Bottom line up front:** PropScore v1 currently exercises **ranking and selection authority** on
live surfaces and carries **"validated / proven / out-of-sample-confirmed"** copy — but its
validation is **contaminated by target leakage**, and the one clean season-holdout in the repo
shows the dominant component is **anti-predictive out of sample**. The product is making a stronger
evidence claim than our own evidence supports, in the exact way the frozen contract forbids.

---

## 1. Product impact — where PropScore exercises authority

Not just copy. PropScore (`BK_NFL_PropScore`, computed in `calculate_nfl_prop_score.py`, model id
`NFL_PropScore_v1`) **ranks, filters, and selects** on live surfaces:

| Surface | File:line | Authority |
|---|---|---|
| NFL props screener | `app.py:32194`, `38469-38471`, `templates/props.html:423` | **Default sort key** ("Prop Score (best)") — orders every prop by PropScore desc |
| NFL Spots "Top Plays" | `app.py:45501-45514` | **Filters** (`PropScore ≥ 10`), **ranks**, truncates to top N; sets **premium** flag at ≥ 20 |
| NFL Top-20 Board | `app.py:44091`, `44154-44155` | PropScore is the **ranking base**; PropScore rows tiered **"Validated"** and ordered first |
| Marketing cards | `marketing/generators/weekly_cards.py` (top/premium/floor/hitlist) | **Selects + orders** published social cards by PropScore |
| Per-row display | `app.py:28806`, `football_method_board.html:544` | Shows the score + breakdown (display, not ranking) |

**No paywall** gates on it — "premium" here is a visual tier label (★), not access control. But
items 1–4 are **selection/ranking authority**, which is more than language.

## 2. Authority claims (customer-facing)

Beyond `nfl_board.html:64` and `cfb_board.html:45` already known:

- `nfl_board.html:44` — green **"VALID"** tier badge: "backtested edge (PropScore, wind)"; `:48`
  "**Validated** plays have a real backtested ROI."
- `nfl_spots.html:47` — "the three prop signals that **actually held up on real money** — **validated
  PropScore** top plays…"; `:77` section header "**Validated PropScore**"; `:78` "the one prop
  score that **held out of sample**: ≥10 returned +9–11%, ≥20 returned +13–16%… the **validated
  model**"; `:128` "the two **backtested, out-of-sample-confirmed** edges… PropScore is **monotonic**
  (higher score → higher return both seasons)."
- `nfl_formula_lab.html:15,31,61` — "PropScore Backtest" framing.
- `weekly_cards.py:13,344,407,417-418,467,752` — card copy: "**the validated edge**," "**Our proven
  edge**," "**Validated edge (PropScore)**."

These claims assert a **backtested, out-of-sample, proven** edge.

## 3. Evidence lineage — the contradiction

Two internal artifacts make **opposite** claims, and the mechanism explains why.

**Claim of validation — `research/nfl_edge/FINDINGS.md` (2026-08-22) + `PRODUCT_SPEC.md`:**
"Three angles held up across both seasons, on real money: Top Plays `PropScore ≥ 10` → +9.2%/+11.3%,
`≥ 20` → +13.3%/+16.1%… the PropScore ramp is **monotonic (higher score → higher ROI both years)**."
Method stated as "2024 to find, 2025 to confirm." This is the source of all the "validated" copy.

**Refutation — `validate_nfl_prop_score_oos.py` (as of 2026-07):**
- `calculate_usage_stability` feeds each player's **HitRate computed over ALL resolved rows** back in
  as a scoring input → "a row is scored with a feature derived from its own outcome" (**target
  leakage**).
- `UsageStability` carries **the bulk of PropScore's variance (std ~8.7 vs ~2–3** for the genuine
  pre-game features) → "PropScore is essentially that leaked feature."
- A **proper** holdout (build the player profile from the **train season only**, rank the test
  season) **inverts**: 2024↔2025 player hit-rate correlation **≈ −0.09**; "anti-predictive out of
  sample, and must not gate live selection."

**Why both can exist — leakage was present in the "OOS" split too.** FINDINGS.md computed
`BK_NFL_PropScore` (which already contains the all-data `UsageStability`) and *then* split by season.
Because the 2025 rows were scored with a feature derived from 2025 outcomes, the "2025 OOS"
confirmation is **not a true holdout** — it inherits the same leak. The only artifact that builds the
profile from train data **before** scoring the test season is `validate_nfl_prop_score_oos.py`, and it
inverts. **The clean test supersedes the contaminated one.**

- **Which evidence the public claims reference:** the **pre-clean, leakage-contaminated** numbers
  (+9–16%, "monotonic both seasons"). No customer-facing surface references the clean holdout.
- **Chronology (fact, not blame):** the leak was documented ~2026-07; the "validated" FINDINGS and
  the shipped copy are dated ~2026-08 and later, apparently without reconciling the leak.
- **Scope of the contamination:** the leak sits in `UsageStability`, which also drives the separately
  marketed **"Usage / Volume"** angle — so **two of the three "proven" angles share the leaked
  feature**. Only **Wind-under** is mechanistically independent of player hit-rate (see §Additional).
  *(A clean re-test of the pre-game-only components would be needed to say which, if any, survive —
  that is new research and is NOT authorized here.)*

## 4. Governance-status recommendation

*(Reconciled to the sanctioned taxonomy per the Director's authorization — the taxonomy is
{Qualified, Baseline, Under Review, Failed, Legacy, Retired, Data-Gated}; "Quarantined" is an
**operational** condition, not a governance status. My earlier draft's coined "Invalidated" is
withdrawn.)*

**Recommend: governance status = `Failed`; operational condition = `Quarantined`.** (The assessment
recommends; it does not assign either.)

- Not **Legacy** — it was not merely inherited untested; it was tested.
- Not **Under Review** — the clean holdout is conclusive that the dominant component inverts; this is
  not open.
- Not **Retired** — "Retired" implies authority that was once *legitimately earned* and later lost.
  PropScore v1's authority rested on a leakage-contaminated validation, so it was **never legitimately
  earned** — "Retired" would overstate its prior standing.
- **`Failed`** is the honest fit: it was tested and **did not earn authority** (the one clean holdout
  refutes the component carrying most of its variance; our own code says it "must not gate live
  selection").
- **Why `Quarantined` is also required:** unlike a clean Failed candidate that never shipped (e.g.
  Team Form v1), PropScore v1 is **already embedded and exercising live ranking/selection authority
  and "validated" claims.** "Failed" records the evidence verdict; **"Quarantined" is the operational
  step that actually removes the authority** it should never have held. Status ≠ handling; both are
  recommended, neither assigned here.
- **Scope of the recommendation (per the authorization's methodological boundary):** this applies to
  **PropScore v1 only.** It does **not** conclude that every future leakage-free formulation fails. A
  corrected **v2** would require its own mechanism statement, pre-registration, review, authorization,
  and a clean validation trail.

## 5. Minimal safe quarantine (recommendation)

Smallest intervention that stops PropScore exercising authority **while preserving history,
artifacts, and reproducibility**. Principle: **compute and show with a caveat; do not gate, rank,
select, or claim.**

- **Stop it ranking/selecting (the core):** remove PropScore as the **default sort** of the NFL
  props screener (`app.py:32194`); stop the **filter/rank/premium** gate on NFL Spots
  (`45501-45514`); stop PropScore as the **ranking base + "Validated" tier** on the Top-20 board
  (`44091`); stop PropScore-driven **card selection** in `weekly_cards.py`.
- **Strip the claims:** remove "validated / proven / out-of-sample-confirmed / backtested edge"
  wherever it refers to PropScore (§2), and the ≥10/≥20 ROI citations that rest on the leak.
- **Preserve (do NOT delete):** `calculate_nfl_prop_score.py`, the scored CSVs,
  `validate_nfl_prop_score_oos.py`, `FINDINGS.md`/`PRODUCT_SPEC.md`, and the Formula-Lab display —
  PropScore may still be **computed and shown as a number** with an explicit "not validated;
  our holdout inverts" caveat, so history and reproducibility stay intact.

> **Important scope flag:** unlike the completed copy remediation (labels only), this quarantine
> **changes ranking/selection** (default sort, filters, card selection). It therefore needs its own
> explicit authorization and careful verification (IDs/rows preserved, only the *authority* removed),
> and must NOT be folded into a copy pass. This assessment only **recommends** it.

---

## Additional scope

### (a) Green Light "unpriced edge" language — does it imply an unproven edge? **Yes.**
`green_light.html:48` ("the number **hasn't caught up**"), `:56` ("the number **hasn't moved to price
it in**"), `:83` badge ("Eligible / Priced in"), `:92` ("'eligible' only means the number hasn't yet
moved to it, not that it will hit"), and `build_green_light` **ranks eligible (unpriced) plays first**
(`app.py:30957-30958`), with gate notes like "convergence not yet priced" (`30843`). Framing the
market as not having "caught up" to the convergence **presupposes the convergence is right and the
market is lagging** — an implicit unpriced-edge claim, on lenses that are **Under Review** (none
Qualified). The `:92` disclaimer softens it but the eligible-first ranking and the "hasn't caught up"
wording still assert the signal leads the market. **Recommend:** reframe to purely mechanical ("the
line is unchanged or softer since open") with no "caught up / not yet priced" implication; note the
eligible-first ordering is itself a selection choice (beyond copy).

### (b) Visual "lock" authority cues (rendered, not the variable)
The remediation neutralized `matchup.html` text but the **gold gradient badge persists**, and other
surfaces were never touched:
- `matchup.html:330` — `is_lock` renders a blue→copper **gold gradient** badge (elevated tier).
- `smart_picks_v2.html:885-886` — lock OVER gets the **same gold gradient** **and still appends the
  literal word "Lock"**; `:928` adds a `lock_reason`. ← **"Lock" (do-not-build) still visible.**
- `parlay.html:160-161` — lock leg appends a **🔒 emoji** + accent fill.
- `parlay_formula.html:579` — lock badge gets an accent **glow**.
(`is_lock` = `confidence ≥ 80`, `app.py:26249` — an NBA/general flag, independent of PropScore.)
**Recommend:** treat all four as visual-authority exceptions; the `smart_picks_v2` literal "Lock" is
a do-not-build violation on par with the matchup one and should be handled next.

### (c) Wind-under "validated" — **explicitly deferred (with justification).**
`football_method_board.html:331` ("~55%, our one **validated** totals edge") and `:357` ("the
**validated edge**"). (`how_we_analyze.html:127,133` use "validated edge" only as a generic tier
label, not wind-specific.) Wind-under is the **one** of the three FINDINGS.md angles that is
**mechanistically independent of the leaked player hit-rate**, and the clean holdout does **not**
refute it — so it is **not** an urgent incident like PropScore. But it shares FINDINGS.md's
reconstructed-backfill methodology, now under a cloud, and still lacks a frozen governance record.
**Recommend deferring** its "validated" wording to the **Governance Source gate**, which will either
grant it a clean governed record or soften the word — it must not disappear into the backlog.

---

## Authenticated Production Verification (folded into this gate)

- **Deploy landed / no rollback:** ✅ confirmed anonymously — `/pricing` (public) serves the new
  "de-vigged market-implied probability" copy and the old "highest-confidence props" is gone;
  `60226f6` is live.
- **No template failures:** ✅ (strong proxy). All 8 changed templates **compile through the app's
  Jinja environment** with no syntax error, and `build_green_light()` runs and returns tiers + plays
  without exception. The behind-auth risk these guards against — a Jinja error rendering a 500 after
  the auth check — is ruled out.
- **Green Light / Daily Card visual render behind auth:** ⚠️ **not visually confirmed on prod.**
  `/tools/*` return 401 anonymously, and I have no production session (and will not use the user's
  credentials). Template-compile + Python-build make a render failure very unlikely, but a *visual*
  confirmation (tiers read "4+ configured lenses"; Daily Card reads "assembled by rule") needs one
  of: the user logging the built-in browser into bankrollkings.com so I can view/screenshot, or an
  SSM check of the prod journal for post-restart errors. **Outstanding — not closable autonomously.**

## Recommended next steps (for decision — not taken here)
1. Adopt a governance status for PropScore v1 (recommended: **`Failed`**) + the operational
   condition **`Quarantined`**.
2. Authorize the **minimal safe quarantine** (its own gate — touches ranking/selection).
3. Fold the Green Light "unpriced" framing and the remaining **visual "lock" cues** (esp. the
   `smart_picks_v2` literal "Lock") into the exception-resolution work.
4. Carry **wind-under "validated"** into the Governance Source gate.
5. A clean re-validation of PropScore's pre-game-only components is possible but is **new research**,
   explicitly **not** authorized by this assessment.
