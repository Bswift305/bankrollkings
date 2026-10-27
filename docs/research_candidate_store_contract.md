# Research Candidate — Dark-Store Contract (SLICE 2A → Rev 2; 2B AUTHORIZED)

**Status: Rev 2 — reviewer decisions frozen; 2B authorized under the boundary in §4.** Date 2026-10-27.
Rev 1 was the audit + recommendation; Rev 2 freezes the engine choice and corrects the privacy model,
idempotency, replay, deletion, and path-safety so they cannot conflict with the ledger's transactional
guarantees.

This slice began as a **read-only audit** of how Bankroll Kings persists governed records and a proposed
dark-store contract for the Research Candidate ledger (the four objects of
`docs/research_candidate_contract.md` Rev 2.1, implemented in `services/research_candidate.py` as
in-memory types in Slice 1).

**Boundary (unchanged):** the domain layer stays `RESEARCH_ONLY` with zero authority. 2B adds a local
schema + adapter only — **no** backup system, production path, feature flag, route, UI, job, deployment,
or deletion implementation (§4).

---

## 0. Rev 2 — frozen decisions (reviewer)

1. **Engine: SQLite-WAL.** Approved.
2. **One database file**, with logically separated **tables** (not two DB files): (a) private
   account/observation linkage, (b) de-identified research evidence, (c) the sequence allocator and
   schema metadata. One DB preserves a single `BEGIN IMMEDIATE` transaction, foreign keys, correction
   linkage, sequence allocation, consistent `VACUUM INTO` snapshots, and crash recovery. Two independent
   WAL databases **cannot** provide an atomic cross-store write, FK enforcement, or a consistent backup
   snapshot. If counsel later requires *physical* separation, that is a separately designed migration
   (outbox/saga + reconciliation receipts), **not** a transparent 2B option.
3. **Retention/deletion is UNDECIDED.** Do **not** encode "delete PII but retain tombstone/outcome" as
   approved behavior. In 2B: provide **no** account-erasure API; use **synthetic fixtures only**; document
   the future deletion transaction; **fail closed if deletion is requested.** Legal/privacy must decide
   whether de-identified measurements may survive account deletion.
4. **Do not refactor the Decision Journal backup code in 2B.** Backup/restore belongs to **2C**, and 2C
   first audits whether any extraction is behavior-preserving — never risk the existing production ledger
   merely to reduce duplication.
5. **Idempotency uses a caller-supplied immutable `idempotency_key`** (a stable capture-request id) per
   append — **not** `candidate.case_identity` (which includes content/sequence-dependent material and is
   not a stable retry key). Semantics: exact retry (same key + same content) → **no-op returning the
   existing record**; same key + different content → **conflict, fail closed**; genuine correction → a
   **new record with an explicit `supersedes`** (and its own new key).
6. **Replay follows `record_seq`** and validates ids, content hashes, supersession links and current
   tips. It must **not** use timestamps or a generic "newest wins" rule.
7. **Explicit path required.** The 2B repository constructor **requires** an explicit database path; tests
   use a temporary directory. It must **never** silently default to the checkout, OneDrive, `data/`, or a
   production runtime path.
8. **Privacy erasure vs immutability.** Ordinary records are update/delete-protected (DB triggers). A
   future approved erasure is an explicit **privileged transaction that produces an erasure receipt** —
   never an ordinary repository delete.

---

## 1. Audit — how BK stores records today

Two clearly separated storage tiers; the Research Candidate ledger belongs to the second.

### Tier A — regenerable / bulk data → files (CSV/JSON)
Boards, gamelogs, odds, scenario outputs (`bk_runtime.py`, `services/atomic_csv.py`):
- Runtime outputs live **outside** the git checkout (`BK_RUNTIME_DIR`; gitignored `.runtime/generated/`
  locally) — a git-tracked runtime file is reverted by the deploy's pre-pull clean (the deploy dirty-tree
  trap). **Atomic publish:** temp file → `fsync` → `os.replace`. **Read-path schema gates fail closed.**
  Caches keyed by mtime. Right for bulk, regenerable, non-authoritative data; **wrong** for a governed
  ledger (no atomicity across records, no referential integrity, no immutability enforcement).

