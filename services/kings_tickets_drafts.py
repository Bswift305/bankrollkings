"""King's Tickets — server-side EPHEMERAL active-draft store (Step 4, DARK).

One editable draft per account, kept at most 24h after the last edit, overwrite-only, NO outcomes/
settlement/result fields, NOT placed-bet history and NOT the Decision Journal (which stays dark). This
module is the schema + repository + service + purge; it writes NOTHING in production until the flag
`KINGS_TICKETS_DRAFTS_ENABLED` is turned on (default "0"). No routes, no autosave UI, no flag flip here.

Store: `$BK_RUNTIME_DIR/kings_tickets/active_drafts.db` (dir 0700, db 0600). WAL + synchronous=FULL +
foreign_keys=ON + busy_timeout. One row per account (UNIQUE(account_user_id)); optimistic revision/CAS so
two tabs cannot silently overwrite each other; transactional draft+legs replacement. Corruption or
unavailability disables ONLY draft persistence (callers treat a raised StoreUnavailable as "no draft"),
never the rest of the site, and never falls back to the Decision Journal. No backups (ephemeral scratch).
Unknown leg fields stay NULL — never fabricated.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1
DRAFT_TTL_SECONDS = 24 * 3600
MIN_LEGS = 2
MAX_LEGS = 5
MAX_STR = 400                      # per-string length cap (reject longer)
VALID_QUOTE_STATES = ('current', 'stale', 'missing', 'unknown')

# Full-fidelity leg columns (all nullable except position/canonical key). Mirrors the rejected-SGP-loss
# contract: event/player/team/market/side/line/price/scope/book/source/timestamps/origin/entry/reason.
LEG_COLUMNS = (
    'canonical_leg_id', 'sport', 'league', 'event_id', 'event_start',
    'player_id', 'player_name', 'team_id', 'team_name',
    'market_key', 'direction', 'line', 'price', 'price_format', 'sportsbook',
    'quote_scope', 'source_provider', 'source_timestamp', 'selection_origin', 'entry_method',
    'reason_rule_id', 'display_label', 'quote_state', 'inserted_at', 'last_validated_at',
)
_NUMERIC = {'line', 'price'}


class StoreUnavailable(Exception):
    """The draft store could not be opened/used — callers degrade to 'no draft', never crash the site."""


class DraftConflict(Exception):
    """Optimistic-concurrency failure: another tab saved a newer revision. Caller offers reload/overwrite."""


class DraftInvalid(Exception):
    """The submitted draft violated a hard rule (leg count, duplicate canonical leg, limits, bad enum)."""


def drafts_enabled() -> bool:
    """Dark by default. Production create/update/UI stay off until an operator sets this to 1."""
    return str(os.environ.get('KINGS_TICKETS_DRAFTS_ENABLED', '0')).strip().lower() in ('1', 'true', 'yes', 'on')


def _default_db_path() -> Path:
    base = os.environ.get('BK_RUNTIME_DIR') or '/var/lib/bankrollkings'
    return Path(base) / 'kings_tickets' / 'active_drafts.db'


DDL = """
CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL CHECK(version > 0));
CREATE TABLE IF NOT EXISTS drafts(
  account_user_id TEXT NOT NULL UNIQUE,            -- one active draft per account
  draft_id        TEXT NOT NULL PRIMARY KEY,
  revision        INTEGER NOT NULL CHECK(revision > 0),
  leg_count       INTEGER NOT NULL CHECK(leg_count BETWEEN 2 AND 5),
  originating_surface TEXT,
  risk_amount     REAL,                            -- only if the user entered one; NULL otherwise
  combined_price            INTEGER,               -- ONLY when a sportsbook supplied a combined quote
  combined_price_source     TEXT,
  combined_price_scope      TEXT,
  combined_price_timestamp  TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  expires_at      INTEGER NOT NULL
  -- deliberately NO result/settlement/win-loss/graded columns: this is a draft, never history.
);
CREATE TABLE IF NOT EXISTS draft_legs(
  draft_id          TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
  position          INTEGER NOT NULL,
  canonical_leg_id  TEXT NOT NULL,
  sport TEXT, league TEXT, event_id TEXT, event_start TEXT,
  player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  market_key TEXT, direction TEXT, line REAL, price INTEGER, price_format TEXT, sportsbook TEXT,
  quote_scope TEXT, source_provider TEXT, source_timestamp TEXT, selection_origin TEXT, entry_method TEXT,
  reason_rule_id TEXT, display_label TEXT,
  quote_state TEXT NOT NULL CHECK(quote_state IN ('current','stale','missing','unknown')),
  inserted_at TEXT, last_validated_at TEXT,
  PRIMARY KEY(draft_id, position),
  UNIQUE(draft_id, canonical_leg_id)               -- unique canonical legs within a draft
);
CREATE INDEX IF NOT EXISTS idx_drafts_expires ON drafts(expires_at);
"""


def _canonical_key(leg: dict) -> str:
    """A stable identity for duplicate detection when the client did not supply a canonical_leg_id. Derived
    ONLY from identity fields the client sent; it fabricates no market data."""
    parts = [str(leg.get(k) or '').strip().lower() for k in
             ('sport', 'event_id', 'market_key', 'direction', 'line', 'player_id', 'player_name',
              'team_id', 'team_name', 'display_label')]
    return 'ck_' + hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:24]


def _clean(value):
    """Normalize a submitted value: '' / None -> NULL (unknown stays NULL, never fabricated). Enforce the
    string-length cap. Numbers pass through."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text == '':
        return None
    if len(text) > MAX_STR:
        raise DraftInvalid(f'field exceeds {MAX_STR} chars')
    return text


