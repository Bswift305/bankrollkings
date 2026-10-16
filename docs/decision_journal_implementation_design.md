# Decision Journal — Implementation & Storage Design (design only, no code)

**Status: DESIGN FREEZE for one final implementation approval. No code, no UI, no model tuning.**
This document builds against the approved contract in `docs/decision_journal_review_spec.md` (Rev 3)
and freezes the decisions the implementation-design gate asked for. The DDL and operation descriptions
below are **schema and procedure artifacts** (the thing being frozen), not application code.

Governing constraint (carried from Rev 3): **never manufacture precision a sportsbook ticket did not
provide.** Unknown stays unknown; the book's settlement is authoritative; nothing causal is claimed.

Date: 2026-10-16.

---

## 1. Storage decision — JSON tracker vs transactional SQLite

### 1a. What the existing tracker does
`services/bet_tracker.py` writes `data/user_bets/<uid>.json` — a whole-file read-modify-write of a
list of flat bet dicts. It works for a small personal log but cannot carry the Rev 3 record.

### 1b. Comparison against the Rev 3 requirements

| Requirement (Rev 3) | Whole-file JSON | Transactional SQLite (`sqlite3`, stdlib) |
|---|---|---|
| Atomic ticket **+ N legs + tags + surfaces** in one write | ✗ — one JSON blob; a crash mid-write corrupts the file; no multi-record atomicity beyond "rewrite everything" | ✓ — one `BEGIN IMMEDIATE … COMMIT` transaction spans all rows |
| Concurrency (web worker + settlement job) | ✗ — two read-modify-writes race; last writer wins, the other's write is lost | ✓ — WAL: concurrent readers + serialized single writer; no lost update |
| Crash leaves no partial ticket | ✗ — truncated/partial JSON is unparseable | ✓ — uncommitted transaction rolls back; WAL recovery on open |
| Immutable decision-time fields + audit | ✗ — any field is freely overwritten; no enforcement | ✓ — `BEFORE UPDATE` triggers block frozen columns; append-only `audit_log` |
| Idempotent import / duplicate detection | ✗ — no uniqueness; dedupe is an O(n) scan each time | ✓ — `UNIQUE(import_fingerprint)` + `ON CONFLICT` |
| Grouped reporting with sample sizes, overlapping tags | ✗ — load all, group in Python | ✓ — indexed `GROUP BY`; many-to-many tag table makes overlap explicit |
| Growth | ✗ — rewrite the whole file on every append | ✓ — row-level writes, indexes |
| Backup / integrity check | ~ — copy the file | ✓ — `VACUUM INTO` snapshot + `PRAGMA integrity_check` |
| New dependency | none | **none** — `sqlite3` is in the Python stdlib |