### Tier B — governed, immutable, append-only, (often) user-linked ledgers → SQLite (WAL)
The established idiom for exactly this kind of record. Five live, dark/flag-gated examples under
`BK_RUNTIME_DIR` / `/var/lib/bankrollkings/<store>/` (outside the checkout):
`model_observations.py` (immutable pre-event snapshot + one later grade — the closest analogue),
`decision_journal.py` (user-linked append-only with frozen fields + correction linkage + backup/restore),
`kings_tickets_drafts.py`, `lookup_changes.py`, `trial_eligibility.py`.

**Shared conventions:** `journal_mode=WAL` · `foreign_keys=ON` · `synchronous=FULL` · `busy_timeout`;
`BEGIN IMMEDIATE` txns; a `schema_meta` version table that **fails closed** on an unknown version; DB-level
immutability via `BEFORE UPDATE … RAISE(ABORT, …)` triggers; idempotency via a `UNIQUE` key with a
duplicate insert returning a **noop**; `json.dumps(…, sort_keys=True)` + `hashlib` for deterministic
hashing; one-shot grading via `UPDATE … WHERE … IS NULL`; `PRAGMA integrity_check` + `foreign_key_check`
on open and in backup; `VACUUM INTO` backups with retention on a timer; verify-then-`os.replace` restore
clearing stale `-wal`/`-shm`; DB path outside the checkout, dir `0700`, file `0600`, env-overridable.

**Privacy / account identity today.** Account identity lives in the app's membership store
(`load_users()` in `app.py`, file-based). The Decision Journal keeps user-linked rows in its own DB,
reached only through a repository **scoped by the authenticated `user_id`**, never cross-joined.

---

## 2. Engine (approved) — SQLite-WAL, the Tier-B idiom

`model_observations.py` is nearly a drop-in template. Every property the contract needs — crash-atomic
append, DB-enforced immutability, correction/supersession linkage, idempotency, integrity checks, backup —
is already solved once in Tier B. CSV/JSON is for regenerable boards, not a governed ledger.

---

## 3. Dark-store contract (one DB, logically separated tables)

The store is a thin **persistence adapter** behind the frozen Slice-1 domain objects: it serializes and
reloads the *same* values and adds **no** authority, scoring, or logic the domain layer does not already
enforce. The semantic invariants (binding, lineage, fail-closed conclusions, summary reconciliation) are
the Slice-1 ones; the store adds **storage-level** enforcement on top.

**Table groups in the single DB:**
- **meta** — `schema_meta(version)` (fail closed on unknown); `seq_allocator(max_claimed)` (one row).
- **private (account/observation linkage)** — `observation_private`: the observer (account id), thesis,
  sources, entity/event, `acted`, timestamps, `record_seq`, `content_hash`, `idempotency_key`. This is the
  only place the observer↔observation linkage and the observer's authored text live.
- **de-identified research evidence** — `research_candidate`, `candidate_outcome`, `evaluated_finding`:
  the measurement (category, sub_label, canonical entity/event ids, temporal, baseline, endpoint,
  eligibility/invalidation, snapshots, states, summaries). These tables carry **no observer column**; a
  candidate references its observation by `observation_id` (the join key) and the observer/thesis are
  pulled from the private table on load. Findings expose aggregate, de-identified counts only.

Mapping to the ten required areas:

1. **Immutable records.** Every record table has a `BEFORE UPDATE … RAISE(ABORT)` trigger — records are
   write-once (corrections are new rows, never updates). Each row stores its `content_hash`; on load the
   object is rebuilt and its hash must match the stored one (tamper/corruption detection). Only
   `seq_allocator` is mutable.
2. **Store-wide sequence allocation.** A single `seq_allocator.max_claimed` row, read-and-advanced in the
   same `BEGIN IMMEDIATE` txn as each insert, so `record_seq` is strictly monotonic and never reused or
   regressed across process restarts (the Slice-1 `_max_claimed` persisted).
3. **Append-only correction linkage.** `supersedes` references the prior `record_seq`; candidate
   supersession is lineage-bound (same `observation_id`, prior must be current); outcomes form a version
   chain with one current; findings supersede by `record_seq`. FKs + the Slice-1 guards enforce it.
