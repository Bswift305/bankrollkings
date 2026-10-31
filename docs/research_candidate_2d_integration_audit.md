# Research Candidate — Slice 2D Integration Audit (READ-ONLY; wiring map + acceptance tests)

**Status: READ-ONLY AUDIT — nothing enabled, deployed, or written.** Date 2026-10-31. Returned for
review before any production flag or write path is implemented.

2A/2B/2C are closed: the governed domain (`services/research_candidate.py`, 118 checks), the local
DB-enforced store (`services/research_candidate_store.py`, 52 checks) and its backup/restore/validation
(41→43 checks) are built, dark, and undeployed. 2D would wire the store into production **behind an OFF
flag**. This document maps that wiring against the codebase's existing dark-feature patterns and proposes
acceptance tests. **No code, flag, route, or write path is created here.**

---

## 1. Exact production call site that would create observations

**Today: NONE.** No route, job, or import anywhere constructs a `UserObservation`/`ResearchCandidate`/
`CandidateOutcome` or opens the store. The feature is inert.

**2D would add owner-only capture call sites, each flag-gated** (the `DECISION_JOURNAL_ENABLED` pattern:
`app.py:33822`, default OFF → the route `abort(404)` at `app.py:33916`):
- `record_observation` — an authenticated **owner/founder** submits an observation (entity, event,
  thesis, sources, acted) → the route builds a `UserObservation` and calls `store.record_observation(...)`.
- `freeze_candidate` / `append_outcome` — separate owner actions that promote an observation to a frozen
  candidate and later attach a measured outcome. Each is its own gated call site.
- **No other code path writes.** `EvaluatedFinding` is **not** produced by any route (it stays
  INCONCLUSIVE-only and fails closed, §9).

The call site touches **only** the dependency-free boundary (§2); it never imports the store directly.

## 2. Dependency-free flag boundary + OFF-path zero-import proof

Mirror `services/decision_shadow_boundary.py`: a tiny module (proposed `services/research_candidate_boundary.py`)
with `FLAG = "BK_RESEARCH_CANDIDATE_ENABLED"`, an `enabled()` that reads the env (unset ⇒ OFF), and a
guarded entry point that **lazily imports `research_candidate_store` only inside the ON branch**. `app.py`
imports **only** this boundary (which imports just `os`), never the store/`sqlite3`/domain module.
- OFF (default): the boundary returns immediately / the routes `abort(404)` — zero import, zero DB work,
  no connection opened, no file created.
- ON (local operator only): the boundary lazily imports the store and performs the owner-authorized write.

**Acceptance (zero-import):** in a fresh interpreter with the flag OFF, importing the boundary must leave
`services.research_candidate_store` and the feature's `sqlite3` usage **out of `sys.modules`** (the
`qc_nfl_ats_shadow.py` fresh-interpreter proof is the template).

## 3. Production DB path: ownership, permissions, directory, backup operator

- **Path:** `BK_RUNTIME_DIR/research_candidate/observations.db` (prod default `/var/lib/bankrollkings/
  research_candidate/observations.db`) — **outside** the git checkout (never OneDrive, never `data/`),
  matching `model_observations.py` / `decision_journal.py`. The store constructor **requires an explicit
  path** (no default), so the **boundary owns path resolution** from `BK_RUNTIME_DIR`; the store never
  guesses.
- **Permissions/directory:** directory `0700`, DB file `0600` (the store enforces `0600` on backups,
  POSIX-verified; the live DB's `0600` + the `0700` dir are the operator's responsibility at creation,
  like the Journal's `_ensure_dir` at `0700` / `chmod 0600`). Owner = the app runtime user (`ubuntu` /
  the gunicorn user), not root.
- **Backup operator:** a new **systemd unit set** `ops/bk-research-candidate-backup.{service,timer,sh}`
  mirroring `ops/bk-decision-journal-backup.*`, invoking `ResearchCandidateStore(path).backup(dest)` on a
  schedule with daily/monthly retention. **Installed on the box via SSM, NOT auto-installed** (like every
  other `bk-*` unit). It runs while the feature is dark and empty (consistent `VACUUM INTO`, never
  modifies the live DB).

## 4. User/account identity source + authorization boundary

- **Identity source:** the app membership store (`load_users()`, `app.py:10542`) + the authenticated
  session user.
- **Authorization:** **owner/founder only** (contract §10 Q2) using the existing predicate — `email in
  OWNER_EMAILS` **or** `role == 'owner'` **or** `is_admin` (`app.py:1483-1489`). A non-owner request is
  rejected (404 to match the dark pattern). The stored `observer` is the authenticated owner's id.
- **Privacy boundary:** observer identity + thesis + sources live **only** in `observation_private`; the
  research tables carry no observer column (pseudonymous/linkable via `observation_id`). No cross-user
  join; the account email never enters the research tables or logs (§7).

## 5. Idempotency-key and record_seq allocation ownership

