# Research Candidate — Governed NFL Identity + Event Adapter (DESIGN ONLY)

**Status: DESIGN ONLY. No code, route, flag, schema edit, or deploy.** Date 2026-10-31. This is the first
2D1 prerequisite (the second — the idempotency registry, schema v3 — is BUILT). It is authorized to begin
after: the registry closed (`docs/research_candidate_idempotency_registry_design.md`, BUILT) and the
identity feasibility receipt confirmed an abstain-capable join (`docs/research_candidate_2d1_identity_feasibility.md`:
event binding authoritative; name→`player_id` 80% of names / 92% of rows, with a governed abstain tail).

The adapter turns an owner's loosely-typed NFL observation request into the **authoritative, governed
inputs** the store's sole writer (`capture_observation`) demands — or **abstains**, returning a typed
unavailability with a reason code and writing nothing. It is RESEARCH_ONLY, carries zero authority, and
**never fabricates identity**: no fuzzy matching, no short-form inference, no user-supplied kickoff.

---

## 1. Why an adapter (the gap it closes)

`capture_observation(observer_id, entity: EntityIdentity, event: EventIdentity, thesis, sources, acted,
idempotency_key)` already refuses a non-`RESOLVED` entity and a non-future event, and canonicalizes the
event instant to UTC. But it takes identity/event as **already-governed objects**. Nothing today maps an
owner's input (a player the owner names, a game they mean) to:

1. an immutable **player id**, 2. a canonical **display identity**, 3. a governed **event id**, 4. an
authoritative **kickoff**, 5. explicit **unresolved/ambiguous/missing** behavior.

The adapter is that mapping, and it is the ONLY thing allowed to construct the `EntityIdentity`/
`EventIdentity` handed to `capture_observation`. The owner never types a player id or a kickoff.

## 2. Inputs

- **From the owner (the request):** a player reference (a display name as shown on the board) and an event
  reference (the specific upcoming game — surfaced as a pick from the current slate, never a free-text
  kickoff). Plus the human `thesis`, optional `sources`, `acted`. The owner selects from board rows; they do
  not supply ids or times.
- **From persisted artifacts (read-only, no paid fetch):**
  - the props board `data/props/NFL_Props.csv` — columns `Player`, `EventId`, `EventCommenceAtUTC` (the
    kickoff; confirmed 100% present/parseable, zero conflicting kickoffs);
  - the roster `data/tracking/_nflverse_stats_<season>.parquet` — `player_id` + `player_display_name`
    (auto-discovered latest season; confirmed 0 id→>1-name duplicates).

## 3. The five authoritative facts

| Fact | Source | Rule |
|---|---|---|
| Immutable player id | roster `player_id` | via the EXACT normalized name→id index (§4); abstain if not exactly one |
| Canonical display | roster `player_display_name` | the roster's display, NOT the owner's typed string |
| Event id | props `EventId` | taken from the selected board row; abstain if blank |
| Authoritative kickoff | props `EventCommenceAtUTC` | parsed as tz-aware UTC; abstain if blank/unparseable/conflicting |
| Unresolved/ambiguous/missing | — | explicit abstention with a reason code (§5); never a guess |

On success the adapter returns `EntityIdentity(canonical_id=player_id, display=player_display_name,
resolution=RESOLVED)` and `EventIdentity(canonical_id=EventId, event_effective=<EventCommenceAtUTC, UTC>)`.
The store then re-checks `event_effective > now` under the lock, so a game that kicks off between resolution
and capture is still refused downstream.

## 4. Exact-match resolver + per-refresh collision audit

