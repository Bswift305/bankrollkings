# Research Candidate — Dark-Store Contract (SLICE 2A, DESIGN ONLY)

**Status: DESIGN ONLY — returned for approval before anything is built.** Date 2026-10-27.

This slice does a **read-only audit** of how Bankroll Kings already persists governed records, then
proposes a **dark-store contract** for the Research Candidate ledger (the four objects of
`docs/research_candidate_contract.md` Rev 2.1, implemented in `services/research_candidate.py` as
in-memory types in Slice 1). It recommends a storage model **with its reasoning** and a **reversible
migration plan**, and stops for approval.

**Boundary (unchanged):** no route, UI, production data write, migration, deployment, scheduled job,
or numeric engine is proposed or created here. No storage technology is *chosen* — the recommendation
is for approval. The domain layer stays `RESEARCH_ONLY` with zero authority.

---

## 1. Audit — how BK stores records today

The codebase has **two clearly separated storage tiers**, and the Research Candidate ledger belongs
to the second.

### Tier A — regenerable / bulk data → files (CSV/JSON)
Boards, gamelogs, odds, scenario outputs. Conventions (`bk_runtime.py`, `services/atomic_csv.py`):
- **Runtime outputs live OUTSIDE the git checkout.** `BK_RUNTIME_DIR` on prod; the gitignored
  `.runtime/generated/` locally. A git-tracked runtime file is reverted by the deploy's pre-pull clean
  and silently un-freshes prod (the documented `cfb_line_moves.json` regression → the deploy dirty-tree
  trap). **Never write runtime data into the tracked tree.**
- **Atomic publish:** temp file in the same dir → `flush` → `os.fsync` → `os.replace` (`publish_json`,
  `write_csv_atomic`). A partial write is never visible; a failed write leaves the prior version intact.
- **Read-path schema gates fail closed:** a truncated/mixed-schema/hand-edited file returns the
  *unavailable* state rather than raising or admitting partial data (`validate_graded_schema`,
  `validate_manifest_schema`). No mutation/repair/refetch on read.
- **Caches keyed by mtime** (`_build_file_token`, `scenario_source_mtime`), never by `id(df)`.

This tier is right for large, regenerable, non-authoritative data. It is **wrong** for a governed
research ledger: file-per-record append is not crash-atomic, has no referential integrity, no
immutability enforcement, and no transactional correction linkage.

### Tier B — governed, immutable, append-only, (often) user-linked ledgers → SQLite (WAL)
This is the established idiom for exactly the kind of record a Research Candidate is. Five live
examples, all **dark / flag-gated** and all under `BK_RUNTIME_DIR` (or `/var/lib/bankrollkings/<store>/`,
outside the checkout):

| Store | File | Shape |
|---|---|---|
| `services/model_observations.py` | `model_observations/observations.db` | **immutable pre-event snapshot + one later grade** — the closest analogue to a candidate+outcome |
| `services/decision_journal.py` | `decision_journal/journal.db` | user-linked append-only tickets/legs with frozen fields + correction linkage + backup/restore |
| `services/kings_tickets_drafts.py` | `BK_RUNTIME_DIR/…` | per-user drafts, `SCHEMA_VERSION=2`, `schema_meta` version gate |
| `services/lookup_changes.py` | `lookup/changes.db` | immutable market-change store, `dedup_key` idempotency |
| `services/trial_eligibility.py` | `BK_RUNTIME_DIR/…` | per-account one-shot state |

**The shared SQLite conventions** (observed verbatim across these modules):
- **Pragmas:** `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=FULL` (durability for
  user/governed records), `busy_timeout`.
- **Transactions:** `BEGIN IMMEDIATE` … `COMMIT`/`ROLLBACK` (a context manager in the Journal). Writes
  are crash-atomic; a failed write rolls back.
- **Schema version:** a `schema_meta` table holds an integer `SCHEMA_VERSION`; on open, an unknown
  version **raises / fails closed** (`JournalUnavailable` / `RuntimeError`), never silently migrates.
- **Immutability enforced in the DB:** a `BEFORE UPDATE` trigger that `RAISE(ABORT, …)` when any frozen
  column changes (`observations_decision_immutable`). The app cannot mutate a frozen snapshot even by
  mistake.
- **Idempotency:** a `UNIQUE` `dedup_key` / `import_fingerprint`; a duplicate insert catches
  `IntegrityError` and returns a **noop**, not an error.
- **Determinism / hashing:** `json.dumps(…, sort_keys=True)` for stored JSON; `hashlib` for fingerprints;
  `uuid4` for surrogate ids.
- **One-shot grading:** `UPDATE … WHERE grade IS NULL` so a snapshot is graded at most once.
- **Integrity + recovery:** `PRAGMA integrity_check` + `PRAGMA foreign_key_check` on open and in
  backup/restore. On failure the store is **disabled (fail closed)**, not served partially.
