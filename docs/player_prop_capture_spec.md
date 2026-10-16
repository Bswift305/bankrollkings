# Player-Prop Capture — Specification (design only, no code)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no new surface.** This is "Gate 2" — the
capture prerequisite named in `docs/wave_watch_data_diagnostic_spec.md` (C7/C8). It defines the honest,
graded **player-prop line record** an NFL/NBA prop Wave Watch (Over/Under streaks + active waves, the
ATS-cover-streak analog) must be built on. Building that surface is **Gate 2b**, separate and closed.

Governing lesson: **you cannot establish a prop-line record from a game log.** A game log says what a
player *did*, not the *line and prices the market offered*. Grading "did he beat X" is honest only when
X and the price on **each side** were captured, from a **specific book**, at a **specific instant**,
before the game. Reconstructing a line from the log fabricates the market. Capture must run on a
cadence because the Odds API serves only the **current** line — an uncaptured line is gone.

Date: 2026-10-16. Revision: 2 (ten mechanical corrections from implementation review — see §11).
Scope: **NFL + NBA**. MLB/WNBA out of scope.

---

## 1. The canonical prop observation (revised — a book-specific market snapshot)

**One row = one book's two-sided quote for one player's market, at one capture instant** (correction 1).
It is **not** one side, and **not** a blended/consensus number.

| Field | Required | Meaning |
|---|---|---|
| `event_id` | ✅ | **stable** provider event id (not a team string) + Eastern game date |
| `player_id` | ✅ | **stable** provider/roster player id (not a name) |
| `team`, `opponent` | ✅ | matchup |
| `stat_key` | ✅ | **normalized** market key (one canonical name per market across providers) |
| `book` | ✅ | the single sportsbook this quote is from |
| `line` | ✅ | that book's line |
| `over_price`, `under_price` | ✅ | **that same book's** two prices — never one book's Over paired with another's Under |
| `line_type` | ✅ | `source_open` (only if the source explicitly marks an opener) · `first_captured` · `last_prestart_captured` · `source_close` (only if the source supplies a true close). See §3 |
| `capture_time_utc` | ✅ | exact UTC instant the quote was seen |
| `commence_time_utc` | ✅ | game start; a capture at/after this is rejected (not stored as pre-game) |
| `minutes_to_commence` | ✅ | `last_prestart_captured` carries its distance from kickoff — a proxy, never relabeled "closing" |
| `result` | settle | `OVER / UNDER / PUSH / VOID / DNP / UNGRADED / PENDING` (§6) |
| `actual_value` | settle | the stat the player recorded — only when every component was **observed** (no zero-fill) |

**Per-book observations are the authority (correction 2).** A consensus/aggregate (e.g., modal line,
median price) is a **separately labeled DERIVED record**, stored apart, and **may never be presented as
an actually-available two-sided price, nor used as realized ROI.** Realized ROI uses a real book's real
two prices at a real instant, or it is unavailable.

**Snapshot identity (correction 4):** a row's key is
`(event_id, player_id, stat_key, book, line, capture_window)` — the exact market snapshot. Idempotency
is per-snapshot, **not** per calendar day.

**Stable identifiers are required (correction 5):** without a resolved `event_id` and `player_id` the
observation is still captured, but it grades as **`UNGRADED`** — never silently name-matched to a log.

---

## 2. Current-state audit (verified 2026-10-16) — the NFL archive is **Partial**

Classified **Partial**, not capture-complete and not "nearly canonical" (correction 7). It is preserved
and useful, but its lineage is **not** silently upgraded to the §1 standard.

### NFL board `data/props/NFL_Props.csv`
Carries two-sided open/current/close columns (`OpenLine/CurrentLine/CloseLine`,
`OpenOverOdds/OpenUnderOdds/OverOdds/UnderOdds/CloseOverOdds/CloseUnderOdds`). Raw material exists.

### NFL daily archive `capture_nfl_prop_lines.py` → `NFL_PropLines_Archive.csv` (run_daily-wired) — **Partial**
Verified against the code; gaps vs §1:
- **One row per (player, stat) per calendar day** — not a per-book, per-instant snapshot.
- **Line is the modal line** (`Line.mode()`, else median); **`OverOdds`/`UnderOdds` are the median Over
  and median Under computed *independently*** over whatever books offered the modal line — so the two
  sides **can come from different books** (cross-book price mixing). This is a derived number, not a
  real two-sided quote — it must not be used as realized ROI (correction 2).
