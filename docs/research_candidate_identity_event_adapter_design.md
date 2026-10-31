# Research Candidate — Governed NFL Identity + Event Adapter (DESIGN ONLY — Rev 2)

**Status: DESIGN ONLY — Rev 2. No code, route, flag, schema edit, or deploy.** Date 2026-10-31. First 2D1
prerequisite (second = the idempotency registry, schema v3, BUILT). Rev 1 resolved player and event
independently and let resolution evidence evaporate before storage. **Rev 2** binds player and event
through a single board row, freezes source-season + artifact-health contracts around one immutable read of
each artifact, makes the reason codes mutually exclusive, and persists non-forgeable resolution provenance
with the observation.

The adapter turns an owner's **board selection** into the authoritative, governed inputs the store's sole
writer (`capture_observation`) demands — or **abstains**, returning a typed unavailability with a reason
code and writing nothing. RESEARCH_ONLY, zero authority, **never fabricates identity**: no fuzzy matching,
no short-form inference, no user-supplied kickoff, no independently-supplied player+event pair.

---

## 1. Request is a single board selection (player⟂event binding)

The request identifies **one current-board selection**, not a player and an event chosen separately. A
valid selection is a `(normalized Player, EventId)` pair that **exists as a row in one props snapshot**.
This is the core Rev-2 correction: the adapter never resolves two independently-supplied values. A valid
player id combined with an unrelated (but individually valid) event **abstains** with
`PLAYER_EVENT_MISMATCH`. The player id is resolved from *that row's* `Player`; the event id + kickoff come
from *that same row*. The binding `(EventId, player_id)` is the unit of resolution and of provenance.

## 2. Artifacts, season, and health — one immutable read each

- **Props board** `data/props/NFL_Props.csv` — `Player`, `EventId`, `EventCommenceAtUTC`.
- **Roster** `data/tracking/_nflverse_stats_<season>.parquet` — `player_id`, `player_display_name`.

Contracts (fail closed on every one):

1. **Current-season roster, not "latest filename".** The resolver determines the **current NFL season**
   from the governed season calendar (the same Week-1 table the app's completed-week logic uses —
   `NFL_SEASON_WEEK1_THURSDAY`), and loads **that** season's roster. A roster whose embedded season ≠ the
   resolver's current season → `ROSTER_SEASON_MISMATCH`. A missing/undiscoverable roster → `ROSTER_UNAVAILABLE`.
2. **Health gates.** Missing props → `PROPS_UNAVAILABLE`; props whose last-refresh signal is older than the
   configured freshness window (board must be current) → `PROPS_STALE`; props missing required columns or
   unreadable → `PROPS_SCHEMA_INVALID`. Roster missing `player_id`/display columns or unreadable →
   `ROSTER_UNAVAILABLE`.
3. **One immutable read + fingerprint.** Each artifact is read **once** into an in-memory snapshot; its
   **SHA-256** is computed over those exact bytes; every index (name→id, the `(EventId, player)` row set,
   the per-EventId kickoff set) is built from that single snapshot. A request resolves against one
   consistent `(props_sha256, roster_sha256)` pair.
4. **Fingerprint-keyed cache.** Built indexes are cached under `(props_sha256, roster_sha256, season,
   resolver_version)`. When **either** artifact's SHA-256 changes, the cached authority is invalidated and
   rebuilt — a formerly-valid cached resolution never survives an artifact change.

## 3. Resolution order (first failing gate wins — outcomes are mutually exclusive)

1. Artifact health: `PROPS_UNAVAILABLE` / `PROPS_STALE` / `PROPS_SCHEMA_INVALID` /
   `ROSTER_UNAVAILABLE` / `ROSTER_SEASON_MISMATCH`.
2. Event presence: the referenced `EventId` is absent from the snapshot → `EVENT_NOT_FOUND`.
3. **Binding:** `(normalized Player, EventId)` is not a row in the snapshot → `PLAYER_EVENT_MISMATCH`.
4. Kickoff: the bound row's `EventCommenceAtUTC` is blank/unparseable → `KICKOFF_MISSING`; the `EventId`
   carries >1 distinct kickoff in the snapshot → `KICKOFF_CONFLICT`; the kickoff is not in the future at
   resolution → `EVENT_PAST` (the store re-checks this under its lock, so a kickoff that passes between
   resolution and capture is still refused).
