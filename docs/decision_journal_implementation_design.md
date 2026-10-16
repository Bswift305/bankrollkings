# Decision Journal — Implementation & Storage Design (design only, no code)

**Status: DESIGN FREEZE for one final implementation approval. No code, no UI, no model tuning.**
Builds against `docs/decision_journal_review_spec.md` (Rev 3). The DDL, triggers and operation
**pseudocode** below are schema/procedure artifacts (the thing being frozen), not application code.

Governing constraint (Rev 3): **never manufacture precision a sportsbook ticket did not provide.**
Unknown stays unknown; the book's settlement is authoritative; nothing causal is claimed.

Date: 2026-10-16. Design revision: 3 (rev 2 closed the ten implementability blockers; rev 3 closed two
executable defects + three mechanical alignments found in mechanical review — see §14). **This is the
final design; V1 implementation is authorized directly from it.**

---

## 1. Storage decision — JSON tracker vs transactional SQLite

### 1a–1b. (unchanged) Whole-file JSON fails the hard Rev 3 requirements — atomicity, concurrency,
immutability, lost-update race — on every multi-row write. The comparison table from design rev 1
stands; it is summarized here and not repeated line-by-line.

### 1c. Decision — **SQLite, single database file, WAL, `synchronous=FULL`**
**One SQLite database**, opened with:

```
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;     -- user-owned records: durability over throughput; weaken only on measured evidence (blocker 8)
PRAGMA busy_timeout = 5000;
```

- **Path is configurable and private (blocker 8):** `DECISION_JOURNAL_DB_PATH`, **stored outside the
  deploy checkout** so a `git pull`/redeploy never touches it. Prod default
  `/var/lib/bankrollkings/decision_journal/journal.db`; Windows dev default under the user's app-data
  dir (never OneDrive, never the repo). Directory `0700`, DB file `0600`, owned by the app service
  user. The `-wal`/`-shm` siblings inherit the directory's restricted perms.
- **Single DB, not per-user files.** Isolation is a **service boundary** (§10), not a storage feature.
- `sqlite3` is stdlib — no new dependency. The "no database" project convention is for the analytics
  pipeline (bulk, regenerated); the journal is transactional user-owned state. Exception scoped to the
  journal only.

---

## 2. Schema freeze (DDL)

Timestamps are ISO-8601 UTC text (`YYYY-MM-DDTHH:MM:SSZ`), comparable with `datetime('now')`. Money is
integer **cents**, never float. `NULL` always means *unknown* and is never substituted with a guess.
The base ticket/leg rows are the **immutable decision-time snapshot**; every post-lock change is an
append-only row in `decision_revisions` (§4) — the base is never mutated for a frozen field.

