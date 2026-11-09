# Production receipt — `d7fbefa` (b12eec3 remediation), 2026-11-09 — PRODUCTION ACCEPTED — CLOSED

**Deployed:** `d7fbefa95f093ce714982721f0f36e1196b33e13`. Owner-approved; exact SHA only. Fast-forward `b12eec3..d7fbefa`.
No merge, rebase, cherry-pick or force push.

**Status: PRODUCTION ACCEPTED — CLOSED (owner, 2026-11-09).** The acceptance contract is satisfied: the production
defect is fixed; fresh NBA props are executable immediately on `SourceUpdatedAtUTC`; misleading or malformed
`LastUpdated` cannot move the verdict; all remediation QCs pass in scheduled and focused production runs; scorecards
create no user activity and no paid live-score polling; no temp or process leaks; Run Status binds correctly;
production is healthy and unchanged outside the authorized deployment. Today's `bk-daily` failures are inherited
obligations (§4, §9). They stay visible but do not reopen or block this release.

## 1. Preflight (read-only, 12:52:14Z)

- **Git:** prod HEAD and tracking `origin/master` = `b12eec3` (remote `master` confirmed via `ls-remote`). 0 tracked
  changes; only `?? venv/` (manifest `6d8eb94d…`, unchanged).
- **Service:** active, NRestarts 0, up since 2026-11-08 13:34:07. `/healthz` 200.
- **Flags and jobs:** Research Candidate unset (OFF). No `bk-*` job running.
- **Next heavy job:** `bk-daily` at 13:00Z.
- **Heartbeat marker:** sha `33f72a14…`, content `1794144801`, mtime 2026-11-08 13:33:21 (last stamped by the
  `b12eec3` scorecards).
- **Config fingerprints:** units `ed80c9c3…`, `.env` `63089c1b…`, deploy script `4bbc5dce…` (= repo `ops/`).

## 2. Push and deploy

- **Push:**
  - branch `fix/b12eec3-qc-remediation` → remote `d7fbefa` (verified);
  - then `d7fbefa:refs/heads/master` at 12:53:21Z (`b12eec3..d7fbefa`, verified).
- **Auto-deploy (no manual restart):**
  - 12:53:40 `deploy: b12eec3 -> d7fbefa`;
  - 12:53:45 service restarted;
  - 12:53:48 `deployed d7fbefa | service: active | probe: HTTP 200`;
  - 12:54:24 `prewarm: ok`.
- **Post-deploy:**
  - prod HEAD and tracking `origin/master` = `d7fbefa`; 0 tracked changes; `venv/` unchanged;
  - NRestarts 0; Research Candidate OFF;
  - unit, `.env` and deploy-script fingerprints identical to preflight; `/healthz` 200.

## 3. Deploy-prewarm heartbeat (measured; no extra signed-in request made)

- **Marker:** unchanged through the deploy and prewarm (content `1794144801`, mtime 2026-11-08 13:33:21).
- **Live-score runs:** every run after the deploy logged "no signed-in user active — skipping API poll".
- **Finding:** the auto-deploy prewarm (`--prewarm-only`) ran only cache builders (`live_promotion_signal_context`,
  `nfl_hot_hand`, …). It did **not** call `record_active_user`.
- **Not exercised:** the signed-in `prewarm_expensive_pages()` path. Its session test-user id is present in 0 user-store
  files, so it most likely cannot resolve to a signed-in user. The candidate writer is downgraded, but not proven absent
  for the `bk-daily` "Dashboard prewarm" step.

## 4. Scheduled `bk-daily` (13:00:00Z → 13:30:09Z, exit 2), read-only

**Normal NBA props publication** (acceptance event):
- stage run `60a840baf7c74e2c8a8ebf72a47e4abb`, outcome UPDATED, 13:05:13Z;
- 987 rows, 9 events;
- `SourceUpdatedAtUTC` 13:02:16Z–13:05:10Z, 0 missing;
- zone-less `LastUpdated` "2026-11-09 13:05" (UTC on prod; `b12eec3` misread it as Eastern, i.e. 5 h in the future).

**Failed and degraded steps, every one classified:**

| Step | Today | Yesterday (`b12eec3`) | Class |
|---|---|---|---|
| CFB data refresh | BLOCKED_QUOTA (CFBD monthly quota, latched since 2026-10-24) | same | inherited, unrelated |
| MLB daily refresh | HARD_FAILURE: `game_lines` exit 1 on NO_ACTIVE_EVENTS (off-season, 0 credits) | same | inherited, unrelated |
| NBA daily refresh | HARD_FAILURE: `board_qc` exit 1 (playoff logs/results missing; 987 rows lack team mapping; `postseason_only` default filters regular-season games → "Live prop rows checked: 0"). Props stage itself UPDATED | `board_qc` exit 1 | inherited, unrelated (NBA-readiness `postseason=1` default, already on record). Not the props gate: the deployed verdict marks 987/987 rows executable (§5) |
| WNBA game lines / player props | NO_GOVERNED_REASON (off-season, NO_ACTIVE_EVENTS) | same | inherited, unrelated |
| Scorecards: NBA/WNBA/MLB 99, Prelaunch | WATCH (not blocking) | Prelaunch FAIL | inherited; Prelaunch improved FAIL → WATCH |
| **All scorecards** | **not failed** | **FAIL** (Runner Exit Matrix, Line-Movement Status Persistence, NBA/WNBA Market-Only Entity QCs) | **fixed by this release** |

