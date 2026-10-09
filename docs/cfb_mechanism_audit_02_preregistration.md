# CFB Mechanism Audit #2 — PRE-REGISTRATION (frozen before results)

**Candidate:** Opponent-Adjusted Team **Form** through W-1 (recency-weighted strength).
**Status:** Pre-registration only. **No results exist as of this commit.** This document
freezes the test so it can be inspected before any outcome is known — the NFL governance
rule applied to CFB: *the test must be written before the result exists.* Audit #2 is
**not authorized to run** until the Director confirms this frozen spec. Nothing here is a
build.

This is a correction of the earlier framing. Audit #1 is **already point-in-time and
dynamic** (cumulative SRS through W-1), so the question is **not** "strength vs no strength."
The sharp question is:

> **Does recency-weighted information add anything beyond cumulative opponent-adjusted
> strength and the market spread — on the same games?**

---

## Frozen: mechanism (one definition, no window-shopping)

**Model B = exponentially-weighted SRS.** Identical least-squares SRS as Audit #1
(`margin = r_home − r_away + HFA`, same-season games with week < W), except each prior
game is weighted by recency:

```
weight(game) = 0.5 ** ((target_week − game_week) / H),   H = 3   # half-life, FIXED a priori
```

`H = 3` (weeks) is chosen **once, by fiat**, as a reasonable "recent form" horizon. It is
**not** scanned, tuned, or selected from the data. If `H` were ever to be compared across
values, development seasons (2021–2023) would choose it and evaluation seasons (2024–2025)
would test it — but the pre-registered design uses the single frozen `H = 3`, so the full
2021–2025 sample is the evaluation set.

## Frozen: baselines (paired, same games)

1. **Market** — the game's spread (the reference both models must improve on).
2. **Model A** — Audit #1 cumulative point-in-time SRS (the benchmark, unchanged).
3. **Model B** — the recency-weighted SRS above.

## Frozen: independent unit and eligibility

- **Unit = Game.** Not book-rows, not snapshots, not prices.
- **Same eligible-game set for A and B** (paired): the exact Audit #1 gates —
  `week ≥ 4`, each team `≥ 3` prior games this season, both teams rated, final scores +
  home spread present, pushes excluded. A and B are evaluated on the identical games so all
  comparisons are paired.

## Frozen: metrics (declared before results)

1. **Margin prediction error** — MAE and RMSE of `(pred_margin − actual_margin)` for A and
   B, and for the spread itself (`−HomeSpread`), on the same games.
2. **Error vs the spread** — does B's margin beat the spread's own margin error by more than
   A does?
3. **ATS selection** — cover rate of each model's selected side, with Wilson CI (reported
   descriptively; see the Audit #1 independence caveat — a season-block read is the
   conservative cross-check).
4. **Incremental / paired (the decisive test)** — ATS cover rate on **only the games where
   B picks a different side than A** (the games recency actually changed). This isolates
   whether recency adds *deployable* information rather than reshuffling.
5. **Season-by-season stability** of (3) and (4).

## Frozen: failure conditions (Model B fails if ANY hold)

- B does **not** reduce margin MAE vs A overall.
- On the **disagreement subset** (metric 4), B's ATS cover is ≤ 50%, or its CI includes
  50%.
- The improvement is **not stable** — it doesn't hold in a majority of the five seasons, or
  it concentrates in one season/window.
- B merely **amplifies A** — predicted margins are near-perfectly correlated with A's and
  there is no MAE gain (same signal, louder).
- Any apparent edge appears only after inspecting results (there is no post-hoc tuning;
  `H = 3` and all gates are frozen here).

## Frozen: decision rule

- **Graduate** (to "candidate with incremental signal", research only) only if B **reduces
  margin error vs A** *and* **wins the disagreement subset above the 52.4% hypothetical
  break-even with a CI excluding it** *and* is **stable across seasons**.
- Otherwise: **No demonstrated incremental edge.** Model A (Audit #1 SRS) remains the
  benchmark, and recency-weighting is recorded as tested-and-not-additive.
- Either way, **no build is authorized** by this audit. As in Audit #1, break-even is a
  hypothetical −110 reference, juice is not consistently preserved, and **no ROI claim**
  will be attached.

---

## Execution note

When (and only when) the Director authorizes the run against this frozen spec, Audit #2 will
be a read-only script `research/cfb_mechanism/audit_team_form_w1.py` committed **separately,
after this pre-registration**, so the git history shows the test predating its result. The
script will reuse Audit #1's loader and gates verbatim to guarantee the paired, same-game
comparison.

See `docs/cfb_mechanism_audit_01_opponent_adjusted_strength.md` (the benchmark),
`docs/cfb_research_audit.md` (why CFB is a sides/totals program), and
`BANKROLL_KINGS_DOCTRINE.md` §10.
