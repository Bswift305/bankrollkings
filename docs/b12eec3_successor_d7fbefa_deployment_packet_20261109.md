# Deployment packet — `b12eec3` remediation, final candidate `d7fbefa` (2026-11-09) — APPROVED, DEPLOYED, PRODUCTION ACCEPTED 2026-11-09

**Candidate:** `d7fbefa95f093ce714982721f0f36e1196b33e13` (tree `8c8371e2dfe66c1406c886f12c7ecead0797069a`).
Branch `fix/b12eec3-qc-remediation`, local only. **Not pushed, not deployed.** Nothing here authorizes a push.

**Superseded, must not be deployed:**
- `be00c90`: per-run `qc_lmstatus_logs_*` leak.
- `0b292a4`: per-run `qc_lmstatus_*` root leak.

The `0b292a4` Linux payload was never sent. Its gate script had a malformed T-line block. It is kept as development
history only (`linux_gate2.sh`, `lg2.json` in the session scratchpad).

## 1. Commit lineage (each parent verified with `git rev-list --parents`)

| # | SHA | Parent | Files | What |
|---|---|---|---|---|
| 1 | `0c04f40` | `b12eec3` | 6 | Product fix (D1: NBA props freshness from `SourceUpdatedAtUTC` only); the three production-failing QCs fixed (D2–D4); new `qc_props_source_time_freshness.py`; registered in `run_all_scorecards.py` |
| 2 | `520bc8d` | `0c04f40` | 5 | Four older QCs updated to the explicit-source contract (D6); entity QC heartbeat redirect (D5) |
| 3 | `be00c90` | `520bc8d` | 3 | Option A heartbeat containment: `app.py` honours an absolute `BK_ACTIVE_USER_HEARTBEAT_PATH`; `run_all_scorecards.py` and `qc_offline.py` give every QC its own temp marker |
| 4 | `0b292a4` | `be00c90` | 1 | Line-movement QC: owned, removed empty logs dir (superseded by 5) |
| 5 | **`d7fbefa`** | `0b292a4` | 1 | Line-movement QC: ONE owned per-run root (`qc_lmstatus_*`), with the logs dir inside it, removed in a guaranteed `finally`; ownership-guarded removal |

**Scope change 10 → 11 files:** `be00c90` added `qc_offline.py`, the second QC runner Option A had to cover. Commits 4 and
5 touch only `qc_linemove_status_persistence.py`, which is already in scope. **Product code (`app.py`) is unchanged since
`be00c90`, and so are both runners.**

## 2. Exact diff `b12eec3..d7fbefa` — 11 files, 0 under `docs/`

| File | Lines | Blob at `d7fbefa` |
|---|---|---|
| `app.py` | +48 / -16 | `11bb97fca128` |
| `qc_entity_nba_wnba_market.py` | +34 / -1 | `19bf198363c7` |
| `qc_linemove_status_persistence.py` | +158 / -4 | `5701251fce00` |
| `qc_nba_gated_market_facts.py` | +2 / -0 | `93b5c2f831a6` |
| `qc_nba_market_only.py` | +14 / -7 | `8621c98655be` |
| `qc_nba_wnba_props_stale.py` | +20 / -8 | `53fba4e31593` |
| `qc_offline.py` | +11 / -1 | `e47e54a5e900` |
| `qc_props_source_time_freshness.py` | +177 / -0 | `3e26d3b0d04b` |
| `qc_quick_tools.py` | +3 / -1 | `3cb59b90e78a` |
| `qc_runner_exit_matrix.py` | +28 / -5 | `1795a8819f91` |
| `run_all_scorecards.py` | +11 / -0 | `0667d8f7d56f` |

The full diff is in `docs/b12eec3_final_d7fbefa_exact.diff` (833 lines, sha256 `65049ef6038e0700…`).

