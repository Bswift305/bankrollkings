# NBA / WNBA dataset-level source characterization

**Read-only inventory. No new NBA.com calls were made to produce this; no ingestion was run, no public
exposure changed, and `BK_NBA_STATS_ENABLED` stays `0` (OFF).** This document characterizes every NBA/WNBA
dataset the codebase touches so a licensing decision can be made per dataset. It does not lift the gate or
recommend lifting it; where it names a "cleared substitute," that is a candidate for a separate, reviewed
licensing decision, not an instruction to switch.

Cross-references the existing legal work: `docs/legal_ip_audit.md` (IP register, terms retrieved 2026-10-16)
and `docs/legal_register_v2.md` (dataset dispositions). This file is the engineering-side, per-dataset map
those legal conclusions attach to.

## The gate (applies to all NBA.com-derived datasets below)
`services/nba_source_gate.py` — `nba_stats_enabled()` returns true only for `BK_NBA_STATS_ENABLED ∈
{1,true,yes,on}`; **unset ⇒ OFF**. `SOURCES = ('NBA.com','stats.nba.com','cdn.nba.com','official.nba.com',
'nba_api')`. It gates **both** NBA.com ingestion (each fetcher self-checks) **and** the display/model-input
loaders, and it is folded into the board cache key. It does **not** gate the licensed The Odds API loaders
(props / game lines / schedule odds). QC: `qc_legal_containment.py`, `qc_nba_data_gate_containment.py`,
`qc_nba_market_only.py`.

Classification legend: **PROHIBITED-UNTIL-CLEARED** = NBA.com-derived, Critical per the legal register,
gated OFF. **LICENSED** = The Odds API, contractually permitted, not gated. **GAP** = a containment gap to
fix regardless of the licensing decision.

---

## A. NBA.com-derived datasets — PROHIBITED-UNTIL-CLEARED (gated OFF)

### 1. NBA regular-season player game logs
- **Provider/endpoint:** `nba_api … playergamelog.PlayerGameLog` (Regular Season) → stats.nba.com.
- **Fields:** per-player per-game box score (PTS/REB/AST/… matching gamelog columns; `identity_ok=True`).
- **Collection:** `download_2025_26_game_logs.py`, `floor_play_package/refresh_data.py` (self-gated).
- **Storage:** `data/gamelogs/NBA_GameLogs.csv` (gitignored; not committed).
- **Transforms:** feeds projections/confidence/edges in `services/nba_props_engine.collect_live_prop_rows`,
  the command-center board, and NBA calibration/grading (`load_nba_review_gamelogs`).
- **Displayed/derived outputs:** NBA props projections + command center — **only when the gate is ON**.
- **Retention:** overwrite-on-refresh; gitignored; not backed up (regenerable); not displayed while gated.
- **Attribution:** none emitted in-app (data is withheld).
- **Terms/license evidence:** `docs/legal_ip_audit.md` (NBA.com ToS §9(iv); Critical); `docs/legal_register_v2.md`.
- **Rights (display/redistribution/monetization):** none established — classified Prohibited Until Cleared.
- **Risk:** **High** (bulk statistical redistribution from NBA.com).
- **Cleared substitute (candidate):** a licensed stats provider (e.g. SportsDataIO NBA, or BallDontLie's paid
  tier — listed in `DATA_REFRESH_README.md`, not wired) under its own license + attribution; decide separately.

### 2. NBA playoff player game logs + playoff results
- **Provider/endpoint:** `nba_api … playergamelog` (Playoffs) + `scoreboardv2`; **ESPN** NBA scoreboard for
  results merge.
- **Fields:** playoff box scores; game results (teams, scores).
- **Collection:** `refresh_playoff_player_logs.py`, `refresh_playoff_results.py` (self-gated).
- **Storage:** `data/gamelogs/NBA_Playoff_GameLogs.csv`, `data/tracking/NBA_Playoff_Results.csv` (gitignored).
- **Transforms:** `load_nba_review_gamelogs` (regular+playoff concat) for grading; `load_playoff_results`
  (NOT gate-wrapped — reads the results CSV).
- **Displayed/derived:** grading/calibration inputs; results via playoff loader.
- **Retention / attribution / terms / rights / risk:** as Dataset 1. **Risk: High** (NBA.com + ESPN).
- **Cleared substitute:** licensed stats provider; ESPN results via a permitted feed.

### 3. NBA schedule (NBA.com-derived start times)
- **Provider/endpoint:** `nba_api … scoreboardv2` / `nba_api.live … scoreboard` (cdn/stats.nba.com);
  Odds-API fallback from `NBA_Odds.csv`.
