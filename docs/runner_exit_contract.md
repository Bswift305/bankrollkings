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

## Frozen semantics (owner, 2026-11-07) — NBA v6 + Safeguard A combined

Proven end to end by `qc_runner_exit_matrix.py` (child receipt → runner classification → process exit →
systemd result → Run Status, with mutation proofs) and `qc_fetch_exit_semantics.py`.

| Case | Runner status | Runner exit | systemd (bk-linemove, `SuccessExitStatus=1`) | Run Status |
|---|---|---|---|---|
| `UPDATED` + **integer** `exit_code` 0 (never `True`, `0.0`, `"0"`) | OK | 0 | SUCCESS | GREEN |
| governed, independently sourced `NO_GAMES_SCHEDULED` (receipt `schedule_contract` in `GOVERNED_SCHEDULE_CONTRACTS`, child exit 1, receipt `exit_code` int 1) | `SKIPPED_NO_GAMES_SCHEDULED` | 0 | SUCCESS | GREEN |
| `NO_ACTIVE_EVENTS` (zero provider events), even naming a governed contract | FAILED | 2 | FAILED | DEGRADED |
| unconfigured sport | `UNCONFIGURED_SPORT` (child exit 2) | 2 | FAILED | DEGRADED |
| missing API key | `CONFIG_MISSING` (child exit 2, own receipt, zero requests) | 2 | FAILED | DEGRADED |
| quota exhausted (incl. a persisted latch) | `BLOCKED_QUOTA` — the latch stops calls, never a skip | 2 | FAILED | DEGRADED |
| missing / blank / unknown / `None` / contradictory receipt outcome; missing or non-int `exit_code`; another run's token; no receipt | FAILED / `RUN_RECEIPT_*` | 2 | FAILED | DEGRADED |
| exit ≥ 2, signal, timeout (a governed claim never launders it) | FAILED | 2 | FAILED | DEGRADED |

bk-daily (`run_daily.py`, default systemd success `{0}`): `CONFIG_MISSING` and `BLOCKED_QUOTA` are `FAIL` with that
`reason` (the old `SKIP (PROVIDER_QUOTA_EXHAUSTED)` is gone; Run Status treats a legacy one as ungoverned → DEGRADED).
An exit-0 child that also prints a typed failure is contradictory → `FAIL`. Quota steps are still listed in
`provider_exhausted_steps`.

### `SuccessExitStatus=1`: decision — runner exit mapping (no unit change needed)

The line-movement runner now exits **only 0 or 2**: every failure → 2; a governed skip → 0 with its reason
printed and recorded. It never returns 1, so `SuccessExitStatus=1` on the production `bk-linemove.service` can no
longer read a failure as success — the matrix models both the production unit (`{0,1}`) and a hardened unit
(`{0}`) and they agree on every row. The `SuccessExitStatus=1` line is now dead configuration; removing it is
optional hardening that requires an SSM unit install (a production change, not part of this release).

Run Status also no longer depends on systemd for this job. The runner publishes its status through
`services/linemove_status.py` (owner review of `d2187e5`, 2026-11-07):

* **Location:** `<runtime root>/status/line_movement/` (`$BK_RUNTIME_DIR`, else the POSIX prod default; a QC
  process is refused unless its runtime is isolated). Contained; the directory is created/verified 0700, never a
  symlink, a loose mode repaired only when we own it, otherwise refused.
* **Files:** `invocation.json` (published FIRST, state `RUNNING`, a fresh 32-hex `invocation_id`) and
  `summary.json` (published LAST, same `invocation_id`). 0600, created `O_CREAT|O_EXCL|O_NOFOLLOW` under a unique
  same-directory temp name, flushed + fsync'd, atomically replaced, parent directory fsync'd (POSIX), then read
  back and verified. A target that is a symlink, not regular, hard-linked, foreign-owned or looser than 0600 is
  refused, never written through.
* **Mandatory:** if the marker cannot be published the runner exits 2 **before any child runs**; if the summary
  cannot be published it exits 2 **even when every child succeeded** (and marks the invocation
  `PUBLICATION_FAILED`, best effort). Any unexpected exception exits 2 — never Python's 1, which
  `SuccessExitStatus=1` would read as success. SIGTERM (systemd stop, earlyoom) is turned into exit 2 as well:
  systemd counts a SIGTERM death as a clean exit by default.
* **Legacy file:** the old checkout file `data/tracking/Last_LineMovement_Summary.json` is no longer read or
  written by any code; an existing copy is deliberately left untouched (and cannot mask a governed failure).
* **Binding:** Run Status (`generate_run_status._linemove_signals` → `linemove_status.read_signals`) reads the
  marker first. The summary describes the current run only when its `invocation_id` matches. A
  `PUBLICATION_FAILED` marker is DEGRADED at once; a newer invocation with no summary is "in progress" for
  `RUNNING_GRACE_SECONDS` (20 min) and DEGRADED after that. An older healthy summary is never reported as
  current. An unsafe or unreadable status file, a bad invocation id, a failed step, a non-zero exit, or a run
  older than 8h is also DEGRADED.

Proven adversarially by `qc_linemove_status_persistence.py` (POSIX cases execute on Linux).

Exit 1 survives only where it is fully governed and explicitly proven: a chain runner passes a child 1 through
only when the child printed a GOVERNED claim (`runner_exit_for_child`); everything else maps to ≥2.
