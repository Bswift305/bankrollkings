# Runner exit contract (Safeguard A) + governed off-season / no-game rule

Source of truth in code: `services/run_outcomes.py` (`classify_step_exit`, `runner_exit_for_child`,
`GOVERNED_SEASON_CALENDARS`, `GOVERNED_SCHEDULE_CONTRACTS`). Proven by `qc_fetch_exit_semantics.py`
(run it via `py -3 qc_offline.py qc_fetch_exit_semantics.py`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | the benign "no new rows / last-known-good preserved" outcome, **and only when the cause is governed** (`SKIPPED_OFF_SEASON` from a governed calendar, or `NO_GAMES_SCHEDULED` from a governed schedule contract) |
| >=2 | hard failure / degraded. A runner never maps a hard failure onto 0 or 1 |

Production units only pass the runner's code through: `bk-linemove.service` has `SuccessExitStatus=1`
(0 and 1 read as SUCCESS), `bk-daily.service` uses the default (only 0 reads as SUCCESS).

## Owner decision, 2026-11-04

* An empty or failed fetch is **never** an off-season skip and never OK.
* `SKIPPED_OFF_SEASON` comes only from a calendar listed in `GOVERNED_SEASON_CALENDARS`, decided **before**
  any provider call (zero credits). A child claim must say `provider_calls=0`.
* `NO_GAMES_SCHEDULED` comes only from a contract listed in `GOVERNED_SCHEDULE_CONTRACTS`.
* `UNCONFIGURED_SPORT` is a hard failure (exit 2) in and out of season.
* Empty rows, a provider error, or a non-zero exit with no governed reason is a FAILURE (degraded).
  `NO_ACTIVE_EVENTS` (the provider listed zero events) is ALERTING, because an empty provider answer is not
  a schedule contract.
* A governed claim never overrides an exit of 2 or more.
* `active_sports()` (a non-empty props file) is **not** a season calendar. Nothing uses it to classify a
  failure any more.

Child claim format (one line on stdout):

```
OUTCOME: SKIPPED_OFF_SEASON calendar=<governed id> provider_calls=0
OUTCOME: NO_GAMES_SCHEDULED contract=<governed id>
```

### What is governed today

| Sport / step | Governed calendar or contract | Result when its fetch is empty or fails |
|---|---|---|
| NFL preseason lines | `season_utils.nfl_preseason_active` (Jul 20 to Sep 12). The operator skips the step before it runs | `SKIP (out of preseason window)`, outcome `SKIPPED_OFF_SEASON`, `provider_calls=0` |
| NFL regular season | none. `services/nfl_season_contract.NFL_SEASON_WEEK1_THURSDAY` sets Week 1 only, with no season end or playoffs, so it cannot say "off-season" | FAIL |
| NCAAF, NBA, WNBA, MLB | none (MLB and WNBA wait for F2v2/F6) | FAIL |
| Any sport, "no games" | none. `GOVERNED_SCHEDULE_CONTRACTS` is empty | FAIL |

## Runner matrix

| Child result | run_daily step (with or without `--continue-on-error`) | bk-linemove runner | chain runners (nba/mlb/wnba daily, football line movement) | Run Status |
|---|---|---|---|---|
| exit 0 | PASS | OK, exit 0 | exit 0 | GREEN on this step |
| exit 1, empty rows or provider error, no claim | FAIL `NO_GOVERNED_REASON`, exit 2 | FAILED, exit 2 | exit 2 | DEGRADED |
| exit 1 + governed `NO_GAMES_SCHEDULED` | `NO_GAMES_SCHEDULED`, exit 0, listed in `governed_skips` | OK, exit 0 | exit 2 (output is streamed, so the claim is not visible) | GREEN |
| exit 1 + governed `SKIPPED_OFF_SEASON` (`provider_calls=0`) | `SKIPPED_OFF_SEASON`, exit 0 | OK, exit 0 | exit 2 (output is streamed) | GREEN |
| exit 1 + ungoverned claim, or `provider_calls` not 0 | FAIL `UNGOVERNED_CLAIM`, exit 2 | FAILED, exit 2 | exit 2 | DEGRADED |
| governed calendar closed, decided before the run | `SKIP (out of preseason window)`, not run, 0 provider calls | n/a | n/a | GREEN |
| exit 2 `UNCONFIGURED_SPORT` | FAIL `UNCONFIGURED_SPORT`, exit 2 | FAILED, exit 2 | exit 2 | DEGRADED |
| exit 3 or more, signal, or timeout (claim or not) | FAIL `HARD_FAILURE`, exit 2 | FAILED, exit 2 | the same code (at least 2) | DEGRADED |
| props child: zero provider events | (parent) DEGRADED, `NO_ACTIVE_EVENTS`, exit 2 | n/a | exit 2 | DEGRADED |
| Edge Engine / scorecard step fails, even with empty props | FAIL, runner exit 2 (no `SKIP (off-season)`) | n/a | n/a | DEGRADED |

Run Status (`generate_run_status._operator_signals`) also reads these as DEGRADED:

* any step status that is not PASS, FAIL, the pre-refresh WARN, provider-quota SKIP, or a governed
  non-publish. This includes a legacy `SKIP (off-season)`;
* `failed_steps` even when `blocking_failure` is false;
* a sport whose game lines **and** props are both REFRESH_MISSED (`_odds_family_signals`). This used to be
  silently read as "off-season".

Still not covered by this rule, left for an owner decision: the provider-quota exhaustion step is still
recorded as `SKIP (PROVIDER_QUOTA_EXHAUSTED)` with exit 0 (Run Status shows it DEGRADED);
`refresh_football_props` exits 0 when `ODDS_API_KEY` is missing; `qc_odds_feed` does not flag a sport whose
lines and props are both stale; `run_prelaunch_scorecard` marks route failures for "off-season" sports N/A
using props files; `services/injury_feed_qc` reports a stale injury feed with no games in the window as
`NO_ACTIVE_EVENTS` WATCH; and `fetch_nfl_games --gate` uses its own Aug to Feb month window.
