# Current-market containment matrix (Oct 23 incident)

Fail-closed freshness coverage for every current-market channel. **Paid recovery stays blocked until
this matrix is fully GREEN.** A stale odds feed must render/export **unavailable**, never day-old lines as
current. Labeled *historical* data (with its own data-through date) may remain, separated from current.

Columns: **artifact** (authoritative odds source) · **clock** (freshness signal) · **threshold** ·
**stale behavior** · **cache-key gate** (does the cache key fold the freshness/gate state) ·
**test** · **status**.

Policy: current game LINES use `get_lines_refresh_meta` / `LIVE_LINES_MAX_AGE_HOURS = 6` (the documented
live-market window, same as props `load_*_live_props_feed(require_fresh=True, max_age_hours=6)`).

## GREEN — verified (football)
| Channel | artifact | clock | thr | stale behavior | cache-key gate | test | status |
|---|---|---|---|---|---|---|---|
| NFL game-lines HTML `/sports/nfl/game-lines` | `NFL_Odds.csv` | `LastUpdated` | 6h | rows suppressed + "Current Lines Unavailable" | request-time gate (not a cached builder) | `qc_game_lines_freshness` | ✅ |
| CFB game-lines HTML `/sports/ncaaf/game-lines` | `NCAAF_Odds.csv` | `LastUpdated` | 6h | rows suppressed + banner | request-time | `qc_game_lines_freshness` | ✅ |
| NFL/CFB totals HTML `/sports/*/totals` | same | `LastUpdated` | 6h | line rows suppressed + banner; totals pill suppressed | request-time | `qc_game_lines_freshness` | ✅ |
| NFL/CFB totals **pill** | same | `LastUpdated` | 6h | not built when stale | request-time | `qc_game_lines_freshness` | ✅ |
| Standalone totals `/tools/cfb-totals*`, `/tools/nfl-totals-today` | same | `LastUpdated` | 6h | **builder** returns 0 rows + `tb_stale/nt_stale` (gates every caller) | builder-level gate | `qc_game_lines_freshness` | ✅ |
| NFL/CFB **props** boards `/sports/*/props` | `*_Props.csv` | `LastUpdated` | 6h | `require_fresh=True` → empty + `is_stale` banner | — (request-time) | existing props gate | ✅ (pre-existing) |

## GREEN — verified (cross-sport Market Movers)
| Channel | artifact | clock | thr | stale behavior | cache-key gate | test | status |
|---|---|---|---|---|---|---|---|
| **Market Movers** (`/tools/market-movers`, the market-edge line-movement board, MLB/WNBA/NFL/CFB) | `*_LineMovementHistory.csv` | latest `SnapshotAt` per game | 12h (3× the 4h capture cadence) | game **suppressed** when its capture stalled (no stale "current" line) | builder-level gate; the 300s TTL cache re-evaluates each cycle | `qc_market_movers_freshness` | ✅ |

## Snapshot path (NBA/WNBA) — already contained
| Channel | behavior | test | status |
|---|---|---|---|
| NBA/WNBA runtime snapshots | `load_runtime_snapshot` **rejects** NBA/WNBA snapshots by key while `BK_NBA_STATS_ENABLED=0` → a forbidden/stale snapshot cannot surface; callers fall to the live build | `qc_nba_residual_authority` R7-C (seeded forbidden snapshot rejected) | ✅ |

## GREEN — verified (shared current-line chokepoint, all sports)
| Channel | artifact | clock | thr | stale behavior | cache-key gate | test | status |
|---|---|---|---|---|---|---|---|
| **`build_game_market_lookup`** — the shared chokepoint annotating current spread/total/ML on **every** board + command center (NBA/WNBA/MLB/NFL/CFB; 8 callers incl. `/sports/*` command centers) | per-sport `*_Odds.csv` | freshest `LastUpdated` | 6h | empty lookup when the **whole feed** is stale → no board shows a stale current line/price; any recent update (or no `LastUpdated`) is not suppressed | builder-level (request-time); TTL caches re-evaluate | `qc_market_lookup_freshness` | ✅ |
| NBA/WNBA/MLB command-center game-line annotations | via the chokepoint above | — | 6h | fail closed when feed wholesale-stale | — | same | ✅ |

## RED — remaining (must close before recovery)
| Channel | artifact | clock | thr | current behavior | gate needed | status |
|---|---|---|---|---|---|---|
| **Cached snapshots** — MLB/WNBA line boards prewarmed via `refresh_runtime_snapshots` (NBA/WNBA already rejected by the stats-gate, R7-C) | per-sport `*_Odds.csv` | snapshot build time | — | a non-NBA/WNBA snapshot built while fresh could be **served after the feed goes stale** | re-gate on read (the chokepoint runs at request time, but a snapshot that pre-rendered the lookup bypasses it) OR fold freshness into the snapshot key | ⛔ REMAINING |
| JSON / lazy endpoints (`/tools/cfb-ats/games`, `/api/live-ticker`, `*/games` AJAX) | per-sport odds | per-endpoint | — | those that read `build_game_market_lookup` / `build_market_movers_context` / `build_football_*` are **now covered** by the chokepoint gates; any that read odds directly are **unaudited** | audit each; the ones bypassing the chokepoints need the gate | ⚠️ PARTIAL (audit) |
| Embedded feeds — SGP Workbench, King's Tickets, Matchup Center | per-sport odds / book quotes | per-feed | — | SGP uses book-specific quotes ("price unavailable" never synthesized — partial); Matchup Center + King's Tickets line reads **unverified** | audit each embedded odds read; fail closed on stale | ⛔ REMAINING |
| Exports (`/bet-review/export`, `/elite/alerts/export`) | user bet/alert data, not a current-odds board | n/a | — | likely **N/A** (not a current-market line export) — **to confirm** | confirm no current line/price is exported stale; else gate | ⚠️ VERIFY |

## Notes
- **CFB contradiction RESOLVED:** the earlier "CFB surfaces fail closed" was wrong — the standalone
  `/tools/cfb-totals*` routes called `build_cfb_totals_board_context` directly and were ungated. Now gated
  at the builder, so every CFB current-market **totals/game-lines HTML** channel is GREEN; CFB JSON/lazy
  and any embedded CFB line read remain RED pending audit. CFB is **not** "contained" as a sport until its
  JSON/embedded channels are verified.
- **NBA/WNBA restricted-stats containment is unchanged** — `BK_NBA_STATS_ENABLED=0` stays; this work gates
  only the *licensed Odds* line surfaces for freshness and must not lift the stats gate.
- **Cache keys:** per CLAUDE.md §4, a cached builder that reads an odds file not folded into its version
  token serves stale forever. The lines-freshness gate must be part of the cache key (or applied on read)
  wherever a line board is a cached/prewarmed snapshot — otherwise containment is bypassed by the cache.
- **Sentinel export tests:** a populated-fixture test proving a stale sentinel line neither renders nor
  exports is DONE for football (`qc_game_lines_freshness` captures empty odds to the board builders); it is
  owed for every RED channel as it is closed.
