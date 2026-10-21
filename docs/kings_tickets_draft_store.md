# King's Tickets ephemeral draft store — dark-implementation return (Step 4)

Implemented DARK: `services/kings_tickets_drafts.py` + `qc_kings_tickets_drafts.py` (in
`run_all_scorecards`). Flag `KINGS_TICKETS_DRAFTS_ENABLED` defaults `"0"`. No routes, no autosave UI, no
flag flip, no Decision Journal writes, no persistent history. This document is the controlling spec and is
kept in lock-step with the executable behavior. Corrective **#2** closed ten further review blockers; the
sections below describe the code as it now runs.

## 0. Authoritative-identity boundary (who may write what)
Two layers, deliberately split:
- **`DraftService`** — the ONLY interface routes may import. It is flag-gated and accepts **opaque
  references only** (`candidate_ref`, optional `quote_ref`, plus the operational metadata `selection_origin`
  / `entry_method`). It resolves each reference against a **server-side resolver** (wired, in the future, to
  the current candidate/quote sources) and constructs the authoritative leg itself. A reference that carries
  any authoritative field (player name, line, book, price, timestamp, display label, …) is **rejected**; a
  client leg dictionary is never accepted; with no resolver configured the service **refuses to write**.
- **`KingsTicketDraftStore`** — the low-level repository. It accepts already-validated canonical rows, is
  account-bound on every op, revalidates defensively, and is never handed a request-derived path. Routes
  must not import it (`qc_kings_tickets_drafts` enforces this by scanning `app.py`).

This is the point of blocker #6: "server-reconstructed" now means *resolved from server-side sources*, not
*hashed from client-supplied fields*.

## 1. Complete DDL (SCHEMA_VERSION = 2)
`STRICT` is appended to each table when the deployed SQLite is ≥ 3.37 (keeps strings out of numeric columns).
The schema is created **transactionally** for a brand-new store; an existing store is never altered by
`CREATE TABLE IF NOT EXISTS` before its version is validated (see §7).
```sql
CREATE TABLE schema_meta(
  id INTEGER PRIMARY KEY CHECK(id=1),              -- singleton; exact version validated at startup
  version INTEGER NOT NULL
) STRICT;
CREATE TABLE drafts(
  account_user_id TEXT NOT NULL UNIQUE,            -- one active draft per account
  draft_id        TEXT NOT NULL PRIMARY KEY,
  revision        INTEGER NOT NULL CHECK(revision > 0),
  leg_count       INTEGER NOT NULL CHECK(leg_count BETWEEN 2 AND 5),
  originating_surface TEXT,
  risk_amount_cents INTEGER CHECK(risk_amount_cents IS NULL OR
                                  (risk_amount_cents >= 0 AND risk_amount_cents <= 100000000)),  -- integer cents
  combined_price            INTEGER CHECK(combined_price IS NULL OR combined_price <= -100 OR combined_price >= 100),
  combined_price_format     TEXT    CHECK(combined_price_format IS NULL OR combined_price_format='american'),
  combined_price_source     TEXT,
  combined_price_scope      TEXT,
  combined_price_timestamp  TEXT,
  combined_price_book       TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  -- combined price is ALL-OR-NOTHING; a stored quote preserves price+format+source+scope+timestamp+book
  CHECK((combined_price IS NULL AND combined_price_format IS NULL AND combined_price_source IS NULL
         AND combined_price_scope IS NULL AND combined_price_timestamp IS NULL AND combined_price_book IS NULL)
     OR (combined_price IS NOT NULL AND combined_price_format='american' AND combined_price_source IS NOT NULL
         AND combined_price_scope='combined-ticket' AND combined_price_timestamp IS NOT NULL
         AND combined_price_book IS NOT NULL))
  -- NO result / settlement / win-loss / graded columns. A draft is never history.
) STRICT;
CREATE TABLE draft_legs(
  draft_id TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  selection_key TEXT NOT NULL,                     -- server-reconstructed: event+subject+market+direction
  quote_observation_id TEXT,                       -- server-reconstructed: exact book/line/price/capture (nullable)
  sport TEXT, league TEXT, event_id TEXT, event_start TEXT,   -- event_start is canonical UTC (see §3)
  player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  market_key TEXT, direction TEXT, line REAL,
  price INTEGER CHECK(price IS NULL OR price <= -100 OR price >= 100),
  price_format TEXT CHECK(price_format IS NULL OR price_format='american'),  -- controlled enum
  sportsbook TEXT,
  quote_scope TEXT CHECK(quote_scope IS NULL OR quote_scope='single-leg'),   -- controlled enum
  source_provider TEXT, source_timestamp TEXT,     -- source_timestamp is canonical UTC (see §3)
  selection_origin TEXT, entry_method TEXT,
  reason_rule_id TEXT, display_label TEXT,          -- display_label never participates in identity
  quote_state TEXT NOT NULL CHECK(quote_state IN ('current','stale','missing','unknown')),
  inserted_at TEXT, last_validated_at TEXT,
  PRIMARY KEY(draft_id, position),
  UNIQUE(draft_id, selection_key),                 -- no duplicate underlying selection
  CHECK(price IS NULL OR price_format IS NOT NULL), -- a supplied price requires a format
  -- a 'current' quote must carry full provenance
  CHECK(quote_state != 'current' OR (line IS NOT NULL AND price IS NOT NULL AND price_format IS NOT NULL
        AND sportsbook IS NOT NULL AND quote_scope IS NOT NULL AND source_provider IS NOT NULL
        AND source_timestamp IS NOT NULL)),
  -- a 'stale' quote must preserve its original observation
  CHECK(quote_state != 'stale' OR quote_observation_id IS NOT NULL)
) STRICT;
CREATE INDEX idx_drafts_expires ON drafts(expires_at);
```
PRAGMAs on every connection: `foreign_keys=ON`, `busy_timeout=5000`, `isolation_level=None` (explicit
`BEGIN IMMEDIATE`). A new store adds `journal_mode=WAL` + `synchronous=FULL`; an existing store is opened
`query_only=ON` for inspection and only switched to WAL **after** its version validates.

