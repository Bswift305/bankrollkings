# Timestamp inventories F-T1 / F-T2 (2026-11-04) — governed copy

> Read-only inventory at exact production `17b5e69`; copied verbatim from the working report so the ledger, not a scratchpad, holds the record. No code was changed.
>
> **Frozen direction (owner, 2026-11-04):**
> - `SourceUpdatedAtUTC` = provider/source time; `FetchedAtUTC` = our ingestion time; both timezone-aware canonical UTC (ISO-8601 with `Z`).
> - `LastUpdated` is legacy/ambiguous; it is retired only after every consumer has migrated.
> - No code may infer a source timezone from the server or the developer machine.
>
> **Dev-machine finding:** this development machine runs in **Pacific** time (and June data shows the workstation on Central), which disproves CLAUDE.md §5's claim that "a US-timezone dev box agrees with Eastern and never reproduces this". Proposed corrected wording (documentation change only — NOT to be mixed into a production hotfix):
>
> > "Dev boxes are not reliably Eastern (Pacific and Central have both been observed). Any code that formats or parses a zone-less time with the process clock will behave differently on prod (UTC), on the dev box, and on Eastern. Treat every zone-less timestamp as unknown: parse only zone-explicit UTC, convert for display with `America/New_York` explicitly, and test under UTC, New York and Los Angeles process zones."

---

# F-T1 / F-T2 — Timestamp inventory (read-only)

Worktree: `.claude/worktrees/props-utc` @ `17b5e6979098096c10d38ed3a5d1c27e77c3610e` (exact prod master). Nothing edited; `git status --short` empty at end.
Method: grep and read of every `LastUpdated` / `SnapshotAt` / `FetchedAt*` / `SourceUpdatedAt*` / `last_update` site, plus one pure-local pandas simulation of the `get_lines_refresh_meta` arithmetic (no app import, no network). Line numbers refer to this commit.

Assumption (not verified on the box): prod processes run in **UTC**. CLAUDE.md §5 says so, and no `TZ=` appears in `deploy/*.service`, `ops/*.service` or app code. The only `tzset` in the repo is in `qc_props_quote_source_time.py`.

---

## 0. Summary of the two meanings of `LastUpdated`

The column name hides **three different semantics**. Which one you get depends on the producer.

| Semantics | Producers | Format | Zone |
|---|---|---|---|
| **Provider book time → ET display string** | `fetch_game_lines.py:182`, `fetch_futures_odds.py:~118-138`, historical lines via `parse_event_markets` | `YYYY-MM-DD HH:MM` | Eastern, but zone-less (tz stripped by `services/timeutils.to_eastern_datetime_str`) |
| **Mixed: provider ET when bookmaker `last_update` is present, else OUR FETCH TIME in the process zone** | `fetch_player_props.py:449` (all 5 prop sports) | `YYYY-MM-DD HH:MM` | ET **or** process-local (UTC on prod; Pacific on the box this ran on; Central on the June workstation per `SnapshotAt -05:00`). Zone-less. Per the diag, bookmaker-level `last_update` is absent on the event-odds endpoint, so in practice this is **fetch time, process zone** |
| **Explicit UTC** | `fetch_football_first_half.py:86/137` (fetch time, `...Z`), `refresh_live_scores.py:221` (provider `last_update` or now-UTC ISO), `fetch_nfl_current_roster.py:50/77` (fetch time `+00:00`) | ISO with zone | UTC, explicit |

Consumers assume either "ET" (`_feed_stamp_to_utc`), "process-local naive" (`pd.Timestamp.now()` comparisons), or "UTC" (`utc=True`). Each assumption is right for some producers and wrong for others.

---

# F-T1 — Producer timestamp cleanup inventory

## F-T1.1 Producers

### Market feeds (props / odds / lines / futures)

