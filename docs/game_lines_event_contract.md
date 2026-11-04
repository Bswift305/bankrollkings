# Game-lines event contract (`game_lines_event_v1`)

Shared, configurable event-aware validation for game-lines feeds. Code:
`services/feed_validation.py` (`validate_game_lines_event_slate`, `NBA_GAME_LINES_EVENT_SPEC`, the frozen
rule block above it). Fetcher wiring: `fetch_game_lines.py` (`EVENT_AWARE_GAME_LINES_SPORTS`). QC:
`qc_game_lines_event_slate.py`, `qc_odds_age_timezone.py`.

## Why

`fetch_game_lines.py` pulls with `commenceTimeFrom=now`, so a new candidate holds only not-yet-started
games. The old whole-file test (`validate_feed` + `GAME_LINES_SPEC`, reject when rows < 50% of the prior)
compared it against a prior that still held last night's **played** games: a normal 45 -> 15 NBA
turnover was rejected, and `refresh_nba_daily.py` then skipped every later step.

## Contract

| Rule | Behaviour |
|---|---|
| Identity | `GameID` (Odds API event id). Never guessed. |
| Kickoff | `EventCommenceAtUTC`, canonical `YYYY-MM-DDTHH:MM:SSZ`, copied from provider `commence_time` into **every** newly produced row. `Date`/`Time` stay Eastern display columns only. |
| Slate | Current/future only. `kickoff <= now` is excluded from both sides and never published (`kickoff == now` is started; `now + 1s` is eligible). |
| Vanished event | A previously published, still-future event with **zero valid rows** in the new pull rejects at any size (`EVENT_VANISHED`). |
| Coverage | **No per-event minimum.** One structurally valid current quote lets an event publish. An overlapping event that lost any book or market is listed as `COVERAGE_DEGRADED`; a new event with fewer books than requested is `NEW_EVENT_SPARSE`. Either sets `coverage_status = COVERAGE_DEGRADED` (published, never labelled complete). |
| Provider | Any provider error, or zero usable current events, rejects. |
| Publish | `atomic_write_csv_set`: odds file, schedules mirror and schedule alias are all staged and checked before any `os.replace`; on reject every output is byte-identical. |
| Receipt | `data/tracking/_last_game_lines_fetch_<sport>.json`, written on every exit path: outcome, exit code, validation receipt, and sha256 before/after for each output. |

### Frozen malformed-row rule (v1)

Whole-feed **reject**: R1 missing required column · R2 blank `GameID` / `Away` / `Home` or non-canonical
kickoff · R3 one `GameID` with conflicting kickoff or teams · R4 a non-null line/price that is not a
finite number · R5 conflicting duplicate `(GameID, Book)`, unparseable `LastUpdated`, wrong-sport path,
or a `(GameID, Book)` quote older than the prior's · R6 provider error · R7 zero usable current events ·
R8 prior unreadable / no identity / prior kickoff not establishable · R9 vanished still-future event.

Market-level **null** (fields blanked, row kept if another market survives): M1 `h2h` needs both
`AwayML` and `HomeML` · M2 `spreads` needs `Spread` and `SpreadOdds` · M3 `totals` needs `Total > 0`
plus `OverOdds` and `UnderOdds`. A valid price is finite with `|price| >= 100` (American).

Row **drop** (counted): D1 blank `Book` · D2 no valid market left · D3 started (`kickoff <= now`).

### Legacy bridge (first transition only)

The prior file written before this change has no `EventCommenceAtUTC`. The comparison is **not**
skipped. Each prior row's comparison instant is derived from its explicit Eastern `Date` + `Time`
(`%Y-%m-%d %H:%M`) with `zoneinfo` `America/New_York`, DST-aware
(`services/timeutils.eastern_wall_to_utc_strict`). It is labelled `DERIVED_LEGACY_KICKOFF` in the receipt,
used **only** to classify prior events as started/future, and never written to the new file. Missing,
unparseable, ambiguous (fall-back fold) or nonexistent (spring-forward gap) times fail closed
(`PRIOR_BASELINE_INVALID`). After the first successful publish the prior carries provider UTC and the
bridge is no longer used.

## Governed no-game result

An empty provider response alone is **never** proof that there are no NBA games. The decision belongs to
an authoritative schedule that is independent of the odds provider (`services/nba_schedule_authority.py`):

