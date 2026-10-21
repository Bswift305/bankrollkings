# Site Performance P0 — Phase A baseline + ranked bottleneck table

## Phase B results — confirmed on prod (before → after)

| Route | Before | After | Factor | Commit |
|---|---|---|---:|---|
| **injury-report** (slow on EVERY hit → 504) | 63,745 ms warm | **167 ms warm** | ~375× | `9507e4e` (QW1) |
| **milestones** (cold build → 504 risk) | ~54,000 ms cold | **7,700 ms cold** | ~7× | `17edb8e` (QW2) |
| **riding-the-wave** (N+1 per player) | 11,900 ms cold | **4,463 ms cold** | ~2.7× | `ed0a473` (B2) |
| **dashboard** (200s cold → 504 after every refresh) | 200,672 ms | **79 ms** (user-facing) | ~2,500× | `6dd5a68`+`eb54a4f` |
| **injury-report** (835KB to every visitor) | 835.7 KB / 1453 rows | **123.0 KB / 201 `<tr>`** | ~6.8× | `5c215ae` |

### Injury Report — prod-confirmed (2026-10-20), progressive disclosure CLOSED
Server-side filtering + pagination; default page = 100 most-severe rows. Prod before→after:
**835.7 KB → 123.0 KB** payload, DOM `<tr>` **1453 → 201**, warm render **172 ms → ~115 ms**. Membership
proven complete + page-size-independent (`qc_injury_report_progressive`); filters faithful; no-JS
fallback; auth gated on page + fragment. Prod serves **gzip** (confirmed; Brotli NOT enabled → Phase-C
nginx note). Remaining for this item: CWV/INP/CLS + 375px from a logged-in browser (P4 matrix).

### Dashboard — prod-confirmed (2026-10-20), CLOSED
- `build_player_hit_profiles` forced recompute: **340s → 2.3s** (161k rows, 10,880 profiles).
- Full `build_phase2_dashboard_context` forced cold build: **~200s → 10.1s** (the real standalone budget;
  no row-wise defects, dominated by legit CSV I/O + aggregation).
- Warm read: **0.2 ms**. User-facing `/dashboard` run1 in a fresh process (reads the prewarmed disk
  pkl): **200,672 ms → 79 ms**. Meets cold ≤2s / warm ≤800ms; no 504; membership/order byte-identical;
  NBA gate untouched.

## Phase B2 #2 — safe prewarm of the remaining NFL cold builders (`9fc25d3`)

