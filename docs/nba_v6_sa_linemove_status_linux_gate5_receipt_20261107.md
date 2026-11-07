# NBA v6 + Safeguard A + governed line-movement status — Linux gate #5 receipt — exact `b12eec3` (2026-11-07) — **PASS**

**Verdict.** Every assertion passes. **Not deployed**: no master push, no timers, no paid calls, no capture change.
`d2187e5` is **GATE PASS / DEPLOY HOLD** (its line-movement summary was best-effort, ungoverned and unbound);
`b12eec3` is the successor that closes that production-write boundary. The `d2187e5` receipt remains valid
evidence for the behavior it tested.

## Identity
- Branch `fix/nba-v6-sa-linemove-status-on-d2187e5`, HEAD **`b12eec342a2637596ab4f01b6f3051f2fe21aed2`** (`IDENTITY_OK`).
- `origin/master` = `3d7cda1` (tree == approved `17b5e69`); `10aab11` and `d2187e5` are ancestors.
- After `d2187e5`: 2 commits (`5a58b5c` governed/durable/mandatory status; `b12eec3` legacy-file, killed-run and
  SIGTERM cases), 9 files, +888/−62. Scope vs `3d7cda1`: **85 files** (`SCOPE_85_OK`).

## Governed runtime paths, modes, identifiers (as implemented and verified on Linux)
| Item | Value |
|---|---|
| Runtime root | `$BK_RUNTIME_DIR`, else the POSIX prod default `/opt/bankrollkings-runtime` (`services.nba_lines_publisher.runtime_root`); a QC process is refused unless its runtime is an isolated `qc_*` temp dir |
| Status directory | `<runtime root>/status/line_movement/` — created/verified by `process_lock._validated_lock_dir`: contained, never a symlink, **0700**; a looser dir we own is repaired, a foreign one refused |
| Invocation marker | `<status dir>/invocation.json` — **0600**, published FIRST (state `RUNNING`, `started_at`, `pid`) |
| Summary | `<status dir>/summary.json` — **0600**, published LAST, same `invocation_id`, `finished_at`, `exit_code`, `steps`, `failed_steps` |
| Write protocol | unique same-dir temp `.<name>.<pid>.<32hex>.tmp`, `O_CREAT|O_EXCL|O_NOFOLLOW`, `fchmod 0600`, flush + `fsync`, atomic replace, parent-dir `fsync` (POSIX), read-back verification (regular file, nlink 1, owner = euid, mode ≤ 0600, JSON object, matching id) |
| Refused targets | symlink, non-regular file, hard-linked (nlink ≠ 1), foreign-owned, looser than 0600 — never written through |
| Invocation-ID grammar | `^[0-9a-f]{32}$` (uuid4 hex); anything else is refused on publish and DEGRADED on read |
| Legacy checkout file | `data/tracking/Last_LineMovement_Summary.json` is no longer read or written by any code; an existing copy is **deliberately left untouched** (verified byte- and mtime-identical) and cannot mask a governed failure |

Linux evidence (QC `qc_linemove_status_persistence`, 59/0/0): dir mode `0o40700` under umask 000; both files
`0o100600`, nlink 1, owner euid; parent directory fsync'd after each of the 2 publishes.

## Interrupted runs — distinguished
| Case | Runner | Marker / summary | Run Status | systemd |
|---|---|---|---|---|
| **SIGTERM** (operator stop, earlyoom) | caught by `_entry`'s handler → **exit 2** (Linux: rc=2) | invocation stays `RUNNING`, no bound summary | in progress ≤ 20 min, then **DEGRADED** ("no published summary"); the older healthy summary is never adopted | exit 2 → **failed** (a SIGTERM death would otherwise count as clean by default) |
| **SIGKILL** | cannot be caught (Linux: rc=−9) | start marker remains unmatched | in progress ≤ 20 min, then **DEGRADED** — independent of how systemd classifies the signal | signal death (systemd classification is not relied on) |
| Unexpected exception / stray code | `_entry` → exit 2 | — | DEGRADED (marker unmatched) | failed |
| **Normal `systemctl stop` / restart during a deployment** | delivers SIGTERM → **exit 2** | incomplete invocation | **DEGRADED** until the next successful run | recorded as **failed** |

The last row is intentional and documented, not weakened: an interrupted market-refresh run is never recorded as
successful. Operationally, deploy restarts the web app (`bankrollkings`), not `bk-linemove`; a `bk-linemove` stop
during its ~2-minute run window will now show as one failed run until the next 4-hourly run succeeds.

## Results (CloudShell, kernel 6.1, Python 3.13.16, fresh anonymous clone, `unshare --net`)
| Assertion | Result |
|---|---|
| Compile | `py_compile` on 107 changed `.py`: rc 0 |
| QCs | **`QC_TOTAL=79 QC_FAIL=0`** (65 NBA + Safeguard A set + `runner_exit_matrix` 246/0 + `run_status_degraded` + **`linemove_status_persistence` 59/0/0**) |
| `qc_odds_feed` | refused, rc 3 |
| Probe | 37/37 |
| 4×50 loops | orchestrator / lines lock / props lock / credit attribution **50/0 each**, `LOOPFAIL_FILES=0`; 200 unique 0700 runtimes, 0 left over |
| POSIX | 59/0/0, 41/0/0, 37/0/0, 52/0/0, 59/0/0 — all "0 skipped (platform: linux)" |
| Network | only `lo`, 0 routes, `gaierror`, `curl` rc 6 |
| Prod canary | `PROD_CANARY_UNTOUCHED`; 2 audit events (known `os.putenv` guard-refusal tests) |
| Runtime isolation | 28 unique 0700 runtimes; all 18 publisher-reaching QCs ISOLATED |
| Mutations | **15/15 caught** (M1–M9 as gate #4; M10 summary best-effort, M11 Run Status unbound, M12 hard-link check dropped, M13 dir fsync dropped, M14 marker failure ignored, M15 files 0644) |
| Clean tree | 0 / 0 / 0; HEAD unchanged |

Offline gate (Windows, same SHA): 79/79, `qc_odds_feed` rc 3, clean tree. Gate script sha256 `74002b49…c319f6`
(both sides); log sha256 prefix `beb68e81b67e93ac825c`; finished 2026-11-07T14:38:08Z.

## Deployment notes (when approved)
- The runtime owner of `/opt/bankrollkings-runtime` must be the user running both `bk-linemove` and the Run Status
  generator (owner checks refuse foreign files).
- Off-season MLB/WNBA zero-event answers, the CFBD latch and missing keys now surface as failures (frozen semantics).
