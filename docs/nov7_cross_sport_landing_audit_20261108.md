# November 7 Cross-Sport Landing Audit — INTERIM (read-only, 2026-11-08 ~09:00 UTC)

Scope: data lineage and grading only. No outcome is used to claim any pregame signal predicted anything.
Evidence: signed-in production pages + two read-only SSM file inventories (no provider calls, no writes).

## Structural fact that bounds this audit
Every Nov 7 production artifact was written by the 2026-11-07 13:00–13:27 UTC `bk-daily` run — **before**
Saturday's CFB slate and the evening NBA slate began. No Nov 7 *Saturday* finals can exist yet on prod. They are
first eligible to land in today's 13:00 UTC `bk-daily`. Columns "Final received / Correctly graded" below are
therefore NOT YET DUE for Saturday events; they are completed after today's run.

## Sports with governed events on Nov 7
| Sport | Events | Source |
|---|---|---|
| NFL | **NO EVENTS** (Saturday) | `NFL_Schedule.csv`; last final = Thu Wk 9 JAX@BAL |
| NCAAF | Yes — 152 odds rows dated 11-07; Slate Pulse 66 games | `NCAAF_Odds.csv` (11-07 08:00 ET) |
| NBA | Yes — 7 games | `NBA_Schedule.csv` (7 rows), `NBA_Odds.csv` (21 rows) |
| NCAAB | **NO GOVERNED EVENTS** — 0 NCAAB files on prod | inventory |
| NHL | **NOT SUPPORTED** — 0 NHL files on prod | inventory |
| MLB / WNBA | Off-season | Slate Pulse 255h / 183h stale |

## NBA
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Games / ML / spread / total | 7 (GameIDs e.g. `e76682ca…` DEN@IND 17:10) | 21 rows = 7 × {BetMGM, DraftKings, FanDuel}, 08:05 ET | **0 — no NBA finals artifact exists** (`data/scores/` holds only CFB/NFL) | 0 | **All 7** |
| Props | — | `NBA_Props.csv` 855 rows (`EventCommenceAtUTC` ≤ 11-08T03:00) | `NBA_GameLogs.csv` **last written 2026-06-05, max date Oct 31, 2025** | `NBA_AllPropResults.csv` SnapshotDate 11-07 but **GameDay/ResultDate all null** | **All** |

Pipeline: pregame capture works. **No 2026-27 NBA result has ever landed** — the gamelog producer has not written
since June; the daily NBA step was FAIL in the pre-deploy baseline. Downstream: NBA Streak Patterns shows 0
game-log rows; Command Center blank "Results through". Under the NBA season-readiness gate this is a P0 data gap.

## NCAAF
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Sat Nov 7 games | 152 odds rows dated 11-07 (3 books) | yes, 11-07 08:00 ET | not yet due (lands ≥ 11-08 13:00 UTC) | not yet due | — |
| Fri Nov 6 (ET) games | — | — | **5 finals stored with Date = 2026-11-07** | — | **date anchoring** (below) |
| Grading rows | `NCAAF_GameLineResults_Scored.csv` holds Week-10 11-07 rows (e.g. Oregon@Ohio State `401858514`, Georgia@Ole Miss `401856741`) as `Game Line Backfill` rows dated `2026-11-07 05:00+00:00` | | | pending | verify they are pending, not graded |

Discrepancies:
1. **Finals dated in UTC, not Eastern (CLAUDE.md §5).** `CFB_Finals.csv` rows written 2026-11-07 13:04 UTC — before
   any Saturday kickoff — carry `Date=2026-11-07`: TCU@Arizona `401856855` 28–29, USF@ECU `401862818` 17–20,
   Nebraska@Illinois `401858510` 13–24, New Mexico@Nevada `401864533` 31–3, Virginia Tech@SMU `401858288` 28–51.
   These are Friday-night (Nov 6 ET) games. Same pattern in `NFL_Finals.csv` (Thu 11-05 ET JAX@BAL dated 11-06;
   Mon 11-02 ET CHI@SEA dated 11-03). Any Eastern-dated join (schedule, line history, results pages) can land
   them on the wrong day. Producer to confirm: the finals writer (`refresh_live_scores` / scores step).
2. **CFBD results frozen since 2026-10-24.** `cfbd_quota_state.json`: `exhausted:true`, `reason: HTTP 429 (monthly
   quota) at step 'CFB current-season results'`, **`reset_at: null`** — so the latch did not clear at the November
   monthly reset and will not clear on its own. Downstream: Wave "graded through Wk 7", Streaks "through Wk 8",
   Top Board "Week 8" while the season is in Week 10. Clearing it is an owner decision (override listed in the file);
   nothing changed.
3. **Completed games remain on live surfaces.** Slate Pulse counts 66 NCAAF games as "with live markets today".

## NFL
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Nov 7 | NO EVENTS | — | — | — | — |
| Last game (Thu Wk 9 JAX@BAL `401873037`) | yes | yes | 33–10 Final, landed 11-07 13:04 | props: "Week 9 · 132 props" graded | date stored as 11-06 (UTC) |
| Player stats | — | — | `NFL_GameLogs.csv` max 2026-10-30 (Wk 8) | — | expected: nflverse publishes after the week |

Also stale: `NFL_GameWeather.csv` last written 2026-10-16 (max date 10-25) → "No forecast available" on every
current Matchup Center card. Matchup Center injury module reads "Unavailable" despite `NFL_Injuries.csv` 11-08 07:00.

## Trend-input landing (yesterday → today)
| Input | NFL | NCAAF | NBA |
|---|---|---|---|
| ATS/SU/totals | through Wk 9 (Riding the Wave) | **frozen Wk 7–8** (CFBD latch) | none for 2026-27 |
| Recent form / player history | gamelog through Wk 8 (expected) | frozen | **none since Oct 2025** |
| Streaks | heat map through Wk 8 | frozen | 0 rows |
| Matchup evidence | weather stale, injuries not joined, line-move join null | stale | — |
| Green Light lens inputs | NFL only; through Wk 8 | n/a | n/a |

## Remaining (after today's 13:00 UTC `bk-daily`)
Re-run the inventory; reconcile each Saturday NCAAF and NBA event: final received, ML/spread/total graded at the
exact captured book/line, push handling, props grading, removal from live surfaces, and the producer outcome.
