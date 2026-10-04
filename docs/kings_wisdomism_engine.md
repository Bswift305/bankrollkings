# Kings Wisdomism — Engine Brief & Brainstorm Starter

> **Status:** concept / brainstorm. Nothing built yet. This doc exists so Darrel + the
> dev team (CoCo included) can kick the design around before anyone writes code.
> It captures the *manual* process we ran on the 2026-10-03 NFL Week 5 session and
> proposes turning it into one engine + one page: **Kings Wisdomism** (`/tools/wisdomism`).
>
> Judge every idea here against `BANKROLL_KINGS_DOCTRINE.md` and `CLAUDE.md` §10.

---

## 1. The vision (Darrel's words, paraphrased)

> "I show up, and the site spits out the list for me — best to good — of **independent
> ways to cover my card**. Floors and swings, across different games, so I'm never
> betting one player five times. I don't want to run the whole process by hand every
> night."

So: **one page that runs the Discover → Evaluate pipeline automatically and outputs a
ranked, independent shortlist.** It is the *destination* the tools feed — the same role
the Daily Card plays, but driven by the full game-script → props → heat-map chain, and
built around **independence** (one leg per game) so the list is genuinely "multiple ways
to cover," not a single correlated bet in disguise.

This is the flaw it exists to fix: on 2026-10-03 we built three "diversified" cards that
were all anchored on Jahmyr Gibbs. If Gibbs misses, all three die together. Wisdomism's
job is to **never** hand back a list that lives or dies on one player.

---

## 2. What it automates — the manual flow we ran (make this concrete)

Five steps. Wisdomism = these five steps, run for you, every slate.

1. **Slate + market.** Pull the day's games, spreads, totals. The line and total *are*
   the market's expected game script. (Source tonight: ESPN scoreboard; in-repo:
   `fetch_game_lines.py`, the CFBD slate feed, `NFL_Odds` / board loaders.)

2. **Game-script read.** Overlay current-season form on each line to classify the
   script and the **prop lanes** it opens:
   - *Pass shootout* (both pass D soft) → QB pass yds + WR rec lanes
   - *Big-favorite run script* → RB rush lanes
   - *Run-stuffed* (both run D strong) → rush props UNDER, total rides on the air
   - *Defense controls* → opposing passing UNDER lane
   In-repo: `nfl_current_form.py` (`matchup_read`, `team_form`, def ranks, pressure,
   **QB adot** — the sharpest prop tell), `cfb_current_form.py` for college.

3. **Props pull, script-checked.** Pull the actual lines in those lanes and let the
   board **confirm or kill** the thesis. (Tonight the board killed our "Houston runs on
   Dallas" read — the top rush number belonged to a *Dallas* back. The engine must keep
   that veto power, not force the narrative.) In-repo: `NFL_Props.csv`, the prop-board
   builders.

4. **Heat-map / hit-profile check — with the line-delta gate.** For each candidate
   player, pull their resolved hit rate vs their line. **Critical honest step:** compare
   tomorrow's line to the player's *historical average* line. If the number got bumped
   up, the hit rate is void. In-repo: `NFL_Player_Hit_Profiles.csv` (428 players:
   HitRate, Resolved, AvgLine, Reliability tier), `/tools/nfl-heatmap`
   (`build_nfl_hot_hand`), `build_nfl_prop_floor`.
   - **Finding to preserve, not hide:** almost every consistent player has tomorrow's
     line moved up to erase the floor (Parker Washington 71% but line +41 over his
     norm; Kittle +10.6; Purdy +4.4). *The market already priced the consistency.* The
     heat map's real value is (a) confirming the rare number that *didn't* move
     (Shakir), and (b) catching **heat-vs-script conflicts** (Javonte Williams' history
     liked the number, but Houston's run D is #2 — don't bet a floor the script fights).

5. **Rank + enforce independence.** Produce the best → good list, **one leg per game**,
   each tagged floor / value-swing / dart, each with its drivers and its one honest
   knock. Rank by how many lenses agree (heat + script + line), then sample size /
   reliability / price value.

**Output of tonight's manual run (the target the engine should reproduce):**

| # | Play | Game | Why it ranked there |
|---|------|------|---------------------|
| 1 | Shakir O3.5 rec | NE@BUF | heat + script + line all agree |
| 2 | Henry O96.5 rush | TEN@BAL | best script floor (−11.5 fav, 30th run D) |
| 3 | Gibbs O94.5 rush | DET@CAR | elite matchup (32nd run D), less script-certain |
| 4 | Chase O7.5 rec (+120) | JAX@CIN | best value swing |
| 5 | Jennings O2.5 rec (+100) | MIA@MIN | heat loves it; role unproven |
| 6 | Smith-Njigba O91.5 rec | LAC@SEA | WR1, but high bar / variance |

---

## 3. The honest core — non-negotiables (from the doctrine)

These are the rails. The point of Wisdomism is to be the *honest* version of a "best
bets" generator, which is exactly the kind of thing most sites fake.

