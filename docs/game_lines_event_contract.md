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
