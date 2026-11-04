# D11 (Run Status = current operator run) — scoped Linux gate receipt (2026-11-04)

**Verdict: PASS for exact `feca06ff83d86c80dc14b7eeeaef849b761dadbb`** (`fix/d11-run-status-current-run`; commits
`8064414` → `feca06f` on accepted master `17b5e69`). This is a gate only. Nothing deployed; no deploy before the
November 5 checkpoint and owner review.

## Pre-gate production check (read-only SSM, 2026-11-04 19:05:45Z)

**`bk-daily.service` limits (finite):**

| Setting | Value |
|---|---|
| `Type` | `oneshot` |
| `TimeoutStartSec` | **3600 (1h)** — bounds the whole oneshot run |
| `RuntimeMaxUSec` | infinity |
| `KillMode` | `control-group` (the whole process tree) |
| `KillSignal` | 15 |
| `SendSIGKILL` | yes |
| `FinalKillSignal` | 9 |
| `TimeoutStopUSec` / `TimeoutAbortUSec` | 1min 30s |
| `Restart` | `no` |
| `OnFailure` | `bk-daily-alert.service` |
| `ExecStart` | `run_daily.py --sports nba,wnba,mlb --continue-on-error` |

**A hung run is killed:** SIGTERM to the process group at 1h, then SIGKILL after 90s. The OS then releases the D11
`flock`. Run Status persists `INCOMPLETE` on the next start (same host, process gone) or on the next status read.

**Note:** D11's own marker deadline (planned step timeouts plus slack) can exceed 1h, so on prod the systemd 1h
timeout fires first. The process-gone path, not the deadline path, is what marks such a run `INCOMPLETE`.

**`Run_Status.json` secret scan:**
- `-rw-r--r--`, 7,691 bytes.
- Pattern scan for `sk_live/sk_test`, api key, secret, password, token=, `Bearer`, AWS `AKIA`, private-key headers,
  email addresses and query-string URLs: **0 hits**.
- Top-level keys: `counts`, `degraded_reasons`, `generated_at`, `operator`, `overall`, `rows`.
- **Retaining `0644` is acceptable.** The web app reads it; it contains no secrets.

## Gate

**Environment:**
- AWS CloudShell us-east-1, kernel `6.1.188-233.393.amzn2023.x86_64`, Python 3.13.16.
- Fresh anonymous clone; work dir `/tmp/d11gate`.
- Script sha256 `80e2b4e3…1748478e1fd52` (identical on both sides).
- Log sha256 `851f836f6665a8e87c4f955a0471744216c9cf73434fd800e5a46b092f3718ba`.
- 19:07:53Z → 19:12:36Z.

| Check | Result |
|---|---|
| Identity | `IDENTITY_OK`; `ORIGIN_MASTER_IS_BASE_OK` (`17b5e69`); `BASE_ANCESTOR_OK`; 2 commits |
| Scope | **8 files, +2070/−51** (`SCOPE_8_OK`): `app.py`, `generate_run_status.py`, `qc_run_status_current_run.py`, `run_all_scorecards.py`, `run_bk_edge_engine_pipeline.py`, `run_daily.py`, `services/operator_run.py`, `services/run_outcomes.py` |
| D1 preserved | 8 D1 files `identical_to_base`; `run_all_scorecards.py` `removed_lines=0` |
| Tree | before / after install / after QCs = 0 / 0 / 0 entries; HEAD after = exact `feca06f` |
| `pip install` | rc 0 |
| No network | `sudo unshare --net`, loopback up, no routes: `NO_NETWORK_CONFIRMED gaierror [Errno -2]`, `lo: UNKNOWN`, `curl_http=000`, curl rc 6 |
| `py_compile` | 52 changed `.py` files (vs D1 base), rc 0 |
| QCs | **`QC_TOTAL=53 QC_FAIL=0`** — the 46 production QCs (incl. `props_quote_source_time` 158/158, `ticket_quote_change` 114/114, `parlay_save_exact` 117/117, `unpriced_line_legs` 174/174) plus `run_status_current_run`, `run_status_degraded`, `operator_post_refresh_health`, `daily_operator_season_gate`, `run_outcomes`, `sport_parent_props` and `freshness_contract` |
| `qc_odds_feed` via `qc_offline.py` | **rc 3** (NOT RUN, `REQUIRES_NETWORK`) |
| Blocked connections | 5, all inside `unpriced_line_legs`' own socket-guard self-tests; 0 elsewhere |

**`qc_run_status_current_run` on Linux:** "[OK] baseline: 13 case groups pass", and **all 15 mutations caught**.

**The POSIX checks executed, not skipped.**
- The QC prints a `[NOTE] … skipped` line when it skips the 0600 or symlink checks (source lines 835–851). The gate
  log contains **0** "skip" lines.
- The lock under test is the real `fcntl.flock(LOCK_EX | LOCK_NB)` (`services/operator_run.py:337-339`).

**What the 13 case groups and 15 mutations cover:**
- **Concurrency and locking:** six concurrent starts produce exactly one run; `kill -9` releases the lock; a second
  run refuses with exit 75 and writes nothing.
- **Files:** 0600 operator files; symlink write refusal and no follow.
- **Finalization and recovery:** run-id-safe finalization (compare-and-swap; a newer pointer is never closed);
  killed-run transition to `INCOMPLETE` persisted by run start and by Run Status.
- **Child outcomes:** stale/legacy child outcomes excluded.
- **Retention:** bounded, and never deletes the current run's file.
- **Identity:** UTC/Eastern midnight cases; both invocation sites; run id immutable across 7 real child processes.

## Not covered
- No deploy and no production data.
- The production unit's `TimeoutStartSec` and its interaction with the marker deadline are analysed above, not
  exercised.
