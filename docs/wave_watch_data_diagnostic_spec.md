# Wave Watch — Data & Diagnostic Phase + Shared Specification (read-only)

**Status: READ-ONLY DIAGNOSTIC + SPECIFICATION — rev 3 (2026-10-16). No code changed. No UI,
scoring, ranking, weight, or governance change.** Rev 3 adds the authority-language containment the
review required: (1) a full **inventory of every betting-authority phrase** on the CFB Wave Watch +
ATS Streaks surfaces with **frozen neutral replacements** (C6), separated into Facts / Context / Model
overlay; (2) the three CFB cohorts stay visible (C1); (3) **staged player-prop capability** — captured
record → price-adjusted return → CLV (C7); (4) the **player-prop cohorts are frozen** (≥3 graded
covers; ≤1 miss / ≥3 decisions) (C1); (5) CFB framed as **gradeable against the stored spread, not
ROI-reconstructable** without prices (−110 disclosed) (B1); (6) the **13-8 result made reproducible**
(cohort + grades + input fingerprint + method) (B1); (7) **execution split into two gates** (C8). The
appendix's single "overbought" retraction is now **superseded by the full C6 inventory**.

Rev 2 applied the six approved factual corrections to `29d2c3a`, each verified against the data: (1) NFL `NFL_AllPropResults`
→ **PARTIAL** (`OpenLine`/`CloseLine`/`OpenPrice`/`ClosePrice` are 0% populated; one direction/row;
only `BetLine`/`BetPrice`); (2) NBA inherits the approved **retrospective/timestamp** ruling (duplicate
snapshots confirmed, ~1,231 unique after dedup); (3) CFB is a **promotion/hierarchy** issue, not
visibility suppression (all five render; only UCLA promoted to "This Week's Hits"); (4) adds the
**one-loss ATS cohort** (Perfect start / Active wave / Strong season record); (5) includes the **2026
3-0 → 13-8 ATS (61.9%, ≈+3.8u)** point-in-time result; (6) replaces the unsupported "prod can't desync"
claim with a **synchronized-generation requirement**. The canonical-observation standard is unchanged.
Produced per the Director's directive to replace the
"eye-test reconstruction" with a data/diagnostic phase across three tracks (CFB team ATS, NFL player
props, NBA player props), define one canonical observation, audit CFB admissions on *synchronized*
inputs, and report honestly what prop-line history is reconstructable vs missing vs stale.

Governing principle (frozen for the spec in Part B): **every qualifying team or player stays
VISIBLE; the model is only an explanatory overlay, never a filter that removes a row.** The site
detects the wave early, shows the facts that explain it, and the user decides whether to ride it.

Date: 2026-10-15.

---

## PART A — DATA INVENTORY & FRESHNESS

### A1. Track 1 — CFB team ATS

| File | What | Fresh (local) | Fit |
|---|---|---|---|
| `data/scenarios/cfb_ats_streaks.json` | active cover/fade runs + this week's line | 10-15 (Wk7) | the streak board |
| `data/scenarios/cfb_2026_ats.json` | per-team season ATS record (`ats`,`cover`,`acm`,`n`) | 10-15 | Wave Watch's record input |
| `data/scenarios/cfb_2026_results.json` | game scores (thru Wk6) | 10-10 | grading inputs |
| `data/tracking/NCAAF_GameLineResults.csv` | graded SPREAD rows (Team/Week/Line + scores) | 10-15 | the ATS backtest source |
| `data/historical/CFBD_Lines_2016_2025.csv` | closing spreads 2016-26 | 09-12 | historical lines |

