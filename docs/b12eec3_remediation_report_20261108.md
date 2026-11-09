# `b12eec3` remediation report (2026-11-08) — FINAL RECORD (accepted as d7fbefa; see production receipt)

**Branch:** `fix/b12eec3-qc-remediation` (local; never pushed).
- First commit: `0c04f40`.
- The successor SHA is recorded at the end of this report.

**Scope:** frozen by the owner to:
- the three QCs that failed in production;
- one production defect introduced by `b12eec3` (NBA props freshness).

Two items are inside scope as direct consequences of the accepted fix:
- four older QCs that encoded the superseded timestamp contract;
- a heartbeat redirect confined to the already-remediated entity QC.

**Excluded:** all inherited items, Green Light and the doctrine work.

## 1. Accepted defects — root cause and fix
| # | Defect | Classification | Root cause | Fix |
|---|---|---|---|---|
| D1 | NBA prop prices withheld ~5h after each publication | **Real production defect, introduced by `b12eec3`** | The central gate (`props_executable_meta` / `_drop_future_rows`) read the zone-less `LastUpdated` fetch stamp as an Eastern wall clock. On prod it is UTC, so 13:08Z read as 18:08Z (`future_timestamp`, skew 14,283 s) | Freshness, age, label and skew come **only** from the zone-explicit `SourceUpdatedAtUTC`. Missing / zone-less / malformed means `no_timestamp` (fail closed). Rows without a valid source time, or beyond +5 min, are dropped. No zone is ever guessed; the 6h rule is unchanged |
| D2 | Line-Movement Status Persistence QC `ValueError` on prod | QC isolation defect | `generate_run_status.LOG_DIR` is bound at import; the QC redirected `BASE_DIR` only, so the real operator log leaked in | Every Run Status build reads an empty QC-owned `LOG_DIR`; new hermetic check |
| D3 | Runner Exit Matrix QC "missing API key" case FAILED on prod | QC isolation defect / production-environment assumption | Importing `fetch_game_lines` runs `load_local_env(<checkout>)`, which restored the key the QC had dropped; on prod a real WNBA request was made (13:19:49Z, **0 credits**, proven from the live-score balance sequence) | Network blocked before the import (tripwire); key dropped **after** the import and asserted absent; per-case no-network check. Exit-code semantics unchanged (built-in M1–M8 still caught) |
| D4 | Market-Only Entity QC failed on prod | Production-environment assumption, which exposed D1 | The QC patched the loaders but not the raw feeds that `props_feed_status` reads; on prod it graded the real feeds (WNBA stale, NBA misread) | Raw loaders isolated with fresh fixtures; real feeds never read |
| D5 | Same QC stamps the **real** activity heartbeat | QC isolation defect (in scope: confined to a remediated QC) | Signed-in test requests: `inject_globals` → `record_active_user()` → `DATA_DIR/live_scores/active_user_heartbeat.txt` | Marker redirected to a QC-owned temp dir; real marker proven unchanged (bytes + mtime) |
| D6 | Four older QCs failed after D1 | Stale QC expectations encoding the superseded contract | Fixtures carried only a zone-less `LastUpdated`, or (`nba_market_only`) `last_update` at bookmaker level, whereas the provider sends it at market level (2026-10-31 raw diagnostic: 23/23 market-level, 0/3 bookmaker-level) | Fixtures carry the explicit `SourceUpdatedAtUTC` (same instant) and keep `LastUpdated` as a decoy. "Naive Eastern stamp ages correctly" replaced by "zone-less source stamp → `no_timestamp`" |

### D6 detail (owner request)
| QC | Exact failing assertion | Old contract | New contract | Why it is stronger | Proving mutation |
|---|---|---|---|---|---|
| `nba_gated_market_facts` | `facts available with a populated feed` → `KeyError 'quote_rows'` | A fresh zone-less `LastUpdated` (Eastern) makes the feed executable | Only `SourceUpdatedAtUTC` makes it executable | The fixture now matches the real producer; the decoy `LastUpdated` stays present | M8 (gate ignores source) caught |
| `nba_market_only` | 0 rows (want 2); parser rows `[]`; NBA/WNBA board renders empty | Same; plus `last_update` at bookmaker level | Explicit source; market-level `last_update` → `SourceUpdatedAtUTC`; the 2099 / blank tests target the source column | Future / missing tests now hit the governing field, not a decoy | M1 caught (1), M8 caught (15) |
| `nba_wnba_props_stale` | Boundary 5h59/6h01; "naive Eastern stamp ages correctly"; skew +3/+5/+5:01; row-level +30 min; skew label | Zone-less stamps are Eastern and age correctly | Explicit UTC ages correctly; **zone-less → `no_timestamp`**; skew/rows read the source; misleading `LastUpdated` decoy present | Adds a fail-closed assertion the old QC lacked; the decoy proves `LastUpdated` cannot move the verdict | M1 caught (8), M8 caught (85) |
| `quick_tools` | Best-lines / risk-radar / slate-pulse fresh synthetic NBA/WNBA did not render | Zone-less `LastUpdated` freshness | Explicit source freshness | The rendering controls stay meaningful under the new gate | M8 caught (3) |

