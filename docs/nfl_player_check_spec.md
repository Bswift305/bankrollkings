# NFL Player Check — Specification (DRAFT v2, not implemented)

**Status: SPEC ONLY.** No Player Check code is to be written until this document is approved.
This revision (v2) incorporates the review corrections: market-level evaluation, surface-
specific entry gates, Live Props as the factual foundation, a frozen shared-predicate
centralization approach, robust name normalization, fixture-based tests, decided NFL/All-Access
placement, and corrected Menu coverage language.

**Surface (proposed):** an NFL player-search / explainability tool. The user types a player
name; the tool answers, honestly and per market:

> *What are this player's live NFL markets right now, and — for each of our surfaces — which of
> those markets flow through to it, which do not, and why?*

It is **decision-support and transparency**, not a recommendation. It never says a player is a
good or bad bet. It reports **facts** (the live markets) and **status** (how those facts do or
do not reach each curated surface), with reasons drawn from the same rules the boards run. It
fits the doctrine promise: *"We show the table. We show what has earned trust. We show what has
not. You decide."*

---

## 1. Why this exists — the real case (timestamped fixture, not a permanent assertion)

> **Fixture captured 2026-10-11 (illustrative only).** Lines, prices, lens counts, and tiers
> change daily. This snapshot motivates the design; it is **not** an assertion the
> implementation should encode. Implementation tests use controlled fixture data (§9), never
> today's live board.

On 2026-10-11, **Bijan Robinson** (ATL · RB) and **Drake London** (ATL · WR) were both among
the most-featured players in the league and appeared on Green Light + Featured, yet neither was
on the floor board or buildable in The Menu. The reason was coherent — they are surfaced by
**opportunity / convergence**, but at that moment their clearance at the posted line sat **below
the reliability (floor) threshold**, so the floor-first surfaces excluded them — but that
reasoning was invisible to the user. Player Check makes it legible, **per market**: a single
player can have one market that clears the raw floor, another that clears but fails the Menu
price band, and another that is unsupported — and the honest answer is *"no current Bijan
market qualifies for The Menu,"* not one blurred player-level verdict.

---

## 2. Core principle — one set of rules, one set of reason codes

**The explanation must be produced by the same gate logic the boards run — never a parallel
re-implementation.** This is frozen (see §5), not an open choice.

- One centralized catalog of reason codes (§7).
- One set of **shared, reason-producing gate predicates**. Each predicate both (a) decides
  inclusion for the board builder and (b) returns the reason code when it excludes. The
  builders and Player Check both call these predicates.
- A reason code is valid only if it maps to a real predicate. No code may describe a rule the
  boards do not enforce; no exclusion may happen without a code to name it.

**Acceptance criterion:** change a gate (a threshold, a new stat, a new rule) and Player Check's
output for an affected player/market must change in lockstep, because both paths call the same
predicate. If they can diverge, the implementation is wrong.

---

## 3. Evaluation model — markets first, then a per-surface summary

Player Check evaluates at the **market** grain and summarizes at the **surface** grain. A
"market" is one (player, stat/market, line, price, book) row from the live feed.

```
for each live market M of the player:
    facts(M)                      # line, price, book, feed timestamp, fact-availability
    for each surface S in [Floor, Menu, Green Light, Featured]:
        verdict(M, S) = INCLUDED(context) | EXCLUDED(reason_code, context) | N/A(S does not consume M)
summarize per surface S:
    if any market INCLUDED on S  -> "On S: <which markets>"
    elif any market is eligible-but-view-filtered -> "On S, hidden only by <filter>"
    else -> "No current <player> market qualifies for S" (+ the dominant reason code[s])
```

Rules:
- **Never collapse a player's markets to one player-level reason.** Show every market's verdict,
  then the surface summary.
- A surface that does not consume a given market type marks it `N/A` for that surface (e.g. a
  receiving market is `N/A` for a QB passing-only lens), not `EXCLUDED`.
- The summary names the dominant reason(s) but links to the per-market detail.

---

## 4. Live Props — the factual foundation (the starting point)

Player Check **begins with the facts**, independent of any curated surface, so a player can
always be found even when no board includes him. The top of the result shows:

- **Current matchup** (team, opponent, kickoff) for the player this week.
- **Feed timestamp** and **fact-availability status** (the existing fact taxonomy:
  Verified / Partial / Pending / Stale / Unavailable / Source-conflict).
