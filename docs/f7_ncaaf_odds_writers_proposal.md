# F7 — NCAAF odds/schedule: two writers, one filename (investigation + proposal)

**Status:** DESIGN ONLY. No code changed. Written against commit `63060a9`.
**Scope:** `data/odds/NCAAF_Odds.csv`, its mirror `data/schedules/NCAAF_Odds.csv`, and
`data/schedules/NCAAF_Schedule.csv`. All three are gitignored (`.gitignore:52`, `.gitignore:55`),
so the repo holds no copy of what production serves. Every claim below is cited to code at `63060a9`.
Anything that depends on production state is listed in §7 as a read-only check, not asserted.

**Defect class:** same as `63060a9` (graders writing the governed NFL roster parquet). Here two
*producers* publish under one name, so "the NCAAF odds file" means whichever ran last.

---

## 1. Findings in brief

1. **Two writers, both in the prod daily chain, last writer wins.** The Odds API path
   (`fetch_game_lines.py`) runs at `run_daily.py:38`. The CFBD path (`fetch_ncaaf_slate_cfbd.py`)
   runs later, at `run_daily.py:183` → `refresh_cfb_data.py:100-101`. When CFBD runs, its output
   replaces the Odds API output for the rest of the day.
2. **They do not share a contract.** They differ in source, row granularity, team names, GameID
   namespace, Time format, LastUpdated meaning, date horizon and game universe. On top of that, the
   CFBD writer **makes up prices**: it writes a hard-coded `-110` for every spread/total price, plus a
   moneyline that is an average of American odds across providers. A shared filename is the only
   thing they have in common.
3. **The CFBD writer is not atomic, does no validation, and clobbers good data with empty output.**
   Every HTTP error, including a CFBD 429, is swallowed per week (`fetch_ncaaf_slate_cfbd.py:82-83`,
   `97-98`). The script then writes **header-only files with exit 0**, so the quota latch in
   `refresh_cfb_data.py` never sees a failure at this step.
4. **Readers silently change behavior with the last writer.** Some CFB tools join raw slate team
   names to CFBD-keyed data, so they only work when CFBD wrote last. Others join to Odds-API-keyed
   data, so they only work when the Odds API wrote last. Monitoring (`qc_odds_feed.py`) treats a CFBD
   write as fresh *Odds API* game lines. See §4.
5. **The writers interfere with each other's validation.** The Odds API publish validates against
   `prior_df = pd.read_csv(output_path)` (`fetch_game_lines.py:442-447`). In steady state that prior
   is the *CFBD* file from yesterday's run, so the row-count-collapse and timestamp-regression checks
   compare the Odds API output against a different source.
6. **Adjacent finding, outside F7 but found on the way:** `_format_game_market_odds` drops
   `LastUpdated` (`app.py:17986`). Every frame returned by `load_ncaaf_game_market_odds()` therefore
   has no `LastUpdated`, and the 6h fail-closed gates in `build_football_live_games`
   (`app.py:6651-6656`) and `build_cfb_totals_board_context` (`app.py:49524-49528`) cannot fire for
   real data. `get_lines_refresh_meta` returns `age_hours=None` for those frames (`app.py:3668-3696`).
   `qc_game_lines_freshness.py:184-194` monkeypatches the loader with a fixture that *has*
   `LastUpdated` (`:23-31`), so it never runs the real formatter. The same formatter serves the
   NBA/WNBA/MLB/NFL loaders (`app.py:17990-18028`). This should be raised as its own item (§8, Q-A).

**Recommendation (§5):** keep **separate artifacts with one writer each, and bind every reader to
one of them explicitly**. Nothing is composed on disk under a legacy name. The few surfaces that need
both sources compose them at read time, in one function, with provenance on every row.

---

## 2. Writer inventory (question 1)

A repo-wide grep for `NCAAF_Odds|NCAAF_Schedule`, plus generic `{prefix}_Odds.csv` /
`{prefix}_Schedule.csv` path builders, covering `*.py`, `batch/`, `ops/` and `deploy/`, finds exactly
two production writers.

### W1 — Odds API: `fetch_game_lines.py` (via `fetch_ncaaf_game_lines.py`)

