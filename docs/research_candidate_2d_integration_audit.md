# Research Candidate — Slice 2D Integration Audit (READ-ONLY; Rev 3)

**Status: READ-ONLY AUDIT — Rev 3. Nothing enabled, deployed, or written to production; no route, flag,
or schema edit.** Date 2026-10-31. Rev 3 resolves the idempotency-intent contradiction, names the exact
account/identity/event provenance (and where it is **BLOCKED**), proves the existing-only backup path,
and freezes the remaining small details.

**Headline: 2D1 (observation-only capture) is BLOCKED from implementation** until a separately governed
NFL **identity + event adapter** exists (§4) and the idempotency **request-fingerprint** schema change is
landed in the store (§5). The account-observer provenance and the existing-only backup path are resolved.

2A/2B/2C remain closed and green: domain 118, store 52, backup/restore 50 (now incl. `backup_existing`).

---

## 0. Frozen decisions

**From Rev 2 (unchanged):** owner auth = `OWNER_EMAILS` or `role=="owner"` (`is_admin` alone insufficient);
observer = server-derived immutable account id; explicit absolute DB-path env var; pilot = observation
capture only; server-derived clocks + canonical identity; request-scoped connections; tiered failures;
de-identified observability; retention/rollback imply no deletion; backup fails closed if the live store
is absent.

**New in Rev 3:**
1. **Idempotency keys on a stable request FINGERPRINT, not the content hash** (§5). The fingerprint covers
   the semantic intent and EXCLUDES the server-generated `record_seq` and capture clocks. **This requires
   a store schema change** (a `request_fingerprint` column) and a `SCHEMA_VERSION` bump to **3**,
   implemented + QC'd as a store (2B-family) change **before** any 2D1 code. Deferred here (no schema edit
   in this rev).
2. **Entity/event identity for 2D1 is BLOCKED** (§4): no existing runtime path provides an authoritative
   player id, canonical display, event id, kickoff, and ambiguity/missing-event behavior. 2D1 waits on a
   separately governed identity/event adapter. No name-based inference; no user-supplied kickoff.
3. **Unauthorized dark-route response = 404** (not 401/403) — never reveal the feature's existence.
4. **Server clocks are timezone-aware UTC** (`services/timeutils.py`); `event_effective` comes from the
   canonical event source, also tz-aware.
5. **Approved-root validation uses RESOLVED paths** (`os.path.realpath`) and a `commonpath` containment
   check, and **rejects symlink escapes**; the **approved root's configuration source is explicit** (its
   own env var, e.g. `BK_RESEARCH_CANDIDATE_ROOT`), never another inferred default.
6. **Existing-only backup is PROVEN** (§9): `mode=ro` `VACUUM INTO` works locally, and the store now has a
   `backup_existing` entry point that opens the source read-only (create=False, fail-closed) and cannot
   initialize or mutate the live store.

---

## 1. Call site (2D1: observation only)
One owner-only, flag-gated POST building a `UserObservation` → `store.record_observation(...)`. OFF ⇒
`abort(404)`. `freeze_candidate`/`append_outcome`/finding paths are not wired in 2D1.

## 2. Dependency-free flag boundary + OFF zero-import
`services/research_candidate_boundary.py` (mirror `decision_shadow_boundary.py`): `FLAG =
"BK_RESEARCH_CANDIDATE_ENABLED"`; store imported lazily only when ON; `app.py` imports only the boundary
(`os` only). OFF ⇒ 404, zero import, no connection, no file. Proven by a fresh-interpreter test.

## 3. Production DB path (explicit env + resolved-root containment)
- **`BK_RESEARCH_CANDIDATE_DB_PATH`** — absolute, required, no `BK_RUNTIME_DIR` derivation.
- **Approved-root containment:** the resolved (`realpath`) DB path must live under the resolved approved
  root from its **own explicit env var `BK_RESEARCH_CANDIDATE_ROOT`** (not inferred). Validation uses
  `os.path.commonpath([realpath(db), realpath(root)]) == realpath(root)` and **rejects symlink escapes**;
  a relative / missing / out-of-root / symlinked-out path fails closed (feature unavailable).