5. Identity: the normalized board name is absent from the roster → `NAME_UNRESOLVED`; it maps to **>1**
   `player_id` → `NAME_AMBIGUOUS`; the matched `player_id` maps to **>1** display names (alias guard,
   fail-closed even though the receipt showed 0) → `PLAYER_ID_ALIAS_CONFLICT`.

On success: `EntityIdentity(canonical_id=player_id, display=player_display_name, resolution=RESOLVED)` and
`EventIdentity(canonical_id=EventId, event_effective=<EventCommenceAtUTC as tz-aware UTC>)`.

### Reason codes (closed, mutually exclusive)

`PROPS_UNAVAILABLE`, `PROPS_STALE`, `PROPS_SCHEMA_INVALID`, `ROSTER_UNAVAILABLE`, `ROSTER_SEASON_MISMATCH`,
`EVENT_NOT_FOUND`, `PLAYER_EVENT_MISMATCH`, `KICKOFF_MISSING`, `KICKOFF_CONFLICT`, `EVENT_PAST`,
`NAME_UNRESOLVED`, `NAME_AMBIGUOUS`, `PLAYER_ID_ALIAS_CONFLICT`.

Rev-1's `NAME_COLLISION` is **removed** — it duplicated `NAME_AMBIGUOUS` (name→>1 id). The id→>1-names
guard is the separately named `PLAYER_ID_ALIAS_CONFLICT`. Rev-1's `EVENT_ID_MISSING` is **removed** (a row
with no usable event is reached as `EVENT_NOT_FOUND` or `PLAYER_EVENT_MISMATCH`).

## 4. Resolution provenance (persisted, non-forgeable)

A successful resolution carries, and MUST persist with the observation:

- `resolver_version` (adapter/resolver version);
- `props_sha256`;
- `roster_sha256` + `roster_season`;
- the selected binding `(EventId, player_id)`;
- `resolved_at` (tz-aware UTC).

**Mechanism — reserved system-source references.** Provenance is carried as **reserved, system-only source
references** under a non-user-forgeable scheme `bkres:` — e.g. `bkres:resolver/v1`,
`bkres:props-sha256/<hex>`, `bkres:roster-sha256/<hex>`, `bkres:roster-season/2026`,
`bkres:binding/<EventId>/<player_id>`, `bkres:resolved-at/<iso-utc>` — distinct from owner-entered
`sources`. This needs a small **store (2B-family) refinement** built with the adapter (design it now,
implement with the adapter, with its own QC):

- `capture_observation` gains a route-supplied `system_sources` input; it **rejects any owner `sources`
  entry in the `bkres:` namespace** (anti-forgery enforced at the sole writer, not only the route), and
  **requires** every `system_sources` entry to be a well-formed `bkres:` reference.
- Stored `sources` = the canonical union (owner + system); provenance therefore rides in the observation
  and its `content_hash`.
- **Idempotency is preserved:** the request fingerprint is computed over **owner sources only** (plus the
  authoritative identity/event/thesis/acted) and **excludes `bkres:` system sources**. The authoritative
  identity is stable regardless of *when* it was resolved, so an exact retry — even re-resolved at a new
  instant against the same artifacts — is still a no-op; the first stored observation's provenance stands.
  (Reserved sources are evidence of resolution, not owner intent, so they must not perturb the fingerprint.)

Provenance cannot disappear before storage: the adapter returns it with the resolved input; the route
passes it as `system_sources`; the store persists it in the same capture transaction. The future
owner-only route **rejects owner sources using the reserved namespace** and stores the resolution
references with the observation.

## 5. Output contract

