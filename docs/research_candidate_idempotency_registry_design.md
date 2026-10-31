# Research Candidate — Idempotency-Intent Registry (Rev 2.1 — BUILT local schema v3)

**Status: BUILT (schema v3), LOCAL ONLY. Approved Rev 2.1 implemented in `services/research_candidate_store.py`
with QC in `qc_research_candidate_idempotency.py` (14/14) + migrated `qc_research_candidate_store.py` /
`qc_research_candidate_backup.py`.** Date 2026-10-31. Still a 2D1 prerequisite satisfied at the STORE layer
only — no route, flag, boundary, unit file, UI, or deploy; the identity/event adapter
(`docs/research_candidate_2d1_identity_feasibility.md`) remains the other, still-blocked, prerequisite. The
sections below are the as-built contract.

Rev 2 fixed the nested-transaction impossibility, bound the registry to the real record in the DB, froze
the old per-table idempotency constraint, removed observation-correction semantics, narrowed the
fingerprint, and corrected privacy wording. **Rev 2.1** closes the last contradiction: since v3 drops
`observation_private.idempotency_key`, **every stored observation must have exactly one registry binding**
— so the raw SQL observation writer becomes internal-only, the registry enforces one key per observation,
and reopen reconciles observation ↔ registry **both directions** and fails closed on any unbound
observation.

## Why a registry (unchanged)

A governed `idempotency_registry` keyed on intent, not on the server-generated sequence/clocks, so an
exact retry returns the original result **without allocating a sequence**, and a changed payload
conflicts. Centralized so the rule cannot diverge per call site.

## Rev 2 frozen decisions

1. **No nested transactions.** `capture_observation()` opens **one** `BEGIN IMMEDIATE` and uses
   **internal, transaction-participating primitives** — `_reserve_seq_in_txn()` and
   `_insert_observation_in_txn()` — that do **not** begin their own transaction. The public `next_seq()` /
   `record_observation()` (each of which begins its own txn) are **not** called inside the capture txn.
2. **The registry is bound to the real record in the DB** (composite FK + triggers, below): a registry row
   cannot name a mismatched kind, id, or observer.
3. **The registry is authoritative; the old per-table idempotency constraint is removed in v3 — for
   `observation_private` ONLY.** The 2B global `observation_private.idempotency_key UNIQUE` is dropped (two
   observers may legitimately use the same opaque token — the registry scopes by `observer_id`); the
   `idempotency_key` for observations lives **only** in the registry. The `candidate`/`outcome`/`finding`
   tables keep their existing `idempotency_key` columns **unchanged** until each is separately migrated to
   the registry.

**New in Rev 2.1 — every observation is bound exactly once:**
7. **The raw SQL observation writer is INTERNAL-only.** There is **no public** `record_observation(obs,
   key)` that could insert an observation without a governed registry binding. The only sanctioned write
   path is `capture_observation()`, which inserts the observation and its registry row in the **same**
   transaction. `_insert_observation_in_txn()` is internal.
8. **One key per observation:** `idempotency_registry` adds **`UNIQUE(bound_record_seq)`** so two keys
   cannot bind one observation.
9. **Both-direction reconcile on reopen (fail closed):** every `observation_private` row must have exactly
   one `idempotency_registry` binding, and every observation registry row must bind an existing
   `observation_private(observer, id, seq)`. A direct-SQL observation left unbound (or double-bound) is
   detected on reopen and disables the store. Replay/tests use `capture_observation()`; **replay needs no
   SQLite writer** (it reconstructs state from reads via the in-memory engine).
4. **No observation correction semantics.** `UserObservation` has **no** `supersedes` field; a new
   idempotency_key creates a **distinct, independent observation**, not a correction. Observation
   correction/supersession stays **deferred** until its own lineage contract exists.
5. **Fingerprint covers only PERSISTED observation intent**, taken from canonical objects (no invisible
   fields): `observer_id`, `EntityIdentity`, `EventIdentity` (its `event_effective` included), `thesis`,
   `sources`, `acted`. **`category`/`sub_label` are NOT part of the observation contract** (they belong to
   candidate promotion, deferred) and are excluded. The API accepts the canonical `EntityIdentity` /
   `EventIdentity` **objects** (not loose id + event-effective args), preventing cross-field mismatch.
6. **Privacy wording corrected:** the registry holds **pseudonymous/linkable** data — a `UserId` and a
   thesis-derived digest — it contains **no direct email and no cleartext thesis**, and remains
   privacy-governed. (Not "no PII".)

## Canonicalization (frozen)

- **Strings** (thesis, sources, display) are **Unicode NFC-normalized** before hashing
  (`unicodedata.normalize("NFC", s)`).
- **Timestamps** serialize as **tz-aware UTC ISO-8601** (`event_effective` from `EventIdentity`).
- **Sources** are a **set**: deduplicated and **sorted** before hashing, so order does not change identity.
- The fingerprint is `sha256(canonical_json({...}))` using the existing deterministic `canonical_json`
  (sorted keys, no NaN/Inf, string keys). It is a **digest**, never cleartext thesis.