| Schedule verdict (checked **before** any paid call) | Provider | Outcome |
|---|---|---|
| fresh authoritative source says zero games for the governed Eastern service date | not called | `NO_GAMES_SCHEDULED` (benign, zero credits) |
| games expected | zero events | `VALIDATION_FAILED` / `PROVIDER_ZERO_EVENTS_GAMES_EXPECTED` (fail closed) |
| missing / stale / ambiguous / circular | zero events | `SCHEDULE_UNAVAILABLE` (alerting, fail closed) |

**Audit result: no authoritative independent NBA schedule source exists** (file:line detail in the module
docstring). `NBA_Schedule.csv` is written by this same fetch (schedule alias), `load_schedule` returns the
`NBA_Odds`-derived frame while `BK_NBA_STATS_ENABLED` is off, `fetch_schedule.py` (nba_api) is gated,
dev-only (batch files, not `run_daily.py`), falls back to `NBA_Odds.csv` and uses a naive service date, and
the Odds API `/events` listing is the same provider. So `AUTHORITATIVE_SOURCES` is empty, the verdict is
always `SCHEDULE_UNAVAILABLE`, and **no code path emits `NO_GAMES_SCHEDULED`**. An NBA provider-empty answer
is recorded as `SCHEDULE_UNAVAILABLE` (exit 1, files untouched, verdict stored in the receipt);
`refresh_nba_daily` and `refresh_line_movement_snapshots` classify it as a failure, never `OK`.

Needed before `NO_GAMES_SCHEDULED` may exist: a licensed, provider-independent NBA season schedule with
provider game ids, UTC tip times, `fetched_at` + source provenance and an explicit Eastern service date,
refreshed on prod through `run_daily.py`, with a freshness bound and its own QC. QC:
`qc_nba_no_game_governance.py`.

## Single publisher + shared lock

Every NBA lines publish goes through `services/nba_lines_publisher.publish` (entered from
`fetch_game_lines.main` for `basketball_nba`; `run_fetch` refuses an NBA fetch when the lock is not held).

| | |
|---|---|
| Lock | `services/process_lock.ExclusiveLock`: `fcntl.flock(LOCK_EX\|LOCK_NB)` on Linux (the contract); `msvcrt.locking` on Windows for local QC. fd-based, released by the kernel on exit or crash; the file is never unlinked and its content is informational only. |
| Path | `$BK_RUNTIME_DIR/locks/nba_game_lines.lock` > `/opt/bankrollkings-runtime/locks/nba_game_lines.lock` (POSIX default, outside the checkout). Windows dev falls back to the gitignored `.runtime/generated/locks/`. `$BK_NBA_LINES_LOCK_PATH` is a QC override honoured **only** when it resolves inside the runtime root or inside a `qc_*` directory directly under the system temp dir; anything else is `LOCK_UNAVAILABLE`. Never set it on prod. |
| Containment | `services/process_lock.open_validated_lock_file`: the lock dir must `realpath` inside the runtime root and the file directly inside the lock dir. A symlinked lock **dir** or lock **file** is refused (lstat, then `O_NOFOLLOW` where available); after open the fd inode must equal the path's inode, and on POSIX the file must be regular with exactly one link. Refused -> `LOCK_UNAVAILABLE`, exit 76, before any request. |
| Permissions (POSIX) | Lock dir created `0700`, lock file `0600`. An existing looser dir/file **owned by this euid** is repaired (`chmod 0700` / `fchmod 0600`) and re-verified; one owned by another uid, or still loose, is refused (`LOCK_UNAVAILABLE`). Every job that takes the lock must run as the same user (`ubuntu`). Windows has no POSIX modes; those checks are skipped there (dev only) and the QC reports them as `[SKIP]`, not as passes. |
| Order | lock **before** any paid request -> reuse decided **under** the lock -> the one validation + atomic 3-file publish -> publisher receipt `data/tracking/_last_nba_lines_publish.json` (written only by the holder). |
| Contention | `SKIPPED_LOCKED`, exit 75: no paid request, no receipt, no write, never `OK`/`PASS`. Unopenable or rejected lock location: `LOCK_UNAVAILABLE`, exit 76, same guarantees. |
| Reuse | bk-daily (`--allow-reuse --lock-wait-seconds 120`, step timeout 240 s) reuses a publish from the last **90 minutes** (`REUSE_WINDOW_MINUTES`) when the fetch receipt is `UPDATED` / exit 0 / `game_lines_event_v1`, its UTC time is valid and not in the future, and every output's sha256 on disk equals the receipt's `sha256_after`. Zero credits. **The 90-minute window is duplicate-fetch suppression only; the executable boundary stays the 6h CLOCK-A rule** (a reused file ages exactly like a fetched one). |

### Lock state machine

