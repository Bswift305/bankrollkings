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

## 3. Browser / CWV half — TO CAPTURE (logged-in Chrome)

For each route below: open logged in, DevTools → **Network** (Disable cache OFF for warm, ON for cold;
record Transfer + Requests + any 4xx/5xx + redirects), **Performance/Lighthouse** for LCP/INP/CLS, and
**Elements** or `document.querySelectorAll('*').length` for DOM nodes. Run **desktop** and **throttled
375px mobile** (DevTools device toolbar + "Slow 4G"/CPU 4×). 3 cold + 3 warm; record median + worst.

Priority routes (highest impact / most changed): `/dashboard`, `/tools/injury-report`,
`/tools/nfl-milestones`, `/tools/riding-the-wave`, `/tools/menu`, `/sports/nfl` matchup, plus a spot
check of `/tools/nfl-matchup-edge`.

| Route | TTFB | total load | requests | transfer | LCP | INP | CLS | DOM nodes | 375px ok? | HTTP errs | redirects |
|---|--|--|--|--|--|--|--|--|--|--|--|
| /dashboard | | | | | | | | | | | |
| /tools/injury-report | | | | | | | | | | | |
| /tools/injury-report (Load More ×2) | | | | | | | | | | | |
| /tools/nfl-milestones | | | | | | | | | | | |
| /tools/riding-the-wave | | | | | | | | | | | |
| /tools/menu | | | | | | | | | | | |
| NFL matchup | | | | | | | | | | | |

**Budgets (pass/fail):** LCP p75 mobile ≤2.5 s · INP ≤200 ms · CLS ≤0.1 · no multi-MB HTML · no 504s ·
0 external API calls on a request path · warm TTFB ≤500 ms pref / ≤800 ms complex.

**Injury-report specific checks:** confirm the default page is ~100 rows (not 1,453); Load More appends
and the "showing X of N" count advances; filters change the URL (GET) and survive a reload; with JS
disabled the Prev/Next links page the table; keyboard can reach the "impact" toggles and the pager.

## 4. Integrity regression status (must stay green for closure)

All verified by QC in `run_all_scorecards` — **no data removed, order/membership identical, gates intact**:
- `qc_injury_report_progressive` — paged membership complete + page-size-independent; filters faithful.
- `qc_perf_guards` (Guards 1–7) — cache stability, wave index reuse+parity, de-arrow parity, dashboard
  vectorization == original per-row funcs, NFL disk artifacts stable-keyed + byte-identical.
- `qc_nfl_milestone_streaks`, `qc_nfl_wave_season_injury`, `qc_nfl_identity_resolution`,
  `qc_entity_links`, `qc_nfl_floor_cache`, `qc_nfl_inclusion_parity` — all green.
- NBA data-rights gate (`BK_NBA_STATS_ENABLED=0`) unchanged; SGP handoff (`a94cbf9`) still isolated.

## 5. Open before closure
- **#3 deep-optimize** — conditional: only if the browser matrix flags a real customer problem
  (candidates: `the-menu` warm ~720 ms; the usage/hot-hand `limit`-in-key quirk; matchup-edge 3.7s cold).
- **#4 browser matrix** — fill §3 on desktop + 375px, logged in. Then this doc is the closure evidence.
