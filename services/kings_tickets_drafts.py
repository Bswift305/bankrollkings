"""King's Tickets — server-side EPHEMERAL active-draft store (Step 4, DARK).

One editable draft per account, kept at most 24h after the last edit, overwrite-only, NO outcomes/
settlement/result fields, NOT placed-bet history and NOT the Decision Journal (which stays dark). This
module is the schema + repository + flag-gated service + purge. It writes NOTHING in production until
`KINGS_TICKETS_DRAFTS_ENABLED` is turned on (default "0"). No routes, no autosave UI, no flag flip here.

Security/correctness posture (see docs/kings_tickets_draft_store.md):
- Identity is reconstructed SERVER-SIDE; client-supplied canonical ids are ignored and display labels never
  participate in identity. Duplicate underlying selections are rejected via `selection_key`.
- Optimistic concurrency: `expected_revision` is MANDATORY (create => 0, update => current). An explicit
  `BEGIN IMMEDIATE` serializes writers; the loser gets DraftConflict, never a generic lock error.
- Expired drafts are treated as absent on read (and purged), never restored, TTL never extended on read.
- STRICT tables + CHECKs + integer cents; NaN/inf/bool/oversized rejected; combined price is all-or-nothing.
- schema_meta is a singleton; an unexpected/missing/duplicate version fails closed.
- Production path is validated (under the private runtime dir, no symlinks, owner-only); the `path=`
  override is TEST-ONLY. Any open failure => StoreUnavailable; callers degrade (site unaffected); never a
  Decision Journal fallback.
Routes may import ONLY `DraftService` (flag-gated), never the repository (`qc_kings_tickets_drafts` guards).
"""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 1
DRAFT_TTL_SECONDS = 24 * 3600
MIN_LEGS = 2
MAX_LEGS = 5
MAX_STR = 400
MAX_UID = 128
RISK_MAX_CENTS = 100_000_000          # $1,000,000 ceiling; integer cents only
VALID_QUOTE_STATES = ('current', 'stale', 'missing', 'unknown')
_STRICT = sqlite3.sqlite_version_info >= (3, 37, 0)
_STRICT_SUFFIX = ' STRICT' if _STRICT else ''

# Full-fidelity leg columns (nullable except the two identities + quote_state). Display label never
# participates in identity.
_LEG_TEXT = ('sport', 'league', 'event_id', 'event_start', 'player_id', 'player_name', 'team_id',
             'team_name', 'market_key', 'direction', 'price_format', 'sportsbook', 'quote_scope',
             'source_provider', 'source_timestamp', 'selection_origin', 'entry_method', 'reason_rule_id',
             'display_label')
_LEG_REAL = ('line',)
_LEG_INT = ('price',)


class StoreUnavailable(Exception):
    """Open/mkdir/corruption/schema failure -- callers degrade to 'no draft', never crash; no Journal fallback."""


class StoreDisabled(Exception):
    """The feature flag is off -- the service refuses without opening the production store."""


class DraftConflict(Exception):
    """Optimistic-concurrency failure (stale/absent revision, or write contention). Offer reload/overwrite."""


class DraftInvalid(Exception):
    """A hard rule was violated (leg count, duplicate selection, insufficient identity, bad number/enum)."""


def drafts_enabled() -> bool:
    return str(os.environ.get('KINGS_TICKETS_DRAFTS_ENABLED', '0')).strip().lower() in ('1', 'true', 'yes', 'on')


def _runtime_root() -> Path:
    return Path(os.environ.get('BK_RUNTIME_DIR') or '/var/lib/bankrollkings').resolve()


def _default_db_path() -> Path:
    return _runtime_root() / 'kings_tickets' / 'active_drafts.db'


# ---------------------------------------------------------------- value validation
def _finite_number(v, field):
    if isinstance(v, bool):
        raise DraftInvalid(f'{field} must not be boolean')
    if not isinstance(v, (int, float)):
        # permissive SQLite typing must not let strings into numeric columns
        raise DraftInvalid(f'{field} must be numeric')
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        raise DraftInvalid(f'{field} must be finite')
    return f


