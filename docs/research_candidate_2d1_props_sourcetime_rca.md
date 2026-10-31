# Research Candidate 2D1 — Props `SourceUpdatedAtUTC` Root-Cause Audit (READ-ONLY)

**Status: DIAGNOSIS for review. Nothing changed on prod** — no code/artifact/env/service/flag touched, **no
paid fetch made.** Read-only prod measurements via SSM on `i-08d2fd818875381dd` (2026-10-31). Why
`NFL_Props.csv.SourceUpdatedAtUTC` is blank while `LastUpdated` is populated.

## Verdict

- **`LastUpdated` is Bankroll Kings' FETCH / file-generation time — NOT a provider/bookmaker update time.**
  Proven below. **It must not be copied into `SourceUpdatedAtUTC`** — that would manufacture provenance.
- The blankness is **producer-wide** (every sport's props board), caused by the producer reading
  `bookmaker.get("last_update")`, which resolves **empty for all player-props rows**, so
  `SourceUpdatedAtUTC` (no fallback) is blank and `LastUpdated` (`… or fetched_at`) falls back to fetch time.
- **One decisive fact is unresolved read-only** (deliverable 6): whether the raw Odds-API event-odds response
  carries `last_update` at the **market** level (which the producer does *not* read) or omits it entirely.
  No raw payload is cached, so this needs **one authorized raw-capture diagnostic (a paid fetch)** before any
  producer change. The narrowest correction (deliverable 9) depends on that answer.

## 1. Producers / transformations that write `NFL_Props.csv`

- **`fetch_player_props.py` is the writer of record.** Confirmed: `NFL_Props_MarketCoverage.csv` (written
  *only* by `fetch_player_props.write_market_coverage`) shares NFL_Props.csv's exact mtime (both 13:00:43Z),
  `LastChecked='2026-10-31 13:00'`. Pipeline: `fetch_event_props` → `parse_market_rows` → `build_dataframe` →
  `merge_market_history` → `validate_feed` → **`atomic_write_csv`** (line 839, temp+replace; writes are atomic).
- `capture_nfl_prop_lines.py` **reads** the board (does not write it); `import_props.py` is a manual import
  utility, not the daily producer. The daily producer wired into `run_daily.py` is `fetch_player_props.py`.

## 2. Lineage of both columns (raw → CSV)

Raw: Odds API `GET /v4/sports/{sport}/events/{id}/odds` → `payload.bookmakers[]`, each with `key/title/
last_update` and `markets[]` (each market also has its own `last_update`).

In `parse_market_rows`:
- `fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")` (line 382) — **the fetch time**.
- `source_updated_utc = to_utc_iso(bookmaker.get("last_update"))` (line 381) → **`SourceUpdatedAtUTC`**
  (line 418). `to_utc_iso` returns `""` for a missing/naive value — **no fallback**.
- `"LastUpdated": to_iso_local(bookmaker.get("last_update")) or fetched_at` (line 414) — Eastern-display of
  the provider time **or, when that is empty, the fetch time.**
- `build_dataframe` carries both columns; `merge_market_history` does not touch `SourceUpdatedAtUTC` (not in
  its merge-column list), so each new row keeps its parsed value → `atomic_write_csv`.

Because `bookmaker.get("last_update")` is empty for every player-props row, `SourceUpdatedAtUTC` = blank and
`LastUpdated` = `fetched_at`.

## 3. Exact meaning of `LastUpdated` (PROVEN) — it is the fetch / file-generation time

Measured on the live `NFL_Props.csv` (2304 rows):

| Evidence | Result | Meaning |
|---|---|---|
| distinct `LastUpdated` values | **1** (`2026-10-31 13:00`) | one timestamp for the whole file |
| `LastUpdated` vs file mtime | within 120s for **2304/2304** (max 43s) | equals the file-generation time |
| distinct `LastUpdated` per Book | max **1** | does not vary by bookmaker |
| distinct `LastUpdated` per Game | max **1** | does not vary by event |

A genuine per-bookmaker source-update time would vary across 3 books, 13 games, 9 markets. It does not — it is
a single value equal to the file mtime. **`LastUpdated` here = Bankroll Kings' fetch/file-generation time**
(the `fetched_at` fallback), **not** provider update time, **not** event time.

## 4. `LastUpdated` cannot substitute for `SourceUpdatedAtUTC`

Proven by §3: wrong semantics (fetch, not source), no provider lineage, and not row-level (a single value).
Copying it into `SourceUpdatedAtUTC` would **fabricate provenance** — label the platform's fetch time as the
bookmaker's price-update time. **Prohibited.**

## 5. Representative-row quantification (books / games / markets / one-sided)

Live `NFL_Props.csv`: 2304 rows, **3 books, 13 games, 9 markets**; **1066 one-sided** quotes + **1238 two-way**.

| Column | blank | parseable | unparseable(non-blank) | distinct | future-dated | note |
|---|---|---|---|---|---|---|
| `SourceUpdatedAtUTC` | **2304 (100%)** | 0 | 0 | 0 | 0 | uniformly empty (no invalid/conflicting values to classify) |
| `LastUpdated` | 0 | 2304 | 0 | **1** | 0 | == file mtime (fetch time) |
| `EventCommenceAtUTC` | 0 | 2304 | 0 | 5 (per game) | **2304 (all future)** | authoritative kickoff — good for capture |

So `SourceUpdatedAtUTC` has nothing to grade (all blank); `EventCommenceAtUTC` is clean and fully future;
`LastUpdated` is a single fetch timestamp.

## 6. Does the raw source provide a bookmaker `last_update`? — UNRESOLVED read-only (gated)

- **Producer-wide, not NFL-specific:** cross-sport, every player-props board has `SourceUpdatedAtUTC` **100%
  blank** and `LastUpdated` **100% parseable** — MLB (449), NBA (726), NCAAF (2552), NFL (2304), WNBA (72). So
  `bookmaker.get("last_update")` is empty for all player props across all sports.
- **No raw payload is cached** (`/opt/bankrollkings/data/odds/` holds only game-line odds CSVs, not raw
  player-props JSON), so the raw provider field cannot be inspected read-only.
- **The decisive unknown:** the Odds API event-odds response carries `last_update` at BOTH the bookmaker and
  the **market** level; the producer reads only the **bookmaker** level. Either the player-props response does
  not populate bookmaker-level `last_update` (but may carry it per-market), or it omits it entirely. **This
  cannot be settled without a raw sample.**
- **Recommended gated step (paid fetch, needs explicit approval + the paid-fetch availability gate):** capture
  ONE event's raw `/events/{id}/odds` JSON to `/tmp`, inspect `bookmakers[].last_update` AND
  `bookmakers[].markets[].last_update`, then delete. This decides deliverable 9's correction.

## 7. Consumers of both columns + behavior change from populating `SourceUpdatedAtUTC`

- **`LastUpdated` consumers:** `merge_market_history` sort key (line 642); the board's CLOCK-A render
  freshness (`get_props_refresh_meta`); `services/feed_validation`, `qc_slate_validation`. ⚠️ *Related
  observation (out of scope):* because `LastUpdated` is the fetch time, the customer-facing CLOCK-A props
  freshness is effectively measuring fetch time, not the provider's price timestamp — a separate latent
  concern worth its own review, not changed here.
- **`SourceUpdatedAtUTC` consumers:** the dark RC adapter (step 5a); `capture_nfl_prop_lines.py` (the
  three-clock capture); `services/feed_validation`; `qc_nfl_capture_precision`, `qc_nfl_props_source_fields`,
  `qc_slate_validation`. Populating it with an **authoritative** provider time changes **no customer-facing
  board** (the UI renders `LastUpdated`, not `SourceUpdatedAtUTC`); it gives the capture + adapter real
  per-row provenance. No negative behavior change.

## 8. Reconciliation with the CLOCK-B freshness contract

`SourceUpdatedAtUTC` (the adapter's step-5a per-row requirement) is a **different** clock from CLOCK-B
(`refresh_cadence_hours`, file mtime, 30h) and from CLOCK-A (render/live-market, 6h). The fix must **not**
change the adapter's required column or any freshness threshold to make the pilot pass. It must make the
**producer** carry an **authoritative per-row UTC provider source time**, left **explicitly blank** when the
provider gives none (never fabricated). CLOCK-A/B stay as declared in `services/freshness_contract.py`.

## 9. Narrowest producer-level correction + fail-closed QC (CONTINGENT on §6)

**IF the raw response carries a provider `last_update` (most likely at the market level):**
- Correction: in `parse_market_rows`, source `SourceUpdatedAtUTC` from the authoritative provider field
  (the market's `last_update` for that market — or the bookmaker's, whichever the raw sample proves),
  normalized by the existing `to_utc_iso` (tz-aware UTC only; naive/missing → stays blank). **Never** fall
  back to `fetched_at` for `SourceUpdatedAtUTC`.
- Deterministic aggregation rule: each row is one `(player, line, book, market)` — exactly one provider
  `last_update` applies; **no** cross-book/market averaging. (If a displayed row ever merges multiple books,
  declare a deterministic rule — e.g. the max/most-recent — explicitly; today rows are per-book.)
- Fail-closed QC proving: (a) every row with a provider time has a parseable **zero-offset UTC**
  `SourceUpdatedAtUTC`; (b) **no** row's `SourceUpdatedAtUTC` equals the fetch time / file mtime (guards
  against fetch-time mislabeling); (c) rows with no provider time keep it **blank** (explicit unavailable,
  never fabricated); (d) the value is genuinely row-level (varies by book/game when the provider does).

**IF the raw response has NO `last_update` anywhere:** there is no authoritative source time; `SourceUpdatedAtUTC`
stays blank and the RC pilot on NFL player props remains blocked until the provider exposes a source time **or**
a governed decision formally changes the adapter's freshness contract — **not** a silent change to pass.

**Either way this is a CODE change — NOT done here.**

## 10. Regeneration / atomic-publication / rollback / post-regen dry-run

For the later, separately-approved run (NOT executed here; it requires a **paid fetch** → run the paid-fetch
availability gate first):
1. **Back up** the live board: `cp -p NFL_Props.csv NFL_Props.csv.bak-<utc>`.
2. **Regenerate** with the corrected producer — `fetch_player_props.py` already writes **atomically**
   (`atomic_write_csv`, temp+replace) behind `validate_feed`, so a concurrent web read never sees a half file.
3. **Validate:** the new fail-closed QC (§9) + `qc_nfl_props_source_fields`; then the adapter dry-run against
   the **corrected roster** → must report `RESOLVED_capturable ≥ 1`.
4. **Rollback:** `mv NFL_Props.csv.bak-<utc> NFL_Props.csv` (atomic; old bytes preserved).

---

**Bottom line:** `SourceUpdatedAtUTC` is blank because the provider's `last_update` (as the producer reads it —
bookmaker level) is empty for all player props across all sports; `LastUpdated` is a fetch-time fallback and
**must not** be substituted. The narrowest correction hinges on one gated raw-capture (does the event-odds
response carry a per-market `last_update`?). No code/artifact/env/service/flag changed; no paid fetch made. The
roster correction stays parked; per the reviewer, after approval implement the roster and props producer
corrections as separate reversible commits and regenerate once. The pilot stays blocked until **both** corrected
artifacts yield ≥1 governed, capturable board selection.