| # | Producer file:line | Column | Value written | Zone | Lands in | Sports |
|---|---|---|---|---|---|---|
| P1 | `fetch_player_props.py:449` (`parse_market_rows`) | `LastUpdated` | `to_iso_local(bookmaker.last_update) or fetched_at`. `fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")` (`:414`) | **Zone-less.** ET if the bookmaker ts exists (absent per diag), else **process-local fetch time** | `data/props/{NBA,WNBA,NFL,NCAAF,MLB}_Props.csv` (`:157-161`) | NBA, WNBA, MLB, NFL, NCAAF (sport wrappers `fetch_{mlb,wnba,nfl,ncaaf}_player_props.py` all `import fetch_player_props`) |
| P1b | `fetch_player_props.py:453` | `SourceUpdatedAtUTC` | `to_utc_iso(market.last_update)` (`:370-390`). Blank if absent or naive; never falls back to fetch time | **Explicit UTC `...Z`** | same props CSVs | same 5 sports |
| P1c | `fetch_player_props.py:452` | `EventCommenceAtUTC` | `to_utc_iso(event.commence_time)` | Explicit UTC | same | same |
| P1d | `fetch_player_props.py:610/638` | `LastChecked` | `datetime.now().astimezone().strftime(...)` | Zone-less, process-local | `data/tracking/<stem>_MarketCoverage.csv` | all prop sports (ops only) |
| P2 | `import_props.py:32,130-132,282` | `LastUpdated` | Whatever the pasted sheet's `lastupdated`/`updated`/`time` column held | Unknown | `data/props/NBA_Props.csv` (manual) | NBA (manual path). No `SourceUpdatedAtUTC` |
| P3 | `fetch_game_lines.py:182` (`parse_event_markets`) | `LastUpdated` | `to_iso_local(bookmaker.last_update)` (bulk `/odds` endpoint, `:238`). Blank if absent, with no fetch-time fallback (`:175`) | Zone-less **ET** (provider time) | `data/odds/{NBA,WNBA,NFL,NCAAF,NFL_Preseason,MLB}_Odds.csv` + `data/schedules/*_Odds.csv` alias (`:28-56`, `build_schedule_alias :294`) | NBA, WNBA, MLB, NFL, NFL preseason, NCAAF (wrappers `fetch_{mlb,wnba,nfl,ncaaf}_game_lines.py`) |
| P3b | `fetch_game_lines.py:315-316` | `SnapshotAt` | `datetime.now().astimezone().isoformat(timespec="seconds")` | **Explicit offset**, process zone (`+00:00` on prod) | `data/tracking/<SPORT>_LineMovementHistory.csv` | same |
| P3c | `fetch_game_lines.py:349-351` | `FirstSeen`, `LastSnapshotAt`, `LastUpdated` | Passthrough of `SnapshotAt` / `LastUpdated` | as above | `data/tracking/<SPORT>_LineMovementCurrent.csv` | same |
| P4 | `fetch_oddsapi_historical_game_lines.py:13,96-111` (+ `fetch_ncaaf_historical_game_lines_oddsapi.py`) | `LastUpdated` (+ `SnapshotDate`, `CommenceTime` raw provider) | Same `parse_event_markets` → ET zone-less | ET zone-less | `data/historical/*_OddsAPI_GameLines_History.csv` | NCAAF, NFL, CBB |
| P5 | `fetch_futures_odds.py:~118-138` | `LastUpdated` | `to_iso_local(market.last_update) or to_iso_local(bookmaker.last_update)` | Zone-less ET (provider) | `data/futures/Futures_Odds.csv` | outrights, all sports |
| P5b | `fetch_futures_odds.py:193-194, 221-223` | `SnapshotAt`, `FirstSeen`, `LastSnapshotAt`, `LastUpdated` | `datetime.now().astimezone().isoformat()` + passthrough | Explicit offset (process zone) | `data/tracking/Futures_LineMovement{History,Current}.csv` | futures |
| P6 | `fetch_football_first_half.py:86,137` | `LastUpdated` | `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`, i.e. **fetch time**, not provider time | **Explicit UTC `Z`** | `data/odds/{NFL,NCAAF}_FirstHalf.csv` | NFL, NCAAF |
| P7 | `fetch_ncaaf_slate_cfbd.py:161,171` | `FetchedAtUTC` | `datetime.now(timezone.utc)...Z` | Explicit UTC | `data/odds/NCAAF_CFBD_Lines.csv`, `data/schedules/NCAAF_CFBD_Schedule.csv` | NCAAF (no prices) |
| P8 | `capture_nfl_prop_lines.py:125,180` (+ `:26-59` source clocks) | `BKCapturedAtUTC`, `SourceUpdatedEarliestUTC/LatestUTC`, `EventCommenceAtUTC` | UTC fetch time and propagated `SourceUpdatedAtUTC` | Explicit UTC | `data/tracking/NFL_PropLines_Archive.csv` | NFL |
| P9 | `capture_nfl_line_open.py:62,73` | `FirstSeen` | `datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")` | **UTC but zone-less** | `data/tracking/NFL_LineOpen.csv` | NFL |
| P10 | `fetch_season_markets_sportsdataio.py:142,166,185,189`; `refresh_season_markets.py:75-85` | `SnapshotAt`, `SourceUpdatedAt` | `SnapshotAt` = UTC ISO. `SourceUpdatedAt` = SportsDataIO `Updated`/`Created`, else now-UTC | `SnapshotAt` explicit. `SourceUpdatedAt` is **provider zone unverified** (SportsDataIO strings, not checked), mixed with UTC fallback | season-markets files (`services/season_markets.py`) | season markets |

### Non-market but in scope (rosters, live scores)

| # | Producer file:line | Column | Value | Zone | Lands in |
|---|---|---|---|---|---|
| P11 | `refresh_live_scores.py:221` | `LastUpdated` | `event.last_update` (Odds API scores, `Z`) or `datetime.now(timezone.utc).isoformat()` | Explicit UTC | live scores CSV (`LIVE_SCORES_PATH`) |
| P12 | `fetch_nfl_current_roster.py:50,77` | `LastUpdated` | `datetime.now(timezone.utc).isoformat(timespec="seconds")` | Explicit `+00:00` | NFL current roster CSV |

### Adjacent context producers (zone-less, process-local, the same bug class; not market feeds)

`build_mlb_game_context.py:106,141` · `build_mlb_umpire_context.py:124,143` · `build_official_tendency_profiles.py:241` · `build_officiating_context.py:85,104` · `fetch_basketball_officiating_assignments.py:102,128` · `fetch_mlb_umpire_assignments.py:139,162`. All write `datetime.now().strftime("%Y-%m-%d %H:%M")` → `LastUpdated`.
`fetch_mlb_weather_context.py:157` writes **Central** (`datetime.now(CENTRAL)`), zone-less.
`fetch_injuries.py:177,203,241,307` and `fetch_sport_injuries.py:213` write `Updated` = `datetime.now()` zone-less.
`fetch_nfl_weather.py:131` writes `Updated` = Eastern string. `fetch_mlb_lineups.py:46` writes `FetchedAt` = UTC zone-less. `fetch_final_scores.py:45` writes `Updated` = UTC zone-less.