- **Perms:** dir `0700`, DB `0600`, app-user owned; securely created/verified at first ON use.
- **Backup operator:** `ops/bk-research-candidate-backup.*` (SSM-installed, not auto) calling
  `backup_existing` (§9); records creation only, no deletion/retention (§8).

## 4. Account / identity / event provenance — RESOLVED vs BLOCKED

**Observer (account id) — RESOLVED.** `UserId` is assigned once at signup as `uuid4().hex`
(`app.py:41587`) and read as `current_user['user_id']`. It is random (NOT email-derived) and immutable: no
code path reassigns `UserId` (email/password reset flows change those fields, never `UserId`); it is the
stable account key. **The observer is set server-side from this id**, never from email or the payload.

**NFL player + event identity — BLOCKED.** The first pilot is scoped to **NFL player observations**, which
require five authoritative facts. Current state:

| Needed | Exists? | Where / gap |
|---|---|---|
| Immutable player id | ❌ runtime | `player_id` exists only **build-time** in `build_nfl_player_stats_from_pbp.py` / `NFL_GameLogs.csv`; there is NO runtime function mapping an owner's input to a stable id. `services/entity_links.py` is a URL/link resolver, **not** authoritative identity. |
| Canonical display identity | ⚠️ build-time | `player_display_name` in the gamelogs; no runtime canonical-name resolver. |
| Event id | ❌ | No governed NFL event-id scheme (only synthetic `nfl_ats_fixtures.event_id`). |
| Authoritative kickoff | ❌ | Only odds-derived `CommenceTime` (UTC) on the **current slate** (`app.py:7724` etc.) — slate-bound and provider-derived, not an authoritative per-event schedule kickoff. |
| Ambiguity / missing-event behavior | ❌ | No runtime resolver, so no defined ambiguous/missing handling. |

**Conclusion:** no existing path provides all five as a runtime, authoritative, ambiguity-handling
resolver. **2D1 is blocked on a separately governed NFL identity+event adapter** that returns an immutable
player id, a canonical display, a governed event id, an authoritative kickoff (distinct from odds
`CommenceTime`), and explicit unresolved/ambiguous/missing-event behavior. **No name-based inference and no
user-supplied kickoff are permitted.**

## 5. Idempotency-intent contract (fixes the retry→409 contradiction)

**Problem:** `record_seq`, `observed_at`, `bk_captured` are generated per request and feed the observation
`content_hash`; so an exact retry (same token + same payload) would produce a different hash and 409, not
a no-op.

**Contract:** idempotency is keyed on a **stable request fingerprint** computed BEFORE allocating a
sequence or clocks, over exactly:
- the authenticated immutable observer id;
- the validated client intent (category/sub_label);
- the resolved **canonical** entity and event identity;
- the canonical `event_effective`;
- the human `thesis`, `sources`, and `acted` state.

It **excludes** the server-generated `record_seq`, `observed_at`, and `bk_captured`. The store stores
`(idempotency_key, request_fingerprint)`; on a repeat key it compares fingerprints: **same fingerprint →
return the original record (no-op)**; **different fingerprint → 409**. The store owns setting the clocks +
sequence after the idempotency decision.

**Schema impact (must land first):** this adds a `request_fingerprint` column to `observation_private`
(and the canonical-form hash input) — a **`SCHEMA_VERSION` bump to 3**. It is a **store (2B-family) change
with its own QC**, to be implemented and approved **before** any 2D1 route code. Not done in this rev.

## 6. Authorization boundary
Owner only: `email in OWNER_EMAILS` **or** `role == "owner"` (`app.py:1483/1486`); **`is_admin` alone is
rejected.** Unauthorized ⇒ **404** (dark). `observer` = the server-side `UserId` (§4).