| | |
|---|---|
| Paths | `SPORT_OUTPUTS["americanfootball_ncaaf"]` = odds / schedules-mirror / schedule_alias (`fetch_game_lines.py:44-48`) |
| Entry | `fetch_ncaaf_game_lines.py:11-17` injects `--sport americanfootball_ncaaf --bookmakers draftkings,caesars,fanduel,betmgm` and calls `fetch_game_lines.main()` |
| Fetch | one `/v4/sports/americanfootball_ncaaf/odds` call; one row per (event, bookmaker) (`:233-253`) |
| Failure handling | fetch error **and** empty frame → exit 1, files preserved (`:429-432`); missing quota receipt → exit 1 (`:433-435`) |
| Validation | `validate_feed(df, GAME_LINES_SPEC, prior_df=<current file>, sport_tokens=("NCAAF",))` (`:440-452`, spec at `services/feed_validation.py:299-308`). Checks schema, finite numbers, timestamp regression vs prior, conflicting `(GameID, Book)` duplicates, path sport token, and collapse below 50% of prior rows when the prior has ≥5 rows (`feed_validation.py:143-147`) |
| Publish | `atomic_write_csv` for each of the 3 paths **in sequence** (`:453-459`; temp file + `os.replace`, `services/atomic_csv.py:43-58`). Each file is atomic; the set of 3 is not |
| Side effect | appends `data/tracking/NCAAF_LineMovementHistory.csv` + rewrites `NCAAF_LineMovementCurrent.csv` (`:460-461`, `:305-370`); plain `to_csv`, not atomic |
| Prod schedule | `run_daily.py:38` "Football line movement" → `refresh_football_line_movement.py:10` (`--days 130`, timeout 240s). This file's exit code is non-zero if the NCAAF step fails (`:30-32`) |
| Other schedules | Windows dev box only: `batch/TASK_refresh_football_data.bat:19` and `batch/REFRESH_FOOTBALL_DATA.bat:26` (`--days 7`). **Not** in `bk-linemove` (`refresh_line_movement_snapshots.py:24-27` = MLB + WNBA only). No `ops/` or `deploy/` unit references it |

### W2 — CFBD: `fetch_ncaaf_slate_cfbd.py`

| | |
|---|---|
| Paths | `data/schedules/NCAAF_Schedule.csv` (`:132-133`), then `data/odds/NCAAF_Odds.csv` and `data/schedules/NCAAF_Odds.csv` (`:134-136`) |
| Fetch | for weeks 1–16: `/games` then `/lines` per week (`:79-98`). Regular season only (`seasonType=regular`, `:81`, `:95`) |
| Failure handling | **every** `/games` exception → `continue` (`:82-83`); every `/lines` exception → `pass` (`:97-98`). A 429 on the first call leaves `games == []`, and the script **still writes all three files, header-only, and exits 0** |
| Validation | none |
| Publish | plain `open(p, "w")` + `csv.DictWriter` (`:132-136`). Not atomic: a reader can see a truncated file, and a crash leaves one. The schedule is written first, so schedule and odds can come from different moments |
| Prod schedule | `run_daily.py:183` "CFB data refresh" → `refresh_cfb_data.py` first step, `--days 12` (`refresh_cfb_data.py:100-101`) |
| Skip paths | no `CFBD_API_KEY` → whole refresh skipped, exit 0 (`refresh_cfb_data.py:167-169`); persisted quota latch → skipped, exit 3 (`:171-177`) |
| Other schedules | none. Not in any `batch/*.bat`; not in `ops/` or `deploy/` |

### Ordering and the prod operator

Both steps sit in `_active_refresh_steps`, which applies to every sport (`run_daily.py:27-189`). The
order is fixed: W1 at `:38`, then 27 other steps, then W2 at `:183`. If the operator runs **without**
`--continue-on-error`, a W1 failure (for example a validation reject) aborts the run at `:356-359`,
W2 never runs, and the files keep yesterday's CFBD content. `docs/refresh_incident_2026-10-23.md:20`
says prod runs `--continue-on-error`. The prod unit is **not in the repo**
(`docs/aws_runbook.md:145-162` shows only an example `ExecStart` without the flag), so this needs
verification (§7, P1).

`batch/TASK_daily_operator.bat:9` runs `run_daily.py --skip-refresh`, so the local operator writes
neither file. On the Windows box only W1 (batch) is scheduled, which means **local and prod show
different NCAAF contracts**. This is one more way that "it works locally" can mislead.

### Non-writers checked

- `fetch_football_first_half.py` writes `NCAAF_FirstHalf.csv`, not these files.
- `refresh_live_scores.py` reads these files and writes `live_scores` (`:298`).
- `fetch_cfb_weather.py` reads them only (`:87`).
- `recover_odds_fetch.py` wraps whatever command it is given. It is an operator tool, not
  scheduled, and becomes W1 when wrapped around `fetch_game_lines.py`.

---

## 3. The two contracts (question 2)

Both writers use the same 16 column **names**
(`fetch_game_lines.py:257-274` == `fetch_ncaaf_slate_cfbd.py:29-30`). The values in those columns
mean different things:

| Field | W1 Odds API | W2 CFBD |
|---|---|---|
| Row granularity | one row per **(event, bookmaker)**: up to 4 rows per game (DK/Caesars/FD/BetMGM). Dedup on `(Date, Away, Home, Book)` (`fetch_game_lines.py:284`) | one **consensus** row per game (`:117-124`) |
| Game universe | events that have ≥1 bookmaker row; an event without books produces no row (`:250-252`). Horizon `--days 130` | FBS games (≥1 FBS conference, `:107-108`) within `--days 12`. Schedule includes unlined games; odds rows only where spread or total exists (`:115-116`) |
| `Book` | real book title, e.g. `DraftKings` (`:180`) | the literal `"CFBD consensus"` (`:123`), not a book |
| `Spread` | the book's home point, or the negated away point (`:200-212`) | **mean** of provider `spread`s, rounded to 0.1 (`:54-56`, `:111`), so it can be a number no book is dealing (e.g. −3.2) |
| `SpreadOdds/OverOdds/UnderOdds` | the book's real price | **always `-110`** (`:121-122`), invented |
| `AwayML/HomeML` | the book's real price | `int(mean(American odds))` across providers (`:113-114`, `:120`). Averaging American odds is not a price, and a mix of + and − prices can average toward 0 |
| Team names | Odds API full names, e.g. "Georgia Bulldogs" (`Away = AwayFull = event.away_team`, `:162-165`) | CFBD school names, e.g. "Georgia" (`AwayFull = Away = homeTeam/awayTeam`, `:106`, `:119`) |
| `GameID` | Odds API event id (`:174`) | CFBD integer game id (`:123`). **Different namespaces; not joinable** |
| `Date` | Eastern date via `services.timeutils.to_eastern_datetime_str` (`:150-157`) | Eastern date via its own `ZoneInfo` conversion (`:59-68`); compatible |
| `Time` | 24h `HH:MM` ET | `H:MM AM/PM` ET (`:65-66`) |
| `LastUpdated` | the **bookmaker's** `last_update`, ET, tz-naive string (`:182`): when the market moved | **fetch time**, UTC with `Z` (`:101`, `:123`): when we pulled, not when the line moved |
| Schedule file columns | `Date,Time,Away,Home,AwayFull,HomeFull,Book,GameID,LastUpdated` (`:292-295`) | `Date,Time,Away,Home` (`:133`) |
| Line movement | appended to `NCAAF_LineMovement*` (`:460-461`) | none |

**Verdict:** these are **different sources that happen to share a filename**. A reader cannot tell
which contract it has without sniffing `Book`. No column records provenance.

Spread sign: W1 is home-perspective by construction. W2's comment says "home perspective" (`:111`).
The code takes CFBD's `spread` field as-is, so the sign convention is the provider's. Confirm with a
prod sample (§7, P6).

---

## 4. Readers and what each one assumes (question 3)

The loaders hide the source. `load_ncaaf_game_market_odds()` reads `odds/` first, then the mirror
(`app.py:18030-18037`). `load_ncaaf_schedule()` concatenates `NCAAF_Schedule.csv` with the **mirror**
first (`app.py:20797-20820`). Both inherit whichever writer ran last. `sport_registry.py:125-126`
registers these two loaders as NCAAF's canonical odds/schedule.

### 4a. Readers that only work under the **CFBD** contract (raw CFBD-school-name joins)

Under W1, the slate names are "Georgia Bulldogs" and these lookups silently miss. Bullets or
sections go empty with no error.

| Reader | Join | Effect when W1 wrote last |
|---|---|---|
| `_cfb_analyze_game` / Best Spots (`app.py:49190-49205`, `49341-49357`) | `teams.get(away)`, `totals.get(home)`, `power.get(home)` keyed by CFBD names | `F` is None → returns no bullets → `bs_live` empty; the page falls to evergreen text |
| Big Favorites (`app.py:49424-49457`) | `teams.get(fav)` for the coach; `team_rec.get(fav)` | coach and team records blank |
| CFB totals board (`app.py:49513-49546`) | `look.get(team)` on `cfb_totals.json` rows | Over%/pace blank |
| Totals pace (`app.py:49036-49044`) | `prof.get(a)` | games skipped ("need both FBS profiles") |
| Matchup card streaks (`app.py:46418-46419`) | `sidx.get(name.lower())` on `cfb_ats_streaks.json` | streaks blank |
| `_cfb_weather` (`app.py:46226-46256`) | exact `(home, away)` against `cfb_weather.json`. That JSON's names come from **whichever writer** owned `NCAAF_Odds.csv` when `fetch_cfb_weather.py:87` ran, which is inside `refresh_cfb_data`, right after W2 | matches only while the same writer still owns the file |
| `_match_first_half` (`app.py:7203-7219`) | prefix match; its docstring states "The board uses CFBD school names" | works under both (prefix and exact). The assumption is documented, but it is still CFBD-shaped |

### 4b. Readers that only work under the **Odds API** contract

