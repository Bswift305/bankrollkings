"""King's Tickets — server-side EPHEMERAL active-draft store (Step 4, DARK).

One editable draft per account, kept at most 24h after the last edit, overwrite-only, NO outcomes/
settlement/result fields, NOT placed-bet history and NOT the Decision Journal (which stays dark). This
module is the schema + repository + flag-gated service + purge. It writes NOTHING in production until
`KINGS_TICKETS_DRAFTS_ENABLED` is turned on (default "0"). No routes, no autosave UI, no flag flip here.

Security/correctness posture (see docs/kings_tickets_draft_store.md). Changes in this corrective:
- AUTHORITATIVE identity. The public `DraftService` does NOT accept arbitrary client leg dictionaries.
  It accepts opaque candidate/quote *references* and resolves them against a SERVER-SIDE resolver, then
  constructs the canonical leg itself. Client display labels, names, lines, books and timestamps can never
  override authoritative fields. The low-level repository may accept already-validated canonical rows.
- Optimistic concurrency everywhere, including CLEAR. `expected_revision` is a strict non-negative int
  (no bool, no float, no decimal string): create => exactly 0, update/clear => the current positive int.
  Clearing an existing draft REQUIRES the revision; a route-facing clear never erases blindly. Account
  deletion uses a SEPARATE administrative method, not the route-facing clear.
- All supplied timestamps (leg event_start, leg source/capture, combined capture) must be timezone-aware
  and are normalized to one canonical UTC representation; naive/local timestamps are rejected.
- Quote-state invariants are frozen: a 'current' leg must carry full provenance; a 'stale' leg must
  preserve its original observation; price_format and quote_scope use controlled enums; a supplied price
  requires a supported format. Enforced in service validation AND with DB-level CHECKs.
- A combined quote is all-or-nothing and preserves price + price_format + sportsbook + scope + source +
  capture timestamp (price_format is now stored, not discarded).
- Startup never mutates an existing store before validating it: an absent store is created transactionally;
  an existing store is opened READ-ONLY, its schema/version inspected, and an unsupported/missing/duplicate/
  malformed schema fails closed with the file byte-identical. No implicit "repair".
- Production path safety happens BEFORE any mkdir/chmod: the runtime root is validated first, every path
  component is lstat-checked for symlinks, only the single missing child dir is created beneath the
  validated root, and the dir/db/-wal/-shm owner+mode are verified (and never silently repaired).
Routes may import ONLY `DraftService`; never the repository (`qc_kings_tickets_drafts` guards this).
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 2                     # bumped: combined_price_format column + quote-state CHECKs
DRAFT_TTL_SECONDS = 24 * 3600
MIN_LEGS = 2
MAX_LEGS = 5
MAX_STR = 400
MAX_UID = 128
RISK_MAX_CENTS = 100_000_000           # $1,000,000 ceiling; integer cents only
VALID_QUOTE_STATES = ('current', 'stale', 'missing', 'unknown')
VALID_PRICE_FORMATS = ('american',)    # the store validates American prices only; controlled enum
VALID_LEG_QUOTE_SCOPES = ('single-leg',)        # a single leg's own quote is single-leg
COMBINED_SCOPE = 'combined-ticket'
_STRICT = sqlite3.sqlite_version_info >= (3, 37, 0)
_STRICT_SUFFIX = ' STRICT' if _STRICT else ''

# References the public service accepts (opaque). It resolves them against a server-side source; it never
# reads authoritative identity/quote fields off the client. Only these keys may appear on a reference.
_REFERENCE_KEYS = frozenset(('candidate_ref', 'quote_ref', 'selection_origin', 'entry_method'))

# Canonical leg columns (nullable except the two server-derived identities + quote_state). Display label
# never participates in identity. event_start / source_timestamp are UTC-validated, not plain text.
_LEG_PLAIN_TEXT = ('sport', 'league', 'event_id', 'player_id', 'player_name', 'team_id', 'team_name',
                   'market_key', 'direction', 'price_format', 'sportsbook', 'quote_scope',
                   'source_provider', 'selection_origin', 'entry_method', 'reason_rule_id', 'display_label')
_LEG_TS = ('event_start', 'source_timestamp')
# Full ordered column list for INSERT (matches the DDL order below).
_LEG_COLS = ('selection_key', 'quote_observation_id', 'sport', 'league', 'event_id', 'event_start',
             'player_id', 'player_name', 'team_id', 'team_name', 'market_key', 'direction', 'line',
             'price', 'price_format', 'sportsbook', 'quote_scope', 'source_provider', 'source_timestamp',
             'selection_origin', 'entry_method', 'reason_rule_id', 'display_label', 'quote_state')


class StoreUnavailable(Exception):
    """Open/mkdir/corruption/schema failure -- callers degrade to 'no draft', never crash; no Journal fallback."""


class StoreDisabled(Exception):
    """The feature flag is off -- the service refuses without opening the production store."""


class DraftConflict(Exception):
    """Optimistic-concurrency failure (stale/absent revision, or write contention). Offer reload/overwrite."""


class DraftInvalid(Exception):
    """A hard rule was violated (leg count, duplicate selection, insufficient identity, bad number/enum/ts)."""


def drafts_enabled() -> bool:
    return str(os.environ.get('KINGS_TICKETS_DRAFTS_ENABLED', '0')).strip().lower() in ('1', 'true', 'yes', 'on')


def _runtime_root() -> Path:
    return Path(os.environ.get('BK_RUNTIME_DIR') or '/var/lib/bankrollkings').resolve()


def _default_db_path() -> Path:
    return _runtime_root() / 'kings_tickets' / 'active_drafts.db'


# ---------------------------------------------------------------- value validation
def _exact_nonneg_int(v, field='expected_revision'):
    """A real non-negative int. Rejects bool, float (incl. 1.9), decimal strings and negatives, so a
    truncating ``int()`` can never let a fractional/garbage revision masquerade as a valid CAS token."""
    if isinstance(v, bool):
        raise DraftInvalid(f'{field} must be an integer, not boolean')
    if not isinstance(v, int):
        raise DraftInvalid(f'{field} must be an integer (got {type(v).__name__})')
    if v < 0:
        raise DraftInvalid(f'{field} must be >= 0')
    return v


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
    cents = int(round(f * 100))
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


def _utc_ok(v, field='timestamp'):
    """Require a timezone-aware timestamp and normalize it to one canonical UTC representation
    (``...Z``). Naive/local timestamps are rejected -- SQLite would otherwise store them as opaque text."""
    if v in (None, ''):
        return None
    text = str(v).strip()
    if len(text) > MAX_STR:
        raise DraftInvalid(f'{field} too long')
    iso = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise DraftInvalid(f'{field} must be an ISO 8601 timestamp')
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DraftInvalid(f'{field} must be timezone-aware UTC (naive/local rejected)')
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


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
    """Stable identity for duplicate detection: event + subject + market + direction. Derived from the
    already-authoritative row ONLY; display_label and any client id are excluded. Rejects an
    under-identified leg."""
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


def _validate_leg_row(leg):
    """Validate ONE already-authoritative canonical leg dict into a stored row. Enforces timestamps,
    enums, quote-state provenance and reconstructs the server-side identities."""
    if not isinstance(leg, dict):
        raise DraftInvalid('each leg must be an object')
    row = {c: _text(leg.get(c), c) for c in _LEG_PLAIN_TEXT}
    for c in _LEG_TS:
        row[c] = _utc_ok(leg.get(c), c)
    row['line'] = _line(leg.get('line'))
    row['price'] = _american(leg.get('price'))
    qs = (_text(leg.get('quote_state')) or 'unknown')
    if qs not in VALID_QUOTE_STATES:
        raise DraftInvalid(f'quote_state must be one of {VALID_QUOTE_STATES}')
    row['quote_state'] = qs
    # controlled enums
    if row['price_format'] is not None and row['price_format'] not in VALID_PRICE_FORMATS:
        raise DraftInvalid(f'price_format must be one of {VALID_PRICE_FORMATS}')
    if row['price'] is not None and row['price_format'] is None:
        raise DraftInvalid('a supplied price requires a price_format')
    if row['quote_scope'] is not None and row['quote_scope'] not in VALID_LEG_QUOTE_SCOPES:
        raise DraftInvalid(f'quote_scope must be one of {VALID_LEG_QUOTE_SCOPES}')
    # identities reconstructed server-side from authoritative fields; a client canonical id is IGNORED
    row['selection_key'] = _selection_key(row)
    row['quote_observation_id'] = _quote_observation_id(row)
    # quote-state provenance invariants
    if qs == 'current':
        need = ('line', 'price', 'price_format', 'sportsbook', 'quote_scope', 'source_provider', 'source_timestamp')
        missing = [k for k in need if row.get(k) in (None, '')]
        if missing:
            raise DraftInvalid(f"a 'current' quote requires full provenance; missing {missing}")
    if qs == 'stale' and row['quote_observation_id'] is None:
        raise DraftInvalid("a 'stale' quote must preserve its original observation (book/line/price/capture)")
    return row


def _validate_legs(legs):
    """Validate a list of already-authoritative canonical leg dicts (repository input)."""
    if not isinstance(legs, (list, tuple)):
        raise DraftInvalid('legs must be a list')
    if not (MIN_LEGS <= len(legs) <= MAX_LEGS):
        raise DraftInvalid(f'a draft must have {MIN_LEGS}-{MAX_LEGS} legs (got {len(legs)})')
    rows, seen = [], set()
    for leg in legs:
        row = _validate_leg_row(leg)
        if row['selection_key'] in seen:
            raise DraftInvalid('duplicate underlying selection in the draft')
        seen.add(row['selection_key'])
        rows.append(row)
    return rows


def _validate_combined(combined):
    """ALL-OR-NOTHING: a combined quote is stored only with price + price_format + sportsbook +
    scope==COMBINED_SCOPE + capture timestamp + source. Otherwise nothing (illustrative is display-only).
    Returns (price, price_format, source, scope, timestamp, book)."""
    combined = combined or {}
    price = combined.get('price')
    if price in (None, ''):
        return (None, None, None, None, None, None)
    p = _american(price, 'combined_price')
    fmt = _text(combined.get('price_format'), 'combined price_format')
    book = _text(combined.get('sportsbook'), 'combined sportsbook')
    scope = _text(combined.get('scope'), 'combined scope')
    ts = _utc_ok(combined.get('timestamp'), 'combined timestamp')
    source = _text(combined.get('source'), 'combined source')
    if fmt is not None and fmt not in VALID_PRICE_FORMATS:
        raise DraftInvalid(f'combined price_format must be one of {VALID_PRICE_FORMATS}')
    if not (fmt and book and scope == COMBINED_SCOPE and ts and source):
        raise DraftInvalid(
            'combined price requires price+price_format+sportsbook+scope(combined-ticket)+timestamp+source')
    return (p, fmt, source, scope, ts, book)


# ---------------------------------------------------------------- schema
_DDL_STATEMENTS = [
    f"""CREATE TABLE schema_meta(
  id INTEGER PRIMARY KEY CHECK(id=1),
  version INTEGER NOT NULL
){_STRICT_SUFFIX}""",
    f"""CREATE TABLE drafts(
  account_user_id TEXT NOT NULL UNIQUE,
  draft_id        TEXT NOT NULL PRIMARY KEY,
  revision        INTEGER NOT NULL CHECK(revision > 0),
  leg_count       INTEGER NOT NULL CHECK(leg_count BETWEEN 2 AND 5),
  originating_surface TEXT,
  risk_amount_cents INTEGER CHECK(risk_amount_cents IS NULL OR (risk_amount_cents >= 0 AND risk_amount_cents <= 100000000)),
  combined_price            INTEGER CHECK(combined_price IS NULL OR combined_price <= -100 OR combined_price >= 100),
  combined_price_format     TEXT    CHECK(combined_price_format IS NULL OR combined_price_format='american'),
  combined_price_source     TEXT,
  combined_price_scope      TEXT,
  combined_price_timestamp  TEXT,
  combined_price_book       TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  CHECK((combined_price IS NULL AND combined_price_format IS NULL AND combined_price_source IS NULL
         AND combined_price_scope IS NULL AND combined_price_timestamp IS NULL AND combined_price_book IS NULL)
     OR (combined_price IS NOT NULL AND combined_price_format='american' AND combined_price_source IS NOT NULL
         AND combined_price_scope='combined-ticket' AND combined_price_timestamp IS NOT NULL
         AND combined_price_book IS NOT NULL))
){_STRICT_SUFFIX}""",
    f"""CREATE TABLE draft_legs(
  draft_id TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  selection_key TEXT NOT NULL,
  quote_observation_id TEXT,
  sport TEXT, league TEXT, event_id TEXT, event_start TEXT,
  player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  market_key TEXT, direction TEXT, line REAL,
  price INTEGER CHECK(price IS NULL OR price <= -100 OR price >= 100),
  price_format TEXT CHECK(price_format IS NULL OR price_format='american'),
  sportsbook TEXT,
  quote_scope TEXT CHECK(quote_scope IS NULL OR quote_scope='single-leg'),
  source_provider TEXT, source_timestamp TEXT, selection_origin TEXT, entry_method TEXT,
  reason_rule_id TEXT, display_label TEXT,
  quote_state TEXT NOT NULL CHECK(quote_state IN ('current','stale','missing','unknown')),
  inserted_at TEXT, last_validated_at TEXT,
  PRIMARY KEY(draft_id, position),
  UNIQUE(draft_id, selection_key),
  CHECK(price IS NULL OR price_format IS NOT NULL),
  CHECK(quote_state != 'current' OR (line IS NOT NULL AND price IS NOT NULL AND price_format IS NOT NULL
        AND sportsbook IS NOT NULL AND quote_scope IS NOT NULL AND source_provider IS NOT NULL
        AND source_timestamp IS NOT NULL)),
  CHECK(quote_state != 'stale' OR quote_observation_id IS NOT NULL)
){_STRICT_SUFFIX}""",
    "CREATE INDEX idx_drafts_expires ON drafts(expires_at)",
]

_LEG_INSERT_COLS = ('draft_id', 'position') + _LEG_COLS + ('inserted_at', 'last_validated_at')


# ---------------------------------------------------------------- production path safety
def _require_safe_root(p, label='runtime root'):
    """The runtime ROOT is a shared parent (e.g. a root-owned ``/var/lib/bankrollkings`` at 0755 that also
    holds the Decision Journal dir), NOT the sensitive leaf. It must be a real directory, not a symlink,
    owned by root or the service user, and NOT writable by group/other -- so no untrusted user can plant
    the draft dir beneath it. It may be group/other *readable/traversable*; the DB is protected at the 0700
    leaf validated by `_require_safe_dir`."""
    try:
        lst = os.lstat(p)
    except OSError as exc:
        raise StoreUnavailable(f'{label} missing: {exc}')
    if stat.S_ISLNK(lst.st_mode):
        raise StoreUnavailable(f'{label} is a symlink')
    if not stat.S_ISDIR(lst.st_mode):
        raise StoreUnavailable(f'{label} is not a directory')
    if os.name == 'posix':
        if lst.st_uid not in (0, os.getuid()):
            raise StoreUnavailable(f'{label} must be owned by root or the service user')
        if lst.st_mode & 0o022:
            raise StoreUnavailable(f'{label} is writable by group/other')


def _require_safe_dir(p, label):
    """The sensitive leaf (the draft dir that holds the DB): a real directory, not a symlink, owned by the
    service user, owner-only (0700)."""
    try:
        lst = os.lstat(p)
    except OSError as exc:
        raise StoreUnavailable(f'{label} missing: {exc}')
    if stat.S_ISLNK(lst.st_mode):
        raise StoreUnavailable(f'{label} is a symlink')
    if not stat.S_ISDIR(lst.st_mode):
        raise StoreUnavailable(f'{label} is not a directory')
    if os.name == 'posix':
        if lst.st_uid != os.getuid():
            raise StoreUnavailable(f'{label} not owned by the service user')
        if lst.st_mode & 0o077:
            raise StoreUnavailable(f'{label} permissions too open')


def _assert_no_symlink_chain(path):
    """Reject a symlinked ancestor or target: lstat every EXISTING component top-to-bottom. Components that
    do not exist yet are fine -- we create only the single missing child below, under the validated root."""
    parts = path.parts
    if not parts:
        return
    cur = Path(parts[0])
    for part in parts[1:]:
        cur = cur / part
        if os.path.lexists(cur) and os.path.islink(cur):
            raise StoreUnavailable(f'symlinked path component rejected: {cur}')


def _prepare_prod_dir(path):
    """Validate the runtime root first, reject symlinked ancestors/targets, then create ONLY the single
    missing child dir beneath the validated root. Never chmod before establishing root-containment."""
    root = _runtime_root()
    parent = path.parent
    # the draft dir must be the runtime root itself or exactly one controlled level beneath it
    if parent != root and parent.parent != root:
        raise StoreUnavailable('draft dir must be within the private runtime root')
    _require_safe_root(root)                                # trusted parent (root- or service-owned, not o/g-writable)
    _assert_no_symlink_chain(path)                          # no symlinked ancestor or target
    if parent != root and not os.path.lexists(parent):
        os.mkdir(parent, 0o700)                             # create ONLY the missing child, owner-only
    _require_safe_dir(parent, 'draft dir')                  # validate the (now existing) dir; no repair


def _create_prod_db_file(path):
    """Create the DB file owner-only (0600) and atomically, refusing to follow a symlink. SQLite then opens
    this existing 0-byte file, so the main DB and its -wal/-shm inherit 0600."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags, 0o600)
    os.close(fd)