### Local evidence (dev box, read-only sample; NOT prod)
- The box this ran on reports **Pacific** (`-08:00`). The local `data/props/NFL_Props.csv` (mtime Nov 4 05:30 local) has `LastUpdated = "2026-11-04 05:30"`, which is the **Pacific fetch time**. It has **no `SourceUpdatedAtUTC` column**: the main checkout's `fetch_player_props.py` (HEAD `3098325`) contains no `SourceUpdatedAtUTC`.
- Local `NFL_LineMovementHistory.csv` has `SnapshotAt = 2026-06-04T04:33:23-05:00` (June → `-05:00` = Central). The same producers write different wall clocks on different machines. CLAUDE.md §5 says "a US-timezone dev box agrees with Eastern". That does not hold on these machines.
- Local `NFL_Odds.csv` `LastUpdated = 2026-11-04 08:29` (ET provider), `NFL_FirstHalf.csv` `2026-09-24T23:46:34Z`, `Futures_Odds.csv` `2026-09-24 11:30` (ET). Formats match the table above.

---

## F-T1.2 Consumers of `LastUpdated`

Classes: **(a)** AUTHORITY · **(b)** CUSTOMER DISPLAY · **(c)** SORT/DEDUP · **(d)** OPS/QC · **(e)** dead/unused.
"ISO-Z impact" = what happens if the producer writes explicit UTC (`YYYY-MM-DDTHH:MM:SSZ`) in the same column.

### app.py

| # | file:line | Function | Reads (file / sport) | Class | Current behaviour on the UTC prod box | ISO-Z impact |
|---|---|---|---|---|---|---|
| C1 | app.py:3627-3638 | `get_props_refresh_meta` (LastUpdated block) | all props CSVs (NBA/WNBA/MLB/NFL/NCAAF) | **(a)+(b)** | Computes `age_hours` and the label from naive `LastUpdated` vs naive `pd.Timestamp.now()`. On prod both are UTC (fetch fallback), so the age is right **but the label is UTC wall clock with no zone**. **Hotfix override (`:3643-3652`)**: if a `SourceUpdatedAtUTC` column exists, label+age come from it in explicit ET. **Residual:** column present but all blank → label "Update time not recorded" but `age_hours`/`is_stale` **still come from LastUpdated** (fetch age, not provider age). Column absent (pre-2026-10-24 files, `import_props` NBA, the MLB fallback file alone) → the UTC label is shown unlabelled | Age is still correct (tz-aware now path). The label (`strftime('%b %d, %Y %I:%M %p')`) would show **UTC wall clock unlabelled**, a change. Mixed naive/aware values in one parse could coerce to NaT. Within a single props file this doesn't happen today, because `build_dataframe` writes current-run rows only |
| C2 | app.py:3715-3751 | `load_{,wnba_,mlb_,nfl_,ncaaf_}live_props_feed` (`require_fresh`) | props, 5 sports | **(a)** | Empties the board when `is_stale`. Inherits C1 | Same as C1 |
| C3 | app.py:3682-3710 | `get_lines_refresh_meta` | game-lines odds CSVs | **(a)+(b)** | **BUG on UTC box.** Naive ET `LastUpdated` vs naive **UTC** `pd.Timestamp.now()` → age **+5 h (EST) / +4 h (EDT)**. Simulated: a 30-min-old line reads `age_hours=5.5`, so any line more than ~1 h old (EST) crosses the 6 h window and `is_stale=True`. On a Pacific box it reads 3 h *fresher* (fail-open). Label = ET wall time, **no zone**. Warning text embeds the inflated age | Fixes the age (aware now). Label becomes UTC wall time unlabelled unless the label code converts to ET. **Highest-value consumer to migrate first** |
| C4 | app.py:6672-6682 | `build_football_live_games` wholesale-stale gate | NFL/NCAAF odds | **(a)** | Drops all odds (lines abstained) when C3 says stale. Inherits the +5 h bias | via C3 |
| C5 | app.py:18293-18298 | `load_ncaaf_context_slate` | `NCAAF_Odds.csv` | **(a)** | Drops odds rows when C3 says stale | via C3 |
| C6 | app.py:18351-18360 | `build_game_market_lookup` gate ("THE chokepoint … NBA/WNBA/MLB/NFL/CFB") | odds, all sports | **(a)** | Returns an empty lookup when C3 says stale, so boards and command centers lose spread/total/ML | via C3 |
| C7 | app.py:35522-35528 | `_render_football_method_page` | NFL/NCAAF odds | **(a)+(b)** | Suppresses game-lines/totals rows; renders `lines_refresh_meta.last_updated` + warning (football_method_board.html:79-90) | via C3 + label |
| C8 | app.py:51152-51156, 51224-51228, 51393-51395 | `build_cfb_totals_board_context`, `build_nfl_totals_board_context`, `build_nfl_matchup_center_context` | NCAAF / NFL odds | **(a)+(b)** | Empty totals board + `tb_stale_note`/`nt_stale_note` = C3 warning (inflated age); Matchup Center abstains lines | via C3 |
| C9 | app.py:18378 → 24671, 25660 | `build_game_market_lookup` payload `last_updated` → `build_tonights_card` `market_updated`, `build_matchup_editorial` `market_updated` | odds (callers at 24374, 28663, 30620, 30839, 39771, 40056, 40133) | **(b)** | Raw ET string ("2026-11-04 13:05") rendered at dashboard.html:1304 and matchup.html:130 as "Last update: …", **no zone**. The value is correct ET | Would render a raw `2026-11-04T18:05:00Z`. **Display changes**: needs a formatter |
| C10 | app.py:6569 → 6743 | `build_live_game_lookup` → `build_football_live_games` `updated_utc` via `_feed_stamp_to_utc` | football odds + schedule alias | **(b)** (and quote lineage) | `_feed_stamp_to_utc` localizes zone-less as ET, which is **correct for game lines** (provider ET). Flows to `_unpriced_line_fields` / `_updated_label` → "updated … ET" on Daily Card / Menu / King's Tickets team-line legs (33558, 33580, 49416, 49445) | **Safe**: aware strings keep their zone |
| C11 | app.py:19613/19633 | `build_slate_pulse_context` | props via C1 | **(b)+(a-display)** | slate_pulse.html:65 shows `updated` + age. ET-labelled when SourceUpdatedAtUTC is populated | via C1 |
| C12 | app.py:19833/19839 | `_build_best_lines_snapshot` feed states | props via C1 | **(b)** | best_lines.html:171 `feed.updated` | via C1 |
| C13 | app.py:20135 | `_build_risk_radar_snapshot` | props via C1 | **(a)** | stale-feed list | via C1 |
| C14 | app.py:25267 | `build_featured_nba_top_plays` | NBA props via C1 | **(a)** | returns `[]` if `age_hours > 6` | via C1 |
| C15 | app.py:30943/30955 | `build_nba_command_center_context` → `props_last_updated` | NBA props (canonical, columns preserved) | **(b)** | dashboard.html:1224 "Props refreshed {…}" | via C1 |
| C16 | app.py:42228-42251 | `build_market_only_board` `book_updated_at` | NBA (gate off, 42260; 30725) + WNBA (35941) props | **(b)** | **Mislabel.** Renders `LastUpdated` under the header **"Book Updated"**, and the footnote (market_only_board.html:54) says it is "the Odds API bookmaker's reported quote-update time — not when Bankroll Kings ingested". It is actually **our fetch time** (UTC on prod), shown with "(tz unknown)" | `_tz_known` becomes True: the "(tz unknown)" tag disappears and a raw Z string shows, **still mis-attributed as book time**. Should read `SourceUpdatedAtUTC` instead |
| C17 | app.py:48828 | `_nfl_sgp_leg_menu`: game-line legs | `NFL_Odds.csv` | **(b)** | Raw ET string, tz note `'provider time; tz unverified'` (`:48520`); sgp_workbench.html:127,150,216 and copy-export | Would show a raw Z string; the note becomes inaccurate |
| C18 | app.py:48873 | `_nfl_sgp_leg_menu`: team-total/period legs | `NFL_FirstHalf.csv` (P6, UTC fetch time) | **(b)** | Shows the `...Z` **fetch time** labelled "provider time; tz unverified". Mis-attributed (fetch, not provider) | Already ISO-Z; no change |
| C19 | app.py:2731 | `load_live_scores` | live scores (P11) | **(a)** | `utc=True` on an explicit UTC stamp: correct. Flips stale 'live' rows to final | Already explicit; safe |
| C20 | app.py:20286-20292 | `build_game_context_context` | MLB game context (`build_mlb_game_context.py`, naive local) | **(b)+(a-display flag)** | game_context.html:44 "context updated {…}" = UTC wall clock unlabelled on prod. The stale flag compares naive vs naive on the same box (OK) | n/a (different producer) |
| C21 | app.py:29028-29047 | `build_market_reference_lookup` | props | **(c)** | picks newest row per preferred book by `LastUpdated` | Ordering unchanged within one producer format |
| C22 | app.py:40306 | `raw_data` | props | **(c)** | string sort, first row per stat | Lexical ISO-Z still orders correctly |
| C23 | app.py:2236, 19221 | `PROP_MARKET_COLUMNS` / `normalize_props_market_data` | props | **(e)** schema | ensures the column exists (NaN) | Retiring needs a list edit |
| C24 | app.py:5739, 6456 | `build_mlb_prop_board` / `build_wnba_prop_board` row `last_updated` | MLB/WNBA props | **(e)** | Carried in the row dict. No template, JS or Python read found (grepped `last_updated` across templates/static/app) | none |
| C25 | app.py:15721 | `load_mlb_game_context_lookup` payload `last_updated` | MLB context | **(e)** | not read | none |
| C26 | app.py:41566 | `_load_derivative_prop_rows` `last_updated` | all props (`DERIVATIVE_SPORT_PROP_PATHS :41450`) | **(e)** | derivatives.html does not render it | none |
| C27 | app.py:3178-3193 | `_format_nfl_current_roster` | roster (P12) | **(e)** passthrough | none | safe |