| Reader | Join | Effect when W2 wrote last |
|---|---|---|
| `build_football_live_prop_board` for NCAAF (`app.py:9687`, `9707`). Used by `/sports/ncaaf` (`:34265`), the props screener (`:42117-42124`), `archive_daily_candidates.archive_football` (`:308-325`) and `qc_cfb_board.py:31-32` | `odds_lookup.get(game)`, where the prop's `Game` is the raw Odds API label `"{away_team}@{home_team}"` (`fetch_player_props.py:364-367`) and the lookup is keyed `AwayFull@HomeFull` (`app.py:6534-6538`) | every prop misses its game. Spread/total environment notes (`:9892`, `:9974`) come out empty, **and those rows are archived without game context** |
| `_football_total_move_map` (`app.py:6890-6918`, used at `7089-7094`) | `(away, home)` from `NCAAF_LineMovementCurrent.csv`, which **only W1 writes**, in Odds API names | total movement blank on the preseason/totals card |
| Price-dependent display: book name, `SpreadOdds`, ML (`build_game_market_lookup` `app.py:18040-18075`; `build_live_game_lookup` `:6522-6555`; `format_game_market_summary`) | — | shows `Book = "CFBD consensus"` and invented `-110` / averaged ML as if they were prices. CLAUDE.md §10: availability states exist "so missing context never reads as neutral" |
| Time ordering (`build_football_live_games` sort, `app.py:6727`) | string sort on `Time` | `H:MM AM/PM` sorts wrongly ("9:00 AM" after "7:00 PM") |
| `refresh_live_scores.sport_has_live_window` (`refresh_live_scores.py:105-110`, `:135`) | parses `Time` as `%H:%M` | CFBD times don't parse, so the 20-minute pregame gate is skipped. (Separately, `_today_str` at `:91` uses server-local time, not Eastern) |

### 4c. Name-agnostic readers (safe under either)

These go through `cfb_current_form._resolve` (exact name or longest school prefix,
`cfb_current_form.py:58-69`) or `fetch_cfb_weather._resolve` (`:57-66`):

- `_cfb_line_move` (`app.py:46196-46220`)
- `_cfb_prior_context` (`:46275-46311`)
- `matchup_read` / `total_read` in the matchup card (`:46378`, `:46413`)
- buy-low/sell-high slate (`:45668-45675`)
- period profiles (`:45829-45834`)
- `_cfb_form_legs` (`:32896-32912`). Note it emits "a priced side (-110)", which is a real price under W1 and invented under W2.

They are still affected by **universe and horizon** (12 vs 130 days; unlined games appear only under
W2) and by line values (consensus mean vs a single book).

### 4d. Generic consumers whose output depends on the last writer

- `build_football_live_games` callers: `/sports/ncaaf` (`app.py:34261-34264`), method pages
  (`:34371-34374`), home slate (`:34102-34118`), preseason markets (`:7053-7079`), the cross-league
  schedule (`:38667`), sport-hub tables (`:19255`, `:22944`), the date map (`:33076`), and
  `qc_cfb_contradictions.py:21-22`.
  - Book shown: W1 → the first book after the sort (`build_live_game_lookup` dedupes `keep='first'`
    on `Away, Home, Date, Time`, `app.py:6529-6531`, which with `fetch_game_lines.py:285` ordering
    is alphabetically first). W2 → "CFBD consensus".
  - Horizon: 130 days vs 12.
- `qc_odds_feed.py`: "NCAAF game lines" freshness is the **file mtime** of
  `data/odds/NCAAF_Odds.csv` (`:39`, `:47`, `:93-104`). A W2 write, **including a header-only one**,
  marks the Odds API family FRESH. That masks a W1 failure from the authoritative post-refresh health
  check (`run_daily.py:365-373`), and the "props STALE while lines FRESH" rule (`:99-104`) can be
  tripped by CFBD activity alone.
- `report_feed_availability.py`: NCAAF schedule = `NCAAF_Schedule.csv` (`:72-75`). The upcoming-event
  count behind the **paid** props-probe verdict (`:121-145`, `:165-185`) counts CFBD's full FBS
  universe under W2 and Odds API lined events under W1.
- `services/injury_feed_qc.py:34-35`: "games expected" check; same universe dependence.
- `diag_refresh_incident.py:167` labels the file "Odds API / CFBD lines", which already admits the
  ambiguity.
- `fetch_cfb_weather.py:87-88`: groups by `(Away, Home)` and handles both Time formats (`:67-75`).
  The names it writes into `cfb_weather.json` follow the last writer, and that is what feeds
  `_cfb_weather` (4a).
- `research/cfb_gameline/cfb_gameline_capture.py:30`: research only, but assumes the "in-season
  weekly feed" is the Odds API shape (its history sibling is `NCAAF_OddsAPI_GameLines_History.csv`).
- **F5 slate manifest** (`fetch_player_props.py:100-102`): **NBA-only** today; NCAAF is not bound.
  If NCAAF is ever added, it must bind to the W1 artifact. W2 school names would never match the
  Odds API props `Game` labels, so coverage would read 0/N and fail closed on every run.
- Validation itself: W1's `validate_feed` prior (`fetch_game_lines.py:442-447`) is normally W2's
  file. The collapse check rejects W1 whenever `len(W1) < 0.5 × len(W2 prior)` and the prior has ≥5
  rows (`feed_validation.py:143-147`). The timestamp-regression check (`:98-109`) compares W1's ET
  tz-naive `LastUpdated`, parsed **as UTC** (`utc=True`), against W2's true-UTC fetch time. That is an
  apples-to-oranges gate in both directions.

