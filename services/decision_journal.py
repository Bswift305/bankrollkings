"""Decision Journal — storage + repository service (V1).

Implements `docs/decision_journal_implementation_design.md` (design rev 3). Pure data/service layer:
stdlib only, NO Flask import, so `app.py` imports it without a cycle (like `sport_registry`).

The record contract is frozen in `docs/decision_journal_review_spec.md` (Rev 3). The governing
constraint: **never manufacture precision a sportsbook ticket did not provide** — unknown stays NULL,
the book's settlement is authoritative, nothing causal is claimed.

Everything flows through `JournalRepository`, the single access boundary (every method takes the
authenticated `user_id` and scopes by it). Money is integer cents. Timestamps are ISO-8601 UTC
(`...Z`); all lock/timing comparisons in SQL use `julianday(...)`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# ---- allowlists mirrored from the DDL CHECKs (repository enforces the table-appropriate subset) ----
TICKET_TYPES = ('straight', 'parlay', 'same-game-parlay', 'legacy_flat_ticket')
PROVENANCE = ('prospective-captured', 'historical-documented', 'historical-reconstructed', 'legacy-flat')
SELECTION_ORIGINS = ('user-selected', 'BK-rule-assembled', 'unknown')
ENTRY_METHODS = ('manual', 'sportsbook-import', 'BK-builder', 'migration')
REVIEW_STATES = ('yes', 'no', 'unknown')
QUOTE_SCOPES = ('individual-leg', 'combined-ticket', 'unavailable')
REASON_TAGS = ('streak', 'coaching', 'effort', 'matchup', 'injuries', 'pace/game-env',
               'line-value', 'model', 'other')
LEG_RESULTS = ('win', 'loss', 'push', 'void', 'pending')
TICKET_RESULTS = ('win', 'loss', 'push', 'void', 'cashout', 'pending')

_TICKET_FROZEN = ('game_thesis', 'game_thesis_at', 'combined_price', 'record_provenance',
                  'ticket_type', 'earliest_kickoff', 'import_fingerprint')
_LEG_FROZEN = ('selection_origin', 'entry_method', 'user_reviewed_before_bet', 'surfaces_known',
               'sport', 'game', 'event_start', 'player', 'market', 'selection', 'line', 'quote_scope',
               'price', 'book', 'decision_time', 'leg_rationale', 'leg_rationale_at', 'confidence',
               'alt_line', 'alt_price', 'leg_index')
_ORIGIN_FROZEN = ('surface', 'candidate_id', 'rule_version', 'captured_at', 'displayed_line',
                  'displayed_price')
_MEMBERSHIP_OPS = ('tag:add', 'tag:remove', 'surface:add', 'surface:remove')
REVISION_FIELDS = {
    'tickets': set(_TICKET_FROZEN),
    'legs': set(_LEG_FROZEN),
    'leg_bk_origin': set(_ORIGIN_FROZEN),
    'leg_reason_tags': {'tag:add', 'tag:remove'},
    'leg_bk_surfaces': {'surface:add', 'surface:remove'},
}


class JournalError(Exception):
    """Base for journal errors."""


class ValidationError(JournalError):
    """A record violates the frozen contract (caller/user error)."""


class JournalUnavailable(JournalError):
    """Storage failed an integrity check or could not be opened — journal is disabled (§9)."""


# ---------------------------------------------------------------------------------------------------
# Path + connection
# ---------------------------------------------------------------------------------------------------
def resolve_db_path() -> str:
    """The DB path. `DECISION_JOURNAL_DB_PATH` wins; otherwise a per-platform default that is OUTSIDE
    the deploy checkout (never OneDrive, never the repo) — the real value is set via env in prod."""
    p = (os.environ.get('DECISION_JOURNAL_DB_PATH', '') or '').strip()
    if p:
        return p
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'BankrollKings', 'decision_journal', 'journal.db')
    return '/var/lib/bankrollkings/decision_journal/journal.db'


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        try:
            os.chmod(d, 0o700)  # best-effort; a no-op on Windows ACLs
        except OSError:
            pass


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA synchronous=FULL')     # user-owned records: durability first
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


@contextmanager
def _txn(conn: sqlite3.Connection):
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
    except Exception:
        conn.execute('ROLLBACK')
        raise
    else:
        conn.execute('COMMIT')


# ---------------------------------------------------------------------------------------------------
# Schema (DDL + triggers) — the frozen artifact from the design doc, rev 3
# ---------------------------------------------------------------------------------------------------
_LOCKED = ("((t.earliest_kickoff IS NOT NULL AND julianday(t.earliest_kickoff) <= julianday('now')) "
           "OR t.settled_at IS NOT NULL)")

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  ticket_type TEXT NOT NULL CHECK (ticket_type IN
     ('straight','parlay','same-game-parlay','legacy_flat_ticket')),
  record_provenance TEXT NOT NULL CHECK (record_provenance IN
     ('prospective-captured','historical-documented','historical-reconstructed','legacy-flat')),
  book TEXT,
  game_thesis TEXT,
  game_thesis_at TEXT,
  combined_price INTEGER,
  book_ticket_result TEXT CHECK (book_ticket_result IN
     ('win','loss','push','void','cashout','pending') OR book_ticket_result IS NULL),
  cash_stake_cents INTEGER,
  promo_stake_cents INTEGER,
  total_returned_cents INTEGER,
  cashout_amount_cents INTEGER,
  book_settlement_note TEXT,
  net_cash_pl_cents INTEGER,
  thesis_correct INTEGER CHECK (thesis_correct IN (0,1) OR thesis_correct IS NULL),
  import_fingerprint TEXT UNIQUE,
  migrated_from_json TEXT UNIQUE,
  earliest_kickoff TEXT,
  placed_at TEXT,
  settled_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS ix_tickets_prov ON tickets(user_id, record_provenance);

CREATE TABLE IF NOT EXISTS legs (
  leg_id TEXT PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  leg_index INTEGER NOT NULL,
  selection_origin TEXT NOT NULL CHECK (selection_origin IN ('user-selected','BK-rule-assembled','unknown')),
  entry_method TEXT NOT NULL CHECK (entry_method IN ('manual','sportsbook-import','BK-builder','migration')),
  user_reviewed_before_bet TEXT NOT NULL CHECK (user_reviewed_before_bet IN ('yes','no','unknown')),
  surfaces_known INTEGER NOT NULL DEFAULT 1,
  sport TEXT NOT NULL,
  game TEXT NOT NULL,
  event_start TEXT,
  player TEXT,
  market TEXT NOT NULL,
  selection TEXT NOT NULL,
  line REAL,
  quote_scope TEXT NOT NULL CHECK (quote_scope IN ('individual-leg','combined-ticket','unavailable')),
  price INTEGER,
  book TEXT,
  decision_time TEXT,
  leg_rationale TEXT,
  leg_rationale_at TEXT,
  confidence INTEGER CHECK (confidence BETWEEN 1 AND 5 OR confidence IS NULL),
  alt_line REAL,
  alt_price INTEGER,
  leg_result TEXT CHECK (leg_result IN ('win','loss','push','void','pending') OR leg_result IS NULL),
  read_happened INTEGER CHECK (read_happened IN (0,1) OR read_happened IS NULL),
  CHECK (quote_scope != 'individual-leg' OR price IS NOT NULL),
  UNIQUE (ticket_id, leg_index)
);
CREATE INDEX IF NOT EXISTS ix_legs_ticket ON legs(ticket_id);

CREATE TABLE IF NOT EXISTS leg_reason_tags (
  leg_id TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  tag TEXT NOT NULL CHECK (tag IN
     ('streak','coaching','effort','matchup','injuries','pace/game-env','line-value','model','other')),
  PRIMARY KEY (leg_id, tag)
);

CREATE TABLE IF NOT EXISTS leg_bk_surfaces (
  leg_id TEXT NOT NULL REFERENCES legs(leg_id) ON DELETE CASCADE,
  surface TEXT NOT NULL,
  PRIMARY KEY (leg_id, surface)
);

CREATE TABLE IF NOT EXISTS leg_bk_origin (
  leg_id TEXT PRIMARY KEY REFERENCES legs(leg_id) ON DELETE CASCADE,
  surface TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  displayed_line REAL,
  displayed_price INTEGER
);

CREATE TABLE IF NOT EXISTS decision_revisions (
  revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  target_table TEXT NOT NULL CHECK (target_table IN
     ('tickets','legs','leg_reason_tags','leg_bk_surfaces','leg_bk_origin')),
  target_id TEXT NOT NULL,
  field TEXT NOT NULL CHECK (field IN (
     'game_thesis','game_thesis_at','combined_price','record_provenance','ticket_type',
     'earliest_kickoff','import_fingerprint',
     'selection_origin','entry_method','user_reviewed_before_bet','surfaces_known','sport',
     'game','event_start','player','market','selection','line','quote_scope','price','book',
     'decision_time','leg_rationale','leg_rationale_at','confidence','alt_line','alt_price','leg_index',
     'surface','candidate_id','rule_version','captured_at','displayed_line','displayed_price',
     'tag:add','tag:remove','surface:add','surface:remove')),
  old_value TEXT,
  new_value TEXT,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rev_target ON decision_revisions(target_table, target_id);
""" + f"""
-- ====== immutability + timing triggers (lock predicate uses julianday) ======
CREATE TRIGGER IF NOT EXISTS trg_tickets_freeze BEFORE UPDATE ON tickets FOR EACH ROW
WHEN (OLD.earliest_kickoff IS NOT NULL AND julianday(OLD.earliest_kickoff) <= julianday('now')) OR OLD.settled_at IS NOT NULL
BEGIN
  SELECT CASE WHEN
      NEW.game_thesis IS NOT OLD.game_thesis OR NEW.game_thesis_at IS NOT OLD.game_thesis_at
   OR NEW.combined_price IS NOT OLD.combined_price OR NEW.record_provenance IS NOT OLD.record_provenance
   OR NEW.ticket_type IS NOT OLD.ticket_type OR NEW.earliest_kickoff IS NOT OLD.earliest_kickoff
   OR NEW.import_fingerprint IS NOT OLD.import_fingerprint
  THEN RAISE(ABORT,'frozen ticket field') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_legs_freeze BEFORE UPDATE ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = OLD.ticket_id AND {_LOCKED})
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
  THEN RAISE(ABORT,'frozen leg field') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_legs_no_insert BEFORE INSERT ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = NEW.ticket_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'leg insert after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_legs_no_delete BEFORE DELETE ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = OLD.ticket_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'leg delete after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_tags_no_insert BEFORE INSERT ON leg_reason_tags FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = NEW.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'reason-tag insert after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_tags_no_delete BEFORE DELETE ON leg_reason_tags FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = OLD.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'reason-tag delete after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_surfaces_no_insert BEFORE INSERT ON leg_bk_surfaces FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = NEW.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'surface insert after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_surfaces_no_delete BEFORE DELETE ON leg_bk_surfaces FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = OLD.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'surface delete after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_bkorigin_no_insert BEFORE INSERT ON leg_bk_origin FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = NEW.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'bk_origin insert after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_bkorigin_no_update BEFORE UPDATE ON leg_bk_origin FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = OLD.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'bk_origin update after lock'); END;

CREATE TRIGGER IF NOT EXISTS trg_bkorigin_no_delete BEFORE DELETE ON leg_bk_origin FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM legs l JOIN tickets t ON t.ticket_id = l.ticket_id WHERE l.leg_id = OLD.leg_id AND {_LOCKED})
BEGIN SELECT RAISE(ABORT,'bk_origin delete after lock'); END;

-- captured_at must not postdate the leg decision (julianday)
CREATE TRIGGER IF NOT EXISTS trg_bkorigin_capture_timing BEFORE INSERT ON leg_bk_origin FOR EACH ROW
BEGIN
  SELECT CASE WHEN EXISTS (SELECT 1 FROM legs l WHERE l.leg_id = NEW.leg_id
             AND l.decision_time IS NOT NULL AND julianday(NEW.captured_at) > julianday(l.decision_time))
         THEN RAISE(ABORT,'bk_origin captured_at after decision_time') END;
END;

-- prospective timing (julianday)
CREATE TRIGGER IF NOT EXISTS trg_legs_prospective BEFORE INSERT ON legs FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = NEW.ticket_id AND t.record_provenance='prospective-captured')
BEGIN
  SELECT CASE WHEN NEW.event_start IS NULL THEN RAISE(ABORT,'prospective leg requires event_start') END;
  SELECT CASE WHEN NEW.decision_time IS NULL OR julianday(NEW.decision_time) >= julianday(NEW.event_start)
         THEN RAISE(ABORT,'decision_time must precede event_start') END;
  SELECT CASE WHEN NEW.leg_rationale_at IS NOT NULL AND julianday(NEW.leg_rationale_at) >= julianday(NEW.event_start)
         THEN RAISE(ABORT,'leg rationale after event start') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_ticket_thesis_timing BEFORE UPDATE OF earliest_kickoff ON tickets FOR EACH ROW
WHEN NEW.record_provenance='prospective-captured' AND NEW.game_thesis_at IS NOT NULL
BEGIN
  SELECT CASE WHEN julianday(NEW.game_thesis_at) >= julianday(NEW.earliest_kickoff)
         THEN RAISE(ABORT,'thesis after kickoff') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_rev_no_update BEFORE UPDATE ON decision_revisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_rev_no_delete BEFORE DELETE ON decision_revisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""


def init_db(path: str | None = None) -> str:
    """Create the schema + triggers if absent. Idempotent. Returns the path used."""
    path = path or resolve_db_path()
    _ensure_dir(path)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        row = conn.execute('SELECT version FROM schema_meta WHERE id=1').fetchone()
        if row is None:
            conn.execute('INSERT INTO schema_meta(id, version, applied_at) VALUES (1, ?, ?)',
                         (SCHEMA_VERSION, _utcnow()))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        conn.close()
    return path


# ---------------------------------------------------------------------------------------------------
# Settlement math (§6)
# ---------------------------------------------------------------------------------------------------
def compute_net_cash_pl(cash_stake_cents, total_returned_cents, book_ticket_result, cashout_amount_cents):
    """net = total_returned - cash_stake, ONLY when inputs suffice; else None (unavailable)."""
    if cash_stake_cents is None or total_returned_cents is None:
        return None
    if book_ticket_result == 'cashout' and cashout_amount_cents is None:
        return None
    return int(total_returned_cents) - int(cash_stake_cents)


def compute_roi(net_cash_pl_cents, cash_stake_cents):
    """ROI = net / cash_stake. None when net is unavailable OR cash_stake is 0 (zero denominator)."""
    if net_cash_pl_cents is None or cash_stake_cents is None or int(cash_stake_cents) == 0:
        return None
    return net_cash_pl_cents / float(cash_stake_cents)


def compute_fingerprint(user_id, book, placed_at, legs):
    """Stable, order-independent hash over (user, book, placed_at-to-minute, each leg's
    game|market|selection|line). Includes `selection` (blocker 1)."""
    minute = (placed_at or '')[:16]  # YYYY-MM-DDTHH:MM
    parts = sorted('{}|{}|{}|{}'.format(
        (l.get('game') or '').strip().lower(),
        (l.get('market') or '').strip().lower(),
        (l.get('selection') or '').strip().lower(),
        '' if l.get('line') is None else repr(float(l['line'])),
    ) for l in legs)
    blob = '\x1e'.join([str(user_id), (book or '').strip().lower(), minute] + parts)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------------------------------
# Repository — the single access boundary (every method takes + scopes by user_id)
# ---------------------------------------------------------------------------------------------------
class JournalRepository:
    def __init__(self, db_path: str | None = None, auto_init: bool = True):
        self.db_path = db_path or resolve_db_path()
        if auto_init:
            init_db(self.db_path)

    # -- connection + availability -----------------------------------------------------------------
    def _open(self) -> sqlite3.Connection:
        try:
            return connect(self.db_path)
        except sqlite3.Error as e:
            raise JournalUnavailable(f'cannot open journal store: {e}') from e

    def integrity_ok(self) -> bool:
        try:
            conn = self._open()
        except JournalUnavailable:
            return False
        try:
            r = conn.execute('PRAGMA integrity_check').fetchone()
            fk = conn.execute('PRAGMA foreign_key_check').fetchall()
            return bool(r) and r[0] == 'ok' and not fk
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    def _gate(self) -> None:
        """Raise JournalUnavailable if the store fails its integrity check (§9). Callers catch this
        and show 'Journal temporarily unavailable' — it never propagates to unrelated pages."""
        if not self.integrity_ok():
            raise JournalUnavailable('journal integrity check failed')

    # -- create ------------------------------------------------------------------------------------
    def create_ticket(self, user_id, *, ticket_type, record_provenance, legs,
                       book=None, game_thesis=None, game_thesis_at=None, combined_price=None,
                       placed_at=None, import_fingerprint=None, migrated_from_json=None):
        """Atomically create a ticket + its legs + tags + surfaces + BK-origin rows. All-or-nothing.
        Returns the new ticket_id. Validates the frozen contract before COMMIT; triggers enforce
        timing/immutability; the whole transaction rolls back on any violation."""
        if not user_id:
            raise ValidationError('user_id required')
        if ticket_type not in TICKET_TYPES:
            raise ValidationError(f'bad ticket_type {ticket_type!r}')
        if record_provenance not in PROVENANCE:
            raise ValidationError(f'bad record_provenance {record_provenance!r}')
        legs = list(legs or [])
        if ticket_type == 'legacy_flat_ticket':
            if legs:
                raise ValidationError('legacy_flat_ticket carries ZERO legs (no placeholder)')
        if record_provenance == 'prospective-captured' and not legs:
            raise ValidationError('prospective-captured ticket requires >=1 leg')
        for i, leg in enumerate(legs):
            self._validate_leg(leg, i)

        self._gate()
        tid = str(uuid.uuid4())
        now = _utcnow()
        conn = self._open()
        try:
            with _txn(conn):
                conn.execute(
                    """INSERT INTO tickets(ticket_id,user_id,ticket_type,record_provenance,book,
                         game_thesis,game_thesis_at,combined_price,import_fingerprint,migrated_from_json,
                         earliest_kickoff,placed_at,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)""",
                    (tid, str(user_id), ticket_type, record_provenance, book, game_thesis,
                     game_thesis_at, combined_price, import_fingerprint, migrated_from_json,
                     placed_at, now, now))
                for i, leg in enumerate(legs):
                    self._insert_leg(conn, tid, i, leg)
                # set earliest_kickoff from the legs (fires thesis-timing trigger for prospective)
                ek = conn.execute(
                    'SELECT min(event_start) FROM legs WHERE ticket_id=? AND event_start IS NOT NULL',
                    (tid,)).fetchone()[0]
                conn.execute('UPDATE tickets SET earliest_kickoff=?, updated_at=? WHERE ticket_id=?',
                             (ek, now, tid))
                # validate BK-origin presence BEFORE COMMIT (blocker 2: no AFTER-INSERT trigger)
                orphan = conn.execute(
                    """SELECT 1 FROM legs WHERE ticket_id=? AND selection_origin='BK-rule-assembled'
                       AND leg_id NOT IN (SELECT leg_id FROM leg_bk_origin) LIMIT 1""", (tid,)).fetchone()
                if orphan:
                    raise ValidationError('BK-rule-assembled leg missing its leg_bk_origin reference')
        except sqlite3.IntegrityError as e:
            raise ValidationError(str(e)) from e
        finally:
            conn.close()
        return tid

    def _validate_leg(self, leg, idx):
        if not (leg.get('selection') or '').strip():
            raise ValidationError(f'leg {idx}: selection (the pick) is required')
        if leg.get('selection_origin') not in SELECTION_ORIGINS:
            raise ValidationError(f'leg {idx}: bad selection_origin')
        if leg.get('entry_method') not in ENTRY_METHODS:
            raise ValidationError(f'leg {idx}: bad entry_method')
        if leg.get('user_reviewed_before_bet') not in REVIEW_STATES:
            raise ValidationError(f'leg {idx}: bad user_reviewed_before_bet')
        qs = leg.get('quote_scope')
        if qs not in QUOTE_SCOPES:
            raise ValidationError(f'leg {idx}: bad quote_scope')
        if qs == 'individual-leg' and leg.get('price') is None:
            raise ValidationError(f'leg {idx}: individual-leg quote requires a price')
        if qs != 'individual-leg' and leg.get('price') is not None:
            raise ValidationError(f'leg {idx}: non-individual quote must not carry a per-leg price')
        for t in (leg.get('reason_tags') or []):
            if t not in REASON_TAGS:
                raise ValidationError(f'leg {idx}: bad reason_tag {t!r}')
        if leg.get('selection_origin') == 'BK-rule-assembled' and not leg.get('bk_origin'):
            raise ValidationError(f'leg {idx}: BK-rule-assembled requires a bk_origin reference')

    def _insert_leg(self, conn, tid, idx, leg):
        lid = str(uuid.uuid4())
        surfaces = list(leg.get('surfaces') or [])
        surfaces_known = 1 if leg.get('surfaces_known', True) else 0
        conn.execute(
            """INSERT INTO legs(leg_id,ticket_id,leg_index,selection_origin,entry_method,
                 user_reviewed_before_bet,surfaces_known,sport,game,event_start,player,market,selection,
                 line,quote_scope,price,book,decision_time,leg_rationale,leg_rationale_at,confidence,
                 alt_line,alt_price,leg_result,read_happened)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lid, tid, idx, leg.get('selection_origin'), leg.get('entry_method'),
             leg.get('user_reviewed_before_bet'), surfaces_known, leg.get('sport'), leg.get('game'),
             leg.get('event_start'), leg.get('player'), leg.get('market'), leg.get('selection'),
             leg.get('line'), leg.get('quote_scope'), leg.get('price'), leg.get('book'),
             leg.get('decision_time'), leg.get('leg_rationale'), leg.get('leg_rationale_at'),
             leg.get('confidence'), leg.get('alt_line'), leg.get('alt_price'),
             leg.get('leg_result'), leg.get('read_happened')))
        for t in dict.fromkeys(leg.get('reason_tags') or []):
            conn.execute('INSERT INTO leg_reason_tags(leg_id,tag) VALUES(?,?)', (lid, t))
        if surfaces_known:
            for s in dict.fromkeys(surfaces):
                conn.execute('INSERT INTO leg_bk_surfaces(leg_id,surface) VALUES(?,?)', (lid, s))
        o = leg.get('bk_origin')
        if o:
            conn.execute(
                """INSERT INTO leg_bk_origin(leg_id,surface,candidate_id,rule_version,captured_at,
                     displayed_line,displayed_price) VALUES(?,?,?,?,?,?,?)""",
                (lid, o.get('surface'), o.get('candidate_id'), o.get('rule_version'),
                 o.get('captured_at'), o.get('displayed_line'), o.get('displayed_price')))
        return lid

    # -- settle ------------------------------------------------------------------------------------
    def settle_ticket(self, user_id, ticket_id, *, book_ticket_result, cash_stake_cents=None,
                      promo_stake_cents=None, total_returned_cents=None, cashout_amount_cents=None,
                      book_settlement_note=None, thesis_correct=None, leg_results=None):
        """Record the book-authoritative settlement + per-leg results, atomically. Settlement columns
        are NOT frozen, so this succeeds after kickoff. net_cash_pl derived per §6 (NULL when short)."""
        if book_ticket_result not in TICKET_RESULTS:
            raise ValidationError(f'bad book_ticket_result {book_ticket_result!r}')
        self._gate()
        net = compute_net_cash_pl(cash_stake_cents, total_returned_cents, book_ticket_result,
                                  cashout_amount_cents)
        now = _utcnow()
        conn = self._open()
        try:
            with _txn(conn):
                cur = conn.execute(
                    """UPDATE tickets SET book_ticket_result=?,cash_stake_cents=?,promo_stake_cents=?,
                         total_returned_cents=?,cashout_amount_cents=?,book_settlement_note=?,
                         net_cash_pl_cents=?,thesis_correct=?,settled_at=?,updated_at=?
                       WHERE ticket_id=? AND user_id=?""",
                    (book_ticket_result, cash_stake_cents, promo_stake_cents, total_returned_cents,
                     cashout_amount_cents, book_settlement_note, net, thesis_correct, now, now,
                     ticket_id, str(user_id)))
                if cur.rowcount == 0:
                    raise ValidationError('ticket not found for this user')
                for lr in (leg_results or []):
                    conn.execute(
                        """UPDATE legs SET leg_result=?, read_happened=?
                           WHERE leg_id=? AND ticket_id=?""",
                        (lr.get('leg_result'), lr.get('read_happened'), lr.get('leg_id'), ticket_id))
        finally:
            conn.close()
        return net

    # -- correct (append-only) ---------------------------------------------------------------------
    def correct(self, user_id, target_table, target_id, field, new_value, reason, actor):
        """The ONLY post-lock edit path: append a typed-JSON revision. Base rows stay immutable."""
        if target_table not in REVISION_FIELDS or field not in REVISION_FIELDS[target_table]:
            raise ValidationError(f'field {field!r} not correctable on {target_table!r}')
        if not (reason or '').strip():
            raise ValidationError('a correction must state a reason')
        self._gate()
        now = _utcnow()
        conn = self._open()
        try:
            self._assert_owns_target(conn, user_id, target_table, target_id)
            old = self._effective(conn, target_table, target_id, field)
            with _txn(conn):
                conn.execute(
                    """INSERT INTO decision_revisions(user_id,target_table,target_id,field,old_value,
                         new_value,reason,actor,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (str(user_id), target_table, target_id, field, json.dumps(old),
                     json.dumps(new_value), reason, actor, now))
        finally:
            conn.close()

    def _assert_owns_target(self, conn, user_id, target_table, target_id):
        if target_table == 'tickets':
            row = conn.execute('SELECT user_id FROM tickets WHERE ticket_id=?', (target_id,)).fetchone()
        else:  # leg-scoped tables key on leg_id
            row = conn.execute(
                """SELECT t.user_id FROM legs l JOIN tickets t ON t.ticket_id=l.ticket_id
                   WHERE l.leg_id=?""", (target_id,)).fetchone()
        if not row or str(row[0]) != str(user_id):
            raise ValidationError('target not found for this user')

    def _effective(self, conn, target_table, target_id, field):
        rev = conn.execute(
            """SELECT new_value FROM decision_revisions WHERE target_table=? AND target_id=? AND field=?
               ORDER BY revision_id DESC LIMIT 1""", (target_table, target_id, field)).fetchone()
        if rev is not None:
            return json.loads(rev[0])
        if field in _MEMBERSHIP_OPS:
            return None
        if target_table == 'tickets':
            r = conn.execute(f'SELECT {field} FROM tickets WHERE ticket_id=?', (target_id,)).fetchone()
        elif target_table == 'legs':
            r = conn.execute(f'SELECT {field} FROM legs WHERE leg_id=?', (target_id,)).fetchone()
        elif target_table == 'leg_bk_origin':
            r = conn.execute(f'SELECT {field} FROM leg_bk_origin WHERE leg_id=?', (target_id,)).fetchone()
        else:
            r = None
        return (r[0] if r else None)

    def effective_value(self, user_id, target_table, target_id, field):
        conn = self._open()
        try:
            self._assert_owns_target(conn, user_id, target_table, target_id)
            return self._effective(conn, target_table, target_id, field)
        finally:
            conn.close()

    # -- reads -------------------------------------------------------------------------------------
    def get_ticket(self, user_id, ticket_id):
        conn = self._open()
        try:
            t = conn.execute('SELECT * FROM tickets WHERE ticket_id=? AND user_id=?',
                             (ticket_id, str(user_id))).fetchone()
            if not t:
                return None
            ticket = dict(t)
            legs = [dict(r) for r in conn.execute(
                'SELECT * FROM legs WHERE ticket_id=? ORDER BY leg_index', (ticket_id,)).fetchall()]
            for leg in legs:
                leg['reason_tags'] = [r[0] for r in conn.execute(
                    'SELECT tag FROM leg_reason_tags WHERE leg_id=? ORDER BY tag', (leg['leg_id'],)).fetchall()]
                leg['surfaces'] = [r[0] for r in conn.execute(
                    'SELECT surface FROM leg_bk_surfaces WHERE leg_id=? ORDER BY surface', (leg['leg_id'],)).fetchall()]
                o = conn.execute('SELECT * FROM leg_bk_origin WHERE leg_id=?', (leg['leg_id'],)).fetchone()
                leg['bk_origin'] = dict(o) if o else None
            ticket['legs'] = legs
            ticket['roi'] = compute_roi(ticket.get('net_cash_pl_cents'), ticket.get('cash_stake_cents'))
            return ticket
        finally:
            conn.close()

    def list_tickets(self, user_id, limit=200):
        conn = self._open()
        try:
            rows = conn.execute(
                """SELECT ticket_id,ticket_type,record_provenance,book,book_ticket_result,
                     net_cash_pl_cents,cash_stake_cents,earliest_kickoff,placed_at,settled_at,created_at
                   FROM tickets WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
                (str(user_id), int(limit))).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d['roi'] = compute_roi(d.get('net_cash_pl_cents'), d.get('cash_stake_cents'))
                d['legs_count'] = conn.execute(
                    'SELECT count(*) FROM legs WHERE ticket_id=?', (d['ticket_id'],)).fetchone()[0]
                out.append(d)
            return out
        finally:
            conn.close()

    # -- descriptive reporting (no tuning, no causal claims) ---------------------------------------
    def report(self, user_id, prospective_only=True):
        """Descriptive record with sample sizes. Only prospective-captured records enter the
        decision-quality cuts; historical/reconstructed are reported separately. Overlapping reason
        tags are disclosed; differences are descriptive, never causal."""
        conn = self._open()
        try:
            prov_sql = " AND t.record_provenance='prospective-captured'" if prospective_only else ''
            # by selection origin (leg-level record)
            by_origin = {}
            for origin in ('user-selected', 'BK-rule-assembled'):
                rows = conn.execute(
                    f"""SELECT l.leg_result, count(*) n FROM legs l JOIN tickets t ON t.ticket_id=l.ticket_id
                        WHERE t.user_id=? AND l.selection_origin=?{prov_sql}
                        GROUP BY l.leg_result""", (str(user_id), origin)).fetchall()
                by_origin[origin] = self._tally(rows)
            # by ticket type (ticket-level record + P/L)
            by_type = {}
            for tt in ('straight', 'parlay', 'same-game-parlay'):
                rows = conn.execute(
                    f"""SELECT book_ticket_result res, count(*) n,
                           sum(net_cash_pl_cents) pl, sum(net_cash_pl_cents IS NULL) pl_missing,
                           sum(CASE WHEN cash_stake_cents=0 THEN 1 ELSE 0 END) zero_stake
                        FROM tickets t WHERE t.user_id=? AND t.ticket_type=?{prov_sql}
                        GROUP BY book_ticket_result""", (str(user_id), tt)).fetchall()
                by_type[tt] = self._tally_tickets(rows)
            # reason tags (overlapping!) — leg-level
            tag_rows = conn.execute(
                f"""SELECT rt.tag, l.leg_result, count(*) n
                    FROM leg_reason_tags rt JOIN legs l ON l.leg_id=rt.leg_id
                    JOIN tickets t ON t.ticket_id=l.ticket_id
                    WHERE t.user_id=?{prov_sql} GROUP BY rt.tag, l.leg_result""",
                (str(user_id),)).fetchall()
            by_tag = {}
            for tag, res, n in tag_rows:
                by_tag.setdefault(tag, {'win': 0, 'loss': 0, 'push': 0, 'void': 0, 'pending': 0, 'n': 0})
                by_tag[tag][res or 'pending'] = n
                by_tag[tag]['n'] += n
            return {
                'by_origin': by_origin,
                'by_ticket_type': by_type,
                'by_reason_tag': by_tag,
                'disclosures': {
                    'overlapping_tags': ('Reason tags overlap — a leg can carry several, so the per-tag '
                                         'rows are not mutually exclusive and do not sum to the total.'),
                    'descriptive_only': ('Descriptive record of what happened, with sample sizes. Not '
                                         'causal evidence and not a recommendation.'),
                    'prospective_only': prospective_only,
                },
            }
        finally:
            conn.close()

    @staticmethod
    def _tally(rows):
        d = {'win': 0, 'loss': 0, 'push': 0, 'void': 0, 'pending': 0, 'n': 0}
        for res, n in rows:
            d[res or 'pending'] = n
            d['n'] += n
        return d

    @staticmethod
    def _tally_tickets(rows):
        d = {'win': 0, 'loss': 0, 'push': 0, 'void': 0, 'cashout': 0, 'pending': 0, 'n': 0,
             'net_cash_pl_cents': 0, 'pl_available': True, 'any_zero_stake': False}
        for res, n, pl, pl_missing, zero_stake in rows:
            d[res or 'pending'] = n
            d['n'] += n
            d['net_cash_pl_cents'] += int(pl or 0)
            if pl_missing:
                d['pl_available'] = False
            if zero_stake:
                d['any_zero_stake'] = True
        # ROI only when every ticket in the bucket has P/L and no zero-stake (zero denominator)
        if not d['pl_available'] or d['any_zero_stake'] or d['n'] == 0:
            d['roi'] = None
        else:
            stake = 0
            d['roi'] = None  # ticket-bucket ROI requires stake sum; computed in report consumer if needed
        return d

    # -- integrity + orphan checks (startup + QC) --------------------------------------------------
    def integrity_report(self):
        issues = []
        if not self.integrity_ok():
            return {'ok': False, 'issues': ['integrity_check/foreign_key_check failed']}
        conn = self._open()
        try:
            orphan = conn.execute(
                """SELECT count(*) FROM legs WHERE selection_origin='BK-rule-assembled'
                   AND leg_id NOT IN (SELECT leg_id FROM leg_bk_origin)""").fetchone()[0]
            if orphan:
                issues.append(f'{orphan} BK-rule-assembled legs missing leg_bk_origin')
            bad_prosp = conn.execute(
                """SELECT count(*) FROM tickets t WHERE t.record_provenance='prospective-captured'
                   AND (SELECT count(*) FROM legs l WHERE l.ticket_id=t.ticket_id)=0""").fetchone()[0]
            if bad_prosp:
                issues.append(f'{bad_prosp} prospective tickets with zero legs')
            bad_legacy = conn.execute(
                """SELECT count(*) FROM tickets t WHERE t.ticket_type='legacy_flat_ticket'
                   AND (SELECT count(*) FROM legs l WHERE l.ticket_id=t.ticket_id)>0""").fetchone()[0]
            if bad_legacy:
                issues.append(f'{bad_legacy} legacy_flat_ticket rows with legs')
        finally:
            conn.close()
        return {'ok': not issues, 'issues': issues}

    # -- migration from the existing JSON tracker (reversible, non-destructive) --------------------
    def migrate_user_json(self, user_id, bets):
        """Migrate a user's flat bet_tracker records (read-only input) into the journal. Straight bets
        -> one-leg tickets; parlays/multi-leg -> legacy_flat_ticket with ZERO legs. Idempotent via
        migrated_from_json UNIQUE. `bets` is a list of the tracker's bet dicts. Returns #migrated."""
        self._gate()
        migrated = 0
        for b in (bets or []):
            jid = str(b.get('id') or '').strip()
            if not jid:
                continue
            marker = f'{user_id}:{jid}'
            conn = self._open()
            try:
                exists = conn.execute('SELECT 1 FROM tickets WHERE migrated_from_json=?', (marker,)).fetchone()
            finally:
                conn.close()
            if exists:
                continue
            is_parlay = bool(b.get('legs')) or str(b.get('bet_type') or '').lower() == 'parlay'
            result = _map_result(b.get('result'))
            stake_cents = _to_cents(b.get('stake'))
            try:
                if is_parlay:
                    self.create_ticket(
                        user_id, ticket_type='legacy_flat_ticket', record_provenance='legacy-flat',
                        legs=[], book=b.get('book'), placed_at=_iso_date(b.get('placed')),
                        migrated_from_json=marker)
                    self._settle_legacy(user_id, marker, result, stake_cents, b)
                else:
                    price = b.get('odds')
                    leg = {
                        'selection_origin': 'unknown', 'entry_method': 'migration',
                        'user_reviewed_before_bet': 'unknown', 'surfaces_known': False, 'surfaces': [],
                        'sport': str(b.get('sport') or 'Other'), 'game': str(b.get('description') or '')[:200] or 'unknown',
                        'event_start': None, 'player': None,
                        'market': str(b.get('description') or 'unknown')[:120] or 'unknown',
                        'selection': str(b.get('selection') or 'unknown')[:200] or 'unknown',
                        'line': None,
                        'quote_scope': 'individual-leg' if price not in (None, '') else 'unavailable',
                        'price': _to_american(price) if price not in (None, '') else None,
                        'book': b.get('book'), 'decision_time': None,
                        'reason_tags': ['other'], 'leg_result': result if result != 'cashout' else 'pending',
                    }
                    self.create_ticket(
                        user_id, ticket_type='straight', record_provenance='legacy-flat', legs=[leg],
                        book=b.get('book'), placed_at=_iso_date(b.get('placed')), migrated_from_json=marker)
                    self._settle_legacy(user_id, marker, result, stake_cents, b)
                migrated += 1
            except (ValidationError, sqlite3.Error):
                continue  # skip a record we cannot faithfully represent; never fabricate
        return migrated

    def _settle_legacy(self, user_id, marker, result, stake_cents, b):
        if result == 'pending':
            return
        conn = self._open()
        try:
            row = conn.execute('SELECT ticket_id FROM tickets WHERE migrated_from_json=?', (marker,)).fetchone()
        finally:
            conn.close()
        if not row:
            return
        self.settle_ticket(user_id, row[0], book_ticket_result=result,
                           cash_stake_cents=stake_cents, book_settlement_note='migrated from tracker')

    def reverse_migration(self, user_id):
        """Delete exactly the rows this user migrated from JSON (reverse pass). Legs cascade."""
        conn = self._open()
        try:
            with _txn(conn):
                conn.execute('DELETE FROM tickets WHERE user_id=? AND migrated_from_json IS NOT NULL',
                             (str(user_id),))
        finally:
            conn.close()


def _map_result(r):
    r = str(r or '').strip().lower()
    return {'win': 'win', 'won': 'win', 'loss': 'loss', 'lost': 'loss', 'lose': 'loss',
            'push': 'push', 'void': 'void', 'cashout': 'cashout'}.get(r, 'pending')


def _to_cents(v):
    try:
        if v in (None, ''):
            return None
        return int(round(float(str(v).replace(',', '').replace('$', '')) * 100))
    except (TypeError, ValueError):
        return None


def _to_american(v):
    try:
        return int(round(float(str(v).replace('+', ''))))
    except (TypeError, ValueError):
        return None


def _iso_date(d):
    s = str(d or '').strip()
    if not s:
        return None
    return s if 'T' in s else f'{s}T00:00:00Z'
