# Research Candidate — Governed NFL Identity + Event Adapter (DESIGN ONLY — Rev 2.2)

**Status: DESIGN ONLY — Rev 2.2. No code, route, flag, schema edit, or deploy.** Date 2026-10-31. First
2D1 prerequisite (second = the idempotency registry, schema v3, BUILT). Rev 2.1 froze the health contracts
and the typed evidence object. **Rev 2.2** freezes four details that affect persistence and future replay:
(1) extract the NFL season contract out of `app.py` so nothing imports the monolith; (2) bind freshness to
the same open file handle (no TOCTOU) and require the roster's embedded `season` column; (3) tighten
`ResolutionEvidence` (registered resolver id, strict integer season, round-trip-parseable references); and
(4) advance the store to **schema v4** because every governed observation must now carry one complete
evidence set — v3 is rejected with no migration, and reopen validates the provenance without pinning
historical observations to the current season.

The adapter turns an owner's **board selection** into the authoritative, governed inputs the store's sole
writer (`capture_observation`) demands — or **abstains**, returning a typed unavailability with a reason
code and writing nothing. RESEARCH_ONLY, zero authority, **never fabricates identity**: no fuzzy matching,
no short-form inference, no user-supplied kickoff, no independently-supplied player+event pair.

---

## 1. Request is a single board selection (player⟂event binding)

Unchanged from Rev 2. The request identifies **one current-board selection** — a `(normalized Player,
EventId)` pair that **exists as a row in one props snapshot**. A valid player id + an unrelated (but
individually valid) event **abstains `PLAYER_EVENT_MISMATCH`**; two independently-supplied values are never
resolved. The player id comes from that row's `Player`; the event id + kickoff from that same row. The
binding `(EventId, player_id)` is the unit of resolution and of provenance.

## 2. Frozen health / season / freshness contracts

Artifacts: props `data/props/NFL_Props.csv` (`Player`, `EventId`, `EventCommenceAtUTC`, `SourceUpdatedAtUTC`);
roster `data/tracking/_nflverse_stats_<season>.parquet` (`player_id`, `player_display_name`, **`season`**).

**No `app.py` import — a pure season contract module.** `_nfl_expected_completed_week()` and
`NFL_SEASON_WEEK1_THURSDAY` currently live in `app.py`. They are extracted into a pure, side-effect-free
module (e.g. `services/nfl_season_contract.py`); `app.py`, the adapter, and the store all consume that one
implementation. The adapter/store **never import `app.py`**. A **parity QC** proves `app.py`'s existing
completed-week / season behavior is unchanged after the extraction (the app delegates to the module).

**Same-handle snapshot (no TOCTOU).** Each artifact is **opened once**; its bytes, its SHA-256, and its
CLOCK-B mtime (`os.fstat(fd)` on that same descriptor) all come from the **same open handle** — the adapter
never hashes one file version and then reads mtime or rows from a replacement. The bytes are parsed
in-memory (e.g. `BytesIO`) from that one snapshot. A request resolves against one consistent
`(props_sha256, roster_sha256)` pair; the index cache is keyed on
`(props_sha256, roster_sha256, season, resolver_version)` and invalidated whenever either SHA-256 changes.

**Named contracts (no hand-picked thresholds):**

- **Current NFL season** = the extracted season contract's completed-week/season resolver (the same logic
  `app.py` uses today). No calendar entry for the candidate season → `SEASON_UNAVAILABLE` (fail closed; no
  roster load). The season is derived, never supplied.
