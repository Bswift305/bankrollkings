# Research Candidate — Slice 2D Integration Audit (READ-ONLY; Rev 2)

**Status: READ-ONLY AUDIT — Rev 2. Nothing enabled, deployed, or written.** Date 2026-10-31.
Rev 1 was the wiring map; Rev 2 freezes the reviewer's authority/operational boundaries and stages the
first production slice as **observation capture only (2D1)**. No code, flag, route, unit file, or
deployment is created here. Returned for review before any of that is implemented.

2A/2B/2C are closed: governed domain (`services/research_candidate.py`, 118 checks), the DB-enforced
local store (`services/research_candidate_store.py`, 52 checks) and its backup/restore/validation
(43 checks) are built, dark, and undeployed.

---

## 0. Rev 2 — frozen decisions (reviewer)

1. **Owner authorization is frozen:** `email in OWNER_EMAILS` **or** `role == "owner"`. **`is_admin`
   alone is INSUFFICIENT.** The `observer` is a **server-derived immutable account id** — never an email,
   never from the request payload.
2. **Explicit DB-path env var:** require an absolute **`BK_RESEARCH_CANDIDATE_DB_PATH`**; do **not** derive
   a default from `BK_RUNTIME_DIR`. Reject missing / relative / outside-approved-runtime paths. Never
   silently initialize the backup target. Securely create/verify the directory at `0700` and the live DB
   at `0600`.
3. **Pilot = observation capture only (2D1).** The first production slice exposes **only** owner-entered
   `record_observation` under the dark flag. `freeze_candidate` and `append_outcome` are **NOT** exposed
   until a later slice with their own input/authority contracts and production receipts.
4. **Observation input contract** (see §4) — server-derived clocks + canonical identity resolution +
   size-limited, schema-validated human thesis/sources + CSRF + an opaque caller idempotency token.
5. **Request-scoped connections:** open lazily after flag + auth pass, and close in `finally` per request.
   No per-worker retained connection until the worker/thread topology is separately proven safe.
6. **Tiered failure semantics** (see §7): OFF→404, unauthorized→the existing dark-feature response,
   invalid input→400/422, idempotency conflict→409, unhealthy store→calm 503. **No raw exception text** in
   any response.
7. **Tightened observability** (see §7): never log thesis, identity, email, sources, content hash, or full
   record identifiers — only a request correlation id, the operation kind, a coarse status, and a
   sanitized error code. Any health/count surface is **owner-only**.
8. **Retention/rollback do NOT imply deletion.** Daily/monthly retention windows are **not approved**; the
   backup operator records backup *creation* only and implements **no deletion policy**. Rollback
   **preserves** the database and backups — the operator is **not** told they may be removed while erasure
   remains undecided.
9. **The backup operator fails closed if the live store is absent:** it opens an **existing** store
   without initializing one, validates it, then backs it up. Missing / wrong-version / corrupt live state
   makes the unit **FAIL** — it never creates a new empty database.

---

## 1. Exact production call site (2D1: observation only)

**Today: none.** 2D1 would add exactly **one** owner-only, flag-gated call site: an authenticated POST that
constructs a `UserObservation` and calls `store.record_observation(obs, idempotency_key=...)`. Gated by
the dark flag (default OFF → `abort(404)`, the `DECISION_JOURNAL_ENABLED` pattern at `app.py:33822/33916`).
`freeze_candidate` / `append_outcome` / any `EvaluatedFinding` path are **not** wired in 2D1.

## 2. Dependency-free flag boundary + OFF-path zero-import

A tiny `services/research_candidate_boundary.py` mirroring `decision_shadow_boundary.py`:
`FLAG = "BK_RESEARCH_CANDIDATE_ENABLED"`, `enabled()` reads the env (unset ⇒ OFF), and the store (which
imports `sqlite3` + the domain module) is imported **lazily only inside the ON branch**. `app.py` imports
only this boundary (which imports just `os`). OFF ⇒ 404, zero import, no connection, no file.
**Acceptance:** a fresh interpreter with the flag OFF must not load `research_candidate_store` (the
`qc_nfl_ats_shadow.py` fresh-interpreter proof is the template).