M1 is not distinguishable in `nba_gated_market_facts` or `quick_tools`. Their `LastUpdated` is true Eastern time, consistent with the source. They are rendering tests; the authority contract is owned by `qc_props_source_time_freshness`, `nba_wnba_props_stale` and `nba_market_only`.

## 2. Before / after proof of D1 (read-only copy of today's production `NBA_Props.csv`)
- **Copy:** sha256 `9b0b7e56…` (868 rows), a subset of the published file `f8ac60db…`.
- **Timestamps in the file:** `LastUpdated` = "2026-11-08 13:08" (zone-less); `SourceUpdatedAtUTC` from 13:06:41Z to 13:08:05Z.

| now (UTC) | `b12eec3` | remediation |
|---|---|---|
| 13:10 | `future_timestamp`, withheld, `last_updated_utc` 18:08:00Z, 0 rows | **executable**, 13:08:05Z, age 0.03h, 868 rows |
| 14:00 | `future_timestamp`, withheld, 0 rows | **executable**, age 0.87h, 868 rows |
| 19:20 | executable (wrongly; age frozen at 1.19h) | **stale** (6.2h), withheld, never future-dated |

## 3. Mutation proofs (all CAUGHT)
- **M1** LastUpdated governs again → `qc_props_source_time_freshness` (15 FAIL).
- **M2** untimed rows stay executable → 1 FAIL.
- **M3** stale wall-clock warning left → 2 FAIL.
- **M4** 6h loosened to 24h → 2 FAIL.
- **M5** Status Persistence reads checkout `logs/` → 1 FAIL.
- **M6** key dropped before import → 3 FAIL (network tripwire fired, blocked).
- **M7** entity raw loaders not isolated → 1 FAIL.
- **M8** gate ignores the source → caught in all 4 revised QCs.
- **M9** entity heartbeat redirect removed → "REAL activity heartbeat … written by this QC".

## 4. Heartbeat trace and containment proposal (scope-change request — NOT implemented beyond D5)
**Trace:**
- **Writer:** `record_active_user()`, throttled to 20 s, writes `DATA_DIR/live_scores/active_user_heartbeat.txt`.
- **Callers:**
  - `inject_globals` (the context processor on every rendered template for a signed-in user);
  - `/api/live-ticker`.
- **Execution:** QC requests run **in-process** through the Flask test client, not the live service. The marker
  path is the checkout's real `data/live_scores/`.
- **Who reads it:** the poller `refresh_live_scores.py` reads the same path (heartbeat ≤ 120 s ⇒ a paid
  `/scores` call while a window is open).
- **When it happens:** both in ordinary offline gates (dev box: the local marker, read by the local "Live Scores"
  scheduled task with a separate key) and in production scorecards (the real marker).
- **QCs affected:** 18 QC files open a signed-in test client. Only `qc_nba_market_only`, `qc_nba_wnba_props_stale`
  and `qc_quick_tools` (and now `qc_entity_nba_wnba_market`) redirect `app.ACTIVE_USER_HEARTBEAT_PATH`.
  Inherited, not redirected:
  - `research_candidate_route`
  - `parlay_save_exact`
  - `game_lines_freshness`
  - `ticket_quote_change`
  - `game_lines_event_slate`
  - `ticket_submission_atomic`
  - `universal_tool_hubs`
  - `platform_routes`
  - `plan_access_matrix`
  - `nba_residual_authority`
  - `mlb_visual_trust`
  - `mlb_readiness`
  - `membership_regression`
  - `legal_containment`
  - `cfb_wave_wording`
  - `cfb_readiness`
  - `cfb_matchup_total`

  Some may already redirect through `DATA_DIR`; verify each before scoping.
