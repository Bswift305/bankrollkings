# NCAAB discovery audit (read-only, 2026-11-04) — governed copy

> Read-only discovery at exact production `17b5e69` for the P1 "NCAAB Page Program — season live" track. Copied from the working report. **No implementation until the owner reviews this audit.** Credit figures are estimates (per-event / scores credit rates inferred, not verified with the provider).

---

# NCAAB Page Program — season live: READ-ONLY discovery audit

- Date: 2026-11-04
- Worktree: `.claude/worktrees/props-utc` @ `17b5e6979098096c10d38ed3a5d1c27e77c3610e` (prod master)
- Scope: men's college basketball (NCAAMB); women's (NCAAWB) noted where trivially visible.
- Method: code/doc reading plus a read-only listing of the main checkout's local `data/`. No code edits, no fetchers, no network, no prod access.
- Notation: **[V]** = I verified it in code or data. **[I]** = inference (general provider knowledge or reasoning) that has **not** been verified here. Treat every [I] as a check to run before building.
- Line numbers refer to `app.py` unless another file is named.

---

## 0. Bottom line

College hoops today is **routes plus themed shells with no data pipeline**. There is no NCAAB fetcher, no output-path mapping, no schedule, no scores, no team identity table, no metrics source, and no run_daily wiring. The registry entry points at loaders that **do not exist**. The good news is that the generic Odds API machinery (bulk game lines, quota receipts, atomic validated publish, line-movement history) is reusable for full-game spread/ML/total once an NCAAB mapping is added. Two latent bugs in that shared machinery must be fixed before any NCAAB price is shown:

1. The game-lines freshness gate fails open because the formatter strips `LastUpdated`.
2. `SpreadOdds` can silently carry the away side's price.

---

## 1. Inventory (with evidence)

### 1.1 Registry, routes, templates, nav, shells

| Item | Evidence | State |
|---|---|---|
| Registry `NCAAMB` / `NCAAWB` | `sport_registry.py:134-155`: `live=False`, `stat_column_map=None`, `identity_ok=False`, `requires_play_verdict=False`, `calibrator=None`, notes "Themed shell only…" | [V] declared, not live |
| Declared loaders | Registry names `load_ncaamb_props`, `load_ncaamb_gamelogs`, `load_ncaamb_game_market_odds` (and the ncaawb equivalents). Grep finds **only** `load_ncaamb_schedule` (`app.py:21139`) and `load_ncaawb_schedule` (`21165`). The others **do not exist** | [V] registry points at missing functions |
| `qc_sport_registry.py` | A not-live sport is only a **warning** (`:49`, `:123-125`), so the missing loaders pass today | [V] |
| `/sports/ncaamb`, `/sports/ncaawb` | Catch-all `@app.route('/sports/<league>')` (`39322`) branches to `college_hoops_command_center.html` (`39344-39376`) | [V]. `docs/PROJECT_MAP.md:204` still says `under_construction.html`, so the doc is stale |
| `/sports/ncaamb/props` (+ `<filter_type>`) | `39445-39454` → `_render_college_hoops_props` → **fabricated example rows** with `confidence` 60–71, `over_rate`, `game_total 142.5`, real team abbreviations (DUKE, UNC, KAN, …) and `book: 'Example'` (`39388-39414`) | [V] **Honesty risk.** These are invented confidence numbers on real team names. They must not survive into a live product (doctrine §7 forbids composite confidence) |
| `/sports/ncaamb/market-edge`, `/trends`; `/parlay?sport=ncaamb` | `39549-39566`, `43371-43378`. They render empty `smart_picks_v2.html`, `trend_board.html` and `parlay_formula.html` with `sort_by='confidence'` | [V] shells |
| Access gate | `_college_hoops_access_gate` (`39457`) checks `get_plan_rank('pro')` and `user_has_sport_access`, which are legacy tier concepts. CLAUDE.md §11 says gating is now binary `all_access` | [V] works through normalization, but the naming is legacy |
| Nav | `SPORTS_NAV_ITEMS` (`36827-36835`); sidebar `templates/_sidebar.html:210-231` labels the link **"Live Board & Lines"** for a shell; `ncaamb_count` is hard-wired to 0 (`1623`) | [V] the label overstates what exists |
| Hubs | Universal hubs list CBB as `status: 'watch'` (`36848-36905`); Today hub (`23261-23262`) uses `load_ncaamb_schedule` | [V] |
| Launch copy | `SPORTS_LAUNCH_PAGES` (`36812-36823`) promises "Tempo + efficiency tracking", "Team form boards"; `561` says "Full prop boards across … college hoops" | [V] **Over-claim:** no CBB prop board exists |
| Sport profile | `2048-2058` "lean on game line, total, team environment" | [V] direction text only |
| Prop pointers | `prop_pointers.py:146-168` CBB playbook text | [V] text only |
| Officiating | `build_officiating_context.py:54-60`, `build_official_tendency_profiles.py:32-45,74-75` reference `NCAAMB_PlayByPlay.csv` and similar. Local `data/context/NCAAMB_OfficiatingContext.csv` is **header-only** (146 bytes, Jul 28). `fetch_basketball_officiating_assignments.py:15` is NBA-only (`official.nba.com`) | [V] no data |
| Season markets | `fetch_season_markets_sportsdataio.py:56` maps `NCAAMB` → SportsDataIO `cbb`; `services/season_markets.py:10` | [V] code path exists; licence/key status for CBB unknown |
| QCs referencing CBB | `qc_universal_tool_hubs.py:14,61-62`, `qc_plan_access_matrix.py:20-21`, `run_prelaunch_scorecard.py:161` (route render only) | [V] no data QC; no `qc_ncaamb_*.py` exists |