---

## 5. What users see on a given day (question 4)

Read from the code paths (prod timing needs §7 evidence):

| Day type | Between W1 (`run_daily.py:38`) and W2 (`:183`) | After W2 until the next day's W1 |
|---|---|---|
| CFBD healthy, key set, not latched | W1 Odds API (if it published) | **W2 CFBD contract**: consensus lines, invented −110, school names, 12-day horizon, no real book |
| CFBD latched (`refresh_cfb_data.py:171-177`, exit 3, no request) | W1 | **W1 all day** (or yesterday's W2 if W1 failed or was rejected) |
| `CFBD_API_KEY` absent (`:167-169`) | W1 | W1 all day |
| CFBD first call returns 429 (not yet latched) | W1 | **All three files header-only.** The CFB board has no games and no lines until the next W1 run. The latch is set only if a *later* CFBD step exits non-zero with quota text (`:220-242`) |
| CFBD `/games` OK, `/lines` fails (429 mid-run) | W1 | W2 schedule with games, **odds file with zero rows**. Real W1 lines are replaced by "no lines" |
| W1 rejected by validation against a W2 prior (collapse/regression) | yesterday's W2 | W2 |

So in steady state with CFBD healthy, **for most of each day the CFB product shows the CFBD contract,
under a filename and loaders that monitoring and the props join treat as the Odds API contract.** The
Odds API lines are only on the page for the minutes between steps 38 and 183. They do survive in
`NCAAF_LineMovement*`, which never includes CFBD rows.

---

## 6. Proposal (question 5)

### 6.1 Options

**A. One canonical publisher** (e.g. a `publish_ncaaf_slate.py` that merges both sources into
`NCAAF_Odds.csv` with per-row provenance).
- Pros: one file and one name for readers.
- Cons: the sources arrive at different times under independent quota states, so the merge must run
  after both, or the slate goes stale until it does. A merge bug blocks both sources. The merged file
  still mixes priced book rows with unpriced consensus rows in one schema, so every price reader has
  to filter by provenance anyway. And it keeps the legacy name carrying two meanings.

**B. Separate artifacts, one writer each, every reader bound to exactly one; compose at read time
where a surface needs both.** **← Recommended.**
- Each artifact has one producer, one validator and one contract.
- Each publish validates against **its own** prior, which fixes finding 5.
- Price surfaces can never see an unpriced row.
- Monitoring can report two honest families.
- CFBD quota state no longer changes which contract a page shows.
- The only joint view is a **pure function** (no file), so last-writer-wins is impossible by
  construction.

### 6.2 Target artifacts

| Artifact | Writer (sole) | Contract |
|---|---|---|
| `data/odds/NCAAF_Odds.csv` + mirror `data/schedules/NCAAF_Odds.csv` + alias `data/schedules/NCAAF_Schedule.csv` | `fetch_game_lines.py:main` for `americanfootball_ncaaf` | **Odds API only.** Unchanged columns plus provenance (below). Executable book prices |
| `data/odds/NCAAF_CFBD_Lines.csv` (new) | `fetch_ncaaf_slate_cfbd.py` publish fn | **One row per (CFBD game, CFBD provider).** No averaging. **No** `SpreadOdds/OverOdds/UnderOdds` columns at all, because prices are unavailable, not −110. ML only as provided per provider |
| `data/schedules/NCAAF_CFBD_Schedule.csv` (new) | same | full FBS slate (lined or not), CFBD ids and school names |
| `data/tracking/NCAAF_CFBD_publish.json` (new) | same, written **last** | generation manifest: run id, sha256 + row count of both CFBD files, window, weeks fetched, request outcome per week |

Keeping the legacy `NCAAF_Schedule.csv` name for W1's alias is deliberate: that matches every other
sport (`fetch_game_lines.py:28-58`). The CFBD universe moves to the new name.

### 6.3 Provenance columns

- **W1 (added; existing columns unchanged for back-compat):**
  - `Source` = `odds_api`
  - `SourceEventId` (= `GameID`)
  - `SourceUpdatedAtUTC`: the bookmaker `last_update`, tz-aware UTC, same approach as `aee1fe2` for NFL props
  - `FetchedAtUTC`
  - `PublishRunId`

  The validator's timestamp-regression check moves to `SourceUpdatedAtUTC`, which removes the
  ET-parsed-as-UTC skew (finding 5).
- **W2:**
  - `Source` = `cfbd`
  - `CfbdGameId`, `Provider`
  - `StartDateUTC`
  - `Date` (ET), `Time` (ET, **24h `HH:MM`**, aligned to W1)
  - `HomeSchool`, `AwaySchool`, `HomeConference`, `AwayConference`
  - `Spread`, `Total`, `HomeML`, `AwayML` as provided
  - `FetchedAtUTC`, `PublishRunId`

  `LastUpdated` is **not** carried, because CFBD gives no market-update time. Freshness for this
  artifact is retrieval freshness and is labeled that way.
- **Read-time composer:** `load_ncaaf_slate()` in `app.py`. It returns one row per game:
  - the game universe from the CFBD schedule (when available), else the W1 alias
  - market columns from W1, matched via `cfb_current_form._resolve`, with `LineSource = odds_api:<book>`
  - when W1 has no row, CFBD consensus at display time with `LineSource = cfbd_consensus` and
    **price fields = None**
  - when neither has a line, `LineSource = none`

  Its derived cache key must include **both** artifacts' file tokens (CLAUDE.md §4: a builder that
  reads a file missing from its version token serves stale).