### 1c. Decision — **SQLite, single database file, WAL mode**
Recommended and frozen: **one SQLite database at `data/decision_journal/journal.db`**, opened with
`PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `PRAGMA synchronous=NORMAL`, `busy_timeout=5000`.

- **Single DB, not per-user files.** User isolation is enforced by a `user_id` column + mandatory
  app-layer scoping (§7), which keeps integrity, migration and backup to one file and still gives the
  reporting group-bys a single place to run. Per-user files were rejected: they multiply migration and
  backup surface and give no isolation that a scoped query does not already give at this scale.
- **Why not keep JSON:** it fails atomicity, concurrency and immutability — four of the hard Rev 3
  requirements — and no amount of discipline on a whole-file rewrite fixes the lost-update race.
- The project's "no database, CSV/JSON under `data/`" convention is for the **analytics data
  pipeline** (bulk, regenerated, read-mostly). The journal is **transactional user-owned state** with
  different needs; a stdlib SQLite file under `data/` adds no deployment dependency and does not change
  the pipeline. This exception is scoped to the journal only.

---

## 2. Schema freeze

Expressed as SQLite DDL (the frozen schema artifact). Timestamps are ISO-8601 UTC text; money is
integer **cents** (never float). `NULL` always means *unknown* and is never substituted with a guess.

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE schema_meta (        -- single row; migration bookkeeping
  version      INTEGER NOT NULL,
  applied_at   TEXT    NOT NULL
);

CREATE TABLE tickets (
  ticket_id          TEXT PRIMARY KEY,         -- uuid4
  user_id            TEXT NOT NULL,
  ticket_type        TEXT NOT NULL CHECK (ticket_type IN
                        ('straight','parlay','same-game-parlay','legacy_flat_ticket')),
  record_provenance  TEXT NOT NULL CHECK (record_provenance IN
                        ('prospective-captured','historical-documented',
                         'historical-reconstructed','legacy-flat')),
  book               TEXT,
  game_thesis        TEXT,                      -- frozen at decision time
  game_thesis_at     TEXT,                      -- when the thesis was recorded (must precede kickoff for prospective)
  combined_price     INTEGER,                   -- American odds; actual book payout; no independence caveat
  -- settlement block (book-authoritative; §5 of the spec) --
  book_ticket_result TEXT CHECK (book_ticket_result IN
                        ('win','loss','push','void','cashout','pending') OR book_ticket_result IS NULL),
  cash_stake_cents       INTEGER,
  promo_stake_cents      INTEGER,
  total_returned_cents   INTEGER,
  cashout_amount_cents   INTEGER,
  book_settlement_note   TEXT,
  net_cash_pl_cents      INTEGER,               -- derived ONLY when inputs support it; else NULL (unavailable)
  thesis_correct     INTEGER CHECK (thesis_correct IN (0,1) OR thesis_correct IS NULL), -- SUBJECTIVE user judgment
  import_fingerprint TEXT UNIQUE,               -- idempotent import / dup detection (§6); NULL for manual
  earliest_kickoff   TEXT,                      -- min(leg.event_start); drives the immutability lock (§4)
  placed_at          TEXT,
  settled_at         TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);
CREATE INDEX ix_tickets_user ON tickets(user_id);
CREATE INDEX ix_tickets_prov ON tickets(user_id, record_provenance);

CREATE TABLE legs (
  leg_id             TEXT PRIMARY KEY,          -- uuid4
  ticket_id          TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  leg_index          INTEGER NOT NULL,          -- 0-based order within the ticket
  selection_origin   TEXT NOT NULL CHECK (selection_origin IN
                        ('user-selected','BK-rule-assembled','unknown')),
  entry_method       TEXT NOT NULL CHECK (entry_method IN
                        ('manual','sportsbook-import','BK-builder','migration')),
  user_reviewed_before_bet TEXT NOT NULL CHECK (user_reviewed_before_bet IN ('yes','no','unknown')),
  surfaces_known     INTEGER NOT NULL DEFAULT 1,-- 0 => consulted-surfaces unknown; 1 => known (0..N rows)
  sport              TEXT NOT NULL,
  game               TEXT NOT NULL,
  event_start        TEXT,                      -- kickoff/tip; used for the immutability lock
  player             TEXT,                      -- prop only
  market             TEXT NOT NULL,
  line               REAL,                      -- captured at decision time; NULL = unknown, never inferred
  quote_scope        TEXT NOT NULL CHECK (quote_scope IN ('individual-leg','combined-ticket','unavailable')),
  price              INTEGER,                   -- REQUIRED iff quote_scope='individual-leg'; else NULL
  book               TEXT,
  decision_time      TEXT,                      -- must precede event_start for prospective; may be NULL for historical
  leg_rationale      TEXT,
  leg_rationale_at   TEXT,
  confidence         INTEGER CHECK (confidence BETWEEN 1 AND 5 OR confidence IS NULL), -- personal, not a system score
  alt_line           REAL,
  alt_price          INTEGER,
  leg_result         TEXT CHECK (leg_result IN ('win','loss','push','void','pending') OR leg_result IS NULL),
  read_happened      INTEGER CHECK (read_happened IN (0,1) OR read_happened IS NULL), -- objective, != ticket result
  CHECK (quote_scope != 'individual-leg' OR price IS NOT NULL),  -- combined-only legs are NOT forced to invent a price
  UNIQUE (ticket_id, leg_index)
);
CREATE INDEX ix_legs_ticket ON legs(ticket_id);

CREATE TABLE leg_reason_tags (    -- many-to-many; a leg has >=1, tags OVERLAP (reporting must disclose)
  leg_id  TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  tag     TEXT NOT NULL CHECK (tag IN
            ('streak','coaching','effort','matchup','injuries','pace/game-env','line-value','model','other')),
  PRIMARY KEY (leg_id, tag)
);

CREATE TABLE leg_bk_surfaces (    -- many-to-many; ZERO rows with surfaces_known=1 means "consulted none"
  leg_id  TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  surface TEXT NOT NULL,          -- 'wave-watch','ats-streaks','matchup','heat-map','daily-card',...
  PRIMARY KEY (leg_id, surface)
);

CREATE TABLE audit_log (          -- append-only; every correction to a frozen field lands here
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL,
  ticket_id   TEXT,
  leg_id      TEXT,
  field       TEXT NOT NULL,
  old_value   TEXT,
  new_value   TEXT,
  reason      TEXT NOT NULL,      -- a correction must state why
  actor       TEXT NOT NULL,      -- the acting user/owner id
  created_at  TEXT NOT NULL
);
CREATE INDEX ix_audit_ticket ON audit_log(ticket_id);
```