- **Roster season** is read from the roster's embedded **`season` column** (part of its schema contract),
  not the filename, and must equal the current season (season-partitioned, so "stale roster" == "wrong
  season"): embedded season ≠ current → `ROSTER_SEASON_MISMATCH`; missing/undiscoverable →
  `ROSTER_UNAVAILABLE`; unreadable or missing `player_id`/`player_display_name`/`season` →
  `ROSTER_SCHEMA_INVALID`. No roster refresh-cadence family is declared, so roster freshness is exactly
  current-season correctness.
- **Props staleness clock** = the ONE declared freshness contract `services/freshness_contract.py`,
  `refresh_cadence_hours("props", "NFL")` — **CLOCK B** (the same handle's `fstat` mtime vs refresh
  cadence), today **30.0h**, the SAME clock `qc_odds_feed` / `generate_run_status` /
  `report_feed_availability` use, so the adapter can never call the board FRESH when the platform calls it
  STALE. File-age over the window → `PROPS_STALE`. Missing props → `PROPS_UNAVAILABLE`.
- **Props freshness metadata (fail closed, no silent mtime-only pass).** The bound row's `SourceUpdatedAtUTC`
  (provider `last_update`, tz-aware UTC) **must be present and parseable**. Absent/unparseable →
  `PROPS_SCHEMA_INVALID`. Independent of the CLOCK-B staleness gate; absent freshness metadata is never
  treated as fresh and mtime is never silently substituted for it.
- **Props schema.** Missing required columns or an unreadable file → `PROPS_SCHEMA_INVALID`.

## 3. Resolution order (first failing gate wins — outcomes mutually exclusive)

1. Season: `SEASON_UNAVAILABLE`.
2. Artifact health: `PROPS_UNAVAILABLE` / `PROPS_STALE` / `PROPS_SCHEMA_INVALID` / `ROSTER_UNAVAILABLE` /
   `ROSTER_SCHEMA_INVALID` / `ROSTER_SEASON_MISMATCH`.
3. Event presence: referenced `EventId` absent from the snapshot → `EVENT_NOT_FOUND`.
4. Binding: `(normalized Player, EventId)` is not a row in the snapshot → `PLAYER_EVENT_MISMATCH`.
5. Kickoff: bound row's `EventCommenceAtUTC` blank/unparseable → `KICKOFF_MISSING`; the `EventId` carries
   >1 distinct kickoff → `KICKOFF_CONFLICT`; kickoff not in the future at resolution → `EVENT_PAST` (the
   store re-checks under its lock).
6. Identity: normalized board name absent from roster → `NAME_UNRESOLVED`; name → >1 `player_id` →
   `NAME_AMBIGUOUS`; matched `player_id` → >1 display names (alias guard, fail-closed) →
   `PLAYER_ID_ALIAS_CONFLICT`.

On success: `EntityIdentity(canonical_id=player_id, display=player_display_name, resolution=RESOLVED)` and
`EventIdentity(canonical_id=EventId, event_effective=<EventCommenceAtUTC, tz-aware UTC>)`, plus a
`ResolutionEvidence` (§4).

### Reason codes (closed, mutually exclusive)

`SEASON_UNAVAILABLE`, `PROPS_UNAVAILABLE`, `PROPS_STALE`, `PROPS_SCHEMA_INVALID`, `ROSTER_UNAVAILABLE`,
`ROSTER_SCHEMA_INVALID`, `ROSTER_SEASON_MISMATCH`, `EVENT_NOT_FOUND`, `PLAYER_EVENT_MISMATCH`,
`KICKOFF_MISSING`, `KICKOFF_CONFLICT`, `EVENT_PAST`, `NAME_UNRESOLVED`, `NAME_AMBIGUOUS`,
`PLAYER_ID_ALIAS_CONFLICT`. (`NAME_COLLISION` and `EVENT_ID_MISSING` were removed in Rev 2.)

## 4. Typed `ResolutionEvidence` (not route-supplied strings)

Calling route-supplied strings "non-forgeable" overclaims. Rev 2.1 defines a governed value object the
**adapter constructs** and the **store validates and serializes** — the route never handcrafts references.

```
ResolutionEvidence (frozen value object, in the research-candidate domain):
  resolver_id:    str            # e.g. "nfl_identity_event_adapter"
  resolver_version: str          # grammar-checked, e.g. "v1" / "v1.2"
  props_sha256:   str            # 64 lowercase hex
  roster_sha256:  str            # 64 lowercase hex
  roster_season:  int
  event_id:       str            # == EventIdentity.canonical_id
  player_id:      str            # == EntityIdentity.canonical_id
  resolved_at:    datetime       # tz-aware UTC
```

`capture_observation(..., evidence: ResolutionEvidence)` — a store (schema-v4) refinement, designed here —
takes `evidence` as a **mandatory** argument (no governed observation may be written without it) and
**validates before any write** (reject → fail closed, no record, no reservation):

- `props_sha256` / `roster_sha256` match `^[0-9a-f]{64}$`; `resolver_version` matches `^v\d+(\.\d+)*$`;
- `resolver_id` **equals the registered adapter id** (a store-side constant / small allow-list), not merely
  non-empty — an unregistered resolver is rejected;
- `roster_season` is a **strict `int`** — booleans and non-integers are rejected (`isinstance(x, int) and
  not isinstance(x, bool)`);
- `resolved_at` is tz-aware UTC;
- `evidence.event_id == event.canonical_id` **and** `evidence.player_id == entity.canonical_id`;
- `evidence.roster_season ==` the **governed current season** (the store re-derives it via the §2 season
  contract, so season-binding at capture is enforced by the store, not trusted from the route).

The **store** then serializes the validated object into canonical reserved references (§5) and persists
them with the observation (in `sources_json` + `content_hash`), **excluded from the request fingerprint**
(§6). Owner-entered `sources` are rejected if, after `strip()` → NFC → `casefold()`, any entry begins with
the reserved prefix `bkres:` — so `BKRES:`, `  Bkres: …`, and whitespace variants are all caught. This puts
anti-forgery and evidence validation at the sole writer, not only the route.

## 5. Reserved-reference grammar (store-generated, frozen)

The store (never the caller) emits the references from the validated `ResolutionEvidence`, in a fixed field
order, under a versioned prefix so the grammar can evolve:

```
bkres:v1:resolver=<resolver_id>@<resolver_version>
bkres:v1:props-sha256=<64hex>
bkres:v1:roster-sha256=<64hex>
bkres:v1:roster-season=<int>
bkres:v1:event=<enc(event_id)>
bkres:v1:player=<enc(player_id)>
bkres:v1:resolved-at=<iso8601-utc>     # canonical: YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00
```

`enc(x)` percent-encodes every byte outside `[A-Za-z0-9._-]` (so `:`, `=`, `@`, `%`, and whitespace are
escaped), making each reference unambiguously parseable. Callers never handcraft these; they pass the typed
object and the store generates and parses the `bkres:v1:` forms.

**Round-trip invariant.** The store's parser accepts a reserved-reference set **only if it parses back into
exactly one complete `ResolutionEvidence`**: all seven fields present, **each exactly once**, **no missing
field, no duplicate field, no extra `bkres:v1:` field**, and the parsed `event`/`player` equal the stored
`EventIdentity`/`EntityIdentity`. `serialize(evidence)` then `parse(...)` must reproduce the original
evidence; any deviation fails closed. This is enforced both when writing (serialize is total) and on reopen
(§6a).

## 6. Idempotent provenance behavior (explicit)

- The request fingerprint **excludes** resolution evidence entirely (it covers owner `sources` + the
  authoritative identity/event/thesis/acted only).
- The **first** successful record's evidence is **immutable** (it is in `content_hash`; the record and its
  registry binding are write-once).