- **`idempotency_key` — caller/route-owned, stable.** The route supplies an immutable capture-request id
  (e.g. a client-submitted request token, or a deterministic hash of the submitted payload + observer +
  client nonce). It is **not** `case_identity` (content/seq-dependent). Semantics are the store's: exact
  retry → noop; same key + different content → conflict (fail closed); correction → a new key + explicit
  `supersedes`.
- **`record_seq` — store-owned, durable.** The route calls `store.next_seq()` (durable reservation in its
  own committed txn) then builds the record with that seq; the record write claims it. Unclaimed
  reservations are permanent gaps. The registry PK + strict monotonic allocator make this safe under
  retries and multiple workers (§6).

## 6. Process / concurrency topology

- gunicorn `preload_app=True`, workers = `cpu_count` (2 on the t3.large). **The store must be opened
  LAZILY per worker on first ON request — never at import/preload and never shared across forked
  workers** (a shared SQLite connection across `fork()` is unsafe). Each worker holds its own connection
  to the one DB file.
- WAL + `BEGIN IMMEDIATE` + `busy_timeout` serialize writers; the durable `seq_reservation` + the
  `record_registry` PK guarantee no two workers ever claim the same `record_seq` (the two-connection
  acceptance test in 2B proves this). Writes are owner-rare; concurrent readers are unaffected.
- Flag OFF ⇒ no connection is ever opened in any worker.

## 7. Failure behavior + observability (no thesis/account leakage)

- **Fail closed:** `SchemaVersionError` / `StoreIntegrityError` / `CleanupError` disable the feature; the
  route returns a calm "unavailable" (never a 500 that leaks internals), exactly as the gate intends.
- **Observability = de-identified only.** Logs/metrics may carry `record_seq`, `kind`, `status`, counts,
  and `content_hash` — **never** the thesis text, observer id/email, sources, or any account data
  (mirrors the Journal's "sanitized summary, counts only, never contents", `run_scheduled_backup`). A
  health surface reports counts + last `record_seq` only.

## 8. Rollback procedure

- **Instant disable:** unset/`0` the `BK_RESEARCH_CANDIDATE_ENABLED` flag → routes `404`, no writes, no
  connection, zero import. (A restart is needed only because `preload_app` caches code, per CLAUDE.md §3.)
- **Full rollback:** `git revert` the 2D wiring commit; the DB file, being outside the checkout, is
  untouched by any deploy and can be archived or removed by the operator. There is **no migration to
  undo** (the store is additive and was dark).

## 9. Confirmation: no UI, no evaluation engine, no automatic thesis generation

- **No evaluation engine.** `SUPPORTED`/`UNSUPPORTED` remain unconstructible (fail closed with
  `EvaluationEngineNotGoverned`); 2D wires only capture (observation/candidate/outcome) + the
  INCONCLUSIVE path. The numeric §7 engine stays deferred and separately governed.
- **No automatic thesis generation.** Every observation is a **human owner** entry; the system never
  fabricates or suggests a thesis.
- **No UI implied.** 2D is the flag + owner-only capture endpoints (API-first; a minimal owner form at
  most). No public surface, no board/Green-Light/ranking/ticket integration (the domain is
  `RESEARCH_ONLY`, zero authority).

---

## Proposed 2D acceptance tests (to pass BEFORE the flag is ever turned on)

1. **OFF zero-import / zero-effect:** fresh interpreter, flag unset → importing the boundary does not load
   the store or its `sqlite3` usage; the capture routes `404`; no DB file created; no connection opened.
2. **Owner-only authorization:** flag ON, owner session → observation recorded; non-owner (free/paid/
   admin-not-owner per the policy) → rejected; the `observer` stored equals the authenticated owner id.
3. **Explicit prod path + perms:** the boundary resolves the path under `BK_RUNTIME_DIR`; a missing/empty
   path is refused by the store; POSIX dir `0700` / file `0600`.
4. **Idempotency:** same capture-request key + same payload → noop (one row); same key + different payload
   → conflict (fail closed); a correction uses a new key + `supersedes`.
5. **Concurrency:** two worker connections against one file → distinct `record_seq`, no duplicate, WAL;
   an unclaimed reservation remains a gap after a restart.
6. **Fail-closed + no leak:** a wrong-version / corrupted DB disables the feature (route "unavailable",
   not 500); assert logs contain no thesis/observer/email/sources — only seq/kind/status/hash/counts.
7. **Backup operator:** the timer runs `backup()` → a validated `0600` snapshot with retention; `restore()`
   to a NEW path validates; neither touches the live DB.
8. **Rollback:** after writes, flag OFF → routes `404`, data at rest unchanged; a deploy does not touch
   the runtime DB file.
9. **No-engine / no-auto-thesis guard:** no wired path can construct a `SUPPORTED`/`UNSUPPORTED` finding;
   no code generates a thesis; no public/board surface references the feature.

**STOP — returned for review.** No production flag, route, write path, UI, evaluation engine, backup unit,
or deployment is implemented or enabled. This is the wiring map and the acceptance tests for approval.