Already migrated by hotfix 17b5e69 (read `SourceUpdatedAtUTC`, **not** `LastUpdated`, verified): `_quote_from_row` 33355-33372, `_quote_freshness_failure` 33511, `build_nfl_floor_board` newest-row sort 31608-31610, `evaluate_nfl_player` `feed_ts` + per-book `ts` 33115-33136, `_build_best_lines_snapshot` per-offer `updated` 19857-19860/19917, `_nfl_sgp_leg_menu` prop legs 48790-48794. Guarded by `qc_props_quote_source_time.py`.

### Other code

| # | file:line | Function | Reads | Class | Behaviour | ISO-Z impact |
|---|---|---|---|---|---|---|
| C28 | services/feed_validation.py:113-124 + specs 486-570 | `validate_*`: required col, parse check, **timestamp REGRESSION reject** (`new max < prior max`) | game lines, props (generic/NBA slate/football event), futures | **(a)** publish gate | `utc=True` treats zone-less as UTC. Internally consistent per box | **Forward change is safe**: ET→UTC moves instants later, so no false regression. **Rollback hazard**: writing zone-less ET after ISO-Z would read 4-5 h earlier → `timestamp REGRESSION` → REJECT. **Retire** breaks `required_cols` |
| C29 | archive_daily_candidates.py:144-148 → app.py:11926-11940 | `archive_available_props_for_sport` | props, 5 sports | **(a)/(d)** record keying | `SnapshotDate` = `.date()` of the **first row's** `LastUpdated`. On prod that is the UTC fetch date, so fetches after 7 pm EST land on **tomorrow's** SnapshotDate. Effect on grading: **not verified** | Aware UTC `.date()` gives the same wrong day. Needs explicit ET conversion (`to_eastern_date_str`) |
| C30 | refresh_live_scores.py:163 | catch-up gate | live scores | **(a)** | explicit UTC, correct | safe |
| C31 | recover_odds_fetch.py:117-120 | receipt `data_through` | any artifact | **(d)** | `utc=True` labels zone-less ET game-line stamps as UTC, so the receipt is 4-5 h off | Becomes correct |
| C32 | report_feed_availability.py:95,132 | `_DATE_COLS` fallback for schedule dates | schedules | **(d)/(e)** | Last fallback after Date/CommenceDate/…; effectively unused for schedule files that have `Date` | aware parse → UTC `.date()` (would shift) if ever reached |
| C33 | ingest_lookup_market_changes.py:65, 111 | observation hash `book_updated_raw`, `source_updated_raw` | props (dark; `LOOKUP_CHANGE_ENABLED=0`, no prod job) | **(c)** dedup + lineage | Uses the fetch-time `LastUpdated` as "provider update" identity, so every fetch looks like a new provider observation. Player Check "Book Updated {…} (tz unknown)" (player_check.html:128) shows it | Format change → **every hash changes** → one-time re-observation of all quotes. Version the hash or switch to `SourceUpdatedAtUTC` first |
| C34 | fetch_player_props.py:677 | `merge_market_history` sort | prior props file | **(c)** | orders prior rows before picking previous Open/Close | safe within one format |
| C35 | fetch_game_lines.py:339,351; fetch_futures_odds.py:210,223 | history sort tiebreak + passthrough | own history | **(c)** | `SnapshotAt` is the primary key; `LastUpdated` breaks ties only | safe |
| C36 | import_props.py:130-132,282 | alias map | manual sheet | producer-side alias | — | retire with P2 |
| C37 | services/freshness_contract.py:13,32 | docstring "CLOCK A reads `LastUpdated`" | — | **(d)** doc | Stale once migrated (props already read SourceUpdatedAtUTC) | doc edit |
| C38 | diag_nfl_props_source_fields.py:8,80,120 | diagnostic | NFL props | **(d)** | presence check | none |
| C39 | run_all_scorecards.py:65,332 | comments only | — | **(d)** | — | none |

