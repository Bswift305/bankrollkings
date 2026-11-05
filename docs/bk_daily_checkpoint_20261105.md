# First post-release `bk-daily` — November 5 checkpoint receipt

**Overall: FAILED (exit 1) / Run Status DEGRADED.** This is the first ordinary 13:00Z run on the accepted production
build `17b5e69`.

**How this was read:** read-only SSM at 18:09:27Z and 18:1xZ (`i-08d2fd818875381dd`). Nothing was changed, restarted,
fetched or purged.

## Unit result
| Field | Value |
|---|---|
| Start | 2026-11-05 13:00:10Z |
| Exit | 13:27:04Z (26 min 6 s) |
| `Result` | `exit-code` |
| `ExecMainStatus` | 1 |
| Alert | `bk-daily-alert` ran 13:27:12Z |
| Prod HEAD | `17b5e69` (unchanged) |
| Working tree | One untracked entry, `venv/`, dated 06-05. Long-standing; no tracked file is dirty |

## Run Status (`Run_Status.json`, generated 13:27:04Z)
- **overall:** `DEGRADED`
- **counts:** FRESH 19, AGING 2, STALE 4, MISSING 0
- **operator:** `blocking_failure=True`, `provider_exhausted_steps=[]`, `degraded_child_outcomes=[]`

## Failed steps, 11-04 vs 11-05
| Step | 11-04 (pre-release) | 11-05 (post-release) |
|---|---|---|
| CFB data refresh | FAIL | FAIL |
| MLB daily refresh | FAIL | FAIL (MLB game lines: "empty/too-small current slice: 0 rows < min 1", 1 credit) |
| NBA daily refresh | FAIL | FAIL — see NBA below |
| WNBA game lines | FAIL | FAIL |
| WNBA player props | FAIL | FAIL |
| All scorecards | FAIL | FAIL (incl. `NBA 99 Scorecard`, `Prelaunch Scorecard`) |
| NFL Heat-Map Freshness QC (**F1**) | FAIL | **CLEARED** (not in the failed list) |

**7 → 6 failed steps.** F1/heat-map is cleared. The scorecard failure is **not** cleared. The other five are the known
RCA classes (MLB/WNBA off-season empties, CFB, NBA), not regressions from this release.

## NBA lines and props
- **Game lines:** `fetch_game_lines` for `basketball_nba` received HTTP 200 and 6 bookmaker rows, 1 response,
  3 credits.
  - Validator verdict: **"implausible row-count collapse: 6 rows < 50% of prior 42"** → strong validation FAILED,
    existing files preserved, exit 1.
  - **Fail-closed as designed:** nothing was published. `data/odds/NBA_Odds.csv` is still the 11-04T13:05Z file.
- **Props:** `refresh_nba_daily` stops at the failed `game_lines` step, so the NBA props fetch **did not run**.
  - `NBA_Props.csv`: 1,678 rows, max `SourceUpdatedAtUTC` 2026-11-04T13:05:19Z, mtime 11-04T13:05Z (~29h old at read
    time).
  - Receipt `_last_props_fetch_basketball_nba.json`: at 11-04T13:05:24Z, 14 events, `rows_fetched 1678`,
    `provider_error_count 0`.
- **Not determined (read-only):** whether 6 rows was a genuine thin slate or a provider/window effect. The NBA v6 branch
  (event-slate contract) addresses this class. Not deployed.

## NFL / NCAAF props — no regression
| File | Rows | Max `SourceUpdatedAtUTC` | mtime |
|---|---|---|---|
| `NFL_Props.csv` | 2,248 | 2026-11-05T13:00:52Z | 11-05T13:00Z |
| `NCAAF_Props.csv` | 2,066 | 2026-11-05T13:00:55Z | 11-05T13:00Z |

Both refreshed on schedule with zone-explicit source time.

## Capture
- `BK_RESEARCH_CANDIDATE*`: **OFF**.
- 0 enabled flags in all three gunicorn processes' environments, and 0 enabled lines in `.env`. Values were not
  printed.

## Not covered
- No cause analysis beyond the log lines quoted.
- No fix proposed here; the open RCA items (F2 season gate, F3 NBA, F5 NCAAF, scorecards) stand as before.