| State | Condition | Outcome | Exit | Class | Paid request |
|---|---|---|---|---|---|
| S0 | lock location rejected (containment / symlink / perms) or unopenable | `LOCK_UNAVAILABLE` | 76 | alerting | none |
| S1 | lock still held by another process after the bounded wait | `SKIPPED_LOCKED` | 75 | alerting | none |
| S2a | acquired **without** waiting, `--allow-reuse`, receipt + hashes valid | `REUSED_FRESH` | 0 | benign | none |
| S2b | acquired **after waiting** for another holder, `--allow-reuse`, receipt + hashes **re-read under the lock** and valid | `REUSED_FRESH_AFTER_LOCK` | 0 | benign | none |
| S2b' | acquired after waiting, `--allow-reuse --no-fetch-after-lock`, no valid fresh publish | `NO_FRESH_AFTER_LOCK` | 1 | alerting | none |
| S2b'' | acquired after waiting, `--allow-reuse` (default), no valid fresh publish | fetch normally under the lock (S3) | | | one |
| S2c | no `--allow-reuse` (4-hourly job, manual run): it is the refresh | S3 | | | one |
| S3 | fetch + event validation + atomic publish | `UPDATED` / `PROVIDER_ERROR` / `VALIDATION_FAILED` / `SCHEDULE_UNAVAILABLE` | 0 / 1 | benign / alerting | one |

Another process holding the lock is never a success by itself: success after a wait requires the
receipt and every output hash to verify under the lock. There is no pre-lock reuse path. bk-daily
treats `UPDATED`, `REUSED_FRESH` and `REUSED_FRESH_AFTER_LOCK` as lines-ready (`run_outcomes.LINES_READY`);
anything else skips the lines-dependent steps as `SKIPPED_BLOCKED_BY_LINES`.

QC: `qc_nba_lines_lock.py` (real two-process contention, waiting after a failed holder, crash release,
location/symlink enforcement with a call-counting stub provider, POSIX permission rules, reuse rules).

## Stale NBA/WNBA props: central enforcement

The 6h rule is enforced in the **loaders**, not per page: `load_props` / `load_wnba_props` /
`load_live_props_feed` / `load_wnba_live_props_feed` return only executable rows
(`_executable_props_frame`): rows exist, the freshest provider `LastUpdated` is a timezone-aware UTC
instant (naive = Eastern wall clock), not > 5 min in the future, and <= `LIVE_LINES_MAX_AGE_HOURS`. A caller
may tighten the window but never loosen it, and `require_fresh=False` no longer returns stale rows.
`props_feed_status(sport)` reads the raw file only to report the honest state (actual update time, age,
reason). The three raw-CSV readers (cross-sport dashboard, free previews, derivatives) and the hot-hands
"playable" filter go through the same gate. Caches: `_build_file_token` adds an executable-state token for
any NBA/WNBA props input (a file that stops being rewritten keeps its mtime, so a fresh-era build would
otherwise be served for the full TTL); Best Lines / Risk Radar carry the token as their version; NBA/WNBA/
Elite runtime snapshots are refused when the feed is withheld or the snapshot predates the feed.

**v2 contradiction, resolved:** `qc_nba_market_only` asserted "stale props -> zero rows" by calling the
loader with `require_fresh=True`, but `build_market_only_board` called it with `require_fresh=False`, and the
QC's board/page checks used future-dated (2099) fixtures through a stubbed loader. The QC tested the loader,
not the board. Now the board passes `require_fresh=True`, the loader ignores any loosening, the board
re-verifies whatever frame it receives, and the QC renders the board + page through the real loader.
Route-by-route proof: `qc_nba_wnba_props_stale.py`.

## Required before any stronger coverage rule

A per-event book minimum or a book-retention ratio must **not** be added from intuition. A read-only
historical coverage audit (per-event book and market counts across past NBA fetches, by hours to tip)
has to come first. It has not been done; v1 only records `COVERAGE_DEGRADED`.

## F5 migration (NFL / NCAAF game lines)

F5 (unmerged branch) built a separate football game-lines slate validator. It should move onto this
contract instead of merging as is:

1. Add `NFL_GAME_LINES_EVENT_SPEC` / `NCAAF_GAME_LINES_EVENT_SPEC` (`dataclasses.replace` of the NBA spec)
   and add the sport keys to `EVENT_AWARE_GAME_LINES_SPORTS` in `fetch_game_lines.py`. No new validator.
2. Their first publish runs the legacy bridge exactly like NBA did (a prior without `EventCommenceAtUTC`).
3. Football-specific needs go in the spec (fields), not in a fork of the function. Anything F5 has that
   this contract lacks (for example a different book set) is a spec field plus a QC case.