def _risk_cents(v):
    if v in (None, ''):
        return None
    f = _finite_number(v, 'risk_amount')
    cents = int(round(f * 100)) if isinstance(v, float) else int(v) * 100 if isinstance(v, int) else int(round(f * 100))
    # accept either dollars (float/int) -> cents; reject negative/oversized
    if cents < 0 or cents > RISK_MAX_CENTS:
        raise DraftInvalid('risk_amount out of range')
    return cents


def _american(v, field='price'):
    if v in (None, ''):
        return None
    f = _finite_number(v, field)
    if f != int(f):
        raise DraftInvalid(f'{field} must be an integer American price')
    iv = int(f)
    if not (iv <= -100 or iv >= 100):
        raise DraftInvalid(f'{field} must be a valid American price (<=-100 or >=100)')
    return iv


def _line(v):
    if v in (None, ''):
        return None
    return _finite_number(v, 'line')


def _utc_ok(v):
    if v in (None, ''):
        return None
    text = str(v).strip()
    if len(text) > MAX_STR:
        raise DraftInvalid('timestamp too long')
    try:
        datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise DraftInvalid('timestamp must be a parseable ISO/UTC value')
    return text


def _text(v, field=''):
    if v is None:
        return None
    if isinstance(v, bool) or isinstance(v, (int, float)):
        v = str(v)
    text = str(v).strip()
    if text == '':
        return None
    if len(text) > MAX_STR:
        raise DraftInvalid(f'{field or "field"} exceeds {MAX_STR} chars')
    return text


def _selection_key(row):
    """Stable identity for duplicate detection: event + subject + market + direction. Reconstructed
    server-side ONLY; display_label and any client id are excluded. Rejects an under-identified leg."""
    sport = row.get('sport') or row.get('league')
    event = row.get('event_id')
    market = row.get('market_key')
    direction = row.get('direction')
    subject = row.get('player_id') or row.get('player_name') or row.get('team_id') or row.get('team_name')
    if not (sport and event and market and direction and subject):
        raise DraftInvalid('leg lacks minimum identity (sport/league, event, market, direction, player/team)')
    basis = '|'.join(str(x).strip().lower() for x in (sport, event, market, direction, subject))
    return 'sel_' + hashlib.sha256(basis.encode('utf-8')).hexdigest()[:28]


def _quote_observation_id(row):
    """Exact book/line/price/capture observation, when all present; else NULL (no fabrication)."""
    book, line, price, cap = row.get('sportsbook'), row.get('line'), row.get('price'), row.get('source_timestamp')
    if book is None or line is None or price is None or cap is None:
        return None
    basis = '|'.join(str(x).strip().lower() for x in (book, line, price, cap))
    return 'qo_' + hashlib.sha256(basis.encode('utf-8')).hexdigest()[:28]


def _validate_legs(legs):
    if not isinstance(legs, (list, tuple)):
        raise DraftInvalid('legs must be a list')
    if not (MIN_LEGS <= len(legs) <= MAX_LEGS):
        raise DraftInvalid(f'a draft must have {MIN_LEGS}-{MAX_LEGS} legs (got {len(legs)})')
    rows, seen = [], set()
    for leg in legs:
        if not isinstance(leg, dict):
            raise DraftInvalid('each leg must be an object')
        row = {c: _text(leg.get(c), c) for c in _LEG_TEXT}
        row['line'] = _line(leg.get('line'))
        row['price'] = _american(leg.get('price'))
        qs = (_text(leg.get('quote_state')) or 'unknown')
        if qs not in VALID_QUOTE_STATES:
            raise DraftInvalid(f'quote_state must be one of {VALID_QUOTE_STATES}')
        row['quote_state'] = qs
        # identities are reconstructed server-side; a client canonical id is IGNORED
        row['selection_key'] = _selection_key(row)
        row['quote_observation_id'] = _quote_observation_id(row)
        if row['selection_key'] in seen:
            raise DraftInvalid('duplicate underlying selection in the draft')
        seen.add(row['selection_key'])
        rows.append(row)
    return rows