```
resolve(board_selection) -> ResolvedObservationInput | Abstention

ResolvedObservationInput:
  entity:  EntityIdentity        # RESOLVED; canonical_id = roster player_id, display = roster display name
  event:   EventIdentity         # canonical_id = EventId, event_effective = EventCommenceAtUTC (tz-aware UTC)
  system_sources: tuple[str]     # reserved bkres: provenance refs (§4); route passes straight to the store

Abstention:
  reason_code: one of §3
  dimension:   "artifact" | "event" | "binding" | "player"
```

The future owner-only route passes `entity`/`event`/`system_sources` into `capture_observation` with the
owner's `observer_id`, `thesis`, owner `sources`, `acted`, and an opaque `idempotency_key`. An `Abstention`
maps to a tiered unavailable (e.g. 422) — never a record.

## 6. What it must NOT do

- No fuzzy/approximate matching, no short-form/nickname expansion, no cross-season carry of a name whose id
  changed, no "latest filename" roster.
- No independently-supplied player+event; resolution is always through one bound board row.
- No user-supplied/synthesized kickoff or `player_id`; a missing/ambiguous id or event abstains.
- No owner-supplied `bkres:` source (rejected at the store); no authority/score/sort/promotion — identity
  resolution only. `SUPPORTED`/`UNSUPPORTED` remain unconstructible upstream.
- No writes to props/roster; the index build and collision audit are read-only.

## 7. Proposed QC (adversarial — build alongside the adapter, before any route)

1. Exact single match on a real board row → `RESOLVED` entity (`canonical_id == player_id`, roster display)
   + `EventIdentity` from the same row; `system_sources` carry all five provenance facts.
2. **Valid player paired with the wrong event** (both individually valid, not a board row) →
   `PLAYER_EVENT_MISMATCH`, nothing built.
3. **Event absent from the current board** → `EVENT_NOT_FOUND`.
4. **Roster wrong season** (embedded season ≠ resolver current season) → `ROSTER_SEASON_MISMATCH`;
   missing roster → `ROSTER_UNAVAILABLE`.
5. **Stale / schema-invalid props** → `PROPS_STALE` / `PROPS_SCHEMA_INVALID`; missing props →
   `PROPS_UNAVAILABLE`.
6. Name unresolved / `NAME_AMBIGUOUS` / `PLAYER_ID_ALIAS_CONFLICT` each produce the correct code; a
   near-miss (one edit away) does NOT fuzzy-resolve — it abstains `NAME_UNRESOLVED`.
7. Kickoff blank/unparseable → `KICKOFF_MISSING`; EventId with >1 kickoff → `KICKOFF_CONFLICT`; past
   kickoff → `EVENT_PAST` (and end-to-end, the store refuses a future-turned-past event under its lock).
8. **Artifact change invalidates a formerly-valid cached resolution:** resolve once; change the props (or
   roster) bytes so its SHA-256 changes; the cached authority is rebuilt and the stale index is not reused.
9. **Provenance fingerprints change with source content:** two resolutions against different artifact bytes
   carry different `props_sha256`/`roster_sha256` in `system_sources`.
10. **Owner forgery rejected:** an owner `sources` entry in the `bkres:` namespace is rejected by the store
    (sole-writer anti-forgery), no record written.
11. **End-to-end provenance retention:** a `ResolvedObservationInput` fed through `capture_observation`
    records exactly once, and the stored observation retains `resolver_version`, both artifact SHA-256s,
    `roster_season`, the `(EventId, player_id)` binding, and `resolved_at`; an exact retry (re-resolved at a
    new instant against the same artifacts) is still a no-op (owner-source-only fingerprint).

## 8. Boundary

Design only. Building this is a new resolver module + the small `capture_observation` `system_sources`
refinement + their QC, to be approved and landed BEFORE any 2D1 owner-only route, flag, boundary module, or
unit file. **No paid fetch** (persisted artifacts only), **zero authority**, **abstains** rather than guess.
2D1 production routing stays blocked until this adapter (and the store refinement) are
**designed → approved → built** and wired behind the dark flag.

**STOP — returned for review.** No code, route, flag, schema edit, or deployment has been made.