Not consumers (verified by grep, no `LastUpdated`): `run_daily.py`, `generate_run_status.py`, `qc_odds_feed.py` (Clock B / file mtime), `templates/`, `static/`, `marketing/generators/`, `ops/`, `deploy/`.

### QC scripts (21) — class (d)

Pin current semantics (break or need edit on a producer change):
- `qc_nfl_props_source_fields.py:10,61-63,95` asserts `LastUpdated` is non-empty ("Eastern display"). Breaks on **retire/rename**; its docstring is already inaccurate (it is fetch time).
- `qc_nfl_props_source_time.py:55,74-77` treats `LastUpdated` as the fetch-time fallback (`r["LastUpdated"]`). **KeyError on rename.**
- `qc_props_quote_source_time.py` (static guards that authority code never reads `LastUpdated`). Keep. Extend its list to new consumers.

**Mask the bug:** their fixtures write `LastUpdated` in **process-local naive** time (`datetime.now()`), which matches `get_lines_refresh_meta`'s naive-now and never exercises the real producer's ET semantics on a UTC process:
- `qc_game_lines_freshness.py:24,30`
- `qc_market_lookup_freshness.py:22-26`

Fixture-only (update when the format or column changes):
- `qc_feed_availability`, `qc_freshness_contract`, `qc_run_status_degraded`
- `qc_lookup_change_store` (hash), `qc_matchup_center_cache_version`, `qc_nba_gated_market_facts`, `qc_nba_market_only`
- `qc_ncaaf_odds_single_writer`, `qc_odds_recovery_preflight`, `qc_recover_odds_wrapper`, `qc_props_slate_turnover`, `qc_slate_validation`
- `qc_sgp_kickoff_gate`, `qc_ticket_kickoff_gate`, `qc_unpriced_line_legs`
- `qc_nfl_roster_freshness` (explicit UTC; fine)

### Class counts (distinct code sites, excluding QC)

| Class | Count | Sites |
|---|---|---|
| (a) AUTHORITY | 13 | C1, C2 (5 loaders, counted once), C3, C4, C5, C6, C8 (3 builders, counted once), C13, C14, C19, C28, C29, C30. C7 also gates |
| (b) CUSTOMER DISPLAY | 12 | C1 label, C3 label, C7, C8 notes, C9, C10, C11, C12, C15, C16, C17, C18, C20 |
| (c) SORT/DEDUP | 5 | C21, C22, C33, C34, C35 |
| (d) OPS/QC | 6 code + 21 QC | C31, C32, C37, C38, C39, C36(alias) + qc_* |
| (e) dead/unused | 5 | C23, C24, C25, C26, C27 |

(C1/C3/C7/C8 count in both (a) and (b).)

---

## F-T1.3 Proposed producer contract (not implemented)

**Principle:** `LastUpdated` carries two incompatible meanings: provider-ET for lines/futures, and mostly fetch-local for props. So **no in-place rewrite of `LastUpdated` is safe**. Writing ISO-Z into the same column silently changes 4 display sites (C9, C16, C17, C18), every lookup-store hash (C33), and gives a rollback-reject hazard (C28). Each feed gets **explicit, single-meaning columns**; `LastUpdated` is then retired.