- A retry with **unchanged semantic intent** returns that **original** record and its **original** evidence
  (the store no-ops).
- The **newly resolved evidence on that retry is discarded** — the no-op writes nothing, so it never
  overwrites the stored provenance (even if re-resolved against changed artifacts, see §7 case 6).
- If the **current resolution abstains before store invocation**, **no idempotency lookup is implied** — the
  adapter short-circuits with an `Abstention` and `capture_observation` is never called, so there is no key
  lookup and no historical record is consulted.

## 6a. Persisted evidence invariant — schema v4

This refinement changes the persisted observation invariant: **every governed observation must carry exactly
one complete `ResolutionEvidence` set.** Existing schema-v3 observations do not. Because nothing is deployed,
the store advances to **`SCHEMA_VERSION = 4`** and **rejects v1/v2/v3 on open with no migration**.
`capture_observation`'s `evidence` is mandatory; an observation cannot be written without it.

**Reopen rules (capture-time vs durable invariants are distinct):**

- Every `observation_private` row's reserved `bkres:v1:` references **parse back to exactly one complete
  evidence set** (§5) whose `event_id`/`player_id` **equal the stored `EventIdentity`/`EntityIdentity`** —
  otherwise `StoreIntegrityError` (fail closed). This joins the existing observation↔registry both-direction
  reconcile.
- Reopen does **NOT** require the stored `roster_season` to equal the *current* season. Otherwise every
  prior-season observation would invalidate the database the moment the calendar advances. **Current-season
  equality is a capture-time gate only** (§4); once stored, the season is historical fact and stays valid.
  Reopen validates the provenance **grammar + binding + completeness**, never current-season recency.

## 7. Proposed QC (adversarial — build alongside the adapter, before any route)

1. Exact single match on a real board row → `RESOLVED` entity (`canonical_id == player_id`, roster display)
   + `EventIdentity` from the same row + a `ResolutionEvidence` carrying all fields.
2. Valid player paired with the wrong event (not a board row) → `PLAYER_EVENT_MISMATCH`; event absent from
   the board → `EVENT_NOT_FOUND`.
3. Roster wrong season → `ROSTER_SEASON_MISMATCH`; missing → `ROSTER_UNAVAILABLE`; bad columns →
   `ROSTER_SCHEMA_INVALID`. **Unsupported season** (calendar has no entry) → `SEASON_UNAVAILABLE`.
4. Props missing → `PROPS_UNAVAILABLE`; file-age over `refresh_cadence_hours("props","NFL")` → `PROPS_STALE`;
   **missing/unparseable `SourceUpdatedAtUTC`** → `PROPS_SCHEMA_INVALID` (fail closed, no silent mtime pass);
   bad columns → `PROPS_SCHEMA_INVALID`.
5. `NAME_UNRESOLVED` / `NAME_AMBIGUOUS` / `PLAYER_ID_ALIAS_CONFLICT` each produce the correct code; a
   near-miss (one edit away) does NOT fuzzy-resolve → `NAME_UNRESOLVED`.
