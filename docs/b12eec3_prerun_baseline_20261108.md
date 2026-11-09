# `b12eec3` — pre-`bk-daily` production baseline (read-only, 2026-11-08 12:33 UTC)

This is the before-picture for the 13:00 UTC `bk-daily` receipt.
- **Capture method:** one read-only SSM `AWS-RunShellScript` run against `i-08d2fd818875381dd` from CloudShell.
  Output was saved to `base.out` in the CloudShell home directory.
- **Nothing was written in production.** The script wrote only a temporary script under `/tmp`, removed afterwards.
- **No provider calls, no credentials printed.** The NBA gate is the only env value read.
- **Hashes:** each `sha` is the first 16 hex characters of the SHA-256 of the file bytes.
- **Times:** `mtime` is UTC.

## Code and service
| Item | Value |
|---|---|
| Prod HEAD | `b12eec342a2637596ab4f01b6f3051f2fe21aed2` |
| `origin/master` (on box) | `b12eec342a2637596ab4f01b6f3051f2fe21aed2` (equal) |
| Tracked tree | **clean** (no porcelain output) |
| `bankrollkings` | active/running, `NRestarts=0`, `ActiveEnterTimestamp` Sat 2026-11-07 14:51:36 UTC (the deploy restart) |
| `/healthz` | **200** |
| Research Candidate | 0 `RESEARCH_CANDIDATE` lines in `.env`; 0 in both gunicorn process environments → **OFF** |
| `BK_NBA_STATS_ENABLED` | **absent**: 0 lines in `.env`, not in the process env (the gate defaults OFF) |
| Active `bk-*` units | Timers only, all `active waiting`. **No `bk-*` service was active or activating** at capture |
| Next `bk-daily.timer` | **Sun 2026-11-08 13:00:00 UTC** (26 min after capture); last Sat 2026-11-07 13:00:00 UTC |

`bk-backup.timer` is described as "daily (12:30 UTC, before t…)". It is not running at capture. Its writes are
backup copies, not data artifacts, so it does not affect the comparison below.

## Artifacts before the run
| File (all resolve under `/opt/bankrollkings/…`, no symlinks) | sha (16) | mtime UTC | rows | events | newest timestamps |
|---|---|---|---|---|---|
| `data/props/NFL_Props.csv` | `9b834b72c8344653` | 2026-11-07 13:00:53 | 2,519 | 14 (EventId) | SourceUpdatedAtUTC max 2026-11-07T13:00:51Z (0 null); EventCommenceAtUTC max 2026-11-10T01:15Z |
| `data/odds/NFL_Odds.csv` (game lines) | `97732b973a09b0f7` | 2026-11-07 13:00:15 | 68 | 27 (GameID) | LastUpdated max "2026-11-07 08:00" (zone-less); Date max 2026-11-16 |
| `data/odds/NFL_FirstHalf.csv` | `04a80327a125db6d` | 2026-11-07 13:00:34 | 14 | 14 | LastUpdated max 2026-11-07T13:00:25Z |
| `data/tracking/NFL_LineMovementHistory.csv` | `e9989f421aa20353` | 2026-11-07 13:00:16 | 20,367 | 272 | SnapshotAt max 2026-11-07T13:00:15+00:00 |
| `data/tracking/NFL_LineMovementCurrent.csv` | `ab5f222351942004` | 2026-11-07 13:00:17 | 591 | 272 | LastUpdated max "2026-11-07 08:00"; Date max 2027-01-10 (includes rows dated from 2026-09-09) |
| `data/odds/NBA_Odds.csv` (game lines) | `5f6a9a75eb01a879` | 2026-11-07 13:06:10 | 21 | 7 (GameID) | LastUpdated max "2026-11-07 08:05"; Date max 2026-11-07 |
| `data/props/NBA_Props.csv` | `e406fa53448d683a` | 2026-11-07 13:06:13 | 855 | 7 (EventId) | SourceUpdatedAtUTC max 2026-11-07T13:05:56Z (0 null); EventCommenceAtUTC max 2026-11-08T03:00Z |
| `data/gamelogs/NBA_GameLogs.csv` | `77843066a9a74016` | **2026-06-05** 19:27:42 | 25,923 | n/a | Date max "Oct 31, 2025": no 2026-27 results (O-4) |
| `data/tracking/NBA_AllPropResults.csv` | `151c5bf162236861` | 2026-11-07 13:13:10 | 15,942 | n/a | — |
| NBA finals file | — | — | — | — | **none exists** (`data/scores/` holds only CFB and NFL finals) |
| `data/odds/NCAAF_Odds.csv` | `d1387f632b0af9b7` | 2026-11-07 13:00:18 | 173 | 66 (GameID) | LastUpdated max "2026-11-07 08:00"; Date max 2026-11-14 |
| `data/odds/NCAAF_FirstHalf.csv` | `f5134b3aa6e3e28a` | 2026-11-07 13:00:48 | 51 | 51 | LastUpdated max 2026-11-07T13:00:34Z |
| `data/scores/CFB_Finals.csv` | `ac69bbc03675f8dd` | 2026-11-07 13:04:05 | 303 | 303 | Date max 2026-11-07 |
| `data/tracking/NCAAF_GameLineResults_Scored.csv` | `4f3dd34e08ca3816` | 2026-11-07 13:12:46 | 31,336 | 7,858 | GameDate max 2026-12-12 (includes scheduled games) |
| `data/scores/NFL_Finals.csv` | `f7d54558b69d7b56` | 2026-11-07 13:04:03 | 74 | 74 | Date max 2026-11-06 |
| `data/tracking/NFL_AllPropResults.csv` | `1db0c43865953105` | 2026-11-07 13:09:23 | 33,973 | n/a | — |
| `data/tracking/Run_Status.json` | `9e16a0c410b0965a` | 2026-11-07 13:29:12 | — | — | generated_at 2026-11-07T13:29:12+00:00, **overall DEGRADED** |

