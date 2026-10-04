# The Averaging Audit — Bankroll Kings

> **One question, asked of every number on the site:**
> ### "What context does this average hide?"
>
> **Status (2026-10-03):** methodology written; grounded inventory being populated from a
> codebase sweep. This is not a feature spec — it's the research method behind the next
> round of features. Pairs with `BANKROLL_KINGS_DOCTRINE.md` and feeds
> `docs/kings_wisdomism_engine.md` (every audit finding is a candidate Wisdomism *lens*).

---

## 1. Why this is the thread to pull

Every recent breakthrough came from the same move — not new math, but **refusing to let an
average hide context:**

| Breakthrough | The average it broke open |
|---|---|
| Opportunity vs production | "points/yards per game" hid *role and usage* |
| Buy Low / Sell High | "record" hid *performance vs opponent-adjusted level* |
| CLV vs win rate | "win %" hid *whether you beat the closing number* |
| Process vs outcome | "did it hit?" hid *whether the decision was sound* |
| 1Q/1H vs full game | "31 PPG" hid *when* those points happen |

That's a pattern, not a coincidence. An average collapses a distribution to a single
number, and **the signal is almost always in what got collapsed.** The audit
systematically hunts for the next one.

CoCo's framing, which we're adopting: this may be less a feature pipeline than **the
Bankroll Kings research methodology** — and it reframes the whole Wisdomism project.
Wisdomism's real job is not "find the best plays." It's **"assemble the strongest
convergence of independent context the market may not have fully captured."** Evidence
assembly, not scoring.

---

## 2. The five ways an average hides context

Every aggregate on the site collapses at least one of these. Tagging each number by *which*
tells us where a conditional version would reveal something.

| Dimension | The average collapses… | Example of what's hidden |
|---|---|---|
| **WHEN** | within-game time | 1Q/1H scoring; fast vs slow starters; finishers vs faders |
| **CONDITION** | game state | pass rate when trailing vs run rate when leading (*script identity*) |
| **WHO** | distribution across players | who actually gets the red-zone touches / targets (*concentration*) |
| **VS WHOM** | opponent / venue quality | strength of schedule; home vs road |
| **HOW RELIABLY** | the shape of the distribution | the *floor*, not the mean; volatility; consistency |

**VS WHOM** is largely handled already (SRS / opponent-adjusted form). **WHEN** and **HOW
RELIABLY** are started (CFB period board; hit profiles). The two wide-open frontiers are
**CONDITION** (game-script identity) and **WHO** (concentration) — and not by accident:
those are the two that directly *manufacture player props*.

---

## 3. The lens-independence test (the part that makes a finding usable)

CoCo's sharpest point, and the acceptance test for everything the audit produces:

> **A group of metrics is ONE lens wearing many hats if knowing one lets you predict the
> others. It's several independent lenses only if each is a genuinely different argument.**

His example says it perfectly:

**One argument, four hats** (do *not* count as 4 lenses):
```
Target Share · Air Yard Share · Targets/Game · Receiving Opportunity
```
All four are the **Opportunity** signal restated.

**Four actual arguments** (genuinely independent):
```
Opportunity · Game Script · Market Movement · Quarter/Half Behavior
```

This matters because **Kings Wisdomism ranks by convergence**, and convergence of
correlated lenses is false conviction — the three-Gibbs-cards trap one level up. So every
audit finding gets tagged with its **lens-family**, and we track which families are
actually independent of each other.

**How we'll decide independence:**
- *By mechanism (now):* do two metrics draw on the same underlying cause (team strength,
  game volume, the price)? If yes, suspect one lens.
- *By measurement (once coded):* correlate the two metrics' per-play signals across the
  historical play universe. High correlation → collapse them into one lens.

---

## 4. Candidate lens-families (independent arguments) + their market exposure

The convergence model needs a small set of *independent* families. Starting hypothesis —
to be confirmed by the independence test — plus whether the market likely already prices
each (the "un-priced gate" from the Wisdomism brief):

| Lens-family | Captures | Likely already priced? |
|---|---|---|
| **Opportunity / Usage** | volume, role, snaps, touches, targets | partly — stars are priced, role *changes* less so |
| **Game-script identity** | conditional behavior by game state | **under-priced** (frontier) |
| **Coaching / structural** | 4th-down, pace, RZ philosophy | **least priced** — market prices the QB, not the OC |
| **Concentration** | who gets the RZ/goal-line/target share | **under-priced** (esp. anytime-TD) |
| **Time-sliced behavior** | quarter/half, starts/finishes | partly — 1H/1Q lines exist and are priced |
| **Matchup / opponent quality** | form, SRS, def ranks | **priced** — the line already knows team strength |
| **Market context** | line, movement, line-delta, CLV | *is* the price — by definition reflects consensus |
| **Reliability / shape** | floor, consistency, variance | partly — floors erode as the line is bumped |