def _validate_prod_files(path):
    """Fail closed on an existing dir/db/-wal/-shm with the wrong owner or too-open mode. Never repair."""
    _require_safe_dir(path.parent, 'draft dir')
    for suffix in ('', '-wal', '-shm'):
        f = Path(str(path) + suffix)
        if not os.path.lexists(f):
            continue
        lst = os.lstat(f)
        if stat.S_ISLNK(lst.st_mode):
            raise StoreUnavailable(f'{f.name} is a symlink')
        if os.name == 'posix':
            if lst.st_uid != os.getuid():
                raise StoreUnavailable(f'{f.name} not owned by the service user')
            if lst.st_mode & 0o077:
                raise StoreUnavailable(f'{f.name} permissions too open')


class KingsTicketDraftStore:
    """Low-level repository. Account-bound on every op. Accepts already-authoritative canonical leg rows.
    Tests construct it directly with path=; production code must go through DraftService, which resolves
    references server-side and never hands this layer a request-derived path or a raw client leg dict."""

    def __init__(self, path=None):
        test_path = path is not None
        self.path = Path(path) if test_path else _default_db_path()
        self.conn = None
        self._new_prod_file = False
        try:
            if test_path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                new_db = not self.path.exists()
            else:
                _prepare_prod_dir(self.path)               # validate + create dir BEFORE opening
                new_db = not self.path.exists()
                if new_db:
                    _create_prod_db_file(self.path)        # 0600, no-follow, atomic
                    self._new_prod_file = True
            if new_db:
                self._create_new()
            else:
                self._open_existing()                      # read-only inspection; no mutation if unsupported
            if not test_path:
                _validate_prod_files(self.path)
        except StoreUnavailable:
            self._cleanup_on_failure(unlink=self._new_prod_file)
            raise
        except (sqlite3.Error, OSError) as exc:
            self._cleanup_on_failure(unlink=self._new_prod_file)
            raise StoreUnavailable(str(exc))

    def _cleanup_on_failure(self, unlink=False):
        self._safe_close()
        if unlink:
            for suffix in ('', '-wal', '-shm'):
                try:
                    os.remove(str(self.path) + suffix)
                except OSError:
                    pass

    def _connect(self):
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)  # explicit txns
        self.conn.row_factory = sqlite3.Row

    def _create_new(self):
        """Absent store: create the schema transactionally (all-or-nothing)."""
        self._connect()
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            for stmt in _DDL_STATEMENTS:
                self.conn.execute(stmt)
            self.conn.execute('INSERT INTO schema_meta(id, version) VALUES(1, ?)', (SCHEMA_VERSION,))
            self.conn.execute('COMMIT')
        except Exception:
            self.conn.execute('ROLLBACK')
            raise

    def _open_existing(self):
        """Existing store: open READ-ONLY, inspect the schema/version, and fail closed WITHOUT mutating the
        file if it is unsupported/missing/duplicate/malformed. Only after validation do we enable WAL."""
        self._connect()
        self.conn.execute('PRAGMA query_only=ON')          # guarantee no write while inspecting
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA busy_timeout=5000')
        self._check_schema_readonly()
        self.conn.execute('PRAGMA query_only=OFF')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')

    def _check_schema_readonly(self):
        try:
            rows = self.conn.execute('SELECT id, version FROM schema_meta').fetchall()
        except sqlite3.Error as exc:
            raise StoreUnavailable(f'schema_meta unreadable (not a supported draft store): {exc}')
        if not rows:
            raise StoreUnavailable('schema_meta missing (unsupported draft store)')
        if len(rows) != 1 or rows[0]['id'] != 1:
            raise StoreUnavailable('schema_meta is not a singleton')
        if int(rows[0]['version']) != SCHEMA_VERSION:
            raise StoreUnavailable(f'unsupported schema version {rows[0]["version"]} (need {SCHEMA_VERSION})')

    def _safe_close(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass

    def close(self):
        self._safe_close()

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
        """Overwrite the account's single draft with already-authoritative canonical leg rows.
        `expected_revision` is a strict non-negative int: 0 to create, or the current revision to update (a
        deliberate post-conflict overwrite passes the LATEST revision). Mismatch/absence -> DraftConflict;
        a newer revision is never silently discarded."""
        uid = self._uid(account_user_id)
        exp = _exact_nonneg_int(expected_revision)
        rows = _validate_legs(legs)
        cprice, cfmt, csource, cscope, ctime, cbook = _validate_combined(combined)
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
                        'combined_price=?, combined_price_format=?, combined_price_source=?, combined_price_scope=?, '
                        'combined_price_timestamp=?, combined_price_book=?, updated_at=?, expires_at=? '
                        'WHERE account_user_id=?',
                        (new_rev, len(rows), surface, ra, cprice, cfmt, csource, cscope, ctime, cbook, ts,
                         ts + DRAFT_TTL_SECONDS, uid))
                else:
                    if exp != 0:
                        raise DraftConflict('no existing draft; create requires expected_revision=0')
                    draft_id, new_rev, created = 'd_' + uuid4().hex, 1, ts
                    self.conn.execute(
                        'INSERT INTO drafts(account_user_id, draft_id, revision, leg_count, originating_surface, '
                        'risk_amount_cents, combined_price, combined_price_format, combined_price_source, '
                        'combined_price_scope, combined_price_timestamp, combined_price_book, created_at, '
                        'updated_at, expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (uid, draft_id, new_rev, len(rows), surface, ra, cprice, cfmt, csource, cscope, ctime,
                         cbook, created, ts, ts + DRAFT_TTL_SECONDS))
                for pos, r in enumerate(rows):
                    vals = [draft_id, pos] + [r.get(c) for c in _LEG_COLS] + [nowiso, nowiso]
                    self.conn.execute(
                        f'INSERT INTO draft_legs({",".join(_LEG_INSERT_COLS)}) '
                        f'VALUES({",".join("?" * len(_LEG_INSERT_COLS))})', vals)
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

    def clear_draft(self, account_user_id, expected_revision):
        """Route-facing clear. If a draft EXISTS, `expected_revision` is mandatory and must match the
        current revision (an old tab cannot erase a newer draft). If no draft exists it is a no-op. Account
        deletion must use `administrative_delete`, not this."""
        uid = self._uid(account_user_id)
        try:
            self._begin_immediate()
            try:
                cur = self.conn.execute('SELECT revision FROM drafts WHERE account_user_id=?', (uid,)).fetchone()
                if cur:
                    if expected_revision is None:
                        raise DraftInvalid('expected_revision is required to clear an existing draft')
                    exp = _exact_nonneg_int(expected_revision)
                    if exp != int(cur['revision']):
                        raise DraftConflict(f'stale revision on clear (have {cur["revision"]}, sent {exp})')
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

    def administrative_delete(self, account_user_id):
        """Internal, non-route-facing: unconditionally remove an account's draft (e.g. on account
        deletion). NOT reachable through the route-facing clear, which always requires a revision."""
        uid = self._uid(account_user_id)
        try:
            self._begin_immediate()
            try:
                n = self.conn.execute('DELETE FROM drafts WHERE account_user_id=?', (uid,)).rowcount
                self.conn.execute('COMMIT')
            except Exception:
                self.conn.execute('ROLLBACK')
                raise
            return n
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