def _validate_legs(legs):
    if not isinstance(legs, (list, tuple)):
        raise DraftInvalid('legs must be a list')
    if not (MIN_LEGS <= len(legs) <= MAX_LEGS):
        raise DraftInvalid(f'a draft must have {MIN_LEGS}-{MAX_LEGS} legs (got {len(legs)})')
    rows, seen = [], set()
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise DraftInvalid('each leg must be an object')
        row = {}
        for col in LEG_COLUMNS:
            if col in ('inserted_at', 'last_validated_at'):
                continue
            v = _clean(leg.get(col))
            if col in _NUMERIC and v is not None:
                try:
                    v = float(v) if col == 'line' else int(round(float(v)))
                except (TypeError, ValueError):
                    raise DraftInvalid(f'{col} must be numeric or null')
            row[col] = v
        # server reconstructs the canonical id if the client did not send one (never trusts it blindly)
        row['canonical_leg_id'] = _clean(leg.get('canonical_leg_id')) or _canonical_key(row)
        qs = (row.get('quote_state') or 'unknown')
        if qs not in VALID_QUOTE_STATES:
            raise DraftInvalid(f'quote_state must be one of {VALID_QUOTE_STATES}')
        row['quote_state'] = qs
        if row['canonical_leg_id'] in seen:
            raise DraftInvalid('duplicate canonical leg in the draft')
        seen.add(row['canonical_leg_id'])
        rows.append(row)
    return rows


