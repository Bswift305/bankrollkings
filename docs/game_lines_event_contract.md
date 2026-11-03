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