6. Kickoff blank/unparseable → `KICKOFF_MISSING`; >1 kickoff → `KICKOFF_CONFLICT`; past → `EVENT_PAST`
   (and end-to-end, the store refuses a future-turned-past event under its lock).
7. **Artifact change invalidates the cached resolution:** change props (or roster) bytes so the SHA-256
   changes; the cache rebuilds, the stale index is not reused; evidence then carries the new SHA-256
   (provenance fingerprints change with content).
8. **Forged reserved owner source**, mixed-case + whitespace (`BKRES:…`, `  bkres: …`) → rejected by the
   store after trim+NFC+casefold; no record.
9. **Malformed evidence** — bad hash (non-64-hex), bad `resolver_version`, non-UTC `resolved_at` → store
   rejects, no record, no reservation.
10. **Evidence/identity mismatch** — `evidence.event_id` ≠ `EventIdentity.canonical_id`, or
    `evidence.player_id` ≠ `EntityIdentity.canonical_id`, or `evidence.roster_season` ≠ governed season →
    store rejects.
11. **End-to-end provenance retention + idempotent retry:** a resolved input + evidence through
    `capture_observation` records once and the stored observation retains resolver id/version, both
    SHA-256s, season, the `(EventId, player_id)` binding, and `resolved_at`. A **retry with changed artifact
    fingerprints** (same semantic intent + key) returns the **original** record and its **original**
    provenance **unchanged**; the newly-resolved evidence is discarded.
12. **App ↔ season-resolver parity:** the extracted season module and `app.py`'s delegating call produce
    identical completed-week/season results across a span of dates (existing app behavior unchanged).
13. **Same-handle snapshot metadata:** SHA-256 and CLOCK-B mtime are taken from one `fstat` on the open
    handle; a file swapped after the handle is opened cannot split the hash from the mtime/rows.
14. **Incomplete / duplicate / extra provenance:** a reserved set missing a field, with a duplicated
    `bkres:v1:` field, or with an extra field fails to parse → rejected on write and on reopen.
15. **Unregistered resolver id:** `evidence.resolver_id` ≠ the registered adapter id → store rejects, no
    record. Strict-int season: a boolean or non-int `roster_season` → rejected.
16. **Schema v4 rejects v3:** a v3 (or v1/v2) store fails closed on open (`SchemaVersionError`), no migration,
    no mutation.
17. **Reopen after the calendar advances:** a store of prior-season observations reopens cleanly when the
    current season has moved on — provenance grammar + binding validate, and `roster_season` recency is NOT
    required at reopen.

## 8. Boundary + build sequence

Design only. Building this is staged, each step approved before the next, and all BEFORE any 2D1 owner-only
route/flag/boundary/unit:

1. **Extract `services/nfl_season_contract.py`** (pure, side-effect-free) + the app parity QC; `app.py`
   delegates to it. No behavior change.
2. **Store schema-v4 refinement — BUILT** (dark/local): `ResolutionEvidence` added to the domain; mandatory
   `evidence` on `capture_observation`; the store generates/parses the `bkres:v1:` references with the
   round-trip + reopen invariants (incl. owner-only fingerprint recompute) and reserved-scheme owner-source
   rejection; `SCHEMA_VERSION`→4 rejects v1/v2/v3; the domain/store/backup/idempotency QC capture **with**
   evidence (domain 128, store 73, backup 50, idempotency 56).
3. **The resolver module — BUILT** (dark/local): `services/nfl_identity_event_adapter.py` —
   `NflIdentityEventAdapter(props_path, roster_path, clock=…).resolve(player_ref, event_id)` returns a
   `ResolvedObservationInput` (RESOLVED `EntityIdentity` + UTC `EventIdentity` + `ResolutionEvidence`) or
   exactly one `Abstention(reason_code, dimension)`. Single-snapshot reads (bytes+sha+fstat from one fd),
   pure season contract, declared props freshness + bound-row `SourceUpdatedAtUTC`, board-row binding,
   exact unique name→`player_id` with per-build collision audit, embedded roster season, cache keyed on
   `(props_sha256, roster_sha256, season, resolver_version)`. QC `qc_nfl_identity_event_adapter.py` (36):
   success + every abstention code + wrong-event + TOCTOU + cache invalidation + collision-on-refresh +
   stale/schema-invalid + UTC kickoff + end-to-end capture/provenance. No route/flag/UI/unit/deploy.

**No paid fetch** (persisted artifacts only), **zero authority**, **abstains** rather than guess. 2D1
production routing stays blocked until all three are **designed → approved → built** and wired behind the
dark flag.

**STOP — returned for review.** No code, route, flag, schema edit, or deployment has been made.