**Freshness finding (already hit this session):** the surfaces were **de-synchronized locally** — I
had re-run only `build_cfb_ats_streaks.py`, so the streak board was Wk7 while `cfb_2026_ats.json`
(Wave Watch's record input) was stuck at 09-26 (~Wk4), producing the "3-0 vs 5-0" mismatch. Re-ran the
stale builders locally (`build_cfb_2026_ats`, `fetch_cfb_line_moves`, `build_cfb_rankings`) to restore
parity. `NCAAF_GameLineResults.csv` is graded only through Wk2 of 2026 locally (its grader
`build_ncaaf_game_line_backfill.py` is **not** in the daily pipeline) but has **complete 2021-2025**,
which is what the continuation study needs.

**Correction — this is NOT a prod-immune problem.** Running every builder in one `refresh_cfb_data`
script is **not atomic publication**: a sequential daily refresh can **partially fail** (a mid-run
CFBD error, timeout, or earlyoom kill) and leave the scenario files from **different update
generations** — exactly the skew above, just by failure rather than operator error. The spec must
therefore **enforce synchronized generations** (C4), not assume them.

### A2. Track 2 — NFL player props

| File | Rows/size | Seasons | Fresh | Role |
|---|---|---|---|---|
| `data/tracking/NFL_AllPropResults.csv` | 22.5 MB, 78 col | **2024-2025** | 10-15 | historical graded record |
| `data/tracking/NFL_PropLines_Archive.csv` | **0.0 MB**, 11 col | 2026 | **09-30 (stale)** | daily CAPTURE (no result) |
| `data/tracking/NFL_PropLines_Graded.csv` | 0.1 MB, 14 col | 2026 | **09-30 (stale)** | current-season graded capture |
| `data/historical/NFL_Props_History.csv` | 4.3 MB | — | 05-24 (old backfill) | legacy backfill |

### A3. Track 3 — NBA player props

| File | Rows | Coverage | Fresh | Role |
|---|---|---|---|---|
| `data/tracking/NBA_AllPropResults.csv` | 5,290 | **2025-26, SnapshotDate 2026-05-28 → 07-18 (playoffs only)**; ResultDate on 2,047 (~39% graded) | 10-15 | historical graded record |
| `data/props/NBA_Props.csv` | — | stale/empty (off-season) | 07-28 | current board input |
| current 2026-27 season | — | **none — season opens ~late Oct 2026** | — | — |

**The 10-15 mtime does NOT make NBA observations fresh or point-in-time.** Inheriting the approved
NBA ruling (`docs/nba_results_diagnostic_2026-10-12.md`): the NBA graded record is a **single
retrospective batch lineage** with **unreliable pre-event timing** and **duplicate snapshots** (this
inventory confirms 188 of 540 markets carry more than one snapshot), reducing to **~1,231 unique
graded markets after deduplication**. It is **retrospective / descriptive** and **cannot establish a
trustworthy prop-wave record** — treat it as history to study, never as a live or point-in-time wave.

---

## PART B-prereq — THE CANONICAL OBSERVATION

**You cannot establish a prop-line record from a game log.** One graded wave observation is defined
as exactly one **(player · stat market · game · direction)** row carrying:

| Required field | Why |
|---|---|
| player identity | the subject |
| stat market | e.g. Rec Yds, Points |
| game (date + opponent, ideally an EventId) | the event |
| **source** (sportsbook, or a defined consensus rule) | which market |
| **line type** — one of OPENING / CAPTURED / CONSENSUS / CLOSING, **labeled** | a 3.5 at open ≠ at close |
| **line value** | the number graded against |
| **both prices** (Over and Under American odds) | ROI needs the actual price, not just W/L |
| actual result | the stat the player produced |
| **capture timestamp** | when the line was seen (for CLV / line-move) |
| **push / void handling** | line == result is money back, not a loss |

### Reconstructability against that bar

| Source | player | stat | game | source | line type | both prices | result | timestamp | push | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **NFL_AllPropResults (2024-25)** | ✅ | ✅ | ~ (GameDate+Opp, no EventId) | ✅ Book | ⚠️ **CAPTURED only** — `OpenLine`/`CloseLine` columns exist but are **0% populated**; only `BetLine`/`CurrentLine`/`Line` (100%) | ⚠️ **one direction per row** (17,394 OVER / 17,394 UNDER); `OpenPrice`/`ClosePrice` **0% populated**, only `BetPrice`/`MarketPrice` (99.9%) | ✅ ResultValue | ✅ SnapshotDate/WrittenAt | ✅ OutcomeState/Hit_Binary | **PARTIAL** — supports an against-the-line hit record + **directional return at `BetPrice`**; **cannot** do open-vs-close or two-sided (both-price) reconstruction |
| **NFL_PropLines_Graded (2026)** | ✅ | ✅ | ✅ Game | ~ BookCount only | ⚠️ **captured only** (no open/close) | ✅ OverOdds+UnderOdds | ✅ Actual | ✅ SnapshotDate | ❌ no push field | **PARTIAL + STALE** (09-30) |
| **NFL_PropLines_Archive (2026)** | ✅ | ✅ | ✅ | ~ | captured only | ✅ | ❌ no result | ✅ | ❌ | capture-only, **STALE/THIN** |
| **NBA_AllPropResults (2025-26)** | ✅ | ✅ | ❌ **no game key** | ✅ Book | ~ open/close columns, population unverified | ⚠️ per-direction | ⚠️ 2,047 of 5,290 graded (~39%) | ⚠️ **unreliable pre-event timing** | ~ OutcomeState | **PARTIAL / RETROSPECTIVE** — one batch lineage, duplicate snapshots (188/540 markets carry >1 snapshot), ~1,231 unique graded markets after dedup (approved NBA diagnostic). Descriptive only; **cannot establish a trustworthy prop-wave record** |
| current NBA 2026-27 | — | — | — | — | — | — | — | — | — | **NONE (off-season)** |
| any game-log file | ✅ | ✅ | ✅ | **✅ has no line at all** | — | — | ✅ | — | — | **NOT a prop record — do not use** |

**Headline gaps:**
1. **No source currently supports complete two-sided prop-line reconstruction — not even the
   completed seasons.** `NFL_AllPropResults` (2024-25) is the richest, but its `OpenLine`/`CloseLine`/
   `OpenPrice`/`ClosePrice` are **entirely empty** and each row is a single direction, so it supports
   an **against-the-line hit record** and a **directional return at `BetPrice`** — not open-vs-close
   movement or a two-sided market. The current-season capture (`NFL_PropLines_Archive/Graded`) is
   stale (09-30), thin, captured-line-only, no push field, book-count-only source.
2. **NBA has no current-season prop history** (off-season) and the historical file is **retrospective**
   — one batch lineage, unreliable pre-event timing, duplicate snapshots, no game key, ~1,231 unique
   graded markets after dedup (per the approved NBA diagnostic, `docs/nba_results_diagnostic_2026-10-12.md`).
   Descriptive only.
3. **CFB team ATS is the one fully GRADEABLE track** (cover/no-cover/push is certain from the stored
   closing spread + score, 2021-25 complete). It is **not fully ROI-reconstructable** — no captured
   ATS price is stored, so unit returns assume −110 (B1). Its current-season surfaces are reliable
   **only when the inputs share one refresh generation** (A1, C4) — a requirement to enforce, not an
   assumption to assert.

---

## PART B — DIAGNOSTICS

### B1. CFB team ATS — continuation beginning at 3-0 (2021-2025, real closing lines)

From `NCAAF_GameLineResults.csv` (graded SPREAD, 5 complete seasons, ~13.6k team-games), **next-game**
cover rate by the streak a team ENTERS the game on:

| Entering streak | Next-game cover % | n |
|---|---|---|
| baseline (all) | 50.0% | 13,610 |
| exactly 3 | 52.8% | 684 |
| 4+ | 46.0% | 520 |
| 5+ | 45.5% | 202 |
| 6+ | 47.9% | 71 |

Breakeven −110 = 52.4%. **Descriptive, not a forecast or a fade signal** (noisy sub-samples; OOS not
yet modeled). The historical read: a 3-0 wave continues at roughly a coin flip and **decays the deeper
it runs** — consistent with "the market catches hot teams."

**Gradeable vs ROI-reconstructable (disclosure).** CFB ATS is **fully gradeable against the stored
closing spread** — cover / no-cover / push is certain from the stored spread + final score. It is
**not** fully reconstructable for *actual* ROI, because these rows carry **no captured moneyline/price**
for the ATS bet. Therefore **every "ROI" / "units" figure here (and on the live surface) assumes a flat
−110** and is labeled as such; a real return needs captured prices (same gap as the player-prop
tracks).

**Current-season (2026) point-in-time result — the reason this diagnostic exists.** Of the teams that
reached **3-0 ATS** this season, **21 FBS teams** qualified; their **next played, graded game** went
**13-8 ATS = 61.9%**, ≈ **+3.8 units** at an assumed −110 (per the disclosure above). This is
**descriptive and not validated** (one season, n=21, no price/push/CLV modeling, point-in-time
eligibility only) and it runs *against* the multi-year decay above — which is exactly why the wave
deserves a visible, factual board rather than a model verdict: a single season can diverge sharply
from the 2021-25 base rate, and the user should see both.

**Reproducibility of the 13-8 result (required before it is cited as product context).** The figure
must be regenerable, not asserted. Preserve: (a) the **21-team cohort** — each team, the week it
reached 3-0 ATS, and the three covers that qualified it; (b) each team's **next graded game** with
opponent, stored closing spread, final score, and cover/no-cover (the 13-8); (c) an **input
fingerprint** — the source file(s), their run-id/through-week, and row counts used (so a re-run proves
the same inputs); (d) the **calculation method** — point-in-time eligibility rule, push handling, and
the −110 assumption. Byes are **no wager**, not a loss or a streak break. Until (a)-(d) are stored and
a re-run reproduces 13-8, the number stays an internal diagnostic note, not surface copy.

### B2. CFB admission/exclusion audit (synchronized inputs)

`build_cfb_wave_context` logic, read directly:
- **Admission gate:** a team enters the wave iff FBS **and** `n ≥ 3` **and** `cover ≥ 60%`
  (`app.py:44188`-ish). **All five of the Director's teams pass** (Georgia 83%, others 100%).
- **Surfacing/ranking:** rows are then split into `wave_hits` (2) + `wave_tiers` (3) + fades, where a
  **hit = an underrated coverer** (AP "surging/rising" or SRS-vs-prior divergence, `tier 0`) **into a
  number the model still likes** (`edge = their_proj + their_line > 0`). Teams whose number the model
  reads as already **priced** (edge ≤ 0) and that carry no "underrated" status fall below the surfaced
  shortlist.
- **Result for the five (on synced data):** **all five render on the full Wave Watch page**
  (`cfb_wave.html` renders every `wave_tiers` group — each is `{tier, label, plays}` — beneath the
  promoted section; the context carries all five). **Only UCLA is promoted into the primary "This
  Week's Hits" section** (a hit = underrated + positive model edge). Oregon State, Utah, BYU, Georgia
  remain present, in the tier groups below, with the model reading their number as priced.

**Corrected finding (was overstated in the pre-review draft):** this is a **promotion / hierarchy
problem, not complete visibility suppression.** All five stay in the full inventory; one is promoted.
It still matters — **most users treat the first shortlist ("This Week's Hits") as *the* actionable
list**, so a covering team demoted below the fold is effectively out of view for practical purposes —
but the accurate statement is *demoted, not removed*. Whether the model's "priced" demotion is *right*
is a separate, unproven question (B1 says a deep streak is a coin flip on average; it says nothing
about a specific team).

### B3. Player-prop surfaces using stale/incomplete records

- **NFL Riding-the-Wave / prop-streak surfaces** read the graded record; the **current-season (2026)
  capture is stale (09-30) and thin**, so a live NFL player-prop wave is only partially current. The
  under-streak surface was repointed earlier this session to `NFL_AllPropResults.csv`, whose **latest
  complete season is 2025** — so "current" NFL player prop waves lean on a record that lags the live
  slate unless the capture runs.
- **NBA** has **no current-season prop data** and a playoff-only, partially-graded, game-key-less
  historical file — an NBA player-prop wave is **not reconstructable for the opening slate** without a
  live capture.

---

## PART C — SHARED WAVE WATCH SPECIFICATION (design only, not implemented)

One model for both team ATS and player prop waves. **Every qualifying subject stays visible; the
model is an explanatory overlay.**

### C1. Qualifier (visibility), per track
- **CFB team ATS — three separate FACTUAL cohorts** (a single "active streak ≥ 3" gate wrongly omits
  one-loss teams like 5-1 / 4-1 whose *current consecutive* run is short). A team may carry **multiple
  labels**; **none is model-filtered**, and all render:
  - **Perfect start** — the team's **first three graded ATS decisions were all covers**.
  - **Active wave** — **current consecutive cover streak ≥ 3** (today's streak board).
  - **Strong season record** — **≤ 1 ATS loss with ≥ 3 graded decisions** (captures Georgia 5-1,
    which the active-streak gate would drop even though it is 5-1 ATS).
  - Symmetric fade cohorts apply the same way.
- **NFL / NBA player props — frozen cohorts** (no longer TBD), per the canonical observation in
  B-prereq; both are factual, a player may carry both, and **neither is model-filtered**:
  - **Active prop wave** — **active Over or Under streak ≥ 3 graded covers** vs the posted line.
  - **Strong line record** — **≤ 1 miss across ≥ 3 graded decisions** vs the line (the one-miss
    analogue of the CFB "Strong season record" cohort).

### C2. The row carries FACTS (verifiable, source-labeled), never a verdict
Team: record, active streak, avg cover margin, the run's weeks, this week's line + line-move, opponent.
Player: O/U record, active streak, avg margin above/below the line, streak start + games, **line-move
as the market adjusts**, **actual price + price-adjusted return**, role (snaps/minutes, usage/targets/
carries), opponent + injury context, **whether the player remained available**. Each number labels its
**line type** (captured vs closing) and **source**, and handles **push/void** explicitly.

### C3. The model is an OVERLAY, never a filter
The model attaches a read — e.g. *"still underrated (model edge +X)"*, *"priced (edge ≈ 0)"*, *"soft
spot"* — **beside** the row, and may sort, but **must not remove** a qualifier from view. B2's
"priced → off-screen" behavior is the anti-pattern this spec exists to end: a covering team the model
dislikes stays on the board with the model's reason shown, so the user sees the wave the model is
fading and decides for themselves.

### C4. Data prerequisites before any build (gating)
1. A **live, running capture** of the current-season prop market (NFL now; NBA at tip-off) writing the
   full canonical observation — **captured AND closing line, both prices, source, timestamp, push** —
   not a game log, not a stale 09-30 file.
2. The current-season graded record folded in only once it meets the canonical bar; until then the
   surface shows **Pending / line-type = captured**, never a fabricated closing record.
3. **Synchronized-generation requirement** (replaces any "prod can't desync" assumption). Before any
   surface renders a *combined* conclusion from multiple sources (streak board + ATS record + lines +
   results), the inputs must be proven to share one generation:
   - a **shared refresh/run identifier** stamped on every file a run produces;
   - **source-through-week metadata** on each file (which season/week it is current to);
   - a **parity check** at read time — if the inputs disagree on run-id or through-week, do **not** mix
     them into one conclusion;
   - a visible **"sources not synchronized"** state (name the lagging file + its through-week) instead
     of silently blending generations. This makes a partial-refresh failure *loud*, not invisible.

### C6. Authority-language inventory & frozen neutral replacements

The live surfaces turn descriptive ATS history + a model difference into **betting authority**. Every
phrase below is frozen to neutral wording that keeps the three layers separate — **Facts** (record,
streak, next line, sample), **Context** (historical continuation + the 2026 point-in-time result),
**Model overlay** (the model–market difference shown *beside* every qualifier, never used to remove
one). No *ride / fade / bet / hit / edge / overbought / underrated / overrated* verdict survives.

| Current phrase (live) | Location | Frozen neutral replacement | Layer |
|---|---|---|---|
| "the **edge** is a team covering because it's **genuinely underrated**, into a number the model still likes" | `cfb_wave.html:41` | "teams covering ATS this year, with the model's read of each number shown beside it" | Facts + Model overlay |
| "**This Week's Hits**" (promoted section header) | `cfb_wave.html:50,52` | "Covering, and the model still projects a cover" — a labeled group, **not** a promoted shortlist | Model overlay |
| "covering **because they're better than the market rated them**" | `cfb_wave.html:53` | "covering, and the model's number is higher than the closing line" | Model overlay |
| "**Ride until it does**" | `cfb_wave.html:73` | "the model still projects a cover; the market may adjust" (statement, not instruction) | Model overlay |
| "the cover is **baked into the number** now. Neutral." | `cfb_wave.html:74` | "the model and the closing number agree" | Model overlay |
| "**Fade the Sinkers** (anti-wave)" | `cfb_wave.html:90,92` | "Not covering" — teams missing the spread (a factual cohort) | Facts |
| "a spot to **bet the opponent**" · "**FADE** {line} → back {opp}" | `cfb_wave.html:93,99` | "the model projects a miss against this line" (no bet instruction) | Model overlay |
| "**overrated**, model projects them to **miss this number** — **bet {opp}**" | `cfb_wave.html:100` | "the model's number is below the closing line; it projects a miss" | Model overlay |
| "The **edge** is the **underrated** tier … its mirror, an **overrated** sinker the model fades" | `cfb_wave.html:121` | "a streak is where you start; beside each, the model's number-vs-line difference — context, not a signal on its own" | Context + Model overlay |
| "this shows you **who's overbought**, not who to ride" | `cfb_ats_streaks.html:72` | "over 2021-25 a deep cover streak continued at ~46–50% next game, below the 52.4% breakeven — a descriptive record, not a forecast or a fade signal" | Context |

The model-overlay labels (surging / rising / priced / soft; tier 0/1/2) **stay as a read beside each
row, never as a gate** that removes a qualifier. The responsible-gambling line stays; "spots, not
locks" / "don't force it" are retained as caution, not promotion.

### C7. Staged player-prop capability (build only what the data supports)

The absence of closing history must **not** block an honestly-labeled captured-line streak surface.
Three stages, each gated on the source meeting the canonical bar (B-prereq):
1. **Captured-line record** — W/L/push vs a **timestamped captured line**, with line-type labeled
   "captured". Buildable now for any source recording a captured line + result + timestamp + push.
2. **Price-adjusted directional return** — a unit return **only where the recorded price supports it**
   (e.g. NFL `BetPrice`). Where no price is recorded, show W/L/push with **no** return — or a
   −110-assumed figure **explicitly disclosed** (see B1 / #6).
3. **Open → current → close movement + CLV** — **only after complete two-sided capture exists** (both
   prices, open and close). Until then this stage is **Pending**; nothing fabricates a closing record.

### C5. Explicitly out of scope here
No UI, no scoring, no new weights, no governance/status labels, no "edge" or "fade" claim. The
continuation numbers (B1) stay **descriptive**. Those decisions follow review of this diagnostic.

### C8. Execution gates (sequencing only — not an authorization)
1. **Gate 1 — CFB Wave Watch hierarchy + wording remediation.** Implementable from existing data: the
   three visible cohorts (C1), the neutral replacements (C6), and the "every qualifier visible, model
   as overlay" structure. No new data needed.
2. **Gate 2 — NFL/NBA prop-capture infrastructure.** The live capture writing the full canonical
   observation (C4 #1, C7) must be specified and *verified* before the complete player-prop Wave Watch
   is built. Gate 2 does not start until its data prerequisite is met.

---

## Appendix — overclaim retraction (now folded into C6)
The CFB ATS Streaks tool shipped earlier (`242a7a9`) carries *"this shows you who's overbought, not who
to ride"* — a productizable fade read B1 does not establish. **This is now one row of the full C6
authority-language inventory**, not a standalone retraction: C6 freezes its neutral replacement
alongside every other ride/fade/bet/edge/underrated phrase on the CFB surfaces. All held per the
product freeze; nothing edited in this read-only phase.