- **Backup/retention:** `VACUUM INTO` a new file → verify BOTH integrity checks → `chmod 0600`; daily +
  monthly snapshots pruned to retention on a timer (`run_scheduled_backup`,
  `ops/bk-decision-journal-backup.sh`).
- **Restore:** verify the backup's integrity **first**, copy to a temp file, `os.replace` (atomic), then
  delete any stale `-wal`/`-shm` so the restored file is authoritative.
- **Filesystem posture:** DB path **outside** the checkout (never OneDrive, never the repo); dir `0700`,
  file `0600`; path overridable by env for tests.

### Privacy / account identity today
Account identity lives in the **app's membership store** (`load_users()` in `app.py`, file-based under
`data/`), **separate** from the dark SQLite ledgers. The Decision Journal keeps user-linked rows in its
own DB, reached only through `JournalRepository`, **scoped by the authenticated `user_id`** and never
cross-joined to other users. This is the separation the Research Candidate contract §6 already requires.

---

## 2. Recommendation (for approval) — follow the SQLite-WAL dark-store idiom

**Adopt the Tier-B SQLite-WAL pattern (the `model_observations.py` / `decision_journal.py` idiom) for
the Research Candidate ledger — not CSV/JSONL.** Reasoning, compared against project conventions:

| Need (contract) | SQLite WAL (Tier B) | JSONL append | CSV |
|---|---|---|---|
| Crash-atomic append | ✅ `BEGIN IMMEDIATE` txn | ⚠️ line append not fsync-atomic across multi-row writes | ❌ |
| Immutability enforced by the store | ✅ `BEFORE UPDATE` trigger | ❌ app-only | ❌ app-only |
| Correction/supersession linkage + one current | ✅ FKs + `record_seq` + indexes | ⚠️ hand-rolled scan | ❌ |
| Idempotency (`dedup_key` UNIQUE) | ✅ UNIQUE + IntegrityError→noop | ⚠️ scan to dedup | ⚠️ |
| Schema version gate | ✅ `schema_meta` + fail closed | ⚠️ per-line version field | ⚠️ |
| Integrity check / corruption detection | ✅ `PRAGMA integrity_check` | ❌ | ❌ |
| Backup/restore already solved | ✅ reuse Journal helpers verbatim | ❌ bespoke | ❌ bespoke |
| Privacy separation | ✅ separate DB(s) + scoped access | ⚠️ | ⚠️ |
| **Matches an existing BK idiom** | ✅ five live stores | ❌ none | ❌ (bulk only) |

CSV/JSON is the right tool for **regenerable bulk board data**, not a governed ledger. Every property
the contract demands — immutability, append-only correction linkage, idempotency, integrity, backup —
is already *solved once* in Tier B and reused across five stores. Re-deriving them on JSONL/CSV would be
new, unproven, bespoke code for guarantees SQLite gives for free. **The model-observation store is
nearly a drop-in template.**

> This is a recommendation, not a decision. If approval prefers a file-based ledger, §3 still defines
> the same contract; only the engine row changes, and the reversibility plan (§4) is unaffected.

---

## 3. Proposed dark-store contract (engine-agnostic; maps 1:1 to Slice-1 domain types)

The store is a thin **persistence adapter** behind the existing frozen domain objects. It serializes and
reloads the *same* `UserObservation` / `ResearchCandidate` / `CandidateOutcome` / `EvaluatedFinding`
values; it adds **no** authority, scoring, or logic the domain layer does not already enforce.

1. **Immutable records.** Observation, candidate (frozen before-event fields), outcome version, and
   finding rows are write-once. Enforced by a `BEFORE UPDATE` trigger on the frozen columns (SQLite),
   mirroring `observations_decision_immutable`. The row stores the domain object's **`content_hash`**;
   on reload the hash is recomputed and must match (tamper/corruption detection).
2. **Store-wide sequence allocation.** One strictly-monotonic `record_seq` across observations/
   candidates/outcomes/findings (Slice-1 `InMemoryResearchStore` already governs this). Persisted as a
   single allocator row updated in the same `BEGIN IMMEDIATE` txn as the insert, so a sequence is never
   reused and never regresses, even across process restarts.
3. **Append-only correction linkage.** `supersedes` foreign-keys the prior `record_seq`; candidate
   supersession is lineage-bound (same `observation_id`, prior must be current); outcomes form a version
   chain with exactly one current; findings supersede by `record_seq`. Enforced by FKs + a partial
   unique index on "current" rows. No `UPDATE`/`DELETE` of a superseded row.
4. **Content hashes + schema version.** Each row carries its `content_hash`; a `schema_meta` table holds
   `SCHEMA_VERSION`. On open, an unknown version **fails closed** (store disabled), never auto-migrates.
   Serialization is canonical (`canonical_json`, sorted keys, ISO-8601, no NaN/Inf) so hashes are stable.
