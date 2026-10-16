# Player-Prop Capture — Specification (design only, no code)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no new surface.** This is "Gate 2" — the
capture prerequisite named in `docs/wave_watch_data_diagnostic_spec.md` (C7 staged capability, C8
execution gates). It defines the honest, graded **player-prop line record** that an NFL/NBA prop Wave
Watch (Over/Under streaks + active waves for individual props, the ATS-cover-streak analog) must be
built on. Building that surface is a **separate, separately-authorized gate** and is out of scope here.

Governing lesson (verified below): **you cannot establish a prop-line record from a game log.** A game
log tells you what a player *did*; it does not tell you the *line and price the market offered*. Grading
"did he beat X" is only honest when X — and the price on each side — were **captured at a point in
time, before the game**. Reconstructing a line from the log (e.g., using a player's average as the
"line") fabricates the market. Capture is therefore mandatory, and it must run daily, because the Odds
API serves only the **current** line — an uncaptured line is gone.

Date: 2026-10-16. Scope: **NFL + NBA** (per direction). MLB/WNBA are out of scope for this spec.

---

## 1. The canonical prop observation (the unit of the record)

Mirrors the Wave Watch and Decision-Journal canonical observations. One row = one **side of one market,
for one player, captured at one point in time**:

| Field | Required | Meaning |
|---|---|---|
| `player`, `team`, `opponent` | ✅ | subject + matchup |
| `game_key` | ✅ | a **stable event id** (not just a team string) + Eastern game date |
| `stat` / `market` | ✅ | Rec Yds, Pass Yds, Points, Rebounds, … |
| `line` | ✅ | the number **as the book offered it**, at capture time |
| `over_price`, `under_price` | ✅ (both) | American odds for **each** side — both, so ROI is real, not assumed |
| `book` + `book_count` | ✅ | the book, or a defined **consensus** across N books (book_count disclosed) |
| `line_type` | ✅ | **open / interim / closing** — labeled, not inferred silently |
| `capture_time` | ✅ | timestamp the line/prices were seen — **must precede commence** |
| `commence_time` | ✅ | game start (UTC→Eastern via `services/timeutils`) |
| `result` | settle | **OVER / UNDER / PUSH / PENDING**, graded against the **captured** line |
| `actual_value` | settle | the stat the player actually recorded |

**Push handling** is explicit: a whole-number line with `actual_value == line` is a PUSH (money back),
never a loss or a win. **Unknown stays unknown** — a side with no offered price is recorded without a
price, never back-filled with an assumed −110.

---

## 2. Current-state audit (what exists, verified 2026-10-16)

### NFL — a capture+grade pipeline ALREADY EXISTS and is wired into `run_daily.py`
- **Board snapshot** `data/props/NFL_Props.csv` already carries both sides and open/current/close:
  `OpenLine, CurrentLine, CloseLine, OpenOverOdds, OpenUnderOdds, OverOdds, UnderOdds, CloseOverOdds,
  CloseUnderOdds, BetLine, BetOverOdds, BetUnderOdds`. The raw material for a both-sided line history is
  present at the board level.
- **Daily line archive** `capture_nfl_prop_lines.py` → `data/tracking/NFL_PropLines_Archive.csv`
  (`SnapshotDate, Season, Player, Team, Stat, Line, OverOdds, UnderOdds, BookCount, Game, GameDate`).
  Wired into `run_daily.py` ("NFL prop-line capture"). Idempotent: one row per (SnapshotDate, Player,
  Stat). **Both over and under odds are captured.** `data/tracking/` is gitignored, so prod accumulates
  its own running record.
- **Grader** `grade_nfl_prop_lines.py` → `data/tracking/NFL_PropLines_Graded.csv` with the actual value
  + **OVER/UNDER/PUSH/PENDING** against the captured line. Also wired into `run_daily.py`.
- **This graded line archive is the honest basis for an NFL prop Over/Under wave.**

### NFL — what is NOT a line record (do not use it as one)
- `data/tracking/NFL_AllPropResults.csv` (34,788 rows) is the **model snapshot** archive, not a line
  history. Verified column population: `OpenLine / CloseLine / OpenPrice / ClosePrice` are **0%
  populated**; only `BetLine / BetPrice / Direction` are filled (one direction per row). So it **cannot**
  support open→close movement, CLV, or two-sided ROI. The existing "Riding the Wave" NFL prop-streak
  surface reads this file (directional streaks only); an honest **priced** Over/Under wave must read the
  two-sided graded archive (`NFL_PropLines_Graded.csv`) instead.

### NBA — the board has the columns, but there is NO capture and NO grader
- `data/props/NBA_Props.csv` has the same two-sided open/close schema as NFL.
- There is **no `capture_nba_prop_lines.py` and no `grade_nba_prop_lines.py`.** `NBA_AllPropResults.csv`
  is a model snapshot (retrospective, playoff-weighted), not a daily line history.
- **Consequence: there is no honest NBA prop line record today, so an NBA prop wave is not yet
  possible.** NBA season tips ~late Oct 2026; capture must be live before then to accrue.

---

## 3. Gaps to close (the capture work this spec authorizes later)

