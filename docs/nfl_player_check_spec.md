# NFL Player Check — Specification (DRAFT, not implemented)

**Status: SPEC ONLY.** No code is to be written for Player Check until this document is
reviewed and approved. This is a design document, not an implementation.

**Surface (proposed):** an NFL player-search / explainability tool — the user types a player
name and the tool answers one question honestly:

> *Does this player appear on our NFL player-prop surfaces right now — and if not, exactly
> why?*

It is **decision-support and transparency**, not a recommendation. It never says a player is a
good or bad bet; it reports **status** and the **reason** for that status, drawn from the same
rules the boards already run. It fits the doctrine promise: *"We show the table. We show what
has earned trust. We show what has not. You decide."*

---

## 1. Why this exists — the real case

Searched live on 2026-10-11:

| Player | Green Light | Featured (usage) | Floor board | The Menu |
|---|---|---|---|---|
| **Bijan Robinson** (ATL · RB) | ✅ 3 lenses — Rush Yds O88.5 | ✅ | ❌ | ❌ |
| **Drake London** (ATL · WR) | ✅ 2 lenses + TD angle — Rec Yds O80.5 | ✅ | ❌ | ❌ |

Both are among the most-featured players in the league, yet neither is on the floor board or
buildable in The Menu. A user who sees Drake London on Green Light and then cannot find him in
The Menu has **no way to learn why** today. The answer is coherent — they are surfaced by
**opportunity / convergence**, but their clearance rate at the posted line is **below the
reliability (floor) threshold**, so the floor-first surfaces exclude them — but that reasoning
is invisible. Player Check makes it legible.

This is the whole point: the same player is legitimately **present on one surface and absent
from another**, because the surfaces ask different questions. Player Check must explain each
surface independently, in the surface's own terms.

---

## 2. Core principle — one set of rules, one set of reason codes

The hard requirement: **the explanation must be derived from the same inclusion rules the
boards use — never a parallel re-implementation that can drift.**

Concretely:

- There is **one** centralized reason-code catalog (an enum/constant set).
- There is **one** evaluator that walks the inclusion gates for a given player and emits those
  codes. The boards and Player Check both consume it (or, at minimum, the board builders and
  the evaluator share the identical gate predicates and the identical threshold constants, so
  a change to a gate changes both in lockstep).
- A reason code is only valid if it maps to an **actual gate in the pipeline**. No code may
  describe a rule the boards do not enforce; no gate may exclude a player without a code to
  name it.

**Acceptance criterion:** if a board's inclusion logic changes (a threshold, a new stat, a new
gate) and Player Check's output for an affected player does *not* change correspondingly, the
implementation is wrong. This is the test that proves centralization.

---

## 3. The inclusion pipeline, surface by surface (the rules the codes derive from)

All line/function references are `app.py` unless noted. These are the gates as they exist
today; the reason codes in §4 are keyed to them.

### 3.1 Shared foundation — the reliability pipeline
`build_nfl_floor_board(limit, min_hit, min_games)` (≈ line 29983). Per (player, stat):

1. Player must have a **live prop** in `data/props/NFL_Props.csv` this week. *(No row ⇒ the
   player is not evaluated at all.)*
2. The prop's `Stat` must map through `_NFL_PROP_STAT_MAP` (≈ 29966) to a supported stat.
3. `Line` must be numeric (`dropna(subset=['Line'])`).
4. The player must resolve to a gamelog in `_nfl_player_index()` (≈ 29843), keyed by
   lowercased full name off `_nfl_player_week_data()` (≈ 29763).
5. The stat's gamelog columns (`_NFL_FLOOR_STATS[stat]['cols']`) must exist for that player.
6. Window selection: `season` if ≥ `min_games`, else `l2y`, else `career`; the chosen window
   must still have ≥ `min_games` rows.
7. **Hit rate** `P(value ≥ line)` over that window must be ≥ `min_hit`.
8. Result is ranked by `(-hit, -clears)` and sliced to `limit`.

Threshold constants are **surface-specific** and must be read from one place:
- Floor page `/tools/nfl-floor` → defaults `limit=24, min_hit=78, min_games=8`.
- `_card_pools` (The Menu + Daily Card) → `limit=90, min_hit=52` for the raw board, then
  re-tiers (see §3.3).