> ⚠️ **Suspected correlations to resolve:** Matchup quality ↔ Market context ↔ Opportunity
> may all be partly the same "this team/player is good, and the line knows it" signal. The
> independence test has to settle this before convergence counting is trustworthy. The
> genuinely *orthogonal* trio looks like **what a team/player DOES (script + concentration)
> × how MUCH (opportunity) × what the market MISSED (line-delta)** — but that's a
> hypothesis to verify, not a conclusion.

---

## 5. How to read the inventory (next section)

Each row of the grounded inventory is tagged:

| Column | Meaning |
|---|---|
| **Metric** | the average/rate/ranking as the site computes it |
| **Where** | file:function — so it's actionable, not theoretical |
| **Window** | season / last-N / all-resolved / career |
| **Collapses** | which of the 5 dimensions it washes out |
| **Lens-family** | which independent argument it belongs to (§4) |
| **Conditional buildable?** | can we split it with data we already hold? |
| **Priced?** | does the market likely already see the split (§4 exposure) |

The payoff column is the last two: a metric that **collapses a frontier dimension**, is
**buildable from data we have**, and is **not already priced** is a candidate for the next
breakthrough — and the next Wisdomism lens.

---

## 6. The dominant finding (read this first)

> **Nearly every number on the site collapses GAME-STATE** — leading / trailing / tied,
> and its cousin, garbage-time. And game-state is not just *one* hidden dimension. It is
> the hidden **common cause** that makes our supposedly-separate lenses secretly the same
> signal:
>
> - **Usage** (`target_share`, `rush_share`) is *created by* game-script — trailing teams
>   throw, leading teams run — so our "opportunity" number already has game-script baked in.
> - **Defensive ranks** (pass/run ypg allowed) are *inflated by* game-script — a defense
>   that's often led looks "soft vs the pass" because it faced catch-up throwing.
> - **Totals, quarter margins, streaks** are distorted by garbage-time.
>
> **Therefore: conditioning on game-state is the single highest-leverage move we can make.**
> It reveals the most hidden context (CONDITION — our #1 frontier) **and** it's what
> *disentangles the lenses* so Wisdomism's convergence counting is honest. One fix, both
> payoffs. If we do nothing else from this audit, we do this.

A second cross-cutting pattern: **opponent-quality is collapsed across the entire NFL
player/trends stack** (hit profiles, floor board, hot-hand, buy-low) — while the **CFB**
side already opponent-adjusts (SRS) and venue-splits. CFB is the template; NFL is behind.

A third: **line-level blending.** Every streak/hit number is measured against a *single
fixed line* (today's posted number, applied to past games), and the hit-profile `AvgLine`
blends every line a player was ever graded at into one figure that matches no real bet.

---

## 7. Grounded inventory — where context is hidden

Only the context-*hiding* metrics are listed (the ones already split well are called out
as templates). Lens-family codes: **OPP** opportunity · **SCRIPT** game-state · **MATCH**
opponent/matchup · **MKT** market · **TIME** quarter/half · **SHAPE** reliability/floor ·
**COACH** coaching (not yet built) · **CONC** concentration (not yet built).

### 7a. Game / Team
| Metric | Where | Collapses | Lens |
|---|---|---|---|
| Pass/run ypg-allowed (adj) **def ranks** | `nfl_current_form` `_adj_*_rank`/`defense_note` | game-state, garbage-time | MATCH⊗SCRIPT |
| Raw **ppg/papg/avg_margin** (NOT opp-adj, beside adjusted SRS) | `cfb_current_form.team_form:356` | opponent, home/road, game-state | MATCH |
| Projected **total** (per-game pts, not per-drive) | `cfb_current_form._off_def_ratings:259` | pace/possessions | MATCH |
| Elo rating w/ **single league-wide HFA** | `power_ratings.compute_elo:173` | per-team/venue HFA, garbage-time | MATCH |
| ATS/OU cover% + **coach** ATS | `build_nfl_matchup_dossier:43208`, `build_bk_power_context:44379` | recency, opponent | MKT/COACH |

### 7b. Player
| Metric | Where | Collapses | Lens |
|---|---|---|---|
| **HitRate / AvgLine** (biggest single collapse) | `build_nfl_historical_calibration.build_player_profiles:415` | **line level**, recency, opponent, game-state | SHAPE |
| **target_share / rush_share** / opportunity score | `build_nfl_usage_board:30469` | **game-script (its own creator)**, opponent | OPP⊗SCRIPT |
| Prop-floor / floor-board **clear rate** | `build_nfl_prop_floor:29842`, `build_nfl_floor_board:29955` | opponent, home/road, game-state | SHAPE |
| Hot-hand **streak / avg_clear** | `build_nfl_hot_hand:30174` | opponent, game-state, **line level** (past games vs today's line) | SHAPE |
| **FloorHitRate / Follow3 / ConsistencyIndex** (archive) | `build_trend_board:27728` | opponent, home/road, game-state, real market line | SHAPE |
| Buy-low **delta_pct** | `build_nfl_buy_low_board:30323` | opponent (NOT schedule-adj), game-state | OPP |

### 7c. Market / Trends / Truth
| Metric | Where | Collapses | Lens |
|---|---|---|---|
| Market-Movers **consensus delta** | `_build_market_movers_snapshot:18464` | time-to-kickoff, book disagreement | MKT |
| ATS **cover_rate_5y/last5** + continuation | `build_football_historical_market_rows:8394` | home/road, fav/dog, opponent | MKT/MATCH |
| CFB Game-Flow **quarter/half margins** | `build_cfb_period_context:42280` | opponent (raw), score-state/garbage-time | TIME |
| Calibration **overall hit rate** + signal cohort hit_rate | `model_calibration.run_calibration:334`, `grade_signals._cohort:142` | **price/odds** (calibrated can still lose money) | SHAPE/MKT |

**Already split well — copy these patterns:** CFB buy-low (opp-adjusted residual + venue
split), CFB period board (venue), `build_nfl_ats_context` / `build_cfb_ats_context`
(home/away/fav/dog), `model_calibration` buckets, candidate-archive (hit rate **paired with
ROI**), featured-archive (CLV).

---

## 8. The hidden-context shortlist (the payoff)

Ranked by *collapses a frontier dimension × buildable now × not already priced.* Split into
**(A) de-collapse an existing number** and **(B) net-new lenses the site doesn't compute at
all** (the sweeps confirmed coaching + concentration don't exist today).

### A — De-collapse (reveal context inside numbers we already show)
1. **Usage × game-script** — split `target_share` / `rush_share` by leading/trailing/tied.
   *Highest leverage on the board:* reveals the #1 frontier AND decouples Opportunity from
   Game-Script for honest convergence. Buildable from nflverse PBP (+ the projected-state
   tags `build_nfl_historical_calibration` already computes). Un-priced.
2. **Defensive ranks × neutral-script** — recompute ypg-allowed on neutral / pre-garbage
   plays. Kills the "soft pass D is an artifact of trailing opponents" problem that shaped
   tonight's shootout reads. Buildable from PBP. Largely un-priced.
3. **Hit-profile / floor rates de-blended by line level (+ opponent)** — fixes the biggest
   single collapse (`AvgLine` blends line levels) that feeds the prop score **and tonight's
   line-delta gate.** More correctness than new edge, but high trust. Regrade
   `NFL_AllPropResults` into line buckets.
4. **NFL buy-low schedule-adjust + venue split** — quick win: the pattern already exists in
   `build_cfb_buy_low_board` (opp-adjusted residual + home/road). Just port it.
5. **CFB Game-Flow opponent-adjust + close-game-only** — port SRS into the quarter margins,
   filter garbage-time. (Venue split already done.)
6. **Price/ROI in the truth layer** — pair every calibration + signal hit rate with ROI and
   split fav/dog. Mirror candidate-archive's existing ROI pairing. Honesty fix: a calibrated
   hit rate can still lose money.

### B — Net-new independent lenses (greenfield, genuinely un-priced)
7. **Coaching / structural tendencies** — 4th-down aggression, pace, red-zone run/pass
   philosophy. Nothing computes these today. Buildable from the 7-yr nflverse PBP. **Least
   priced on the whole list** (the market prices the QB, not the OC). Strongest new lens.
8. **Red-zone concentration** — who actually gets the goal-line carries / RZ targets. Not
   computed today. Buildable from PBP. Destroys the anytime-TD market; independent of
   yardage usage.

---

## 9. The lens-independence verdict (Wisdomism's catalog)

CoCo's question — *are these independent lenses or one argument in many hats?* — now has a
grounded answer: **today they are more entangled than the hypothesis, and the common cause
is game-state.**
- Opportunity ⟂ Game-Script → **no** (usage bakes in script)
- Matchup/def-ranks ⟂ Game-Script → **no** (ranks inflated by script)
- Form/Matchup ⟂ Market → **partly** (both encode team strength the line already knows)

So the honest independent lens set — **after the Type-A fixes** — is roughly:

| Lens | Earned by |
|---|---|
| Script-conditioned usage | fix #1 (decouples OPP from SCRIPT) |
| Neutral-script matchup | fix #2 (decouples MATCH from SCRIPT) |
| Market / line-delta | already independent (it's the price) |
| Time-sliced behavior | fix #5 (opp-adjusted periods) |
| Coaching / structural | new lens #7 |
| Red-zone concentration | new lens #8 |
| Reliability / shape (de-blended by line) | fix #3 |

**The headline, restated:** conditioning on game-state is the one move that both reveals
the most hidden context *and* earns Wisdomism honest lens independence. The audit didn't
just find fixes — it found that the fix and the independence requirement are the **same
move.**

---

---

## 10. Results — what building A1 + A2 actually found (2026-10-03)

We built A1 and A2 as proofs. Both came back **more honest than the hypothesis**, and
together they redirected the sprint.

**A1 — usage × game-state** (`build_nfl_usage_by_state.py`, 2019-25 PBP):
- For the *typical* player, game-state is **NOT a separable lens**: corr(leading, trailing)
  = **0.93** target share / **0.96** rush share; the median player moves ~1% between states.
- But a **~7–12% minority flips hard** and intuitively: TreVeyon Henderson rush share
  24%→8% (leading→trailing); Nabers targets 8%→16%; committee backs vanish when trailing.
- **Verdict:** game-script is a **targeted** lens — independent evidence only for the
  script-dependent minority, redundant with raw usage for everyone else. That's the
  lens-independence discipline working *before* we wired a double-count into the engine.

**A2 — defense ranks × game-state** (`build_nfl_defense_by_state.py`, 2019-25 PBP):
- Mechanism confirmed but modest: a defense that **leads** faces a **61% pass rate** vs
  55% when trailing — yet allows **fewer** yards per attempt (6.08 vs 6.48). So per-game
  pass-yds-allowed is inflated by **volume the lead created**, not worse coverage.
- 2025 reshuffle: switching per-GAME ranks → neutral-script per-DROPBACK moved **25% of
  defenses ≥6 rank spots** (MIA looked 9th, is 27th; DEN looked 11th, is 1st). Real, but a
  partial reorder, not wholesale.

**The meta-finding that matters most:** most of the "game-state distortion" in the
defensive ranks is really the **per-GAME vs per-PLAY** distinction. *Counting* stats
(yards/game, targets/game) embed volume — which game-script drives — while *rate* stats
(yards/dropback, yards/target, share-per-opportunity) don't. So the cheapest, broadest fix
on the whole board may be **"rate stats, not counting stats,"** applied everywhere the
inventory flagged a per-game number — with game-state conditioning as a smaller, targeted
refinement on top.

**Revised priority (for the next confer with CoCo):**
1. **Switch counting metrics → rate metrics** site-wide (the 80/20 of the volume artifact).
2. **Flag script-dependent players** from A1 (the targeted game-script lens), not a blanket split.
3. **A3 — de-blend the hit-profile `AvgLine`** — ✅ **DONE** (below).
Full game-state conditioning drops from "foundational sprint" to "targeted refinement" —
because the data said so.

**A3 — hit-profile AvgLine de-blend** (`build_nfl_hit_profile_linemeta.py` +
`build_nfl_historical_calibration` + `calculate_nfl_prop_score`, commit 99eb701):
- `AvgLine` is the mean of *every* line a player was ever graded at. **68% of multi-line
  profiles are phantoms** (line range > 40% of the mean): Rico Dowdle's rush line spans
  15.5→91.5 (backup→bell-cow) blended to 58.2; Jauan Jennings rec 17.5→79.5.
- `calculate_line_value`'s "soft number" bonus (up to **+6** score pts) fired on **25% of
  props — 72% of those off a phantom AvgLine.** So most of the time it rewarded "this line
  is soft vs his usual," it was comparing to fiction.
- **Fix:** added `LineBlend` (TIGHT/MODERATE/WIDE/THIN) to the profile; the bonus now applies
  at full weight only for TIGHT, half for MODERATE, **zero for WIDE/THIN**. Verified: Dowdle
  (WIDE) line_value 10→4; Mahomes (TIGHT) bonus kept.
- **Honest note:** this is a *correctness* fix, not new edge — lines are priced ~50% at every
  level, so de-blending reveals nothing hidden; it stops the score (and the line-delta gate we
  used to vet cards) from comparing today's number to a reference that never existed.

---

*Written 2026-10-03 after the strategy brainstorm with Darrel + CoCo; inventory grounded in
a three-domain codebase sweep; §10 added after building A1/A2. The method is the product:
keep asking what the average hides, keep the lens-independence test honest, and let the
findings — not the hypothesis — decide what gets built next. **A1/A2 did exactly that.***