```sql
CREATE TABLE schema_meta (
  id          INTEGER PRIMARY KEY CHECK (id = 1),   -- enforces a single row (blocker 7)
  version     INTEGER NOT NULL,
  applied_at  TEXT    NOT NULL
);

CREATE TABLE tickets (
  ticket_id          TEXT PRIMARY KEY,               -- uuid4
  user_id            TEXT NOT NULL,
  ticket_type        TEXT NOT NULL CHECK (ticket_type IN
                        ('straight','parlay','same-game-parlay','legacy_flat_ticket')),
  record_provenance  TEXT NOT NULL CHECK (record_provenance IN
                        ('prospective-captured','historical-documented',
                         'historical-reconstructed','legacy-flat')),
  book               TEXT,
  game_thesis        TEXT,
  game_thesis_at     TEXT,                           -- < earliest_kickoff for prospective (trigger)
  combined_price     INTEGER,                        -- actual book payout odds; NO independence caveat
  -- settlement block (book-authoritative; semantics frozen in §6) --
  book_ticket_result TEXT CHECK (book_ticket_result IN
                        ('win','loss','push','void','cashout','pending') OR book_ticket_result IS NULL),
  cash_stake_cents       INTEGER,
  promo_stake_cents      INTEGER,
  total_returned_cents   INTEGER,
  cashout_amount_cents   INTEGER,
  book_settlement_note   TEXT,
  net_cash_pl_cents      INTEGER,                    -- stored ONLY when §6 inputs sufficient; else NULL
  thesis_correct     INTEGER CHECK (thesis_correct IN (0,1) OR thesis_correct IS NULL),  -- SUBJECTIVE
  import_fingerprint TEXT UNIQUE,                    -- idempotent import / dup detect (§5); NULL = manual
  migrated_from_json TEXT UNIQUE,                    -- source JSON record id when migrated; else NULL (blocker 7)
  earliest_kickoff   TEXT,                           -- = min(legs.event_start); drives the lock (§4)
  placed_at          TEXT,
  settled_at         TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);
CREATE INDEX ix_tickets_user ON tickets(user_id);
CREATE INDEX ix_tickets_prov ON tickets(user_id, record_provenance);

CREATE TABLE legs (
  leg_id             TEXT PRIMARY KEY,               -- uuid4
  ticket_id          TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  leg_index          INTEGER NOT NULL,
  selection_origin   TEXT NOT NULL CHECK (selection_origin IN
                        ('user-selected','BK-rule-assembled','unknown')),
  entry_method       TEXT NOT NULL CHECK (entry_method IN
                        ('manual','sportsbook-import','BK-builder','migration')),
  user_reviewed_before_bet TEXT NOT NULL CHECK (user_reviewed_before_bet IN ('yes','no','unknown')),
  surfaces_known     INTEGER NOT NULL DEFAULT 1,     -- 0 => consulted-surfaces unknown; 1 => known (0..N rows)
  sport              TEXT NOT NULL,
  game               TEXT NOT NULL,
  event_start        TEXT,                           -- kickoff/tip; required for prospective (trigger)
  player             TEXT,                           -- prop only
  market             TEXT NOT NULL,                  -- e.g. 'passing yards', 'spread', 'moneyline', 'total'
  selection          TEXT NOT NULL,                  -- WHAT was picked (blocker 1): 'over'/'under' for props&totals;
                                                     --   the chosen team or 'home'/'away' for spread/ML. The pick,
                                                     --   not just the market+line.
  line               REAL,                           -- captured at decision time; NULL = unknown, never inferred
  quote_scope        TEXT NOT NULL CHECK (quote_scope IN ('individual-leg','combined-ticket','unavailable')),
  price              INTEGER,                         -- REQUIRED iff quote_scope='individual-leg'
  book               TEXT,
  decision_time      TEXT,                            -- < event_start for prospective (trigger)
  leg_rationale      TEXT,
  leg_rationale_at   TEXT,                            -- < event_start for prospective (trigger)
  confidence         INTEGER CHECK (confidence BETWEEN 1 AND 5 OR confidence IS NULL),  -- personal, frozen
  alt_line           REAL,
  alt_price          INTEGER,
  leg_result         TEXT CHECK (leg_result IN ('win','loss','push','void','pending') OR leg_result IS NULL),
  read_happened      INTEGER CHECK (read_happened IN (0,1) OR read_happened IS NULL),
  CHECK (quote_scope != 'individual-leg' OR price IS NOT NULL),   -- combined-only legs not forced to invent a price
  UNIQUE (ticket_id, leg_index)
);
CREATE INDEX ix_legs_ticket ON legs(ticket_id);

CREATE TABLE leg_reason_tags (                       -- >=1 per leg; tags OVERLAP (reporting discloses)
  leg_id  TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  tag     TEXT NOT NULL CHECK (tag IN
            ('streak','coaching','effort','matchup','injuries','pace/game-env','line-value','model','other')),
  PRIMARY KEY (leg_id, tag)
);

CREATE TABLE leg_bk_surfaces (                       -- 0 rows with surfaces_known=1 => "consulted none"
  leg_id  TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  surface TEXT NOT NULL,
  PRIMARY KEY (leg_id, surface)
);

CREATE TABLE leg_bk_origin (                         -- immutable BK-origin reference (blocker 5)
  leg_id          TEXT PRIMARY KEY REFERENCES legs(leg_id) ON DELETE CASCADE,  -- present IFF origin=BK-rule-assembled
  surface         TEXT NOT NULL,                     -- the tool/surface that assembled it
  candidate_id    TEXT NOT NULL,                     -- the assembly/candidate id the surface showed
  rule_version    TEXT NOT NULL,                     -- rule / engine version at decision time
  captured_at     TEXT NOT NULL,                     -- when the suggestion was captured; <= leg.decision_time (trigger, §4)
  displayed_line  REAL,                              -- line the surface showed, where available
  displayed_price INTEGER                            -- price the surface showed, where available
);

CREATE TABLE decision_revisions (                    -- APPEND-ONLY: the ONLY post-lock change path (§4)
  revision_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      TEXT NOT NULL,
  target_table TEXT NOT NULL CHECK (target_table IN           -- explicit allowlist (incl. leg_bk_origin)
                 ('tickets','legs','leg_reason_tags','leg_bk_surfaces','leg_bk_origin')),
  target_id    TEXT NOT NULL,                        -- ticket_id or leg_id
  field        TEXT NOT NULL CHECK (field IN (        -- explicit allowlist: every frozen field + membership ops
                 -- tickets:
                 'game_thesis','game_thesis_at','combined_price','record_provenance','ticket_type',
                 'earliest_kickoff','import_fingerprint',
                 -- legs:
                 'selection_origin','entry_method','user_reviewed_before_bet','surfaces_known','sport',
                 'game','event_start','player','market','selection','line','quote_scope','price','book',
                 'decision_time','leg_rationale','leg_rationale_at','confidence','alt_line','alt_price','leg_index',
                 -- leg_bk_origin:
                 'surface','candidate_id','rule_version','captured_at','displayed_line','displayed_price',
                 -- membership ops:
                 'tag:add','tag:remove','surface:add','surface:remove')),
  old_value    TEXT,                                 -- typed JSON (json.dumps): number/null/string never confused
  new_value    TEXT,                                 -- typed JSON
  reason       TEXT NOT NULL,                        -- a correction MUST state why
  actor        TEXT NOT NULL,
  created_at   TEXT NOT NULL
);
CREATE INDEX ix_rev_target ON decision_revisions(target_table, target_id);
```