## 2. Operation pseudocode (matches the code)
```
# ---- public service (routes import ONLY this) ----
DraftService.save(uid, references, expected_revision, resolver, combined_reference?, surface?, risk?):
  require_enabled()                               # dark -> StoreDisabled, store never opened
  require resolver                                # else DraftInvalid: no client leg dicts accepted
  for ref in references:                          # each ref: candidate_ref (+quote_ref/origin/entry) ONLY
     reject ref if it carries any authoritative field
     row = resolver(ref.candidate_ref, ref.quote_ref)   # AUTHORITATIVE leg from server-side source
     row.selection_origin/entry_method = ref.*          # operational metadata only
  combined = resolver(combined_reference) if combined_reference else None
  return KingsTicketDraftStore().save_draft(uid, rows, expected_revision, ..., combined)

DraftService.get(uid)                    = require_enabled(); store.get_draft(uid)
DraftService.clear(uid, expected_revision)  # expected_revision REQUIRED (no default)
                                         = require_enabled(); store.clear_draft(uid, expected_revision)
DraftService.delete_account_data(uid)    # flag-independent; NEVER creates a store (absent -> 0)
                                         = store.administrative_delete(uid) if db exists else 0

# ---- repository (canonical rows only) ----
save_draft(uid, legs, expected_revision, surface?, risk?, combined?):
  exp = exact_nonneg_int(expected_revision)   # rejects bool / float(1.9) / '0' / negative
  rows = validate(legs)                       # 2-5; UTC timestamps; enums; quote-state provenance;
                                              # identity reconstructed; duplicate selection rejected
  combined persisted ALL-OR-NOTHING (price+format+source+scope+timestamp+book) or entirely NULL
  BEGIN IMMEDIATE
    cur = SELECT draft_id,revision FROM drafts WHERE account_user_id=uid
    if cur:
       if exp != cur.revision: raise DraftConflict         # CAS
       new_rev = cur.revision+1; DELETE legs; UPDATE drafts(...)
    else:
       if exp != 0: raise DraftConflict                    # create requires exactly 0
       draft_id=new; new_rev=1; INSERT drafts(... expires_at = now+24h ...)
    INSERT each leg at its position
  COMMIT                                                    # any error -> ROLLBACK (no partial)

get_draft(uid, now?)   -> expired => purged + None in the same txn; TTL never extended by a read
clear_draft(uid, exp)  -> if a draft EXISTS, exp is mandatory and must match (else DraftInvalid/DraftConflict);
                          absent => no-op (returns 0)
administrative_delete(uid) -> unconditional (account deletion); NOT reachable via the route-facing clear
purge_expired(now)     -> DELETE FROM drafts WHERE expires_at<=now   (cascade legs)
```