### 1.2 Local data artifacts (main checkout `data/`; local ≠ prod)

- [V] **None for NCAAB.** No `data/odds/NCAAMB_Odds.csv`, `NCAAWB_Odds.csv`, `data/schedules/NCAAMB_*`, scores, gamelogs, props, injuries, rosters or historical files.
- [V] `data/historical/CBB_OddsAPI_GameLines_History.csv` is referenced (`fetch_oddsapi_historical_game_lines.py:22`) but **absent**.
- [V] `data/live_scores/Live_Scores.csv` holds only MLB, NBA, NCAAF, NFL and WNBA rows.
- [V] The only CBB files are the two header-only officiating CSVs.
- Prod data was not inspected (out of scope).

### 1.3 Odds API sport keys

- [V] `basketball_ncaab` appears once, in `fetch_oddsapi_historical_game_lines.py:22`.
- [V] `basketball_wncaab` appears **nowhere** in code or docs.
- [I] Both keys are the provider's published keys. Confirm with a free `/v4/sports` call before building; that call costs no quota per `qc_odds_feed.py:9`.

### 1.4 Full-game spread / ML / total

- [V] `fetch_game_lines.py` has **no** `basketball_ncaab` in `SPORT_OUTPUTS` (`28-59`), `SPORT_DEFAULT_MARKETS` (`63-70`), `SPORT_TRACKING_PREFIX` (`71-78`) or `_sport_tokens` (`100-106`).
- [V] **Hazard:** `--sport basketball_ncaab` today falls back to `SPORT_OUTPUTS[DEFAULT_SPORT]` (`main`, ~`386`), which is the **NBA** output paths. Because `_sport_tokens("basketball_ncaab")` returns `()` (the string contains none of ncaaf/nfl/wnba/nba/mlb), the path/sport guard in `services/feed_validation.py:83-87` is skipped. Only the 50% row-collapse check would stand between an NCAAB fetch and an overwrite of `NBA_Odds.csv`. **Do not run it ad hoc.**
- [V] Not wired anywhere: `run_daily.py` has no basketball college step (`:27-120`), no batch file, no `ops/` or `deploy/` unit. Per CLAUDE.md §7, it would never run on prod.
- [V] **Reusable:** bulk `/odds` call (`228-249`), `QuotaRecorder` receipt and ledger `data/tracking/odds_quota_ledger.jsonl` (`services/odds_quota.py:23`), validation via `GAME_LINES_SPEC` (`feed_validation.py:486-495`), `atomic_write_csv`, `--expected-cost` and `--allow-collapse` guards.
- [V] **Writer defects relevant to an honest board:**
  - `parse_event_markets` (`fetch_game_lines.py:197-208`) stores one `Spread` (home perspective) and one `SpreadOdds`, taken from **whichever outcome comes first**. If the away outcome is first, `Spread` is negated to home perspective but `SpreadOdds` is the **away** price. The price can be attached to the wrong side, and the opposite side's spread price is never stored.
  - `LastUpdated` = `to_eastern_datetime_str(bookmaker.last_update)`, a **zone-less Eastern string**. There is **no** `SourceUpdatedAtUTC` and **no** `EventCommenceAtUTC` (contrast `fetch_player_props.py`, which writes `SourceUpdatedAtUTC`).
  - Commence time is stored only as Eastern `Date` plus `Time`; the UTC instant is discarded.
  - Dedupe key is `Date, Away, Home, Book` (`272`), not `GameID`.
- [I] Default `--bookmakers draftkings` (`DEFAULT_BOOKMAKERS`) means one book unless overridden. CBB needs 4+ books to support best-line and the `SINGLE BOOK` rule (CLAUDE.md §10.3).

### 1.5 First-half spread/total and team totals

