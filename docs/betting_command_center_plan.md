# Betting Product — Pivot Plan (grounded in code audit)

> Status: PLAN ONLY. No code shipped from this doc yet. Written for Darrel + the
> developer to review/edit before any build. Date: 2026-06-25.

This is the pivot from Franchise Kings back to the core betting/analytics product.
It is grounded in a full audit of the existing betting code so we **build on the
engines that already exist** rather than rewriting them.

---

## 1. What already exists (audit summary)

The product is **mature and prop-first**. Confirmed in code:

- **Prop boards** across all six sports: `/sports/{nba,wnba,mlb,nfl,ncaaf}/props`,
  college hoops `/sports/ncaamb|ncaawb/props`, plus `/market-edge` smart-pick boards.
  Builders: `build_live_props_board()`, `build_mlb_prop_board()`,
  `build_wnba_prop_board()`, `build_football_live_prop_board()`.
- **Game-line pages** (sides/totals): `/sports/nfl/game-lines`,
  `/sports/ncaaf/game-lines`, `/sports/nfl/totals`, and a universal `/game-lines`
  hub (`game_lines_page()`). Intelligence builder:
  `build_football_game_line_intelligence()` (app.py:6274),
  `build_game_line_teaching_note()` (app.py:6242).
- **Parlay builder** `/parlay`: cross-sport, multi-leg, Kelly sizing
  (`calculate_bankroll_iq()`), live correlation alerts, saved tickets
  (`save_parlay_ticket()`, `analyze_saved_parlay_ticket()`).
- **Edge engines**: `calculate_nfl_edge_score.py`, `calculate_nfl_prop_score.py`,
  `calculate_ncaaf_edge_score.py`, simulation (`simulate_nfl_props.py`,
  `simulate_active_sport_props.py`), calibration summaries
  (`CrossSport_Calibration_Summary.csv`, `Sport_Driver_Calibration.csv`).
- **Market intelligence**: multi-book disagreement
  (`build_prop_multi_book_context()`), line-movement history CSVs per sport,
  Elite sharp-money/line-move scanners.
- **CLV is already stored** (`ClvLine`, `ClvPricePct` fields, app.py:~10344) —
  just not surfaced to users.

### The real gaps (where the to-do list maps)

| Gap | Status today | To-do item it serves |
|-----|--------------|----------------------|
| Cross-league game-lines board | per-sport pages exist; **no unified ranked board** | Game Lines Command Center / "Opportunity Season" |
| Discipline/education for regular users | guardrails + trap tags **computed but hidden / Elite-only** | Before You Bet, Heart-Bet warning, Pass Discipline |
| User bet-tracking dashboard | parlay tickets + Elite bet log only | Bankroll by type, CLV, bettor report card |

The encouraging part: **most of this is surfacing intelligence we already
compute**, not building new models.

---

## 2. Track A — Game Lines Command Center  *(recommended first)*

A single cross-league ranked board: NFL + CFB + (in season) NBA/CBB best
sides/totals/moneylines, sorted by edge, each with one intelligence card.

- **Reuse**: `build_football_game_line_intelligence()`, `build_game_line_teaching_note()`,
  `build_football_environment_note()`, EdgeScore components, line-movement CSVs.
- **New**: a thin aggregator that calls each sport's game-line builder, normalizes
  rows to a shared shape `{league, matchup, kickoff, side, model_line, market_line,
  edge, confidence, trap_flags, line_value_window}`, merges, ranks, and renders.
- **Card contents**: model line vs market, edge & confidence, line-movement read
  (opener→now), public-trap warning (wind/role/contradiction tags), and a
  "line-value window" (is the current number still a good number?).
- **Route**: extend `/game-lines` (`game_lines_page()`) with a `?view=command`
  cross-league mode, or a new `/game-lines/command`.
- **Why first**: headline of the Game Lines to-do, biggest *visible* gap, reuses
  the most existing engine code, and the cross-league board *is* the
  "Opportunity Season" concept made real.

## 3. Track B — Discipline & Education layer

Surface the intelligence currently hidden or Elite-gated, for free/pro users.

- **Before You Bet card** — pre-ticket checklist on `/parlay`: correlation risk
  (already computed), thin-market flags, contradiction warnings
  (`apply_*_contradiction_guardrails()` — currently hidden), stake-vs-bankroll check.
- **Heart-Bet warning** — "you keep betting the Lions — here's your record on them."
  Needs per-user bet history (see Track C) to be meaningful.
- **Pass Discipline score** — credit/track bankroll preserved by passing flagged
  traps; needs a lightweight "I passed" action + log.
- **Reuse**: contradiction guardrails, trap tags (`COLD`, `VOLATILE`, `ROLE SLIP`),
  `Live_Drift_Alerts.csv`, `/glossary`, `/responsible-gambling`.