4. **Content hashes + schema version.** `schema_meta.version = SCHEMA_VERSION`; unknown → fail closed, no
   auto-migration. Canonical serialization (`canonical_json`) keeps hashes stable.
5. **Crash-safe / atomic transactions.** One `BEGIN IMMEDIATE` txn per write
   (`WAL`/`synchronous=FULL`/`foreign_keys=ON`/`busy_timeout`); partial writes roll back.
6. **Duplicate / idempotency.** A caller-supplied immutable `idempotency_key` (UNIQUE per table), per Rev-2
   decision 5: exact retry → noop returning the existing record; same key + different content →
   conflict/fail closed; a correction is a **new** record + explicit `supersedes` with its own key.
7. **Privacy separation.** The private table holds the account/observation linkage and authored text; the
   research tables hold only de-identified measurement, joined by `observation_id`. No cross-user join;
   findings are aggregate.
8. **Retention / deletion (UNDECIDED, Rev-2 decision 3).** 2B provides **no** erasure API and **fails
   closed** if deletion is requested; the future deletion transaction is documented only. No "delete PII,
   keep tombstone" behavior is encoded.
9. **Export / replay (Rev-2 decision 6).** Export = canonical rows in `record_seq` order. Replay re-applies
   rows **in `record_seq` order** through the Slice-1 validation engine, checking ids, content hashes,
   supersession links and current tips — **never** timestamps or "newest wins". A round-trip (persist →
   reopen → load) must reproduce identical `content_hash`es and current pointers.
10. **Corruption recovery / rollback.** `PRAGMA integrity_check` + `foreign_key_check` on open; on failure
    the store is **disabled (fail closed)**. Backup/restore is **2C**, not 2B (Rev-2 decision 4) — and 2C
    audits behavior-preserving extraction before touching any shared code.

**Erasure vs immutability (Rev-2 decision 8).** Ordinary records are update/delete-protected by the
triggers. A future erasure is a separate privileged transaction that produces an **erasure receipt**;
2B does not implement it and fails closed on any deletion request.

---

## 4. 2B — AUTHORIZED scope + reversible boundary

**Authorized now:** one **local** SQLite database, its schema, and the adapter; **synthetic fixtures only**.
QC gates to pass, then stop: **round-trip, idempotency, immutability, schema-gate, sequence, replay.**

**Explicitly NOT in 2B** (each a later, separately-approved slice): backup/restore system (2C), production
path, feature flag, route, UI, job, deployment, deletion/erasure implementation. The 2B repository
constructor **requires an explicit db path** (tests pass a temp dir); it never defaults to the checkout,
OneDrive, `data/`, or a runtime path.

**Later stages (not started):**
- **2C — integrity + backup/restore, local only.** First audit whether the Journal's
  backup/integrity/restore helpers can be extracted behavior-preservingly; QC corruption-fail-closed and
  restore. No prod presence.
- **2D — dark production store (separately approved).** DB path points at
  `BK_RUNTIME_DIR/research_candidate/…` behind an OFF feature flag (the `decision_journal`/`lookup_changes`
  dark pattern). Still no writer job, route, or UI.

**Reversibility:** the store is additive and isolated — revert = delete `services/research_candidate_store.py`
(+ its QC). The Slice-1 domain module and the rest of the tree are untouched; master/prod are unaffected
because nothing is wired until 2D's separate approval.

---

## 5. Resolved vs still-open
- **Resolved (Rev 2):** engine = SQLite-WAL; one DB with separated tables; idempotency = caller key;
  replay = record_seq; explicit path; erasure = future privileged transaction with a receipt.
- **Still open (for later approval):** the retention/deletion policy itself (§3.8, legal/privacy); whether
  2C extracts a shared backup util (§4). Neither blocks 2B.

**Contradiction check (Rev 2):** the two-file privacy split of Rev 1 is removed — the privacy boundary is
now table-level inside one DB, so the atomic cross-table write, FK enforcement, and consistent snapshot
hold. `case_identity` is no longer an idempotency key. No "delete PII, keep tombstone" is encoded.
Backup/restore is deferred to 2C. Replay is record_seq-ordered, not timestamp/newest-wins. No prod path,
flag, route, UI, job, deploy, or erasure is proposed for 2B.