- [V] Only `fetch_football_first_half.py` exists. Its `PREFIX` (`34`) covers NFL/NCAAF only.
- [V] It requests `spreads_h1,totals_h1,spreads_q1,totals_q1,team_totals` per event (`93-95`). The docstring says "~2 credits each", which **undercounts the 5 requested markets**.
- [V] It writes a **median consensus line** (`_consensus`, `71-74`): no per-book rows, **no prices**, `LastUpdated` = fetch time (`now`), not the provider timestamp. No `QuotaRecorder`, no atomic write, no validation.
- [V] **Not fit for an honest "real book/price" NCAAB 1H board as-is.** It needs a per-book writer.
- [I] On the Odds API, `spreads_h1`, `totals_h1` and `team_totals` are "additional markets" served only from `/v4/sports/{key}/events/{id}/odds`, billed roughly at (unique markets returned × regions) per event. For NCAAB: 1H spread + 1H total = ~2 credits per event per pass, +1 with `team_totals`. 1H availability for low-major games is likely sparse. Measure with one small dry pass before committing a cadence.

### 1.6 Books, prices, timestamps, freshness (stale-state / timezone)

- [V] **Fail-open freshness bug (shared, affects any sport on this path).** `get_lines_refresh_meta` (`3682-3711`) reads `odds_df['LastUpdated']`. But every `load_*_game_market_odds` routes through `_format_game_market_odds` (`18076-18107`), whose `keep_cols` **drop `LastUpdated`**. The method-view caller (`35523-35528`) passes that formatted frame. The meta therefore returns `last_updated='Unknown'`, `age_hours=None`, **`is_stale=False`, `status='live'`**, and the "stale lines are suppressed" fail-closed contract never fires. *(Verified by reading `keep_cols` and the call chain; not executed.)* Other callers (`6680`, `18295`, `18358`, `51153`, `51225`, `51394`) may pass raw frames; check each.
- [V/I] **Suspected ~5h skew (when `LastUpdated` *is* present).** It parses zone-less Eastern strings to naive timestamps and compares them with naive `pd.Timestamp.now()`. On the UTC prod box (CLAUDE.md §2/§5), that makes fresh lines read about 5h old after the Nov 1 DST end (about 4h in EDT). The window is `LIVE_MARKET_MAX_AGE_HOURS = 6.0` (`services/freshness_contract.py:35`), so a 1h-old line would read about 6h and flip **stale**. This is the same class as the 2026-11-04 props incident, where the props path was fixed to prefer `SourceUpdatedAtUTC` (`3640-3652`). Any NCAAB odds file using `LastUpdated` inherits this. **[I] on the exact prod magnitude.**
- [V] CLOCK B monitoring (`qc_odds_feed.py:42-43`) covers NFL, NCAAF, NBA, WNBA and MLB only. NCAAB would be unmonitored. `REFRESH_CADENCE_MAX_AGE_HOURS` game_lines = 30h (`freshness_contract.py:43-48`).
- [V] Reusable zone-safe helpers already exist: `_canonical_kickoff_utc` (`33382`), `_source_time_label` (`33343`), `services/timeutils.to_eastern_*`, `sports_today_ts()` (`25720`), `get_upcoming_games` anchored on `sports_today_ts` (`25745-25750`).

### 1.7 Final scores / grading

- [V] `refresh_live_scores.py` uses the Odds API `/scores` endpoint. Its `SPORTS` (`72-78`) has **no** `basketball_ncaab`.
- [V] It polls every ~60s, gated by game window and user heartbeat. `fetch_scores` uses `daysFrom=1` (`171-172`).
- [V] **Timezone bug:** `_today_str()` (`89-91`) uses server-local `datetime.now()`, which is UTC on prod, against Eastern schedule dates. That violates CLAUDE.md §5 and would mis-gate the late slates (9–11pm ET tips) common in CBB.
- [V] `fetch_final_scores.py` uses ESPN `site.api.espn.com` with a `Mozilla/5.0` UA (`7-10`, `31`), covering NFL/CFB only. ESPN 403s `BankrollKings*` UAs (memory: project_daily_refresh_failures).
- [I] The ESPN scoreboard is an **undocumented, unlicensed** endpoint. Spoofing a browser UA is a ToS grey area. Do not adopt it for CBB without owner sign-off.
- [V] No NCAAB grading data or grader exists.

### 1.8 ATS / O-U history

- [V] **None exists.** The historical fetcher can target `basketball_ncaab` (`fetch_oddsapi_historical_game_lines.py:19-23`, `/v4/historical/...`), but the output file is absent. That fetcher has **no** `QuotaRecorder` and no validation.
- [I] Odds API historical snapshots are genuine captured provider snapshots, not reconstructions. They are expensive, though (historical calls are billed at a multiple of live, roughly 10× per market per region) and need a paid tier. One season of daily 3-market snapshots ≈ 150 days × 30 ≈ 4.5k credits. That is affordable at 100k/month, but cost must be confirmed by receipt.
- [V] Forward capture is genuine and free once wired: `append_line_movement_snapshot` (`fetch_game_lines.py:288-354`) writes `<PREFIX>_LineMovementHistory.csv` with `SnapshotAt`. Note: `SnapshotAt` = `datetime.now().astimezone()`, which is offset-explicit but uses the process zone.