- **Normalization:** casefold + whitespace-collapse only (the identity audit's `norm`). **No** fuzzy
  distance, **no** short-form/initial expansion, **no** nickname tables.
- **Index:** from the current roster, build `normalized_display → {player_id}`. A normalized name mapping to
  **exactly one** `player_id` is *authoritative*; **zero** ids = unresolved; **>1** ids = ambiguous.
- **Collision audit (every roster refresh):** recompute the index and record the set of ambiguous
  (name→>1 id) names and the unresolved set. These shift week to week (the receipt showed 3 roster
  collisions and 84 unresolved against the current board). A name that becomes non-unique **loses
  authority immediately** — the adapter abstains on it even if it resolved last week. The audit is a
  read-only report; it never mutates the roster.
- **Stability note:** the receipt showed 0 id→>1-name duplicates, so a resolved name's id is a stable 1:1.
  That is a precondition the audit re-verifies; if it ever fails, the adapter abstains store-wide on the
  affected ids rather than pick one.

## 5. Abstention taxonomy (typed, reason-coded — never zero-filled)

The adapter returns either a `ResolvedObservationInput` (§6) or an `Abstention(reason_code, dimension)`.
It writes nothing on abstention. Reason codes (closed set):

- `NAME_UNRESOLVED` — the normalized board name is absent from the roster.
- `NAME_AMBIGUOUS` — the normalized name maps to >1 `player_id`.
- `NAME_COLLISION` — the name is in the current collision-audit set (non-authoritative this refresh).
- `EVENT_ID_MISSING` — the selected row has a blank `EventId`.
- `KICKOFF_MISSING` — `EventCommenceAtUTC` is blank/unparseable.
- `KICKOFF_CONFLICT` — the `EventId` carries >1 distinct kickoff on the board (ambiguous event).
- `EVENT_PAST` — the kickoff is not in the future at resolution time (the store re-checks under lock).
- `ROSTER_UNAVAILABLE` — no roster artifact discovered / missing `player_id`|display columns (fail closed).

Abstentions are **surfaced** (count + reason), never silently dropped and never coerced to a neutral/zero
identity. An abstained request is simply not an observation.

## 6. Output contract

```
resolve(player_ref, event_ref) -> ResolvedObservationInput | Abstention

ResolvedObservationInput:
  entity: EntityIdentity   # RESOLVED, canonical_id = roster player_id, display = roster display name
  event:  EventIdentity    # canonical_id = EventId, event_effective = EventCommenceAtUTC (tz-aware UTC)

Abstention:
  reason_code: one of §5
  dimension:   "player" | "event"
```

The caller (a future owner-only route, still blocked) passes a `ResolvedObservationInput`'s `entity`/`event`
straight into `capture_observation` with the owner's `observer_id`, `thesis`, `sources`, `acted`, and an
opaque `idempotency_key`. An `Abstention` maps to a tiered unavailable (e.g. 422) — never a record.

## 7. What it must NOT do

- No fuzzy/approximate matching, no short-form or nickname expansion, no cross-season carry of a name whose
  id changed.
- No user-supplied or synthesized kickoff; the kickoff is the persisted Odds `EventCommenceAtUTC` only.
- No synthesized `player_id`; a missing/ambiguous id abstains.
- No authority, no score, no sort delta, no promotion — the adapter resolves identity only; `SUPPORTED`/
  `UNSUPPORTED` remain unconstructible upstream.
- No writes to the roster/props; the audit is read-only.

## 8. Proposed QC (adversarial — to accompany the build, before any route)

1. Exact single match → `RESOLVED` entity with `canonical_id == player_id`, display from the roster.
2. Unresolved / ambiguous / collision names → the correct `Abstention` code, no `EntityIdentity` built.
3. Blank `EventId` / blank-or-unparseable kickoff / conflicting kickoff → the correct event `Abstention`.
4. A past kickoff → `EVENT_PAST` abstention (and, end-to-end, the store refuses a future-turned-past event
   under the lock).
5. Missing roster / missing `player_id`|display columns → `ROSTER_UNAVAILABLE` (fail closed), no build.
6. Collision-audit shift: a name authoritative in one roster becomes ambiguous in the next → abstains.
7. The resolved `event_effective` is tz-aware UTC and equals the persisted `EventCommenceAtUTC` instant.
8. No fuzzy fallback: a near-miss name (one edit away) does NOT resolve — it abstains `NAME_UNRESOLVED`.
9. End-to-end: a `ResolvedObservationInput` feeds `capture_observation` and records exactly once; an
   `Abstention` never reaches the store.

## 9. Boundary

Design only. Building this is a new module + its QC, to be approved and landed BEFORE any 2D1 owner-only
route, flag, boundary module, or unit file. It performs **no paid fetch** (persisted artifacts only), holds
**zero authority**, and **abstains** rather than guess. 2D1 production routing stays blocked until this
adapter is **designed → approved → built** and wired behind the dark flag.

**STOP — returned for review.** No code, route, flag, schema edit, or deployment has been made.