- **Production evidence 2026-11-08:**
  - Live-score polls ran **every minute 13:18:28 → 13:33:32** (16 polls = **32 credits**), coinciding with
    `run_all_scorecards` (log 13:17:22, run exit 13:33:31).
  - The morning baseline showed only 7 user-driven polls in 4.5h.
  - The marker keeps only its last value, so per-poll attribution to a specific QC is **not provable**. The writer
    class is proven (code + empirical: the entity QC rewrote a local marker).
- **Classification:** inherited production-test side effect; cost-bearing.

**Containment options:**
| Option | Change | Proves | Risk |
|---|---|---|---|
| **A (recommended)** | The QC **runners** (`run_all_scorecards.py`, `qc_offline.py`) set a process env `BK_ACTIVE_USER_HEARTBEAT_PATH=<temp>` for every child QC. `app.py` builds `ACTIVE_USER_HEARTBEAT_PATH` from that env when present, else the current default | Scorecards and offline gates can never touch the real marker → no QC-triggered paid polls. Real requests are unchanged (the service env never sets it). A **request cannot** set a process env, so QC mode cannot be impersonated | 2–3 files. Covers all current and future runner-launched QCs; a QC launched by hand outside the runners is not covered |
| B | Suppress `record_active_user()` when the request is a Werkzeug test request (non-HTTP WSGI environ marker) | Same, plus manual runs | Behavior change in the request path; relies on an environ marker semantic |
| C | Patch all 17 inherited QCs individually (like D5) | Same per QC | Broad, error-prone, misses future QCs |

**Recommendation:** A. Proof plan:
1. Run the scorecards on a copy with the marker hashed before and after: unchanged.
2. Mutation: drop the env injection → marker changes → caught.
3. A real signed-in request in a non-QC process still stamps the default marker.
4. A static check that the production service units do not set the env.

Owner approval is needed: this is a scope change beyond the frozen remediation.

## 5. Gates
**Git state**
- **Remediation:** worktree `.claude/worktrees/b12eec3-qc-remediation`, branch `fix/b12eec3-qc-remediation`, base
  `b12eec3`.
  - `0c04f40`: product fix and the three QC fixes.
  - **`520bc8d` (production successor)**: fixture updates and the entity heartbeat redirect.
  - Not pushed. 10 files changed against `b12eec3`, **0 under `docs/`**.
- **Ledger:** worktree `.claude/worktrees/jolly-ishizaka-c6519a`, branch `program/ledger`, HEAD `d204bc2`
  (local; `origin` at `ba19461`).
  - All 2026-11-08 evidence and doctrine documents are **uncommitted** there, never part of the production diff.

**Results**
- **Baseline gate on `0c04f40`:** 80 QCs, 4 failed (the four D6 QCs, superseded contract), compile OK, clean
  before and after.
- **Repeat runs with prod-like `.env`, `logs/`, props feeds, heartbeat, `data/tracking`, `data/odds` present:**
  - `props_source_time_freshness` 10/10;
  - `entity_nba_wnba_market` 10/10;
  - `linemove_status_persistence` 10/10;
  - `runner_exit_matrix` 5/5;
  - `nba_gated_market_facts` 10/10;
  - `nba_market_only` 10/10;
  - `nba_wnba_props_stale` 5/5;
  - `quick_tools` 5/5.

  That is 65/65 with 0 flakes, and **0 protected files changed** (byte and mtime).
- **Full gate on `520bc8d`:** 80/80 pass, `COMPILE_OK`, `qc_odds_feed` correctly refused (rc 3,
  `REQUIRES_NETWORK`), tree clean before and after, 716 s.
- **Sentinel heartbeat: CHANGED.**
  - Before: sha `ca0cd346…`, mtime 1700000000.
  - After: content `1794161449`.
  - **Stopped here per owner rule.** The writers are inherited gate QCs, not remediation QCs.

**Heartbeat inventory** (each QC run alone against a sentinel)
- **Write the real marker and run in prod scorecards (14):**
  - `cfb_matchup_total`
  - `entity_link_crawl`
  - `entity_links`
  - `game_lines_event_slate`
  - `game_lines_freshness`
  - `green_light_workspace`
  - `injury_report_progressive`
  - `legal_containment`
  - `lookup_change_views`
  - `lookup_facts_context`
  - `nba_residual_authority`
  - `nfl_matchup_center`
  - `nfl_weather_venue_integrity`
  - `ticket_editor_shared`