---

## 3. Atomic operations (pseudocode)

All writes: `BEGIN IMMEDIATE` … single `COMMIT`; any error → `ROLLBACK`. The repository (§10) is the
only caller.

```
create_ticket(user_id, ticket_fields, legs[]):            # atomic, all-or-nothing
  assert legs is non-empty if provenance == 'prospective-captured'   # >=1 real leg (blocker 4)
  assert legs is empty      if ticket_type == 'legacy_flat_ticket'   # zero legs, no placeholder (blocker 7)
  BEGIN IMMEDIATE
    INSERT tickets(... earliest_kickoff = NULL ...)       # not yet locked
    for i, leg in legs:
      INSERT legs(leg_index=i, ...)                       # triggers enforce prospective timing on insert
      for tag in leg.reason_tags:      INSERT leg_reason_tags
      if leg.surfaces_known:
        for s in leg.surfaces:         INSERT leg_bk_surfaces
      if leg.selection_origin == 'BK-rule-assembled':
        INSERT leg_bk_origin(...)                          # required (trigger verifies, blocker 5)
    UPDATE tickets SET earliest_kickoff = (SELECT min(event_start) FROM legs WHERE ticket_id=?)
                                                           # thesis-timing trigger fires here for prospective
  COMMIT

settle_ticket(user_id, ticket_id, settlement, leg_results[]):   # atomic
  BEGIN IMMEDIATE
    UPDATE tickets SET book_ticket_result, cash_stake_cents, promo_stake_cents,
       total_returned_cents, cashout_amount_cents, book_settlement_note,
       net_cash_pl_cents = compute_net_cash_pl(...)        # §6; NULL when inputs insufficient
       , settled_at = now, updated_at = now
     WHERE ticket_id=? AND user_id=?                       # settlement columns are NOT frozen
    for lr in leg_results:
      UPDATE legs SET leg_result=?, read_happened=? WHERE leg_id=? AND ticket_id=?
  COMMIT
```

---

## 4. Immutability + the append-only correction mechanism (blockers 2 & 3)

