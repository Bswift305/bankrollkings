# NFL Active ATS Wave — Source Characterization

> **Update — IMPLEMENTED (2026-10-16).** The source swap recommended below was approved and shipped as a
> separate reversible NFL-only commit: `build_nfl_ats_wave` / `_nfl_ats_decisions_from_games` /
> `_nfl_ats_sync` read `nflverse_games.parquet` with an explicit active-season gate, `game_id` identity,
> the recorded-spread sign (verified by fixtures), event-level completeness, duplicate/conflict and
> stale-source fail-closed, and a 48h freshness budget; SU and O/U are failed closed. Tests:
> `qc_nfl_ats_wave.py`. **Before:** the board showed 2025 season-final streaks as active (NO 6, MIN 5,
> SEA 5, CLE 3, DEN 3). **After (real local data):** fail-closed (15 overdue + source 174h stale),
> 0 ATS/0 SU/0 OU. **Open operator task stands:** wire + verify a production refresh for
> `nflverse_games.parquet` (none exists today) — until then the board correctly fails closed.

**Status of this document: the read-only characterization that gated the implementation.** Gate before implementing the frozen
Active ATS Wave rule (`docs/ats_wave_contract.md`) on the NFL surface. Date: 2026-10-16. Companion to
the CFB implementation (commit `db650a8`). The directive was explicit: **do not implement by copying CFB
assumptions** — establish the eight points below first, then build NFL as its own reversible commit using
the same *product rule*, not necessarily the same *storage mechanics*.

Scope: the NFL team **ATS** streaks on "Riding the Wave" (`build_nfl_wave_context` → `/tools/riding-the-wave`,
also `build_nfl_wave_watch_context`/`nfl_wave.html`). The player prop-streak sub-board is a separate,
already-freshness-gated surface and is out of scope here.

---

## The eight establishments

### 1. Authoritative closing-line / result source
- **Current (live board):** `load_nfl_game_lines_history()` → `data/historical/NFL_GameLines_History.csv`.
  A **build-once merged archive** (`Source` column: sbr 2946 + nfldata 1139 rows), **2011→2025**. ATS is
  **derived live** from `HomeScore`/`AwayScore`/`HomeSpread`, not stored as a graded Hit/Miss/Push state.
  Gitignored. **No in-season refresh job writes it** (only calibration/stats/research *read* it).
- **Fallback path** (only if the primary CSV is absent): stacks the SBR JSON + `NFL_Games_nfldata.csv`
  with **no dedup** (see §7). Prod does not hit this path — the primary file is present → early return.
- **Recommended authoritative current-season source:** `data/historical/nflverse_games.parquet`
  (1999→**2026**: 272 scheduled 2026 rows, **65 completed**, weeks 1–18), carrying `game_id`,
  `spread_line`, `gameday`, `gametime`, `result`, teams and scores. Already on disk and read by other
  builders. **One file serves both the schedule manifest and the graded results** (contrast CFB, which
  needed `NCAAF_GameLineResults.csv` + `cfb_line_moves.json`).

### 2. Stable game identity
- **NFL has a real stable identifier: `game_id`** (nflverse, e.g. `2026_06_KC_BUF`), present in BOTH the
  history CSV and the parquet. **This is the key divergence from CFB**, which had no event ID and forced a
  synthesized `(team, opponent, GameDate)` identity. For NFL: **canonical game = `game_id`;
  team-game = `(game_id, team)`**. No matchup/date synthesis, and the CFB "two opponents under one week
  label" collapse **cannot occur** (NFL plays one game per team per week).

### 3. Team-side grading grain
- Per **team-game**, sign ∈ {**+1 cover / −1 non-cover / 0 push**}: `home = sign(margin + HomeSpread)`,
  `away = −home`. Already implemented in `build_nfl_wave_context`. Grain is correct and matches the
  contract; it needs no change.

### 4. Season / week / kickoff chronology
- `Season` (year), `Week` (numeric), date. The **history CSV carries day-level `Date` only**; the parquet
  adds **`gameday` + `gametime`** (true kickoff). NFL has one game per team per week, so day-level order is
  usually enough — but **Thu/Sun/Mon ordering within a week is real** and only `gametime` resolves it. Order
  by `(gameday, gametime)`.

### 5. Push / cancellation / no-line handling
- **Push** (`margin + spread == 0`) → sign 0; `_wave_trailing_run` treats a trailing push as streak 0 and
  an interior push as a break (`W,W,P,W → 1`) — **exactly the frozen rule**. No change needed.