### 1.9 Team form / splits / pace / efficiency

- [V] No source in code: no CBBD fetcher, no KenPom, no barttorvik, no sports-reference, no TeamRankings for CBB (TeamRankings import is NCAAF-only, `docs/bk_edge_engine_master_checklist.md:632-635`).
- [V] `.env.example` keys: `ODDS_API_KEY`, `CFBD_API_KEY`, `SEASON_MARKETS_*`, Stripe. **No CBB keys.**
- [I] Possible sources:
  - CollegeBasketballData (CBBD, same maintainer as CFBD): an API key is likely required and may be separate from the CFBD key.
  - KenPom: paid and licensed, so **NOT LICENSED**.
  - barttorvik: free site with no published API licence, so scraping/ToS is unclear.
  - sports-reference: ToS restricts scraping and bulk reuse.
- [I] **Derivable without any licence:** home/away/neutral records, margins and points for/against from our own final-scores feed once one exists. Pace and efficiency need possessions, which need box-score data (FGA, ORB, TOV, FTA), not just finals.

### 1.10 Market movement / best lines

- [V] `refresh_line_movement_snapshots.py:24-27` STEPS = MLB + WNBA only. `bk-linemove` units are **not in the repo** (CLAUDE.md §3).
- [V] `_MARKET_MOVER_SPECS` (`19650-19655`) = mlb, wnba, nfl, ncaaf.
- [V] `_BEST_LINE_SPECS` (`19808-19814`) = **player-prop loaders only** (`load_props`, …). Best Lines is a props tool, so there is **no game-line best-line surface for any sport** to reuse directly. `/tools/best-lines` is at `45744`; `/tools/market-movers` at `45670`.

### 1.11 Injuries / availability

- [V] `fetch_sport_injuries.py` covers WNBA, NFL, MLB (ESPN pages) and NCAAF. No CBB entry.
- [V] `refresh_all_sport_injuries.py:5-6,23` keeps NCAAF on manual/last-good data.
- [I] There is no licensed, structured NCAAB availability feed in hand, and college injury disclosure is not uniformly mandated. Treat as **Unavailable** and render it as such, never as "no injuries".

### 1.12 Player props

- [V] `fetch_player_props.py` sport maps (`157-161`) have no college basketball. The CBB "props" page is example data.
- [I] Odds API NCAAB player-prop coverage is limited (few books, mostly high-major games) and would cost per-event credits. Defer.

### 1.13 Identity, aliases, neutral sites, tournaments

- [V] No CBB team table, alias map or conference map. `services/entity_links.py` covers football (`:37-39`).
- [V] `normalize_team_abbr` (`16983-16991`) uses the pro `TEAM_NAME_TO_ABBR`: names containing a space pass through verbatim and single tokens are upper-cased. It has no college disambiguation.
- [V] CFB precedent: `cfb_ats` uses `(GameID, TeamSide)` and "never fuzzy names" (`47713-47735`, `48031`).
- Duplicate and alias risks to design for:
  - Miami (FL)/Miami (OH)
  - St. John's / Saint John's
  - Saint Mary's (CA) / Mount St. Mary's / St. Mary's
  - UConn / Connecticut
  - USC (Southern California) vs South Carolina, and USC Upstate
  - "Texas A&M" vs "Texas A&M-Corpus Christi" / "-Commerce"
  - Loyola Chicago / Loyola (MD) / Loyola Marymount
  - Saint Louis / SIU-Edwardsville; "UNC" family (UNC Asheville / Greensboro / Wilmington)
  - Long Island / LIU; "Penn" vs "Penn State"
- [I] There are 360+ D-I teams. The Odds API supplies `home_team` and `away_team` full names; whether it offers participant ids is unverified. **Identity must key on the provider event id plus an explicit, owner-reviewed alias table, failing closed (UNKNOWN → abstain), never fuzzy matching.**
- [I] **Neutral sites:** the Odds API event payload has `home_team` but no neutral flag (unverified). The Nov MTEs (Maui, Battle 4 Atlantis, PK85, etc.), conference tournaments and the NCAA tournament are mostly neutral sites, and the "home" label there is nominal. Without a neutral-site source, home/away splits for those games are **wrong by construction**. Show `Venue: Unknown` rather than home/away.

---

## 2. Credit-impact model (inferences, assumptions shown)

[I] Assumed slate sizes: Nov–Mar D-I men's ~40 games/day average, 100–160 on peak Saturdays and opening week, conference tournaments ~50–80 per day, and the NCAA tournament's first weekend 16 per day. Women's adds a similar but smaller slate.