def _validate_combined(combined):
    """ALL-OR-NOTHING: a combined quote is stored only with price + format + sportsbook +
    scope=='combined-ticket' + capture timestamp + source. Otherwise nothing (illustrative is display-only)."""
    combined = combined or {}
    price = combined.get('price')
    if price in (None, ''):
        return (None, None, None, None, None)
    p = _american(price, 'combined_price')
    fmt = _text(combined.get('price_format'), 'combined price_format')
    book = _text(combined.get('sportsbook'), 'combined sportsbook')
    scope = _text(combined.get('scope'), 'combined scope')
    ts = _utc_ok(combined.get('timestamp'))
    source = _text(combined.get('source'), 'combined source')
    if not (fmt and book and scope == 'combined-ticket' and ts and source):
        raise DraftInvalid('combined price requires price+format+sportsbook+scope(combined-ticket)+timestamp+source')
    return (p, source, scope, ts, book)


_DDL = f"""
CREATE TABLE IF NOT EXISTS schema_meta(
  id INTEGER PRIMARY KEY CHECK(id=1),
  version INTEGER NOT NULL
){_STRICT_SUFFIX};
CREATE TABLE IF NOT EXISTS drafts(
  account_user_id TEXT NOT NULL UNIQUE,
  draft_id        TEXT NOT NULL PRIMARY KEY,
  revision        INTEGER NOT NULL CHECK(revision > 0),
  leg_count       INTEGER NOT NULL CHECK(leg_count BETWEEN 2 AND 5),
  originating_surface TEXT,
  risk_amount_cents INTEGER CHECK(risk_amount_cents IS NULL OR (risk_amount_cents >= 0 AND risk_amount_cents <= 100000000)),
  combined_price            INTEGER CHECK(combined_price IS NULL OR combined_price <= -100 OR combined_price >= 100),
  combined_price_source     TEXT,
  combined_price_scope      TEXT,
  combined_price_timestamp  TEXT,
  combined_price_book       TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  CHECK((combined_price IS NULL AND combined_price_source IS NULL AND combined_price_scope IS NULL
         AND combined_price_timestamp IS NULL AND combined_price_book IS NULL)
     OR (combined_price IS NOT NULL AND combined_price_source IS NOT NULL
         AND combined_price_scope='combined-ticket' AND combined_price_timestamp IS NOT NULL
         AND combined_price_book IS NOT NULL))
){_STRICT_SUFFIX};
CREATE TABLE IF NOT EXISTS draft_legs(
  draft_id TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  selection_key TEXT NOT NULL,
  quote_observation_id TEXT,
  sport TEXT, league TEXT, event_id TEXT, event_start TEXT,
  player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  market_key TEXT, direction TEXT, line REAL, price INTEGER, price_format TEXT, sportsbook TEXT,
  quote_scope TEXT, source_provider TEXT, source_timestamp TEXT, selection_origin TEXT, entry_method TEXT,
  reason_rule_id TEXT, display_label TEXT,
  quote_state TEXT NOT NULL CHECK(quote_state IN ('current','stale','missing','unknown')),
  inserted_at TEXT, last_validated_at TEXT,
  PRIMARY KEY(draft_id, position),
  UNIQUE(draft_id, selection_key),
  CHECK(price IS NULL OR price <= -100 OR price >= 100)
){_STRICT_SUFFIX};
CREATE INDEX IF NOT EXISTS idx_drafts_expires ON drafts(expires_at);
"""

_LEG_INSERT_COLS = ('selection_key', 'quote_observation_id') + _LEG_TEXT + _LEG_REAL + _LEG_INT + ('quote_state',)


def _validate_prod_path(path: Path):
    """Production safety: the resolved DB path must sit under the private runtime dir, with no symlinked
    dir/db target, owner-only perms, and the right owner on Linux. Never chmod an arbitrary resolved path."""
    root = _runtime_root()
    parent = path.parent
    try:
        rp = parent.resolve()
    except OSError as exc:
        raise StoreUnavailable(f'cannot resolve draft dir: {exc}')
    if root not in rp.parents and rp != root:
        raise StoreUnavailable('draft dir escapes the private runtime directory')
    if parent.is_symlink() or path.is_symlink():
        raise StoreUnavailable('symlinked draft path rejected')
    if os.name == 'posix' and parent.exists():
        st = parent.stat()
        if st.st_uid != os.getuid():
            raise StoreUnavailable('draft dir not owned by the service user')
        if st.st_mode & 0o077:
            raise StoreUnavailable('draft dir permissions too open')