4. Re-point F5's QCs at `validate_game_lines_event_slate`, keep `qc_game_lines_event_slate.py`'s scope
   check, and drop F5's own validator.
5. Customer containment: football surfaces already fail closed through `get_lines_refresh_meta`, but
   `_format_game_market_odds` drops `LastUpdated`, so in production that gate never fires for any sport
   except NBA (which now keeps it via `_format_nba_game_market_odds`). Migrating a sport should include
   keeping its provenance columns the same way.

## Stale threshold

Customer surfaces use CLOCK A from `services/freshness_contract.py`:
`LIVE_MARKET_MAX_AGE_HOURS = 6` (`app.LIVE_LINES_MAX_AGE_HOURS`) on the freshest provider `LastUpdated`,
computed between timezone-aware UTC instants. NBA game lines refresh once a day, so outside roughly six
hours after a refresh NBA lines show as stale and their prices are withheld.

## Migration matrix (cross-sport)

The NBA patch is **not** expanded to any other sport until its production behaviour is proven: at least
one real slate turnover published on the event contract on prod (receipt `outcome=UPDATED`,
`contract=game_lines_event_v1`), the legacy bridge used exactly once, and the customer surfaces showing
the actual update time with stale prices withheld. Each row below is a separate, reviewed change.

| Sport | Game-lines validation | Customer freshness | Plan |
|---|---|---|---|
| NBA | `game_lines_event_v1` (**this branch**) | `_format_nba_game_market_odds` keeps `LastUpdated` + `KickoffUTC`; CLOCK-A 6h gate fires; `/game-lines`, `/sports/nba` and the matchup lens withhold stale or started prices | Ship, then prove on prod before any other row moves |
| NFL / NCAAF | Whole-file `GAME_LINES_SPEC` today; F5 (unmerged football game-lines slate branch) has its own validator | Shared `_format_game_market_odds` drops `LastUpdated` | Move F5 onto **this** shared event-aware contract (see "F5 migration"); do not merge F5's separate validator |
| MLB / WNBA | Whole-file `GAME_LINES_SPEC` | Shared formatter drops `LastUpdated` | Migrate before their next active season (spec + `EVENT_AWARE_GAME_LINES_SPORTS` entry + provenance-keeping formatter + QC case) |
| Every sport | -- | Timezone-aware ages (`services/timeutils`, naive `LastUpdated` = Eastern wall clock) and an honest stale state (actual update time shown, prices non-executable past `LIVE_LINES_MAX_AGE_HOURS`) | Required for every sport's migration |

**Known gap, all non-NBA sports:** `load_wnba_game_market_odds`, `load_mlb_game_market_odds`,
`load_nfl_game_market_odds` and `load_ncaaf_game_market_odds` all load through the shared
`_format_game_market_odds`, whose `keep_cols` does not include `LastUpdated`. `get_lines_refresh_meta`
therefore sees no timestamp, reports `age_hours=None` / `is_stale=False`, and the fail-closed stale gate
in `build_game_market_lookup` **never fires** for those sports: a days-old WNBA/MLB/NFL/NCAAF line can
still render as current. Fixing this is part of each sport's migration row above, not of the NBA patch.

The 6-hour executable-price rule (`LIVE_LINES_MAX_AGE_HOURS`, CLOCK A) is an owner decision. No
migration may loosen it.

## Follow-up design item: independent NBA props event adapter

Owner decision (kept): when NBA game lines fail to publish, `refresh_nba_daily.py` reports
`player_props` as `SKIPPED_BLOCKED_BY_LINES`. Props are lines-dependent because
`fetch_player_props.py` validates NBA props against an independent eligible-event manifest, and that
manifest is `NBA_Odds.csv` (`SPORT_EVENT_MANIFESTS` / `_eligible_event_keys`). Without a fresh lines
publish the manifest can still list played games, so props coverage would be judged against the wrong
slate.

Props may run without lines **only** after an independent NBA props event adapter exists. Requirements:

1. It establishes event identity (provider event id) and kickoff (provider UTC `commence_time`) directly
   from authoritative props-side provider data (the props `/events` listing), not from `NBA_Odds.csv`.
2. The denominator for slate coverage stays independent of the props response itself (a missing event
   must not drop out of both numerator and denominator).
3. Started/unknown-kickoff events fail closed exactly as in this contract.
4. It has its own written contract and QC before `STEP_LINES_DEPENDENCY["player_props"]` changes from
   `True`. Until then the skip stays.