5. **Crash-safe / atomic transactions.** Every public write is one `BEGIN IMMEDIATE` txn
   (`journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout`). A partial write rolls
   back; readers never see a half-written record.
6. **Duplicate / idempotency behavior.** A `UNIQUE dedup_key` per record kind (derived from the natural
   identity — e.g. a candidate's `case_identity`, a finding's `(family_key, supersedes)`); a duplicate
   insert returns a **noop**, not an error, matching `model_observations.capture`.
7. **Privacy separation between research evidence and account identity.** **Two stores, not one:**
   - a **private, user-scoped** store for `UserObservation` (observer id, thesis text, sources, `acted`
     + any Decision-Journal reference) — reached only through a repository that takes the authenticated
     user and scopes by it, like `JournalRepository`;
   - a **de-identified research** store for candidates/outcomes/findings, which carry the sport-canonical
     `entity_id`/`event_id` and the measurement, **not** the observer's identity or bet activity.
   The observer linkage lives only in the private store; findings expose **aggregate, de-identified**
   statistics only (contract §6). No cross-user join.
8. **Retention / deletion boundaries.** Per contract §6 (deferred, privacy/legal-dependent): deletion of
   a `UserObservation` removes the account linkage/PII from the private store, **excludes** the case from
   future evaluations, and retains only a **non-identifying tombstone + recount notice** in the research
   store so sample accounting stays honest. No de-identified outcome is retained for evaluation without
   an approved policy. The two-store split makes "remove PII, keep the honest count" a physical operation.
9. **Export / replay.** Export = the canonical-JSON rows (already the hashed form), newest-wins per
   current pointer. Replay is deterministic: re-inserting exported rows in `record_seq` order through the
   same adapter must reproduce identical `content_hash`es and the same current pointers — the Slice-1
   invariants make this a property test.
10. **Corruption recovery / rollback.** `PRAGMA integrity_check` + `foreign_key_check` on open and in
    backup; on failure the store is **disabled (fail closed)**, never served partial. Backup via
    `VACUUM INTO` + both integrity checks + `0600`, daily/monthly retention on a timer. Restore verifies
    the backup first, then `os.replace` (atomic) + clears stale `-wal`/`-shm`. These helpers are reused
    from the Journal, not re-written.

---

## 4. Reversible migration plan (for approval — nothing starts yet)

Staged, each stage dark and independently revertible; **no** route/UI/job/prod-write/migration/deploy in
any stage until a later, separately-approved stage explicitly adds it.

- **2B — adapter + schema, local only.** Add `services/research_candidate_store.py`: `schema_meta` +
  tables + immutability triggers + the two-store privacy split, and `save`/`load` that round-trip the
  Slice-1 domain objects. DB path resolves to a test/local dir by default (env-overridable), **never**
  `data/`, never the checkout. QC: a round-trip + replay property test proving reload reproduces hashes
  and current pointers, an immutability-trigger test, an idempotency (noop) test, a schema-version
  fail-closed test. No writer, no job, no flag wired to anything.
- **2C — integrity + backup/restore, local only.** Reuse the Journal's `VACUUM INTO`/integrity/restore
  helpers (or lift them into a shared util); QC the corruption-fail-closed and restore paths. Still no
  prod presence.
- **2D — dark production store (separately approved).** Only here does the DB path point at
  `BK_RUNTIME_DIR/research_candidate/…` on prod, behind an OFF feature flag (the
  `LOOKUP_CHANGE_ENABLED`/`decision_journal` dark pattern: flag OFF → nothing reads or writes). A backup
  timer unit (`ops/bk-…`) mirrors the Journal's. **No writer job, route, or UI** — those are later,
  separately-approved slices, exactly as the Decision Journal stayed dark after its store shipped.

**Reversibility at every stage:** the store is additive and isolated — revert = delete
`services/research_candidate_store.py` (+ its QC) and, in 2D, remove the OFF flag and the (empty) DB
directory. The Slice-1 domain module and the rest of the tree are untouched; master/prod are unaffected
because nothing is wired until 2D's separate approval.

---

## 5. Open questions for approval
1. **Engine:** approve SQLite-WAL (recommended, §2), or direct a file-based ledger?
2. **One DB with two schemas, or two DB files** for the privacy split (§3.7)? (Two files make the
   PII/evidence boundary a filesystem boundary; one DB is simpler to back up.)
3. **Retention/deletion (§3.8 / contract §6 Q4):** still deferred pending a legal decision — confirm the
   interim "remove PII, keep a non-identifying tombstone" is the 2B/2C behavior to encode.
4. **Shared backup util:** lift the Journal's backup/restore/integrity helpers into a shared module, or
   copy the pattern per store?

**STOP — returned for review.** No store, adapter, route, UI, job, migration, flag, or numeric engine
exists or is proposed to be built yet. This is an audit, a recommendation, and a reversible plan for
approval.
