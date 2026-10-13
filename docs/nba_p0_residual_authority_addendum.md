# NBA P0 — Residual-Authority Conformance Addendum (read-only)

**Status: INVENTORY + RECOMMENDATIONS ONLY. No code changed. Do not implement until approved.
Do not change non-NBA sports.** Companion to `docs/nba_p0_remediation_spec.md` (frozen §1a–1f) and
`docs/nba_commit_c_characterization.md`. Commit C (`9fcf691`) removed Confidence/Tier/Locks (§1a–1c);
this addendum enumerates the customer-facing authority language on the authenticated NBA props page
(`/sports/nba/props`, template `props.html`, builder `build_live_props_board` + enrichment) that was
**outside** Commit C's frozen scope and now needs a conformance decision.

Date: 2026-10-13. Scope term list (as directed): `Edge`, `EV`, `Fair`, `Model`,
`Simulation Leaders`, `strongest`, `Live Authority`, `Best … Plays`.

**Governance frame (from the doctrine / §1f):** the board presents **market facts** (Fact) and
**Legacy** context ("the market's number," not a BK edge). A de-vigged market number is a Fact; a BK
model/simulation output is Legacy; nothing here is Qualified. Two of the labels below are worse than
"ungoverned" — they are **market facts mislabeled as a BK edge**.

---

## 1. Inventory

| # | Occurrence (customer text) | Location | Source / computation | What it really is | Member­ship / ordering | Shared? |
|---|---|---|---|---|---|---|
| R1 | **"Edge"** column + `{{ edge_pct }}% Edge` | `props.html:491` (th), `541–542` (cell), `564` (detail) | `edge_pct = lean_gap = round(abs(over_rate − under_rate),1)` (`app.py:5332, 5488, 11915`) | **Market fact, mislabeled.** It is the de-vigged market's two-sided lean magnitude, not a BK edge over the market. | No filter. Sortable key exists but the NBA sort control no longer offers it (Commit C). | Shared (renders for all sports) |
| R2 | **"EV"** `{{ ev_pct }}% EV` | `props.html:537–538` | `ev_pct` is set to `''` for the NBA board (`app.py:11916, 12038`) | Effectively **blank** on NBA; where populated elsewhere it is an expected-value model calc. As-is it renders an empty "% EV". | None | Shared |
| R3 | **"Fair"** `Fair {{ fair_price }}` | `props.html:564` | `fair_price = prob_to_american_odds(lean_prob/100)` (`app.py:5491`) | **Market fact, mislabeled.** It is the de-vigged market implied probability expressed as American odds — not a BK "fair" model price. | None | Shared |
| R4 | **"Model"** `Model {{ model_prob }}%` | `props.html:564` | `model_prob = calibrated_sim_hit_probability` (`app.py:11891, 12446`) | **Genuine BK model output** (calibrated simulation hit %). Legacy, not Fact. | None | Shared |
| R5 | `core_model_read` (free text) | `props.html:562` | model-read text carried on the row | **BK model output.** Legacy. | None | Shared |
| R6 | **"Simulation Leaders"** header + **"strongest simulation reads"** + **"Live Authority reads carry the most weight"** | `props.html:330–331`, rows `332–340` | `board_intelligence.top_sims` sorted desc by `calibrated_sim_hit_probability` (`build_board_intelligence_summary`, `app.py:4105, 4123`); `simulation_authority ∈ {LIVE_AUTHORITY, WATCH, CALIBRATION_NEEDED}` (`app.py:12446`) | **BK model leaderboard + authority framing.** "strongest" and "carry the most weight" are edge-authority claims; it is an implicit ranked "best sims" list. | Side panel only — does **not** change the main board's membership or order. | Shared (block renders wherever `board_intelligence` is passed) |
| R7 | **"Best Over Plays (70%+)" / "Best Under Plays (70%+)"** | `props.html:409–410`; reachable from `dashboard.html:1760` (`/props/unders`) | `filter_type in {overs,unders}` filters the board to `direction` + `confidence >= 70` + `play_verdict=='PLAY'` (`app.py:38416–38419`) | **Best-bets framing + a surviving Confidence-70 MEMBERSHIP gate.** Confidence was removed from sort/display in Commit C but still gates membership here. | **Yes — membership** (confidence ≥ 70). | Shared mechanism; the `/props/overs|unders` entry is NBA (dashboard link) |
| R8 | **"Team Prior Leaders"** (context sibling, not in the term list) | `props.html:317–327` | `board_intelligence.top_priors`, `team_prior_score` (0–100 power/blend) | Market-independent-ish power rating; already honestly captioned "context for the row, not a pick." | Side panel only | Shared |