- **`BookCount` counts every book in the (player,stat) group**, not the books offering the selected
  line.
- **No stable event or player id** (keys on `Player` name + `AwayFull@HomeFull`).
- **`line_type` is absent**: "first captured" is **not** necessarily the opener and "last captured
  before kickoff" is **not** the close (correction 3).

### NFL grader `grade_nfl_prop_lines.py` → `NFL_PropLines_Graded.csv` — **Partial**
- **Zero-fills missing components** (`val += v if notna else 0.0`) — a missing component stat manufactures
  a lower value and can manufacture a result (correction 6).
- Name-key matched (no stable `player_id`); a mismatch silently yields **PENDING** forever.
- Only `OVER/UNDER/PUSH/PENDING`; **no `DNP/VOID/UNGRADED`**, so "didn't play," "not yet played," and
  "couldn't match the player" are conflated.

### `NFL_AllPropResults.csv` is NOT a line history
34,788 rows; `OpenLine/CloseLine/OpenPrice/ClosePrice` **0% populated**; only `BetLine/BetPrice/
Direction` filled (one direction/row). Cannot support open→close, CLV, or two-sided ROI.

### NBA — no capture, no grader
`NBA_Props.csv` has the columns, but there is **no `capture_nba_prop_lines.py` and no grader**.
`NBA_AllPropResults.csv` is a retrospective model snapshot. **No honest NBA prop record exists.**

---

## 3. Line-type labeling (correction 3)
- **`source_open`** only when the provider explicitly supplies an opener.
- Otherwise the earliest capture is **`first_captured`** — honestly "the first we saw," not the open.
- The latest pre-commence capture is **`last_prestart_captured`**, stored **with `minutes_to_commence`**
  — never relabeled "closing."
- **`source_close`** only when the provider supplies a true closing line.

A surface may say "last line we saw, 14 min before kickoff," never "closing line," unless `source_close`.

---

## 4. Capture mechanics to build (NFL upgrade/migration; NBA new)

### NFL — upgrade to the §1 snapshot (migration, not a silent relabel)
Persist **per-book** rows (not a modal/median collapse), with resolved `event_id`/`player_id`, a
`stat_key` normalizer, `line_type`, `capture_time_utc`/`commence_time_utc`, and the exact snapshot key
(§1). Keep the existing `NFL_PropLines_Archive.csv` as the labeled **Partial** legacy source; the new
canonical capture is a distinct lineage. A consensus/derived view may be computed on top, clearly
labeled, never as realized ROI.

### NBA — new pipeline, mirroring the corrected NFL design
`capture_nba_prop_lines.py` + `grade_nba_prop_lines.py` writing the §1 canonical rows; **wired into
`run_daily.py`** (the §7 rule: not in run_daily ⇒ never runs on prod). Live before tip-off (~late Oct
2026) or it accrues nothing.

Both: **reject a capture whose `capture_time_utc` ≥ `commence_time_utc`** (not a pre-game observation).

---

## 5. Capture cadence — measure first, then freeze (correction 8)
Cadence is **not frozen in this spec.** First **measure the Odds API quota and per-call cost** actually
available, then freeze checkpoints against **kickoff proximity** (e.g., a daily baseline plus denser
captures approaching commence, mirroring why `bk-linemove.timer` exists — once-daily gives a near-term
game only 1–2 snapshots). Freeze freshness limits only after the quota measurement.

---

## 6. Result taxonomy (correction 6)
`OVER / UNDER / PUSH / VOID / DNP / UNGRADED / PENDING`:
- **PUSH** only when the player played and `actual_value == line` exactly (money back).
- **VOID** when the book voided the market.
- **DNP** when the player did not play (no log row for a player confirmed inactive/out).
- **UNGRADED** when identifiers couldn't be resolved — never a silent name-match, never PENDING-forever.
- **PENDING** only genuinely-not-yet-resolved.
- **Never** turn a missing source/component column into 0 unless **0 was explicitly observed.**

---