**No transaction-local trigger bypass is used** (it is not a real SQLite primitive). The frozen
mechanism is **append-only decision revisions**: after a ticket locks, its base rows and child rows are
**hard-immutable** (triggers `RAISE(ABORT)` with no exception), and the *only* way to amend a frozen
datum is to append a row to `decision_revisions`. The decision-time snapshot is therefore preserved
forever; the effective (corrected) value is the base overlaid with the latest matching revision.

**Lock predicate:** a ticket is locked when
`earliest_kickoff IS NOT NULL AND julianday(earliest_kickoff) <= julianday('now')`, **or**
`settled_at IS NOT NULL`. **All** lock and timing comparisons use `julianday(...)`, never lexical
string comparison — stored timestamps are `...T...Z` while `datetime('now')` is `... ...` (space, no
`Z`), so a lexical `<=` can misfire on the day of kickoff (blocker 1).

**Frozen after lock** — ticket: `game_thesis, game_thesis_at, combined_price, record_provenance,
ticket_type, earliest_kickoff, import_fingerprint`. Leg: `selection_origin, entry_method,
user_reviewed_before_bet, surfaces_known, sport, game, event_start, player, market, selection, line,
quote_scope, price, book, decision_time, leg_rationale, leg_rationale_at, confidence, alt_line,
alt_price, leg_index`, plus the **whole** `leg_bk_origin` row, and the **membership** of
`leg_reason_tags` and `leg_bk_surfaces`, and leg **insert/delete** (blocker 3).

**Mutable after lock** (results known later): ticket settlement block, `settled_at`, `thesis_correct`;
leg `leg_result`, `read_happened`.

All lock/timing tests use `julianday(...)`. The locked sub-expression is written once here and reused:
`LOCKED(t) ::= (t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) OR t.settled_at IS NOT NULL`.