| Feed | Provider time (explicit) | Our capture time (explicit) | `LastUpdated` |
|---|---|---|---|
| Props (P1) | `SourceUpdatedAtUTC`: exists, keep | **add `FetchedAtUTC`** (run-level `...Z`) | retire |
| Game lines (P3/P4) | **add `SourceUpdatedAtUTC`** = `to_utc_iso(bookmaker.last_update)` | **add `FetchedAtUTC`**; `SnapshotAt` already explicit | retire |
| Futures (P5) | **add `SourceUpdatedAtUTC`** (market, else bookmaker) | **add `FetchedAtUTC`** | retire |
| First-half (P6) | none (provider time not captured) | rename `LastUpdated` → **`FetchedAtUTC`** (value already UTC-Z fetch time) | retire |
| Live scores (P11), roster (P12) | already explicit UTC | — | optional rename for consistency; no risk |
| NFL_LineOpen (P9) | — | `FirstSeen` → ISO-Z (`FirstSeenAtUTC`) | — |

Recommended option: **"add explicit columns → migrate consumers → retire LastUpdated"**. Rejected alternatives:
- "keep `LastUpdated` but write ISO-Z": silent semantic change for C9/C16/C17/C33/C28.
- "rename props `LastUpdated` → `FetchedAtUTC` in one step": breaks C28 `required_cols`, `PROP_MARKET_COLUMNS`, QC pins.

**Migration order the consumer list implies**

1. **Additive producers.** P3/P4/P5 add `SourceUpdatedAtUTC`; P1/P3/P5 add `FetchedAtUTC`. `LastUpdated` stays unchanged. Add a producer QC for lines/futures mirroring `qc_nfl_props_source_time.py`. No consumer changes, so zero behaviour change.
2. **Authority consumers** (prod-risk order):
   - C3 `get_lines_refresh_meta` → `SourceUpdatedAtUTC` vs aware UTC now. This auto-fixes C4/C5/C6/C7/C8. It is the one with a live prod bias, and it can be fixed independently of the rest.
   - C1 residual: when `SourceUpdatedAtUTC` is all blank, stop deriving `age_hours` from `LastUpdated` (decide: unknown, or `FetchedAtUTC`).
   - C28 `timestamp_col` → explicit column (and `required_cols`).
   - C29 SnapshotDate → `to_eastern_date_str(FetchedAtUTC)`.
3. **Display consumers.**
   - C9 `market_updated` → `_source_time_label`.
   - C16 market-only "Book Updated" → `SourceUpdatedAtUTC`.
   - C17/C18 SGP game/period legs → explicit ET label; first-half labelled as capture time, not provider time.
   - C3 label → explicit ET.
4. **Sort/dedup.** C21/C22/C34/C35 → explicit column. C33 → versioned hash on `SourceUpdatedAtUTC` (dark, so it can go anytime before the flag turns on).
5. **QC.** Replace process-local fixtures (`qc_game_lines_freshness`, `qc_market_lookup_freshness`) with real-producer-format fixtures run under `TZ=UTC` (pattern already in `qc_props_quote_source_time.py:56-61`). Update the pins (`qc_nfl_props_source_fields`, `qc_nfl_props_source_time`).
6. **Retire.** Drop `LastUpdated` from P1/P2/P3/P4/P5 writers, `PROP_MARKET_COLUMNS`, `import_props` alias, feed_validation specs and the freshness_contract docstring. Rename P6. Prior on-disk files still carry the old column, so readers must tolerate its absence (C1/C3 already handle "column absent").

---

# F-T2 — Other-sport timestamp audit

## F-T2.1 Feed files: does the producer write a zone-explicit source time?

| Feed file | Sports | Producer | Zone-explicit provider source time? | Other explicit clocks | Zone-less stamp |
|---|---|---|---|---|---|
| `data/props/NBA_Props.csv` | NBA | fetch_player_props.py:453 | **Yes** `SourceUpdatedAtUTC` (market-level; presence in NBA responses **not verified**, diag covered NFL only) | `EventCommenceAtUTC` :452 | `LastUpdated` :449 (fetch-local) |
| `data/props/NBA_Props.csv` (manual) | NBA | import_props.py | **No** | — | `LastUpdated` (unknown zone) |
| `data/props/WNBA_Props.csv` | WNBA | fetch_player_props.py:453 | Yes (presence unverified) | yes | yes |
| `data/props/MLB_Props.csv` | MLB | fetch_player_props.py:453 | Yes (presence unverified) | yes | yes |
| `data/props/MLB_Props_Fallback.csv` | MLB | **no writer in repo** (read at app.py:2594/2601) | **No** | — | whatever exists |
| `data/props/NFL_Props.csv` | NFL | fetch_player_props.py:453 | Yes (diag-verified present) | yes | yes |
| `data/props/NCAAF_Props.csv` | NCAAF | fetch_player_props.py:453 | Yes (presence unverified) | yes | yes |
| `data/odds/{NBA,WNBA,MLB,NFL,NCAAF,NFL_Preseason}_Odds.csv` + `data/schedules/*_Odds.csv` | all | fetch_game_lines.py:182 | **No** | **none**: no commence UTC either (Date/Time are ET strings, :150-160) | `LastUpdated` ET |
| `data/tracking/*_LineMovementHistory.csv` / `Current.csv` | MLB, WNBA (4 h), NBA/NFL/NCAAF (daily) | fetch_game_lines.py:315,349 | **No** | `SnapshotAt` (explicit offset, fetch) | `LastUpdated` ET passthrough |
| `data/historical/*_OddsAPI_GameLines_History.csv` | NCAAF/NFL/CBB | fetch_oddsapi_historical_game_lines.py | **No** | `CommenceTime` raw provider (explicit), `SnapshotDate` | `LastUpdated` ET |
| `data/futures/Futures_Odds.csv` | futures | fetch_futures_odds.py:~118-138 | **No** | — | `LastUpdated` ET |
| `data/tracking/Futures_LineMovement*.csv` | futures | fetch_futures_odds.py:193 | **No** | `SnapshotAt` explicit | `LastUpdated` ET |
| `data/odds/{NFL,NCAAF}_FirstHalf.csv` | NFL/NCAAF | fetch_football_first_half.py:86 | **No** (provider time not captured) | `LastUpdated` is UTC-Z **fetch** time (explicit) | — |
| `data/odds/NCAAF_CFBD_Lines.csv` | NCAAF | fetch_ncaaf_slate_cfbd.py:171 | No (CFBD has no provider quote time) | `FetchedAtUTC`, `StartDateUTC` | — |
| `data/tracking/NFL_PropLines_Archive.csv` | NFL | capture_nfl_prop_lines.py | Yes (`SourceUpdatedEarliest/LatestUTC`) | `BKCapturedAtUTC` | — |
| `data/tracking/NFL_LineOpen.csv` | NFL | capture_nfl_line_open.py:62 | No | — | `FirstSeen` UTC zone-less |
| season markets | multi | fetch_season_markets_sportsdataio.py / refresh_season_markets.py | `SourceUpdatedAt`: **zone unverified** | `SnapshotAt` explicit | — |
| live scores | all | refresh_live_scores.py:221 | Yes (`LastUpdated` explicit) | — | — |
| NFL roster | NFL | fetch_nfl_current_roster.py:77 | n/a (fetch) explicit `+00:00` | — | — |