Names that do not exist on prod (checked so the receipt does not look for them): `NFL_GameLines.csv`,
`NFL_Game_Lines.csv`, `NBA_GameLines.csv`, `NCAAF_GameLines.csv`, `CFB_Odds.csv`, `data/scores/NBA_Finals.csv`.

## Provider quota (ledger tail; no credentials)
- Last entries: 2026-11-08 12:00:02/03Z, MLB/WNBA game_lines, `last=0`, **used 4,304 / remaining 95,696**.
- The 08:00Z entries read used 4,290 / remaining 95,710.
- Between 08:00 and 12:00 the balance moved by 14 credits. The four entries shown all have `last=0`, so this
  extract does not attribute those 14 credits; a fuller ledger read can.

### Credit attribution 08:00–12:33 UTC — **14 CREDITS FULLY ATTRIBUTED** (SSM `ede12441-31fd-4888-83eb-7b9930913152`, read-only)
**Ledger and journal headers.**
- The quota ledger's own entries cost 0: the `bk-linemove` game-lines runs at 08:00:11/12Z and 12:00:02/03Z
  (MLB, WNBA), `last=0`.
- The only Odds API remaining-balance lines in the window are those `bk-linemove` headers and the
  `bk-live-scores` poll lines. Both are journal output, not ledger entries.

| UTC | Unit | Sport / endpoint | Remaining after | Credits |
|---|---|---|---|---|
| 09:14:01 | `bk-live-scores.service` | NFL `/scores` (27 games, 0 live) | 95,708 | 2 |
| 09:15:11 | `bk-live-scores.service` | NFL `/scores` | 95,706 | 2 |
| 09:47:25 | `bk-live-scores.service` | NFL `/scores` | 95,704 | 2 |
| 09:53:10 | `bk-live-scores.service` | NFL `/scores` | 95,702 | 2 |
| 09:54:21 | `bk-live-scores.service` | NFL `/scores` | 95,700 | 2 |
| 10:07:01 | `bk-live-scores.service` | NFL `/scores` | 95,698 | 2 |
| 10:08:11 | `bk-live-scores.service` | NFL `/scores` | 95,696 | 2 |
| | | | **Total** | **14** |

95,710 − 95,696 = 14. That fully reconciles with the ledger's used 4,290 → 4,304.

**Expected: yes, by design.**
- `refresh_live_scores.py` self-gates to game windows and to signed-in user activity. It skipped **233** times in
  the window and polled only on these 7 activity-triggered ticks.
- **Which user:** not identifiable from the retained evidence, and not looked up (privacy).
- **Ledger gap:** the ledger does not record `/scores` calls; only the journal does. This is a pre-existing
  ledger-coverage gap, not new spend.

No other `bk-*` unit with provider calls ran in the window. Units that ran:
- `bk-nfl-gameday`, every 20 min (NFL injury poll);
- `bk-decision-journal-backup`, 08:17;
- `bk-nfl-games`, 12:30 (nflverse source, not the Odds API);
- `bk-backup`, 12:30.

