# Site Performance P0 — measurement matrix (closure evidence)

Two halves: the **server-side** half is measured and filled (prod, `perf_baseline_authed.py` +
`perf_dashboard_cold.py`); the **browser/CWV** half needs a logged-in Chrome session (DevTools +
Lighthouse) — fill the blanks and this becomes the closure sign-off.

## 1. Headline fixes — prod-confirmed (before → after)

| Route | Metric | Before | After | Evidence |
|---|---|--:|--:|---|
| **dashboard** | first user hit after refresh | **200,672 ms** | **79 ms** | 504-class → warm disk read |
| dashboard | forced cold rebuild | ~200 s | **10.1 s** | builder budget (no row-wise defects) |
| **injury-report** | payload / DOM rows | **835.7 KB / 1453** | **123.0 KB / 201** | server-side progressive disclosure |
| injury-report | warm server render | 172 ms | **115 ms** | — |
| **milestones** | cold (prewarmed) | 8,623 ms | **422 ms** | cross-process disk prewarm |
| **prop-floor** | cold (prewarmed) | 4,915 ms | **11 ms** | cross-process disk prewarm |
| **riding-the-wave** | cold | 11,900 ms | **1,667 ms** | N+1 → one grouped participation index |
| injury-report (earlier) | warm (every hit) | 63,745 ms | 167 ms | keyset cache keyed on mtime not id(df) |

Compression: prod serves **gzip** (confirmed live); **Brotli not enabled** (nginx — Phase-C note).
`Vary: Cookie` present; the injury fragment route sets `private, no-store`. **Zero 504s** on any route
in the baseline.

## 2. Server-side route baseline (prod, authed owner, in-process render)

`run1` = cold process (all caches empty = post-restart worst case); `med` = warm. Server render only —
NOT wire TTFB. From `perf_baseline_authed.py`, 2026-10-20 (post-prewarm run).

| Route | cold run1 (ms) | warm med (ms) | KB | rows | notes |
|---|--:|--:|--:|--:|---|
| dashboard | 78 | 11 | 72.0 | 0 | prewarmed (disk) |
| injury-report | 685 | 115 | 123.0 | 201 | progressive disclosure |
| milestones | 422 | 71 | 134.2 | 360 | prewarmed (disk) |
| nfl-props-floor | 11 | 10 | 58.9 | 2 | prewarmed (disk) |
| riding-the-wave | 1,667 | 115 | 72.7 | 48 | N+1 fixed; in-memory cache |
| heat-map | 2,222–5,255 | 11 | 78.9 | 34 | in-memory only (cold-process noisy) |
| nfl-matchup-edge | 3,656 | 42 | 87.9 | 60 | in-memory only (limit-key quirk; not disk-cached) |
| nfl-matchup | 1,153 | 373 | 172.4 | 1 | largest payload after injury-report |
| the-menu | 733 | 717 | 88.9 | 0 | **slowest WARM route** — candidate if matrix flags it |
| daily-card | 2,497 | 310 | 80.7 | 12 | cold worst; warm ok |
| player-check(NFL) | 361 | 361 | 60.8 | 3 | |
| sgp-workbench | 363 | 363 | 56.7 | 0 | |
| nfl-totals(wind) | 64 | 61 | 63.7 | 15 | |
| nfl-spots | 62 | 61 | 56.9 | 0 | |
| nfl-team(JAX) | 67 | 62 | 85.4 | 2 | |
| green-light | 49 | 46 | 73.9 | 0 | |
| login | 537 | 8 | 17.5 | 0 | |

**Server-side read:** warm medians are ≤400 ms everywhere except **the-menu (~720 ms)** — under the
≤800 ms complex budget but the lone warm outlier. The cold-*process* numbers (matchup-edge 3.7s,
heat-map noisy) are post-restart first-hits for the not-disk-cached boards; non-504, warm in ≤42 ms.

## 3. Browser / CWV half — CAPTURED (built-in browser, logged-in owner, prod, 2026-10-20)

Controlled **lab** measurements (not field p75): Navigation Timing + `largest-contentful-paint` /
`layout-shift` PerformanceObservers (buffered) + Event Timing for a real (trusted) interaction + DOM
node count. Desktop unless noted; 375px = mobile emulation. TTFB/LCP in ms.