## Scope + fingerprint

- **Scope (key):** `(record_kind, observer_id, idempotency_key)`. `observer_id` = the immutable account
  `UserId` (pseudonymous uuid, never email); `idempotency_key` = the caller's opaque token (no thesis/PII).
- **Fingerprint (stored as a 64-hex digest):** over `{record_kind, observer_id,
  entity=EntityIdentity.canonical_dict(), event=EventIdentity.canonical_dict() (incl. event_effective),
  thesis(NFC), sources(NFC, sorted-unique), acted}` — **excluding** `record_seq`, `observed_at`,
  `bk_captured`.

## Proposed schema (SCHEMA_VERSION → 3; v2 rejected, no migration)

```sql
-- SCHEMA_VERSION = 3. Opening a v2 store -> SchemaVersionError (no migration, no mutation; undeployed).
-- v3 also DROPS observation_private.idempotency_key and its UNIQUE (the registry is authoritative, decision 3),
-- and adds a composite-unique on record_registry so the registry can bind to it by (seq, kind, id).

-- record_registry gains the composite UNIQUE needed as a FK target:
--   UNIQUE (record_seq, kind, record_id)   -- trivially unique (record_seq is PK); enables the FK below

CREATE TABLE IF NOT EXISTS idempotency_registry (
  record_kind         TEXT NOT NULL CHECK (record_kind = 'observation'),   -- 2D1: observations ONLY
  observer_id         TEXT NOT NULL,                 -- immutable account UserId (pseudonymous), never email
  idempotency_key     TEXT NOT NULL,                 -- caller opaque token (no thesis/PII)
  request_fingerprint TEXT NOT NULL,                 -- sha256 of persisted semantic intent (never cleartext)
  bound_record_seq    INTEGER NOT NULL,
  bound_record_id     TEXT NOT NULL,
  created_at          TEXT NOT NULL,                 -- tz-aware UTC
  PRIMARY KEY (record_kind, observer_id, idempotency_key),
  UNIQUE (bound_record_seq),                          -- one key per observation (Rev 2.1 decision 8)
  FOREIGN KEY (bound_record_seq, record_kind, bound_record_id)
      REFERENCES record_registry(record_seq, kind, record_id)             -- binds kind + id + seq (decision 2)
);
-- NOTE (decision 3): v3 drops observation_private.idempotency_key + its UNIQUE; candidate/outcome/finding
-- keep their idempotency_key columns UNCHANGED until separately migrated.

-- observer binding: for an observation, the bound record must be an observation_private row whose
-- observer equals this registry row's observer_id. Future record_kinds are refused until they declare a
-- governed lineage-to-observer binding (the CHECK above already restricts 2D1 to 'observation').
CREATE TRIGGER idempotency_registry_observer_bind BEFORE INSERT ON idempotency_registry
WHEN NEW.record_kind = 'observation' AND NOT EXISTS (
  SELECT 1 FROM observation_private o
  WHERE o.record_seq = NEW.bound_record_seq AND o.observation_id = NEW.bound_record_id
    AND o.observer = NEW.observer_id)
BEGIN SELECT RAISE(ABORT, 'idempotency row does not bind a matching observation_private(observer, id, seq)'); END;

-- write-once: a correction is a NEW key, never an edit of an existing binding.
CREATE TRIGGER idempotency_registry_no_update BEFORE UPDATE ON idempotency_registry
BEGIN SELECT RAISE(ABORT, 'idempotency_registry is immutable'); END;
CREATE TRIGGER idempotency_registry_no_delete BEFORE DELETE ON idempotency_registry
BEGIN SELECT RAISE(ABORT, 'idempotency_registry is append-only'); END;
```

The composite FK ties `(seq, kind, id)` to a real `record_registry` row; the observer-bind trigger ties
`observer_id` to the actual `observation_private.observer`; the `CHECK(record_kind='observation')` keeps
other kinds out of the registry until each declares its own observer lineage.

## Proposed API (store-owned; single transaction; canonical objects)

```
capture_observation(*, observer_id, entity: EntityIdentity, event: EventIdentity,
                    thesis, sources, acted, idempotency_key) -> {status, record_id, record_seq}
```

One `BEGIN IMMEDIATE` txn:
1. `fp = _request_fingerprint(observer_id, entity, event, thesis, sources, acted)` (NFC + sorted sources;
   excludes seq/clocks).
2. look up `('observation', observer_id, idempotency_key)`:
   - **found + fingerprint == stored** → return the bound `record_id`/`record_seq` — **no reservation, no
     insert**;
   - **found + fingerprint != stored** → raise `IdempotencyConflict` (route → 409);
   - **not found** → `_reserve_seq_in_txn()` (durable reservation, no nested BEGIN) → set tz-aware UTC
     clocks → build the `UserObservation` → `_insert_observation_in_txn()` (record + `record_registry`
     bind + tips, no nested BEGIN) → insert the `idempotency_registry` row → return.
3. A new `idempotency_key` yields a **distinct observation**; it is **not** a correction (decision 4).