### 6.4 Reader rebinding (who changes)

| Reader | Bind to |
|---|---|
| `load_ncaaf_game_market_odds` / `load_ncaaf_schedule` and all price surfaces (§4b, §4d boards, home slate, preseason markets, cross-league schedule, `build_football_live_prop_board`, `archive_football`, `_football_total_move_map`) | **W1** (no code change beyond loaders becoming truly single-source) |
| §4a CFBD-name joins (Best Spots, Big Favorites, totals board, totals pace, matchup streaks/weather) | `load_ncaaf_slate()` **and** name-resolve every join through `cfb_current_form._resolve` instead of raw strings, which makes them writer-agnostic regardless |
| `fetch_cfb_weather.py:28` | **W2** schedule (CFBD lane script, needs the full FBS universe). Keep `_resolve` |
| `qc_odds_feed.py` | "NCAAF game lines" = W1 only. Add a separate non-Odds family "NCAAF CFBD lines" read from the W2 manifest, so a CFBD write can never mark Odds API fresh |
| `report_feed_availability.py:72-75` (paid props gate) | **W1** alias, since props are Odds API events. Report the W2 universe count alongside as information |
| `services/injury_feed_qc.py:34-35` | explicit list: W2 schedule, then W1 alias, with the source named in the result |
| `refresh_live_scores.py:105-110` | **W1** (its scores come from the Odds API; `HH:MM` parse) |
| `diag_refresh_incident.py:167` | split into two rows (W1, W2) |
| `fetch_player_props.SPORT_EVENT_MANIFESTS` (if NCAAF is ever added) | **W1** |

### 6.5 W2 hardening (needed under either option)

- Request failure on any week (HTTP error, including 429) → **exit non-zero, write nothing**, and
  print the quota text so `refresh_cfb_data._is_provider_quota_exhausted` (`:158-163`) latches at
  this step. Today the latch only trips at a later step.
- Zero weeks fetched, or `/lines` failed for any fetched week → no publish.
- Validate both frames (own spec: required columns, `Source=='cfbd'`, integer `CfbdGameId`, no price
  columns, no conflicting `(CfbdGameId, Provider)` duplicates, collapse vs **its own** prior). Write
  both temps, `os.replace` both, then write the manifest last. Readers that need pair consistency
  check the manifest hashes.
- Write via `services.atomic_csv.atomic_write_csv`.

### 6.6 Migration steps

0. **Gather evidence first** (§7 P1–P9). It decides whether anything is urgent today. For example,
   if the latch has been set all season, users have been on W1 all along and the 4a tools are the
   broken ones.
1. Add `qc_ncaaf_odds_single_writer.py` (§6.8) **in failing mode** against current code. It must
   flag W2 as a second writer of the legacy paths. This proves the QC catches the bug before the fix.
2. W2: switch the outputs to the new paths and apply §6.5. Stop writing all three legacy paths in
   the same commit.
3. W1: add the provenance columns; move the regression check to `SourceUpdatedAtUTC`.
4. Add `load_ncaaf_slate()` and rebind the §6.4 readers. `_resolve` every CFBD-keyed join.
5. `qc_odds_feed` / `report_feed_availability` / `injury_feed_qc` / `diag` rebinding.
6. Run the QC suite: the new QC, `qc_sport_registry.py`, `qc_cfb_board.py`,
   `qc_cfb_contradictions.py`, `qc_cfb_readiness.py`, `qc_game_lines_freshness.py`,
   `qc_odds_feed.py`, `qc_feed_availability.py`, `qc_freshness_contract.py`, `qc_slate_validation.py`,
   and `py -3 -m py_compile app.py`.
7. Deploy (push → `bk-deploy`, **restart**). The first prod W1 run after deploy compares against a
   prior that is still the old W2 file. Either run W1 once with `--allow-collapse` under
   `recover_odds_fetch.py` (receipted), or accept one rejected day. Decide which beforehand.
8. Update CLAUDE.md §13 and `docs/PROJECT_MAP.md` (W1/W2 split; reader binding table).

### 6.7 Validation per artifact

