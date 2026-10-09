# Lens Governance Constitution

The roster ([lens_research_queue.md](lens_research_queue.md)) says *which* state each lens
is in. This document says *how* a lens earns or loses a seat — and it is binding.

**The one rule that makes this credible: the test is written before the data arrives.**
Every lens below carries a promotion test and a failure test that were set *now*, while the
archive is empty. We do not move the goalposts after seeing outcomes. If a lens clears its
promotion test, it's promoted; if it trips its failure test, it's demoted or retired — no
re-litigating the threshold because we liked the lens's story.

Promotion and retirement are **human decisions**; the attribution system *recommends*, a
human *decides*. There is no automatic promotion. (See the Wait list in the roster.)

**Governance floor for every lens:** no state change in either direction until the lens has
**≥ 25 settled (Win/Loss) recommendations** in `GreenLight_Archive.csv`. Pushes, voids and
DNPs don't count toward the floor. Below the floor every cell reads "too few to trust" and
the lens's state is frozen.

---

## Production

### Opportunity
- **Mechanism** — volume and role create the chance: targets, routes, carries, snap share.
- **Markets** — all player props (yardage, receptions, attempts).
- **Promotion test** — *(already in production — the baseline every other lens is measured against)*.
- **Failure test** — settled hit rate at or below the de-vigged market rate across ≥ 25 plays (i.e. it's just restating the price). Demote to Probation.
- **Known confounders** — game script (blowouts suppress volume), injury to the player mid-game, pace.
- **State entry** — Production (founding lens).

### Matchup (Defense vs Channel)
- **Mechanism** — a defense surrenders the *specific* channel (rb_rush, wr_rec, te_rec…), not generic "defense".
- **Markets** — yardage + receptions props tied to the channel.
- **Promotion test** — in production.
- **Failure test** — no separation between plays with Matchup and without, ≥ 25 each. Demote.
- **Known confounders** — opponent injuries changing the defense after capture; small-sample channel ranks (thin flag already exists).
- **State entry** — Production.

### Game Identity (script)
- **Mechanism** — the game script dictates whether a player's plan even gets run (trailing team throws, leading team runs).
- **Markets** — yardage + attempts props; direction-sensitive.
- **Failure test** — Game-Identity plays don't beat non-GI plays, ≥ 25 each. Demote. (Script Certainty, below, is the humility layer being tested *on top of* this.)
- **Known confounders** — win-probability estimate wrong at capture; the TB@DAL lesson (gave the favorite too much credit for playing ahead).
- **State entry** — Production.

### Role Stability
- **Mechanism** — a locked snap/target share is a floor; a volatile one is an average hiding a wide range. Variance information, not level.
- **Markets** — props where a floor matters (receptions, yardage overs).
- **Promotion to *permanent* status** — **Opportunity + Stability(Locked)** beats **Opportunity ALONE** on both hit rate and ROI, ≥ 25 settled each. This is the first governance vote. (Historical validation: partial r +0.69 controlling for mean share.)
- **Failure test** — if the two rows do **not** separate, Role Stability goes to **Probation, not immediate retirement** — the story is strong enough to earn scrutiny, not a firing.
- **Known confounders** — mean share (a locked star also has high volume; the +0.69 is *after* controlling for it).
- **State entry** — Production (on probationary watch via the vote above).

### Channel Dependency
- **Mechanism** — single-channel production is easier for a defense to take away than dual-threat; concentration changes variance.
- **Markets** — combined yardage, anytime-TD.
- **Failure test** — Dual-threat doesn't beat Single-channel, ≥ 25 each, *and* the direction contradicts the mechanism. Demote.
- **Known confounders** — low secondary volume misread as single-channel (clamp + MIN_SECONDARY_YDS already guard this).
- **State entry** — Production.

### Concentration (TD)
- **Mechanism** — red-zone / goal-line share concentrates scoring opportunity in one back.
- **Markets** — anytime-TD, rushing-TD.
- **Failure test** — Concentration plays don't out-hit the field on TD markets, ≥ 25. Demote.
- **Known confounders** — TD variance is high; needs a larger floor in practice than yardage lenses.
- **State entry** — Production.

---

## Probation (on trial — built, capturing, not yet proven)

### Script Confidence
- **Mechanism** — conditioning Game Identity on win-probability *certainty*; a humility gate, not a new signal.
- **Promotion test** — `high`-confidence plays beat `medium` on hit rate, ≥ 25 each, in the predicted direction.
- **Failure test** — no separation, or inverted. Retire the gate (Game Identity keeps its seat without it).
- **State entry** — Probation, 2026-10-09.

### Fragile (single-channel × shaky script)
- **Mechanism** — a warning: single-channel production in an uncertain script should miss more.
- **Promotion test** — Fragile plays **underperform** non-fragile plays, ≥ 25 each. (A warning earns its seat by being *right about misses*.)
- **Failure test** — Fragile plays hit at or above the field. **It loses its seat** — a warning that doesn't predict misses is just anxiety.
- **State entry** — Probation, 2026-10-09.

### Lens Interactions (the killer table)
- **Mechanism** — independent lenses stacking should compound; the interaction rows test it.
- **Promotion test** — Opportunity + Stability + Matchup beats each simpler subset, ≥ 25 each.
- **Failure test** — stacking doesn't beat the best single lens (lenses aren't independent after all). Fold back.
- **State entry** — Probation, 2026-10-09.

---

See also [lens_research_queue.md](lens_research_queue.md) (the roster + Research Queue +
genealogy), `BANKROLL_KINGS_DOCTRINE.md` §10 (the four questions), and the harness
(`capture_green_light.py` / `grade_lenses.py` → `data/tracking/Lens_Grades_Summary.json`).