- **Note**: keep framing as *analytics/education*, never personalized financial
  advice. Strong fit with responsible-gambling positioning.

## 4. Track C — Personal bettor analytics

A real bet-tracking dashboard for everyone, not just Elite.

- **Reuse**: Elite `/elite/bet-log` + `grade_manual_bet_logs()` patterns, stored
  CLV fields, parlay-ticket grading (`analyze_saved_parlay_ticket()`).
- **New**: open the bet log to all tiers; aggregate into bankroll-by-bet-type,
  weekly report card, CLV trend (you beat/lost the close), confidence calibration
  (are your A/B/C plays actually winning?), and personal leaks (best/worst leagues).
- **Dependency**: Track B's Heart-Bet warning leans on this history existing.

---

## 5. Suggested build order

1. **Track A — Game Lines Command Center** (standalone, reuses most, highest visibility).
2. **Track C — Bettor analytics** (unlocks per-user history).
3. **Track B — Discipline layer** (best once C provides history for Heart-Bet/Pass).

Each track ships in reviewable slices (engine → route → template → verify → deploy),
same cadence as the franchise work.

---

## 6. Decisions (answered 2026-06-25)

- **Tiering: gone.** Single price of admission — every member sees everything. No
  free/Pro/Elite split. So all the currently Elite-gated intelligence (line-move
  alerts, sharp-money scanner, bet log, guardrails) moves to *every* user.
- **CFB data: good to go.** `CFBD_API_KEY` is fine; CFB coverage is in scope for
  Track A.
- **Cross-league = all sports.** The Game Lines Command Center should span every
  sport from launch, not football-only.

## 7. Shipped from this plan

- **Market-independent power ratings + true model-vs-market edge** (`power_ratings.py`):
  Elo computed purely from final game results (NFL 1999-now, NCAAF 2025 FBS-only,
  WNBA & MLB from gamelog-derived team scores) — owes nothing to the betting market,
  so the comparison is honest. The board shows the model's home win% vs the market's
  no-vig implied win% (win-prob needs no points-scale calibration). Backtested
  straight-up accuracy: NFL .649, NCAAF .681, WNBA .585, MLB .508. A **skill gate**
  (`MIN_SKILL_ACCURACY = 0.55`) means **MLB is computed but NOT surfaced** — a coin
  flip is not an edge. Ratings persisted to `data/tracking/Power_Ratings.csv` +
  `_Meta.csv`; rebuild with `python power_ratings.py` (cron candidate). Shown on the
  Game Lines Command Center with a "Model ±X%" chip when the lean is >= 5%. SHIPPED
  2026-06-25. Model **spread-in-points** now shipped too: Elo->points fit by least
  squares on real margins (~4 pts/100elo NFL/WNBA, ~7 college, ~0 MLB so it stays
  gated). Board shows "Model line: HOME +/-x (mkt +/-y) -> +/-z pt value on TEAM" and
  a "Model +/-z pts" chip. Still open: (1) **refresh ratings on a schedule** (cron
  after the nightly data refresh — currently a manual `venv/bin/python
  power_ratings.py` on deploy); (2) **sync football history files** (data/historical/*)
  to prod so NFL/CFB ratings exist there (data/ is gitignored); (3) retire the old
  market-derived Team_Strength_Priors now that real ratings exist.


- **Game Lines Command Center** (`/game-lines/command`, `build_cross_league_game_lines`):
  one ranked board across every league with lines posted (NFL, CFB, NBA, WNBA, MLB),
  each game showing best market read (spread/total/ML), scoring environment, a plain
  teaching note, and notable spots to study — ranked by signal, framed honestly as
  market context (not a guaranteed winner). Reuses existing per-sport schedule + odds
  loaders and the market/environment helpers. Linked from `/game-lines`. SHIPPED
  2026-06-25. Now also carries: **line-shopping** (cents-on-the-table best ML across
  books, sign-consistent + capped), **line-movement** (opener->current spread/total,
  auto-activates when the feed captures multi-snapshot moves), and **football
  game-script tags** (NFL/CFB rows, populates in season). Still open: a true
  per-upcoming-game EdgeScore (projection vs market) — needs a live projection /
  team-strength-prior calibration, a separate larger build, not a display wiring.
- **Prop Betting Pointers Engine** (`prop_pointers.py`) — universal + sport-specific
  pointers and a sport profile (Opportunity / Reliability / Best market / Main trap)
  on every prop page via the shared `props.html`. Teaches while the user bets.
  Covers nba, wnba, nfl, ncaaf, mlb, ncaamb, ncaawb. SHIPPED 2026-06-25.