Production behaviour changes are confined to `app.py`:
1. **Props freshness (D1).** The authority is `SourceUpdatedAtUTC` only. Missing, zone-less or malformed values mean
   `no_timestamp` (fail closed). Rows are dropped if their own source time is missing or more than 5 minutes ahead.
   The 6-hour rule is unchanged.
2. **Heartbeat override.** It is honoured only as an absolute path. When it is absent, the live path is unchanged. Prod
   `.env` and units reference it 0 times (Linux gate).

## 3. Evidence mapped to SHA

Rows marked **FINAL** ran on exact `d7fbefa`: either the clean worktree at HEAD `d7fbefa` or a byte-verified
`git archive d7fbefa` export. Other rows are development history only.

| Evidence | SHA | Result |
|---|---|---|
| 80-QC offline gate, compile, refusal | **FINAL** `d7fbefa` (worktree) | 80/80; `COMPILE_OK`; `qc_odds_feed` rc 3 (REQUIRES_NETWORK); clean before and after; sentinel sha `ca0cd346…`, mtime 1700000000 unchanged; temp counts unchanged (45 roots / 32 logs, historical, untouched); 758 s |
| M1–M9 (+ original-shape M8) | **FINAL** `d7fbefa` (export) | All caught; matrix in §4 |
| Cleanup mutations M10–M10e (+ M5 both shapes) | **FINAL** `d7fbefa` (export, private TMP) | All caught by the intended T assertion; matrix in §4 |
| Line-movement repeat set (protected decoys) | **FINAL** `d7fbefa` | 10/10; 553 decoy files unchanged; 0 new roots, 0 new logs after every run |
| H1–H3 and runner probe | **FINAL** `d7fbefa` | H1/H2/H3 caught; both runners stamp only the temp marker (`stamped=True`); with no runner, the known writer stamps the live path (control) |
| 8 remediation QCs isolated without the runner (under H1 and H3) | **FINAL** `d7fbefa` | All 8 leave the real marker unchanged; the control writer changes it (mutation live) |
| Process-leak probe (Windows) | **FINAL** `d7fbefa` | Planted positive control detected; 0 processes referencing the QC temp dir during the run or at t+0/2/5/10/20 s after return |
| Linux gate | **FINAL** `d7fbefa` | §6 |
| 65/65 repeats (all 8 QCs) | `be00c90` (dev history) | 65/65, 553 protected files unchanged |
| 14 inherited writers: standalone vs `run_scorecard` | `be00c90` (dev history) | 14/14 change the marker standalone; 14/14 unchanged under the runner. The runners and `app.py` are byte-identical in `d7fbefa` |
| `0b292a4` gate, mutations, H runs | `0b292a4` (superseded) | 80/80, H1–H3 caught — retained as history |
| Original M1–M9, 65 repeats | `0c04f40`/`520bc8d` working trees (dev history) | Superseded by the FINAL rows |

## 4. Mutation matrix (FINAL, `d7fbefa`)

Every anchor applied exactly once, every mutated file compiled (no harness damage), and every mutated file was
restored byte-for-byte (sha-checked).