**Feeds lacking a zone-explicit provider source time:** all game-lines odds files (6 sports), line-movement history/current, historical Odds-API lines, futures (+history), first-half, the manual NBA import, and the MLB fallback.

## F-T2.2 Customer-facing "updated / refreshed / as of / captured" labels

| Template:line | Label | Context field ← builder ← column | Sport(s) | Zone presented | On UTC prod |
|---|---|---|---|---|---|
| props.html:257, 290 | stat card | `refresh_meta.last_updated` ← `get_props_refresh_meta` ← `SourceUpdatedAtUTC` (else `LastUpdated`) | NBA/WNBA/MLB/NFL/NCAAF props pages | "… ET" when SourceUpdatedAtUTC is populated; **no zone** on the LastUpdated fallback | correct ET if the column is populated; **UTC wall clock unlabelled** if the column is absent |
| heatmap.html:184 | same | same | per route | same | same |
| smart_picks_v2.html:525 | same | same | same | same | same |
| parlay_formula.html:249 | same | same | same | same | same |
| mlb_dashboard.html:203 | same | `load_mlb_live_props_feed` | MLB | same | same |
| wnba_dashboard.html:141; wnba_matchup.html:91 "Refresh status:" | same | `load_wnba_live_props_feed` | WNBA | same | same |
| dashboard.html:1224 "Props refreshed …" | `nba_data_pulse.props_last_updated` ← C15 | NBA | same ("refreshed" while the value is provider market time: wording) | same |
| slate_pulse.html:65 | `r.updated` + age ← C11 | all 5 | same | same |
| best_lines.html:171 | `feed.updated` ← C12 | all 5 | same | same |
| best_lines.html:126 | `r.updated` ← `_source_time_label(SourceUpdatedAtUTC)` | all 5 | explicit ET | correct (hotfix) |
| player_check.html:189 / per-book ts | `feed_ts` ← SourceUpdatedAtUTC | NFL | explicit ET | correct (hotfix) |
| player_check.html:128 "Book Updated … (tz unknown)" | lookup-change `source_updated` ← `LastUpdated` (C33) | NFL (dark, flag off) | none; "(tz unknown)" | fetch time mis-attributed as book time (dark) |
| market_only_board.html:48 "Book Updated" + footnote :54 | `book_updated_at` ← `LastUpdated` (C16) | **NBA (gate off), WNBA** | none, "(tz unknown)" | **our UTC fetch time presented as the bookmaker's quote time** |
| football_method_board.html:79-90 "odds feed last refreshed …" + warning | `lines_refresh_meta` ← C3 | NFL, NCAAF | **no zone** (value is ET) | inflated age (+5 h) in the warning; rows suppressed |
| nfl/cfb totals stale notes (`tb_stale_note`, `nt_stale_note`) | C3 warning | NFL, NCAAF | no zone | inflated age |
| dashboard.html:1304, matchup.html:130 "Last update: …" | `market_updated` ← C9 (game-lines `LastUpdated`) | NBA dashboard/matchup (+ any `build_game_market_lookup` caller) | **no zone** (value is ET) | value correct, unlabelled. Suppressed entirely if C3 says stale |
| menu_board.html:140,232; _ticket_editor.html:148,167; _unpriced_context_lines.html | `updated_label` ← `_updated_label` | team-line legs ← `_feed_stamp_to_utc(LastUpdated)`; prop legs ← SourceUpdatedAtUTC | NFL/CFB/MLB legs | explicit "… ET" | correct |
| sgp_workbench.html:127,150,216 | `leg.timestamp (leg.tz)` | game legs ← NFL_Odds `LastUpdated` (ET); period legs ← NFL_FirstHalf `LastUpdated` (UTC-Z fetch); prop legs ← SourceUpdatedAtUTC | NFL | "provider time; tz unverified" / "provider source time" | game legs: ET value, label hedged. **Period legs: fetch time labelled "provider time"** |
| nfl_matchup_center.html:67 "captured" | `line_move.first/last_captured` | `_line_movement_for_game` never sets these keys (grep), so it falls back to `odds_as_of` = file mtime "… ET" | NFL | ET | dead key; as_of correct |
| game_context.html:44 "context updated …" | `context_updated` ← MLB context `LastUpdated` (naive local) | MLB | **no zone** | **UTC wall clock unlabelled** |
| injuries.html:11 "Last updated:"; _injury_rows.html:17 | `Updated` ← `fetch_injuries`/`fetch_sport_injuries` naive `datetime.now()` | multi | **no zone** | **UTC wall clock unlabelled** |
| cfb_first_half / cfb_buy_low / nfl_buy_low / green_light page-kicker | `updated` = `datetime.utcnow()… UTC` (render/build time) | NFL/CFB | explicit "UTC" | honest zone; it is build time, not data time |
| season_markets.html:97 | `latest_snapshot` (SnapshotAt raw ISO with offset) | multi | raw offset | unformatted but explicit |
| nfl_milestones / riding_the_wave / heatmap "updated" | file-mtime → ET (not market columns) | NFL | ET | not in scope; not traced further |

