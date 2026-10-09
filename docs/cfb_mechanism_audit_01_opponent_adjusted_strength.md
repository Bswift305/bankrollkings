# CFB Mechanism Audit #1 — Opponent-Adjusted Team Strength

**Status:** Research (authorized). Not development, not a board, not a live model. The
deliverable is this audit; the evidence is a read-only point-in-time backtest
(`research/cfb_mechanism/audit_opponent_adjusted_strength.py`). Audited 2026-10-09.

This is the first mechanism audit after the evidence-base audit
([cfb_research_audit.md](cfb_research_audit.md)) ruled CFB a **sides/totals** research
program. Opponent-Adjusted Team Strength was chosen first because it is the most
evidence-ready and least contaminated candidate: the mechanism is obvious, the data
already exists and passed the evidence-base audit, and it needs no player-level history.

---

## The eleven fields

**Mechanism.** A team's scoring margin, adjusted for strength of schedule (SRS: solve
`margin = rating_home − rating_away + home_field` by least squares over played games).
Opponent-adjustment is the point — raw margin rewards a team for beating weak opponents;
SRS nets the opponent's own strength back out. The causal claim: a team that is genuinely
stronger per the adjusted record should outperform the closing spread when the market
hasn't fully priced that strength.

**Market.** Sides / ATS. (Totals is a separate mechanism; not tested here.)

**Evidence availability.** ✅ Present and sufficient. `NCAAF_GameLines_History.csv` —
7,274 unique games (2021–2026), 7,081 with both final scores and a home spread. No new
collection needed. This is the surface that passed the evidence-base audit.

**Point-in-time reproducibility.** ✅ Enforced. A game in (season, week W) is rated using
**only games with week < W in the same season**. No full-season aggregates (the exact
leak that contaminated `calculate_ncaaf_edge_score.py`, per
[ncaaf_game_line_formula.md](ncaaf_game_line_formula.md)); no cross-season carry. Ratings
are re-solved each week from scratch.

**Independent unit.** **Game.** The history is already one row per game (7,274 unique,
zero duplicates), and n counts games, never book-rows or snapshots. Per the Director's
correction: 7,274 games ≠ 7,274 independent anything unless the unit is the game.
Predicted n after the point-in-time / min-sample gates = **4,653 games**.

**Baseline.** The market (the closing spread). Null = 50% ATS; break-even at −110 =
**52.4%**. A mechanism earns an edge claim only by clearing 52.4% out of sample with a CI
that doesn't straddle it.

**Primary metric.** ATS cover rate of the model-selected side (bet the side the rating
favors against the spread), with a 95% Wilson interval, on game units.

**Expected direction.** Under the project's standing belief (the market prices public,
obvious context — and team strength is the most obvious context there is), the expected
result was ~50%, i.e. **no edge**. This audit is as much about *confirming the baseline* as
about finding an edge.

**Result.**

| Slice | n (games) | ATS cover | 95% CI |
|---|---|---|---|
| ALL picks | 4,653 | **51.8%** | [50.4, 53.3] |
| disagreement 0–3 pts | 1,710 | 52.1% | [49.7, 54.5] |
| disagreement 3–7 | 1,646 | 51.9% | [49.5, 54.3] |
| disagreement 7–14 | 974 | 50.1% | [47.0, 53.2] |
| disagreement 14+ | 323 | 55.4% | [50.0, 60.7] |
| 2021 | 575 | 49.7% | [45.7, 53.8] |
| 2022 | 982 | 51.6% | [48.5, 54.7] |
| 2023 | 919 | 50.7% | [47.5, 53.9] |
| 2024 | 1,061 | 52.5% | [49.5, 55.5] |
| 2025 | 1,116 | 53.4% | [50.5, 56.3] |

**Failure test (pre-registered reading).** The mechanism fails as an *edge* if the ALL-picks
cover rate's CI includes the 52.4% break-even. **It does** — 51.8% [50.4, 53.3] straddles
break-even and nearly straddles 50%. No disagreement bucket and no single season clears
break-even with a CI that excludes it. The one bucket that looks live (14+ pts, 55.4%) is
underpowered (n=323, CI down to 50.0) and sits exactly where the NFL work taught us small
samples at the extreme mislead and reverse out of sample. **Verdict on the edge: fails.**

**Confounders.**
- *The market already prices strength* — the spread is itself an opponent-adjusted strength
  estimate, so we're testing residual, and finding ~none. This is the most likely
  explanation, not a flaw.
- *Home-field* is fit as a single constant; a per-team/venue HFA might shift a point, not
  the conclusion.
- *Early-season instability* — handled by `MIN_WEEK=4` and `MIN_PRIOR_GAMES=3`, which also
  shrinks the usable sample (and drops most of 2026, scores only through ~wk 5).
- *Line source mix* — the "spread" for a game comes from whichever book CFBD returned
  (consensus/ESPN Bet/Bovada/DK…); it's one line per game, treated as the market estimate.
- *No price field* — ROI isn't computed; this is cover rate only, graded at −110 break-even.

**Verdict.** **Testable ✅, tested, and it does not beat the market baseline.** Opponent-
adjusted team strength is a *real* property of teams but it is *priced*: a clean point-in-
time SRS covers 51.8% ATS, inside the no-edge band. This is the same lesson the NFL graded
record keeps teaching — predictive factors are in the price. The mechanism therefore
**graduates to being the baseline**: it is the honest "strength is priced" floor that every
future CFB sides mechanism (coaching continuity, situational, line-value) must beat out of
sample before it earns a seat. It does **not** get built into anything live.

---

## What this implies for the queue

- This audit also largely answers candidate #2 (**market baseline / closing-line
  efficiency**): the closing spread is ~unbeatable by team strength alone, as expected.
- Next mechanism audits still worth running (research only, when authorized): **Team Form
  through W-1** (does recent form add anything beyond full-season strength?), then
  **Coaching Continuity** — but only after proving regime/coordinator/continuity history
  can be reconstructed reliably point-in-time. **Per-possession** stays **data-gated** (no
  drive/PBP data exists).
- Nothing here authorizes a build. A CFB sides model is a separate decision, and it would
  start life having to beat 51.8%.

See `research/cfb_mechanism/audit_opponent_adjusted_strength.py`,
[cfb_research_audit.md](cfb_research_audit.md), and `BANKROLL_KINGS_DOCTRINE.md` §8–§10.