- **Fields:** game id, teams, date/time.
- **Collection:** `fetch_schedule.py`, `add_todays_games.py` (self-gated).
- **Storage:** `data/schedules/NBA_Schedule.csv` (gitignored).
- **Transforms/outputs:** `load_schedule` merges the NBA.com schedule with Odds-API odds. **Note:**
  `load_schedule` itself is **not** gate-wrapped — the gate is enforced upstream at ingestion and at the
  board route. The Odds-API schedule alias can stand alone.
- **Risk:** **Medium** (schedule facts, NBA.com-derived); **Cleared substitute:** the Odds-API schedule
  alias already written by `fetch_game_lines.py`, or a licensed schedule feed.

### 4–6. NBA player/defensive tracking + advanced stats (tracking family)
- **Provider/endpoint:** `nba_api … leaguedashptstats` (tracking), `leaguedashplayerstats` (Advanced),
  `leaguedashptdefend` (defense) → stats.nba.com.
- **Fields:** speed/distance/touches/drives; advanced efficiency; defensive matchup stats.
- **Collection:** `refresh_tracking_stats.py`, `floor_play_package/refresh_data.py` (self-gated).
- **Storage:** `data/tracking/NBA_Tracking.csv`, `NBA_PlayerTracking.csv`, `NBA_Advanced.csv`,
  `NBA_PlayerAdvanced.csv`, `NBA_Defense.csv`, `NBA_PlayerSnapshot.csv` (gitignored).
- **Loaders:** `load_player_tracking`, `load_player_advanced`, `load_player_snapshot` — **GATED**.
- **Transforms/outputs:** model inputs to `collect_live_prop_rows` (projections/edges) — gate ON only.
- **Risk:** **High** (granular NBA.com tracking IP). **Cleared substitute:** licensed advanced-stats provider.

### 7. NBA injuries
- **Provider/endpoint (fallback chain):** official.nba.com report page + CMS PDF, cdn.nba.com injuries JSON,
  stats.nba.com widget JSON **with spoofed `x-nba-stats-token`/`x-nba-stats-origin` headers**, ESPN NBA.
- **Fields:** player, team, status/designation; derived teammate boosts + active-boost plays.
- **Collection:** `fetch_injuries.py` (self-gated); merges `NBA_Injuries_Manual.csv`.
- **Storage:** `data/injuries/NBA_Injuries.csv`, `_last_good`, `_Manual`, `NBA_Return_Overrides.csv`,
  `Teammate_Boosts.csv`, `Active_Boost_Plays.csv` (gitignored).
- **Loaders:** `load_injuries`, `load_sport_injuries` — **GATED**; teammate-boost reads gated.
- **Risk:** **High** — NBA.com injury report + **header spoofing** of an undocumented endpoint (an access-
  method risk beyond redistribution; flagged in `docs/legal_ip_audit.md:57-60`). **Cleared substitute:** a
  licensed injury feed; drop the spoofed-header path entirely.

### 8. NBA/WNBA referee (officiating) assignments
- **Provider/endpoint:** official.nba.com referee-assignments page.
- **Fields:** per-game officiating crew; derived official tendency profiles.
- **Collection:** `fetch_basketball_officiating_assignments.py` (self-gated) → `build_officiating_context`,
  `build_official_tendency_profiles`.
- **Storage:** `data/context/NBA_OfficiatingContext.csv`, `WNBA_OfficiatingContext.csv` (gitignored by the
  blanket `*.csv` rule).
- **Risk:** **Medium-High** (official.nba.com scrape). **Cleared substitute:** licensed officiating data, or
  drop the lens.

### 11. NBA roster
- **Provider/endpoint:** document-sourced (`refresh_current_roster.py` → `NBA_CurrentRoster_FromDoc.csv`);
  `DATA_REFRESH_README.md` labels `NBA_Rosters.csv` source "NBA.com".
- **Risk:** **Medium** (roster facts; thin IP but NBA.com-labeled). **Cleared substitute:** licensed roster
  feed or a document the operator is cleared to use.

### 12. WNBA game logs (stats.nba.com, league_id 10)
- **Provider/endpoint:** `nba_api … leaguegamefinder` (`league_id_nullable="10"`) → stats.nba.com.
- **Storage:** `data/gamelogs/WNBA_GameLogs.csv` (gitignored). **Loader:** `load_wnba_gamelogs` — **GATED**
  (comment confirms stats.nba.com lineage).
- **Risk:** **High** (same NBA.com lineage as Dataset 1). **Cleared substitute:** licensed WNBA stats feed.

---

## B. Licensed datasets — The Odds API (contractually permitted, NOT gated)

### 9. NBA player props · 10. NBA game lines/odds · 13. WNBA player props · 14. WNBA game lines/odds
- **Provider/endpoint:** The Odds API (`api.the-odds-api.com`), keys `basketball_nba` / `basketball_wnba`;
  markets player points/reb/ast/threes/steals/blocks and h2h/spreads/totals.