```sql
-- ticket frozen columns
CREATE TRIGGER trg_tickets_freeze BEFORE UPDATE ON tickets FOR EACH ROW
WHEN (OLD.earliest_kickoff IS NOT NULL AND julianday(OLD.earliest_kickoff) <= julianday('now')) OR OLD.settled_at IS NOT NULL
BEGIN
  SELECT CASE WHEN
      NEW.game_thesis       IS NOT OLD.game_thesis       OR NEW.game_thesis_at IS NOT OLD.game_thesis_at
   OR NEW.combined_price    IS NOT OLD.combined_price    OR NEW.record_provenance IS NOT OLD.record_provenance
   OR NEW.ticket_type       IS NOT OLD.ticket_type       OR NEW.earliest_kickoff IS NOT OLD.earliest_kickoff
   OR NEW.import_fingerprint IS NOT OLD.import_fingerprint
  THEN RAISE(ABORT,'frozen ticket field — use decision_revisions') END;
END;

-- leg frozen columns (parent locked)
CREATE TRIGGER trg_legs_freeze BEFORE UPDATE ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = OLD.ticket_id
             AND ((t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) OR t.settled_at IS NOT NULL))
BEGIN
  SELECT CASE WHEN
      NEW.selection_origin IS NOT OLD.selection_origin OR NEW.entry_method IS NOT OLD.entry_method
   OR NEW.user_reviewed_before_bet IS NOT OLD.user_reviewed_before_bet OR NEW.surfaces_known IS NOT OLD.surfaces_known
   OR NEW.sport IS NOT OLD.sport OR NEW.game IS NOT OLD.game OR NEW.event_start IS NOT OLD.event_start
   OR NEW.player IS NOT OLD.player OR NEW.market IS NOT OLD.market OR NEW.selection IS NOT OLD.selection
   OR NEW.line IS NOT OLD.line OR NEW.quote_scope IS NOT OLD.quote_scope OR NEW.price IS NOT OLD.price
   OR NEW.book IS NOT OLD.book OR NEW.decision_time IS NOT OLD.decision_time
   OR NEW.leg_rationale IS NOT OLD.leg_rationale OR NEW.leg_rationale_at IS NOT OLD.leg_rationale_at
   OR NEW.confidence IS NOT OLD.confidence OR NEW.alt_line IS NOT OLD.alt_line OR NEW.alt_price IS NOT OLD.alt_price
   OR NEW.leg_index IS NOT OLD.leg_index
  THEN RAISE(ABORT,'frozen leg field — use decision_revisions') END;
END;

-- no leg insert/delete/reorder after lock
CREATE TRIGGER trg_legs_no_insert BEFORE INSERT ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = NEW.ticket_id
             AND ((t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) OR t.settled_at IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'leg insert after lock'); END;

CREATE TRIGGER trg_legs_no_delete BEFORE DELETE ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = OLD.ticket_id
             AND ((t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) OR t.settled_at IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'leg delete after lock'); END;

-- tags / surfaces / bk_origin immutable after lock. The same INSERT+DELETE pair exists for
-- leg_reason_tags and leg_bk_surfaces; leg_bk_origin additionally blocks UPDATE and DELETE (its row is
-- the decision-time BK snapshot). All join leg -> ticket for the LOCKED test. One shown:
CREATE TRIGGER trg_tags_no_insert BEFORE INSERT ON leg_reason_tags FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id
             WHERE l.leg_id = NEW.leg_id
             AND ((t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) OR t.settled_at IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'reason-tag change after lock'); END;
-- (… trg_tags_no_delete, trg_surfaces_no_insert/delete, trg_bkorigin_no_insert/update/delete analogous …)

-- BK-origin capture must not postdate the decision (blocker alignment: captured_at <= decision_time)
CREATE TRIGGER trg_bkorigin_capture_timing BEFORE INSERT ON leg_bk_origin FOR EACH ROW
BEGIN
  SELECT CASE WHEN EXISTS (SELECT 1 FROM legs l WHERE l.leg_id = NEW.leg_id
             AND l.decision_time IS NOT NULL AND julianday(NEW.captured_at) > julianday(l.decision_time))
         THEN RAISE(ABORT,'leg_bk_origin.captured_at is after the leg decision_time') END;
END;

-- NOTE: there is NO AFTER-INSERT trigger requiring a leg_bk_origin row for BK-rule-assembled legs.
-- SQLite runs it immediately after the leg INSERT, before the origin row is inserted in the same
-- transaction, so it would ALWAYS abort and no BK leg could ever be created (blocker 2). The invariant
-- "every BK-rule-assembled leg has exactly one leg_bk_origin row" is instead enforced by:
--   (a) repository validation AFTER inserting the origin rows and BEFORE COMMIT (the atomic transaction
--       rolls the whole ticket back if it fails); and
--   (b) a startup + QC orphan query:
--       SELECT leg_id FROM legs WHERE selection_origin='BK-rule-assembled'
--         AND leg_id NOT IN (SELECT leg_id FROM leg_bk_origin);   -- must return zero rows

-- prospective timing (blocker 4) — julianday throughout
CREATE TRIGGER trg_legs_prospective BEFORE INSERT ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = NEW.ticket_id AND t.record_provenance='prospective-captured')
BEGIN
  SELECT CASE WHEN NEW.event_start IS NULL THEN RAISE(ABORT,'prospective leg requires event_start') END;
  SELECT CASE WHEN NEW.decision_time IS NULL OR julianday(NEW.decision_time) >= julianday(NEW.event_start)
         THEN RAISE(ABORT,'decision_time must precede event_start') END;
  SELECT CASE WHEN NEW.leg_rationale_at IS NOT NULL AND julianday(NEW.leg_rationale_at) >= julianday(NEW.event_start)
         THEN RAISE(ABORT,'leg rationale timestamped after event start') END;
END;

CREATE TRIGGER trg_ticket_thesis_timing BEFORE UPDATE OF earliest_kickoff ON tickets FOR EACH ROW
WHEN NEW.record_provenance='prospective-captured' AND NEW.game_thesis_at IS NOT NULL
BEGIN
  SELECT CASE WHEN julianday(NEW.game_thesis_at) >= julianday(NEW.earliest_kickoff)
         THEN RAISE(ABORT,'thesis timestamped after kickoff') END;
END;

-- decision_revisions is append-only
CREATE TRIGGER trg_rev_no_update BEFORE UPDATE ON decision_revisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER trg_rev_no_delete BEFORE DELETE ON decision_revisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
```

