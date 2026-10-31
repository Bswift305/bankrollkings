# Research Candidate 2D1 — Props Source-Time Raw Diagnostic Receipt + Proposed Contract

**Status: DIAGNOSTIC RECEIPT + proposed source-time contract for review. No code/artifact/env/service/flag
changed.** One authorized paid, read-only Odds-API raw-capture for a single current NFL event (2026-10-31).

## Conclusion: `MARKET_TIMESTAMP_AVAILABLE`

The provider's authoritative update time exists at the **market** level of the event-odds response (not the
bookmaker level). The producer reads the **bookmaker** level, which is absent — that is the whole cause of the
blank `SourceUpdatedAtUTC`. The correction is therefore well-defined: source `SourceUpdatedAtUTC` from the
**bound market-level `last_update`**.

## Diagnostic receipt (sanitized)

| Field | Value |
|---|---|
| SSM command id | `330ddbaa-40ea-4a28-910e-11703e7bd958` (instance `i-08d2fd818875381dd`) |
| Gate (zero-network) | `report_feed_availability` nfl `verdict=FRESH`, `events_next_7d=14` → **PROCEED** |
| Event (existing, future) | `EventId=9255ca8f32aea590d00aa57de79f6bb6`, kickoff `2026-11-01T18:00:00Z`, 181 board rows |
| Request | exactly one `GET /v4/sports/americanfootball_nfl/events/{id}/odds` — same params as `fetch_player_props` (bookmakers `draftkings,caesars,fanduel,betmgm`, regions `us`, the 12 default NFL markets, `oddsFormat=american`, `dateFormat=iso`). No retry, no fan-out, no second event. |
| HTTP status | **200** |
| Cost (headers) | `x-requests-last=9` (this request = 9 credits), `x-requests-remaining=94304`, `x-requests-used=5696` |
| Response counts | bookmakers **3**, markets_total **23**, emitting `(book,market)` combos **23** |
| `bookmakers[].last_update` | **present 0/3**, parseable 0 — absent (this is the extraction gap) |
| `bookmakers[].markets[].last_update` | **present 23/23, parseable UTC 23, distinct 3** — authoritative + varies |
| Deterministic binding | **every** emitting `(book,market)` combo binds to a market-level timestamp (23/23) |
| Data hygiene | response saved to a unique `0600` `/tmp` file, cleanup installed before the request, **deleted after** (`response_tmp_deleted=True`); the API key, request URL, raw payload, player markets, and prices were **never printed** |

## Why the current extraction misses it

`fetch_player_props.parse_market_rows` computes `source_updated_utc = to_utc_iso(bookmaker.get("last_update"))`
**once per bookmaker, before the market loop** (line 381). But the event-odds response carries `last_update`
**per market**, and the bookmaker-level field is empty — so `to_utc_iso` returns `""` for every row, and
`LastUpdated` (`… or fetched_at`) falls back to the fetch time. The timestamp was always present in the raw
response; it was read at the wrong nesting level.

## Final proposed source-time contract (design-only — NOT implemented)

- **Authoritative source time = the provider's MARKET-level `last_update`** for the specific market, normalized
  to zero-offset UTC via the existing `to_utc_iso` (tz-aware only; naive/missing → stays blank).
- **Narrowest producer correction** (`fetch_player_props.parse_market_rows`): move the `SourceUpdatedAtUTC`
  source **into the per-market loop** and set it from `market.get("last_update")` for that market's rows
  (instead of the bookmaker-level value before the loop). Change nothing else.
- **Never** fall back to `fetched_at` for `SourceUpdatedAtUTC`; leave it **blank** when a market has no
  parseable UTC `last_update` (explicit unavailable, never fabricated).
- **Deterministic binding, no aggregation:** each emitted row is one `(player, line, book, market)` — exactly
  one market `last_update` applies. (`LastUpdated`'s fetch-time fallback is a separate, out-of-scope concern;
  the RC fix does not require changing it.)
- **Fail-closed QC proving:** (a) every emitted row with a provider market time has a parseable zero-offset
  UTC `SourceUpdatedAtUTC`; (b) **no** `SourceUpdatedAtUTC` equals the fetch time / file mtime; (c) rows with
  no provider market time keep it **blank**; (d) the value is genuinely per-market (varies when the provider
  varies — the raw response showed 3 distinct market timestamps).
- **CLOCK-A/B + adapter unchanged:** this does not alter the adapter's required column (`SourceUpdatedAtUTC`),
  the 6h/30h thresholds, or `services/freshness_contract.py`.

## Next steps (for your approval — nothing implemented)

1. Approve the two producer corrections. Per your directive, implement them as **separate reversible commits**:
   (i) roster drop-null-identity rows (`fetch_nfl_player_week.py` + fail-closed QC), and (ii) props market-time
   (`fetch_player_props.parse_market_rows` + fail-closed QC).
2. Regenerate **once** (both are paid/producer runs → run the paid-fetch gate first; both write atomically).
3. Re-run the adapter dry-run against the corrected roster + corrected props → it must report
   `RESOLVED_capturable ≥ 1`.
4. Only then revisit the `0700` state-dir provisioning and the ON-state pilot — both still parked/blocked.

**Nothing was changed on prod; one 9-credit paid request was made as authorized; production capture remains
OFF and the pilot remains blocked until both corrected artifacts yield ≥1 governed, capturable selection.**