- **No composite 1–100 score. No "lock." No auto-EV list. No cross-sport best-bets
  ranking. No Kelly / auto-staking.** All explicitly on the do-not-build list. A ranked
  list is allowed **only** if the rank is transparent and within a single slate/sport —
  never a black-box number that implies profit.
- **Rank by tiers + visible drivers, not a hidden score.** Floor / value-swing / dart,
  each showing the heat %, the sample, the line-delta, the script reason, and the knock.
  The user sees *why* #1 is above #3.
- **The line-delta gate is mandatory.** If the market moved the number past the player's
  history, the play is downgraded or dropped, and the engine *says so.* This is the
  doctrine's "it's already priced" lesson, enforced in code.
- **Independence = one leg per game.** The whole product promise. Flag shared-game legs;
  never present correlated legs as independent cover.
- **Availability states** (Verified / Partial / Pending / Stale / Unavailable) so a
  missing lane never reads as neutral.
- **It makes no profit claim.** Wisdomism surfaces *context and consistency*, labeled as
  such — not predicted edge. Combined odds on any multi-leg view stay labeled "assumes
  independence."

---

## 4. Proposed shape (reuse what exists — don't rebuild)

- **Engine:** `build_kings_wisdom(sport, slate_date, legs_wanted=None)` → ordered list of
  play dicts (player, stat, line, price, game, tier, drivers{}, knock, availability).
- **Reuses:** `nfl_current_form` / `cfb_current_form` (script), the prop-board builders
  (lanes + lines), `NFL_Player_Hit_Profiles.csv` + `build_nfl_prop_floor` (heat), and
  `_card_pools` / `render_daily_card` (to also emit a card, closing into the Daily Card
  destination).
- **Page:** `/tools/wisdomism` → `kings_wisdomism.html`. Ranked list up top (best→good),
  each row expandable to drivers + knock; optional "render as card" + "split across top
  N" helpers (helpers only — user sizes their own stake; no auto-staking).
- **Caching:** `_build_file_token` must include **every** input (slate, props, form,
  hit-profiles) — a cached builder that misses an input serves a stale list forever
  (CLAUDE.md §4).
- **Sport scope:** **NFL first** (deepest data: props + hit profiles + form). CFB next
  at the team level (college player props are too thin — see the CFB ATS Streaks work).
  Each sport is its **own** list; they are never merged into one ranking.
- **Close the loop:** wire Wisdomism's own output into the daily capture + the Signal
  Report Card so the page's picks get **graded** over time. A recommendation engine we
  can't score later violates the doctrine's second filter.

---

## 5. Open questions for the brainstorm (CoCo — have at it)

1. **Ranking without a banned score.** *Leading answer (see §7): rank by evidence
   convergence, not goodness.* The two unresolved pieces for CoCo: how do we **measure
   lens independence** (so "4 lenses agree" isn't one signal counted four times), and
   how do we wire in the **un-priced gate** (convergence the market already sees is
   context, not opportunity)?
2. **The "knock" generator.** Auto-write each play's one-line caveat from the drivers
   (big-fav blowout risk, high-line variance, role change, heat-vs-script conflict), or
   keep a curated caveat library? How do we keep it from reading like boilerplate?
3. **Independence vs. depth.** One leg per game caps the list at ~14 on an NFL Sunday.
   Enough? Do we ever allow a *second* leg in a game if it's a different, uncorrelated
   stat — and how do we prove "uncorrelated" without overclaiming?
4. **Stake-split helper.** Darrel wants "multiple ways to cover." How far can a
   split-your-stake helper go before it's auto-staking / Kelly (banned)? Proposal: show
   the independent plays and *let the user* choose singles vs small parlays; the engine
   never recommends unit sizes.
5. **Grading / honesty feedback.** What's the minimum to grade Wisdomism's lists weekly
   and show the record on the page itself (good decisions ≠ good outcomes — show the
   process record, not a win-rate brag)?
6. **Naming & placement.** "Kings Wisdomism" as the page title; route `/tools/wisdomism`
   (or `/wisdom`?). Where in the loop nav does it live — is it *the* Evaluate→Build
   destination that outranks the standalone Daily Card, or a sibling?

---

## 6. What already exists we can stand on (so nobody rebuilds)

| Piece | File / route | Gives us |
|---|---|---|
| Current-season form | `nfl_current_form.py`, `cfb_current_form.py` | game script, def ranks, pressure, QB adot |
| Props board | `NFL_Props.csv`, prop-board builders | lines in each lane |
| Player heat map | `NFL_Player_Hit_Profiles.csv`, `/tools/nfl-heatmap`, `build_nfl_prop_floor` | hit rate, sample, AvgLine, reliability |
| Card render | `marketing/generators/weekly_cards.py` `render_daily_card` | emit the list as a card |
| Daily Card pools | `_card_pools`, `build_daily_cards` | existing floor/swing pool logic |
| Capture + grading | `capture_*`, `grade_signals.py`, `/tools/signal-report` | close the loop |

---

---

## 7. The ranking model — convergence, not goodness (Darrel's answer to the core tension)

Kings Wisdomism should **not rank by how good a play is.** It should rank by **how much
independent evidence converges on it.** That surfaces a real hierarchy without ever
claiming edge:

- **Highest conviction** — multiple independent lenses agree
- **Strong context** — three agree
- **Worth investigating** — two agree
- **Single-lens idea** — one lens only

This avoids "94/100 BEST PLAY OF THE DAY" while still giving the user a top-to-bottom
list. You're ranking **evidence convergence, not predicted profit** — a very different,
and doctrine-safe, claim.

**Two fixes this needs to actually be honest** (or it recreates the very trap the engine
exists to kill):

1. **Lens independence is the whole game.** Four lenses agreeing only means something if
   the four are *independent*. If current-form, matchup, and the line all encode the same
   underlying "this team is good," then "4 lenses agree" is **one signal counted four
   times** — false conviction. This is the three-Gibbs-cards trap one level up. The engine
   must track *which lenses are independent of each other*, not just count how many fired.
2. **Convergence the market can see is already priced.** Tonight's heat-map finding,
   restated: lenses agreeing **and** the number moved to match = *context*. Lenses
   agreeing **and** the number didn't move = the real flag. So the top tier is
   "independent lenses converge **AND** the line hasn't priced it," not convergence alone.

---

## 8. The dimensions frontier — what we're still averaging away

The sharper question than "what feature next?" is **"what important variable are we not
inviting into the room?"** Every recent breakthrough (opportunity vs production, buy-low
vs sell-high, 1Q/1H behavior, process vs outcome, CLV vs win rate) came not from new math
but from **refusing to let an average hide context.** An average collapses a distribution
to one number; the signal is in what got collapsed. There are five ways it hides:

| An average can hide... | Example | Where we are |
|---|---|---|
| **When** (within-game time) | 1Q/1H, fast vs slow starters | started — CFB period board |
| **Under what conditions** (game state) | pass-when-trailing *identity* | **frontier — strongest** |
| **To whom** (concentration) | red-zone TD / target concentration | **frontier** |
| **Vs whom** (opponent / venue) | SRS opponent adjustment | mostly done |
| **How reliably** (shape, not mean) | floors vs production | started — hit profiles |

The two untouched frontiers — **game-state conditionality** and **concentration** — are
exactly the ones that *manufacture props*, which is why they matter most.

**Ranked by the only test that counts (survives "already priced / out-of-sample"):**

1. **Game-script identity** — the best, because it's a *conditional*, not a prediction:
   "IF the game goes this way, THIS player's volume spikes." Plugs straight into the
   game-line read (spread/total predicts the script → identity names who benefits). Fully
   measurable from the 7 seasons of nflverse PBP we already have (`NFL Scenario Engine`).
2. **Coaching behavior** (4th-down aggression, pace, red-zone run/pass) — underrated,
   because *the market prices the star QB, not the OC's tendencies.* Structural, boring,
   roster-stable → the least-priced thing on the list. Same PBP source.
3. **Red-zone concentration** — won't move a spread, but **destroys the anytime-TD
   market**: casual money spreads TD bets across names while one back gets 80% of the
   goal-line work. Underpriced because it's unglamorous.
4. **Market-shock events** (injury happened + line barely moved, *or* moved a lot) — keep
   it, but as a **"go investigate" flag**, never a bet. By construction it's a
   priced-vs-unpriced detector — the Research Engine layer, not a pick.
5. **Time-slicing (1Q/1H)** — real but with a known ceiling: 1H/1Q lines are *themselves*
   priced, so it's a context + period-bet finder, not an edge.

**The guardrail on this whole thesis:** every time you de-average, you **trade bias for
variance.** Slice 3 games into halves → 3 half-samples; condition on "trailing in the 4th"
→ maybe 2 plays. The 1Q/1H insight was trustworthy because the *direction* was large and
consistent (Alabama slow, Miss State fast at home), not because a precise conditional
number was reliable. **De-average until the context appears, then stop before the sample
vanishes — trust direction and shape over fragile conditional point estimates.** (Same
lesson as the 3-leg parlay: +63% at n=21, −29% at n=2,861.)

---

## 9. The synthesis + the next step (not a board)

**"Find what's averaged away" and "rank by agreement" are the same project.**
De-averaging is how we *manufacture new independent lenses*; convergence ranking is how
Wisdomism *consumes* them. We only earn the right to rank by agreement by doing the work
to add lenses that are genuinely independent — each one a different thing the market
averaged away. **The audit feeds the engine.**

So the next step is not another score, board, or trend page. It's an **averaging audit**,
made concrete and cheap: one document that inventories every aggregate stat the site
currently shows, tags each with *which of the five dimensions it collapses*, and marks
whether a conditional version is buildable with data we already hold. That document is
both the "what are we washing out" map **and** the lens catalog Wisdomism ranks over.

---

*Written 2026-10-03 off the NFL Week 5 working session; §§7–9 added after the strategy
brainstorm with Darrel. Start at the doctrine, keep the line-delta gate, rank by
independent convergence (not goodness), keep it independent, make no profit claim, and
grade what it says. The audit feeds the engine.*