class KingsTicketDraftStore:
    """Authenticated repository boundary: EVERY method takes account_user_id; the client can never name
    another account (callers pass the session uid). Connection per instance; open briefly, close."""

    def __init__(self, path=None):
        self.path = Path(path or _default_db_path())
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
            new_db = not self.path.exists()
            self.conn = sqlite3.connect(str(self.path), timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA foreign_keys=ON')
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.execute('PRAGMA busy_timeout=5000')
            self.conn.executescript(DDL)
            cur = self.conn.execute('SELECT version FROM schema_meta LIMIT 1')
            if cur.fetchone() is None:
                self.conn.execute('INSERT INTO schema_meta(version) VALUES(?)', (SCHEMA_VERSION,))
                self.conn.commit()
            if new_db:
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        except (sqlite3.Error, OSError) as exc:          # ANY open/mkdir failure -> degrade, never crash
            raise StoreUnavailable(str(exc))

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---- repository (account-bound) ----
    def get_draft(self, account_user_id: str):
        if not account_user_id:
            return None
        try:
            d = self.conn.execute('SELECT * FROM drafts WHERE account_user_id=?', (account_user_id,)).fetchone()
            if not d:
                return None
            legs = self.conn.execute(
                'SELECT * FROM draft_legs WHERE draft_id=? ORDER BY position', (d['draft_id'],)).fetchall()
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))
        return {'draft': dict(d), 'legs': [dict(r) for r in legs]}

    def save_draft(self, account_user_id, legs, originating_surface=None, risk_amount=None,
                   expected_revision=None, combined=None, now=None):
        """Overwrite the account's single draft transactionally. `expected_revision` is the optimistic CAS
        token the caller last read: None for a first save, the current revision otherwise. A mismatch
        raises DraftConflict (newer revision exists) -- the caller then offers reload/overwrite; a newer
        revision is NEVER silently discarded. Returns the new {draft_id, revision, expires_at}."""
        if not account_user_id:
            raise DraftInvalid('account_user_id required')
        rows = _validate_legs(legs)
        combined = combined or {}
        # combined price persisted ONLY when a sportsbook supplied it; otherwise all NULL (illustrative is
        # display-only, never stored as if it were a quote).
        cprice = combined.get('price') if combined.get('source') else None
        csource = _clean(combined.get('source')) if cprice is not None else None
        cscope = _clean(combined.get('scope')) if cprice is not None else None
        ctime = _clean(combined.get('timestamp')) if cprice is not None else None
        ra = None
        if risk_amount not in (None, ''):
            try:
                ra = float(risk_amount)
            except (TypeError, ValueError):
                raise DraftInvalid('risk_amount must be numeric')
        ts = int(now if now is not None else time.time())
        nowiso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))
        try:
            with self.conn:                                   # BEGIN..COMMIT (rollback on any error)
                cur = self.conn.execute(
                    'SELECT draft_id, revision, created_at FROM drafts WHERE account_user_id=?',
                    (account_user_id,)).fetchone()
                if cur:
                    if expected_revision is not None and int(expected_revision) != int(cur['revision']):
                        raise DraftConflict(f'stale revision (have {cur["revision"]}, sent {expected_revision})')
                    draft_id, new_rev, created = cur['draft_id'], int(cur['revision']) + 1, cur['created_at']
                    self.conn.execute('DELETE FROM draft_legs WHERE draft_id=?', (draft_id,))
                    self.conn.execute(
                        'UPDATE drafts SET revision=?, leg_count=?, originating_surface=?, risk_amount=?, '
                        'combined_price=?, combined_price_source=?, combined_price_scope=?, '
                        'combined_price_timestamp=?, updated_at=?, expires_at=? WHERE account_user_id=?',
                        (new_rev, len(rows), _clean(originating_surface), ra, cprice, csource, cscope, ctime,
                         ts, ts + DRAFT_TTL_SECONDS, account_user_id))
                else:
                    if expected_revision not in (None, 0):
                        raise DraftConflict('no existing draft to match the sent revision')
                    draft_id, new_rev, created = 'd_' + uuid.uuid4().hex, 1, ts
                    self.conn.execute(
                        'INSERT INTO drafts(account_user_id, draft_id, revision, leg_count, '
                        'originating_surface, risk_amount, combined_price, combined_price_source, '
                        'combined_price_scope, combined_price_timestamp, created_at, updated_at, expires_at) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (account_user_id, draft_id, new_rev, len(rows), _clean(originating_surface), ra,
                         cprice, csource, cscope, ctime, created, ts, ts + DRAFT_TTL_SECONDS))
                for pos, r in enumerate(rows):
                    cols = ['draft_id', 'position'] + [c for c in LEG_COLUMNS
                                                       if c not in ('inserted_at', 'last_validated_at')] \
                           + ['inserted_at', 'last_validated_at']
                    vals = [draft_id, pos] + [r.get(c) for c in LEG_COLUMNS
                                              if c not in ('inserted_at', 'last_validated_at')] \
                           + [nowiso, nowiso]
                    self.conn.execute(
                        f'INSERT INTO draft_legs({",".join(cols)}) VALUES({",".join("?" * len(cols))})', vals)
            return {'draft_id': draft_id, 'revision': new_rev, 'expires_at': ts + DRAFT_TTL_SECONDS}
        except (DraftConflict, DraftInvalid):
            raise
        except sqlite3.IntegrityError as exc:
            raise DraftInvalid(str(exc))
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))

    def clear_draft(self, account_user_id) -> int:
        if not account_user_id:
            return 0
        try:
            with self.conn:
                cur = self.conn.execute('DELETE FROM drafts WHERE account_user_id=?', (account_user_id,))
                return cur.rowcount
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))

    def purge_expired(self, now=None) -> int:
        ts = int(now if now is not None else time.time())
        try:
            with self.conn:
                cur = self.conn.execute('DELETE FROM drafts WHERE expires_at <= ?', (ts,))
                return cur.rowcount
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))