## 7. What an Over/Under prop wave needs
A per-(`player_id`, `stat_key`) chronological series of graded OVER/UNDER against the **captured per-book
line**, each row carrying its line, book and two prices, so an active wave reads "cleared 6 straight
receiving-yards lines" with the real numbers. **ROI only from real two-sided per-book prices**; where
absent, ROI is "unavailable," never assumed −110 and never from a consensus blend.

---

## 8. Honesty rails (doctrine + §10)
Streaks are priced (171k graded props) → a wave is descriptive, a starting point, **not** a proven
edge; no sharp/steam/lock language. Every built surface shows **sample size (n)**, discloses that depth
isn't continuation evidence, and is non-causal. Prefer-UNDER / single-book→CONFLICTED / LONGSHOT-OVER
guardrails apply. Availability states so a gap never reads as neutral.

---

## 9. Execution gates
- **Gate 2a — capture complete (per sport, opens separately for NFL and NBA).** NFL is an
  upgrade/migration from the Partial archive; NBA is a new pipeline. Gate 2a thresholds are **not frozen
  until measured** (correction 9): first measure, on real data, **supported markets offered, stable-ID
  (`event_id`/`player_id`) coverage, per-book row coverage, both-price coverage, and grading
  resolution**; then freeze the % bars and the consecutive-green-days requirement, **verified with real
  on-disk observations, not synthetic fixtures.**
- **Gate 2b — the visible Wave surface.** Closed. Separate authorization; inherits the CFB Wave Watch
  wording contract (`qc_cfb_wave_wording.py` bar).

---

## 10. Required tests (correction 10)
Before Gate 2a closes for a sport, automated QC must reproduce, on real-shaped data:
- **cross-book price mixing** — reject/label an Over and Under drawn from different books as a real
  two-sided quote;
- **late/post-kickoff capture** — a `capture_time_utc ≥ commence_time_utc` row is rejected;
- **duplicate snapshots** — the exact snapshot key (§1) dedupes; a different capture window does not;
- **player ambiguity** — unresolved `player_id` ⇒ `UNGRADED`, never a silent name-match;
- **DNP** — an inactive player ⇒ `DNP`, not PUSH/UNDER/PENDING;
- **missing components** — a missing component does **not** zero-fill into a manufactured result;
- **line-type labels** — `first_captured` vs `source_open`, `last_prestart_captured` (with
  `minutes_to_commence`) vs `source_close` are distinguished, never conflated.

---

## 11. Changelog — Rev 2 (ten corrections)
1. Canonical row = one **book-specific two-sided market snapshot** (event_id, player_id, team/opp,
   normalized stat_key, book, line, over+under price, exact capture + commence UTC) — not one side.
2. **Per-book observations are authority**; any consensus row is a separately labeled derived record,
   never an available two-sided price, never realized ROI.
3. `source_open` only on an explicit opener; else `first_captured`; `last_prestart_captured` with
   `minutes_to_commence`, not "closing"; `source_close` only on a true close.
4. Snapshot identity = (event, player, stat, book, line, capture window) — not `SnapshotDate`.
5. Stable `event_id`/`player_id` required; ambiguous match ⇒ `UNGRADED`, never silent name-match.
6. Result set adds `VOID/DNP/UNGRADED`; missing columns/components never become 0 unless 0 is observed.
7. The current NFL archive + grader are classified **Partial** (verified: modal line + independent
   median Over/Under across books, BookCount counts all group books, no stable ids, grader zero-fills
   components, no DNP/VOID/UNGRADED) — preserved, lineage not silently upgraded.
8. Cadence is **measure-first**: measure Odds API quota/cost, then freeze checkpoints vs kickoff
   proximity and freshness limits.
9. Gate 2a thresholds frozen **only after** measuring real coverage (markets, stable-ID, per-book,
   both-price, grading resolution).
10. Tests required for cross-book mixing, late capture, duplicate snapshots, player ambiguity, DNP,
    missing components, and source-vs-captured line labels.

## 12. Out of scope
No code, no UI, no model tuning, no Wave surface, no sportsbook automation beyond the existing Odds API
fetch. Does not touch the Decision Journal. This is the capture contract to review before any capture
work (and later, separately, the surface) is authorized.