| Route | TTFB | LCP | CLS | DOM | doc KB (gzip→decoded) | failed | redirects | notes |
|---|--:|--:|--:|--:|---|--:|--:|---|
| /dashboard | 598 | 784 | 0 | 1049 | 18.3 → 73.2 | 0 | 0 | disk-cached |
| /tools/injury-report | 921 | 1116 | 0 | 1207 | 22.4 → 96.0 | 0 | 0 | 50 rows; INP **56 ms** |
| /tools/injury-report (375px) | 782 | 1004 | 0 | 1207 | — | 0 | 0 | no horizontal scroll |
| /tools/nfl-milestones | 1159 | 1340 | 0 | 3296 | 22.9 → 135.8 | 0 | 0 | disk-cached; DOM-heavy board |
| /tools/riding-the-wave (cold) | 2569 | 2776 | 0 | 988 | — | 0 | 0 | first build (writes disk) |
| /tools/riding-the-wave (disk) | 357–379 | **508–524** | 0 | 988 | 18.3 → 73.8 | 0 | 0 | **disk-cached (new)** |
| /tools/nfl-heatmap (cold) | 6426 | 6580 | 0 | 1116 | — | 0 | 0 | first build (writes disk) |
| /tools/nfl-heatmap (disk) | 583 | **728** | 0 | 1116 | — | 0 | 0 | **disk-cached (new)** |
| /tools/menu | 2030 | 2152 | 0.003 | 1116 | 21.1 → 90.1 | 0 | 0 | aggregates many builders; not disk-cached |
| /tools/nfl-matchup | 1221 | 1424 | 0 | 2046 | 39.1 → 173.8 | 0 | 0 | largest payload |
| /tools/sgp-workbench | 843 | — | — | 627 | — | 0 | 0 | "No legs yet" (no live plays to add) |

**Interactions exercised (trusted input where noted):**
- Injury **search/filter** — INP **56 ms** (real keystrokes); server-side filter faithful.
- Injury **Load More** — 50→100 rows appended, ~755 ms (incl. prod round-trip); "showing X of N" advanced.
- **Entity link** — `/tools/nfl-team?team=SEA` resolves to the real "NFL Team ATS Trends" page.
- **Riding-the-Wave / Heat Map** — pages interactive; cold→disk transitions measured above.
- **SGP leg** — not exercisable: no live NFL plays to add at capture time (data state, not perf).

**Budgets:** LCP ≤2.5 s · INP ≤200 ms · CLS ≤0.1 · no multi-MB HTML · no 504s · warm TTFB ≤800 ms.
**Result:** CLS ≤0.003 everywhere, 0 failed resources, 0 redirects, INP 56 ms, no 504s. All LCPs pass in
the disk-cached/warm state. The only >2.5 s LCPs are the **first-ever build** of a board (writes the disk
artifact; the scheduled prewarm pre-writes it so no user pays it) — proven by wave (2776→516) and
heat-map (6580→728). Compression: doc transfer ≈ ¼ of decoded = **gzip active**; Brotli off (Phase-C).

### Heat Map cold — RESOLVED
The one-off 5.3 s was cold-PROCESS noise (one-time parquet load). Repeated builder measurement (warm
process, cache-miss ×5): **median 1.9 s, worst 2.6 s** — over budget at worst. Fixed two ways: (1)
`build_nfl_hot_hand` now caches the full set + slices at return (also fixing a first-caller-wins
`limit`-key quirk) and writes a disk artifact; (2) added to the prewarm. Browser: cold 6.58 s → disk 0.73 s.

### Injury Report initial record count — CLARIFIED + reduced
"201" was a DOM `<tr>` count: **100 data records + ~100 hidden "impact" expansion rows** (present only
for displayed NFL players with with/without data that day) **+ 1 header**. Data records were always ≤
page size. Default reduced to **50** (conservative end of the 50–100 target); user-selectable via
`?page_size` (clamped 10–100). All 1,453 reachable; membership parity + no-JS Prev/Next + keyboard
toggles verified. 375px: no horizontal scroll, LCP 1.0 s.

## 4. Integrity regression status (must stay green for closure)

All verified by QC in `run_all_scorecards` — **no data removed, order/membership identical, gates intact**:
- `qc_injury_report_progressive` — paged membership complete + page-size-independent; filters faithful.
- `qc_perf_guards` (Guards 1–7) — cache stability, wave index reuse+parity, de-arrow parity, dashboard
  vectorization == original per-row funcs, NFL disk artifacts stable-keyed + byte-identical.
- `qc_nfl_milestone_streaks`, `qc_nfl_wave_season_injury`, `qc_nfl_identity_resolution`,
  `qc_entity_links`, `qc_nfl_floor_cache`, `qc_nfl_inclusion_parity` — all green.
- NBA data-rights gate (`BK_NBA_STATS_ENABLED=0`) unchanged; SGP handoff (`a94cbf9`) still isolated.

## 5. Routes still exceeding budget — explicit disposition
- **the-menu** — LCP 2.15 s (CLS 0.003), *under* the 2.5 s budget but the slowest page; aggregates many
  builders and is not disk-cached. **Disposition:** within budget; monitor. Candidate for the same
  disk-materialization if it regresses past 2.5 s.
- **nfl-matchup-edge** — ~3.7 s on a cold worker (42 ms warm); not disk-cached because `build_nfl_usage_board`
  applies `limit` inside the cached payload but not in the key (first-caller-wins quirk). **Disposition:**
  the correct fix is the same cache-full-slice-at-return refactor applied to hot-hand; deferred as a
  scoped follow-up (cold-worker-only, non-504). Not a closure blocker.
