# King's Tickets ephemeral draft store — dark-implementation return (Step 4)

Implemented DARK (`8650b74`): `services/kings_tickets_drafts.py` + `qc_kings_tickets_drafts.py` (in
`run_all_scorecards`). Flag `KINGS_TICKETS_DRAFTS_ENABLED` defaults `"0"`. No routes, no autosave UI, no
flag flip, no Decision Journal writes, no persistent history. Returned per directive for the enablement
decision.

## 1. Complete DDL
```sql
CREATE TABLE schema_meta(version INTEGER NOT NULL CHECK(version > 0));
CREATE TABLE drafts(
  account_user_id TEXT NOT NULL UNIQUE,            -- one active draft per account
  draft_id        TEXT NOT NULL PRIMARY KEY,
  revision        INTEGER NOT NULL CHECK(revision > 0),
  leg_count       INTEGER NOT NULL CHECK(leg_count BETWEEN 2 AND 5),
  originating_surface TEXT,
  risk_amount     REAL,                            -- only if entered
  combined_price            INTEGER,               -- ONLY when a sportsbook supplied a combined quote
  combined_price_source     TEXT,
  combined_price_scope      TEXT,
  combined_price_timestamp  TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
  -- NO result / settlement / win-loss / graded columns. A draft is never history.
);
CREATE TABLE draft_legs(
  draft_id TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  canonical_leg_id TEXT NOT NULL,
  sport TEXT, league TEXT, event_id TEXT, event_start TEXT,
  player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  market_key TEXT, direction TEXT, line REAL, price INTEGER, price_format TEXT, sportsbook TEXT,
  quote_scope TEXT, source_provider TEXT, source_timestamp TEXT, selection_origin TEXT, entry_method TEXT,
  reason_rule_id TEXT, display_label TEXT,
  quote_state TEXT NOT NULL CHECK(quote_state IN ('current','stale','missing','unknown')),
  inserted_at TEXT, last_validated_at TEXT,
  PRIMARY KEY(draft_id, position),
  UNIQUE(draft_id, canonical_leg_id)               -- unique canonical legs per draft
);
CREATE INDEX idx_drafts_expires ON drafts(expires_at);
```
PRAGMAs on every connection: `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=5000`.

## 2. Operation pseudocode
```
save_draft(uid, legs, surface, risk?, expected_revision?, combined?):
  rows = validate(legs)                       # 2-5; each field length-capped; unknown->NULL;
                                              # canonical_leg_id reconstructed server-side if absent;
                                              # reject duplicate canonical legs; quote_state in enum
  combined persisted only if combined.source present (else all NULL; illustrative is display-only)
  BEGIN IMMEDIATE
    cur = SELECT draft_id,revision FROM drafts WHERE account_user_id=uid
    if cur:
       if expected_revision != cur.revision: raise DraftConflict       # CAS
       new_rev = cur.revision+1; DELETE legs; UPDATE drafts(...)
    else:
       if expected_revision not in (None,0): raise DraftConflict
       draft_id=new; new_rev=1; INSERT drafts(... expires_at = now+24h ...)
    INSERT each leg at its position
  COMMIT                                       # any error -> ROLLBACK (no partial)
  return {draft_id, revision:new_rev, expires_at}

get_draft(uid)  -> {draft, legs ordered by position} | None      (account-bound)
clear_draft(uid)-> DELETE FROM drafts WHERE account_user_id=uid   (cascade legs)
purge_expired(now)-> DELETE FROM drafts WHERE expires_at<=now     (cascade legs)
```

## 3. Retention / purge
24h TTL measured from the **last user edit** (`expires_at = updated_at + 24h`, reset on every save).
`purge_expired()` is called (a) on a scheduled timer and (b) at service startup. No backups (ephemeral
scratch). A draft is purged automatically regardless of whether the user cleared it.

## 4. Concurrency proof
Single-slot row per account + an integer `revision`. Every save carries the caller's last-seen revision
as a CAS token; the transaction (`BEGIN IMMEDIATE`) re-reads the row and raises `DraftConflict` unless the
token equals the stored revision, so a stale tab can never silently overwrite a newer one — the caller
then offers reload/overwrite. SQLite `BEGIN IMMEDIATE` + `busy_timeout` serializes concurrent writers.
Proven in QC: a stale-revision save is rejected AND leaves the stored draft unchanged.

## 5. Failure isolation
Any open/mkdir/SQLite failure raises `StoreUnavailable`; callers treat that as "no draft" and the rest of
the site is unaffected. There is **no fallback to the Decision Journal**. A failed save rolls back
transactionally (no partial draft). Validation errors raise `DraftInvalid`; concurrency raises
`DraftConflict`; neither leaks DB internals to the client (callers map them to generic messages). No ticket
contents are logged.

## 6. Privacy disclosure (draft text, pending review)
> **Your in-progress ticket draft.** When you build a King's Tickets ticket, we keep your current draft for
> up to **24 hours** so it's still here if you refresh or move around the site. It is **not** a placed bet,
> is **not** shared, and is **not** part of your betting or performance history. It's deleted automatically
> after 24 hours, and you can clear it any time with **Clear Draft**. You can ask to see or delete it as
> part of your account data rights.

Classification: **product/data**, not a legal conclusion — privacy/legal review required before broad
enablement. The draft is account-bound, cleared on account deletion, user-clearable immediately, included
in a data-access response (or described there as ephemeral current state), purged after 24h, and **excluded
from analytics, model training and historical performance reporting**.

## 7. Production dark-setup (flag stays 0)
Create the private store directory on prod (SSM, as the service user) — the service also self-creates it on
first use, but pre-creating sets ownership/perms deterministically:
```bash
sudo -u ubuntu bash -lc 'install -d -m 700 "${BK_RUNTIME_DIR:-/var/lib/bankrollkings}/kings_tickets"'
```
Verify the module loads + the QC passes on prod; the DB file is created 0600 on first open. Do **not** set
`KINGS_TICKETS_DRAFTS_ENABLED`. Add a purge timer unit (like the other `bk-*` units) when enabling, not now.

## 8. Enablement checklist (all required before flipping the flag)
- [ ] Privacy/legal review of §6 complete; disclosure published in the privacy policy.
- [ ] Routes added: get/save/clear, **CSRF-protected**, account-bound on every op, rate-limited, generic
      errors, no draft id/contents in URLs, no cross-account cache.
- [ ] Autosave UI (save state, last-saved time, retry/error, **conflict reload/overwrite**, Clear Draft,
      the 24h disclosure) — no "placed"/"journaled" claims.
- [ ] Restore path renders saved selections first, then revalidates quotes separately (mark stale/missing,
      never silently substitute/reprice; keep the originally captured line/price for comparison).
- [ ] Account-deletion + data-access wired to the store.
- [ ] Purge timer installed (scheduled) + startup purge confirmed; path/symlink protection on the dir.
- [ ] Load/concurrency/crash-recovery/security tests green on prod (dark).
- [ ] `DECISION_JOURNAL_ENABLED=0` unchanged; `a94cbf9` still isolated.
- [ ] Then, and only then, set `KINGS_TICKETS_DRAFTS_ENABLED=1`.

**Stop point:** awaiting the enablement decision. No routes, UI, or flag flip until approved.