class KingsTicketDraftStore:
    """Low-level repository. Account-bound on every op. Tests construct it directly with path=; production
    code must go through DraftService (never a request-derived path)."""

    def __init__(self, path=None):
        test_path = path is not None
        self.path = Path(path) if test_path else _default_db_path()
        try:
            if not test_path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.chmod(self.path.parent, 0o700)
                except OSError:
                    pass
                _validate_prod_path(self.path)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            new_db = not self.path.exists()
            self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)  # explicit txns
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA foreign_keys=ON')
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.execute('PRAGMA busy_timeout=5000')
            self.conn.executescript(_DDL)
            self._check_schema()
            if new_db and not test_path:
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        except StoreUnavailable:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StoreUnavailable(str(exc))

    def _check_schema(self):
        rows = self.conn.execute('SELECT id, version FROM schema_meta').fetchall()
        if not rows:
            self.conn.execute('INSERT INTO schema_meta(id, version) VALUES(1, ?)', (SCHEMA_VERSION,))
            return
        if len(rows) != 1 or rows[0]['id'] != 1:
            raise StoreUnavailable('schema_meta is not a singleton')
        if int(rows[0]['version']) != SCHEMA_VERSION:
            raise StoreUnavailable(f'unsupported schema version {rows[0]["version"]} (need {SCHEMA_VERSION})')

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @staticmethod
    def _uid(account_user_id):
        if not account_user_id or not isinstance(account_user_id, str):
            raise DraftInvalid('account_user_id required')
        if len(account_user_id) > MAX_UID:
            raise DraftInvalid('account_user_id too long')
        return account_user_id

    def _begin_immediate(self):
        try:
            self.conn.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            if 'lock' in str(exc).lower() or 'busy' in str(exc).lower():
                raise DraftConflict('write contention — another edit is in progress')
            raise StoreUnavailable(str(exc))

    def get_draft(self, account_user_id, now=None):
        """Account-bound read. An expired draft is treated as ABSENT and purged in the same immediate
        transaction; the TTL is never extended by a read."""
        uid = self._uid(account_user_id)
        import time as _t
        ts = int(now if now is not None else _t.time())
        try:
            self._begin_immediate()
            try:
                d = self.conn.execute('SELECT * FROM drafts WHERE account_user_id=?', (uid,)).fetchone()
                if d and int(d['expires_at']) <= ts:
                    self.conn.execute('DELETE FROM drafts WHERE account_user_id=?', (uid,))  # expired => gone
                    d = None
                legs = []
                if d:
                    legs = self.conn.execute(
                        'SELECT * FROM draft_legs WHERE draft_id=? ORDER BY position', (d['draft_id'],)).fetchall()
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
        except (DraftConflict, DraftInvalid):
            raise
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))
        if not d:
            return None
        return {'draft': dict(d), 'legs': [dict(r) for r in legs]}

    def save_draft(self, account_user_id, legs, expected_revision, originating_surface=None,
                   risk_amount=None, combined=None, now=None):
        """Overwrite the account's single draft. `expected_revision` is MANDATORY: 0 to create, or the
        current revision to update (a deliberate post-conflict overwrite passes the LATEST revision, never
        omits the token). Mismatch/absence -> DraftConflict; a newer revision is never silently discarded."""
        uid = self._uid(account_user_id)
        if expected_revision is None or isinstance(expected_revision, bool):
            raise DraftInvalid('expected_revision is mandatory (0 to create)')
        try:
            exp = int(expected_revision)
        except (TypeError, ValueError):
            raise DraftInvalid('expected_revision must be an integer')
        rows = _validate_legs(legs)
        cprice, csource, cscope, ctime, cbook = _validate_combined(combined)
        ra = _risk_cents(risk_amount)
        surface = _text(originating_surface, 'originating_surface')
        import time as _t
        ts = int(now if now is not None else _t.time())
        nowiso = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime(ts))
        try:
            self._begin_immediate()
            try:
                cur = self.conn.execute(
                    'SELECT draft_id, revision, created_at FROM drafts WHERE account_user_id=?', (uid,)).fetchone()
                if cur:
                    if exp != int(cur['revision']):
                        raise DraftConflict(f'stale revision (have {cur["revision"]}, sent {exp})')
                    draft_id, new_rev, created = cur['draft_id'], int(cur['revision']) + 1, cur['created_at']
                    self.conn.execute('DELETE FROM draft_legs WHERE draft_id=?', (draft_id,))
                    self.conn.execute(
                        'UPDATE drafts SET revision=?, leg_count=?, originating_surface=?, risk_amount_cents=?, '
                        'combined_price=?, combined_price_source=?, combined_price_scope=?, '
                        'combined_price_timestamp=?, combined_price_book=?, updated_at=?, expires_at=? '
                        'WHERE account_user_id=?',
                        (new_rev, len(rows), surface, ra, cprice, csource, cscope, ctime, cbook, ts,
                         ts + DRAFT_TTL_SECONDS, uid))
                else:
                    if exp != 0:
                        raise DraftConflict('no existing draft; create requires expected_revision=0')
                    draft_id, new_rev, created = 'd_' + uuid4().hex, 1, ts
                    self.conn.execute(
                        'INSERT INTO drafts(account_user_id, draft_id, revision, leg_count, originating_surface, '
                        'risk_amount_cents, combined_price, combined_price_source, combined_price_scope, '
                        'combined_price_timestamp, combined_price_book, created_at, updated_at, expires_at) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (uid, draft_id, new_rev, len(rows), surface, ra, cprice, csource, cscope, ctime, cbook,
                         created, ts, ts + DRAFT_TTL_SECONDS))
                for pos, r in enumerate(rows):
                    cols = ('draft_id', 'position') + _LEG_INSERT_COLS + ('inserted_at', 'last_validated_at')
                    vals = [draft_id, pos] + [r.get(c) for c in _LEG_INSERT_COLS] + [nowiso, nowiso]
                    self.conn.execute(
                        f'INSERT INTO draft_legs({",".join(cols)}) VALUES({",".join("?" * len(cols))})', vals)
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
            return {'draft_id': draft_id, 'revision': new_rev, 'expires_at': ts + DRAFT_TTL_SECONDS}
        except (DraftConflict, DraftInvalid):
            raise
        except sqlite3.IntegrityError as exc:
            raise DraftInvalid(str(exc))
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))

    def clear_draft(self, account_user_id, expected_revision=None):
        """Delete the account's draft. If `expected_revision` is given it must match (an old tab cannot
        delete a newer draft); None means an unconditional user-initiated clear."""
        uid = self._uid(account_user_id)
        try:
            self._begin_immediate()
            try:
                cur = self.conn.execute('SELECT revision FROM drafts WHERE account_user_id=?', (uid,)).fetchone()
                if cur and expected_revision is not None and int(expected_revision) != int(cur['revision']):
                    raise DraftConflict(f'stale revision on clear (have {cur["revision"]})')
                n = self.conn.execute('DELETE FROM drafts WHERE account_user_id=?', (uid,)).rowcount
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
            return n
        except (DraftConflict, DraftInvalid):
            raise
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))

    def purge_expired(self, now=None):
        import time as _t
        ts = int(now if now is not None else _t.time())
        try:
            self._begin_immediate()
            try:
                n = self.conn.execute('DELETE FROM drafts WHERE expires_at <= ?', (ts,)).rowcount
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
            return n
        except sqlite3.Error as exc:
            raise StoreUnavailable(str(exc))


class DraftService:
    """The ONLY interface routes may import. Flag-gated: when dark it refuses every op WITHOUT opening or
    initializing the production store, and never falls back to the Decision Journal."""

    @staticmethod
    def enabled():
        return drafts_enabled()

    @staticmethod
    def _require_enabled():
        if not drafts_enabled():
            raise StoreDisabled('King\'s Tickets drafts are disabled')

    @classmethod
    def get(cls, account_user_id):
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.get_draft(account_user_id)
        finally:
            store.close()

    @classmethod
    def save(cls, account_user_id, legs, expected_revision, **kw):
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.save_draft(account_user_id, legs, expected_revision, **kw)
        finally:
            store.close()

    @classmethod
    def clear(cls, account_user_id, expected_revision=None):
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.clear_draft(account_user_id, expected_revision)
        finally:
            store.close()

    @classmethod
    def purge(cls):
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.purge_expired()
        finally:
            store.close()