There is **no public raw observation writer** (Rev 2.1 decision 7): `_reserve_seq_in_txn()` and
`_insert_observation_in_txn()` are internal and transaction-participating, used only by
`capture_observation`. The old `record_observation(obs, key)` SQL primitive is removed as a public API so
nothing can insert an observation without a registry binding. `next_seq()` (own-txn) remains for the
operator/standalone reservation only. **All normal tests use `capture_observation`; replay reconstructs
state from reads via the in-memory engine and needs no SQLite writer.**

**Reopen reconcile (both directions, fail closed — Rev 2.1 decision 9):**
```sql
-- (a) every observation is bound exactly once:
SELECT COUNT(*) FROM observation_private o
 WHERE NOT EXISTS (SELECT 1 FROM idempotency_registry r
                   WHERE r.record_kind='observation' AND r.bound_record_seq=o.record_seq);   -- must be 0
-- (b) every observation registry row binds a real observation (observer/id/seq):
SELECT COUNT(*) FROM idempotency_registry r WHERE r.record_kind='observation' AND NOT EXISTS (
   SELECT 1 FROM observation_private o
   WHERE o.record_seq=r.bound_record_seq AND o.observation_id=r.bound_record_id
     AND o.observer=r.observer_id);                                                           -- must be 0
```
Either nonzero ⇒ `StoreIntegrityError` (store disabled). `UNIQUE(bound_record_seq)` already prevents two
keys binding one observation.

## Adversarial QC plan (implement with the schema, before 2D1 routes)

1. **No nested transaction:** `capture_observation` completes within a single `BEGIN IMMEDIATE` (assert no
   "cannot start a transaction within a transaction" and that `_reserve_seq_in_txn`/
   `_insert_observation_in_txn` issue no `BEGIN`).
2. **Exact retry → true no-op:** same scope + same fingerprint returns the original id/seq; **no new
   reservation consumed**, no second record.
3. **Clocks/seq excluded:** two captures differing only in server clocks/seq → same fingerprint → no-op.
4. **Different fingerprint, same key → 409** (no record written).
5. **Two observers, same token:** independent records (scope includes `observer_id`) — the dropped
   per-table UNIQUE no longer collides them.
6. **Mismatched kind/id/observer rejected by the DB:** a registry row whose `(bound_record_seq, kind,
   bound_record_id)` is not in `record_registry` → FK error; whose `observer_id` ≠
   `observation_private.observer` → the observer-bind trigger aborts; `record_kind != 'observation'` →
   CHECK/trigger aborts.
7. **No observation supersession:** `UserObservation` exposes no `supersedes`; a new key makes a distinct
   observation, and there is no correction path.
8. **Invisible-field rejection:** the fingerprint inputs are a subset of PERSISTED `UserObservation`
   fields — `category`/`sub_label` are absent from capture and the fingerprint.
9. **No cleartext PII:** the registry stores an opaque key, a 64-hex digest, ids, and a UTC timestamp —
   never an email or thesis text; privacy-governed (pseudonymous/linkable).
10. **Write-once + v3 gate:** `UPDATE`/`DELETE` on the registry abort; a v2-schema store opens as
    `SchemaVersionError` with no migration/mutation.
11. **Concurrency:** two connections racing the same scope+key+fingerprint → exactly one record + one
    binding; both callers get the same bound id (PK + `BEGIN IMMEDIATE` serialize).
12. **Observation without a registry row (Rev 2.1):** a direct-SQL `observation_private` insert with no
    matching registry row → reopen reconcile (a) fails closed (`StoreIntegrityError`); no public writer can
    produce this state.
13. **Two keys targeting one observation (Rev 2.1):** a second `idempotency_registry` row with the same
    `bound_record_seq` → `UNIQUE(bound_record_seq)` violation.
14. **Legacy-key scope (Rev 2.1):** only `observation_private` loses its `idempotency_key` in v3;
    `candidate`/`outcome`/`finding` retain theirs unchanged (asserted on the v3 schema).

## Boundaries

Design only — implementing this is a **store (2B-family) change** (schema v3 incl. dropping the old
per-table idempotency column, the composite FK + observer-bind triggers, the internal txn primitives, the
`capture_observation` API, and the adversarial QC) to be approved and landed **before** any 2D1 route,
flag, boundary, or unit file. No deletion/erasure implied. `SUPPORTED`/`UNSUPPORTED` remain unconstructible.

**BUILT (local schema v3).** Implemented in `services/research_candidate_store.py` (SCHEMA_VERSION=3,
`idempotency_registry` + observer-bind/write-once triggers, `capture_observation` + the internal
`_reserve_seq_in_txn`/`_insert_observation_in_txn`, `_request_fingerprint`, both-direction reopen
reconcile; `observation_private` lost its legacy `idempotency_key`; candidate/outcome/finding unchanged).
QC: `qc_research_candidate_idempotency.py` runs all fourteen cases green; `qc_research_candidate_store.py`
and `qc_research_candidate_backup.py` were migrated to `capture_observation` and pass. No route, flag,
boundary, unit file, UI, or deployment was made; v1/v2 stores fail closed with no migration.