| Mutation | Intended defect | Caught by (primary assertion) | Kind |
|---|---|---|---|
| M1 | LastUpdated governs freshness again | `props_source_time_freshness` (15 FAIL: "fresh NBA feed is executable…aged from its source time", "dst_fresh: explicit source time governs…") + `nba_wnba_props_stale` (8) + `nba_market_only` (1) | assertion |
| M2 | Untimed rows stay executable | `props_source_time_freshness`: "row level: missing-source and future-source rows are dropped" | assertion |
| M3 | Wall-clock warning left in place | `props_source_time_freshness` (4): "…misleading LastUpdated ignored; no stale warning" | assertion |
| M4 | 6h loosened to 24h | `props_source_time_freshness`: "7h-old source -> stale, withheld"; `nba_wnba_props_stale` (37) | assertion |
| M5 | Status Persistence reads the checkout `logs/` | `linemove`: "H hermetic: …never the checkout logs/". With a prod-like `logs/` decoy it reproduces the production `ValueError` (crash) | assertion (crash only with the decoy) |
| M6 | API key dropped before the fetcher import | `runner_exit_matrix` (prod-like `.env` decoy): "missing API key: runner status FAILED (expected CONFIG_MISSING)", "…zero requests", "REAL child attempted no network access" | assertion |
| M7 | Entity raw loaders not isolated | `entity_nba_wnba_market` (prod-like feeds): "wnba-player page missing identity/abstain" | assertion |
| M8 (strict: always fresh) | Gate ignores source time | `props_source_time_freshness` (12), `nba_wnba_props_stale` (83), `nba_market_only` (4), `quick_tools` (3); **only `nba_gated_market_facts` misses it** (a rendering test). The suite kills it, so no strengthening is needed | assertion |
| M8 (original: source ignored → untimed) | Same | All 5 incl. `nba_gated_market_facts` (1) | assertion |
| M9 | Entity heartbeat redirect removed | `entity_nba_wnba_market`: "the REAL activity heartbeat … written by this QC" (with and without the runner) | assertion |
| M10 | Owned root never removed | T pass / assertion-failure / exception / SystemExit paths (+ QC rc 1: **failure to clean fails loudly**) | assertion |
| M10b | Cleanup skipped when an exception escapes | T assertion-failure / exception / SystemExit paths + "this run left zero new…" | assertion |
| M10c | Ownership guard removed | T "foreign / historical / sibling-run directories … never deleted" | assertion |
| M10d | Logs dir created outside the owned root | T cycle checks (6 top-level `qc_lmstatus_logs_*` leaked) | assertion |
| M10e | Second, unowned root (the inherited `b12eec3` leak) | T "this run left zero new `qc_lmstatus_*` (1)…" | assertion |

**Environment note:** M6 and M7 are inert without a key and real feeds (rc 0 in a bare export). Those defects only exist
when the production conditions are present. With the prod-like decoys both are caught by their intended assertions.

## 5. Cleanup design and temp hygiene (FINAL)

