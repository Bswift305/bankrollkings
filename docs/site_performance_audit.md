# Site Performance P0 — Phase A baseline + ranked bottleneck table

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