**Field-to-spec mapping** is 1:1 with Rev 3 §2a/§2b; nothing in the spec is dropped and nothing new is
added beyond the bookkeeping columns (`import_fingerprint`, `earliest_kickoff`, `surfaces_known`,
`schema_meta`, `audit_log`) that the frozen requirements imply.

---

## 3. Atomic operations

All writes use `BEGIN IMMEDIATE` (acquire the write lock up front; no upgrade deadlock) and a single
`COMMIT`; any error → `ROLLBACK`, leaving the DB exactly as before.

- **Create ticket (+legs+tags+surfaces)** — one transaction: insert `tickets`, then each `legs` row,
  then that leg's `leg_reason_tags` and `leg_bk_surfaces`. The whole ticket appears or none of it does.
  `earliest_kickoff` is computed from the legs' `event_start` inside the same transaction.
- **Settlement update** — one transaction: update the ticket settlement block and every leg's
  `leg_result` / `read_happened` together, set `settled_at`. A half-settled ticket is impossible.
- **Idempotent import** — `INSERT … ON CONFLICT(import_fingerprint) DO NOTHING`; the call returns
  "already present" without duplicating (§6).

---

## 4. Immutability of decision-time fields + audited corrections

**Frozen once the ticket locks.** The lock trips at **the earliest leg `event_start`** (kickoff/tip);
for an already-settled ticket it is also locked. Frozen fields:

- ticket: `game_thesis`, `game_thesis_at`, `combined_price`, `record_provenance`, `ticket_type`
- leg: `selection_origin`, `entry_method`, `user_reviewed_before_bet`, `line`, `price`, `quote_scope`,
  `decision_time`, `leg_rationale`, `leg_rationale_at`, `event_start`, `market`, `player`, `game`,
  and the leg's `reason_tags` / `bk_surfaces`

**Mutable after kickoff** (results are only known later): the settlement block, `leg_result`,
`read_happened`, `thesis_correct`, `settled_at`.

**Enforcement** = two layers. (a) App layer refuses a direct edit of a frozen field on a locked ticket.
(b) A `BEFORE UPDATE` trigger on `tickets`/`legs` **raises** if a frozen column changes while
`earliest_kickoff` is in the past, *unless* the same transaction has first written the corresponding
`audit_log` row (the correction path). A correction therefore can never be silent: it must record
`field`, `old_value`, `new_value`, `reason`, `actor`. Design intent — the trigger checks a
transaction-local marker (e.g. a one-row `pragma`/temp flag set only by the audited-correction code
path) so ordinary UPDATEs stay blocked.