**Scheduled remediation QCs, all PASS:** Quick Tools, NBA/WNBA Stale Props, Runner Exit Matrix, Line-Movement Status
Persistence, NBA/WNBA Market-Only Entity, NBA Market-Only Board, Props Source-Time Freshness.

**Scorecard containment (scheduled, governed runner):**
- **Heartbeat marker:** unchanged across the whole run (yesterday the same step stamped it at 13:33:21).
- **Live-score:** 44 runs from 12:53 to 13:38, **0 provider polls**.
- **`/tmp` patterns:** `qc_lmstatus_*` roots 2 → 2 and logs 1 → 1 (historical, untouched).
- **Other new `/tmp` entries:** 23, all from inherited QCs (17 `dj_qc_*`, 5 `qc_*`, `qc_lens_attr.parquet`, 1 `bk*`).
- **Orphans:** 0.

**Run Status binding (`build_run_status`, read-only):**
- operator `finished_at` 2026-11-09T13:30:08, matching the summary mtime;
- Daily Operator row → `logs/daily_operator_20261109_130000.log` (FRESH, today's);
- Scorecards row → `logs/all_scorecards_20261109_131515.log`;
- overall DEGRADED, for the inherited reasons above plus line-movement MLB/WNBA failures (off-season).

**Service:** `bk-daily`'s out-of-repo `ExecStopPost` restarted the service at 13:30:12 (expected, unchanged
behaviour). NRestarts 0.

## 5. NBA props verdict through deployed `d7fbefa` (after `bk-daily` was terminal)

**Verdict on the published file:**

| Field | Value |
|---|---|
| `freshness_source` | **SourceUpdatedAtUTC** |
| `executable` | **True** |
| `prices_withheld` | False |
| `unavailable_reason` | None |
| `status` | live |
| `last_updated_utc` | 2026-11-09T13:05:10Z |
| `age_hours` | 0.56 |
| `clock_skew_seconds` | 0 |
| Executable frame | 987/987 rows; `future_rows_dropped` 0 |
| `props_feed_status("nba")` | executable True, source `SourceUpdatedAtUTC` |

**`LastUpdated` invariance:** the verdict is **IDENTICAL** with `LastUpdated` set to:
- the Eastern-misread future (+5h);
- far future (2099);
- garbage;
- removed entirely.

**Result:** no `future_timestamp`; the valid `SourceUpdatedAtUTC` governs; prices are executable straight after normal
publication; the zone-less `LastUpdated` cannot move the verdict.

## 6. Focused isolation checks (only what the scheduled run did not prove)

Run at 13:38:53–13:40:48Z, after confirming no `bk-*` unit was active.

- **Governed runner:** `nba_gated_market_facts` (not in the scorecard list) rc 0.
- **Self-isolation:** all 8 remediation QCs pass on prod with **no heartbeat override and the network blocked**:
  - props_source_time_freshness 23/23;
  - linemove 67/0/0 on Linux, including SIGTERM;
  - runner_exit_matrix 248 ok;
  - nba_wnba_props_stale 158/0;
  - the others rc 0.

  The real heartbeat was unchanged after every QC.
- **Orphans:** positive control detected; 0 orphans after.
- **`/tmp`:** 0 new entries (0 `qc_lmstatus_*`, 0 `qc_lmstatus_logs_*`).
- **Final state:** HEAD `d7fbefa`; 0 tracked changes; `venv/` `6d8eb94d…`; Research Candidate OFF; units/`.env` unchanged;
  service active; `/healthz` 200.

## 7. Heartbeat containment — final statement

- **Production scheduled scorecards:** contained (proven today: marker unchanged, 0 polls).
- **Remediation QCs:** self-isolated, with or without the runner.
- **All 14 inherited heartbeat-writing QCs:** contained only under the governed runner. Standalone invocation can still
  update the marker. **No claim of universal containment.**
- **Signed-in prewarm path:** not exercised today and not proven either way (§3).

## 9. Inherited obligations recorded at close (outside this release; see `PROGRAM_TABLE.md` I-1…I-5)

- **I-1 CFBD quota latch:** BLOCKED_QUOTA since 2026-10-24.
- **I-2 MLB/WNBA off-season handling:** `game_lines` exits 1 on NO_ACTIVE_EVENTS; WNBA NO_GOVERNED_REASON; line-movement
  MLB/WNBA FAILED in Run Status.
- **I-3 NBA board QC:** the `postseason_only` default and missing-playoff assumptions give "Live prop rows checked: 0";
  987 rows lack team mapping.
- **I-4 Legacy QCs:** 14 inherited QCs need the governed runner for heartbeat containment; standalone runs still stamp
  the real marker.
- **I-5 Prewarm:** the signed-in prewarm path is unverified.

## 10. Not done (by rule)

- No cleanup of: the 24 `be00c90`-gate leftovers, today's 23 inherited QC `/tmp` entries, the 45 historical roots, the
  32 historical log dirs, or the local Windows directory.
- No manual provider calls, refreshes, restarts, timer changes, rollback or extra deploy.
- Ledger documents remain uncommitted on `program/ledger`, off `master`.