## 3. Timestamps
Leg `event_start` / `source_timestamp` and the combined capture timestamp must be **timezone-aware**;
naive/local values are rejected. Accepted values are normalized to one canonical UTC representation
(`YYYY-MM-DDTHH:MM:SS[.ffffff]Z`). Server-written `inserted_at` / `last_validated_at` are already canonical.

## 4. Retention / purge
24h TTL from the **last user edit** (`expires_at = updated_at + 24h`, reset on every save). `purge_expired()`
runs on a scheduled timer and at service startup; an expired draft is also treated as absent and purged on
read. No backups (ephemeral scratch).

## 5. Concurrency proof
Single-slot row per account + an integer `revision` CAS token on **save and clear**. `BEGIN IMMEDIATE` +
`busy_timeout` serialize writers; a stale/absent token raises `DraftConflict` (never a generic lock error),
leaving the stored draft unchanged. Proven in QC with a real two-connection threaded race (exactly one save
wins, the other conflicts) and with fault injection at every transaction phase (each rolls back to the prior
complete revision).

## 6. Failure isolation
Any open/mkdir/SQLite failure raises `StoreUnavailable`; callers treat that as "no draft" and the rest of the
site is unaffected. There is **no fallback to the Decision Journal**. A failed save rolls back transactionally.
Validation errors raise `DraftInvalid`; concurrency raises `DraftConflict`; neither leaks DB internals. No
ticket contents are logged.

## 7. Startup / schema safety (never mutate before validating)
- **Absent store:** validate the runtime root, create only the missing child dir, create the DB file
  `O_EXCL|O_NOFOLLOW` at 0600, then create the schema **transactionally** (`BEGIN IMMEDIATE` → tables →
  `schema_meta` → `COMMIT`); a failed create removes the partial file.
- **Existing store:** open `query_only=ON`, read `schema_meta` **without applying any DDL**. A missing /
  duplicate / non-singleton / wrong-version / unreadable schema fails closed as `StoreUnavailable` with the
  file **byte-identical** (QC hashes the file before and after a failed open). Only after validation is WAL
  enabled. Migrations, if ever needed, must be explicit, versioned and transactional.

## 8. Production path & permission safety (POSIX/prod)
Ordering is: **validate the configured runtime root first** → lstat every existing path component and reject
a symlinked ancestor or target → create **only** the single missing child dir beneath the validated root →
create the DB `O_EXCL|O_NOFOLLOW` 0600 → validate owner + mode of the dir, DB, `-wal` and `-shm`. Nothing is
`chmod`-ed before root-containment is established, and an existing dir/DB/WAL/SHM with the wrong owner or a
too-open mode **fails closed** (the operator setup corrects it explicitly — the app never silently repairs).
The draft dir must be the runtime root or exactly one controlled level beneath it; anything else is rejected.

## 9. Privacy disclosure (draft text, pending review)
> **Your in-progress ticket draft.** When you build a King's Tickets ticket, we keep your current draft for
> up to **24 hours** so it's still here if you refresh or move around the site. It is **not** a placed bet and
> is **not** part of your betting or performance history. It is **visible only within your authenticated
> account and processed by Bankroll Kings to provide the draft feature**; as with the rest of your account
> data, our infrastructure/service providers may process it on our behalf under our privacy policy. It's
> deleted automatically after 24 hours, and you can clear it any time with **Clear Draft**. You can ask to
> see or delete it as part of your account data rights.

Classification: **product/data**, not a legal conclusion — privacy/legal review required before broad
enablement. The draft is account-bound, cleared on account deletion (via `delete_account_data`),
user-clearable immediately, included in a data-access response (or described there as ephemeral current
state), purged after 24h, and **excluded from analytics, model training and historical performance reporting**.