| Feed | Unit cost | Cadence | Credits/day | Credits/month (30d) |
|---|---|---|---|---|
| Full-game bulk (h2h, spreads, totals × us) | 3 per call, independent of game count [V per prompt] | every 2h, 12×/day | 36 | ~1,080 |
| same | 3 | every 1h, 18× during 10am–4am ET | 54 | ~1,620 |
| same | 3 | every 30 min, 48× | 144 | ~4,320 |
| 1H spread + total, per event | ~2 per event [I] | 1× daily, avg 40 events | 80 | ~2,400 |
| same | ~2 | 3× daily | 240 | ~7,200 |
| + team totals | +1 per event [I] | 1× daily | +40 | +1,200 |
| Scores `/scores?daysFrom=1` | ~2 per call [I] | 60s poll over a ~14h CBB window | ~1,680 | **~50,000, unaffordable** |
| Scores, finals-only | ~2 | every 15 min, 11am–2am | ~120 | ~3,600 |
| Scores, finals-only | ~2 | hourly | ~32 | ~950 |
| Historical backfill, one season daily | ~30 per snapshot [I] | one-off | — | ~4,500 one-time |
| Women's (same structure) | ~same | mirror the chosen men's cadence | ×~1 | ×~1 |

**Recommended MVP budget [I]:**
- Men's bulk lines hourly: ~1.6k/month.
- 1H once per day, at about 11am ET after openers post: ~2.4k/month.
- Finals hourly: ~1k/month.

That totals **~5k/month, about 5% of the 100k plan**. Adding women's at the same cadence roughly doubles it to ~10k. The current NFL, NCAAF and others use was ~1.4k by 11-03, so headroom is large. **The live 60s scores poller must not be extended to CBB unchanged.**

---

## 3. READINESS MATRIX

| # | Component | Status | Reason / evidence |
|---|---|---|---|
| 1 | Odds API sport key (men) | **PARTIAL** | `basketball_ncaab` in code once (`fetch_oddsapi_historical_game_lines.py:22`); not confirmed against the provider [I] |
| 2 | Odds API sport key (women) | **PARTIAL** | `basketball_wncaab` absent from code and docs; assumed [I] |
| 3 | Registry entry | **PARTIAL** | `sport_registry.py:134-155` exists, `live=False`; 3 of 4 named loaders missing; identity/verdict choices are placeholders |
| 4 | Routes / nav / shells | **PARTIAL** | Routes render (`39322-39566`), but props shell shows fabricated confidence on real team names, the sidebar says "Live Board & Lines", and launch copy over-claims |
| 5 | Full-game spread/ML/total fetch | **PARTIAL** | Generic fetcher is reusable but has no NCAAB mapping, an NBA-path fallback hazard, a SpreadOdds side-ambiguity defect, and no zone-explicit UTC |
| 6 | Wired into prod (`run_daily` / timer) | **BLOCKED** | No step, batch file or unit for CBB (`run_daily.py:27-120`; `refresh_line_movement_snapshots.py:24-27`) |
| 7 | Authoritative schedule / event IDs | **PARTIAL** | Odds API event `id` (→ `GameID`) is the only id source. `load_ncaamb_schedule` reads files that don't exist. Events outside the odds window (unpriced games) are invisible |
| 8 | Team identity / alias table (360+) | **BLOCKED** | No CBB table; normalizer is NBA-centric (`16983`). Needs an owner-reviewed alias map |
| 9 | Neutral-site / tournament flag | **BLOCKED** | No source; Odds API home label is nominal at neutral sites [I] |
| 10 | 1H spread/total | **PARTIAL** | Per-event endpoint pattern exists (football), but the writer is consensus-only with no prices or books; NCAAB availability unmeasured [I] |
| 11 | Team totals | **PARTIAL** | Same as 10 |
| 12 | Book / price / source timestamp, zone-explicit UTC | **BLOCKED** | Game-lines writer emits Eastern zone-less `LastUpdated` only; no `SourceUpdatedAtUTC` or `EventCommenceAtUTC` |
| 13 | Freshness gate (stale suppression) | **BLOCKED** | `get_lines_refresh_meta` fails open (LastUpdated dropped by `_format_game_market_odds`), plus a suspected 5h skew. Shared bug |
| 14 | Feed-health monitoring | **BLOCKED** | `qc_odds_feed.py:42-43` omits CBB |
| 15 | Final scores | **BLOCKED** | Odds API `/scores` poller lacks CBB, has a UTC-"today" bug and 60s cadence is unaffordable for CBB. ESPN path is unlicensed and UA-sensitive |
| 16 | Grading (ATS/OU results) | **BLOCKED** | Depends on 15 + 8; no grader |
| 17 | ATS/OU history (genuine prices) | **BLOCKED** | None stored. Historical Odds API is genuine but needs a paid pull plus receipts [I]. Forward capture is possible once 5 + 6 land |
| 18 | Line movement (forward) | **PARTIAL** | `append_line_movement_snapshot` reusable; needs a CBB prefix + cadence; Market Movers specs omit CBB |
| 19 | Best lines (game lines) | **PARTIAL** | `_BEST_LINE_SPECS` is props-only for all sports; a game-line best-line view must be built (data exists once 5 has multi-book rows) |
| 20 | Team form from own finals (W/L, margin, H/A) | **BLOCKED** | Needs 15; becomes derivable without any licence |
| 21 | Pace / efficiency (possession-based) | **NOT LICENSED** | No box-score source. CBBD (key/terms TBD), KenPom (paid, no licence), barttorvik / sports-ref (ToS/scraping) |
| 22 | KenPom specifically | **NOT LICENSED** | No licence; never scrape |
| 23 | Injuries / availability | **BLOCKED** | No CBB source in `fetch_sport_injuries.py`; no licensed feed. Render as Unavailable |
| 24 | Player props | **BLOCKED** | No fetcher mapping; provider coverage sparse [I]; defer |
| 25 | Officiating context | **BLOCKED** | Header-only CSVs; NBA-only assignment fetcher |
| 26 | Season markets / futures (CBB) | **PARTIAL** | SportsDataIO `cbb` path in code; key/licence for CBB unverified |
| 27 | Credit budget | **AVAILABLE** | 100k/month with ~1.4k used; a ~5–10k/month MVP fits [I estimates] |
| 28 | Timezone helpers | **AVAILABLE** | `services/timeutils`, `sports_today_ts`, `_canonical_kickoff_utc` |
| 29 | Atomic / validated publish + quota receipts | **AVAILABLE** | `feed_validation.py`, `atomic_csv`, `odds_quota.py` (event-aware spec fields at `feed_validation.py:52-56`) |
| 30 | QC suite for CBB | **BLOCKED** | No `qc_ncaamb_*.py` exists |