- (These differing params are exactly what the floor-board cache-determinism fix made safe —
  each param set is cached independently. Player Check must likewise evaluate against the
  **surface's own** thresholds, not one global number.)

### 3.2 Green Light — the convergence pipeline
`build_green_light(limit, pos)` (≈ 30872). This is a **different entry set** from the floor
board — it starts from the **usage/opportunity board**, not reliability:

1. Player must be in `build_nfl_usage_board()` featured players (opportunity: carry share /
   target & air-yards share). *(Defenses excluded.)*
2. Player must have the **primary over** prop — `Rush Yds` for backs, `Rec Yds` for others.
3. `convergence ≥ 1` configured lens **or** a TD angle (else dropped).
4. Position filter (`pos`) is a **display** filter applied before the limit; a selected
   position exposes the complete matching set.

### 3.3 The Menu — buildable board
`build_menu_board(legs, timeframe, sport, tier, pos)` (≈ 31314), fed by `_card_pools` (≈ 31263):

- From the raw floor board (min_hit=52): a leg is tagged **floor** only if `hit ≥ 80` and
  `-185 ≤ price ≤ 115`; tagged **swing** only if `price ≥ 120` and `hit ≥ 55`. A player who
  clears but sits between these bands qualifies for neither and does not enter the Menu pool.
- Price must be a valid American number (`|odds| ≥ 100`).
- Then filtered by timeframe window, sport, tier, and position; deduped by
  `(sport, label, game)`.

### 3.4 Featured Players
`/tools/nfl-featured` → `build_nfl_usage_board()` — opportunity ranking; same entry gate as
Green Light step 1.

---

## 4. Reason-code catalog (the enum)

Every code carries: **machine code**, **surface(s)**, **class** (ELIGIBILITY = a real data/
quality gate, or VIEW = a current filter state the user can clear), **plain-English
template**, and the **gate it derives from** (§3 step). Player Check reports, per surface,
either `INCLUDED` (with rank/context) or `EXCLUDED` + one primary code (plus optional
secondary codes).

### 4.1 Inclusion
| Code | Surfaces | Meaning |
|---|---|---|
| `INCLUDED` | any | Appears on the surface; carry rank, tier/lens count, and the prop line. |

### 4.2 Eligibility gates (true exclusions — the player genuinely does not qualify)
| Code | Surface(s) | Derives from | Template |
|---|---|---|---|
| `NOT_ON_SLATE` | all | §3.1.1 | "{player} has no live NFL prop this week, so nothing can evaluate him." |
| `STAT_NOT_SUPPORTED` | all | §3.1.2 | "{player}'s posted prop ({stat}) isn't a stat we grade for floors yet." |
| `NO_VALID_LINE` | all | §3.1.3 | "{player}'s {stat} prop has no usable numeric line right now." |
| `NO_GAMELOG` | all | §3.1.4 | "We couldn't match {player} to game-log history (name/roster join)." |
| `AMBIGUOUS_NAME` | all | §3.1.4 + `_nfl_name_key` | "{query} is ambiguous (e.g. B.Robinson → Bijan vs Brian); we won't guess." |
| `STAT_COLUMNS_MISSING` | all | §3.1.5 | "We have {player}'s logs but not the columns needed for {stat}." |
| `INSUFFICIENT_SAMPLE` | all | §3.1.6 | "{player} has fewer than {min_games} qualifying games in season/L2Y/career." |
| `BELOW_HIT_THRESHOLD` | floor, Menu | §3.1.7 / §3.3 | "{player} clears {stat} {line} only {hit}% of the time — below this surface's {min_hit}% floor." |
| `INVALID_PRICE` | floor, Menu | §3.3 | "{player}'s {stat} price isn't a usable American line (|odds| ≥ 100)." |
| `NOT_FLOOR_OR_SWING` | Menu | §3.3 | "{player} clears {hit}% but doesn't meet the floor (≥80%, fair price) or swing (+odds, ≥55%) rule." |
| `NOT_FEATURED_USAGE` | Green Light, Featured | §3.2.1 | "{player} isn't among this week's opportunity-featured players." |
| `NO_PRIMARY_PROP` | Green Light | §3.2.2 | "{player} is featured but has no primary Rush/Rec Yds over to anchor the lenses." |
| `NO_LENS_SUPPORT` | Green Light | §3.2.3 | "No configured lens (and no TD angle) points to {player} this week." |
| `BELOW_DISPLAY_CUTOFF` | floor, Green Light (All only) | §3.1.8 / §3.2.4 | "{player} qualifies but ranks below the {limit}-row display cut on the unfiltered view." |

### 4.3 View / filter state (not an exclusion — clearable on the page)
| Code | Surface(s) | Derives from | Template |
|---|---|---|---|
| `POSITION_FILTERED` | Green Light, Menu | position filter | "{player} ({pos}) is hidden only by the current position filter; clear it to see him." |
| `ROSTER_POSITION_UNKNOWN` | Menu | roster join | "{player} has no current roster-position match, so he appears under 'Unknown', not {pos}." |
| `TIMEFRAME_EXCLUDED` | Menu | timeframe window | "{player}'s game is outside the selected window ({timeframe})." |
| `SPORT_OR_SOURCE_EXCLUDED` | Menu | sport/source filter | "{player} is excluded by the current Sport/Source filter, not by eligibility." |

> **Class matters for honesty.** ELIGIBILITY codes explain a genuine absence. VIEW codes
> explain that the player *is* eligible and only the current page controls hide him — Player
> Check must visibly distinguish the two, so "not shown" is never mistaken for "not good."

---

## 5. Proposed architecture (for the review — not a build order)

- A single module (working name `services/nfl_player_check.py`) owns:
  1. the reason-code enum (§4), and
  2. `evaluate_nfl_player(name) -> PlayerCheckResult`, which normalizes the name, resolves the
     gamelog/roster, and walks the §3 gates **per surface**, returning for each surface either
     `INCLUDED(context)` or `EXCLUDED(primary_code, secondary_codes, context)`.
- **Centralization is the deliverable, not a bonus.** Either the existing board builders are
  refactored to call shared gate predicates from this module, or the module imports the exact
  threshold constants and predicate functions the builders use. A parallel re-derivation of
  "when does a player appear" is explicitly **out of bounds** — it is the drift this feature is
  meant to prevent.
- Name resolution reuses `_nfl_name_key` / `_nfl_player_index` and must honor the existing
  anti-guess rule (`_nfl_player_week_data` deliberately leaves ambiguous initials like
  `B.Robinson` unresolved) → surfaced as `AMBIGUOUS_NAME`, offering the candidate full names
  rather than picking one.
- Read-only. No caching concerns beyond reusing the builders' own caches.

---

## 6. Worked test cases (must pass once implemented)

### 6.1 Bijan Robinson (ATL · RB) — present on opportunity, absent from reliability
Expected `evaluate_nfl_player("Bijan Robinson")`:
- **Green Light:** `INCLUDED` — RB tier, 3 lenses (Opportunity, Game Identity, Coaching), Rush
  Yds O88.5 (-113).
- **Featured:** `INCLUDED` (opportunity).
- **Floor board:** `EXCLUDED` → `BELOW_HIT_THRESHOLD` (clears Rush Yds 88.5 below the 78%
  floor-page threshold).
- **The Menu:** `EXCLUDED` → `BELOW_HIT_THRESHOLD` / `NOT_FLOOR_OR_SWING` (does not meet the
  ≥80% floor or the +odds swing rule).
- User-facing summary: *"Bijan Robinson is featured by opportunity and appears on Green Light
  (3 lenses). He's not on the floor board or The Menu because his Rush Yds clearance at the
  current line is below the reliability threshold — opportunity, not proven floor."*

### 6.2 Drake London (ATL · WR) — same shape, different surface path
- **Green Light:** `INCLUDED` — WR tier, 2 lenses (Opportunity, Matchup) + TD angle, Rec Yds
  O80.5 (-113).
- **Featured:** `INCLUDED`.
- **Floor board / Menu:** `EXCLUDED` → `BELOW_HIT_THRESHOLD`.
- Confirms the explainer handles a WR via the receiving path and reports the **same** reliability
  reason through a **different** convergence path.

### 6.3 Required negative / edge cases
- A player with **no live prop** → `NOT_ON_SLATE` on every surface (proves the top gate).
- A **defender** whose only prop is tackles/sacks on a surface that doesn't grade it →
  `STAT_NOT_SUPPORTED` where applicable.
- An **ambiguous initial** search (`B. Robinson`) → `AMBIGUOUS_NAME` listing Bijan vs Brian,
  no silent pick.
- A player eligible but hidden by a filter → `POSITION_FILTERED` / `TIMEFRAME_EXCLUDED`
  (VIEW class), **not** an eligibility code.

---

## 7. Honesty & governance constraints

- **Status, never a verdict.** Player Check reports presence/absence and the reason. It must
  not rank players, score them, imply a present player is +EV, or an absent one is -EV.
- **Two status systems stay separate** (per the product contract): Player Check reports
  *inclusion status*, which is distinct from the live *fact statuses*
  (Verified/Partial/Pending/Stale/Unavailable) and from *research status*
  (Qualified/Baseline/Under Review/Failed/…). It may cite a fact status as context but must
  not invent a new trust label.
- **VIEW vs ELIGIBILITY must be visually distinct**, so "hidden by my filter" never reads as
  "doesn't qualify."
- Mirrors the existing availability doctrine: a missing input is named, never shown as neutral.

### Non-goals / do-not-build
No projection or prediction; no composite 1–100 score; no "should you bet"/lock verdict; no
cross-surface "best player" ranking; no auto-EV. Read-only.

---

## 8. Open questions for review
1. **Scope:** NFL-only v1 (the only sport with the full usage + floor + convergence stack)?
   CFB/MLB later as their pipelines mature?
2. **Shared predicates vs call-the-builders:** refactor the builders to expose gate predicates,
   or have the evaluator import constants + re-express gates against the same inputs? (Both
   satisfy "same rules"; the refactor is cleaner but larger.)
3. **Surface set:** Floor board, Green Light, The Menu, Featured — correct starting set? Add
   the live props board?
4. **Name UX:** on `AMBIGUOUS_NAME`, present candidates for the user to pick; confirm that's the
   desired behavior vs a best-effort match.
5. **Placement:** where does Player Check live in nav, and is it free or All-Access?

*Awaiting review. No implementation until approved.*