- **No line** (`HomeSpread` NaN) → the ATS row is skipped (ignored; does not interrupt) — matches "no
  closing line is ignored."
- **Unplayed / cancelled** (no scores / no `result`) → skipped. Consistent with the contract.

### 6. Completed-game manifest
- **Current: NONE.** There is no forward manifest; the only "freshness" signal is season-level
  (`latest_season` = max season in the data). This is **weaker than CFB's completeness check** and is the
  root of the defect in §8.
- **Recommended:** derive the manifest from `nflverse_games.parquet` — scheduled 2026 games are the
  expected set; `result`-not-null are the graded/completed set; **`completed_week` = the max week whose
  every scheduled game has a result**. This is the NFL analog of `cfb_line_moves.json`, in the same file as
  the results.

### 7. Duplicate / conflict behavior
- **In reality: 0 duplicate game rows, 0 conflicting duplicates** in `NFL_GameLines_History.csv` (the
  sbr+nfldata merge was done once at build time). The parquet is one row per `game_id` (no dup).
- **Latent risk only on the fallback stacking path** (§1), which has no dedup and which prod does not use.
- With a real `game_id`, dedup/conflict detection becomes **exact**: group by `game_id`; an exact repeat
  collapses, a `game_id` with a conflicting score/spread is a conflict → fail closed. No `(team,opp,date)`
  heuristic needed.

### 8. Production freshness — **the headline**
- Both source files are **gitignored** → refreshed on prod independently of deploys; **true prod freshness
  is unknown from the dev box and must be verified prod-side.**
- **Locally, the ATS source is stale by construction:** `NFL_GameLines_History.csv` has **zero 2026 games**
  (max date Feb 8 2026 = the 2025-season Super Bowl), and no job refreshes it in-season. The fresher
  `nflverse_games.parquet` (2026 through ~week 6–7) is **not wired into the ATS wave**.
- **Concrete current defect (reproduced locally):** `build_nfl_wave_context` presents **2025 season-final
  ATS streaks as active** — New Orleans 6, Minnesota 5, Seattle 5, Cleveland 3, Denver 3, all
  `last_season 2025` — under an "as of Feb 8 2026" stamp, because the only gate is "the streak ran into the
  latest season present" and the data ends in 2025. The player **prop**-streak sub-board already fails
  closed ("As of 2025 Week 18 · current season results pending"); the team **ATS/SU/OU** boards do not.
  This is precisely the stale-run class the frozen rule and the heat-map/prop-streak freshness work exist
  to prevent.

---

## Why NFL must not copy CFB mechanics
1. **Identity:** NFL has a stable `game_id`; CFB had none. NFL skips the `(team, opponent, date)` synthesis
   and the same-week-two-opponents collapse entirely.
2. **One source, not two:** `nflverse_games.parquet` is both the schedule manifest and the graded record;
   CFB needed a separate line-moves manifest to cross-validate. NFL's lineage check becomes "does the
   source contain the requested season through the claimed completed week," not a two-file season match.
3. **Chronology:** NFL needs `gametime` (Thu/Sun/Mon within a week), which the day-level history CSV lacks.
4. **The real fix is a source swap + a completed-week freshness gate**, not a dedup/identity rewrite — the
   current ATS source is a 2025-terminal archive, so the primary problem is that it has no current-season
   games and no completed-week gate.

## Recommended NFL mechanics (for approval — NOT yet built)
- Read current-season (2026) ATS decisions from `nflverse_games.parquet`: `result`-not-null + `spread_line`
  present, team-game grain keyed by `game_id`, ordered by `(gameday, gametime)`.
- Derive `completed_week`; build the expected manifest from the same file; **synchronized only when every
  expected decision through `completed_week` is graded** (conflicts fail closed). Otherwise show the honest
  unavailable state — **never** fall back to a prior season's final streaks (the current behavior).
- Reuse `_wave_trailing_run` (already correct) and the model-overlay firewall.
- Ship as a **separate, reversible, NFL-only commit** with `qc_nfl_ats_wave_*` fixtures mirroring the CFB
  suite (truth table, push-interrupt, no-line/unplayed ignored, stale-season fail-closed, completeness).

## Open decision for the director
Confirm the **source swap onto `nflverse_games.parquet`** (recommended: it already has 2026, a stable
`game_id`, and an independent refresh) versus wiring current-season game-lines into
`NFL_GameLines_History.csv`. And confirm the **production freshness report** is required prod-side before
the NFL ATS wave is declared operational, same as CFB.
