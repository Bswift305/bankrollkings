# Research Candidate — Idempotency-Intent Registry (DESIGN ONLY, schema v3)

**Status: DESIGN ONLY — schema/trigger/API proposal + adversarial QC plan, for approval before any
code.** Date 2026-10-31. This is the second 2D1 prerequisite (the first is the identity/event adapter,
`docs/research_candidate_2d1_identity_feasibility.md`). No code, route, flag, or deployment here.

## Why a registry, not a per-observation column

A one-off `request_fingerprint` column on `observation_private` would (a) not generalize to the other
record kinds, (b) entangle idempotency with the frozen record row, and (c) still require the caller to
have allocated a `record_seq`/clocks before the check. A **governed idempotency registry** centralizes the
"same intent → same result, without re-allocating" guarantee and keys it on intent, not on the
server-generated sequence/clocks (the Rev-3 contradiction).

## Scope + fingerprint

- **Scope (the key):** `(record_kind, observer_id, idempotency_key)`.
  - `record_kind` ∈ the four kinds (2D1 uses only `observation`).
  - `observer_id` = the immutable account `UserId` (pseudonymous uuid — **not** email).
  - `idempotency_key` = the caller's **opaque** token. **No thesis text and no PII (email) ever appear in
    the key.**
- **Request fingerprint (stored as a sha256, never cleartext):** canonical hash over the **semantic
  intent** only —
  `{record_kind, observer_id, category, sub_label, entity_canonical_id, event_canonical_id,
  event_effective, thesis, sources(sorted), acted}` —
  and it **EXCLUDES** `record_seq`, `observed_at`, and `bk_captured`. Thesis participates in the *hash*
  (so a changed payload is detected) but its **text is never stored**; the registry stores only the digest.
- **Binding:** the registry row binds the resulting `record_id` + `record_seq`, so a repeat returns the
  original result without allocating anything.

## Proposed schema (SCHEMA_VERSION → 3; v2 rejected, no migration)

```sql
-- SCHEMA_VERSION = 3. A v2 store opens as an unsupported version -> SchemaVersionError, no migration
-- (nothing is deployed). (Also drops the 2B-era per-table idempotency_key UNIQUE in favor of the registry,
--  OR keeps it as a secondary guard — decided at implementation; the registry is authoritative.)

CREATE TABLE IF NOT EXISTS idempotency_registry (
  record_kind        TEXT NOT NULL CHECK (record_kind IN ('observation','candidate','outcome','finding')),
  observer_id        TEXT NOT NULL,                 -- immutable account UserId (pseudonymous), never email
  idempotency_key    TEXT NOT NULL,                 -- caller opaque token (no thesis/PII)
  request_fingerprint TEXT NOT NULL,                -- sha256 of the semantic intent (never cleartext thesis)
  bound_record_seq   INTEGER NOT NULL,              -- the result this key produced
  bound_record_id    TEXT NOT NULL,
  created_at         TEXT NOT NULL,                 -- tz-aware UTC
  PRIMARY KEY (record_kind, observer_id, idempotency_key),
  FOREIGN KEY (bound_record_seq) REFERENCES record_registry(record_seq)
);

-- write-once: the registry is append-only (a correction is a NEW key, never an edit of an existing one).
CREATE TRIGGER idempotency_registry_no_update BEFORE UPDATE ON idempotency_registry
BEGIN SELECT RAISE(ABORT, 'idempotency_registry is immutable'); END;
CREATE TRIGGER idempotency_registry_no_delete BEFORE DELETE ON idempotency_registry
BEGIN SELECT RAISE(ABORT, 'idempotency_registry is append-only'); END;
```

The `bound_record_seq` FK into `record_registry` ties every idempotency row to a real committed record;
the PK enforces one binding per `(kind, observer, key)`; the write-once triggers make the binding
immutable.

## Proposed API (store-owned; caller never pre-allocates a sequence)

A single governed capture entry point owns the whole flow so the check precedes allocation:

```
capture_observation(*, observer_id, category, sub_label, entity, event, event_effective,
                     thesis, sources, acted, idempotency_key) -> {status, record_id, record_seq}
```

Flow, in one `BEGIN IMMEDIATE` transaction:
1. `fp = _request_fingerprint(...)` over the semantic fields above (excludes seq + clocks).
2. look up `(record_kind='observation', observer_id, idempotency_key)` in `idempotency_registry`:
   - **found + fingerprint == stored** → return `{status:'noop', bound_record_id, bound_record_seq}` —
     **no `next_seq()`, no record insert**;
   - **found + fingerprint != stored** → raise `IdempotencyConflict` (route → 409);
   - **not found** → `next_seq()` (durable reservation) → set server clocks (tz-aware UTC) → build the
     `UserObservation` → persist it (record + `record_registry` bind + tips as in 2B) → insert the
     `idempotency_registry` row binding `(record_seq, record_id, fp)` → return `{status:'recorded', …}`.
3. corrections are a **new key** + an explicit `supersedes` on the record (never an edit of a registry
   row).

`record_observation(obs, idempotency_key)` (the 2B primitive) stays for tests/replay;
`capture_observation` is the governed 2D1 path. The fingerprint helper lives in the store (centralized,
deterministic, `canonical_json`-based) so no caller can diverge.

## Adversarial QC plan (to implement with the schema, before 2D1 routes)

1. **Exact retry → true no-op:** same scope + same fingerprint returns the original `record_id`/`seq`;
   assert **no new `record_seq` was allocated** (reservation count unchanged) and no second record row.
2. **Clocks/seq excluded:** two captures identical except for server clocks/sequence produce the **same
   fingerprint** → no-op (directly fixes the Rev-3 contradiction).
3. **Different fingerprint, same key → conflict:** same `(kind,observer,key)` with changed thesis/entity/
   event/event_effective/acted/sources → `IdempotencyConflict` (409); no record written.
4. **Scope isolation:** same `idempotency_key` under a different `observer_id`, or a different
   `record_kind`, are independent (both recorded).
5. **Correction path:** a correction uses a **new** key + `supersedes`; it is a new record, and the old
   binding is untouched (immutable).
6. **No PII in the registry:** assert the stored columns contain the opaque key + a 64-hex fingerprint +
   ids only — **never** thesis text or an email; the fingerprint is a digest, not cleartext.
7. **Write-once registry:** direct `UPDATE`/`DELETE` on `idempotency_registry` aborts.
8. **FK integrity:** a registry row cannot bind a `bound_record_seq` absent from `record_registry`;
   reopen `foreign_key_check` catches an orphan.
9. **v3 rejects v2:** opening a v2-schema store raises `SchemaVersionError` with **no migration and no
   mutation** (the AT test pattern, bumped to v3).
10. **Concurrency:** two connections, same `(kind,observer,key)` + same fingerprint, racing → exactly one
    record and one binding; both callers receive the **same** bound id (the registry PK + `BEGIN
    IMMEDIATE` serialize; the loser sees the committed binding and returns the no-op).

## Boundaries

Design only. Implementing this is a **store (2B-family) change** — schema v3 + triggers + the
`capture_observation` API + the adversarial QC — to be approved and landed **before** any 2D1 route,
flag, boundary, or unit file. No deletion/erasure is implied (the registry is append-only; erasure remains
the separately-governed open question). `SUPPORTED`/`UNSUPPORTED` remain unconstructible.

**STOP — returned for review.** No code, schema edit, route, flag, or deployment has been made.