```
correct(user_id, target_table, target_id, field, new_value, reason, actor):   # the ONLY post-lock edit
  assert field is in the repository's allowlist FOR target_table   # table-appropriate subset, tighter than the CHECK
  BEGIN IMMEDIATE
    old = effective_value(target_table, target_id, field)
    INSERT decision_revisions(user_id, target_table, target_id, field,
                              old_value = json.dumps(old), new_value = json.dumps(new_value),
                              reason, actor, created_at=now)
  COMMIT
# effective_value(field) = json.loads(latest decision_revisions.new_value) for (target, field),
#   else the base row's value. Values are stored as typed JSON so a number, a null and a string "null"
#   are never confused. child membership corrections use field='tag:add'/'tag:remove'/'surface:add'/
#   'surface:remove' with new_value = the tag/surface name.
```

**≥1-leg (prospective) and 0-leg (legacy_flat_ticket)** are asserted by the repository inside the
create transaction (SQLite cannot declaratively require a child-count at COMMIT), and re-verified by a
startup + QC integrity query — stated honestly rather than claimed as a pure DB constraint.

---

## 5. Imports — idempotent, dup-detected (schema frozen; UI deferred to post-V1)
`import_fingerprint` = stable hash of `(user_id, book, placed_at rounded to minute, and each leg's
game + market + selection + line)` — **now includes `selection`** (blocker 1), order-independent.
`UNIQUE`, so re-import is a no-op. Near-duplicate manual entries are **flagged for the user**, never
silently merged. Import UI is not in V1 (§11); the column and rule are frozen so the schema is stable.

---

## 6. Settlement semantics (frozen — blocker 6)

All amounts in cents. Definitions:

- **`cash_stake_cents`** — real money risked. **`promo_stake_cents`** — free-bet/bonus amount wagered
  (not real money).
- **Free-bet stake is NOT returned** — on a winning free bet the book credits winnings only, never the
  promo stake. So the promo stake never appears in `total_returned_cents`.
- **`total_returned_cents`** — the total **real cash** the book credited from this ticket, **including
  any cashout proceeds** and the settlement of any residual. One convention, no ambiguity:
  everything the book paid back to the cash balance for this ticket.
- **`cashout_amount_cents`** — the portion of `total_returned_cents` that came from a cashout (0/NULL
  if none). **Partial cashout + later settlement:** `cashout_amount_cents` = the cashed portion;
  `total_returned_cents` = cashout proceeds **plus** the residual's normal settlement return; so the
  invariant below still holds without special-casing.
- **`net_cash_pl_cents`** — the single deterministic formula:

  ```
  net_cash_pl_cents = total_returned_cents − cash_stake_cents
  ```

  Stored **only** when **both** `cash_stake_cents` and `total_returned_cents` are known (and, when
  `book_ticket_result='cashout'`, `cashout_amount_cents` is known). Otherwise **NULL = unavailable** —
  never derived from assumed odds. (Worked cases: cash win → returned = stake + winnings, net = +win;
  free-bet-only win → cash_stake 0, returned = winnings, net = +winnings; full cashout → returned =
  cashout proceeds, net = proceeds − stake; void/push → returned = stake, net = 0.)
- **ROI is separate from net cash P/L, and has a zero-denominator rule.** `roi = net_cash_pl_cents /
  cash_stake_cents`. When **`cash_stake_cents = 0`** (e.g. a free-bet-only ticket) the net cash
  **profit is still shown**, but **ROI is "unavailable"** — the denominator is zero, so no percentage
  is computed or displayed. ROI is likewise unavailable whenever `net_cash_pl_cents` is NULL.

---

## 7. (merged into §4) Audit / correction trail
The correction trail **is** `decision_revisions`, append-only and trigger-protected against
UPDATE/DELETE. There is no separate mutable `audit_log` (that reconciles the blocker-7 concern that an
"append-only" table had no enforcement).

---

## 8. Migration — reversible, additive, non-destructive (reconciled with the DDL — blocker 7)
- **Source:** `data/user_bets/<uid>.json`, read **read-only**; never modified or deleted.
- **Straight bets** → one-leg tickets: `entry_method='migration'`, `record_provenance='legacy-flat'`,
  `selection` from the recorded pick, `quote_scope='individual-leg'` if a price was present else
  `'unavailable'`, `selection_origin='unknown'`, `user_reviewed_before_bet='unknown'`,
  `migrated_from_json = <json record id>`.