- **Every available market** for the player: market/stat, line, price, and **book**, exactly as
  the feed carries them (`data/props/NFL_Props.csv` and the live props board that renders
  `/sports/nfl/props`).

Only after the facts are laid out does the tool explain how each market **flows — or does not
flow — into** Floor, Menu, Green Light, and Featured (§6). "Found with facts, zero curated
surfaces" is a valid, fully-explained result.

---

## 5. Centralization — FROZEN approach

The required approach (no longer an open question):

> **Extract shared gate predicates / reason-producing evaluators into one module, and make BOTH
> the existing board builders AND Player Check consume them.** A second implementation of the
> inclusion rules is not acceptable.

Concretely:
- A module (working name `services/nfl_player_check.py`, or a shared `nfl_inclusion` helper)
  owns the reason-code enum (§7) and the gate predicates.
- `build_nfl_floor_board`, `build_green_light`, `build_menu_board`, and `build_nfl_usage_board`
  are refactored to call these predicates for their include/exclude decisions, so the predicate
  is the single source of truth.
- `evaluate_nfl_player(name) -> PlayerCheckResult` walks the same predicates per market/surface.
- Threshold constants (floor-page 24/78, `_card_pools` 90/52, Menu floor ≥80 & price band,
  swing +odds & ≥55, `min_games`) live in one place and are read by both.

This refactor **is** the deliverable — the point of the feature is that the explanation cannot
drift from behavior.

---

## 6. Surface-specific entry pipelines (each starts from its OWN entry set)

There is **no single shared foundation**. Each surface begins from its actual entry pipeline;
the floor pipeline is one surface's pipeline, not a prerequisite for the others. References are
`app.py` unless noted.

### 6.1 Floor board — reliability pipeline
`build_nfl_floor_board(limit, min_hit, min_games)`. Entry set = players with a **supported live
prop market** this week. Per market:
1. Market present in `NFL_Props.csv`; `Stat` maps via `_NFL_PROP_STAT_MAP`; `Line` numeric.
2. Player resolves to a gamelog (`_nfl_player_index`), stat columns present
   (`_NFL_FLOOR_STATS`).
