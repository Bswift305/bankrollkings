# Research Candidate — Governed NFL Identity + Event Adapter (DESIGN ONLY — Rev 2.1)

**Status: DESIGN ONLY — Rev 2.1. No code, route, flag, schema edit, or deploy.** Date 2026-10-31. First
2D1 prerequisite (second = the idempotency registry, schema v3, BUILT). Rev 2 bound player+event through one
board row and persisted provenance. **Rev 2.1** freezes the health contracts to named, versioned sources,
replaces route-supplied provenance strings with a typed `ResolutionEvidence` object the store validates,
freezes the reserved-reference grammar, and states idempotent-provenance behavior exactly.

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
roster `data/tracking/_nflverse_stats_<season>.parquet` (`player_id`, `player_display_name`). Each is read
**once** into a snapshot, SHA-256'd over those exact bytes, and all indexes built from that single read; a
request resolves against one consistent `(props_sha256, roster_sha256)` pair. The index cache is keyed on
`(props_sha256, roster_sha256, season, resolver_version)` and invalidated whenever either SHA-256 changes.

**Named contracts (no hand-picked thresholds):**

- **Current NFL season** = `_nfl_expected_completed_week()` → `NFL_SEASON_WEEK1_THURSDAY` (`app.py`). If the
  governed calendar has **no entry** for the candidate season (cannot resolve) → `SEASON_UNAVAILABLE`
  (fail closed; no roster load attempted). The season is derived by the resolver, never supplied.
- **Roster season** must equal that current season (the roster is season-partitioned, so "stale roster" ==
  "wrong season"): embedded season ≠ current → `ROSTER_SEASON_MISMATCH`; missing/undiscoverable →
  `ROSTER_UNAVAILABLE`; unreadable or missing `player_id`/`player_display_name` → `ROSTER_SCHEMA_INVALID`.
  There is **no** declared roster refresh-cadence family, so roster freshness is exactly current-season
  correctness — the adapter does not invent a cadence.
- **Props staleness clock** = the ONE declared freshness contract `services/freshness_contract.py`,
  `refresh_cadence_hours("props", "NFL")` — **CLOCK B** (artifact file mtime vs refresh cadence), today
  **30.0h**, the SAME clock `qc_odds_feed` / `generate_run_status` / `report_feed_availability` use, so the
  adapter can never call the board FRESH when the platform calls it STALE. File-age over the contract
  window → `PROPS_STALE`. Missing props → `PROPS_UNAVAILABLE`.
- **Props freshness metadata (fail closed, no silent mtime-only pass).** The bound row's `SourceUpdatedAtUTC`
  (provider `last_update`, tz-aware UTC) **must be present and parseable**. Absent/unparseable →
  `PROPS_SCHEMA_INVALID`. This metadata requirement is independent of the CLOCK-B staleness gate; the
  adapter never treats absent freshness metadata as fresh and never silently substitutes mtime for it.
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

`capture_observation(..., evidence: ResolutionEvidence)` — a store (2B-family) refinement, designed here —
**validates before any write** (reject → fail closed, no record, no reservation):

- `props_sha256` / `roster_sha256` match `^[0-9a-f]{64}$`; `resolver_version` matches `^v\d+(\.\d+)*$`;
  `resolver_id` non-empty;
- `resolved_at` is tz-aware UTC;
- `evidence.event_id == event.canonical_id` **and** `evidence.player_id == entity.canonical_id`;
- `evidence.roster_season ==` the **governed current season** (the store re-derives it via the §2 calendar,
  so season-binding is enforced by the store, not trusted from the route).

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

## 8. Boundary

Design only. Building this is a new resolver module + the `capture_observation` `ResolutionEvidence`
refinement + their QC, to be approved and landed BEFORE any 2D1 owner-only route, flag, boundary module, or
unit file. **No paid fetch** (persisted artifacts only), **zero authority**, **abstains** rather than guess.
2D1 production routing stays blocked until this adapter and the store refinement are
**designed → approved → built** and wired behind the dark flag.

**STOP — returned for review.** No code, route, flag, schema edit, or deployment has been made.