The removal path refuses any target unless all of the following hold:
- the exact path is recorded in `_CREATED_ROOTS` (exact generated identity, from this process's own `mkdtemp`);
- it is not a symlink;
- it is a directory;
- its name has the `qc_lmstatus_` prefix;
- its resolved parent equals the system temp dir.

It never removes pre-existing, historical, foreign or sibling directories. The T check proves this with live decoys.

- **Retry:** hard 30-second deadline. If the directory still exists afterwards, the final T assertion fails and the QC
  exits 1 (M10 proves this).
- **Windows:** the first post-fix run left one empty root. A transient handle is the likely cause; it is unidentified.
  The process probe shows no process survives the QC, so the retry hides no orphan. That one empty directory is in local
  dev temp and was left untouched.
- **Historical leftovers:** never deleted. That covers the 32 logs and 45 roots on the dev box, plus the prod `/tmp`
  entries from earlier QC runs.

## 6. Linux gate on exact `d7fbefa` (SSM `6bd2aeea-5d53-41ff-bd28-2fb1367cc786`)

**Payload.** Validated before sending: the decoded bundle verifies and its only head is `d7fbefa95f09…`; the decoded
script matches the reviewed file byte for byte and passes `bash -n`; old SHAs appear only in a header comment.

| Artifact | Hash / size |
|---|---|
| Bundle | sha256 `af72991b…f793` |
| Script | sha256 `93e35389…f0c2` |
| JSON | sha256 `0d6f3d45…a941`, 47,096 base64 bytes; re-verified in CloudShell before send |

The first typing attempt never reached the terminal (no focus after the CloudShell reconnect). Nothing ran; all seven
parts were retyped and verified.

**Status:** Success, 12:35:55Z–12:43:50Z, 475 s.

| Requirement | Result |
|---|---|
| Exact SHA | HEAD `d7fbefa95f093ce714982721f0f36e1196b33e13`, IDENTITY_OK; scope 11 files, 0 docs |
| Throwaway clone clean before and after | yes / yes |
| Compile | `COMPILE_OK` |
| QCs | 80 run, 0 failed |
| Refusal | `qc_odds_feed` rc 3 (REQUIRES_NETWORK) |
| Line-movement QC on Linux | 67 passed, 0 failed, **0 skipped**. All T checks OK, including SIGTERM (rc 143) and the foreign/sibling guard; POSIX S/P/K run |
| Line-movement repeats on Linux | 5/5 |
| Process-zone checks | identical verdicts under New York and Los Angeles as under UTC; freshness QC 23/23 |
| Heartbeat sentinel | `ca0cd346…81d6` mtime 1700000000, UNCHANGED |
| Orphan check | positive control (planted pid 1731413) detected = 1; 0 surviving wrapper/child/grandchild processes after all QCs, and 0 again after the gate exited |
| QC temp artifacts | `TMPDIR` inside the clone: 0 `qc_lmstatus_*` roots and 0 logs dirs left; inherited QCs left 17 `dj_qc_*`, 4 `qc_*` and `qc_lens_attr.parquet` there, all removed with the clone |
| `/tmp` (ubuntu) | before 510 (`qc_lmstatus_*` roots 2, logs 1, historical); after 509 (roots 2, logs 1). **0 new entries.** The −1 is the gate's own `/tmp/bk_rem_bundle.b64`, deleted after decoding (it was in the "before" snapshot). Historical entries untouched |
| Removal | clone `/opt/bankrollkings-runtime/qcgate.xjUPxu` gone; 0 `qcgate.*` dirs; `/tmp/bk_rem_bundle.b64`, `/tmp/bk_linux_gate.sh` and `/tmp/bk_linux_gate.out` all gone |

**Live system after the gate, unchanged:**
- HEAD `b12eec3`; porcelain is only `?? venv/`; `.git/index` mtime 2026-11-07 14:51:35.
- Service ActiveEnter 2026-11-08 13:34:07, NRestarts 0.
- `.env` mtime 2026-10-23; newest unit file 2026-10-18; override references in `.env`/units 0/0.
- Real heartbeat marker mtime 2026-11-08 13:33:21 (unchanged).

As with every SSM command, the agent keeps its own copy of this command under `/var/lib/amazon/ssm/…/orchestration/`
(default retention).

## 7. Production-host operations and cleanup evidence

### `be00c90` gate (SSM `d8bb79b9-…`, 2026-11-09 10:42:10Z–10:49:57Z)

- **Created and removed:**
  - `/tmp/bk_rem_bundle.b64`
  - `/tmp/bk_linux_gate.sh`
  - `/tmp/bk_linux_gate.out`
  - clone `/opt/bankrollkings-runtime/qcgate.FQCGO1`

  All are absent (read-only check 11:03Z).
- **Left behind:** 24 `/tmp` entries owned by `ubuntu`, all created by the gate's QCs (1,892 KB):
  - 17 `dj_qc_*` (decision_journal);
  - `qc_nba_lines_lock_default_*`, `qc_nba_props_lock_default_*`;
  - 2 `qc_runreceipts_*`;
  - `qc_lmstatus_logs_*` (the `be00c90` leak);
  - `qc_lmstatus_*` (the inherited root leak).
- **Modified, not created:** `qc_lens_attr.parquet` (birth 2026-10-09).

  23 of the 24 were born inside the window. None contains the bundle, the gate script, source, `.env`, keys or
  credential patterns. One helper names the deleted clone path. 452 same-pattern entries from 2026-10-17 → 11-08
  predate the gate. **Not cleaned (owner rule).** They age out under `D /tmp … 30d`.
- **The SSM agent keeps its own copy** of the command (44 KB, including the bundle base64) under
  `/var/lib/amazon/ssm/…/orchestration/d8bb79b9…`, at default retention. This is true of every SSM command.
- **Unchanged on the live system:**
  - HEAD `b12eec3`; the only porcelain line is `?? venv/`.
  - `.git/index` mtime 2026-11-07 14:51 (unchanged by any probe).
  - Service up since 2026-11-08 13:34:07, NRestarts 0.
  - Newest unit file 2026-10-18; `.env` mtime 2026-10-23.
  - 0 files modified in `/opt/bankrollkings` or `/opt/bankrollkings-runtime` during the window.
  - Heartbeat marker mtime 2026-11-08 13:33:21 (before the gate).

### `d7fbefa` gate

`TMPDIR` points inside the clone, so every QC temp artifact is removed with it. The result is in §6.

### The `venv/` porcelain entry

- Untracked (`?`), not ignored, never tracked in history.
- Mode `drwxrwxr-x`, owner `ubuntu`; born 2026-06-05 02:56:16; newest file mtime 2026-06-06.
- 15,602 files, 636,672 KB; manifest sha `6d8eb94d…`.
- 0 files modified or ctime-changed in the gate window or since. It existed four months before the gate; no gate command
  wrote to it.
- Earlier probes ran plain `git status`, but `.git/index` mtime stayed at 2026-11-07, so they wrote nothing. Later probes
  use `GIT_OPTIONAL_LOCKS=0`.

## 8. Heartbeat containment — three separate statements

1. **Gate containment (proven):** the runners give every QC a temp marker. The Linux and local gate sentinels were
   unchanged. The 6 writers inside the 80-QC gate were contained; the other 8 writers are not gate members and were not
   exercised there.
2. **Remediation-QC containment (proven, FINAL):** all 8 remediation QCs leave the real marker unchanged:
   - standalone, with no runner;
   - under `qc_offline`;
   - under H1 (runner override removed);
   - under H3 (`app.py` ignores the override).
3. **Inherited-QC containment (conditional, unresolved beyond the runner):**
   - All 14 inherited writers change the real marker when run standalone.
   - All 14 leave it unchanged under `run_all_scorecards.run_scorecard`.
   - Production schedules them only through that runner (`run_daily` → `run_all_scorecards`). No other runner, unit or
     script invokes the 8 non-gate writers.
   - **Containment therefore depends on using the governed runner.** It applies to prod only once `d7fbefa` is deployed;
     until then, prod's daily scorecards (on `b12eec3`) still stamp the real marker (last stamp 2026-11-08 13:33:21Z).
   - Standalone QC runs still need the override set by hand.
   - **No claim of universal containment.**
   - **Not yet characterized** (separate active item): `refresh_runtime_snapshots.prewarm_expensive_pages()` signs in a
     session and renders routes. It runs in `bk-daily`, after every auto-deploy and in the post-week script. Whether it
     stamps the real marker depends on `get_current_user()` resolving that session on prod, which has not been verified.

## 9. Proposed checks (read-only; to run only after an approved deploy)

**Preflight, before any push:**
- `origin/master..d7fbefa` shows exactly the 5 commits above.
- The prod tree is clean apart from `?? venv/`.
- Prod HEAD is `b12eec3`.
- `bk-deploy.timer` is active.
- No `qcgate.*` exists.

**Post-deploy acceptance:**
- **Deploy landed:** `journalctl -u bk-deploy.service` shows the pull to `d7fbefa` and the restart; prod HEAD is
  `d7fbefa`; NRestarts is 0 after the restart.
- **D1:** NBA props status reads `freshness_source=SourceUpdatedAtUTC`, with no `future_timestamp` while the feed's
  source time is current.
- **Heartbeat:** the next `bk-daily` "All scorecards" step leaves the real heartbeat mtime unchanged.
- **Scorecards:** the three remediated QCs pass, with no new `qc_lmstatus_*` in `/tmp`.
- **Prewarm cost note:** the auto-deploy prewarm may stamp the heartbeat (unverified, §8). Expect at most about 2 minutes
  of live-score polling if a game window is open.