- **Parlays / multi-leg** → `ticket_type='legacy_flat_ticket'` with **zero legs** (no fabricated
  placeholder — blocker 7). Ticket-level stake/result/settlement carried where present.
- **Reversible & idempotent:** `migrated_from_json` is `UNIQUE`; re-running inserts nothing new, and a
  reverse pass deletes exactly the rows whose `migrated_from_json` is set. JSON stays authoritative
  until a later, separately-approved cutover.

---

## 9. Failure behavior (blocker 9)
On DB open failure or a failed `PRAGMA integrity_check` / `foreign_key_check`:
- the journal enters a **disabled** state: **writes are refused** and the UI shows **"Journal
  temporarily unavailable."**
- **No unrelated site page is affected** — the journal module catches its own storage errors; no
  exception propagates to other routes.
- The failure **alerts** (the daily-refresh alert path) and the DB is **not** silently rewritten;
  recovery is the §12 restore.

---

## 10. Access isolation = one repository/service boundary (blocker 10)
- All journal DB access goes through a **single `JournalRepository` service** that **requires the
  authenticated `user_id`** and scopes every statement by it. No other module issues SQL against
  `journal.db`.
- **Tests assert cross-user denial on every public operation** (read, create, settle, correct, report)
  — attempts to touch another user's `ticket_id`/`leg_id` return not-found/denied. We do **not** claim
  a QC proves "no unscoped SQL exists anywhere"; the guarantee is the boundary + per-operation denial
  tests.

---

## 11. V1 UI scope (frozen — deliberately small)
1. **Prospective manual entry** (`entry_method='manual'`, `record_provenance='prospective-captured'`),
   `decision_time`/`game_thesis` captured pregame, `selection` required per leg.
2. **Individual leg preservation** incl. `quote_scope` (SGP combined-only honored; no invented price).
3. **Pregame thesis & rationale** capture.
4. **Actual settlement** entry (§6).
5. **User-selected vs BK-rule-assembled** comparison (with the immutable `leg_bk_origin` reference
   captured for BK legs) with sample sizes.
6. **Straight / parlay / same-game-parlay reporting** with sample sizes, overlapping-tag disclosure,
   descriptive (non-causal) framing.

**OUT of V1:** sportsbook automation, OCR, model tuning, causal conclusions, import/near-duplicate UI,
and a full correction console (the schema/triggers enforce corrections; the V1 UI simply blocks frozen
edits and exposes settlement).

---

## 12. Backup, restore, corruption recovery (retention frozen — blocker 8)
- **Backup:** scheduled `VACUUM INTO` snapshot to the private backup dir (not the checkout): **hourly
  WAL checkpoint; a daily snapshot retained 30 days; a monthly snapshot retained 12 months.** Prod =
  a `bk-*` systemd timer (installed via SSM, like the other units); Windows dev = a Scheduled Task.
- **Integrity:** `integrity_check` + `foreign_key_check` on app start and after each snapshot; failure
  → §9 disabled state + alert.
- **Recovery:** restore the latest good snapshot; records newer than it that still exist in the JSON
  source (rollout window) can be re-migrated idempotently (`migrated_from_json`). WAL gives
  crash-consistency for the in-flight transaction with no manual step.

---

## 13. Acceptance tests (QC-style, runner-registered)

