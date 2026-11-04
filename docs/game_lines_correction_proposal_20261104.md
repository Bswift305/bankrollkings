# Game-lines truthfulness — consolidated correction proposal (2026-11-04)

**Status: PROPOSAL ONLY — nothing implemented.** Production is the accepted master `17b5e69`.

**Evidence:**
- read-only production SSM at 15:13:59Z;
- the read-only surface map (appendix);
- signed-in page checks at 15:15Z and 16:19Z.

## 1. What is actually happening in production

| Defect | Production effect today | Evidence |
|---|---|---|
| **G1 Five-hour shift.** `get_lines_refresh_meta` (`app.py:3682`) reads the zone-less Eastern `LastUpdated` (writer `fetch_game_lines.py:182` converts the book's `last_update` to an Eastern string) against the UTC clock: age is inflated by 5h (4h during EDT) | Bites **only where the column survives**: `load_ncaaf_context_slate` (`app.py:18295`; `_ncaaf_market_raw` keeps all columns). From ~1h after each NCAAF fetch, Odds API book lines are dropped there, so games fall back to CFBD consensus (no price) or no line. No warning text. **Surfaces:** `/tools/cfb-matchup` week list, `/tools/cfb-totals` (this week), `/tools/cfb-best-spots`, `/tools/weekend` (CFB half), `/tools/cfb-hub`. Withheld about 23h a day (about 18h with a correct clock under once-daily fetching) | Prod 15:13:59Z: NCAAF_Odds freshest `08:00` → prod age 7.23h STALE, true 2.23h. NFL `08:00` and NBA `08:05` show the same shift. 16:19Z: `/tools/cfb-matchup` shows lines with no book or price (e.g. "-3.5", "+25.5 · O/U 53.5"). Whether those are CFBD consensus or the G3 schedule-mirror leak is **not verified** |
| **G2 Gate inert (fails open).** `_format_game_market_odds` (`app.py:18107`) keeps a fixed column list without `LastUpdated`. It is used by every `load_*_game_market_odds()` loader (NBA, WNBA, MLB, NFL, NCAAF), so the age is None and `is_stale` is always False | Every other caller (`build_game_market_lookup` `:18358`, `build_football_live_games` `:6680`, football method pages `:35523`, CFB/NFL totals boards `:51153`/`:51225`, Matchup Center `:51394`) **would show genuinely days-old lines as current**. Today the lines are about 2–3h old in truth, so nothing false is displayed yet; the protection simply does not exist. **Surfaces:** `/game-lines`, `/game-lines/command`, `/schedule`, `/`, NBA command center, `/team/<team>`, `/sports/nfl` (+game-lines, totals), `/tools/nfl-totals-today`, `/tools/nfl-matchup-center` (feeds nfl-featured / nfl-spots), `/tools/nfl-board`, `/tools/nfl-game-board`, `/tools/nfl-wave`, `/tools/nfl-matchup`, `/sports/ncaaf` (+lines/totals), `/tools/cfb-buy-low`, `/tools/cfb-first-half` | The surface map ran the two functions verbatim on real files: the loader output has no `LastUpdated`, and the age is None. 15:15Z pages showed lines (`/game-lines` "DET -2.5 · 219.5 · FanDuel"; Matchup Center "Total 40.0 · Spread +10 · BetMGM") |
| **G3 Schedule-mirror leak.** `load_nfl_schedule` / `load_ncaaf_schedule` merge `data/schedules/*_Odds.csv`, which carries spreads, totals and prices | Even when a gate empties the odds frame, lines return through the schedule frame. This defeats the Matchup Center withhold (`:51395`) and the preseason path (`:7207`) | Surface map (code reading) |
| **G4 Spread side.** `fetch_game_lines.py:197-208` stores `SpreadOdds` from whichever team's outcome appears first; the other side's price is never stored | A spread price can be shown against the wrong team. Game-line legs are context-only under D4 (no kickoff, no ticket or payout authority), so **no executable action**, but the display is untruthful | NCAAB audit plus the surface map (code reading); production frequency not measured |
| **G5 Props fallback (same family).** `get_props_refresh_meta` falls back to the zone-less `LastUpdated` when a props file lacks `SourceUpdatedAtUTC` | Mis-aged props-feed labels and staleness for those sports. Local NBA/NCAAF props files lack the column; **production not checked** | Surface map / F-T2 |

**Executable impact:** none found.
- Game-line legs are context-only (D4).
- Card line legs read zone-less stamps as New York time (`_feed_stamp_to_utc`).
- SGP game legs carry "tz unverified" and have no authority.
- Monitoring (`qc_odds_feed`, `report_feed_availability`, Run Status) ages files by modification time, not `LastUpdated`.

**Why the QCs missed it:**
- fixtures are built from the local clock;
- the fixtures use 50–55h ages;
- loaders are monkeypatched to raw frames, which bypasses the column drop;
- one QC passes on UTC with only 1h of margin and never checks the age.

## 2. Proposed correction (owner decides scope)

**L1 — truthful time, no product-visibility change (narrow; recommended first).**
1. The writer (`fetch_game_lines.py`; also futures) additionally emits zone-explicit `SourceUpdatedAtUTC` (book/market `last_update`, ISO-Z) and `FetchedAtUTC`. `LastUpdated` is untouched (legacy; F-T1 migration order).
2. `get_lines_refresh_meta` prefers `SourceUpdatedAtUTC`. Otherwise it reads legacy `LastUpdated` explicitly as `America/New_York` (DST-aware) via `_feed_stamp_to_utc` — only for writers whose contract is "Eastern display". It compares against an injectable UTC `now`, never the process zone.
3. Fix G4 at the source. Store both spread sides with their own price and point (`HomeSpread`/`HomeSpreadOdds`/`AwaySpread`/`AwaySpreadOdds`, or long-form rows). An uncaptured side shows "price unavailable", never the other side's price.
4. **Effect:** the CFB context tools stop withholding fresh book lines (G1). No other surface changes, because the G2 gate is still inert.
5. **QC:** the real writer format through the **real loaders** at true ages 0.5h, 5.5h and 6.5h, under `TZ=UTC`, `America/New_York` and `America/Los_Angeles`, including the DST boundaries; spread-side fixtures with the away team first; mutation proofs.
6. **Cache:** the CFB context tools are uncached (restart only). No purge.

**L2 — make the stale gate real everywhere (product decision).**
1. Keep the timestamp through `_format_game_market_odds`, and evaluate staleness **after** cache retrieval (per request), not frozen at build time.
2. Close G3: the schedule loaders must not re-introduce lines or prices from `data/schedules/*_Odds.csv` when the odds feed is stale, or must carry the same time fields and gate.
3. Bump the affected cache versions (`nfl_matchup_center::src2` → `src3`, the NFL dashboard bundle `srcutc1` → `srcutc2`, NBA/runtime tokens). Old files are left unread; no purge.
4. **Visibility consequence:** with lines fetched once a day (13:00Z), a 6h window makes NFL/NCAAF/NBA current lines stale or withheld from about 19:00Z daily on roughly 20 pages. One owner decision is needed:
   - **(a)** raise line-refresh cadence for in-season sports (credit cost per the cadence audit);
   - **(b)** keep showing the last lines **labelled with their true age** ("as of HH:MM ET", non-live) instead of withholding them;
   - **(c)** withhold.
5. **QC:** a stale feed yields zero priced current lines through every loader, including the schedule loaders; fresh lines unaffected; per-request evaluation proven against a cached builder.

**L3 — F-T1/F-T2 track.**
- Migrate the remaining `LastUpdated` consumers to `SourceUpdatedAtUTC`/`FetchedAtUTC`, then retire `LastUpdated`.
- Includes G5: every props writer emits `SourceUpdatedAtUTC`, and props-feed labels/staleness never fall back to a zone-less stamp.

## 3. Owner decisions needed
1. Approve L1 as the next narrow truthfulness correction (branch from `17b5e69`, full offline + exact-SHA Linux gate, then deploy on approval).
2. L2 visibility policy: (a), (b) or (c).
3. Whether G4 ships inside L1 (recommended — same writer change) or alone.

---

# Appendix — read-only surface map (verbatim)

# Game-lines staleness (`get_lines_refresh_meta`) — exact affected-surface map

Read-only analysis of worktree `.claude/worktrees/props-utc` @ `17b5e69` (= prod master). No edits, no network,
no prod access. `[I]` = inference (not directly proven from code or the prod facts you gave me).

## 0. Headline: the premise needs correcting

**The +5h bug is real, but it reaches almost none of the surfaces you listed.** The reason is not caching.
Every market loader strips `LastUpdated` before any gate sees it, so on those frames the gate can never fire.

- `_format_game_market_odds` (app.py:18078-18108) ends with
  `keep_cols = ['Date','Time','Away','Home','AwayML','HomeML','Spread','SpreadOdds','Total','OverOdds','UnderOdds','Book','GameID']`
  (app.py:18107). **`LastUpdated` is not in the list.**
- That transform backs `load_game_market_odds` (NBA, 18111), `load_wnba_…` (18121), `load_mlb_…` (18131),
  `load_nfl_…` (18141) and, through `_format_ncaaf_game_market_odds` (18182), `load_ncaaf_game_market_odds` (18197).
- `get_lines_refresh_meta` (3682) only computes an age `if 'LastUpdated' in odds_df.columns` (3691).
  Otherwise `age_hours=None`, so `is_stale=False` (3704) and `status='live'`.
- **Result:** for every caller fed by a `load_*_game_market_odds()` frame, the "fail-closed" gate is dead code.
  It does not fire for the timezone bug, and it would not fire for a genuinely 3-day-stale feed either.

Checked locally: I ran a probe that pulls these two functions verbatim out of `app.py` (via AST) and runs them
on the local data:

| File | Raw-file age | Formatted frame |
|---|---|---|
| `NFL_Odds.csv` | −1.17h (max `2026-11-04 08:29`) | `has LastUpdated=False age=None stale=False` |
| `NCAAF_Odds.csv` | −1.19h | `has LastUpdated=False age=None stale=False` |
| `NBA_Odds.csv` | `LastUpdated` empty | `has LastUpdated=False age=None stale=False` |

The local box sits about one hour behind Eastern, so raw ages come out negative there. This is the dev-box
mirror of prod's +5h.

**So the pages you saw at 15:15Z still showing lines are explained by the dropped column, not by a cache.**
None of them will flip today, after any rebuild, from this bug.

**The only live customer-facing path that does get a raw `LastUpdated` is `load_ncaaf_context_slate`** (§1, row 2).
It feeds the CFB context tools, it is evaluated on every request, and it is uncached. On prod those tools
started withholding Odds-API book lines at about **14:00Z today** `[I: timing derived from your 13:00Z
book stamp]`.

## 1. The seven call sites

Odds column: **R** = raw frame, `LastUpdated` present, the bug bites. **F** = formatted frame, no
`LastUpdated`, gate inert.

| # | Site | Frame actually passed on prod paths | Bites? |
|---|---|---|---|
| 1 | app.py:6680 `build_football_live_games` | **F** from every prod caller (7200, 7347 via 35556, 31155, 33529, 33706, 35237, 35387, 46918, 47079, 49178, 49284, 49383, 49559, 51159, 51231, 51397). Context-slate callers (47629, 50658, 50971, 51047) pass the composed frame built from `line_cols` (18288), which has no `LastUpdated`. **R** only at 7207 (`NFL_Preseason_Odds.csv` raw), which is August data and genuinely stale anyway. | No (see the latent leak below) |
| 2 | app.py:18295 `load_ncaaf_context_slate` | **R**: `w1 = _load_cached_csv(NCAAF_Odds.csv, transform=_ncaaf_market_raw)`. `_ncaaf_market_raw` (18186) keeps all columns, by design ("AwayFull/HomeFull/LastUpdated", 18187). | **YES** |
| 3 | app.py:18358 `build_game_market_lookup` | **F** at every caller: 24374 (`/team/<team>` via 40167), 28663, 30620, 30839, 39771, 40056, 40133 (`load_game_market_odds` and siblings) | No |
| 4 | app.py:35523 `_render_football_method_page` | **F**: `live_config['odds']()` = `load_nfl_game_market_odds` / `load_ncaaf_game_market_odds` (35490-35496) | No |
| 5 | app.py:51153 `build_cfb_totals_board_context` | **F**: `load_ncaaf_game_market_odds()` (51152) | No |
| 6 | app.py:51225 `build_nfl_totals_board_context` | **F**: `load_nfl_game_market_odds()` (51224) | No |
| 7 | app.py:51394 `build_nfl_matchup_center_context` | **F**: `load_nfl_game_market_odds()` (51393) | No |

### Latent leak (independent of the timezone bug; it matters for the fix)

Even when the `build_football_live_games` gate *does* empty `odds_df`, lines come back through the schedule frame:

- `load_nfl_schedule` (21081) and `load_ncaaf_schedule` (21107) concatenate `data/schedules/{NFL,NCAAF}_Odds.csv`
  through `_format_schedule`. That transform only cleans Date/Away/Home and keeps Spread, Total, prices, Book
  and `LastUpdated`.
- `build_live_game_lookup` (6545) merges `[odds_df, schedule_df]` (6547-6551) and reads Spread, Total and prices
  from whichever row survives.
- So an emptied `odds_df` still yields lines from the mirror. The Matchup Center's
  `_mc_odds_for_games = empty` (51395) is defeated the same way, because it still passes `load_nfl_schedule()`.
- The preseason call at 7207 passes the same raw frame as both odds and schedule, so it is defeated outright.

## 2. Surface map

Effect column, unless noted: **none** = the gate is inert, so lines always render whatever their true age.

### NBA

| URL | Path to a gate | Cache between route and gate | Effect / when it flips | Executable? |
|---|---|---|---|---|
| `/game-lines` | `game_lines_page` 40128 → `build_game_market_lookup(load_game_market_odds())` 40133 | `DATAFRAME_CACHE` only (mtime, 2310-2325); lookup built per request | none; never flips. **Does not call `get_lines_refresh_meta` directly**, only through the lookup chokepoint, and that is inert. Explains "DET -2.5 219.5 FanDuel" at 15:15Z. | No |
| `/game-lines/command` | `build_cross_league_game_lines` 40041 → lookup 40056 (NFL, CFB, NBA, WNBA, MLB) | per request | none | No |
| `/schedule` | `schedule_page` 39768 → lookup 39771 | per request | none | No |
| `/` (frontpage) | 30620 lookup | per request (plus snapshot `nba_context`, 30550) | none | No |
| NBA dashboard / command center (frontpage, 30999, 31113, 31134) | `build_nba_command_center_context` 30794 → lookup 30839 | runtime snapshot `payload` first (30550 / 30999); then `RUNTIME_TTL_CACHE` 180s + disk pkl keyed on a `_build_file_token` that includes `NBA_Odds.csv` (30803-30823). Short-circuited to a stub when the NBA source gate is off (30801). | none. **Answer:** the lookup runs inside the cached bundle (TTL + disk + snapshot), not per request. | No |
| NBA prop runtime (41253, 41379, 43383) | `build_live_prop_runtime_context` 28644 → lookup 28663 | `_build_file_token` includes `NBA_Odds.csv` (28650) | none | No |
| `/team/<team>` | 40167 → `build_team_decision_context` → lookup 24374 | per request | none | No |

### NFL

| URL | Path | Cache | Effect | Executable? |
|---|---|---|---|---|
| `/sports/nfl` | `build_nfl_dashboard_runtime_bundle` 31142 (`live_odds` = **F**); `build_football_home_slate` 35221; `build_football_preseason_markets` 7165 | disk TTL 43200s, version = file token of NFL_Odds/Props/Schedule + `'srcutc1'` (31145-31181) | none. The preseason fold (7207) is genuinely stale, but the gate is defeated (same frame passed twice). | No |
| `/sports/nfl/game-lines`, `/sports/nfl/totals` | `_render_football_method_page` 35448 (gate 35523; totals pill gated on `_lines_stale` 35537-35554) | per request | none. The banner "Current Lines Unavailable" never renders on prod data. | No |
| `/tools/nfl-totals-today` | 51272 → `build_nfl_totals_board_context` (gate 51225) | per request | none. Stale text never appears: `nt_stale_note` = the `get_lines_refresh_meta` warning (template at 3707-3708). | No |
| `/tools/nfl-matchup-center` (also feeds `/tools/nfl-featured` via `_gl_matchup_games` 46402, and `build_nfl_spots_context` 51589) | gate 51394 | memory sig + disk `nfl_matchup_center::src2`. Sig = (version, file token of odds + injuries, player-log sig, **ET date**, weather sig) (51370-51378). Prewarmed by `refresh_runtime_snapshots.prewarm_nfl_tool_caches` (322). | none. `lines_stale` (51554) is always False. Explains "Total 40.0 Spread +10 BetMGM", which is the first BetMGM row of `NFL_Odds.csv`. | Game-line legs are context-only (D4) |
| `/tools/nfl-board`, `/tools/nfl-game-board`, `/tools/nfl-wave`, `/tools/nfl-matchup`, `/tools/weekend` (NFL half) | 49284 / 49383 / 49559 / 49178 / 51303 → `build_football_live_games(F)` | `_NFL_BOARD_CACHE` / `_NFL_GAME_BOARD_CACHE` / `_NFL_WAVE_CACHE` sig = file mtimes including NFL_Odds (49259-49263, 49357-49361, 49547-49550) | none | No |
| SGP Workbench `/tools/sgp-workbench` | game legs read raw `NFL_Odds.csv` (48820) and show `LastUpdated` as a string tagged `'provider time; tz unverified'` (48520, 48828). **No staleness gate.** | per request | Not affected by `get_lines_refresh_meta`. Legs have `kickoff_utc=None`, so they are never addable or exported (48813-48816). | No (context-only) |

### NCAAF

| URL | Path | Cache | Effect | Executable? |
|---|---|---|---|---|
| `/sports/ncaaf`, `/sports/ncaaf/game-lines`, `/sports/ncaaf/totals`, `/tools/cfb-buy-low`, `/tools/cfb-first-half`, card-pool `_cfb_form_legs` | **F** frames (35384, 35495, 51152, 46918, 47079, 33529) | per request or mtime | none | `_cfb_form_legs` feeds Daily Card / Menu pools, but it reads **F**, so it is unaffected |
| **`/tools/cfb-matchup`** (week list) | 47696 → `build_cfb_matchup_context` → `build_football_live_games(*load_ncaaf_context_slate())` (47629) | **None on the slate.** Only the static JSON is mtime-cached (`_CFB_MU_CACHE`). `w1` is DATAFRAME_CACHE'd by mtime, but `get_lines_refresh_meta` runs on **every request** with `pd.Timestamp.now()`. | **AFFECTED.** When the inflated age is over 6h, `w1` is emptied (18296). Each game then shows the CFBD consensus spread/total labelled **"CFBD consensus — no book price"** (18157, 18341-18342, 6740/6748, every price None), or no line at all if CFBD lines are older than 48h (18308-18309, 18339-18340). **No warning text is shown** (the composer drops `warning`). | No (context only) |
| **`/tools/cfb-totals`** ("this week" section) | 50688 → `build_cfb_totals_context` (50658) | same, per request | **AFFECTED.** `posted` total becomes the CFBD consensus, or NaN. | No |
| **`/tools/cfb-best-spots`** (`?date=today\|week`, `?fav=`) | 51011 → `build_cfb_best_spots_context` (50971) + `build_cfb_big_favorites_context` (51047) | per request | **AFFECTED.** The analysis cards and the 20/30/40 big-favourite list are computed off the CFBD consensus spread instead of the book spread. | No |
| **`/tools/weekend`** (CFB fades, covers, spots) | `build_weekend_context` 51281 → 51288, 51298 | per request | **AFFECTED** (CFB half only) | No |
| **`/tools/cfb-hub`** (`h_best`) | `build_cfb_hub_context` 51634 | per request | **AFFECTED** | No |

**When the CFB context tools flip** (prod is UTC; EST since Nov 1, so +5h):

- Inflated age = (now − 13:00Z) + 5h for the 13:00Z book stamp.
- So `is_stale` turns True at **14:00Z** and stays True until the next `NCAAF_Odds` fetch. That fetch is
  bk-daily at 13:00Z tomorrow; bk-nfl-games does **not** fetch odds (`ops/bk-nfl-games-refresh.sh` runs
  `fetch_nfl_games.py`, the nflverse parquet).
- Withheld about 23 of every 24h. With a correct clock it would be withheld from 19:00Z, about 18h/day,
  because a once-daily fetch cannot stay inside a 6h CLOCK A window. `[I]`
- `[I]` Applies only when `load_ncaaf_cfbd_schedule()` is non-empty on prod. If it were empty, the function
  returns the **F** market frame (18300-18305), which is ungated.

### MLB, WNBA

- Every path is **F** (lookup callers via `CROSS_LEAGUE_GAME_SOURCES` 39788 and the dashboards). No effect.
  Their feeds are genuinely stale off-season, and that is **not** gated either, for the same dropped-column reason.

### CBB (NCAAMB / NCAAW)

- No `get_lines_refresh_meta` caller exists. `load_ncaamb_schedule` (21139) has no gate.

## 3. Executable actions

- **No executable action is gated by `get_lines_refresh_meta`.**
- Game-line legs are context-only:
  - SGP: `kickoff_utc=None` (48813-48816).
  - Daily Card / Menu line legs: `_unpriced_line_fields` (33292, 33558, 33580). `updated_utc` comes from
    `_feed_stamp_to_utc`, which **correctly** reads zone-less stamps as America/New_York (33308-33323).
- Prop legs, tickets and SGP export use the prop quote-time path (`SourceUpdatedAtUTC`, 48790-48794;
  `_quote_freshness_failure` 33477 / 48743). That path is not lines staleness.
- The affected CFB context tools (`/tools/cfb-*`, weekend, hub) produce no ticket, payout or export.

## 4. Monitoring

- `qc_odds_feed.py` (game lines vs props, "props STALE while lines FRESH", 107-116) and
  `report_feed_availability.py` (`_age_hours` = file mtime, 111-117) use **CLOCK B (file mtime)** from
  `services/freshness_contract.py` (19-23, 37-48). Neither reads `LastUpdated` for age, so **both are unaffected**.
- `report_feed_availability` lists `LastUpdated` in `_DATE_COLS` (95), but only as a last-resort *event-date*
  column for schedule counting.
- `services/feed_validation.py` (114-124) parses `LastUpdated` with `utc=True`, which mislabels ET as UTC,
  but it only compares new-max to prior-max (a regression check). A constant offset cancels out.
  - `[I]` The only exposure is the fall-back hour: ET 01:xx EDT vs 01:xx EST could false-flag a "timestamp
    REGRESSION" once a year.
- Run Status reads CLOCK B as well (per the contract docstring, 22-23). Not affected.

## 5. Adjacent consumers with the same defect class (not lines; unverified on prod)

- **`get_props_refresh_meta`** (3627-3638): when a props file has **no** `SourceUpdatedAtUTC` column, it falls
  back to naive `LastUpdated` vs `pd.Timestamp.now()`. Same +5h on UTC.
  - Feeds `load_*_live_props_feed(require_fresh=True)`, Slate Pulse (19622), Best Lines (19866) and Risk Radar (20138).
  - Locally, `NBA_Props.csv` and `NCAAF_Props.csv` lack `SourceUpdatedAtUTC`. `[I]` Check the prod headers.
- **MLB GameContext** (20286-20292): naive `LastUpdated` vs `pd.Timestamp.now()`, 12h window.
  The writer zone is unchecked (`build_mlb_game_context.py:141`).

## 6. QCs covering `get_lines_refresh_meta` and why they miss this

| QC | Why it misses |
|---|---|
| `qc_game_lines_freshness.py` | (a) Fixture stamp is `datetime.now() - Δ` (process-local naive, line 25), so it is self-consistent with `pd.Timestamp.now()` in **any** process zone. (b) Uses 50h / 1h ages, so a 5h offset never crosses 24h. (c) Unit check passes `max_age_hours=24`, not the real 6h. (d) **Monkeypatches `load_nfl_game_market_odds` to return the raw fixture** (97, 157, 187), bypassing `_format_game_market_odds`. So it "proves" a gate that is inert on real loader output. |
| `qc_market_lookup_freshness.py` | Same: local-naive `datetime.now()` (20, 26), 55h vs 1h, raw frame straight into `build_game_market_lookup`. The real loaders drop the column; never exercised. |
| `qc_ncaaf_odds_single_writer.py` | Writes `fresh = datetime.now(_ET)` (510), the correct writer contract. On a UTC host that ages to about +5h, under 6h, so it passes with **1h of margin**. It never asserts the computed age; it would only fail if run more than an hour after the stamp. |
| `qc_matchup_center_cache_version.py:95`, `qc_nfl_weather_venue_integrity.py:154` | Stub `get_lines_refresh_meta` to `{'is_stale': False}` |
| `qc_unpriced_line_legs.py:331-337` | Fixtures without `LastUpdated` |
| `qc_freshness_contract.py`, `qc_feed_availability.py` | CLOCK B / mtime only |

None of these runs under a forced process zone. None goes through the real `load_*_game_market_odds`
with a `LastUpdated` on disk.

## 7. Proposed narrow correction (not implemented)

1. **Writer contract.** In `fetch_game_lines.parse_event_markets` (fetch_game_lines.py:182), keep `LastUpdated`
   (ET display) and **add `SourceUpdatedAtUTC`** = the raw `bookmaker.last_update` ISO-Z, as the props
   fetcher already does (fetch_player_props.py:453). Same for `fetch_futures_odds.py:121-138`.
   `services/feed_validation.GAME_LINES_SPEC` can keep `LastUpdated` required.
2. **Reader.** `get_lines_refresh_meta(odds_df, max_age_hours, now=None)`:
   - Prefer `SourceUpdatedAtUTC` via `_canonical_kickoff_utc`.
   - Otherwise interpret zone-less `LastUpdated` with the existing `_feed_stamp_to_utc` (33308: `tz_localize('America/New_York', ambiguous='NaT', nonexistent='NaT')`, which is DST-correct; ambiguous fall-back rows drop out, they are not guessed).
   - Compare against `datetime.now(timezone.utc)` (injectable `now`).
   - Mirror the props future-stamp tolerance (`QUOTE_CLOCK_SKEW_TOLERANCE_SECONDS`).
   - Label in explicit ET (`_source_time_label`).
   - Zone-aware strings (FirstHalf `Z`) keep their zone.
3. **Fix the CFB context bug only (minimal).** Step 2 alone fixes `load_ncaaf_context_slate` (the one live
   victim). It is uncached and per-request, so **no cache bump is needed** there. Code-only change: prod needs
   `systemctl restart` (preload_app), which bk-auto-deploy does.
4. **Separate decision: do NOT bundle silently.** To make the documented "fail closed" real on the other six
   sites, `_format_game_market_odds` (18107) must carry `SourceUpdatedAtUTC`/`LastUpdated`. That **activates**
   the gate on about 20 NBA/NFL/CFB/MLB/WNBA surfaces. With a once-daily fetch against a 6h CLOCK A window,
   lines would then be withheld from about 19:00Z daily on `/game-lines`, `/schedule`, the NFL boards, the
   matchup center and the totals pages. That is a product and cadence decision. It also needs:
   - The **schedule-mirror leak** closed: strip line/price/Book columns from `load_{nfl,ncaaf}_schedule` frames,
     or blank them when stale. Otherwise `build_football_live_games` still shows lines.
   - The **build-time freeze** fixed: these caches evaluate staleness once at build and key only on file mtime
     and date. They are `NFL_MATCHUP_CENTER_CACHE_VERSION='src2'` (51355-51356, sig 51370), the `nfl_dashboard_runtime`
     version suffix `'srcutc1'` (31148), the `nba_command_center` disk token (30803), the
     `build_live_prop_runtime_context` token (28650), the in-memory `_NFL_BOARD_CACHE` / `_NFL_GAME_BOARD_CACHE` /
     `_NFL_WAVE_CACHE` sigs, and runtime snapshots (`nfl_dashboard` and the NBA payload, served up to
     `max_age_minutes`).
     A feed that ages past 6h mid-day would otherwise stay "live" until the mtime changes or the ET date rolls.
     Either apply the gate **after** cache retrieval (cache the lines plus their UTC stamp, decide per request),
     or add a stale/fresh boolean to each sig. Then bump the version strings (`src2`→`src3`, add an `lnutc1`
     suffix to `srcutc1`, add a suffix to the NBA and runtime tokens) and `rm -f data/cache/*nfl_matchup_center*
     *nfl_dashboard_runtime* *nba_command_center*` on deploy (CLAUDE.md §4).
5. **Adversarial QC** (`qc_lines_refresh_tz.py`):
   - Write a real `NCAAF_Odds.csv` / `NFL_Odds.csv` to a temp `DATA_DIR` in the **writer's exact format**:
     ET `LastUpdated` built from a fixed UTC instant via `to_eastern_datetime_str`, plus `SourceUpdatedAtUTC`.
   - Call **the real loaders and builders**: `load_ncaaf_context_slate`, `load_*_game_market_odds` →
     `get_lines_refresh_meta`, `build_game_market_lookup`, `build_football_live_games`.
   - Use an injected `now` at true ages 0.5h, 5.5h and 6.5h, so exact boundaries are asserted:
     5.5h live, 6.5h stale.
   - Re-run in subprocesses with `TZ=UTC`, `TZ=America/New_York`, `TZ=America/Los_Angeles`. On Windows, where
     `TZ` is ignored, rely on the injected `now` and the source-level assertion below.
   - Results must be identical across zones.
   - Add DST cases: a stamp in the 2026-11-01 01:00-02:00 ambiguous hour, a 2026-03-08 02:xx nonexistent stamp,
     and an EDT-season stamp (+4h).
   - Assert that no zone-less stamp is compared with naive `pd.Timestamp.now()`: a grep-style guard over the
     source of `get_lines_refresh_meta` / `get_props_refresh_meta`.
   - If item 4 is adopted, also assert that a stale feed yields **zero** priced lines through
     `load_nfl_schedule()` (the mirror leak).

## Answers to the specific questions

- **Does `/game-lines` use `get_lines_refresh_meta`?** Only indirectly, through `build_game_market_lookup`
  (40133). That path is inert, because `load_game_market_odds` drops `LastUpdated`.
- **NBA dashboard / command center:** `build_game_market_lookup` runs inside the cached bundle
  (snapshot → 180s TTL → disk pkl, file-token keyed), not per request. `/game-lines`, `/schedule` and `/` call it
  per request. All are inert.
- **Why lines still showed at 15:15Z:** the loaders dropped the column; no cache was involved. **What flips on
  the next rebuild:** nothing in that observed set. The CFB context tools (cfb-matchup, cfb-totals,
  cfb-best-spots, weekend CFB half, cfb-hub) were already in the withheld/CFBD-consensus state from about
  14:00Z `[I]`. They are evaluated per request, so they will recover only after the next NCAAF odds fetch
  (bk-daily, about 13:00Z), and only for about an hour.

`git status --short` in the worktree at the end: empty.