## F-T2.3 Ranked by user risk

**HIGH: a misleading time or a wrong freshness decision presented as current**

1. **`get_lines_refresh_meta` reads ET-naive provider stamps against a UTC-naive clock (C3).** On the UTC prod box every game-lines age is inflated by +5 h (EST, since Nov 1) / +4 h (EDT). The 6 h live window collapses to about 1 h of real age, so it **fails closed early**:
   - current lines suppressed via `build_game_market_lookup` for every board/command center, all sports
   - NFL/NCAAF live-games, CFB context slate, football method pages, NFL/CFB totals boards, Matchup Center
   - customer warnings show the inflated age ("These game lines are 7h old…") with an unlabelled time

   Derived from code plus a local arithmetic simulation; **not observed on prod**. Read-only verification: on the box compare `date -u` with `max(LastUpdated)` in `/opt/bankrollkings/data/odds/NFL_Odds.csv`, or look for the stale banner on `/tools/nfl-totals`. It is the mirror image of the 11-04 incident: same root cause (zone-less stamp, wrong assumed zone), opposite consumer assumption. `qc_game_lines_freshness`/`qc_market_lookup_freshness` cannot catch it because their fixtures are process-local.
2. **Market-only NBA/WNBA board "Book Updated" (C16).** Shows our fetch time (UTC on prod), and the page footnote explicitly tells users it is the bookmaker's quote-update time, not BK's ingest time. "(tz unknown)" is shown, but the attribution is false.
3. **Props refresh labels on the LastUpdated fallback path (C1).** On every non-NFL props surface (table above), if a sport's props file lacks the `SourceUpdatedAtUTC` column, the label is the UTC fetch wall-clock with no zone, which users will read as ET. Affected files: the pre-2026-10-24 schema, manual `import_props`, or the MLB fallback alone. Whether any prod props file currently lacks the column was **not verified**. Related residual: column present but blank → honest label, but the stale authority (`age_hours`) still uses fetch time.

**MEDIUM**
4. `archive_daily_candidates` SnapshotDate (C29): UTC date of fetch, rolls a day early after 7 pm EST. Record/lineage error; grading impact unverified.
5. MLB `game_context` "context updated" (C20) and the injuries "Last updated" / per-row `Updated`: UTC wall clock unlabelled on prod (not market prices, but presented as current).
6. SGP period legs (C18): our fetch time labelled "provider time".
7. Dev boxes are **not** Eastern: this machine is Pacific, and the June workstation data shows Central. Local `get_lines_refresh_meta` is fail-*open* by 2-3 h, and zone-less fetch stamps written locally carry PT/CT. CLAUDE.md §5's "US-timezone dev box agrees with Eastern" is not reliable here.

**LOW: correct value, merely unlabelled or hedged**
8. dashboard/matchup "Last update:" (C9): ET value, no zone.
9. SGP game legs (C17): ET value, labelled "tz unverified".
10. Football method board "last refreshed" label (C7): ET value, no zone. Its age is item 1.
11. Research page kickers: explicit "UTC" build time (zone honest; not data time).
12. Season markets `latest_snapshot` raw ISO; SportsDataIO `SourceUpdatedAt` zone unverified.

**INTERNAL**
13. `recover_odds_fetch` `data_through` labels ET stamps as UTC (receipt off by 4-5 h).
14. `feed_validation` regression gate rollback hazard (C28).
15. Lookup-store hash uses fetch time as provider identity (C33, dark).
16. `NFL_LineOpen.FirstSeen` UTC zone-less.
17. `*_LineMovementHistory.SnapshotAt` is sorted lexically (`app.py:19713`). Offsets mix across machines and DST; prod-only writes are uniform `+00:00`.

---

## Could not determine (read-only limits)
- The prod system/process timezone (assumed UTC per CLAUDE.md; no TZ override found in repo units).
- Whether `market.last_update` is populated in event-odds responses for NBA/WNBA/MLB/NCAAF (the diag/QC cover NFL), and so whether non-NFL refresh labels on prod show a time or "Update time not recorded".
- Whether every prod props CSV currently carries the `SourceUpdatedAtUTC` column (local dev files do not).
- Whether bulk-`/odds` `bookmaker.last_update` is always present for game lines. If absent, `LastUpdated` is blank → C3 reports 'Unknown' and never stale.
- Whether candidate-archive `SnapshotDate` feeds grading/matching (only sort uses were found at app.py:11800/11848/12744/12819/12956).
- The SportsDataIO `Updated` field's zone.