| Test | Asserts |
|---|---|
| `qc_dj_concurrency` | two writers under WAL → no lost update, no lock error past `busy_timeout`, both present |
| `qc_dj_crash_recovery` | a transaction killed mid-write leaves no partial ticket after reopen |
| `qc_dj_unknown_fields` | NULL line/price/settlement persist as unknown; no coercion to 0/−110; reports show "unavailable" |
| `qc_dj_selection` | a leg without `selection` is rejected; Over vs Under on the same market+line are distinct records and fingerprints |
| `qc_dj_sgp_pricing` | `combined-ticket` leg with no price saves; `individual-leg` leg with NULL price is rejected |
| `qc_dj_push_void_cashout_promo` | §6 arithmetic: cash win, free-bet-only win, full & **partial** cashout, void/push all yield the right `net_cash_pl` or NULL |
| `qc_dj_immutability` | after lock: frozen ticket/leg columns, leg insert/delete, tag add/delete, surface add/delete, `leg_bk_origin` change, and `earliest_kickoff` change are **all** blocked |
| `qc_dj_corrections_append_only` | a correction appends to `decision_revisions` and the effective value overlays; UPDATE/DELETE on `decision_revisions` are rejected |
| `qc_dj_prospective_timing` | prospective ticket requires event_start, enforces decision_time < event_start, thesis/rationale before start, ≥1 leg, and no leg added after earliest kickoff |
| `qc_dj_bk_origin` | a `BK-rule-assembled` leg without a `leg_bk_origin` row is rejected; the reference is immutable after lock |
| `qc_dj_import_idempotent` | re-import of a fingerprint is a no-op; a near-duplicate is flagged, not merged |
| `qc_dj_migration` | straight→one-leg, parlay→`legacy_flat_ticket` with **zero** legs; re-run changes nothing; JSON untouched; reverse pass removes only `migrated_from_json` rows |
| `qc_dj_access_isolation` | every public repository operation denies another user's ids (per-operation cross-user denial) |
| `qc_dj_failure_mode` | a forced integrity-check failure disables journal writes + shows the banner and does not raise into unrelated routes |
| `qc_dj_reporting` | every breakdown emits sample sizes; overlapping-tag disclosure present; no causal language; reconstructed/historical excluded from prospective cuts |

---

## 14. What changed in design rev 2 (the ten blockers)
1. Added required **`selection`** on legs (and into the import fingerprint) — a leg now has a pick.
2. Removed the unsupported transaction-local trigger bypass; froze **append-only `decision_revisions`**
   as the one real SQLite correction mechanism; base rows hard-immutable after lock.
3. Immutability now covers **leg insert/delete, reason-tag and surface membership, `leg_bk_origin`,
   and `earliest_kickoff`**, not just column updates.
4. **DB-enforced prospective timing** (event_start required; decision_time < event_start; thesis/
   rationale before start; ≥1 leg; no leg after kickoff).
5. Added the immutable **`leg_bk_origin`** reference (surface, candidate id, rule version, captured_at,
   displayed line/price) required for `BK-rule-assembled`.
6. **Frozen settlement semantics** + a single deterministic `net_cash_pl` formula, stored only when
   inputs suffice.
7. DDL/migration reconciled: added `migrated_from_json`; `schema_meta` single-row `CHECK`; append-only
   enforced by triggers; `legacy_flat_ticket` = **zero** legs.
8. **`DECISION_JOURNAL_DB_PATH`** outside the checkout, `0700`/`0600`, `synchronous=FULL`, retention
   frozen (30 daily / 12 monthly).
9. **Journal-only failure behavior** defined (disable writes + banner; never take down other pages).
10. Access isolation reframed as a **repository/service boundary** with per-operation cross-user denial
    tests (not a claim that no unscoped SQL exists).

---

## 14b. What changed in design rev 3 (mechanical review)
1. **`julianday()` everywhere** in lock and timing comparisons — stored `...T...Z` vs
   `datetime('now')` (`... ...`, no `Z`) made lexical `<=` misfire on the kickoff day.
2. **Removed `trg_legs_require_bkorigin`** — it ran right after the leg INSERT, before the origin row
   in the same transaction, so it always aborted and no BK leg could be inserted. The invariant is now
   enforced by repository validation before COMMIT + a startup/QC orphan query (+ atomic rollback).
3. **`leg_bk_origin.captured_at <= leg.decision_time`** enforced by a BEFORE INSERT trigger.
4. **`decision_revisions` allowlists** on `target_table` and `field` (incl. `leg_bk_origin`), and
   values stored as **typed JSON** so number/null/string are never confused.
5. **ROI zero-denominator rule** — a free-bet-only ticket (`cash_stake_cents = 0`) shows net profit but
   ROI is **unavailable** (no division by zero).

## 15. What this document is
The corrected design for **one final — and mechanical — implementation approval.** It introduces no
code and no UI. On approval, implementation builds exactly this: the §2 schema + §4 triggers, the §3
operations, §5–§10 guarantees, the §11 V1 scope, the §12 recovery, the §13 tests, nothing broader.