def _require_references(references):
    """The public service accepts only opaque references, never client leg dictionaries. Each reference
    may carry ONLY candidate_ref (required), quote_ref, selection_origin and entry_method -- no player
    names, lines, books, timestamps or display labels that could override authoritative fields."""
    if not isinstance(references, (list, tuple)):
        raise DraftInvalid('references must be a list')
    out = []
    for ref in references:
        if not isinstance(ref, dict):
            raise DraftInvalid('each reference must be an object')
        extra = set(ref) - _REFERENCE_KEYS
        if extra:
            raise DraftInvalid(
                f'references must not carry authoritative fields (offending keys: {sorted(extra)}); '
                'pass candidate_ref/quote_ref only — the server reconstructs the leg')
        if not ref.get('candidate_ref'):
            raise DraftInvalid('each reference requires a candidate_ref')
        out.append(ref)
    return out


class DraftService:
    """The ONLY interface routes may import. Flag-gated: when dark it refuses every op WITHOUT opening or
    initializing the production store, and never falls back to the Decision Journal. It accepts opaque
    references and resolves them with a SERVER-SIDE resolver; it never accepts raw client leg dicts."""

    _resolver = None  # injected by the (future) route layer, wired to server-side current candidate/quote sources

    @staticmethod
    def enabled():
        return drafts_enabled()

    @classmethod
    def configure_resolver(cls, resolver):
        """Install the server-side resolver: a callable (candidate_ref, quote_ref) -> authoritative leg
        dict. In production this resolves against current candidate/quote sources; no such source is wired
        yet (dark)."""
        cls._resolver = resolver

    @staticmethod
    def _require_enabled():
        if not drafts_enabled():
            raise StoreDisabled('King\'s Tickets drafts are disabled')

    @classmethod
    def _resolve(cls, resolver, ref):
        leg = resolver(ref.get('candidate_ref'), ref.get('quote_ref'))
        if not isinstance(leg, dict):
            raise DraftInvalid('resolver did not return an authoritative leg')
        row = dict(leg)
        # operational metadata (where it came from / how it was entered) is NOT authoritative identity
        if ref.get('selection_origin') is not None:
            row['selection_origin'] = ref.get('selection_origin')
        if ref.get('entry_method') is not None:
            row['entry_method'] = ref.get('entry_method')
        return row

    @classmethod
    def get(cls, account_user_id):
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.get_draft(account_user_id)
        finally:
            store.close()

    @classmethod
    def save(cls, account_user_id, references, expected_revision, *, resolver=None,
             combined_reference=None, originating_surface=None, risk_amount=None):
        """Resolve each opaque reference against the server-side source into an authoritative leg, then
        persist. The public service NEVER accepts client leg dictionaries."""
        cls._require_enabled()
        resolve = resolver or cls._resolver
        if resolve is None:
            raise DraftInvalid('a server-side candidate resolver is required; the public service does not '
                               'accept client leg dictionaries')
        refs = _require_references(references)
        rows = [cls._resolve(resolve, r) for r in refs]
        combined = None
        if combined_reference is not None:
            cref = _require_references([combined_reference])[0]
            combined = resolve(cref.get('candidate_ref'), cref.get('quote_ref'))
            if combined is not None and not isinstance(combined, dict):
                raise DraftInvalid('resolver did not return a combined quote dict')
        store = KingsTicketDraftStore()
        try:
            return store.save_draft(account_user_id, rows, expected_revision,
                                    originating_surface=originating_surface, risk_amount=risk_amount,
                                    combined=combined)
        finally:
            store.close()

    @classmethod
    def clear(cls, account_user_id, expected_revision):
        """Route-facing clear -- `expected_revision` is REQUIRED (no default). An unconditional clear is
        not exposed to routes; account deletion goes through `delete_account_data`."""
        cls._require_enabled()
        store = KingsTicketDraftStore()
        try:
            return store.clear_draft(account_user_id, expected_revision)
        finally:
            store.close()

    @classmethod
    def delete_account_data(cls, account_user_id):
        """Administrative, non-route-facing: remove the account's draft unconditionally on account deletion.
        Independent of the flag so deletion always honors data rights, but it NEVER creates a store -- if
        the DB does not exist there is nothing to delete."""
        if not _default_db_path().exists():
            return 0
        store = KingsTicketDraftStore()
        try:
            return store.administrative_delete(account_user_id)
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