- **Write it but are not in scorecards:**
  - `cfb_board`
  - `cfb_readiness`
  - `mlb_readiness`
  - `nfl_board`
  - `plan_access_matrix`
  - `platform_routes`
  - `research_candidate_route`
  - `universal_tool_hubs`
  - `unpriced_line_legs`
- **Unchanged:** the remediated `entity_nba_wnba_market`, plus `cfb_wave_wording`, `membership_regression`,
  `mlb_visual_trust`, `parlay_save_exact`, `sgp_kickoff_gate`, `ticket_kickoff_gate`, `ticket_quote_change`,
  `ticket_submission_atomic`.
- **Gate members among the writers:** `unpriced_line_legs`, `lookup_change_views`, `nfl_board`, `cfb_board`,
  `game_lines_freshness`, `green_light_workspace`, `nfl_weather_venue_integrity`, `game_lines_event_slate`,
  `ticket_editor_shared`.
- **The wider heartbeat incident is NOT contained.** Containment needs the §4 scope decision.

## 6. Heartbeat containment — Option A (owner-approved 2026-11-08; containment and verification only)
**Commit:** `be00c90` on `fix/b12eec3-qc-remediation` (parent `520bc8d`). Files: `app.py`, `run_all_scorecards.py`,
`qc_offline.py`.

- `app.py` honors `BK_ACTIVE_USER_HEARTBEAT_PATH` only when it is an absolute path. Absent means the existing live
  path.
- Each runner gives every QC process its own temp directory and override, and removes it afterwards.
- It is a process environment variable, so no request can set it. No repo unit or `.env` references it.

**Verification**
- A sentinel live marker stayed byte- and mtime-identical through both runners, for a probe and for a known writer
  (`qc_game_lines_freshness`).
- The probe proved the runner's temp marker **was** stamped (`stamped=True`).
- Without a runner, the known writer still stamps the live path, so genuine behavior is unchanged.

**Mutations (all CAUGHT; the real marker changed in each)**
- H1: `qc_offline` stops injecting the override.
- H2: `run_all_scorecards` stops injecting the override.
- H3: `app.py` ignores the override.

**Scope note (owner):** a **standalone** QC invocation outside these two runners does not receive the override. When
it is run against production-like data, it must set `BK_ACTIVE_USER_HEARTBEAT_PATH` to a temporary absolute path
first.

## 7. Isolated Linux gate on `be00c90` (2026-11-09, via git bundle, no origin push)

Delivered through the existing SSM path (command `d8bb79b9-fb4d-47c0-aec4-81501b553105`, status Success). The code
arrived as a git bundle (`b12eec3..be00c90`, sha256 `64df4458…ecff`) and was checked out in a throwaway clone
under `/opt/bankrollkings-runtime/qcgate.*` (ext4, Python 3.12.3). The temp directory was removed on exit. The
production checkout, service, timers, `.env` and data were only read.

| Check | Result |
|---|---|
| Exact SHA | `be00c90dc9478096e08bf23570eea2262a185744`, IDENTITY_OK (matches the local branch tip) |
| Scope vs `b12eec3` | 11 files, 0 under `docs/` |
| Clean tree, before and after | yes / yes |
| Override references in prod `.env` and in systemd units | 0 / 0 |
| Compile (`app.py`, the runners, the remediated and revised QCs) | COMPILE_OK |
| Offline QC loop | 80 run, 0 failed |
| `qc_odds_feed` | rc 3 (declares REQUIRES_NETWORK; not an offline QC), as expected |
| Process-zone checks | identical verdicts under `TZ=America/New_York` and under `TZ=America/Los_Angeles` as under `TZ=UTC`; freshness QC 23 passed, 0 failed |
| Heartbeat sentinel | sha `ca0cd346…81d6`, mtime 1700000000, before and after: UNCHANGED |
| Duration | 467 s |

The branch remains unpushed. Nothing was deployed.

## 8. Superseded: `be00c90` and `0b292a4` — final candidate `d7fbefa` (2026-11-09)

- `be00c90` leaked one `qc_lmstatus_logs_*` directory per run.
- `0b292a4` still left the inherited per-run `qc_lmstatus_*` root.
- `d7fbefa` gives the line-movement QC one owned, guarded, guaranteed-cleanup root.

Neither earlier SHA is to be deployed. The final lineage, exact diff, final-SHA evidence (80/80 local and Linux, M1–M9,
cleanup mutations, repeats, H1–H3, process-leak checks), host cleanup proof and heartbeat statement are in
`docs/b12eec3_successor_d7fbefa_deployment_packet_20261109.md`.