The local dev box contributed nothing: its live-scores task logged "no signed-in user active … skipping API
poll". Older local log entries also show a different balance (~18.8k remaining), consistent with a separate key.

### Live-scores call-gate trace (read-only, code at `b12eec3` + prod schedule; no fix proposed)
Sources: `refresh_live_scores.py`, `deploy/bk-live-scores.{service,timer}`, and prod
`data/schedules/NFL_Schedule.csv` (SSM, read-only).

| Question | Finding |
|---|---|
| Timer frequency | `OnUnitActiveSec=60`, `AccuracySec=15s`: about 60 s after each activation, all day, year-round |
| Overlap / duplicates | None possible: `Type=oneshot` under one timer, and systemd does not start a unit that is already running. There is no file lock, but none is needed for this |
| Global coalescing | Yes, by construction. One server-side job writes one shared `data/live_scores/Live_Scores.csv`, and every user reads that file. Calls scale with **time while any user is active**, not with the number of users |
| Active-user gate | Works as designed: heartbeat age ≤ `ACTIVITY_WINDOW_SECONDS=120`. It skipped 233 runs in the window |
| Event-window gate | `sport_has_live_window()` polls when the sport has a game "today", is past the first start time minus `PREGAME_LEAD=20 min`, and not every game is final in the CSV. **It does not require a live game.** The "0 live" result is therefore allowed by design |
| **Why it called at 09:14Z** | **Timezone mismatch.** `NFL_Schedule.csv` `Time` is Eastern (CIN@ATL `09:30` = 9:30 ET = 14:30Z). The gate compares it with naive `datetime.now()`, which is **UTC on prod**. The window opened at **09:10Z** (04:10 ET), **5 h 20 m early**. "Today" is also the UTC date (`_today_str`, comment "UTC on prod"). This is the same Eastern-vs-UTC defect class as O-2 |
| Why calls ~1 min apart | Timer cadence (~60–70 s) while the heartbeat stayed fresh (≤ 120 s). Pairs such as 09:14/09:15, 09:53/09:54 and 10:07/10:08 are consecutive ticks during a short period of user activity |
| Cached / reused across users | Yes: the shared CSV, written only by the job. Web requests make no provider calls; they only refresh the heartbeat |
| Credits/hour, one user continuously active, no live games | NFL `/scores?daysFrom=1` = **2 credits per poll × ~50–60 polls/h ≈ 100–120 credits/h**. This lasts from 09:10Z on an NFL Sunday until every game is final, or until the UTC date rolls at 00:00Z. A second in-window sport (e.g. NCAAF on Saturday) adds about as much again |

Side observation, recorded only:
- Because "today" is the UTC date, the Sunday-night game (20:20 ET = 01:20Z Monday) falls outside "today's"
  schedule after 00:00Z. Live coverage of prime-time games depends on the stale-live catch-up path rather than
  the window gate.
- Same family as O-2. No fix proposed; no program-table item added.

## Receipt state before the run (all from the 2026-11-07 run unless noted)
- `_child_outcomes_football_props.json` 13:01:05Z: nfl_player_props UPDATED, ncaaf_player_props UPDATED,
  degraded false.
- `_child_outcomes_nba_daily.json` 13:06:13Z: player_props UPDATED, degraded false.
- `_child_outcomes_mlb_daily.json` 2026-10-28 (stale, off-season).
- Last props fetches:
  - NFL 13:00:52Z: 15 events found, 2,519 rows, 0 provider errors.
  - NCAAF 13:01:04Z: 57 events, 2,654 rows.
  - NBA 13:06:13Z: 7 events, 855 rows.
  - WNBA 13:06:30Z: 0 events.
  - MLB 2026-10-28.
- Last game-lines fetches: MLB and WNBA at **2026-11-08 12:00Z** (`bk-linemove`, `GAME_LINES_SPEC whole-file`).
- **CFBD latch:** `exhausted: true`, detected 2026-10-24T13:04:29Z, `reset_at: null`. Reason: HTTP 429 monthly
  quota at "CFB current-season results". The latch stays set until someone overrides it.
- **NFL line-movement summary:** daily snapshots of 45 / 72 / 70 / 68 / 68 rows, 2026-11-03 → 11-07, each at
  ~13:00Z. Current file 591 rows across 272 GameIDs.