---

## 4. Top blockers (ordered)

1. **No prod pipeline.** No CBB mapping in `fetch_game_lines.py`, nothing in `run_daily.py` or a timer. Running the fetcher with `--sport basketball_ncaab` today would target **NBA** output files.
2. **Freshness gate fails open** for game lines (`_format_game_market_odds` drops `LastUpdated` → `is_stale=False`), plus the suspected Eastern-naive vs UTC-naive skew. This is a shared bug, so fix it before showing any NCAAB price as "live".
3. **Price/side integrity:** `SpreadOdds` may hold the away price, and only one side's spread price is stored. There are no zone-explicit `SourceUpdatedAtUTC` or `EventCommenceAtUTC` columns.
4. **Identity:** no 360+-team alias table and no neutral-site flag. Without them, matchup, H/A context and grading are unsafe.
5. **Scores/grading source:** an affordable, licensed finals feed. Odds API `/scores` at a finals-only cadence is the licence-clean option; fix `_today_str` UTC.
6. **Metrics licensing:** pace/efficiency is NOT LICENSED until the owner picks a source.
7. **Honesty cleanup of shells:** example confidence rows, "Live Board & Lines" label, "Full prop boards … college hoops" copy.

---

## 5. Proposed first release — "NCAAB Decision Workspace" (design only, NOT built)

**Hard exclusions:**
- No Green Light authority.
- No confidence/edge/composite score.
- No simulations or projections.
- No invented or consensus-as-price numbers.
- No automatic picks, "best bets" ranking or locks.
- No auto-EV or Kelly.
- No "sharp"/"steam" labels.

Every page separates **Fact status** (Verified/Partial/Pending/Stale/Unavailable/Source conflict) from **Research status** (e.g. "Context, not an edge"), per doctrine §11.

### 5.1 Page map

| Page | Route (proposed) | Content | Loop step |
|---|---|---|---|
| A. Slate | `/sports/ncaamb` (replace shell) | Today/tomorrow games (Eastern date from `EventCommenceAtUTC`). Tip time ET, teams, per-book spread/ML/total with **both sides' prices**, book count, "Updated <ET> (source)" per row, fact-status chip. Filters: conference (when the identity table exists), time window, has-1H | Discover |
| B. Markets | `/sports/ncaamb/markets` (replaces market-edge shell) | Full-game and 1H/team-total grids per book. Only the markets actually returned; absent = "Not offered by tracked books", never blank or zero | Discover / Evaluate |
| C. Matchup | `/sports/ncaamb/game/<event_id>` | Market facts on top; then factual team context from **our own finals**: record, L5/L10 margins, home/road/neutral records (neutral only when sourced, else "Venue: unverified"), rest days. Pace/efficiency section shows **Unavailable — source not licensed** until decided | Evaluate |
| D. Trends evidence | panel on C + `/sports/ncaamb/trends` | Streaks (SU, ATS, O/U from **captured** closing prices only) labeled "Context, not an edge — streaks are priced" (CLAUDE.md §10), with n and window | Evaluate |
| E. Best lines + movement | panel on A/C + `/tools/best-lines?sport=ncaamb` (game-line variant) | Best number/price per side across books, open→current from captured snapshots with `FirstSeenUTC`, snapshot count; "1 snapshot — no movement read" state; `SINGLE BOOK` flag | Evaluate |
| F. Evidence ledger | panel on C | Three columns shown together: **Supporting / Contradicting / Missing** (e.g. "Injury availability: Unavailable", "Neutral site: unverified", "Pace: not licensed"). Counts by type, no score | Evaluate |
| G. Save / Track | existing King's Tickets / Bet Tracker / Decision Journal with `sport=ncaamb` | Save a leg at the shown book/price/time; tracker captures price taken; CLV vs captured close | Build / Save / Track / Learn |

