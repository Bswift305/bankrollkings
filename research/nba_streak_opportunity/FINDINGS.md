# NBA Hot-Streak → Opportunity: Signal Backtest Findings

**Date:** 2026-08-22 · **Data:** `data/gamelogs/NBA_GameLogs.csv` (2025-26 season, 25,923 player-games; 20,874 eligible after a 10-game rolling warm-up) · **Status:** signal proven, real-line ROI test pending.

## TL;DR
The 2-game hot streak **by itself is not an edge** — it continues at ~51% over a form line, right around the −110 break-even. **The edge is the *opportunity around* the streak.** Layering **a star teammate being OUT** and **a soft matchup** onto the streak lifts continuation to **61% (PTS), significant and replicated out-of-sample.** Home/away is noise. Prior head-to-head history was deliberately avoided (small-sample trap). **This measures predictive signal, not profit vs the real closing line — that test still has to be run.**

## Hypothesis
Player exceeds a stat 2 games running ("the marker"). Does the *next* game stay elevated, and do opportunity/context factors (teammate out, matchup, home/away) change it?

## Method (leakage-free)
- **"Line" proxy** = the player's **trailing-10-game median** of the stat, using only PRIOR games. "Over" = actual > line.
- **Streak** = over in the two immediately prior games.
- **Opportunity ("star out")** = a top-2-scoring rotation teammate (≥18 min, ≥10 games) absent from that game's roster.
- **Soft matchup** = opponent in the top third of that stat allowed (team level).
- **Out-of-sample** = split the season at its midpoint; report both halves. Effects hold in both.

## Results

**POINTS — 2-game streak (full season, 95% CI):**
| Filter | Over-rate | 95% CI | n | vs −110 (52.4%) |
|---|---|---|---|---|
| Base (any game) | 48.2% | — | 20,874 | — |
| Streak alone | 51.4% | 50.0–52.8 | 4,779 | ~coin-flip |
| Streak + star OUT | 56.5% | 54.6–58.3 | 2,751 | **beats** |
| Streak + soft opp | 54.5% | 52.0–57.0 | 1,576 | ~ |
| **Streak + star OUT + soft opp (STACK)** | **61.4%** | **58.2–64.6** | **886** | **beats, clearly** |

- **AST stack:** 58.3% [54.6–62.0]. **REB stack:** 54.5% [51.0–58.0] (marginal).
- **Out-of-sample half alone:** streak+star-out PTS = **57.6%** (base 48.2%). Held.
- **3-game streak ≈ 2-game** (55.7% star-out vs 56.5%) → the 2-game marker is sufficient.
- **The tell:** streak with *nobody out* → production **collapses to ~33%.** The streak is a *symptom* of opportunity, not a cause.

**Factor scorecard:** teammate-out 🥇 (biggest, most reliable) · soft matchup 🥈 · home/away ➖ (nothing) · prior-matchup-history 🚩 (not used — noise).

## The critical caveat (unresolved)
"Over" here beats a **form-based line**, and much of the star-out lift exists *because that line lags the new role* (+2.5 pts unaccounted on the stack). That is exactly the un-priced-lag edge we want — **but only if the real sportsbook line lags the same way.** Books move slower on role changes than on hot streaks ("the edge is late"), so it's promising, but **unproven vs the close.** Local graded props (generic, unfiltered) ran **−5.5%** at real prices — the vig you must overcome.

## Roadmap to turn signal → receipt
1. **Retrospective:** grade the in-season candidate archive (real `CloseLine`/`ClosePrice`) against gamelog actuals, tag streak+star-out+soft-opp, compute ROI at the close. Needs the in-season graded lines (prod archive; the thin local off-season file can't isolate the subset).
2. **Prospective (gold standard):** this season, log every streak+star-out+soft-opp prop with its **closing** line+price and grade forward — true out-of-sample, zero hindsight. Aligns with capturing near the close.
3. **If it clears break-even at the close:** it's a genuine, ownable, *honest* edge — "we bet the opportunity, not the heat."

## Reproducibility
- `nba_streak_opportunity.py` — the main signal backtest (splits, OOS).
- `nba_streak_stack.py` — stacked filters, 95% CIs, 3-game streak, local real-price read.

Single season (2025-26). Team-level (not positional) opponent defense. No usage/pace normalization yet — all conservative simplifications; the effect is large enough to survive them.