- First-ever-build LCPs (wave 2.78 s, heat-map 6.58 s) are eliminated for users by the scheduled prewarm
  that pre-writes the disk artifact; the warm/disk LCPs (0.51 s / 0.73 s) are what users see.

## 5b. Operational prewarm (survives refreshes + deploys — no manual run)

The disk prewarm is wired into both lifecycle events and carries an application schema version so a
deploy invalidates stale artifacts:

- **Source refresh** (fingerprint change) → `run_daily` runs `refresh_runtime_snapshots.py --prewarm-only`
  as its LAST step (after grading + scorecards); the NFL **post-week** ops script re-warms after the
  parquet advances.
- **Deploy** (schema change) → `bk-auto-deploy.sh` runs `--prewarm-only` **post-restart**, synchronously,
  before reporting success. **Documented choice — post-restart, not before:** the artifacts must be
  rebuilt by the NEW code at the NEW schema; warming before the restart would publish artifacts the new
  workers reject. Runs as the `ubuntu` service user, no upstream network, no user data, time-bounded
  (300 s); a warm failure is logged LOUDLY (never a silent cold deploy) and does not fail the deploy.
- **Schema version** — `APP_CACHE_VERSION` is folded into `_build_file_token` (dashboard/promotion + every
  token-keyed cache) and stamped as an explicit `app_version` field on the NFL board artifacts. Bump it
  whenever a cached builder's output shape changes; the next restart rejects old-schema artifacts.
- **Hardening** — atomic publish (`temp(.tmp-<pid>)` + `fsync` + `os.replace`), `0600` perms, fail-closed
  reads (corrupt / incomplete / wrong-schema / wrong-fingerprint → rebuild).
- **Receipt** — `prewarm_receipt.py` (run as the service user) rebuilds each artifact and prints a
  sanitized per-artifact line: fingerprint (short hash, not contents), schema, build ms, path category,
  size, atomic method, validation, perms, status; exit non-zero if any fails.
- **Invariants proven** — `qc_prewarm_lifecycle.py`: source-version change → rebuild; app-version change →
  rebuild; unchanged inputs → reuse; corrupt/incomplete/wrong-schema → fail closed; atomic (no partial
  reads, last complete write wins, crashed-writer temp isolated). `qc_sgp_workbench.py` t15 = deterministic
  populated-fixture leg-interaction perf (evaluate() deterministic + <25 ms/call), since the prod
  workbench had no live legs.

**Manual ops step (both `bk-*` wrappers live outside the repo):** after prod pulls, reinstall the deploy
wrapper so the post-restart warming takes effect:
`sudo install -m 755 ops/bk-auto-deploy.sh /usr/local/bin/bk-auto-deploy.sh`.

## 6. Closure checklist
- [x] No 504s; 0 failed resources; 0 redirects (all captured routes).
- [x] Membership/order parity (QCs: injury progressive, perf guards 1–7, milestone/wave/floor/identity).
- [x] gzip confirmed on prod (`Content-Encoding: gzip`); Brotli off → Phase-C nginx note.
- [x] Auth/plan gates intact (page + injury fragment in PRO_ENDPOINTS); NBA gate unchanged; SGP isolated.
- [x] CLS ≤0.003, INP 56 ms, LCP passes warm/disk on every route; mobile 375px clean (no h-scroll).
- [x] Heat Map cold resolved (disk-cached: 6.58 s → 0.73 s); Injury initial records = page size (now 50).
- [x] **Operational prewarm verified on prod (2026-10-20):** receipt = ALL ARTIFACTS OK (NFL boards 0600,
      atomic, validated, distinct fingerprints); fresh-process baseline reads the prewarmed artifacts within
      budget — **riding-the-wave 1,667→126ms, heat-map 2,222→13ms, prop-floor 10ms, milestones 426ms,
      dashboard 390ms**. Lifecycle wiring installed (deploy wrapper reinstalled; run_daily + post-week warm).

## 7. SITE PERFORMANCE P0 — CLOSED (2026-10-20)
Both 504-class routes fixed (dashboard 200,672→79ms; injury-report 835.7KB→~95KB), four NFL boards
disk-materialized + prewarmed (wave/heat-map/floor/milestones all sub-second on a fresh process), the
prewarm is operational across refresh + deploy with a schema version, receipt, and proven invariants.
Lab matrix: CLS ≤0.003, INP 56ms, no 504s, 0 failed resources, gzip confirmed.

**Monitored follow-ups (non-blocking):** (1) Matchup-Edge `limit`-in-key quirk → the first follow-up
(same cache-full-slice fix applied to hot-hand). (2) `the-menu` warm ~720ms (under budget; aggregates many
builders). (3) `player-check` ~3.5s cold rebuild (the known "cache /player shared feeds on signature"
item; one-time per worker after a schema bump / daily refresh). (4) Brotli on nginx (Phase-C).
