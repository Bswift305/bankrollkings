# CFB Mechanism Audit #2 — PRE-REGISTRATION (final freeze candidate)

**Candidate:** Team Form v1 — opponent-adjusted **exponentially-weighted SRS, H = 3**.
**Status:** Pre-registration, submitted for **final freeze review**. **No results exist as
of this commit.** Audit #2 is **not authorized to execute** until the Director approves this
freeze. The governance rule: *the test must be written — completely — before the result
exists; the value is that the meaning of the result cannot change after it appears.*

Audit #1 is already point-in-time and dynamic (cumulative SRS through W-1), so this is **not**
"strength vs no strength." The frozen question:

> **Does recency-weighted information (Team Form v1) add anything beyond cumulative
> opponent-adjusted strength and the market spread — on the same games?**

Every material implementation and interpretation choice below is frozen. The run may only
interpret *this* frozen test.

---

## 1 — Weighted least-squares definition (frozen)

Model B solves the identical SRS normal equations as Audit #1
(`margin = r_home − r_away + HFA`, same-season games with `week < W`), **weighted** by
recency:

```
w_i      = 0.5 ** ((target_week − game_week_i) / 3)          # H = 3, fixed a priori
objective: minimize  Σ_i  w_i · (r_home_i − r_away_i + HFA − margin_i)²
implement: A_weighted = sqrt(w_i) · A_row_i ;  b_weighted = sqrt(w_i) · b_i ;  lstsq
```

The gauge-fixing sum-to-zero constraint row keeps its Audit #1 weight `RIDGE` (it is **not**
recency-scaled). This exact objective **is** Team Form v1. Any other weighting implementation
is a different model and a separate candidate (see §8).

## 2 — Dataset freeze (frozen + enforced)