## 7. Failure semantics + observability
Tiered, no raw exception text: OFF→404, unauthorized→**404**, invalid/oversized/unresolved→400/422,
idempotency conflict→409, unhealthy/unavailable store→calm 503 (the store's Schema/Integrity/Cleanup
errors map to 503). Logs carry only a request correlation id, operation kind, coarse status, and a
sanitized error code — **never** thesis, identity, email, sources, content hash, or a full record id. Any
health/count surface is **owner-only**.

## 8. Retention + rollback (no deletion)
Backups record creation only; no retention/pruning (not approved). Rollback = flag OFF (zero import) +
`git revert`; the DB and backups are **preserved**, never removed (erasure undecided); the runtime DB is
outside the checkout, untouched by deploys.

## 9. Existing-only backup — PROVEN
A local probe confirmed `VACUUM INTO` succeeds on a `mode=ro` connection. The store now exposes
**`backup_existing(src, dest)`** (committed with 2C): it opens the source with `create=False` (read-only;
fails closed with `SchemaVersionError` on a missing/empty/wrong-version/corrupt source and **never creates
a DB**), then runs the validated consistent-snapshot `backup()` (temp → full validation → fsync → 0600 →
atomic no-overwrite publish → dir-fsync). QC proves: a healthy store backs up without mutating the live
bytes; a missing or wrong-version live store fails closed and creates no file. The operator unit calls
`backup_existing` and **fails (exit non-zero)** on any unhealthy/absent live store.

## 10. Out of scope for 2D1
No UI beyond a minimal owner-only form; no evaluation engine (`SUPPORTED`/`UNSUPPORTED` stay
unconstructible); no automatic thesis generation; no `freeze_candidate`/`append_outcome`/finding path; no
board/Green-Light/ranking/ticket integration. `RESEARCH_ONLY`, zero authority.

---

## 2D1 prerequisites (must be approved/landed BEFORE any route code)
1. A separately governed **NFL identity+event adapter** (§4) providing all five authoritative facts.
2. The **`request_fingerprint` store change + `SCHEMA_VERSION` 3** (§5), implemented + QC'd.

## 2D1 staged acceptance tests (observation-only; run before the flag is turned on)
1. OFF zero-import / zero-effect (fresh interpreter; 404; no file/connection).
2. Authorization: owner (`OWNER_EMAILS`/`role=="owner"`) accepted; `is_admin`-only and non-owner → **404**;
   `observer` equals the server-side `UserId`, never email/payload.
3. Explicit DB path: missing/relative/out-of-`BK_RESEARCH_CANDIDATE_ROOT`/symlink-escape → unavailable (no
   file); valid absolute, resolved-contained path → dir `0700`, DB `0600`.
4. Input contract: server sets observer/`observed_at`/`bk_captured` (tz-aware UTC); entity+event via the
   governed adapter (unresolved/ambiguous → 400/422); `event_effective` from the adapter; capture at/after
   `event_effective` → rejected; oversized/invalid thesis/sources → 400/422; missing CSRF → rejected;
   sources never auto-fetched.
5. **Idempotency-intent:** same opaque token + same request fingerprint → **no-op (one row)**; same token +
   different fingerprint → **409**; the fingerprint excludes `record_seq`/`observed_at`/`bk_captured`.
6. Request-scoped connection: opened after flag+auth, closed in `finally`; two concurrent owner requests →
   distinct `record_seq`, no duplicate.
7. Tiered failures / no leakage: 404 / 404 / 400-422 / 409 / 503; no raw exception text; logs carry only
   correlation id, kind, coarse status, sanitized code.
8. Backup operator fails closed on an absent/wrong-version/corrupt live store; a healthy store yields a
   validated `0600` snapshot (creation recorded, no deletion/retention).
9. Rollback preserves data: flag OFF → 404, DB + backups untouched; deploy does not touch the runtime DB.
10. No-engine / no-promotion / no-auto-thesis guard.

**STOP — returned for review.** No production flag, route, write path, boundary module, unit file, UI,
evaluation engine, schema edit, or deployment is implemented or enabled. 2D1 stays blocked pending the two
prerequisites above.