---

## 2. Recommendations (keep / remove / relabel) — NBA board only, pending approval

All implementation would be **NBA-guarded** exactly like Commit C (behind `is_nba_props`), so no
non-NBA sport changes. None of these amends `9fcf691`; they would be a separate, separately-approved
commit.

- **R1 "Edge" → RELABEL (Fact).** It is a market number, not a BK edge. Recommend dropping the word
  "Edge" and presenting it as what it is — the market's lean (e.g. "Mkt lean" / the two-sided split)
  — labeled **Fact**. Keeping it titled "Edge" is the clearest doctrine violation (a market fact
  dressed as a BK edge). No membership/ordering effect.
- **R2 "EV" → REMOVE on the NBA board.** It is blank for NBA and renders an empty "% EV". Suppress
  the EV branch when `is_nba_props` (the Edge/market-lean value already shows). If EV is ever
  populated for NBA, treat it as Legacy, not Fact.
- **R3 "Fair" → RELABEL (Fact).** It is the de-vigged market price. Recommend labeling it as the
  market's de-vigged price (Fact), not "Fair" (which implies a BK model fair value).
- **R4 "Model" + R5 `core_model_read` → RELABEL (Legacy) or REMOVE.** These are genuine model/sim
  outputs. Per §1f they may remain only as **Legacy** context, visibly "the model's number," never
  presented as the board's recommendation. If a clean Legacy treatment isn't wanted, remove them
  from the NBA customer row (they persist internally).
- **R6 "Simulation Leaders" → RELABEL + DE-RANK framing.** Keep the calibrated-sim reads only as
  **Legacy** context; remove "strongest" and "Live Authority reads carry the most weight" (edge
  claims) and the implicit "best sims" ranking emphasis. The panel can show the sim read + its
  calibration status without asserting it "carries the most weight."
- **R7 "Best Over/Under Plays (70%+)" → the consequential one.** This is a **surviving
  Confidence-based membership gate** that Commit C did not touch (Commit C removed Confidence sort +
  display, not this filter). Two sub-decisions, both needing approval:
  1. **Framing:** "Best … Plays" is a best-bets claim. Recommend neutral titles (e.g. "Over plays"
     / "Under plays," or fold into the direction filter) with no "(70%+)" authority.
  2. **Membership:** the `confidence >= 70` gate is the same ungoverned Confidence authority removed
     elsewhere, now acting on membership. Recommend **removing the confidence gate** (show the
     direction-filtered board without a confidence floor) or, if a floor is wanted, replacing it
     with a governed, market-only criterion — **not** confidence. This is the only item here that
     changes NBA membership, so it needs an explicit membership decision.
- **R8 Team Prior Leaders → KEEP.** Already honestly captioned as context, not a pick. No change.

---

## 3. Summary

- **Mislabeled market facts (highest-priority honesty fix):** R1 "Edge", R3 "Fair" — relabel as the
  market's numbers (Fact). No behavior change.
- **Model/sim outputs needing a Legacy label or removal:** R4 Model, R5 core_model_read, R6
  Simulation Leaders ("strongest"/"Live Authority").
- **The one membership item:** R7 "Best … Plays (70%+)" — a surviving confidence membership gate +
  best-bets framing; needs an explicit keep/remove decision.
- **No change:** R2 is a blank-EV cleanup; R8 is already conformant.

Nothing here is implemented. Awaiting a keep/remove/relabel decision per item before any NBA-guarded
change; non-NBA sports are out of scope and untouched.