3. Window (season / L2Y / career) has ≥ `min_games`.
4. Hit rate ≥ `min_hit` (surface's own threshold; floor page = 78).
5. Ranked by `(-hit, -clears)`, sliced to `limit`.

### 6.2 The Menu — buildable board
`build_menu_board` fed by `_card_pools`. Entry set = the floor board at `min_hit=52`, **re-gated
to candidates**: a market is a **floor** only if `hit ≥ 80` and `-185 ≤ price ≤ 115`; a **swing**
only if `price ≥ 120` and `hit ≥ 55`; price must be valid American (`|odds| ≥ 100`). Then
timeframe / sport / tier / position filters; dedup by `(sport, label, game)`.

### 6.3 Green Light — convergence pipeline (its OWN entry set)
`build_green_light`. Entry set = the **opportunity/usage board** (`build_nfl_usage_board`), **not**
the floor board. Per featured player:
1. Player is in the usage board (carry/target/air-yards share); defenses excluded.
2. Player has the **primary over** — `Rush Yds` (backs) or `Rec Yds` (others). *(This is Green
   Light's entry-prop requirement; it is distinct from "on the slate" in general.)*
3. `convergence ≥ 1` lens **or** a TD angle.
4. Position filter (display-only, applied before the limit; selected position shows the complete
   set).

### 6.4 Featured Players — usage pipeline (can include a player with NO current prop)
`build_nfl_usage_board`. Entry set = opportunity ranking from gamelog usage. **A player can be
Featured without any current prop market** — usage is computed from game logs, not the props
feed. So the "no live prop" condition is **not** an exclusion reason for Featured; it only means
Player Check cannot attach a market to the Featured entry.

> Consequence for reason codes: the "not on the slate" idea is **surface-specific**. It excludes
> Floor/Menu (no supported market to evaluate) and blocks Green Light's primary-prop step, but it
> does **not** exclude Featured. §7 encodes this with distinct codes, not one shared
> `NOT_ON_SLATE`.

---

## 7. Reason-code catalog

Each code carries: machine code, surface(s), **class** (ELIGIBILITY = a real data/quality gate,
VIEW = a clearable filter state), grain (MARKET or PLAYER), plain-English template, and the
predicate/gate it derives from (§6). Per market+surface the result is `INCLUDED`,
`EXCLUDED(code)`, or `N/A`.

### 7.1 Inclusion
| Code | Surfaces | Meaning |
|---|---|---|
| `INCLUDED` | any | Market appears on the surface; carry rank, tier/lens count, line/price/book. |

### 7.2 Eligibility gates (true exclusions)
| Code | Surface(s) | Class · grain | Derives from | Template |
|---|---|---|---|---|
| `NO_SUPPORTED_MARKET` | Floor, Menu | ELIG · player | §6.1.1 | "No supported {Floor/Menu} market for {player} this week." |
| `NO_PRIMARY_PROP` | Green Light | ELIG · player | §6.3.2 | "{player} is featured but has no primary Rush/Rec Yds over to anchor the lenses." |
| `STAT_NOT_SUPPORTED` | Floor, Menu | ELIG · market | §6.1.1 | "{player}'s {market} isn't a stat we grade for floors yet." |
| `NO_VALID_LINE` | Floor, Menu | ELIG · market | §6.1.1 | "{player}'s {market} has no usable numeric line." |
| `NO_GAMELOG` | Floor, Menu, GL | ELIG · player | §6.1.2 | "Couldn't match {player} to game-log history." |
| `AMBIGUOUS_NAME` | all | ELIG · player | §8 | "{query} is ambiguous; choose a candidate." |
| `STAT_COLUMNS_MISSING` | Floor, Menu | ELIG · market | §6.1.2 | "We have {player}'s logs but not the columns for {market}." |
| `INSUFFICIENT_SAMPLE` | Floor, Menu | ELIG · market | §6.1.3 | "Fewer than {min_games} qualifying games for {market}." |
| `BELOW_HIT_THRESHOLD` | Floor, Menu | ELIG · market | §6.1.4 | "{player} clears {market} {line} only {hit}% — below the {min_hit}% floor." |
| `INVALID_PRICE` | Floor, Menu | ELIG · market | §6.2 | "{player}'s {market} price isn't a usable American line." |
| `NOT_FLOOR_OR_SWING` | Menu | ELIG · market | §6.2 | "{player}'s {market} clears {hit}% but meets neither the floor (≥80%, fair price) nor swing (+odds, ≥55%) rule." |
| `NOT_FEATURED_USAGE` | Green Light, Featured | ELIG · player | §6.3.1/§6.4 | "{player} isn't among this week's opportunity-featured players." |
| `NO_LENS_SUPPORT` | Green Light | ELIG · player | §6.3.3 | "No configured lens (and no TD angle) points to {player}." |
| `BELOW_DISPLAY_CUTOFF` | Floor, GL (All view) | ELIG · market | §6.1.5/§6.3.4 | "Qualifies but ranks below the {limit}-row display cut on the unfiltered view." |

### 7.3 View / filter state (clearable, not an exclusion)
| Code | Surface(s) | Class · grain | Template |
|---|---|---|---|
| `POSITION_FILTERED` | Green Light, Menu | VIEW · player | "{player} ({pos}) is hidden only by the current position filter; clear it." |
| `ROSTER_POSITION_UNKNOWN` | Menu | VIEW · player | "{player} has no roster-position match; he appears under 'Unknown', not {pos}." |
| `TIMEFRAME_EXCLUDED` | Menu | VIEW · market | "{player}'s game is outside the selected window ({timeframe})." |
| `SPORT_OR_SOURCE_EXCLUDED` | Menu | VIEW · market | "Excluded by the current Sport/Source filter, not by eligibility." |

> **Class drives the UI.** ELIGIBILITY explains a genuine absence; VIEW explains the player is
> eligible and only page controls hide him. The two must be visually distinct so "not shown"
> never reads as "not good."

---

## 8. Name resolution (must be explicit)

`_normalize_player_join_key` (lowercase alphanumeric only) is **not sufficient alone** —
it drops punctuation/spacing but not suffixes, and does nothing for initials or ambiguous
families. The resolver must normalize, in order:

1. **Suffixes:** strip `Jr.`, `Sr.`, `II`, `III`, `IV`, `V` (reuse `_normalize_nfl_roster_player_key`,
   which already does this before the join key).
2. **Punctuation & apostrophes:** `O'Hara`, `Smith-Njigba`, `T.J.` → normalized consistently.
3. **Spacing:** collapse repeated/trailing whitespace.
4. **Initials:** resolve `J.Hurts` → `Jalen Hurts` **only** when the initial+surname key maps to
   exactly one full name (the existing `_nfl_player_week_data` rule).

**Ambiguity returns selectable candidates — never a silent pick.** `B. Robinson` → offer *Bijan
Robinson* vs *Brian Robinson* with team/position, and the user chooses. Emits `AMBIGUOUS_NAME`
until resolved. This honors the existing anti-guess rule and prevents the wrong-player class of
error.

---

## 9. Tests (fixture-based, not live)

Implementation tests must use **controlled fixture data**, not the live board — current lines,
tiers, prices, and lens counts will change. The 2026-10-11 snapshot in §1 is a **timestamped
fixture for intuition only**, never a hard assertion.

Required fixture scenarios:
- A player with **multiple markets**, each hitting a **different** reason code (one
  `BELOW_HIT_THRESHOLD`, one `NOT_FLOOR_OR_SWING`, one `STAT_NOT_SUPPORTED`), proving market-
  level evaluation and the per-surface summary ("no current market qualifies for The Menu").
- A player **Featured via usage with no current prop** → Featured `INCLUDED`, Floor/Menu
  `NO_SUPPORTED_MARKET`, Green Light `NO_PRIMARY_PROP` — proving surface-specific gates (no
  single `NOT_ON_SLATE`).
- A player **on Green Light but below the Menu floor** → Green Light `INCLUDED`, Menu
  `BELOW_HIT_THRESHOLD`/`NOT_FLOOR_OR_SWING`.
- **Ambiguous name** (`B. Robinson`) → `AMBIGUOUS_NAME` with Bijan vs Brian candidates, no pick.
- A player **eligible but hidden by a filter** → `POSITION_FILTERED` / `TIMEFRAME_EXCLUDED`
  (VIEW), not an eligibility code.
- **Centralization test:** flip a threshold constant in the shared predicate and assert both the
  board output and Player Check output change together (the anti-drift guarantee of §5).

---

## 10. The Menu coverage claim (honesty correction)

The Menu subtitle currently reads *"Every option on the board"* while the pool is **candidate-
only** (floors ≥80% at a fair price, swings at +odds, §6.2). That overclaims. The narrowest
honest change, specified here and implemented with Player Check:

- Revise the copy to **"Every option admitted by the current Menu rules."**
- Show **coverage** on the Menu: games loaded, games represented, and games with **no
  qualifying Menu entry**.
- Player Check then explains the missing games and players (why a loaded game contributes no
  Menu leg — every candidate market failed a gate, with the codes).

*(This is a specified change for the Player Check workstream, not an implementation to be made
now. It is flagged as a standalone honesty item in case it should land sooner.)*

---

## 11. Placement & access (decided for v1)

- **NFL-only** (the only sport with the full usage + floor + convergence + props stack).
- **All-Access** surface.
- Search entry points from **The Menu** and **Green Light**.
- A **single Player Check result page**.
- **No new top-level navigation category** yet.

---

## 12. Honesty & governance constraints

- **Status/facts, never a verdict.** Player Check reports live markets and inclusion status with
  reasons. It must not rank players, score them, or imply +EV/-EV.
- **Two status systems stay separate** (product contract): inclusion status is distinct from the
  live fact statuses (Verified/Partial/Pending/Stale/Unavailable/Source-conflict) and from
  research status (Qualified/Baseline/Under Review/Failed/…). Player Check may cite a fact
  status as context but must not mint a new trust label.
- **VIEW vs ELIGIBILITY visually distinct** (§7).
- A missing input is named, never shown as neutral.

### Non-goals / do-not-build
No projection or prediction; no composite 1–100 score; no "should you bet"/lock verdict; no
cross-surface "best player" ranking; no auto-EV. Read-only.

---

## 13. Remaining open questions (narrow)
1. On `AMBIGUOUS_NAME`, confirm candidate-picker UX (list with team/pos) vs a disambiguation
   query param.
2. Should the Menu coverage correction (§10) land as its own small commit **before** Player
   Check, given it is a live overclaim?

*Awaiting review of v2. No implementation until approved.*
