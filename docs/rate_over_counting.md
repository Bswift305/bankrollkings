# Rate-over-Counting — Migration Inventory

> **Bucket 2 of the Averaging Audit. This is an INVENTORY, not an implementation.** It finds
> every place Bankroll Kings uses a *counting* metric (per-game, raw total, win-count) and
> marks its *rate* replacement, plus whether we can build the rate today.
>
> **Status (2026-10-04):** inventory complete. Pairs with `docs/averaging_audit.md` (the law
> this came from) and feeds `docs/kings_wisdomism_engine.md` (cleaner lenses).

---

## The principle (the law A2 uncovered)

> **Volume hides context.** A *counting* stat (yards/game, targets/game, pass-yds-allowed/game,
> career totals, win counts) embeds **volume** — and volume is driven by game-script, pace,
> opportunity, and games played. A *rate* stat (yards/play, yards/target, yards/dropback,
> per-possession, share-of-opportunity, ROI) divides the volume back out and isolates the thing
> we actually want to measure.

A2 proved it on defensive ranks: a defense that leads faces a 61% pass rate (vs 55% trailing)
and its per-game pass-yards-allowed balloons — not because it defends worse (it allows *fewer*
yards/attempt) but because the lead *created pass volume*. The per-game number measured the
game-script; the per-dropback number measured the defense.

**Scope boundary:** this bucket is *only* counting→rate. Metrics that are already rates but
collapse a situation (ATS cover% by home/road/fav/dog, the game-state splits from A1/A2) belong
to the **conditioning** track, not here — noted where they'd otherwise look like duplicates.

---

## How to read

| Column | Meaning |
|---|---|
| **Counting metric** | the per-game / total / win-count as computed today |
| **Where** | file:function |
| **Volume it embeds** | the thing that inflates it (the hidden context) |
| **→ Rate replacement** | the per-X version that divides volume out |
| **Now?** | can we compute the rate from data in hand |

---

## Class A — per-GAME → per-PLAY / per-OPPORTUNITY (the core)

| Counting metric | Where | Volume it embeds | → Rate replacement | Now? |
|---|---|---|---|---|
| Pass/run **ypg allowed** (adj) def ranks | `nfl_current_form` `defense_note` / `_adj_*_rank` | pass **attempts faced** (game-script) | **yds / dropback** & **yds / rush** (+ neutral-script) | ✅ PBP |
| Usage **yds_pg / car_pg / tgt_pg / rec_pg** | `build_nfl_usage_board:30468` | games + game-script volume | **yds / target**, **yds / carry**, **targets / team dropback** | ✅ PBP |
| QB opportunity **att/gm** | `_nfl_qb_opp:30312` | team pass volume (script) | **pass rate** (dropbacks / play) | ✅ PBP |
| Defense score **tk_pg / prs_pg** | `build_nfl_usage_board:30444` | plays faced (trailing D faces more) | **pressure rate** (/dropback); tackles / play-faced | ✅ PBP |
| Receiver **avg_rec** (per game) | `build_nfl_receiver_profile:28` | games + target volume | **catch / target**; yds / target | ✅ (per-target); ❌ per-route |
| CFB **ppg / papg** | `cfb_current_form.team_form:356` | games + **pace** (+ opp-unadj) | **points / possession** (+ opp-adjust) | ❌ needs CFBD drives |
| CFB **projected total** (per-game pts) | `cfb_current_form._off_def_ratings:259` | **pace / possessions** | pts/possession × projected possessions | ❌ needs CFBD drives |
| Buy-low **recent_pg vs season_pg** | `build_nfl_buy_low_board:30372` | games + script + schedule | per-play / per-opportunity (+ schedule-adj) | ✅ PBP |

## Class B — raw TOTALS / SUMS → per-game or SHARE

| Counting metric | Where | Volume it embeds | → Rate replacement | Now? |
|---|---|---|---|---|
| **Career stat sums** (CareerPassYds, CareerTackles…) | `build_ncaaf_player_master:173` | seasons played / longevity | per-game or per-season rate | ✅ |
| Team **summed yds / returning_offense / returning_players** | `build_ncaaf_current_season_context:523` | roster size + games | per-game; **returning production as a SHARE (%)**, not a count | ✅ |

## Class C — HIT RATE (count of wins) → ROI (value-weighted)

A hit *rate* is a count-based success rate that ignores **price** — the volume it hides is
*what each win paid.* A 55% hit rate can lose money; a 48% one can print. ROI is the rate that
divides price back in.

| Counting metric | Where | What it ignores | → Rate replacement | Now? |
|---|---|---|---|---|
| Calibration **overall + per-bucket hit rate** | `model_calibration.run_calibration:334`, `summarize_bucket:226` | price / odds | **ROI / EV per bucket** | ✅ price fields in results |
| Signal cohort **hit_rate** | `grade_signals._cohort:142` | price | **ROI per cohort** | ✅ |
| MLB launch **reliability hit_rate** | `calculate_mlb_launch_reliability:4316` | price | ROI | ⚠️ needs MLB price history |

> Template already done right: `summarize_candidate_archive` pairs hit rate **with ROI**
> (`_archive_roi_for_resolved:12568`), and the ticket scoreboard carries side-ROI. Copy that
> pattern into the calibration + signal layers.

---

## Data gaps — what must be sourced before some rates exist

| Rate we can't build yet | Needs | Note |
|---|---|---|
| Player **per-snap** (snap share, routes) | nflverse **participation / snap counts** | not on the box; the slim PBP has team plays, not player snaps |
| Receiver **per-route** (yds/route, TPRR) | PFF-style routes-run | NGS gives *partial* rate context (separation, CPOE, aDOT) but not routes |
| CFB **per-possession** (ppg → pts/drive, pace) | CFBD **`/drives`** fetch | API supports it; not currently pulled. Unblocks the two CFB rows in Class A |

---

## Priority order (buildable now, by reach × trust)

1. **NFL def ranks → per-dropback / per-rush** (+ neutral-script from A2). Highest reach: feeds
   `build_nfl_matchup_edge`, `_nfl_prop_matchup`, `build_nfl_team_rankings_context`. Proven in A2.
2. **Hit rate → ROI** in the calibration + signal layers. Price fields are already in the
   results; highest *trust* payoff (a calibrated-looking model that loses money is the scariest
   honesty gap). Copy the candidate-archive ROI pattern.
3. **Usage yds_pg → per-target / per-play** (+ the A1 script-dependence flag). Cleans the
   opportunity lens for Wisdomism.

CFB per-possession and player per-snap/route are a **separate data-sourcing track** (CFBD
drives fetch; nflverse participation) — real, but blocked until the feeds exist.

---

## What this does for Wisdomism

Every rate conversion makes a lens measure the *thing* instead of the *volume*, which is what
lets the lens-independence test actually separate arguments. After Class A + C, the honest
lens-family count is likely the ~6 we landed on — opportunity, game-script/identity, market,
matchup, concentration, coaching — not the twenty it looked like before the audit.

---

*Written 2026-10-04 as Bucket 2 of the Averaging Audit. Inventory only — nothing migrated yet.
Build order above; CFB-drives and snap/route feeds are a separate sourcing track.*
