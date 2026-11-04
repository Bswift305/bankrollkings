# NCAAB (men's) first-slice design contract — 2026-11-04

> **DESIGN ONLY.** No code, routes, templates, timers, paid calls or production changes are authorized by
> this document. It turns the owner's eleven NCAAB decisions (ledger, 2026-11-04) and the read-only
> discovery audit (`docs/ncaab_discovery_audit_20261104.md`) into an implementable contract with acceptance
> tests. Implementation starts only after owner review, and every paid request waits for the cost probe in §14.
>
> Read against exact production `17b5e69` (`.claude/worktrees/props-utc`). Line numbers refer to that commit.
>
> **Notation:** **[V]** = verified in code at `17b5e69` (or on a named branch). **[I]** = provider behaviour or
> an inference **not** verified here; each [I] is either measured by the cost probe (§14) or listed as an open
> question (§18).

---

## 0. Binding inputs

| # | Owner decision (2026-11-04) | Where this design enforces it |
|---|---|---|
| 1 | Men's first; registry ready for women's; not combined in release 1 | §3.6, §12 (`Competition` key everywhere; no women's rows, keys or routes in release 1) |
| 2 | 4h freshness target; provisional cap **7,500 credits/month**; no timer/paid call until per-call cost verified | §13 (4h cadence, designed not enabled), §14 (budget guard + probe) |
| 3 | Every licensed book the provider returns, each separately; no consensus-as-price; no invented default book | §4 (book registry), §6 (one row per book/market/selection; no medians) |
| 4 | Scores from Odds API `/scores`, after a separately approved cost probe; no ESPN/unofficial data | §8, §14 Probe B |
| 5 | No external efficiency metric; only facts derived from our licensed scores | §11.3, §17 |
| 6 | Neutral site = `UNKNOWN` unless an authoritative source confirms; no manual guessing | §9.3 |
| 7 | No historical-odds purchase; governed forward capture only | §7 |
| 8 | Games-only registry: lines, schedule, scores, grading; props/injuries/simulations disabled | §12 |
| 9 | Shell cleanup (separate: Safeguard B `fix/ncaab-shell-honesty`) | §1 prerequisite |
| 10 | Shared stale-line contract fixed first (separate: "Game-lines consolidated correction") | §1 prerequisite |
| 11 | "Injuries unavailable" stated plainly; never zeros or inferred availability | §10, §11 |
| — | Frozen timestamp direction: `SourceUpdatedAtUTC` = provider time, `FetchedAtUTC` = our ingestion time, both tz-aware ISO-Z; never infer a zone; `LastUpdated` never used for authority | §6.2, §9.1, §15 (every NCAAMB artifact has **no** `LastUpdated` column) |

Doctrine filters applied (`BANKROLL_KINGS_DOCTRINE.md` §6): every component maps to a loop step (Discover
= slate; Evaluate = matchup + evidence; Build/Save = ticket handoff; Track/Learn = grading + CLV), and no
component makes a claim we cannot prove out-of-sample. Nothing on the do-not-build list (§7) appears.

---

## 1. Prerequisites (separate work; must land before NCAAMB code merges)

| ID | Prerequisite | State | Why NCAAMB depends on it |
|---|---|---|---|
| PRE-1 | **Safeguard A** `fix/fetch-output-path-guard`: unknown or unconfigured sport fails **before** any network call or write; explicit per-sport paths | built + gated, not deployed | Today `fetch_game_lines.py:395` falls back to `SPORT_OUTPUTS[DEFAULT_SPORT]` (NBA) and `_sport_tokens("basketball_ncaab")` returns `()` (`:100-106`), so an NCAAB fetch could overwrite `NBA_Odds.csv` [V]. NCAAMB never uses `fetch_game_lines.py` (§6), but the guard must exist so nobody can run it ad hoc |
| PRE-2 | **Safeguard B** `fix/ncaab-shell-honesty`: fabricated 60–71 confidence rows and coverage over-claims removed | built + gated, not deployed | The new slate replaces the shell; release 1 must not ship alongside example confidence on real team names |
| PRE-3 | **Game-lines consolidated correction** (decision 10): 5h shift, loader dropping timestamp fields (fail-open), spread-price side bug, `LastUpdated` → `SourceUpdatedAtUTC` + `FetchedAtUTC` | pending surface map | NCAAMB uses its **own** long-form contract (§6), so it does not inherit those bugs. But shared helpers it reuses (`_quote_clock_status`, `_canonical_kickoff_utc`, ticket boundary) must be the corrected ones, and NCAAMB must not ship while other sports' line pages still misstate freshness on the same site |
| PRE-4 | **Run-receipt contract** `services/run_receipts.py` (NBA v6, `fix/nba-market-v6-on-17b5e69` `6e7bd6a`) | branch only [V] | §13 reuses its token/receipt rules. Either v6 merges first, or the module is generalized (stage family parameter) in its own reviewed change. NCAAMB does not copy it |
| PRE-5 | **Cost probe** (§14) executed with owner approval and its receipt reviewed | not run | Decision 2: no timer and no paid call in production code paths until per-call cost is verified |

---

## 2. Architecture overview

```
              (free)                 (3 credits [I→probe])          (2 credits [I→probe])
 /v4/sports/basketball_ncaab/events   /odds h2h,spreads,totals us    /scores?daysFrom=3
            │                                  │                              │
            └──────────────┬───────────────────┘                              │
                           ▼                                                  ▼
            fetch_ncaamb_market.py  (ONE writer, run lock, token receipt)    fetch_ncaamb_scores.py (same lock family)
                           │                                                  │
     resolve teams (§3) · books (§4) · events (§5) · long-form quotes (§6)    finals (§8)
                           │                                                  │
   data/odds/NCAAMB_Events.csv        data/odds/NCAAMB_GameLines.csv     data/scores/NCAAMB_Finals.csv
   data/tracking/ncaamb_snapshots/<EventDateET>.csv  (append-only, §7)              │
                           └──────────────────────┬───────────────────────────────┘
                                                  ▼
                               grade_ncaamb_results.py → data/tracking/NCAAMB_Results.csv
                                                  ▼
             app loaders (read-only) → /sports/ncaamb (slate) · /sports/ncaamb/game/<event_id> (matchup)
                                                  ▼
                 user-selected leg → existing ticket boundary (2–8, quote-change 409) / Bet Tracker
```

**New modules (designed, not built):**

| Module | Role | Imports `app`? |
|---|---|---|
| `services/ncaamb_identity.py` | team registry + alias resolver (§3) | no |
| `services/sportsbook_registry.py` | shared book licence registry (§4) | no |
| `services/ncaamb_contract.py` | column specs, enums, validators, fact-state function (§6, §10) | no |
| `fetch_ncaamb_market.py` | events + lines fetch, validate, atomic publish, snapshot append (§5–§7) | no |
| `fetch_ncaamb_scores.py` | `/scores` fetch + finals publish (§8) | no |
| `grade_ncaamb_results.py` | grading against captured pre-tip quotes (§8.3) | no |
| `refresh_ncaamb_market.py` | orchestrator: budget preflight → season gate → lock → stages → receipts (§13) | no |
| `app.py` loaders + 2 routes + 2 templates | read-only rendering (§11) | — |

No NCAAMB module writes outside the paths in §15. No NCAAMB module reads `LastUpdated`.

---

## 3. Canonical men's team registry and aliases

### 3.1 Files (tracked in git; reference data, never written at runtime)

Runtime jobs **never** write these files (deploy dirty-tree trap: a tracked file written by a job blocks
`git pull --ff-only`). They change only through a reviewed commit.

**`data/reference/ncaa_schools.csv`** — one row per institution, shared by men's and women's.

| Column | Type | Rule |
|---|---|---|
| `SchoolId` | str | `sch:<slug>`, lowercase ASCII `[a-z0-9-]`, immutable once published (e.g. `sch:miami-fl`, `sch:miami-oh`) |
| `SchoolName` | str | official short name, display only |
| `State` | str | 2-letter, display + disambiguation evidence only |
| `ReviewedBy` / `ReviewedAtUTC` | str / ISO-Z | required |

**`data/reference/ncaamb_teams.csv`** — one row per men's program.

| Column | Type | Rule |
|---|---|---|
| `Competition` | enum | `NCAAMB` (release 1: the only value permitted) |
| `TeamId` | str | `ncaam:<slug>`, immutable; the slug equals the school slug (`ncaam:miami-fl`) |
| `SchoolId` | str | FK to `ncaa_schools.csv` |
| `DisplayName` | str | e.g. `Miami (FL)` — **never** a bare ambiguous string (§3.3) |
| `Conference` | str or `UNKNOWN` | owner-reviewed; `UNKNOWN` allowed; display/filter only |
| `Division` | enum | `D1` · `NON_D1` · `UNKNOWN` |
| `Status` | enum | `ACTIVE` · `RETIRED` (ids are never reused) |
| `ReviewedBy` / `ReviewedAtUTC` | str / ISO-Z | required |

**`data/reference/ncaamb_team_aliases.csv`** — one row per exact provider string.

| Column | Type | Rule |
|---|---|---|
| `Competition` | enum | `NCAAMB` |
| `Provider` | enum | `oddsapi` (release 1) |
| `ProviderName` | str | the provider string **exactly as observed** (e.g. `Miami (OH) RedHawks`) |
| `NormalizedKey` | str | `normalize_provider_name(ProviderName)` (§3.2), stored so review diffs show it |
| `TeamId` | str | FK to `ncaamb_teams.csv` |
| `Status` | enum | `ACTIVE` · `RETIRED` |
| `Evidence` | str | where the string was observed (probe run id / receipt id) and why it maps to this team |
| `ReviewedBy` / `ReviewedAtUTC` | str / ISO-Z | required; an alias without review is not loaded |

### 3.2 Resolution rule (exact, fail-closed)

```
resolve_team(competition, provider, provider_name) -> (status, team_id | None)
  competition is REQUIRED (no default); provider is REQUIRED.
  key = normalize_provider_name(provider_name)
  if key in BLOCKED_BARE_NAMES[competition]          -> ("AMBIGUOUS", None)
  rows = ACTIVE aliases where (Competition, Provider, NormalizedKey) == (competition, provider, key)
  len(rows) == 0                                       -> ("UNMATCHED", None)
  len({r.TeamId for r in rows}) > 1                    -> ("AMBIGUOUS", None)
  else                                                 -> ("RESOLVED", rows[0].TeamId)
```

`normalize_provider_name` does **only**: Unicode NFKC; map `’ ‘ ʼ ´ \`` to `'`; trim; collapse internal
whitespace to one space; casefold. It does **not** strip punctuation, parentheses, periods, hyphens,
mascots, `St.`/`Saint`, or `State`, and it never matches by prefix, token, substring, edit distance or
"contains". `Miami (OH) RedHawks` and `Miami OH RedHawks` are different keys; if the provider ever emits
both, each needs its own reviewed alias row.

`BLOCKED_BARE_NAMES['NCAAMB']` (normalized) = `miami`, `usc`, `st. mary's`, `saint mary's`, `st mary's`,
`loyola`, `texas a&m-c`, `unc`, `penn`, `liu`. A blocked key is `AMBIGUOUS` even if someone adds an alias row,
and the alias QC fails if such a row exists. The list only grows by reviewed commit.

### 3.3 The named collision cases

Provider strings below are **[I]** (the probe's `team_names.csv` gives the real ones). The rule is what is
binding: each distinct provider string gets its own reviewed alias row; no row is created by inference.

| Case | Required outcome |
|---|---|
| Miami (FL) vs Miami (OH) | Two teams, `ncaam:miami-fl` / `ncaam:miami-oh`, display names `Miami (FL)` / `Miami (OH)`. Bare `Miami` is blocked → `AMBIGUOUS`. A mascot-bearing string (e.g. `Miami Hurricanes`, `Miami (OH) RedHawks`) maps only by its own alias row |
| St. John's vs Saint Joseph's | `ncaam:st-johns` and `ncaam:saint-josephs` are distinct. `St. John's Red Storm` never resolves to Saint Joseph's (different `NormalizedKey`, no fuzzy step). `Saint John's` (a D-III school) is not aliased; if seen it is `UNMATCHED` |
| Saint Mary's vs Mount St. Mary's | `ncaam:saint-marys-ca` and `ncaam:mount-st-marys` are distinct. Bare `Saint Mary's` / `St. Mary's` are blocked → `AMBIGUOUS`. `Mount St. Mary's Mountaineers` is a different key from any `Saint Mary's …` string by construction |
| USC vs South Carolina vs USC Upstate | Three teams: `ncaam:usc` (Southern California), `ncaam:south-carolina`, `ncaam:usc-upstate`. Bare `USC` is blocked. `USC Trojans` → `ncaam:usc` only by alias row; `South Carolina Upstate Spartans` / `USC Upstate Spartans` → `ncaam:usc-upstate` only by alias rows; `South Carolina Gamecocks` → `ncaam:south-carolina` |
| UConn vs Connecticut | One team, `ncaam:uconn`. Both `UConn Huskies` and `Connecticut Huskies` (if observed) are alias rows to the **same** `TeamId`. The QC asserts both resolve to the same id |

Also in the adversarial fixture (audit §1.13): Texas A&M vs Texas A&M-Corpus Christi vs Texas A&M-Commerce;
Loyola Chicago vs Loyola (MD) vs Loyola Marymount; Saint Louis vs SIU-Edwardsville; UNC vs UNC Asheville /
Greensboro / Wilmington; LIU / Long Island; Penn vs Penn State.

### 3.4 Event-level identity status

Each event carries `IdentityStatus`:

- `RESOLVED`: both teams `RESOLVED` and `HomeTeamId != AwayTeamId`.
- `UNMATCHED`: at least one side `UNMATCHED`, none `AMBIGUOUS`.
- `AMBIGUOUS`: at least one side `AMBIGUOUS`.
- `SELF_MATCH`: both sides resolve to the same `TeamId` (an alias error). Fail closed, alerting.

Consequences of anything other than `RESOLVED`:

- The event's market facts are still **shown**, with the provider names verbatim and a chip `Team identity
  unverified`. The price is a real book quote.
- The event is **non-executable** (`TEAM_IDENTITY_UNRESOLVED`): it cannot be added to a ticket. This is the
  fail-closed choice; see open question Q7.
- All team context abstains: form, records, streaks and evidence panel team items read `Unavailable — team
  identity unverified`.
- The event's finals and grades are stored by `EventId` but excluded from every per-team aggregate.

### 3.5 How unmatched names surface

- **Runtime list** `data/tracking/ncaamb_identity_unresolved.csv` (gitignored, upserted by the market writer
  only). Columns: `Competition`, `Provider`, `ProviderName`, `NormalizedKey`, `Status`
  (`UNMATCHED`/`AMBIGUOUS`), `FirstSeenAtUTC`, `LastSeenAtUTC`, `EventCount`, `SampleEventId`.
- Every market run receipt carries `identity: {events, resolved, unmatched, ambiguous, self_match,
  unresolved_names: [...]}`.
- `qc_ncaamb_identity.py` reports the unresolved share. `> 0` is `WATCH` (visible, non-blocking). Any
  `SELF_MATCH`, duplicate alias key or blocked-name alias is `FAIL`.
- **Resolution path:** the owner (or a reviewer) adds alias rows by commit, with `Evidence` naming the receipt.
  Nothing auto-promotes.
- **Seeding:** the probe writes `team_names.csv` (observed strings). A helper may produce
  `ncaamb_alias_candidates.csv` for review, but that file is **never** read by the resolver.

### 3.6 Women's later (designed for, not built)

- Same schema with `Competition=NCAAWB`, `TeamId` prefix `ncaaw:`, files `ncaawb_teams.csv` and
  `ncaawb_team_aliases.csv`, provider sport key `basketball_wncaab` ([I]: absent from code today, to be
  verified with a free `/v4/sports` call at that time).
- `ncaa_schools.csv` is shared, so `ncaam:uconn` and `ncaaw:uconn` both point to `sch:uconn`.
- The resolver's `competition` argument is mandatory, so a men's lookup can never return an `ncaaw:` id. QC
  asserts this.
- Every NCAAMB artifact path, lock, receipt family and route carries `ncaamb`/`NCAAMB`. Women's gets parallel
  `ncaawb` paths. There is no combined file and no gender-agnostic path.

---

## 4. Sportsbook registry (decision 3)

`regions=us` without a `bookmakers` filter returns **every** bookmaker the provider has in that region [I].
Some of them may not be US-licensed sportsbooks (the region mixes regulated and offshore books [I]).
"Track every **licensed** sportsbook" therefore needs an explicit, reviewed licence list. Whether a given book
is licensed is a legal determination for the owner (Phase 5); this design does not make it.

**`data/reference/sportsbooks.csv`** (tracked, shared by every sport, owner-reviewed):

| Column | Type | Rule |
|---|---|---|
| `BookKey` | str | provider key, exact (e.g. `draftkings`) |
| `Provider` | enum | `oddsapi` |
| `DisplayTitle` | str | e.g. `DraftKings` |
| `LicenseStatus` | enum | `LICENSED_US` · `NOT_US_LICENSED` · `UNREVIEWED` |
| `Source` | str | evidence for the status |
| `ReviewedBy` / `ReviewedAtUTC` | str / ISO-Z | required for `LICENSED_US` and `NOT_US_LICENSED` |

Rules:

- Only `LICENSED_US` books are written to `NCAAMB_GameLines.csv` and snapshots.
- A `NOT_US_LICENSED` or unknown book key is **not published**. Its quote count is recorded in the run receipt
  (`books_excluded: {key: {status, quotes}}`), so nothing disappears silently. An unknown key is treated as
  `UNREVIEWED` and raises `WATCH`.
- No default book anywhere. A row without a `BookKey` is rejected (§6.4 D1). The display title comes from this
  registry, never from a hard-coded fallback such as `or 'DraftKings'`.
- `SINGLE BOOK`: an event/market priced by exactly one licensed book carries `BookCount=1` and the label
  `Single book — CONFLICTED` (CLAUDE.md §10.3, an MLB/WNBA-derived rule, labelled as such on NCAAMB pages).

---

## 5. Licensed schedule and event identity

### 5.1 Identity

- `EventId` = Odds API event `id`. It is never derived from teams or dates, and it is never guessed.
- `EventCommenceAtUTC` = provider `commence_time`, parsed strictly (§9.1) and written canonical
  `YYYY-MM-DDTHH:MM:SSZ`.
- The provider listing (`/events`, free [I]) is the **only** schedule source. There is no claim of slate
  completeness: the slate covers provider-listed events only, and the page says so (`Games listed by our odds
  provider`).

### 5.2 `data/odds/NCAAMB_Events.csv` (current state; one row per `EventId`)

| Column | Type | Notes |
|---|---|---|
| `Competition` | enum | `NCAAMB` |
| `SportKey` | str | `basketball_ncaab` |
| `EventId` | str | non-blank, unique |
| `EventCommenceAtUTC` | ISO-Z | strict |
| `EventDateET` | `YYYY-MM-DD` | `to_eastern_date_str(EventCommenceAtUTC)` |
| `HomeTeamProvider` / `AwayTeamProvider` | str | provider strings verbatim |
| `HomeTeamId` / `AwayTeamId` | str or blank | blank unless `RESOLVED` |
| `HomeResolve` / `AwayResolve` | enum | `RESOLVED` · `UNMATCHED` · `AMBIGUOUS` |
| `IdentityStatus` | enum | §3.4 |
| `NeutralSite` | enum | `TRUE` · `FALSE` · `UNKNOWN`. **Release 1 writes `UNKNOWN` only** (§9.3) |
| `NeutralSiteSource` | str | blank in release 1 |
| `ListingStatus` | enum | §5.3 |
| `LinesPosted` | bool | at least one licensed book quote in the latest successful lines run |
| `PriorCommenceAtUTC` | ISO-Z or blank | most recent previous commence value, if it changed |
| `CommenceChangeCount` | int | ≥ 0 |
| `DuplicateGroupId` | str or blank | §5.5 |
| `FirstSeenAtUTC` / `LastListedAtUTC` | ISO-Z | our observation times |
| `FetchedAtUTC` | ISO-Z | the run that last wrote this row |
| `FetchRunId` | str | 32-hex run token (§13.3) |

Change history goes to **`data/tracking/NCAAMB_EventChanges.csv`** (append-only): `EventId`, `Field`
(`commence`/`home`/`away`/`listing`), `OldValue`, `NewValue`, `ObservedAtUTC`, `FetchRunId`.

### 5.3 Listing status (derived from observation only; never asserts a reason)

| `ListingStatus` | Condition | Customer label |
|---|---|---|
| `LISTED` | in the latest successful `/events` run | — |
| `NOT_LISTED` | previously listed, absent from the latest successful run, no completed score | `No longer listed by our odds provider` (we do **not** say postponed or cancelled) |
| `COMPLETED` | `/scores` reports `completed=true` | `Final` |
| `NO_RESULT` | `EventCommenceAtUTC + 48h` passed, never `COMPLETED` | `No final result received` |

A home/away swap for an existing `EventId` is recorded in `EventChanges`; the event becomes non-executable
for the run (`EVENT_TEAMS_CHANGED`) and grading uses only snapshots taken after the swap.

### 5.4 Games without posted lines; postponements; cancellations

- **No lines:** a `LISTED` event with `LinesPosted=FALSE` appears on the slate with `Lines not yet posted by
  tracked books` (fact state `PENDING`, §10). It is never shown with blank or zero prices.
- **Start time changes:** if `commence_time` changes by ≥ 1 minute, the new value replaces the current one,
  `PriorCommenceAtUTC` and `CommenceChangeCount` update, and a change row is appended. The page shows `Start
  time changed by provider (was <ET>)`. Executability always uses the **current** value via the existing
  kickoff gate (`_kickoff_gate_failure`, `app.py:33407`, strictly `kickoff > now`). A moved-to-later game whose
  original time has passed is executable again only if a fresh quote exists.
- **Postponed/cancelled:** the provider gives no explicit flag [I]. The observable signals are a commence
  change, `NOT_LISTED`, or `NO_RESULT`. Each is shown as observed. None is relabelled `Postponed`, `Cancelled`
  or `Void`, because we cannot see book settlement rules.

### 5.5 Duplicate events

Two different `EventId`s with the same unordered `{HomeTeamId, AwayTeamId}` pair (both `RESOLVED`) whose
commence instants are within **12 hours** of each other form one duplicate group.

- Every member gets the same `DuplicateGroupId` = sha256 of the sorted member ids (first 16 hex).
- All members are **non-executable** (`DUPLICATE_EVENT_SUSPECT`) and excluded from grading aggregates and
  streaks until the group dissolves (one member `NOT_LISTED` while the other gets `COMPLETED`).
- The receipt counts groups. The page shows both rows with `Possible duplicate listing`.
- A genuine same-pair rematch days apart (MTE, conference tournament) is outside the 12h window, so it is
  two normal events keyed by `EventId`.

Unresolved-identity events cannot be grouped (no `TeamId`); they are already non-executable (§3.4).

---

## 6. Full-game lines contract

### 6.1 Request

`GET /v4/sports/basketball_ncaab/odds` with `regions=us`, `markets=h2h,spreads,totals`,
`oddsFormat=american`, `dateFormat=iso`, `commenceTimeFrom=<now UTC>`, `commenceTimeTo=<now + 72h UTC>`.
No `bookmakers` parameter, so every us-region book is returned [I]. Expected cost = markets × regions = 3
credits (`services/odds_quota.odds_credit_cost`, `:26-36` [V formula; provider charge to be verified]).
Preceded by the free `/events` call for the same window (§5).

### 6.2 `data/odds/NCAAMB_GameLines.csv` — long form, current state

One row per **(EventId, BookKey, MarketKey, Side)**.

| Column | Type | Rule |
|---|---|---|
| `Competition` | enum | `NCAAMB` |
| `EventId` | str | FK to `NCAAMB_Events.csv` |
| `EventCommenceAtUTC` | ISO-Z | copied from the event, every row |
| `EventDateET` | `YYYY-MM-DD` | derived (§9.2) |
| `BookKey` / `BookTitle` | str | from the registry, `LICENSED_US` only |
| `MarketKey` | enum | `h2h` · `spreads` · `totals` |
| `Period` | enum | `FG` (release 1 only value) |
| `Side` | enum | `HOME` · `AWAY` (h2h, spreads) · `OVER` · `UNDER` (totals) |
| `SelectionProvider` | str | the provider outcome `name` verbatim |
| `TeamId` | str or blank | for `HOME`/`AWAY`, the resolved team; blank for totals |
| `Point` | float or blank | that side's own point: spreads signed from **this side's** perspective; totals the total; blank for h2h |
| `PriceAmerican` | int | finite, `\|price\| ≥ 100` |
| `SourceUpdatedAtUTC` | ISO-Z or blank | market `last_update`, else bookmaker `last_update`; blank if neither |
| `SourceTimeLevel` | enum | `MARKET` · `BOOKMAKER` · `NONE` |
| `FetchedAtUTC` | ISO-Z | the run's single fetch instant |
| `FetchRunId` | str | 32-hex |
| `MarketIntegrity` | enum | `COMPLETE` · `ONE_SIDED` · `INCONSISTENT` (§6.4) |

There is **no** `LastUpdated`, `Spread`, `SpreadOdds`, `HomeML`/`AwayML` or other wide-format column.

### 6.3 Side assignment by construction (fixes the "one team's price on the other side" class)

The writer emits **one row per provider outcome**. It never reads "the first outcome" and never negates a
point to re-express another side.

- h2h / spreads: `Side = HOME` iff `outcome.name == event.home_team` (exact string equality after
  `strip()` only); `AWAY` iff `== event.away_team`; otherwise the outcome is dropped as `OUTCOME_UNMATCHED`
  (counted, alerting if > 0). If home and away strings are equal, the event is rejected (`SELF_MATCH`).
- totals: `Side = OVER` iff `outcome.name.casefold() == 'over'`; `UNDER` iff `'under'`; else
  `OUTCOME_UNMATCHED`.
- `Point` and `PriceAmerican` are copied from **the same outcome object**. No field on one row ever comes from
  another outcome.

Contrast with today's shared writer: `parse_event_markets` (`fetch_game_lines.py:200-212`) keeps the first
spread outcome, negates an away point to home perspective, and stores that outcome's price as `SpreadOdds`
(possibly the away price under a home-perspective spread), and never stores the other side's price [V].

### 6.4 Validation (whole-run rules, then market rules, then row drops)

**Whole-run reject** (nothing published; files byte-identical; receipt `VALIDATION_FAILED` or
`PROVIDER_ERROR`):

- R1 missing required column
- R2 blank `EventId`, or non-canonical/zone-less commence
- R3 one `EventId` with conflicting commence or teams within the same response
- R4 duplicate `(EventId, BookKey, MarketKey, Side)` within the response
- R5 a non-finite point/price
- R6 provider HTTP error or unparseable body
- R7 zero usable events while `/events` lists ≥ 1 future event (`PROVIDER_ZERO_EVENTS_EVENTS_LISTED`)
- R8 output path not in the allow-list (§15)
- R9 `SourceUpdatedAtUTC` more than 5 minutes after `FetchedAtUTC` on any row (`SOURCE_TIME_AFTER_FETCH`)

**Market integrity** (per event × book × market; rows kept, flagged):

- `COMPLETE`: both sides present; spreads `Point_HOME == -Point_AWAY`; totals `Point_OVER == Point_UNDER > 0`;
  h2h both prices valid.
- `ONE_SIDED`: exactly one side present. That row is stored as a fact but is **non-executable**
  (`ONE_SIDED_MARKET`).
- `INCONSISTENT`: both sides present but points disagree. Both rows are stored and **both** are
  non-executable (`MARKET_INCONSISTENT`). Counted in the receipt.

**Row drops** (counted in the receipt):

- D1 blank `BookKey`
- D2 book not `LICENSED_US`
- D3 started (`commence ≤ FetchedAtUTC`)
- D4 invalid price (`|price| < 100` or non-integer American)
- D5 `OUTCOME_UNMATCHED`

### 6.5 Publish rules

- **Vanished event:** an event in the prior file that is still future and still `LISTED` but has zero rows in
  the new run publishes as `LinesPosted=FALSE` (the book pulled the market). This is a fact, not an error;
  the receipt lists it as `MARKET_WITHDRAWN`. (Unlike NBA's `EVENT_VANISHED` reject, the NCAAMB current file
  is per-row state with an explicit events table, so a withdrawal never silently disappears.)
- **Collapse guard:** if the new run has < 50% of the prior run's **future** events with lines, and the free
  `/events` count did not fall similarly, reject (`COVERAGE_COLLAPSE`). An explicit `--allow-collapse` exists
  only for a governed manual run and is recorded in the receipt.
- **Atomic set:** `NCAAMB_Events.csv`, `NCAAMB_GameLines.csv` and the snapshot partition append are staged and
  checked, then replaced (`atomic_write_csv_set` pattern). A failure leaves every file byte-identical.

### 6.6 No medians, no consensus

No NCAAMB module computes a mean, median or mode of `PriceAmerican` or `Point` across books. "Best" displays
are selections from real rows (§11.4). Enforced by `qc_ncaamb_no_consensus.py` (§16).

---

## 7. Forward-only market snapshots (decision 7)

### 7.1 Storage

**`data/tracking/ncaamb_snapshots/<EventDateET>.csv`**, partitioned by the event's Eastern date (bounds file
size: ~80 events × ~8 books × 6 selections × ~12 captures ≈ 46k rows per busy date [I estimate]).

Columns = every §6.2 column + `SnapshotAtUTC` (= the run's `FetchedAtUTC`) + `SnapshotSeq` (int, per
`(EventId, BookKey, MarketKey, Side)`, 1-based, in capture order).

- Append-only. Rows are never rewritten. Dedupe key = `(FetchRunId, EventId, BookKey, MarketKey, Side)`; a
  retried append of the same run is a no-op.
- Every published run appends **all** its rows, including unchanged quotes. The snapshot is proof the quote
  was observed at that instant, and that matters for the pre-tip capture (§7.3).

### 7.2 Cadence

Every 4 hours (§13.4), plus optional pre-tip captures if the owner approves option O2 (§14.3).

### 7.3 Open and pre-tip, labelled honestly

| Term | Definition | Customer label |
|---|---|---|
| First captured | the `SnapshotSeq=1` row per `(EventId, BookKey, MarketKey, Side)` | `First captured by BK <ET>` — **never** "open" / "opening line" |
| Latest captured | the max `SnapshotSeq` row | `Latest captured <ET>` |
| Last pre-tip captured | max `SnapshotAtUTC` with `SnapshotAtUTC < EventCommenceAtUTC` **and** `SourceUpdatedAtUTC < EventCommenceAtUTC` | `Last BK capture before tip (<N> min before)` — **never** "closing line" |
| Movement | latest − first captured, for the same book and side | `Moved <Δ> since first BK capture (<n> captures)` |

- With 1 capture: `1 capture — no movement read`.
- A point move and a price move are reported separately. A move from `-3.5 -110` to `-4.5 -105` is two facts,
  never one blended number.
- No "sharp", "steam", "reverse line movement" or direction-of-money labels.

### 7.4 Retention

- Current season plus the previous season are kept uncompressed through grading.
- Partitions whose `EventDateET` is ≥ 14 days past are gzip-compressed in place (`.csv.gz`, same columns) by
  the market job. They are never deleted in release 1.
- Budget check: `df /opt/bankrollkings` (CLAUDE.md §2), never `df /`.

---

## 8. Scores and grading (decision 4)

### 8.1 Request

`GET /v4/sports/basketball_ncaab/scores?daysFrom=3&dateFormat=iso`. Expected cost **2** [I — provider
documentation as recalled: 1 without `daysFrom`, 2 with; verified only by Probe B]. `daysFrom=3` (the
provider maximum [I]) lets a missed run self-heal.

There is **no** 60-second poller for NCAAMB. `refresh_live_scores.py` is not extended (its `SPORTS` at
`:72-78` stays as is, and its `_today_str` UTC bug is out of scope here). No live in-game display in
release 1.

### 8.2 `data/scores/NCAAMB_Finals.csv` (one row per `EventId`)

| Column | Type | Rule |
|---|---|---|
| `Competition` | enum | `NCAAMB` |
| `EventId` | str | must exist in `NCAAMB_Events.csv`; otherwise the row is held in the receipt as `SCORE_EVENT_UNKNOWN` |
| `EventCommenceAtUTC` | ISO-Z | from the scores payload; a mismatch with the events table is recorded, not overwritten |
| `ScoreState` | enum | `FINAL` (`completed=true`) · `IN_PROGRESS` (`completed=false` and scores present) · `NOT_STARTED` |
| `HomeScore` / `AwayScore` | int or blank | non-negative integers; blank unless `FINAL` |
| `ScoreMapping` | enum | `EXACT` (both score names equal the event's provider home/away strings) · `FAILED` |
| `SourceUpdatedAtUTC` | ISO-Z or blank | payload `last_update` |
| `FetchedAtUTC` / `FetchRunId` | ISO-Z / str | |

- Only `FINAL` rows with `ScoreMapping=EXACT` are gradeable.
- `FINAL` with equal scores → `ANOMALY_TIED_FINAL`: not graded, alerting.
- A `FINAL` row that later changes score → change row in `NCAAMB_EventChanges.csv`, re-grade, and the receipt
  flags `SCORE_CORRECTED`.

### 8.3 `data/tracking/NCAAMB_Results.csv` (one row per graded `(EventId, BookKey, MarketKey, Side)`)

Grading is **only** against the last pre-tip captured quote (§7.3). Never against a post-tip quote, never
against a reconstructed or averaged quote.

| Column | Type |
|---|---|
| `EventId`, `BookKey`, `MarketKey`, `Period`, `Side`, `TeamId` | as §6.2 |
| `GradedPoint` / `GradedPrice` | float / int (from the pre-tip snapshot row) |
| `GradedSnapshotAtUTC` | ISO-Z |
| `GradedSourceUpdatedAtUTC` | ISO-Z |
| `CaptureLeadMinutes` | int, `commence − GradedSnapshotAtUTC` |
| `HomeScore` / `AwayScore` | int |
| `Result` | enum (below) |
| `GradeReason` | str |
| `GradedAtUTC` / `GradeRunId` | ISO-Z / str |

| `Result` | Rule |
|---|---|
| `WIN` / `LOSS` | spreads: `(side score − opp score) + GradedPoint` > 0 / < 0. totals: `home + away` vs `GradedPoint` per side. h2h: higher score wins |
| `PUSH` | spreads margin + point == 0; totals sum == point. h2h has no push |
| `NO_PRETIP_CAPTURE` | no qualifying pre-tip snapshot. Not graded, never reconstructed |
| `MARKET_NOT_GRADEABLE` | the pre-tip row's `MarketIntegrity` ≠ `COMPLETE` |
| `NO_RESULT` | event `NO_RESULT` / `NOT_LISTED` with no final. We do not say "void" (book settlement unknown) |
| `PENDING` | not yet `FINAL` and `< commence + 48h` |
| `EXCLUDED_IDENTITY` | `IdentityStatus ≠ RESOLVED` or duplicate group. Stored, excluded from aggregates |
| `ANOMALY` | tied final, score mapping failed, or snapshot/commence contradiction |

Float comparisons use the provider's half-point grid: points are compared after `round(x * 2) / 2`, and a
point off that grid fails as `ANOMALY`.

**Team ATS/OU, no default book.** Per event and market, the per-book results combine into one of:
`ALL_BOOKS_WIN`, `ALL_BOOKS_LOSS`, `ALL_BOOKS_PUSH`, `MIXED` (books disagree because their numbers
differed). Streaks and records count only unanimous outcomes. `MIXED` breaks a streak and is shown as
`Mixed across books`. This avoids choosing a reference book (decision 3) and avoids a consensus line.

---

## 9. Time, game date, home/away, neutral site

### 9.1 Parsing

- One strict parser, `parse_utc_strict(value) -> aware UTC datetime | None`. It accepts only ISO-8601 with
  `Z` or an explicit offset; a zone-less value returns `None`. It is the same semantics as
  `_canonical_kickoff_utc` (`app.py:33382`) [V]; the services-level helper (Q-A branch
  `parse_feed_timestamp_utc`, or a new one in `services/timeutils.py`) must be shared, not copied.
- Written timestamps are always `YYYY-MM-DDTHH:MM:SSZ`.
- No NCAAMB code calls `datetime.now()` without `timezone.utc`, `pd.Timestamp.now()` without `tz`,
  `.astimezone()` with no argument, or `time.localtime`. QC-enforced (§16).

### 9.2 Game date (Eastern)

- `EventDateET = to_eastern_date_str(EventCommenceAtUTC)` (`services/timeutils.py:46` [V]).
- "Today" = Eastern service date from aware UTC now converted with `ZoneInfo('America/New_York')`. The
  existing `sports_today_ts` (`app.py:25720`) falls back to the ambient zone when tzdata is missing [V]; for
  NCAAMB that fallback must **fail closed** (`SERVICE_DATE_UNAVAILABLE`, empty slate with that message), never
  use the process zone.
- Late tips are the common CBB case: a 22:00 ET tip is 03:00Z the next UTC day and belongs to the earlier ET
  date.
- Every displayed time reads `… ET` explicitly.

### 9.3 Home/away and neutral site (decision 6)

- `HomeTeamProvider` / `AwayTeamProvider` are **provider-nominal**. Labels say `Home (as listed)` /
  `Away (as listed)`.
- `NeutralSite` is `UNKNOWN` for every event in release 1, because no authoritative venue source exists. No
  manual list, no inference from MTE names, no guessing from dates.
- Consequences:
  - No home/road/neutral split is computed or shown. The matchup page shows `Home/road splits unavailable —
    venue not verified`.
  - Overall records and margins do not depend on venue and are shown (§11.3).
  - The "home" label never feeds any evidence item.
- A future authoritative source sets `NeutralSite` + `NeutralSiteSource`. QC already asserts that only
  `FALSE` rows can ever contribute to home/road splits, so enabling a source needs no grading change.

---

## 10. Honest fact states (decision 11 + shared stale contract)

One function, `ncaamb_fact_state(component, row_or_none, now_utc)`, returns one state with a reason code.
Fact status is never mixed with research status (doctrine §11).

| State | Market quote rule | Customer text |
|---|---|---|
| `AVAILABLE` | `SourceUpdatedAtUTC` parses strictly and `now − source ≤ 6h` (`LIVE_MARKET_MAX_AGE_HOURS`, `services/freshness_contract.py:35` [V]); source up to 5 min in the future is tolerated as age 0 (`QUOTE_CLOCK_SKEW_TOLERANCE_SECONDS`, `app.py`) | `Updated <ET> (book time)` |
| `STALE` | `now − source > 6h` | `Stale — book time <ET>, <h>h ago`. Shown as context, non-executable |
| `UNAVAILABLE` | no row, or `SourceUpdatedAtUTC` blank/zone-less/unparseable, or > 5 min in the future, or the component has no licensed source | `Update time not recorded` / `Unavailable — <reason>` |
| `PENDING` | event listed, no licensed book quote yet; or score not yet final | `Lines not yet posted by tracked books` / `Final score pending` |

Rules:

- **`FetchedAtUTC` never substitutes for `SourceUpdatedAtUTC`** (frozen direction). It is shown separately as
  `Checked by BK <ET>`.
- A missing component is never rendered as `0`, `0–0`, `—` without a reason, or a blank cell. QC renders
  pages with empty data and asserts the reason text.
- **Permanently unavailable components** in release 1, always listed with their reason:
  - `Injuries/availability: Unavailable — no licensed source`
  - `Venue: Not verified`
  - `Pace/efficiency: Not licensed`
  - `Player props: Not offered for NCAAB`
  - `First-half markets: Not tracked yet`
- Open measurement question (Q3): whether provider `last_update` refreshes when a quote is re-observed or only
  when it changes. If only on change, stable early lines read `STALE` while still offered. The window is
  **not** loosened to compensate (owner 2026-11-01 cadence decision); the probe measures the age distribution
  first.

---

## 11. Pages

Routes replace the shells after PRE-2: `/sports/ncaamb` (slate) and `/sports/ncaamb/game/<event_id>`
(matchup). `<event_id>` must match `^[A-Za-z0-9]{8,64}$` and exist in `NCAAMB_Events.csv`; otherwise 404.
Access: existing binary gate (`free`/`all_access`, CLAUDE.md §11) — open question Q9 on which tier sees the
slate.

### 11.1 Slate — `/sports/ncaamb`

- **Scope:** `EventDateET` ∈ {today ET, tomorrow ET} (tabs), `ListingStatus ∈ {LISTED, COMPLETED}`, plus a
  separately labelled `Earlier today — started` group (non-executable) so tipped games do not vanish.
- **Ordering:** `EventCommenceAtUTC` ascending, tie-break `EventId` ascending. **No other sort exists**: no
  sort by movement, book count, price, streak or anything evaluative. No "featured" game.
- **Filters (neutral only):** date tab; `Show games without posted lines` (default on); conference filter only
  once `Conference` is populated for both teams (else hidden, not empty).

Per-game fields:

| Field | Source | Empty behavior |
|---|---|---|
| Tip time `<h:mm a> ET` | `EventCommenceAtUTC` | never empty (strict parse required to list) |
| Away @ Home (as listed) | team `DisplayName`, else provider string + `Team identity unverified` chip | — |
| Start-time-changed chip | `CommenceChangeCount > 0` | hidden |
| Spread / Total / Moneyline cells | per side: `<n> books` and the **range** of offered points among `AVAILABLE` quotes (e.g. `-3.5 to -4.5`); moneyline shows the price range. No single "slate number" is chosen (§11.4) | `Lines not yet posted` / `Stale` |
| Book count | distinct `LICENSED_US` books with an `AVAILABLE` quote for that market | `0 books with a current quote` |
| Single-book flag | `BookCount == 1` | hidden |
| Updated | newest `SourceUpdatedAtUTC` among that game's quotes, ET, plus fact-state chip | `Update time not recorded` |
| Status chip | `ListingStatus` / `ScoreState` / duplicate / identity | — |

No prices are averaged into a cell. The slate cell shows the point **range** and book count; per-book prices
live on the matchup page and in the expandable book grid.

**Mobile (< 760 px, existing drawer shell):** one card per game in time order: tip ET · teams · status chip ·
spread range + book count · total range + book count · updated-ago · `Open matchup`. The book grid is a
collapsed `<n> books` chip that expands to a horizontally scrollable table (book · side · point · price ·
book time). No horizontal page scroll.

**Desktop:** a table with sticky header in the same order and columns, and an expandable per-game book grid
row. No side drawer in release 1 (keeps one code path).

### 11.2 Matchup — `/sports/ncaamb/game/<event_id>`

Sections in this fixed order (doctrine §11 layering: Market Facts → Analytical Context → Research Status):

1. **Header:** teams (as listed), tip ET, `EventDateET`, listing/score status, `Venue: Not verified`,
   identity chip, duplicate chip.
2. **Market facts:** one table per market, rows = book × side: point, price, book time (ET), fact state,
   `MarketIntegrity` chip. Books in registry title order (alphabetical); **not** sorted by price.
3. **Movement:** per book and side: first BK capture → latest BK capture, number of captures, last pre-tip
   capture once tipped (§7.3 labels).
4. **Best available (per side, per point):** §11.4.
5. **Team context (own licensed finals only):** §11.3.
6. **Evidence panel:** §11.5.
7. **Unavailable components:** the fixed list from §10, always shown.
8. **Save / track:** §11.6.

Mobile stacks the same order. Desktop uses two columns: market facts + movement on the left, context +
evidence on the right. Order on mobile is the order above.

### 11.3 Team context (decision 5: facts from our licensed finals only)

Shown only for `RESOLVED` teams, computed from `NCAAMB_Finals.csv` rows with `ScoreState=FINAL`,
`ScoreMapping=EXACT`, not in a duplicate group:

- `BK-captured finals since <first capture date ET>: n games` — never "season record" unless coverage is
  proven complete (it is not, in release 1).
- W–L in captured games; last 5 / last 10 results with dates, opponent and margin; average margin with n.
- Rest days before this game = days since the team's previous captured final (ET dates), labelled `since
  last BK-captured game`, because a game we did not capture would shorten it.
- ATS / O-U record and current streak from §8.3 unanimous outcomes, with n, window and
  `MIXED` count, labelled **`Context, not an edge — streaks are priced`** (CLAUDE.md §10).
- n < 3: the module shows `Too few captured games (n=<n>)`, with no rates.

No pace, efficiency, SOS, rankings, ratings, projections or simulated lines.

### 11.4 Best available (no consensus, no default book)

For each market side and each distinct point offered by `AVAILABLE` books: the highest `PriceAmerican` at
that point, with the book(s) offering it and their book times. Points are never merged; a `-3.5` and a `-4`
are separate rows. There is no "best line" across different points and no combined number. Ties list every
tied book.

### 11.5 Evidence panel — Supporting / Contradictory / Missing

The panel is relative to a **user-chosen selection** (e.g. Away +4.5). Until the user chooses one it shows
only the Missing column. Classification uses frozen, deterministic rules (declared in
`services/ncaamb_evidence.py`, versioned `ncaamb_evidence_v1`, mirroring `services/nfl_sgp.py`'s approach):

| Fact type | Supporting (for the selection) | Contradictory | Missing |
|---|---|---|---|
| Market coverage | ≥ 2 `AVAILABLE` books offer the selection | `SINGLE BOOK` | 0 `AVAILABLE` books |
| Quote state | quote `AVAILABLE` and `COMPLETE` | `STALE`, `ONE_SIDED`, `INCONSISTENT` | `UNAVAILABLE` / `PENDING` |
| Number since first capture (same book) | point moved toward the selection (e.g. +4.5 → +5.5 for the taker) | moved away | 1 capture |
| Recent captured form (n ≥ 5) | selection team's last-5 captured W > L | W < L | n < 5 / identity unverified |
| ATS unanimous streak (n ≥ 3) | — (never "supporting": streaks are priced) | — | shown as context only |
| Injuries | — | — | always `Unavailable — no licensed source` |
| Venue | — | — | always `Not verified` |
| Pace/efficiency | — | — | always `Not licensed` |

- The panel header shows **counts by type** (e.g. `Supporting: 1 market, 1 form · Contradictory: 1 market ·
  Missing: 4`). There is no net score, no weighting, no colour scale implying a verdict, no ranking across
  games.
- Streak items carry **`Context, not an edge`** and are listed in their own row, never counted as supporting.
- Research status for every item is **Baseline → "Context, not an edge"** in release 1. No item is Qualified.

### 11.6 Save / track handoff (no Green Light authority)

- **Never fed to Green Light, Daily Card, Menu, Featured Parlay or any proposer.** NCAAMB legs appear only when
  the user selects them. The leg carries `authority_source = 'USER_SELECTED'`. QC asserts no proposer imports an
  NCAAMB loader.
- **Executable** only when `_leg_quote_failures` (`app.py:33434`) returns `[]` — complete single-book quote
  (real `LICENSED_US` book, American price, event/market/selection identity, line for spreads/totals, source
  time, CLOCK-A ≤ 6h) and kickoff strictly after server now — **plus** NCAAMB-specific reasons evaluated
  first: `TEAM_IDENTITY_UNRESOLVED`, `DUPLICATE_EVENT_SUSPECT`, `EVENT_NOT_LISTED`, `ONE_SIDED_MARKET`,
  `MARKET_INCONSISTENT`, `EVENT_TEAMS_CHANGED`.
- **Leg dict** built server-side from one `NCAAMB_GameLines.csv` row: `sport='NCAAMB'`, `event_id`,
  `kickoff_utc=EventCommenceAtUTC`, `quote={book, price, line, event, market, selection, updated_utc}`,
  `line`, `price`.
  - h2h has no line. The existing contract requires a line (`MISSING_LINE`) [V], so **h2h legs are
    non-executable in release 1** unless the shared contract is amended to accept a declared no-line market
    (open question Q8). They remain viewable.
- **Ticket boundary:** the existing 2–8 range (`TICKET_SUBMIT_MIN/MAX_LEGS`, `app.py:34769-34770`), the shared
  editor's 5-leg construction cap, and quote-change atomicity (`docs/ticket_submission_contract.md` §2: any
  book/line/price/event change → whole-ticket 409, confirm-and-resubmit) apply unchanged. The server
  re-resolves the current NCAAMB quote by `(EventId, BookKey, MarketKey, Side)`. A new sport-scoped resolver,
  `_ncaamb_current_quote`, is registered with the boundary; it never accepts the client's price.
  - **Implementation check (not verified here):** whether the boundary's current-quote resolution is
    sport-pluggable today. If it is NFL-specific, the plug-in point is a prerequisite change reviewed on its
    own.
- **Bet Tracker:** `services/bet_tracker.VALID_SPORTS` (`:16`) lacks NCAAMB [V], so an NCAAMB bet is filed
  under `Other` today. Add `'NCAAMB'` (additive). `book` and `odds` come from the executable leg; CLV uses the
  user-entered `closing_odds` (existing field). An optional prefill from the last pre-tip BK capture is labelled
  `BK pre-tip capture (<N> min before tip)`, never "closing line".
- **Context-only legs** (stale, unresolved, h2h under the current contract) show the facts, no payout, no
  implied probability, no ticket action, matching the existing context-only contract.

---

## 12. `sport_registry` entry (decision 8)

### 12.1 Schema change (additive)

```python
@dataclass(frozen=True)
class SportSpec:
    ...existing fields (loader fields become `str | None`)...
    scope: str = 'full'                      # 'full' | 'games_only'
    competition: str | None = None           # 'NCAAMB' | 'NCAAWB' for college hoops; identity namespace
    events_loader: str | None = None         # games_only: load_ncaamb_events
    game_lines_loader: str | None = None     # games_only: load_ncaamb_game_lines
    finals_loader: str | None = None         # games_only: load_ncaamb_finals
    results_loader: str | None = None        # games_only: load_ncaamb_results
    disabled_components: frozenset = frozenset()   # declared-off: {'props','injuries','simulations','gamelogs','efficiency'}

def prop_sports() -> list[SportSpec]:        # live AND scope == 'full'
def games_only_sports() -> list[SportSpec]:  # live AND scope == 'games_only'
```

### 12.2 NCAAMB entry (release 1)

```python
'NCAAMB': SportSpec(
    code='NCAAMB', key='ncaamb', label="Men's College Hoops",
    scope='games_only', competition='NCAAMB',
    props_loader=None, gamelog_loader=None, grading_gamelog_loader=None,
    schedule_loader='load_ncaamb_events', odds_loader='load_ncaamb_game_lines',
    events_loader='load_ncaamb_events', game_lines_loader='load_ncaamb_game_lines',
    finals_loader='load_ncaamb_finals', results_loader='load_ncaamb_results',
    stat_column_map=None, identity_ok=False,   # no prop stats exist; not an identity mapping
    min_market_prob=None, min_lean_gap=None,
    requires_play_verdict=False,               # no verdict concept; no prop archiving
    disabled_components=frozenset({'props', 'injuries', 'simulations', 'gamelogs', 'efficiency'}),
    qc_prefix='ncaamb', calibrator=None,
    live=False,                                # flipped to True only at release (§19 step 9)
    notes='Games-only: lines, schedule, scores, grading. Props/injuries/simulations disabled by owner decision 2026-11-04.',
),
```

- `identity_ok=False` with `stat_column_map=None` would fail `_check_stat_map` today
  (`qc_sport_registry.py:54-59`) [V]. For `scope='games_only'` the QC instead **requires** both to be exactly
  that pair (and `requires_play_verdict=False`), because there are no prop stats to map. Declaring a stat map
  or a props loader on a games-only sport is a failure, which prevents a half-wired props path.
- `NCAAWB` keeps its current not-live shell entry until its own release, then gets the same shape with
  `competition='NCAAWB'`.
- Before flipping `live=True`, audit every consumer: today the only app use is `sport_registry.stat_map_name`
  (`app.py:12862`) [V]. Any future iteration over live sports for props/archiving must use `prop_sports()`.

### 12.3 `qc_sport_registry.py` changes (designed)

- `_check_loaders`: for `games_only`, require `events_loader`, `game_lines_loader`, `finals_loader`,
  `results_loader` to resolve in `app` (fail if live), and require `props_loader`, `gamelog_loader`,
  `grading_gamelog_loader` to be `None` (fail otherwise).
- `_check_stat_map`: `games_only` → require `stat_column_map is None and identity_ok is False`, skip gamelog
  resolution.
- New `_check_scope`: `scope ∈ {'full','games_only'}`; `games_only` ⇒ `competition` set and
  `{'props','injuries','simulations'} ⊆ disabled_components`; `competition` unique across specs.
- Not-live sports stay warnings (unchanged behavior), so landing the schema change cannot turn the scorecard
  red.

---

## 13. Pipeline wiring (designed only — nothing enabled)

### 13.1 Single writer

| Artifact | Only writer |
|---|---|
| `NCAAMB_Events.csv`, `NCAAMB_GameLines.csv`, `ncaamb_snapshots/*`, `NCAAMB_EventChanges.csv`, `ncaamb_identity_unresolved.csv` | `fetch_ncaamb_market.py` |
| `NCAAMB_Finals.csv` | `fetch_ncaamb_scores.py` |
| `NCAAMB_Results.csv` | `grade_ncaamb_results.py` |

- QC `qc_ncaamb_single_writer.py` greps the repo for any other write to these paths. It also asserts that
  `fetch_game_lines.py`, `refresh_live_scores.py` and `fetch_oddsapi_historical_game_lines.py` contain no
  `basketball_ncaab` output mapping.
- Output paths are module constants built from `BASE_DIR` (or `BK_RUNTIME_DIR` where §15 says so). There is
  **no** `--output` override and **no** fallback. An unknown sport or path exits 2 before any request. This
  is the NCAAMB form of Safeguard A.

### 13.2 Locks

- `$BK_RUNTIME_DIR/locks/ncaamb_market.lock` serializes the market and scores stages, so finals and grading
  never read a half-published run. It is taken **before any request**, including the free `/events` call.
- It uses `services/process_lock` with the v4 enforcement (contained under the runtime root, no symlink,
  `0700`/`0600`, kernel release on exit).
- A separate no-wait orchestrator run lock, `ncaamb_market_refresh.lock`, rejects an overlapping orchestrator
  run as `SKIPPED_LOCKED` (exit 75).
- States reuse the NBA lines state machine names: `LOCK_UNAVAILABLE` 76, `SKIPPED_LOCKED` 75, `UPDATED`,
  `REUSED_FRESH`, `PROVIDER_ERROR`, `VALIDATION_FAILED`, plus `SKIP_BUDGET` and `SKIP_OFF_SEASON`.

### 13.3 Receipts (NBA v6 token contract, PRE-4)

- Every stage invocation has a 32-lowercase-hex run token: the caller's `BK_NCAAMB_STAGE_RUN_ID`, or one the
  stage generates when run standalone. An unsafe env token is rejected before any lock or request.
- Each invocation writes its **own** receipt `<runtime>/receipts/ncaamb_stage_runs/<token>.<market|scores|grade>.json`
  on every exit path, including skips: temp in the same dir + fsync + `os.replace`, `0600`, token reuse
  refused, retention 14 days / 2,000 files, never removing the current run.
- The parent classifies a stage **only** from its own token's receipt: missing → `RUN_RECEIPT_MISSING`,
  foreign or absent token → `RUN_RECEIPT_MISMATCH` (both alerting). There is **no mtime fallback** and no
  shared "last receipt" file is ever authority.
- Market receipt body (`bk.ncaamb.market_receipt.v1`):
  - `token`, `stage`, `started_at_utc`, `finished_at_utc`, `outcome`, `exit_code`
  - `quota`: per call `{endpoint_family, x_requests_last, x_requests_used, x_requests_remaining,
    expected_cost}`, `sum_last`, `cost_ok`
  - `budget`: `{month_utc, mtd_before, mtd_after, cap, reserve_class}`
  - `events`: `{listed, priced, new, not_listed, commence_changed, duplicates}`
  - `identity`: §3.5
  - `books`: `{published: {key: quotes}, excluded: {key: {status, quotes}}}`
  - `rows`: `{published, dropped: {D1..D5}, one_sided, inconsistent}`
  - `freshness`: `{source_age_p50_min, p90, max, share_over_6h, source_time_level_counts}`
  - `outputs`: `{path: {sha256_before, sha256_after}}`
- Ledger lines also go to the existing `data/tracking/odds_quota_ledger.jsonl` (`services/odds_quota.py:23`)
  with `sport=basketball_ncaab` and `endpoint_family` ∈ `ncaamb_events`, `ncaamb_odds_bulk`,
  `ncaamb_scores`, `ncaamb_odds_pretip`.

### 13.4 Timer and run_daily (designed; units uninstalled; not enabled)

**`ops/bk-ncaamb-market.{service,timer}`:**

- `OnCalendar=*-*-* 00/4:25:00` UTC — 00:25, 04:25, 08:25, 12:25, 16:25, 20:25. That offsets it from the
  proposed NBA `:15`, from bk-linemove, and from bk-daily at 13:00.
- `Persistent=false`, `TimeoutStartSec=240`, `User=ubuntu`.
- `ExecStart` runs `refresh_ncaamb_market.py`, which:
  1. Budget preflight (§14.4). Over cap → `SKIP_BUDGET` (alerting), zero requests.
  2. Season gate (F2v2 `season_state`, if merged; else a declared NCAAMB window, verified dates, UNKNOWN
     fails open). Off-season → `SKIP_OFF_SEASON`, zero requests. This also closes the 1.5k class of defect for
     this sport.
  3. Market stage.
  4. Scores stage.
  5. Grade stage (no provider call).
  6. One orchestrator receipt.
- Scores run every 4h with the market stage (same timer, same lock). There is no separate scores timer.

**run_daily (CLAUDE.md §7 rule):** one step, `NCAAMB market (ensure)`, calls the same orchestrator with
`--allow-reuse`.

- If the last market receipt is `UPDATED`, < 90 min old, and its output hashes match disk, the step is
  `REUSED_FRESH` at zero credits.
- Otherwise it runs a full cycle. This keeps NCAAMB alive on prod even if the timer is not installed, and
  never double-spends inside a window.
- The step is added to `run_daily.py` only at release (§19 step 9), never before the probe.

**Monitoring:** add an `NCAAMB` family to `qc_odds_feed.py` Clock-B and to `report_feed_availability.py`. Note:
`qc_odds_feed.py` makes a live call (ledger 1.5p), so it is never run as an offline QC.

### 13.5 Women's

A parallel `bk-ncaawb-market.*` at `:35` with its own lock/receipt family and budget line, only after its own
decision.

---

## 14. Credit budget and the cost probe

### 14.1 Per-call cost formulas

| Call | Formula | Expected | Basis |
|---|---|---|---|
| `/v4/sports` | free | 0 | `odds_quota.py:26-36` comment [V]; provider docs [I] |
| `/v4/sports/basketball_ncaab/events` | free | 0 | same |
| `/odds` bulk, `markets=h2h,spreads,totals`, `regions=us` | markets × regions | **3** per call, independent of event count | `odds_credit_cost` [V formula]; provider charge [I] |
| same with `regions=us,us2` | 3 × 2 | 6 | [I] |
| `/odds` bulk with zero events in window | ? | 0 or 3 | [I] — measured only if the owner ticks A5 |
| `/scores?daysFrom=3` | flat | **2** | [I] provider docs as recalled; Probe B verifies |
| `/participants` (optional, registry seed) | flat | 1 | [I] |
| per-event `/events/{id}/odds` (1H, team totals) | markets returned × regions per event | — | **not used in release 1** |

### 14.2 Assumptions for the monthly estimate

- Season window used for planning: early November through early April. A "month" = 31 days (worst case).
- Bulk-call cost does not depend on slate size, so the typical Nov–Mar slate (~40 games/day average, 100–160
  on peak Saturdays, audit §2 [I]) changes **row counts and storage**, not credits.
- 6 market runs/day (4h), each = 1 free `/events` + 1 bulk `/odds`.
- 6 scores calls/day (same runs).
- Manual/governed runs: up to 10 full cycles/month (5 credits each).
- No retries inside a run. A failed run is retried by the next tick.

### 14.3 Estimate vs the 7,500 cap

| Configuration | Lines | Scores | Manual | Total / 31-day month | % of 7,500 |
|---|---|---|---|---|---|
| **Base (recommended): 4h, `us` only** | 6 × 3 × 31 = 558 | 6 × 2 × 31 = 372 | 50 | **980** | 13% |
| O1: + `us2` region | 1,116 | 372 | 80 | 1,568 | 21% |
| O2: base + pre-tip hourly captures 12:00–23:00 ET (12 calls/day, narrow `commenceTimeTo=now+75m`) | 558 + 1,116 | 372 | 50 | 2,096 | 28% |
| O1 + O2 | 1,116 + 2,232 | 372 | 80 | 3,800 | 51% |

O2 matters because with 4h captures the last pre-tip capture can be up to 4h before tip, which weakens CLV and
grading (§7.3 still labels it honestly). Its cost on an empty window (no games tipping in the next 75 min) is
the A5 unknown; if empty windows cost 0, O2 is cheaper than shown.

### 14.4 Budget guard (enforced in code before every paid call)

- **MTD** = sum of `x-requests-last` over ledger lines with `sport=basketball_ncaab` in the current UTC
  calendar month. This is our policy month, not the provider's reset date.
  - A line whose cost is unprovable (headers missing) counts at its `expected_cost`, flagged
    `ESTIMATED_UPPER_BOUND`. The receipt itself still fails (`cost_ok=false`), as today.
- Thresholds (cap from config `BK_NCAAMB_MONTHLY_CREDIT_CAP`, default 7,500, never inferred):
  - **essential** (4h lines, scores) may proceed while `MTD + expected ≤ 95%` of cap (7,125).
  - **deferrable** (pre-tip O2, manual) only while `≤ 80%` (6,000).
  - Beyond → `SKIP_BUDGET` (alerting), zero requests.
- `--expected-cost` is always passed (3, 2, …). A response whose `x-requests-last` exceeds it fails the run's
  cost receipt (`odds_quota.receipt`) and blocks publish, as today.

### 14.5 The exact cost probe (proposal — NOT executed)

**Purpose:** verify the per-call charges in §14.1, the response shape this contract depends on (market-level
`last_update`, outcome-name equality, `/events` ⊇ `/odds`, book keys) and the real team strings for the alias
review.

**Approval units (decision 4 requires scores to be approved separately):**

| Unit | Calls (in order) | Expected credits |
|---|---|---|
| **Probe A — lines** (owner approval #1) | A1 `GET /v4/sports` · A2 `GET /v4/sports/basketball_ncaab/events?dateFormat=iso&commenceTimeFrom=<T>&commenceTimeTo=<T+72h>` · A3 `GET /v4/sports/basketball_ncaab/odds?regions=us&markets=h2h,spreads,totals&oddsFormat=american&dateFormat=iso&commenceTimeFrom=<T>&commenceTimeTo=<T+72h>` | 0 + 0 + 3 = **3** |
| A4 (optional tick) | same as A3 with `regions=us2` | 3 |
| A5 (optional tick) | same as A3 with `commenceTimeFrom=<T+300d>&commenceTimeTo=<T+301d>` (a window with no events) | 0 or 3 |
| **Probe B — scores** (owner approval #2) | B1 `GET /v4/sports/basketball_ncaab/scores?daysFrom=3&dateFormat=iso` | **2** |
| Probe C — participants (optional, approval #3) | C1 `GET /v4/sports/basketball_ncaab/participants` | 1 |

**Maximum if everything is ticked: 12 credits.** Base A+B = **5**.

**Where and when:**

- Run on the dev box with the dev `ODDS_API_KEY` (no prod access, no SSM).
- Run on a slate day ~14:00–16:00 ET, so tonight + 72h has priced games and B1 has finals from the last 3
  days.
- Not within ±10 min of 00/04/08/12/16/20 UTC (bk-linemove) or 13:00–13:45 UTC (bk-daily), so cumulative
  `x-requests-used` deltas are attributable.
- `T` = probe start, UTC, `…Z`.

**How it runs:** a new one-shot script `probe_ncaab_costs.py` (built and reviewed **before** approval; not
part of this doc's scope). It:

- has hard-coded calls only, `--units A,B[,A4,A5,C]` required, and no other arguments
- imports nothing from `app`
- writes **only** under the probe directory below and appends ledger lines
- passes per-call `expected_cost`
- **stops on the first deviation**: HTTP ≠ 200, missing usage headers, or `x-requests-last` > expected

**Output paths** (all under gitignored `data/tracking/`; nothing under `data/odds`, `data/scores`,
`data/schedules` or `data/reference`):

```
data/tracking/probes/ncaab_cost_probe_<YYYYMMDDTHHMMSSZ>_<token8>/
  receipt.json          schema bk.ncaab_cost_probe.v1
  raw/A1_sports.json    provider bodies (no key; the key exists only in the request URL, never written)
  raw/A2_events.json
  raw/A3_odds_us.json   [raw/A4_odds_us2.json] [raw/A5_odds_empty.json]
  raw/B1_scores.json    [raw/C1_participants.json]
  shape.json
  team_names.csv        distinct provider team strings + counts (alias-review input; never authority)
data/tracking/odds_quota_ledger.jsonl   (+1 line per call; endpoint_family ncaab_probe_<unit>)
```

**`receipt.json` proves cost:**

- Per call: `seq`, `unit`, `endpoint_family` (no URL/key), non-secret params, `http_status`,
  `x_requests_last`, `x_requests_used`, `x_requests_remaining`, `expected_cost`, `response_sha256`,
  `response_bytes`, `event_count`, `verdict`.
- Run level: `used_before = used[1] − last[1]`, `used_after = used[n]`, `delta = used_after − used_before`,
  `sum_last = Σ last`.
- Verdicts:
  - `COST_VERIFIED`: every call has headers, every `last ≤ expected`, and `delta == sum_last` (no other
    consumer between calls).
  - `CONCURRENT_USE_SUSPECTED`: `delta > sum_last`. Per-call `last` values still stand, but this is reported
    and is not a clean pass.
  - `COST_MISMATCH`: some `last > expected` (the probe stopped there).
  - `COST_UNPROVABLE`: headers missing.
- `/v4/sports` and `/events` are verified free only if their `x-requests-last` is `0` (or absent while `used`
  does not advance — reported as `FREE_BY_USED_DELTA`).

**`shape.json` answers the [I] items:**

- `basketball_ncaab` present/active; `basketball_wncaab` present (recorded only)
- Book keys + titles seen, with quote counts (input for the §4 licence review)
- Markets seen per book
- Share of markets with market-level `last_update`, and with bookmaker-level only
- Outcome-name exact-match rate vs `home_team`/`away_team`
- `/events` ids not present in `/odds` (unpriced games) and the reverse
- All `commence_time` values end in `Z`
- `FetchedAt − SourceUpdatedAt` distribution (p50/p90/max, share > 6h) — answers Q3
- Duplicate same-pair events within 12h
- Scores: `completed` counts, score-name exact-match rate, `last_update` presence, `daysFrom` coverage

**Acceptance of the probe:** the owner reviews `receipt.json` + `shape.json`. §14.3 is then recomputed with the
measured costs before any timer proposal.

---

## 15. Data contracts summary (types and paths)

| Path | Tracked? | Writer | Shape |
|---|---|---|---|
| `data/reference/ncaa_schools.csv` | **yes** | reviewed commit | §3.1 |
| `data/reference/ncaamb_teams.csv` | **yes** | reviewed commit | §3.1 |
| `data/reference/ncaamb_team_aliases.csv` | **yes** | reviewed commit | §3.1 |
| `data/reference/sportsbooks.csv` | **yes** | reviewed commit | §4 |
| `data/odds/NCAAMB_Events.csv` | no (gitignored) | `fetch_ncaamb_market.py` | §5.2 |
| `data/odds/NCAAMB_GameLines.csv` | no | `fetch_ncaamb_market.py` | §6.2 |
| `data/tracking/ncaamb_snapshots/<YYYY-MM-DD>.csv[.gz]` | no | `fetch_ncaamb_market.py` | §7.1 |
| `data/tracking/NCAAMB_EventChanges.csv` | no | `fetch_ncaamb_market.py` | §5.2 |
| `data/tracking/ncaamb_identity_unresolved.csv` | no | `fetch_ncaamb_market.py` | §3.5 |
| `data/scores/NCAAMB_Finals.csv` | no | `fetch_ncaamb_scores.py` | §8.2 |
| `data/tracking/NCAAMB_Results.csv` | no | `grade_ncaamb_results.py` | §8.3 |
| `<runtime>/receipts/ncaamb_stage_runs/<token>.<stage>.json` | no | each stage | §13.3 |
| `<runtime>/locks/ncaamb_market.lock`, `ncaamb_market_refresh.lock` | no | locks | §13.2 |
| `data/tracking/odds_quota_ledger.jsonl` | no | append (existing) | `odds_quota.py` |

**Git status of these paths [V at `17b5e69`]:** `.gitignore:67` ignores `*.csv` everywhere, and `data/odds/` /
`data/tracking/` are ignored as directories, so every runtime path above is already untracked. The four
reference registries must be tracked. The proposed mechanism is an explicit, narrow `.gitignore` negation in a
reviewed commit (`!data/reference/ncaa_schools.csv`, `!data/reference/ncaamb_teams.csv`,
`!data/reference/ncaamb_team_aliases.csv`, `!data/reference/sportsbooks.csv`), placed after line 67 — never
`git add -f`, and never a broader pattern. Some CSVs are tracked today without a negation (e.g.
`data/context/MLB_BallparkFactors.csv`), which is the force-add pattern this avoids. Also add `data/scores/`
as an explicit ignored directory for clarity (Q12).

**Encoding:** UTF-8, comma-separated, header row, `\n`. Enums are uppercase ASCII. Blank = empty string,
never `NaN`, `None`, `0` or `-`. Booleans are `TRUE`/`FALSE`.

---

## 16. Acceptance tests (offline; `qc_offline.py` socket block; no provider calls)

Every QC uses synthetic fixtures under a `qc_*` temp dir, runs under process `TZ=UTC`,
`TZ=America/New_York` and `TZ=America/Los_Angeles` (timestamp inventory direction), and is mutation-checked
(at least one deliberate defect per rule must fail it).

| QC | Asserts (adversarial cases included) |
|---|---|
| `qc_ncaamb_identity.py` | Every §3.3 pair resolves to distinct ids; UConn + Connecticut → same id; bare `Miami`/`USC`/`Saint Mary's`/`St. Mary's` → `AMBIGUOUS` even with an alias row present (and the alias-file check FAILs that row); `Miami (OH) RedHawks` vs `Miami OH RedHawks` are different keys; curly apostrophe `St. John’s Red Storm` == straight; `Saint John's` (D-III) → `UNMATCHED`; prefix/substring inputs (`Texas A&M` vs `Texas A&M-CC`) never cross-match; duplicate `NormalizedKey` → FAIL; unreviewed alias not loaded; `competition='NCAAMB'` never returns `ncaaw:`; `SELF_MATCH` event → non-executable + alerting; unresolved names land in the runtime list with counts |
| `qc_ncaamb_books.py` | `NOT_US_LICENSED` and unknown keys never published, counted in receipt; unknown → `WATCH`; no hard-coded book fallback string in NCAAMB modules/templates (scan, reusing the 1.5r bookmaker scan) |
| `qc_ncaamb_game_lines_contract.py` | Schema/types; every time column strict ISO-Z (zone-less rejected); away-outcome-first payload yields HOME row with **home** price and AWAY row with **away** price (the "price on the other side" regression); a payload whose away point is `+4.5` keeps `+4.5` on the AWAY row (no negation); `ONE_SIDED`, `INCONSISTENT` (-3.5 / +4.0) flagged and non-executable; `OUTCOME_UNMATCHED` dropped and counted; R1–R9 each reject with byte-identical outputs; `|price|<100` dropped; no `LastUpdated` column exists; `SourceUpdatedAtUTC` from market level, falls back to bookmaker level with `SourceTimeLevel=BOOKMAKER`, blank when neither (never fetch time) |
| `qc_ncaamb_events.py` | Commence change recorded with prior value and change row; `NOT_LISTED` never labelled postponed/cancelled; `NO_RESULT` at +48h; duplicate pair within 12h → both non-executable; same pair 3 days apart → two normal events; unpriced listed event → `PENDING` row, not zero |
| `qc_ncaamb_time.py` | 22:00 ET tip (03:00Z next day) → `EventDateET` previous day; DST boundary days (Nov 1/Mar 8 style fixtures); "today" correct at 23:30Z and 03:30Z; tzdata-missing simulation → `SERVICE_DATE_UNAVAILABLE`, not process zone; static scan: no naive `datetime.now()`, `pd.Timestamp.now()` without tz, or bare `.astimezone()` in NCAAMB modules |
| `qc_ncaamb_freshness.py` | Source 1h old on a UTC process → `AVAILABLE`; 6h00m01s → `STALE`; blank/zone-less → `UNAVAILABLE` (never live); +4 min future → tolerated; +6 min → `UNAVAILABLE`; a stale quote with a fresh `FetchedAtUTC` stays `STALE` (fetch time never substitutes); rendered page with an empty data dir shows reason text, no `0`, `0–0` or blank cells |
| `qc_ncaamb_snapshots.py` | Append-only (prior bytes are a prefix after append); re-appending the same run is a no-op; first-captured label never contains "open"; last pre-tip excludes a snapshot at exactly commence and one whose source time ≥ commence; 1 capture → "no movement read"; gz partition reads back identically |
| `qc_ncaamb_grading.py` | Spread push; total push; h2h win/loss; tied final → `ANOMALY`; no pre-tip capture → `NO_PRETIP_CAPTURE` (post-tip quote present but ignored); one-sided pre-tip → `MARKET_NOT_GRADEABLE`; `NOT_LISTED` + no final → `NO_RESULT` (no "void"); score names not matching → `ScoreMapping=FAILED`, not graded; corrected final re-grades and flags; books with different numbers → `MIXED`, breaks streak; rematch keyed by `EventId` |
| `qc_ncaamb_neutral_site.py` | Release-1 writer emits only `UNKNOWN`; `UNKNOWN`/`TRUE` rows never enter home/road splits; split module renders `unavailable — venue not verified` |
| `qc_ncaamb_no_consensus.py` | Static + behavioural: no mean/median/mode over `PriceAmerican`/`Point` in NCAAMB modules; best-available never merges points; ties list all books |
| `qc_ncaamb_pages.py` | Slate order strictly by `EventCommenceAtUTC` then `EventId` (shuffled fixture); no sort parameter accepted; unavailable-components list always present; honesty token scan (`confidence`, `score` as a rating, `lock`, `sharp`, `steam`, `best bet`, `edge`, `projection`, `Example`) absent; streak rows carry "Context, not an edge"; evidence panel shows counts by type and no numeric total; mobile render width check (no horizontal page scroll at 375 px) |
| `qc_ncaamb_ticket_handoff.py` | Executable leg requires every field + kickoff > now (now−1s, ==now excluded, now+1s eligible); unresolved identity / duplicate / not listed / one-sided / inconsistent each non-executable with its own code; h2h non-executable under the current contract (`MISSING_LINE`); quote change → whole-ticket 409 with server terms; client price never prices; 1 leg and 9 legs rejected, never truncated; no proposer (Green Light, Daily Card, Menu, Featured Parlay) imports an NCAAMB loader; Bet Tracker accepts `NCAAMB` |
| `qc_ncaamb_single_writer.py` | Only the declared writer writes each artifact; no `--output` override; unknown sport/path exits 2 before any request (call-counting stub); `fetch_game_lines.py`/`refresh_live_scores.py` carry no NCAAB output mapping |
| `qc_ncaamb_run_receipts.py` | Token required; missing → `RUN_RECEIPT_MISSING`; foreign token → `RUN_RECEIPT_MISMATCH`; no mtime path; skip paths still write own receipt; concurrent stages (process barrier, no sleeps); killed writer leaves no torn receipt |
| `qc_ncaamb_budget.py` | MTD from ledger by sport + UTC month; unprovable cost counted at expected and flagged; essential blocked above 95%, deferrable above 80% → `SKIP_BUDGET` with zero requests (stub counts calls); month rollover; `x-requests-last > expected` blocks publish |
| `qc_ncaamb_probe_script.py` | (for the probe script, before its approval) only the declared calls in the declared order; stops on first deviation; writes only under its probe dir; never writes the key; verdict logic for VERIFIED/CONCURRENT/MISMATCH/UNPROVABLE on header fixtures |
| `qc_sport_registry.py` (extended) | games-only rules (§12.3); declaring a props loader or stat map on NCAAMB fails; NCAAMB not-live remains a warning |

`py -3 -m py_compile app.py` and `qc_sport_registry.py` run on every change. `qc_odds_feed.py` is **never**
part of an offline gate (it calls the provider).

---

## 17. Out of scope (release 1) and deferred

**Out of scope (by owner decision or doctrine; not planned):**

- Green Light authority, Daily Card/Menu/Featured Parlay inclusion, any proposer
- Confidence, composite or risk scores, "best bets", locks, auto-EV, Kelly
- Simulations, projections, model lines, power ratings
- Picks or recommendations of any kind
- Sharp/steam labels
- Player props (decision 8)
- Injury/availability data (decision 11: shown as unavailable)
- External efficiency metrics: KenPom, barttorvik, sports-reference scraping (decision 5)
- ESPN or any unofficial scores (decision 4)
- Consensus or median prices; default books (decision 3)
- Manual neutral-site lists (decision 6)

**Deferred (possible later, each needs its own decision/design):**

- Women's NCAAB (decision 1; §3.6, §13.5)
- First-half spreads/totals and team totals (per-event cost; needs per-book writer + its own probe)
- h2h executability (shared contract amendment, Q8)
- Pre-tip capture option O2 and `us2` region option O1
- Historical odds purchase (decision 7, revisit after MVP)
- Authoritative neutral-site source
- Conference metadata population, bracket/tournament context
- Game-line best-lines and Market Movers tool integration for NCAAMB
- Licensed box-score source (possessions → pace/efficiency), CBBD terms review
- Officiating context
- Futures/season markets for CBB
- Parlay builder for CBB
- Any research-status promotion beyond Baseline

---

## 18. Open questions for the owner

1. **Licensed-book list (§4):** which provider book keys are `LICENSED_US`? (Legal determination; the probe
   supplies the observed keys.)
2. **Regions:** `us` only (base, 3 credits/run), or `us` + `us2` (6/run) to reach more licensed books? Decide
   after A3/A4 show which licensed books appear in each.
3. **`last_update` semantics:** if the probe shows many on-board quotes with source age > 6h at fetch time,
   those quotes are `STALE` under the frozen rule. Confirm the rule stands (this design assumes yes).
4. **Pre-tip capture (O2):** approve hourly narrow-window captures for better last-pre-tip quotes (≈ +1,100
   credits/month on `us`), or accept up to 4h capture lead?
5. **Probe approval:** Probe A (3 credits), Probe B (2), optional A4 (3), A5 (0–3), C (1).
6. **Season window** for the NCAAMB gate (verified first/last dates with sources), or rely on F2v2 schedule
   evidence?
7. **Unresolved identity:** keep the fail-closed rule (market facts visible, not addable to tickets), or
   allow ticket entry on provider identity alone?
8. **Moneyline legs:** amend the shared executable-leg contract to accept a declared no-line market (h2h), or
   keep h2h non-executable in release 1?
9. **Access tier:** is the NCAAMB slate free or `all_access`? Is the matchup page `all_access`?
10. **Duplicate window:** 12 hours for the same-pair duplicate rule — acceptable?
11. **Policy month:** budget cap on the UTC calendar month (designed), or aligned to the provider's
    billing reset date?
12. **Reference data tracking:** approve the narrow `.gitignore` negations for the four registry CSVs under
    `data/reference/` (§15), or name another tracked location.

---

## 19. Implementation order (each step its own reviewed branch; no step authorized by this doc)

1. PRE-1/PRE-2 deploy decisions (separate); PRE-3 consolidated game-lines correction; PRE-4 run-receipt
   generalization.
2. `probe_ncaab_costs.py` + `qc_ncaamb_probe_script.py` → review → **owner approves Probe A, then Probe B
   separately** → run on dev → receipt reviewed → §14.3 recomputed.
3. Registries: `sportsbooks.csv` (owner licence review), `ncaa_schools.csv`, `ncaamb_teams.csv`, aliases from
   the probe's `team_names.csv` (owner-reviewed) + `services/ncaamb_identity.py` + `qc_ncaamb_identity.py`,
   `qc_ncaamb_books.py`.
4. `services/ncaamb_contract.py` + `fetch_ncaamb_market.py` (offline QCs with stub provider; no live run).
5. `fetch_ncaamb_scores.py` + `grade_ncaamb_results.py` (offline).
6. `sport_registry` schema + `qc_sport_registry` games-only rules (NCAAMB stays `live=False`).
7. App loaders, slate + matchup pages, evidence panel, ticket/Bet Tracker handoff (fixtures only).
8. Orchestrator, lock, receipts, budget guard, `ops/` units (uninstalled).
9. Release gate: full offline gate → scoped Linux gate → owner approval → one governed manual run on prod →
   receipt → install timer and add the run_daily step → flip `live=True` → one monitored day → production
   receipt.