## 3. Production DB path: explicit env var, ownership, permissions, backup operator

- **Path:** an absolute **`BK_RESEARCH_CANDIDATE_DB_PATH`** (no `BK_RUNTIME_DIR` derivation). The boundary
  validates it is **absolute, under the approved runtime root, and not relative** before use; a
  missing/relative/out-of-root value fails closed (feature unavailable). The store constructor already
  requires an explicit path and never defaults.
- **Ownership/permissions:** directory `0700`, live DB `0600`, owned by the app runtime user (`ubuntu` /
  the gunicorn user), never root; the directory is securely created/verified at `0700` at first ON use.
- **Backup operator:** a new `ops/bk-research-candidate-backup.{service,timer,sh}` mirroring
  `bk-decision-journal-backup.*`, **SSM-installed, not auto-installed**. Per §9 it opens the **existing**
  store (create=False / validate-first), validates, then `VACUUM INTO` a snapshot; it **records creation
  only** and applies **no deletion/retention policy** (§8). A missing/wrong-version/corrupt live store
  makes the unit fail, never initializes one.

## 4. Observation input contract (2D1)

- **Server-derived (never from the client):** `observer` (the authenticated immutable account id),
  `observed_at`, and `bk_captured` (server clocks, ET/UTC via `services/timeutils.py`).
