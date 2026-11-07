# NBA v6 + Safeguard A combined — Linux gate #4 receipt — exact `d2187e5` (2026-11-07) — **PASS**

**Verdict.** Every assertion passes. **Not deployed**: no master push, no timers, no paid calls, no capture change.
NBA v6 `10aab11` itself stays **GATE PASS / DEPLOY HOLD** (its runner exited 1 on failure, which prod
`bk-linemove`'s `SuccessExitStatus=1` read as success); this combined successor is the candidate that resolves it.

## Identity
- Branch `fix/nba-v6-safeguard-a-on-10aab11`, HEAD **`d2187e560c074de30c6bdce92ae4edc7bf63ddaf`** (`IDENTITY_OK`).
- Base `origin/master` = `3d7cda1` (`ORIGIN_MASTER_IS_BASE_OK`); `3d7cda1^{tree}` == approved `17b5e69^{tree}`.
- `10aab11` (gate #3 PASS) is an ancestor; 8 commits after it: Safeguard A's 5 commits cherry-picked
  (`4825452`, `bfe5109`, `e1eaf1f`, `b89315a`, `c7b5c32`) + `af56a45` (integration QC fixtures) + `17153fe`
  (frozen exit semantics + matrix QC) + `d2187e5` (runtime isolation for the new QCs; NCAAF mutant on `SPORT_PATHS`).
- Scope vs `3d7cda1`: **81 files** (`SCOPE_81_OK`), +13.6k / −0.5k = v6's 63 + Safeguard A's 15 non-overlapping
  + `qc_runner_exit_matrix.py`, `qc_cfb_quota_shortcircuit.py`, `refresh_cfb_data.py`.

## Frozen semantics (owner 2026-11-07) — implemented
| Case | Result |
|---|---|
| `UPDATED` + **integer** `exit_code` 0 | success (a bool / float / string `exit_code` fails — `is_exact_int`) |
| governed, independently sourced `NO_GAMES_SCHEDULED` | `SKIPPED_NO_GAMES_SCHEDULED`, runner exit 0 (registry `GOVERNED_SCHEDULE_CONTRACTS` still **empty**) |
| `NO_ACTIVE_EVENTS` without governed proof | degraded failure (now ALERTING everywhere, props included) |
| unconfigured sport | `UNCONFIGURED_SPORT`, child exit 2 |
| missing API key | `CONFIG_MISSING`, child exit 2 (fetch_game_lines writes its own receipt; props / football props / CFB no longer exit 0) |
| quota exhaustion | `BLOCKED_QUOTA`, degraded FAIL; the CFBD latch still makes zero calls; `SKIP (PROVIDER_QUOTA_EXHAUSTED)` removed |
| missing / blank / unknown / contradictory outcome | hard failure |
| any internal failure | never SUCCESS under `SuccessExitStatus=1` |

**`SuccessExitStatus=1` decision: runner exit mapping.** `refresh_line_movement_snapshots.py` now exits only 0 or 2,
so the prod unit's `{0,1}` success set can no longer mask a failure; no unit change is required (removing the dead
line is optional SSM hardening). Run Status reads the runner's own summary
(`data/tracking/Last_LineMovement_Summary.json`, gitignored) via `generate_run_status._linemove_signals`.

## Results (AWS CloudShell, kernel 6.1, Python 3.13.16, fresh anonymous clone, `unshare --net`)
| Assertion | Result |
|---|---|
| Compile | `py_compile` 103 changed `.py`: rc 0 |
| QCs | **`QC_TOTAL=77 QC_FAIL=0`** — the 65 NBA QCs + `fetch_exit_semantics` (565 ok), `fetch_output_paths` (247 ok), `run_outcomes`, `football_props_aggregation`, `operator_post_refresh_health`, `daily_operator_season_gate`, `cfb_quota_shortcircuit`, `freshness_contract`, `injury_feed_season_aware`, `nba_sources`, `nfl_season_contract`, **`runner_exit_matrix` 246/0** |
| `qc_odds_feed` | refused, rc 3 (`REQUIRES_NETWORK`) |
| Line-movement probe | **37/37** — incl. blank / whitespace / unknown / lowercase / non-string outcome, `exit_code` `True` / `False` / `0.0` / `"0"`, `NO_ACTIVE_EVENTS`, ungoverned + governed-fixture `NO_GAMES_SCHEDULED`, exit-2 laundering, identical-mtime token sequence |
| End-to-end matrix | 33 bk-linemove rows (child receipt → runner → exit → systemd prod `{0,1}` and hardened `{0}` → Run Status), incl. REAL `fetch_game_lines` unconfigured sport and missing key; 12 bk-daily rows; invariant "no failure reads SUCCESS" on every row |
| 4×50 loops | **orchestrator 50/0, lines lock 50/0, props lock 50/0, credit attribution 50/0**, `LOOPFAIL_FILES=0`; 200 unique 0700 runtimes, 0 left over; 50 audit events = one `os.putenv` per lines-lock guard-refusal run |
| POSIX | lines lock 59/0/0, props lock 41/0/0, receipt contract 37/0/0, orchestrator 52/0/0 — all "0 skipped (platform: linux)" |
| Network isolation | only `lo` (UNKNOWN), 0 routes, `gaierror`, `curl` rc 6 |
| Prod-runtime canary | `PROD_CANARY_UNTOUCHED`; QC phase: 2 audit events, both `os.putenv` guard-refusal tests; 0 filesystem events |
| Runtime isolation | 25 `qc_runtime_*` dirs, 25 unique, all 0700, 0 left over; all 18 publisher-reaching QCs ISOLATED |
| Mutations | **9/9 CAUGHT**: M1 old OK rule, M2 OK without exit_code proof, M3 `NO_ACTIVE_EVENTS` benign, M4 governance bypass, M5 runner exits 1, M6 lenient int, M7 run_daily exit-0 + typed failure → PASS, M8 Run Status ignores the summary, M9 quota no longer typed |
| Clean tree | 0 entries before / after install / after; HEAD unchanged |
| D1 / markers | 8 D1 files identical; all `app.py` markers SAME except the documented `SourceUpdatedAtUTC` 18→19 reader |
| `run_all_scorecards` | 7 removed lines = Safeguard A's intended removal of the props-file `SKIP (off-season)` laundering + exit 1→2; 1 line added (matrix QC registration) |

Offline gate (Windows, same SHA): 77/77, `qc_odds_feed` rc 3, clean tree before/after.

## Runs
- **Run 1** (10:34Z): identity, scope, all 77 QCs, probe, audit identical to run 2; the CloudShell environment was
  recycled during its loops (page outage, fresh host `up 11 min`), so its loops/mutations are **not evidence**.
  Log kept as `gate4_run1_interrupted.log`.
- **Run 2** (12:34Z → 13:15:24Z): the same script, complete. Gate script sha256 `47c1bcbe…46cc` (both sides);
  log sha256 prefix `2d2b477fa7bd047039ea`.

## Findings / owner notes
- **Latent in `10aab11` (fixed here):** its `receipt.get("exit_code") == 0` accepted `False` / `0.0` as success.
- **Behavior changes when deployed** (intended, per the frozen semantics): off-season MLB/WNBA zero-event answers make
  `bk-linemove` exit 2 and Run Status DEGRADED every 4h until a governed schedule contract exists; the latched CFBD
  quota makes bk-daily's CFB step a FAIL daily (it was a SKIP); a missing key anywhere is a hard failure.
- `SuccessExitStatus=1` on `bk-linemove.service` is now dead config — optional removal via SSM, separately approved.