### NFL (upgrade the existing pipeline to meet the canonical observation)
1. **Explicit open & close, plus a near-commence snapshot.** The daily archive currently stores one
   *current* line per day; open→close is only implied by the daily series. Label the first in-window
   snapshot `open` and the last pre-commence snapshot `closing`, and add a **near-kickoff** capture so
   `closing` is genuinely close (the same reason `bk-linemove.timer` exists — once-daily gives a
   near-term game only 1–2 snapshots, per CLAUDE.md §7).
2. **Stable `game_key`.** Carry a real event id (from the schedule/Odds feed), not just
   `AwayFull@HomeFull`, so grading and dedup are robust to name variants.
3. **Consensus vs single book.** Record `book`/`book_count`; a single-book line is flagged (consistent
   with the graded-record guardrail that single-book is CONFLICTED).
4. **Feed both-side prices into the graded record** (`NFL_PropLines_Graded.csv` already can — confirm
   `over_price`/`under_price` persist through grading so ROI is computable).

### NBA (build the analog, mirroring NFL — nothing exotic)
1. `capture_nba_prop_lines.py` → `data/tracking/NBA_PropLines_Archive.csv` (same schema as NFL).
2. `grade_nba_prop_lines.py` → `data/tracking/NBA_PropLines_Graded.csv` (OVER/UNDER/PUSH/PENDING vs the
   captured line, from NBA box-score results).
3. **Wire both into `run_daily.py`** — the §7 rule: *if a feed is not in `run_daily.py`, it never runs
   on prod.* Must be live before tip-off to accrue a real history.

---

## 4. What an Over/Under prop wave needs from this record

The ATS-cover-streak analog for props is a **per (player, stat) chronological series** of graded
OVER / UNDER / PUSH outcomes **against the captured line**, each carrying its line and both prices:
- an **active wave** = consecutive OVERs (or UNDERs) in that series, shown with the lines so it reads as
  "cleared 6 straight receiving-yards lines," not a cherry-picked average;
- **ROI is honest only from the two-sided captured prices** — which the line archive has and
  `NFL_AllPropResults` does not; where a price is missing, ROI is "unavailable," never assumed −110
  (same rule as the Decision Journal).

This is exactly the record the user asked for: ATS-like Over/Under records and active waves for
individual player props — but earned from captured lines, not reconstructed from box scores.

---

## 5. Honesty rails (carried from doctrine + CLAUDE.md §10)

- **Streaks are priced.** 171k graded MLB+WNBA props show every predictive factor already in the
  number; a prop wave is a **descriptive** "who has been clearing their line," a starting point and the
  user's eye test, **not** a proven edge. No "sharp"/"steam"/"lock" language.
- **Descriptive, not causal.** Every surface built on this shows **sample size (n)**, discloses that a
  deeper streak is not evidence of continuation, and frames differences as what happened.
- **Prefer UNDER / single-book → CONFLICTED / LONGSHOT-OVER** guardrails apply to any prop surface, as
  they already do on the boards.
- **Availability states** (Verified/Partial/Pending/Stale/Unavailable) so a missing capture never reads
  as neutral.

---

## 6. Staged capability (what is showable, and when)

- **NFL, now (in season):** the two-sided graded archive is accruing via `run_daily`. Once the §3 NFL
  upgrades land and a monitored history exists, an NFL prop wave can be built on it (its own gate).
- **NBA, from tip-off:** nothing until §3-NBA capture is live and has accrued a monitored history —
  honestly "Pending / Data-Gated" until then. No NBA prop wave may claim a record it does not have.
- A surface may always show the **facts it does have** (today's two-sided lines) while the graded
  **history** is still Pending.

---

## 7. Execution gates

- **Gate 2a — Capture complete (per sport).** Met only when, for that sport: the daily archive runs
  green in `run_daily` for a defined run of consecutive in-season days; coverage reaches a defined % of
  the modeled markets with **both-side prices** and a **stable game_key**; `open`/`closing` line-types
  are labeled; and the grader resolves PENDING→OVER/UNDER/PUSH. **Verified with real on-disk
  observations, not synthetic fixtures.** NFL is close (pipeline exists); NBA starts from zero.
- **Gate 2b — Prop Wave Watch surface.** A **separate** authorization, not opened here. It reads the
  Gate-2a record and inherits the CFB Wave Watch honesty contract (descriptive, priced, sample sizes,
  no betting-authority language — the same wording bar enforced by `qc_cfb_wave_wording.py`).

---

## 8. Monitoring (defined here; built with the capture, not now)

A capture-health check (a `qc_*`/scorecard section) must report, per sport, with sample sizes:
- **coverage** — modeled markets captured today vs offered (and the one-sided-market count);
- **freshness** — newest snapshot age; a stale capture is flagged, never assumed live;
- **two-sided price presence** — % of rows with both `over_price` and `under_price`;
- **key integrity / dedup** — one row per (SnapshotDate, game_key, player, stat, line_type);
- **grading throughput** — PENDING→resolved rate, push count.
Capture is not "done" because a file exists; existence is not completeness (the same lesson the MLB
featured-results staleness check enforces).

---

## 9. Out of scope here
No code, no UI, no model tuning, no prop Wave Watch surface, and no sportsbook automation beyond the
Odds API fetch already in place. This document is the capture contract to review before the capture
work (and later, separately, the surface) is authorized. It does not touch the Decision Journal.