**Mobile flow:** Slate (card per game: teams, tip ET, best spread/total chips, updated-ago, status chip) → tap → Matchup, with stacked sections in order Market Facts → Context → Evidence ledger → "Add to ticket". Book grids collapse to a "best + N books" chip that expands into a scrollable table.

**Desktop:** Slate as a table with sticky header, plus a right-side drawer preview of Matchup; Markets as a full per-book grid.

### 5.2 MVP vs deferred

**MVP (men's only):**
1. Full-game per-book lines with zone-explicit times.
2. Slate page and Matchup page (market facts plus own-finals form, with H/A shown only where neutral status is known or flagged).
3. Forward line-movement capture with open→current display.
4. Game-line best-line panel.
5. Finals plus ATS/OU grading from **captured** closes.
6. Evidence ledger with honest Unavailable states.
7. Save/track handoff.
8. 1H spread/total per book, **only if** a dry pass shows meaningful coverage; otherwise deferred.
9. Shell honesty cleanup.

**Deferred:**
- Women's, unless the owner opts in at the same contract.
- Player props.
- Pace/efficiency (licence).
- Injuries/availability.
- Officiating.
- Historical ATS backfill (paid).
- Team totals.
- Futures.
- Conference/tournament bracket context.
- Parlay builder for CBB.
- Any Research-status promotion.

### 5.3 Data contracts (proposed)

**`data/odds/NCAAMB_GameLines.csv`** (one row per event × book × market × side; long form):

`EventId` (provider id) · `SportKey` (`basketball_ncaab`) · `EventCommenceAtUTC` (ISO-8601 `Z`) · `EventDateET` (derived via timeutils) · `HomeTeamProvider` · `AwayTeamProvider` · `HomeTeamId` · `AwayTeamId` (from alias table; blank → UNKNOWN) · `NeutralSite` (`TRUE/FALSE/UNKNOWN`) · `Book` · `MarketKey` (`h2h|spreads|totals|spreads_h1|totals_h1|team_totals`) · `Period` (`FG|H1`) · `Side` (`HOME|AWAY|OVER|UNDER`) · `Point` (signed from that side's perspective; blank for h2h) · `PriceAmerican` · `SourceUpdatedAtUTC` (bookmaker/market `last_update`, `Z`) · `FetchedAtUTC` · `FetchRunId`

There is no `LastUpdated`, or if one is kept for legacy readers, it is documented as display-only and never aged from.

**`data/tracking/NCAAMB_LineSnapshots.csv`:** the same columns as append-only history, plus `SnapshotAtUTC`. Open = first snapshot per `(EventId, Book, MarketKey, Side)`; close = last snapshot before `EventCommenceAtUTC`.

**`data/scores/NCAAMB_Finals.csv`:** `EventId · EventCommenceAtUTC · HomeTeamId · AwayTeamId · HomeScore · AwayScore · Completed (bool) · Source · SourceUpdatedAtUTC · FetchedAtUTC`.

**`data/reference/NCAAMB_Teams.csv` (owner-reviewed):** `TeamId · CanonicalName · Conference · Division (D1/UNKNOWN) · ProviderAlias (one row per alias, exact match) · AliasSource · ReviewedBy · ReviewedAtUTC`.

**`NCAAMB_Results.csv` (graded):** `EventId · Book · MarketKey · Side · ClosePoint · ClosePrice · CloseSnapshotAtUTC · Result (WIN/LOSS/PUSH/NO_CLOSE)`. `NO_CLOSE` is used when no snapshot exists; it is never reconstructed.

### 5.4 Acceptance tests (QC names proposed; all offline)

- **`qc_ncaamb_game_lines_contract.py`:**
  - Schema check.
  - Every time column ends in `Z` / parses as UTC-aware; zone-less values are rejected.
  - `Point`/`Price` are finite.
  - Side ∈ allowed.
  - Both sides present or the row is flagged PARTIAL.
  - Spread sign is consistent across HOME/AWAY.
  - No row with Book blank.
  - No price where `MarketKey` is not provider-returned.
- **`qc_ncaamb_sport_isolation.py`:** a fetch with `--sport basketball_ncaab` can only write a path containing `NCAAMB`, and an NBA path is refused (adversarial: simulate a missing mapping).
- **`qc_ncaamb_freshness.py`:**
  - Fixtures at UTC 23:30 (= 6:30pm ET) and 01:30 UTC (evening slate); "today" resolves Eastern.
  - A 1h-old line on a UTC-clock process is **not** stale.
  - A 7h-old line **is** stale and suppressed.
  - Missing source timestamp → "Update time not recorded" and **not live** (fail closed).
- **`qc_ncaamb_identity.py`:**
  - Adversarial names: "Miami (OH) RedHawks" vs "Miami Hurricanes"; "St. John's Red Storm" vs "Saint Joseph's Hawks"; "Saint Mary's Gaels" vs "Mount St. Mary's"; "USC Trojans" vs "South Carolina Gamecocks" vs "USC Upstate"; "UConn" vs "Connecticut"; "Texas A&M-CC".
  - Each must resolve exactly, or to UNKNOWN (abstain); no fuzzy merges.
  - Unknown share is reported.
- **`qc_ncaamb_neutral_site.py`:** a game with `NeutralSite=UNKNOWN` never contributes to home/road splits.
- **`qc_ncaamb_grading.py`:**
  - A pushed spread → PUSH.
  - A game with no pre-tip snapshot → NO_CLOSE (never graded from post-tip lines).
  - A postponed or cancelled game is not graded.
  - A doubleheader/same-teams-twice scenario (MTE rematch) is keyed by EventId.
- **`qc_ncaamb_honesty.py`:** rendered pages contain no `confidence`, `score`, `lock`, `sharp`, `steam` or `best bet` tokens; no "Example" rows; unavailable components render the Unavailable label, never 0 or blank.
- **`qc_ncaamb_quota.py`:** each fetch prints a receipt; cost ≤ `--expected-cost`; per-day ledger sum ≤ budget.
- Also: add CBB to `qc_odds_feed.py` families, flip `live=True` only when `qc_sport_registry.py` passes with real loaders, and run `py -3 -m py_compile app.py`.

### 5.5 How it serves the owner's selection loop

- **Discover:** the Slate surfaces every priced game with real book/price/time. These are options, not picks.
- **Evaluate:**
  - Matchup page shows market facts, then own-finals context.
  - Evidence ledger puts Supporting, Contradicting and Missing side by side.
  - Best lines and movement show where the number is.
  - `SINGLE BOOK` and longshot-style avoidance flags only where evidence supports them. CLAUDE.md §10 rules are MLB/WNBA-derived, so they are labeled as such for CBB.
- **Build/Save:** "Add to ticket" carries `EventId`, `Book`, `MarketKey`, `Side`, `Point`, `Price` and `SourceUpdatedAtUTC` into King's Tickets / Journal.
- **Track:** Bet Tracker records the price taken.
- **Learn:** CLV vs the captured close, and graded ATS/OU at real captured prices. Results stay out-of-sample-only and Research status stays "Context, not an edge" until earned.

---

## 6. Open owner decisions

1. **Scope:** men's only for MVP, or men's + women's together? Women's roughly doubles credits and identity work, and `basketball_wncaab` is unverified.
2. **Credit budget and cadence:**
   - Full-game: hourly (~1.6k/month) vs every 2h (~1.1k) vs 30 min (~4.3k).
   - 1H: once daily (~2.4k) vs never.
   - Finals: hourly (~1k) vs 15 min (~3.6k).
   - Explicitly: **no 60s CBB score polling**.
3. **Books:** which bookmakers to track (≥4 recommended for best-line and `SINGLE BOOK`).
4. **Scores source:** Odds API `/scores` (licence-clean) vs ESPN unofficial (ToS/UA risk).
5. **Metrics licence:** CBBD key/tier (verify terms), KenPom licence (paid), or no pace/efficiency in MVP (shown as Unavailable).
6. **Neutral-site source:** a manual owner-maintained MTE/tournament venue list vs a licensed schedule feed vs leaving it UNKNOWN.
7. **Historical backfill:** buy an Odds API historical pull (~4.5k credits/season [I]) or start forward-capture only. Note that early-season ATS streaks will be thin either way.
8. **Registry fields:** keep `requires_play_verdict=False` (there is no verdict concept, so it must stay False or archiving zeroes out). `identity_ok` stays **False** with a real `stat_column_map` only if/when player props arrive; for a game-lines-only sport, decide whether the registry needs a "game-lines-only" flag so `qc_sport_registry.py` does not demand props/gamelog loaders.
9. **Shell cleanup:** approve removing the fabricated example props rows and the "Live Board & Lines" / "Full prop boards … college hoops" copy now, independent of the build.
10. **Shared-bug fix sequencing:** fix `get_lines_refresh_meta` fail-open and the Eastern-naive age skew platform-wide first (it affects NFL/NCAAF/MLB/WNBA/NBA game-line pages too). This is a separate change from NCAAB.
11. **Injuries:** accept "Availability: Unavailable" for MVP, or fund a source.