The NFL tool caches are **in-memory per gunicorn worker**, so a batch prewarm process cannot warm live
workers (unlike the dashboard's disk pkl). The two worst (milestones ~8.6s, floor ~4.9s cold) now also
keep a **cross-process disk cache** keyed on a **process-stable** signature (NOT a `hash()` of it —
`PYTHONHASHSEED` would make the key differ per process and never match):
- `_nfl_disk_cache_load` / `_nfl_disk_cache_store` (atomic temp+replace, backstop TTL, picklable version).
- milestones: cold 5.7s → **disk-warm 0.048s** (local), byte-identical; floor: 2.4s → **0.017s**, per-param
  artifacts independent.
- `refresh_runtime_snapshots --prewarm-only` warms them (`prewarm_nfl_tool_caches`); the NFL **post-week**
  ops script re-warms after the parquet advances. Warming is attached to the jobs that actually
  invalidate each cache (run_daily = props/injuries/date; post-week = parquet), not the daily job blindly.
- **Deliberately NOT disk-cached:** usage/matchup-edge + hot-hand ("Heating Up") apply `limit` inside the
  cached payload but not in the key (pre-existing first-caller-wins quirk) — disk-caching with a prewarm
  default limit would change what other callers see. Left in-memory (non-504, warm after first hit).
  Fixing the limit-key quirk is a separate correctness change (candidate for #3 only if measured as a
  customer problem).
- `qc_perf_guards` Guard 7 proves the artifacts are stable-keyed + read back byte-identical.

**Prod-confirmed (2026-10-20):** prewarm did the real cold build (milestones 8.9s, floor 4.6s) and
persisted; the next fresh process read the artifacts — **milestones 8,623ms → 422ms**, **prop-floor
4,915ms → 11ms**. (Non-disk-cached `heat-map` bounced 2.2s→5.3s cold-process = noise, unchanged code,
11ms warm.)

**Manual ops step (like the other `bk-*` units):** the post-week wrapper changed, so after prod pulls,
reinstall it: `sudo install -m 755 ops/bk-nfl-postweek-refresh.sh /usr/local/bin/bk-nfl-postweek-refresh.sh`.

## Phase B2 — the dashboard (the only remaining 504-class route)

**Dashboard `/dashboard` — ~200s cold → warm (de-arrow + vectorize + batch prewarm).** Prod tottime
profiling pinned the ~200s cold build — paid by the first visitor after every daily refresh, since the
disk-TTL cache keys on the `*_AllPropResults.csv` + `*_99_Scorecard.csv` that grading+scorecards rewrite
— to row-wise work in `services/review_center.py`:
- **`build_player_hit_profiles`** — 340s self-time was pyarrow string boxing (pandas 2.2 `infer_string`
  → `string[pyarrow]`, scalar-accessed in a 10,880-group loop). `6dd5a68`: `_dearrow_string_columns`
  at the load boundary + before the per-group loop (values unchanged). `eb54a4f`: per-group loop
  vectorized to numpy-array slices. **340s → ~5s.**
- **`enrich_candidate_review_rows`** — iterrows + per-row `.at` over every Miss row → array path
  (`_failure_from_values`), `eb54a4f`. **15.1s → 1.3s** local.
- **`_missed_winner_candidates`** — `promoted.iterrows()` + `available.apply(_missed_prop_key)` →
  `_missed_keys()` (zip raw arrays, same `str(x or '')` NaN semantics). **6.7s → 1.8s.**
- **`build_missed_opportunities_context` / `build_missed_winner_bucket_frequency`** —
  `.apply(calculate_missed_opportunity_grade, axis=1)` → `_grade_missed_frame()` (numeric cols coerced
  once; scalar `_grade_values`).
- Full cold build **46s → 18.8s local** (prod additionally sheds the ~340s arrow penalty). Every change
  byte-parity-verified vs pre-change baselines; `qc_perf_guards` Guards 5–6 lock de-arrow parity + the
  equivalence of all vectorizations to the original per-row functions on a NaN/edge frame.

**Batch prewarm (`6dd5a68`).** Root architectural gap: `prewarm_expensive_pages()` existed but ran with
`--skip-prewarm` AND before grading/scorecards, so the dashboard cache was never warmed for its final
file versions. Added `refresh_runtime_snapshots.py --prewarm-only` (warms the dashboard disk-TTL caches
by calling the builders directly — no HTTP/session/auth) wired as the LAST `run_daily` step, after
scorecards. Builder failures are non-fatal. With the builder now at a genuine ~20s standalone budget
(no row-wise defects hidden behind the prewarm, per the directive), the user-facing cold path becomes a
warm disk read.

**Prod verification (pending paste):** `perf_dashboard_cold.py` (forced recompute — proves the builder
budget), `refresh_runtime_snapshots.py --prewarm-only` (proves the batch step), `perf_baseline_authed.py`
(fresh-process `/dashboard` run1 ≤2s = warm disk hit).

- **QW1** — `_entity_player_keyset` for NBA/WNBA/MLB keyed on `id(df)`, but the gamelog loaders return
  a `.copy()`, so the keyset rebuilt over the whole gamelog on every `entity_anchor` call
  (1,479 rows × 2 links). A regression from the entity-link migration; now keyed on the gamelog FILE
  mtime (+ gate state), matching NFL. Same membership/ordering/gating; `qc_entity_links` green.
- **QW2** — `build_nfl_milestone_streaks` sorted every (player, opponent)/(player, stat) group
  individually (56,847 `sort_values`, 52 s) + re-read columns per (stat, threshold). Now sorts once,
  iterates pre-sorted groups over plain lists, pre-filters tiny groups, computes availability lazily.
  Same output; `qc_nfl_milestone_streaks` green.
- Regression guard: `qc_perf_guards.py` (keyset cache-stability, cheap per-row resolve, milestone warm
  cache) — structural invariants against the per-row-rebuild class, in `run_all_scorecards`.

**Acute risk resolved:** the only two 504-class routes are fixed with prod evidence and no integrity
regression (no data/freshness/gating/membership/entity-destination change). Remaining items below are
NBA-Readiness-scoped, Phase-C approval-gated, or low-risk polish.

---

Read-only measurement + static profiling. No remediation here (that is Phase B, after the empirical
baseline). SGP work held on `a94cbf9`; Green Light B1–B4 + NBA characterization queued behind this P0.

## Measured baseline so far

**Unauthenticated curl (3 runs, median/worst):** warm public pages ~0.35–0.5 s; **landing cold-start
~5.6 s on the first hit after idle** (the known cold-cache rebuild — a real worst-run contributor),
warm thereafter. Every member route returns the 401 gate to curl (~0.35 s), so the real member-route
numbers come from `perf_baseline_authed.py` (run on prod — pending).

**Local smoke (indicative, prod will confirm):** `/tools/nfl-milestones` **cold-built ~49 s** (matchup
pass over the full multi-season player-week set); warm hits are instant via `_NFL_MILESTONE_CACHE`. The
daily parquet refresh invalidates that cache, so the next visitor pays the cold build → **cold-cache
timeout risk**.

**Overall finding (static sweep):** most heavy builders are correctly cached on a source signature
(`_build_file_token` mtime tuples, `_nfl_player_log_signature`, props-mtime) — `build_live_props_board`,
`build_nfl_floor_board`, `build_nfl_hot_hand`, `build_nfl_milestone_streaks`, `dashboard` snapshot,
cross-sport dashboard, usage/buy-low/game boards. The defects are where that discipline breaks on the
request path.

## Ranked bottleneck table (LIVE-impact first; NBA items are latent while `BK_NBA_STATS_ENABLED=0`)

| # | Route · builder | Defect | Evidence | Live now? | Fix class |
|---|---|---|---|---|---|
| L1 | **Injury Report** · `build_injury_report_context` | **Uncached** + `iterrows`; recomputed every request | `app.py:18518`, loop `:18544` | **YES** (multi-league quick tool) | Cache on source signature (the earlier 504 was this route) |
| L2 | **NFL Matchup** · `build_nfl_matchup_dossier` | **Weak cache key `sig=len(hist)`** → stale on same-count rewrite + full-history `iterrows` on any count change | `:45752`, `:45766` | **YES** | Key on file mtime (not row count) |
| L3 | **Riding the Wave** · `build_nfl_prop_streaks` → `_nfl_player_return_status` | **N+1**: re-scans the ~100k-row player-week log **per qualifying player** | `:46858` → `:30753`/`:30765` | YES (on cache miss) | Precompute participation once per build (one pass), not per player — *my code from the Wave P0* |
| L4 | **All football tools** · `build_football_live_games` | **Uncached, recomputed many times per request** (home slate, totals, game board, line legs each call it) | `:6522`, `build_live_game_lookup` `:6523` | **YES** | Memoize per source signature |
| L5 | **/player/\<name\>** · `player` | Uncached; rebuilds `build_current_team_map` / `build_prop_market_groups` / `apply_current_team_context` over full feeds every view + nested per-prop `iterrows` | `:38448`, feeds `:38460`, nested `:38370`/`:38387` | YES | Cache the shared feeds on signature |
| L6 | **/team/\<team\>** · `team` | **N+1**: `team_logs[team_logs['Player']==p]` per player | `:38246` | YES | Single `groupby('Player')` |
| L7 | **NFL Hub** · `build_nfl_hub_context` | Uncached fan-out of ~12 builders; uncached callees (matchup_edge, home_slate) + repeated `build_football_live_games` run even off-season | `:44099`, `:44108-44121` | YES | Cache the wrapper on signature / off-season gate |
| L8 | **Milestones** · `build_nfl_milestone_streaks` | Well-cached warm, but **~49 s COLD build**; daily refresh → next user pays it | `:47060`; local smoke | YES | Vectorize the matchup pass + stampede-protect, or precompute on schedule |
| L9 | **Market Movers** · `_build_market_movers_snapshot` | **Raw uncached `pd.read_csv`** on a growing history file | `:18730` | YES | `_load_cached_csv` |
| N1 | **NBA props board** · `collect_live_prop_rows` → `get_player_analysis_logs` | **O(props × gamelog_rows)** — full `NBA_GameLogs.csv` boolean-scanned **once per prop row**; NBA never got NFL's per-player index | `services/nba_props_engine.py:101` → `app.py:16584` | **Latent** (NBA gated) | Port `_nfl_player_index` groupby pattern → **NBA Season Readiness** |
| N2 | **NBA props route** · post-cache enrichment | 4 whole-board passes + sort on **every request even on cache hit** to show 15 rows | `app.py:40389-40415` | Latent (NBA gated) | Move enrichment inside the cached builder / enrich only the visible page → **NBA readiness** |

Lower/again-cached: Green Light, Menu, Daily Card, Matchup Edge wrappers are uncached but delegate to
cached builders and are scoped/bounded (low-moderate). `nfl_current_form._data` `@lru_cache` + dossier
`len(hist)` are staleness (correctness) risks more than per-request cost.

## Proposed Phase B quick wins (reversible commits, evidence-backed; implement AFTER the before-baseline)

Ordered by live impact ÷ risk. Each is one reversible commit with before/after measurement and the
per-route regression guarantees (same membership/ordering, auth/plan, freshness, gating, entity
destinations, fail-closed unavailables, no cross-user cache leak):

1. **L1 — cache `build_injury_report_context`** on a `_build_file_token` of the 5 leagues' injury files
   (+ boost files). Expected: injury-report warm TTFB from "every-request rebuild" → cache hit.
2. **L2 — fix `build_nfl_matchup_dossier` cache key** from `len(hist)` to the history file mtime
   signature. Fixes a stale-data correctness bug AND avoids needless full-history rebuilds.
3. **L4 — memoize `build_football_live_games`** per source signature (module cache), so one request
   builds the game lookup once instead of 4–6×.
4. **L3 — precompute participation once** in `build_nfl_prop_streaks` (one grouped pass feeding
   `_nfl_player_return_status`) instead of re-scanning the log per qualifier.
5. **L6 — `/team` single groupby** replacing the per-player filter; **L5 — cache `/player` shared
   feeds** on signature.
6. **L8 — milestones cold build**: stampede-protect (one builder under a per-key lock, others get a
   brief "assembling" state) + precompute the matchup pass in the daily job with a generation id, so
   no request ever pays the 49 s.
7. **L9 — `_load_cached_csv` for Market Movers.**
8. **L7 — cache the NFL Hub wrapper** on a combined signature / skip off-season callees.

**NBA N1/N2** are the single largest *potential* costs but are **dormant while NBA is gated** — I'll
fold them into the **NBA Season Readiness** workstream (porting `_nfl_player_index` into the NBA
engine + moving enrichment inside the cache), not this NFL-live pass.

## Phase C — architecture (approval-gated, no infra changes without sign-off)
Shared cache (Redis) so warm caches survive restarts + are shared across workers (today each gunicorn
worker has its own module caches → cold per worker); a scheduled **materialized read model** for the
expensive matchup/milestone passes (precompute → atomic publish → request just reads, same pattern as
the ATS wave); CDN/static offload + versioned long-lived static caching; a pagination API for large
boards; a cold-start **prewarm** hook so the first post-restart request doesn't eat the 5.6 s rebuild.

## Budgets (from the directive) — to verify against the prod baseline
Warm authed TTFB ≤500 ms pref / ≤800 ms complex · cold complex ≤2 s · LCP mobile p75 ≤2.5 s · INP
≤200 ms · CLS ≤0.1 · no multi-MB HTML · **no 504s** · **0 external API calls on a request path**.

## Next
1. Run `perf_baseline_authed.py` on prod → empirical before-numbers (ranks confirmed).
2. I implement the quick wins as separate reversible commits with before/after.
3. Re-measure identical routes; CWV from a logged-in browser/Lighthouse.
4. No P0 closure until prod shows material improvement + zero integrity regression.