- **W1:** existing `GAME_LINES_SPEC`, plus NCAAF-specific checks:
  - `Source=='odds_api'` on every row
  - `Book` ∈ the requested bookmaker titles
  - `GameID` matches the Odds API id shape
  - no `CFBD consensus` row
  - `SpreadOdds` / `OverOdds` / `UnderOdds` not all exactly −110 across the file (a canary for a
    regression to invented prices)
- **W2:** its own spec (§6.5), plus the manifest hash match.

### 6.8 `qc_ncaaf_odds_single_writer.py` (style of `qc_nfl_roster_single_writer.py`)

The roster QC's static inventory would **miss both F7 writers as written**, so it must be extended:

- W1 writes through `atomic_write_csv(...)`, which is not in `_WRITE_FUNCS`
  (`qc_nfl_roster_single_writer.py:56-57`).
- W2 writes through `open(p, "w")` where `p` is a **`for`-loop target** (`fetch_ncaaf_slate_cfbd.py:134`).
  `_taint` only follows `Assign` / `AnnAssign` (`:93-102`).

Checks:

1. **Static inventory** over tracked `*.py`, plus a text scan of tracked `*.sh` **and `batch/*.bat`**
   (batch is part of this problem's history). Governed names:
   - `NCAAF_Odds.csv`, `NCAAF_Schedule.csv` → approved `{("fetch_game_lines.py","main")}`
   - `NCAAF_CFBD_Lines.csv`, `NCAAF_CFBD_Schedule.csv`, `NCAAF_CFBD_publish.json` → approved
     `{("fetch_ncaaf_slate_cfbd.py", <publish fn>)}`

   Extensions to the roster QC:
   - taint `for` targets iterating a tainted iterable
   - treat `atomic_write_csv` and `csv.DictWriter` over a tainted handle as writes
   - scan `--output` / `--schedules-output` / `--schedule-alias-output` arguments in scripts
2. **Multi-sport W1 disambiguation:** the AST cannot tell which sport `fetch_game_lines` writes, so
   run it behaviorally in a temp tree with `get_json` stubbed for `americanfootball_ncaaf`. Assert it
   writes exactly the 3 W1 paths and nothing under the W2 names.
3. **W2 behavior** in a temp tree, `_get` stubbed:
   - Success: only W2 paths are created. The seeded legacy W1 files keep sha256, inode, size and
     mtime unchanged.
   - 429 on the first call, 429 on `/lines` only, and zero weeks: W2 artifacts unchanged, exit
     non-zero, quota text present, legacy files unchanged.
   - Temp files cleaned up in every case.
4. **Contract firewall:**
   - The W1 validator rejects a frame with `Book="CFBD consensus"` or integer GameIDs.
   - The W2 validator rejects any price column.
   - `load_ncaaf_game_market_odds()` against a temp tree never returns a `Source!='odds_api'` row.
5. **Reader binding:** a text scan asserting the legacy and new names appear only in an allowlisted
   set of reader files, so a new reader has to choose a contract deliberately.
6. **Mutation:** re-insert the old `for p in (... "NCAAF_Odds.csv", ...): open(p,"w")` loop into W2.
   Check 1 must flag it as a second writer, and check 3 must see the legacy fingerprint change.
7. Synthetic only: no network, no app boot except where the composer is exercised, with the same
   module-stub technique as the roster QC (`:188-199`).

Wire it into `run_all_scorecards` / `QC_FOOTBALL.bat` like the roster QC.

### 6.9 Rollback

All data paths are gitignored, so rollback is code-only: `git revert` the F7 commit(s), push, and
`bk-deploy` restarts the service (restart, not reload: CLAUDE.md §3). After rollback the next W2
run writes the legacy paths again (old behavior). The new `NCAAF_CFBD_*` files become orphans that
nothing reads, and they are harmless to leave. Nothing needs deleting. Before step 2 ships, record
the sha256 of the three legacy files on prod so a rollback can be checked against a known state.

### 6.10 Acceptance evidence on production (after deploy)

Collected read-only over **≥3 consecutive daily runs, including at least one where CFBD is latched or
skipped if that occurs naturally** (never induce a 429 on prod):

1. `qc_ncaaf_odds_single_writer.py` passes on the box.
2. For each run: the mtimes of the three legacy files fall inside the "Football line movement" step
   window of that run's operator log, and **never** inside the "CFB data refresh" window. The W2
   files and manifest fall only inside the CFB window.
3. Legacy `NCAAF_Odds.csv`: the distinct `Book` set ⊆ {DraftKings, FanDuel, BetMGM, Caesars}; zero
   `CFBD consensus`; every `Source=='odds_api'`; GameIDs all Odds-API-shaped.
4. W2 manifest hashes match the files; `Source=='cfbd'` throughout; no price columns.
5. On a latched/skip day: W2 file sha256 unchanged across the run; legacy files governed by W1 only.
6. `qc_odds_feed` reports NCAAF Odds API and NCAAF CFBD as separate families with their own ages.
7. Reader spot checks (owner session):
   - `/tools/cfb-best-spots` shows live cards when the slate has qualifying games, with `LineSource`
     visible.
   - The NCAAF props board shows spread/total environment notes (props joined to games).
   - No "CFBD consensus" book and no invented −110 anywhere on a price surface.

---

## 7. Questions that need production evidence: exact read-only checks

Run on the prod box via SSM, as `ubuntu`, in `/opt/bankrollkings`. None of these makes a provider
request or writes anything.

- **P1. Operator flags and schedule.**
  `systemctl cat bk-daily.service bk-daily.timer`. Confirm `ExecStart` (is `--continue-on-error`
  present?) and `OnCalendar`.
  `systemctl list-timers --all --no-pager | grep bk-`.
- **P2. No other prod writer.**
  `grep -l -E "ncaaf|cfbd|run_daily|fetch_game_lines" /etc/systemd/system/bk-*.service /usr/local/bin/bk-*.sh 2>/dev/null`
  and `sudo crontab -l -u ubuntu; sudo crontab -l` (expect no NCAAF writers outside `bk-daily`).
- **P3. Which writer owns each file right now.**
  ```
  stat -c '%y %s %n' data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv data/tracking/NCAAF_LineMovementCurrent.csv
  head -1 data/schedules/NCAAF_Schedule.csv
  venv/bin/python -c "import csv,collections;r=list(csv.DictReader(open('data/odds/NCAAF_Odds.csv')));print(len(r),collections.Counter(x['Book'] for x in r).most_common(6),collections.Counter(x['SpreadOdds'] for x in r).most_common(3),[x['GameID'] for x in r[:3]],[x['Time'] for x in r[:3]],[x['LastUpdated'] for x in r[:2]])"
  ```
  A schedule header of `Date,Time,Away,Home` only, or `Book == CFBD consensus`, means W2 wrote last.
- **P4. Daily ordering and outcomes.**
  `f=$(ls -t logs/daily_operator_*.log | head -1); grep -n -E "^\[(PASS|FAIL|SKIP|WARN)[^]]*\] (Football line movement|CFB data refresh|Odds feed health)|CFB game slate|PROVIDER_QUOTA_EXHAUSTED|Strong validation FAILED|row-count collapse|timestamp REGRESSION|Saved [0-9]+ rows to .*NCAAF" "$f"`.
  Repeat for the last ~14 logs (`ls -t logs/daily_operator_*.log | head -14`) to get how often each
  state occurs.
- **P5. CFBD latch state.**
  `sudo -u ubuntu bash -c 'set -a; . /opt/bankrollkings/.env; d=${BK_RUNTIME_DIR:-/opt/bankrollkings/data/tracking}; cat "$d/cfbd_quota_state.json" 2>/dev/null || echo "no latch file"'`.
  This echoes only the latch file, never the env.
- **P6. Spread sign agreement** (only when both contracts are observable, e.g. from a W1 snapshot in
  `NCAAF_LineMovementHistory.csv` vs a W2 file of the same day): compare a handful of games' home
  spreads by matchup. Read-only Python over the two CSVs.
- **P7. Header-only incidents so far.**
  `wc -l data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv`, plus a P4 grep for
  `schedule: 0 games` / `odds:     0 games` in operator logs (W2 prints these, `fetch_ncaaf_slate_cfbd.py:138-140`).
  Those lines are inside `refresh_cfb_data`'s captured output, which shows only the last line per
  step (`refresh_cfb_data.py:216-219`), so they may not be visible. If not, rely on P3 at known
  times.
- **P8. Props ↔ odds join rate (§4b).**
  `venv/bin/python -c "import csv;o=list(csv.DictReader(open('data/odds/NCAAF_Odds.csv')));k={r['AwayFull']+'@'+r['HomeFull'] for r in o};p={r['Game'] for r in csv.DictReader(open('data/props/NCAAF_Props.csv'))};print(len(p),len(p&k))"`.
- **P9. Odds-API validation interference (finding 5).**
  `grep -h -A3 "ncaaf_game_lines" logs/daily_operator_*.log | grep -E "collapse|REGRESSION|Strong validation" | sort | uniq -c`.

---

## 8. Open questions for the owner (not production evidence)

- **Q-A.** Should the adjacent `LastUpdated`-dropped-by-`_format_game_market_odds` finding
  (`app.py:17986`, inert fail-closed gate across all game-line sports) become its own ticket? It is
  outside F7 but affects every reader in §4. To confirm without importing `app` on prod:
  `grep -n "keep_cols = \[col for col in \['Date', 'Time', 'Away'" app.py` on the deployed commit.
- **Q-B.** For the composed slate, when W1 has no line for a game, should the CFBD consensus spread
  or total be shown at all (labeled `cfbd_consensus`, no price), or abstain? This proposal shows the
  number without a price. The owner may prefer abstaining.
- **Q-C.** First-run collapse handling at cutover (§6.6 step 7): a receipted `--allow-collapse`
  recovery run, or accept one rejected day?