---

## 5. Sportsbook imports — idempotency & duplicate detection

- **`import_fingerprint`** = a stable hash of (user_id, book, placed_at rounded to the minute, and each
  leg's game+market+line+side, order-independent). `UNIQUE`, so re-importing the same slip is a no-op.
- **Near-duplicate** (manual entry that matches an existing ticket on user + legs within a time window)
  is **flagged for the user to confirm**, never silently merged or silently rejected — the user owns
  the call. V1 scope note: import itself is **not** built in V1 (§10); the fingerprint column and the
  rule are frozen now so the schema does not change when import arrives.

---

## 6. Migration — reversible, additive, non-destructive

- **Source:** the existing `data/user_bets/<uid>.json` files, read **read-only**. They are never
  modified or deleted by migration.
- **Straight bets** → one-leg tickets, `entry_method='migration'`, `record_provenance='legacy-flat'`,
  `quote_scope` from whether a price was present (`individual-leg` if `odds` known, else `unavailable`),
  `selection_origin='unknown'`, `user_reviewed_before_bet='unknown'`.
- **Parlays / multi-leg** → `ticket_type='legacy_flat_ticket'`; the ticket-level stake/result are
  carried; legs are **not** fabricated — a single placeholder leg marked unreconstructed, or zero legs,
  per what the record actually contains.
- **Reversibility:** because migration only *reads* JSON and *writes* the new DB, rollback is "stop
  using the DB" — the JSON tracker remains the untouched source of truth until a later, separately
  approved cutover. A `migrated_from_json` marker on each migrated ticket lets a reverse pass delete
  exactly the migrated rows if needed. Migration is **idempotent** (keyed by the JSON record id in
  `import_fingerprint`) so re-running it changes nothing.

---

## 7. Account ownership & access isolation

- Every `tickets` row carries `user_id`; `legs`/tags/surfaces inherit it through the ticket.
- **Every** read and write is scoped by the authenticated session `user_id`; there is no unscoped query
  in the design. Owner/admin views are scoped the same way (no implicit cross-user read).
- No endpoint returns another user's rows; reporting group-bys run within one user's partition.

---

## 8. Backup, restore, corruption recovery

- **Backup:** a scheduled `VACUUM INTO 'data/backups/journal_<ts>.db'` snapshot (consistent even while
  the app runs), retained N days. On Windows dev this is a Scheduled Task; on prod a `bk-*` systemd
  timer (installed via SSM like the other units, since units are not auto-created).
- **Integrity:** `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on app start and after each
  backup; a failure alerts (the daily refresh alert path) and does not silently continue.
- **Recovery:** restore the latest good snapshot; any records newer than the snapshot that still exist
  in the JSON source (during the rollout window) can be re-migrated idempotently. WAL gives
  crash-consistency for the in-flight transaction without manual steps.

---

## 9. Compatibility during rollout
- The existing `/tools/tracker` and `services/bet_tracker.py` **keep running unchanged** off their JSON
  store. The Decision Journal is **additive and separate** — new DB, new routes, behind a feature flag.
- No dual-write and no cutover in this phase. A future, separately approved gate decides whether the
  tracker is subsumed; until then both coexist and the JSON tracker stays authoritative for its own UI.

---

## 10. V1 UI scope (frozen — deliberately small)

In V1:
1. **Prospective manual entry** of a ticket and its legs (`entry_method='manual'`,
   `record_provenance='prospective-captured'`), with `decision_time`/`game_thesis` captured pregame.
2. **Individual leg preservation** (leg rows, not a flattened blob), incl. `quote_scope` so SGP
   combined-only pricing is honored and no per-leg price is invented.
3. **Pregame thesis & rationale** capture (ticket `game_thesis`, optional leg `leg_rationale`).
4. **Actual settlement** entry (book result, cash/promo stake, total returned, cashout, note →
   `net_cash_pl` only when inputs support it).
5. **User-selected vs BK-rule-assembled comparison** (the §4.1 cut) with sample sizes.
6. **Straight / parlay / same-game-parlay reporting with sample sizes**, overlapping-tag disclosure,
   and descriptive (non-causal) framing.

**Explicitly OUT of V1:** sportsbook automation, OCR, any model tuning, any causal conclusion, and the
import/near-duplicate UI (schema supports it; UI deferred). Audited-correction UI is minimal (the
schema/trigger enforce it; a full correction console is deferred).

---

## 11. Acceptance tests (QC-style, matching the repo's `qc_*.py` suite — runner-registered)

Each is a deterministic script (no live network), registered in `run_all_scorecards.py`:

| Test | Asserts |
|---|---|
| `qc_dj_concurrency` | two writers (threads/processes) creating + settling under WAL → no lost update, no "database is locked" escaping `busy_timeout`, both results present |
| `qc_dj_crash_recovery` | a transaction killed mid-write leaves **no** partial ticket (ticket/legs/tags all-or-nothing) after reopen |
| `qc_dj_unknown_fields` | NULL `line`/`price`/settlement persist as unknown; nothing is coerced to 0 or −110; reports show "unavailable" |
| `qc_dj_sgp_pricing` | a same-game-parlay with `quote_scope='combined-ticket'` and no per-leg price **saves** (the `CHECK` passes); an `individual-leg` leg with NULL price is **rejected** |
| `qc_dj_push_void` | push/void at leg level → book settlement + `total_returned` drive P/L; no derived "any-leg-loss = ticket loss" override |
| `qc_dj_cashout_promo` | cashout and promotional-stake tickets settle from book inputs; `net_cash_pl` uses cash, excludes promo stake correctly; `NULL` when inputs insufficient |
| `qc_dj_immutability_audit` | editing a frozen field on a locked ticket is blocked; an audited correction writes `audit_log` and succeeds; settlement fields remain editable |
| `qc_dj_import_idempotent` | re-import of the same fingerprint is a no-op; a near-duplicate is flagged, not merged |
| `qc_dj_migration` | straight bets → one-leg tickets, parlays → `legacy_flat_ticket`; re-run changes nothing; JSON source untouched; reverse pass removes only migrated rows |
| `qc_dj_access_isolation` | a query scoped to user A never returns user B's rows; no unscoped path exists |
| `qc_dj_reporting` | every breakdown emits sample sizes; overlapping-tag disclosure present; no causal language; reconstructed/historical excluded from prospective cuts |

---

## 12. One-commit rollback & production migration procedure

- **Feature flag** (`DECISION_JOURNAL_ENABLED`, default off) gates all routes/UI. Shipping dark means
  the DB and code exist but nothing is user-visible until the flag flips.
- **One-commit rollback:** the feature lands as a single squashed commit (or a tight series revertable
  together). Because the DB is **additive** and migration is **non-destructive** to the JSON tracker,
  `git revert <commit>` + restart fully disables the Journal with **zero** data loss to the existing
  tracker. The `journal.db` file can be left in place (inert) or archived.
- **Prod migration:** deploy via the normal `git push origin master` → auto-pull + restart; run the
  one-time migration **once** via SSM (guarded: refuses to run twice via `schema_meta`), take a
  `VACUUM INTO` backup immediately after, then flip the flag. If anything looks wrong, flip the flag
  off (instant) and/or revert the commit (full rollback) — the JSON tracker never stopped being
  authoritative, so there is nothing to reconcile.

---

## 13. What this document is
The frozen design for **one final implementation approval**. It introduces no code and no UI. On
approval, implementation builds exactly this: SQLite store, the §2 schema, the §3 atomic operations,
the §4 immutability/audit rules, §5–§9 operational guarantees, the §10 V1 scope, the §11 tests, and the
§12 rollback/migration procedure — nothing broader.