- **Canonical identity:** the entity resolves through the sport-scoped resolver
  (`services/entity_links.py` discipline); the event resolves through the authoritative schedule/event
  source, and **`event_effective` comes from that canonical source, not user input**. Unresolved /
  ambiguous identity is **rejected** (not stored `UNKNOWN`), and a capture at or after `event_effective`
  is **rejected** at submission (the domain's pre-event rule, enforced early at the route).
- **Human-supplied, bounded:** `thesis` and `sources` are entered by the owner, **size-limited and
  schema-validated**, and **never fetched automatically**. Enforce a JSON body size cap and **CSRF**
  protection on the POST.
- **Idempotency:** a **caller-provided opaque token** (e.g. a client UUID) — **never** derived from thesis
  content or `case_identity`.

## 5. Process / concurrency topology (request-scoped)

gunicorn `preload_app=True`, 2 workers. For the low-volume pilot the store is opened **lazily per request,
after the flag and authorization pass, and closed in a `finally`** — **no retained per-worker connection**
until the exact worker/thread topology is separately proven safe. The store is never opened at
import/preload and never shared across forked workers. WAL + `BEGIN IMMEDIATE` + the durable
reservation/registry PK keep concurrent requests safe. OFF ⇒ no connection ever opened.

## 6. Identity source + authorization boundary

Identity from `load_users()` (`app.py:10542`) + the authenticated session. Authorization is **owner only**:
`email in OWNER_EMAILS` **or** `role == "owner"` (`app.py:1483/1486`); **`is_admin` alone is not accepted**.
The stored `observer` is the server-side immutable account id of that owner — not their email, not any
request field. Observer/thesis/sources live only in `observation_private` (pseudonymous/linkable, no
cross-user join).

## 7. Failure semantics + observability

- **Tiered responses, no raw exception text:** flag OFF → **404**; unauthorized → the existing
  dark-feature authorization response; invalid/oversized/unresolved input → **400/422**; idempotency
  conflict → **409**; a store that is unhealthy (schema/integrity/cleanup failure) or unavailable →
  calm **503**. The store's own `SchemaVersionError`/`StoreIntegrityError`/`CleanupError` map to 503 and
  are never echoed verbatim.
- **Observability (de-identified, owner-only surfaces):** logs carry **only** a request correlation id, the
  operation kind, a coarse status, and a sanitized error code. **Never** the thesis, observer id/email,
  sources, content hash, or a full record identifier. Any health/count surface is **owner-only**.

## 8. Retention + rollback (no deletion implied)

- **Backups record creation only.** No daily/monthly retention/pruning is implemented or claimed — that
  window is **not approved** (erasure/retention is the open §6/§10-Q4 legal question).
- **Rollback preserves data.** Disable = unset/`0` the flag (routes 404, zero import, no writes; restart
  for `preload_app`). Full rollback = `git revert` the 2D1 wiring commit. The DB and any backups are
  **preserved**, not removed — the operator is explicitly **not** told to delete them while erasure is
  undecided. The runtime DB is outside the checkout, so deploys never touch it.

## 9. Backup operator must fail if the live store is absent

The backup unit opens the live store **without initializing it** (existing-only / `create=False`-style
validate open), runs full validation (schema version + `integrity_check` + `foreign_key_check` + ledger/
reservation/tip reconcile + replay + hash re-verify), and only then snapshots it. A missing / wrong-version
/ corrupt live store makes the unit **exit non-zero (failed)** — it must **never** create a new empty
database at the backup or live path. (Implementation note: the store's `backup()` runs on an open store;
2D must route the operator through an existing-only open that fails closed, not the creating constructor.)

## 10. Confirmed out of scope for 2D1

No UI beyond a minimal owner-only form (API-first acceptable); **no evaluation engine**
(`SUPPORTED`/`UNSUPPORTED` stay unconstructible, fail closed); **no automatic thesis generation** (human
owner entries only); **no** `freeze_candidate`/`append_outcome`/finding path; no board/Green-Light/ranking/
ticket integration. The domain stays `RESEARCH_ONLY`, zero authority.

---

## 2D1 staged acceptance tests — observation-only capture (pass BEFORE the flag is turned on)

1. **OFF zero-import / zero-effect:** fresh interpreter, flag unset → the boundary loads without importing
   the store or its `sqlite3` usage; the POST route 404s; no DB file created; no connection opened.
2. **Authorization (frozen):** owner by `OWNER_EMAILS` or `role=="owner"` → accepted; **`is_admin`-only →
   rejected**; free/paid → rejected (dark-feature auth response). The stored `observer` equals the
   server-side account id (never the email or a payload field).
3. **Explicit DB path:** a missing / relative / out-of-approved-root `BK_RESEARCH_CANDIDATE_DB_PATH` →
   feature unavailable (no file created); a valid absolute path → dir `0700`, DB `0600` (POSIX).
4. **Input contract:** server sets `observer`/`observed_at`/`bk_captured`; entity/event resolved via the
   canonical resolvers (unresolved/ambiguous → 400/422); `event_effective` taken from the canonical
   source; a capture at/after `event_effective` → rejected; oversized/invalid thesis or sources → 400/422;
   missing CSRF → rejected; sources are never auto-fetched.
5. **Idempotency:** an opaque caller token — same token + same content → **noop (one row)**; same token +
   different content → **409**; the token is not derived from thesis content.
6. **Request-scoped connection:** each request opens the store after flag+auth and closes it in `finally`
   (no retained/shared connection); two concurrent owner requests get distinct `record_seq`, no duplicate.
7. **Tiered failures / no leakage:** OFF→404, unauthorized→auth response, invalid→400/422, conflict→409,
   unhealthy store→503; no response contains raw exception text; logs contain no thesis/identity/email/
   sources/hash/full-id — only correlation id, kind, coarse status, sanitized code.
8. **Backup operator fails closed:** with no live store (or a wrong-version/corrupt one), the unit FAILS
   and creates no empty DB; with a healthy live store it validates then snapshots (`0600`), recording
   creation only (no deletion/retention).
9. **Rollback preserves data:** after captures, flag OFF → routes 404, the DB and backups remain
   untouched; a deploy does not touch the runtime DB; nothing is deleted.
10. **No-engine / no-promotion / no-auto-thesis guard:** no wired path exposes `freeze_candidate`/
    `append_outcome`/finding construction; no `SUPPORTED`/`UNSUPPORTED` is constructible; no thesis is
    generated; no public/board surface references the feature.

**STOP — returned for review.** No production flag, route, write path, boundary module, unit file, UI,
evaluation engine, or deployment is implemented or enabled. This is Rev 2 of the wiring map and the 2D1
observation-only acceptance tests, for approval.