- **Fields:** player, matchup, book, line, Over/Under prices, book-update timestamp; line-movement history.
- **Collection:** `fetch_player_props.py`, `fetch_game_lines.py`, `fetch_wnba_*` wrappers.
- **Storage:** `data/props/NBA_Props.csv`, `data/odds/NBA_Odds.csv`, line-movement CSVs, WNBA equivalents
  (gitignored).
- **Loaders:** `load_props`, `load_game_market_odds`, `load_wnba_props`, `load_wnba_game_market_odds` —
  **NOT gated** (licensed lineage; render even while the NBA stats gate is OFF). When NBA stats are gated,
  the props page serves `build_market_only_board` → `market_only_board.html` (odds only: player, matchup,
  book, line, prices, `book_updated_at`; **no** projections/stats/edges).
- **Retention:** overwrite-on-refresh; gitignored.
- **Terms/license evidence:** `docs/legal_ip_audit.md:41-46` — The Odds API "Licensed / permitted"; flags
  key-in-URL log hygiene.
- **Rights:** display permitted under the Odds API terms; redistribution/monetization per that contract.
- **Risk:** **Low-Medium** (licensed; the only live monetizable NBA surface today is this market-only board).
- **Cleared substitute:** already the cleared source. Action item: confirm key-in-URL log hygiene.

---

## C. Containment gaps (fix regardless of the licensing decision)
1. **WNBA injury ingestion is not gated.** `fetch_sport_injuries.py` (ESPN, used by `fetch_wnba_injuries.py`)
   has **no** `BK_NBA_STATS_ENABLED` ingestion check — only the *display* loader (`load_sport_injuries`) is
   gated. So WNBA injury ingestion can run while the gate is OFF. ESPN (not NBA.com), but it should be gated
   at ingestion for consistency, or explicitly documented as a permitted ESPN feed.
2. **Header spoofing** of an undocumented stats.nba.com endpoint in `fetch_injuries.py`
   (`x-nba-stats-token`/`x-nba-stats-origin`) — an access-method risk independent of redistribution; recommend
   removing that fallback path.
3. **Runtime `pip install nba_api`** in some scripts — supply-chain + reproducibility risk; pin in
   `requirements.txt` (already `nba_api>=1.5`) and never install at runtime.
4. **Non-gate-wrapped loaders that carry NBA.com-derived facts:** `load_schedule` and `load_playoff_results`
   read NBA.com-derived CSVs without a loader-level gate. The route-level + ingestion gate currently contain
   them, but a loader-level gate (or an Odds-API-only schedule) would be defense-in-depth.

## D. Summary matrix
| # | Dataset | Provider | Gated | Risk | Cleared substitute (candidate) |
|---|---|---|---|---|---|
| 1 | NBA reg. gamelogs | stats.nba.com | yes | High | licensed stats feed |
| 2 | NBA playoff logs+results | stats.nba.com + ESPN | yes* | High | licensed stats + results |
| 3 | NBA schedule | nba.com (+Odds fallback) | ingest/route | Medium | Odds-API schedule alias |
| 4-6 | NBA tracking/advanced/defense | stats.nba.com | yes | High | licensed advanced stats |
| 7 | NBA injuries | official/cdn/stats.nba.com + ESPN | yes | High | licensed injury feed; drop spoof |
| 8 | NBA/WNBA officiating | official.nba.com | yes | Med-High | licensed officiating or drop |
| 11 | NBA roster | NBA.com/doc | yes | Medium | licensed roster feed |
| 12 | WNBA gamelogs | stats.nba.com | yes | High | licensed WNBA stats |
| 9,10,13,14 | NBA/WNBA props + lines | The Odds API | no | Low-Med | already cleared |
| 15 | WNBA injuries | ESPN | display-only | Medium | **gate ingestion (gap C.1)** |

\* `load_playoff_results` itself is not loader-gated (see C.4).

## E. sport_registry.py (NBA/WNBA)
NBA: unprefixed loaders (`load_props`/`load_gamelogs`/`load_schedule`/`load_game_market_odds`), grading via
`load_nba_review_gamelogs`, `identity_ok=True`, `requires_play_verdict=False`, calibrator
`calibrate_nba_model.py`. WNBA: prefixed loaders, `requires_play_verdict=True`, `min_market_prob=58`,
`min_lean_gap=5`, "the only sport with a proven end-to-end record."

## F. Scope & non-actions (reaffirmed)
This is characterization only. **No** new NBA.com/stats.nba.com/cdn.nba.com/official.nba.com calls, **no**
ingestion automation, **no** public exposure, **no** change to `BK_NBA_STATS_ENABLED` (stays `0`). The
cleared-substitute column is input to a separate, reviewed licensing decision — not a switch to flip here.