- **Seasons = 2021–2025** (completed, immutable; 2026 excluded — no 2026 game cleared the
  gates in Audit #1 anyway).
- **Deduplication key:** `(Season, Week, Away, Home)` — one row per game.
- **Eligibility filters (identical to Audit #1):** `week ≥ 4`; ≥ 20 prior same-season games
  in the week's solve; both teams rated (≥ 3 prior games); final scores + home spread
  present; **pushes excluded**.
- **Expected eligible game count = 4,653** (per-season: 2021→575, 2022→982, 2023→919,
  2024→1061, 2025→1116).
- **Frozen population fingerprint** (`research/cfb_mechanism/audit2_frozen_population.json`):
  `sha256 = ffb7c73f53d45e9c44249981714f3e6d3664ef78b92cbe46517d9bcc7ebbc6cd` over canonical
  `season|week|away|home|hspread|margin` rows.
- **Enforcement:** the source file is a rolling CFBD fetch, so Audit #2 **recomputes this
  fingerprint at run time and ABORTS if `n ≠ 4653` or `sha256` differs.** A population
  mismatch fails execution — it does not silently re-baseline. Audit #2 imports
  `eligible_games()` from `freeze_audit2_population.py`, so A and B are evaluated on the
  identical, paired universe.

## 3 — Tie handling (frozen)

- **Model selection tie:** `model_edge == 0` → **no selection** (reported separately as
  "no-action", excluded from cover rates).
- **A/B disagreement tie:** a game enters the disagreement subset (§7) only when A and B pick
  **opposite, non-zero** sides. If either model is no-action on a game, that game is excluded
  from the disagreement subset and counted separately.
- Push outcomes are already excluded at the population level (§2).

## 4 — Disagreement sample minimums (frozen, numeric)

- The decisive paired test (§7) renders a verdict only if the **overall disagreement n ≥ 200**.
  Below 200 → verdict = **"underpowered → no demonstrated incremental edge"** (see §3 of my
  stated prior: a small disagreement set is itself the finding — recency rarely flips SRS —
  and must **not** become a "needs more data" loop that invites re-running).
- **Per season:** a season with **< 30** disagreement games is reported but **excluded from
  the majority-of-seasons stability test** (§6).

## 5 — Dependence-aware uncertainty (frozen: Option A, composite)

Wilson intervals are descriptive only (games share teams/weeks → true intervals are wider).
The **decisive** uncertainty rule is the composite conservative standard (no bootstrap seed
or block-structure ambiguity):

> Model B shows a real effect on a metric **only if ALL hold:** (a) the metric's **Wilson
> lower bound** clears the relevant threshold (§7); (b) it holds in a **majority of seasons**
> (§6); (c) it is **not driven by a single dominant season** (§6); (d) the **disagreement
> count ≥ 200** (§4).

A season-block descriptive readout may be printed for color but is **not** decisive.

## 6 — Stability definitions (frozen, numeric)

Among seasons meeting the §4 per-season minimum (≥ 30 disagreement games):

- **"Majority of seasons"** = the metric clears its threshold in **≥ 3 of 5** seasons.
- **"Dominant / concentrated season"** = **leave-one-season-out**: removing the single
  best season flips the **overall** disagreement-subset result from above-threshold to
  at-or-below. If it flips, the effect is "concentrated" and **fails** stability.
- **"Stable"** = passes majority (≥ 3/5) **and** survives leave-one-season-out.

## 7 — Separate success standards (frozen, kept distinct)

Two different questions, two thresholds, never conflated:

- **(I) Informational improvement** — *does recency add information?* Evaluated on the
  **disagreement subset only** (games where B overturned A's side), threshold centered on
  **50%** (did the flip help more than a coin flip?). Plus: does B **reduce margin MAE vs A**
  on the full paired population?
- **(II) Hypothetical betting edge** — *does B clear the −110 bar?* Threshold **52.4%**.
  **No ROI claim, no profitability claim** — break-even is a hypothetical reference; juice is
  not preserved; "the market" is a mixed-book approximation (per Audit #1).

Both are reported; a pass on (I) does not imply (II), and vice versa.

## 8 — Conclusion scope (frozen)

A result applies **only to Team Form v1 (opponent-adjusted exponentially-weighted SRS,
H = 3)**. Success or failure does **not** transfer to momentum, recency generally, "team
form" generally, other half-lives, or other weighting schemes. Each of those is a separate
future candidate requiring its own pre-registration.

## 9 — Evaluation periods (frozen)

Evaluation periods = the five seasons **2021, 2022, 2023, 2024, 2025**, each a unit in the
stability tests (§6). Because `H = 3` is fixed a priori (no data-driven selection), there is
no development/evaluation split — all five seasons are evaluation. "Improvement disappears on
evaluation periods" = fails the §6 majority / leave-one-out tests on these five seasons.

---

## Decision rule (frozen)

- **Graduate** (to "candidate with incremental signal", research only) **iff**: B **reduces
  margin MAE vs A** on the paired population, **AND** the disagreement subset clears **50%**
  under the §5 composite rule (informational), **AND** — for a betting-edge claim —
  separately clears **52.4%** under the same composite rule. Informational-only graduation is
  possible without a betting-edge claim; both are reported.
- **Otherwise: No demonstrated incremental edge.** Audit #1 cumulative SRS remains the
  benchmark; Team Form v1 is recorded as tested-and-not-additive. Underpowered (§4) resolves
  here, not to limbo.
- **No build is authorized** by this audit under any outcome.

## Execution note (post-approval only)

On freeze approval, Audit #2 runs as `research/cfb_mechanism/audit_team_form_w1.py`,
committed **separately after this freeze**, importing `eligible_games()` +
`_load`/`_srs` so the population is provably identical and the fingerprint guard (§2) is
live. History will show the test predating its result.

See `docs/cfb_mechanism_audit_01_opponent_adjusted_strength.md` (benchmark),
`research/cfb_mechanism/audit2_frozen_population.json` (frozen population),
`docs/cfb_research_audit.md`, and `BANKROLL_KINGS_DOCTRINE.md` §10.