## 10. Production dark-setup (flag stays 0)
Create the private store directory on prod (SSM, as the service user). Pre-creating sets ownership/perms
deterministically; the service also validates (and, for a brand-new install, creates) it on first use:
```bash
sudo -u ubuntu bash -lc 'install -d -m 700 "${BK_RUNTIME_DIR:-/var/lib/bankrollkings}/kings_tickets"'
```
Verify the module loads + the QC passes on prod Linux (so the POSIX symlink/owner/mode checks actually run):
```bash
sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && python3 qc_kings_tickets_drafts.py'
```
Do **not** set `KINGS_TICKETS_DRAFTS_ENABLED`. Add a purge timer unit (like the other `bk-*` units) when
enabling, not now.

## 11. Enablement checklist (all required before flipping the flag)
- [ ] Privacy/legal review of §9 complete; disclosure published in the privacy policy.
- [ ] A **server-side resolver** is wired to the current candidate/quote sources and installed via
      `DraftService.configure_resolver`; routes pass only opaque references.
- [ ] Routes added: get/save/clear, **CSRF-protected**, account-bound on every op, rate-limited, generic
      errors, no draft id/contents in URLs, no cross-account cache.
- [ ] Autosave UI (save state, last-saved time, retry/error, **conflict reload/overwrite**, Clear Draft,
      the 24h disclosure) — no "placed"/"journaled" claims. Clear sends the current revision.
- [ ] Restore path renders saved selections first, then revalidates quotes separately (mark stale/missing,
      never silently substitute/reprice; keep the originally captured line/price for comparison).
- [ ] Account-deletion + data-access wired (`delete_account_data`, which never creates a store).
- [ ] Purge timer installed (scheduled) + startup purge confirmed; path/symlink/perm protection on prod.
- [ ] Load/concurrency/crash-recovery/security tests green on prod **Linux** (dark).
- [ ] `DECISION_JOURNAL_ENABLED=0` unchanged; `a94cbf9` still isolated.
- [ ] Then, and only then, set `KINGS_TICKETS_DRAFTS_ENABLED=1`.

**Stop point:** awaiting the enablement decision. No routes, UI, or flag flip until approved.

## Corrective #2 QC output (qc_kings_tickets_drafts.py)
Verified green on **prod Linux** at `23bb619` (and on the Windows dev host). On prod the POSIX
symlink/owner/mode block runs for real — the line below is the live `ubuntu@` run via SSM:
```
====================================================================
BANKROLL KINGS - KING'S TICKETS DRAFT STORE QC (dark, corrective #2)
====================================================================
[NOTE] flag dark by default
[NOTE] create requires expected_revision=0
[NOTE] CAS: update requires the current revision; omission/stale rejected
[NOTE] revision strict: bool/float(1.9)/decimal-string/negative all rejected
[NOTE] 2-5 leg bounds enforced
[NOTE] identity reconstructed server-side: client id ignored, dup selection + bare leg rejected
[NOTE] clear CAS: omitted/stale rejected on an existing draft; nonexistent no-op; correct works
[NOTE] account-deletion uses a separate administrative method (not the route-facing clear)
[NOTE] combined price all-or-nothing; price_format stored and round-trips
[NOTE] numeric validation rejects NaN/inf/bool/negative/oversized + invalid American + strings
[NOTE] timestamps: naive rejected; tz-aware normalized to canonical UTC (Z)
[NOTE] quote-state: a 'current' leg must carry full provenance; a price requires a format
[NOTE] expired-on-read: absent at boundary, purged, TTL not extended
[NOTE] fault injection at update/delete-legs/leg-insert/commit all roll back to prior revision
[NOTE] threaded CAS race: exactly one save wins, the other gets DraftConflict (not a lock error)
[NOTE] race left one complete draft with a single revision increment
[NOTE] account-bound reads isolated
[NOTE] schema singleton + exact-version fail-closed
[NOTE] unsupported DB byte-identical after a failed startup (no pre-validation mutation)
[NOTE] path escape (outside, or nested too deep beneath, the runtime root) rejected
[NOTE] POSIX: symlinked ancestor rejected; clean dir+db validates; wrong dir/db/-wal/-shm owner+mode fail closed
[NOTE] corruption degrades to StoreUnavailable (no crash, no Journal fallback)
[NOTE] authoritative boundary: references resolved server-side; client-supplied fields cannot override
[NOTE] flag-off DraftService refuses and opens nothing
[NOTE] flag-off service creates no filesystem entries
[NOTE] route-layer import guard: app.py does not touch the repository directly

No draft-store issues detected.
```
