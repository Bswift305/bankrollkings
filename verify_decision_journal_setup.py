#!/usr/bin/env python3
"""Decision Journal — dark-production SETUP VERIFIER (non-destructive to the live store).

Run AFTER creating the private directory and setting DECISION_JOURNAL_DB_PATH, with the feature flag
still OFF, as the application service user. Proves permissions, initialization, PRAGMAs, both integrity
checks, an empty new store, a private backup, and a restore round-trip -- WITHOUT enabling routes,
WITHOUT migrating or creating tickets. It is initialization-capable (it creates the empty schema if
absent), not literally read-only, but it never mutates existing rows and runs the corrupt/restore test
only on a temporary COPY, never the live DB.

The report is SANITIZED: it prints no ticket contents, user IDs, row counts, environment secrets, or
database bytes -- only PASS/FAIL checkpoints and non-sensitive configuration (paths, modes, PRAGMAs).

    DECISION_JOURNAL_DB_PATH=/var/lib/bankrollkings/decision_journal/journal.db \
        python3 verify_decision_journal_setup.py <expected_service_user>
"""
from __future__ import annotations

import getpass
import os
import shutil
import sqlite3
import stat
import sys
from datetime import datetime, timezone

import services.decision_journal as dj

REPO_ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
CHECKS, NOTES = [], []


def ok(cond, label, fail_detail=''):
    CHECKS.append((bool(cond), label, '' if cond else fail_detail))


def _mode(path):
    try:
        return oct(stat.S_IMODE(os.stat(path).st_mode))
    except OSError:
        return 'n/a'


def _ro(path):
    """Open a connection for VERIFICATION ONLY. Prefer a read-only file handle (mode=ro); fall back to
    a normal handle with PRAGMA query_only=ON. Either way no write, repair, or schema change can occur
    -- the live store and the verified backup are only ever read during verification."""
    try:
        c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error:
        c = sqlite3.connect(path)
    try:
        c.execute('PRAGMA query_only=ON')
    except sqlite3.Error:
        pass
    return c


def _count(path, table):
    c = _ro(path)
    try:
        return c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    finally:
        c.close()


def _rows_match(a, b):
    """True if two stores hold the same number of tickets. The count itself is never printed."""
    return _count(a, 'tickets') == _count(b, 'tickets')


def _integrity(path):
    """(ok, no_fk_rows) via a READ-ONLY connection — both checks the director requires, no mutation."""
    try:
        c = _ro(path)
    except sqlite3.Error:
        return False, False
    try:
        ic = c.execute('PRAGMA integrity_check').fetchone()[0]
        fk = c.execute('PRAGMA foreign_key_check').fetchall()
        return ic == 'ok', (len(fk) == 0)
    except sqlite3.Error:
        return False, False
    finally:
        c.close()


def main() -> int:
    expected_user = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    path = dj.resolve_db_path()
    rpath = os.path.realpath(path)
    d = os.path.dirname(rpath)
    cur_user = getpass.getuser()
    NOTES.append(f'service user: {cur_user}')
    NOTES.append(f'DB path: {path}')

    # expected service user (passed in) must match the running user
    if expected_user:
        ok(cur_user == expected_user, f'running as the expected service user ({expected_user})',
           f'running as {cur_user}, expected {expected_user}')
    else:
        NOTES.append('no expected service user passed (argv[1]); pass it so the match is asserted')

    # service user is not root (prod)
    if os.name == 'posix':
        ok(os.geteuid() != 0, 'runs as a non-root service user', f'euid={os.geteuid()} (root)')

    # path resolves OUTSIDE the deploy checkout — realpath + commonpath (symlink/sibling-prefix safe)
    try:
        inside = os.path.commonpath([rpath, REPO_ROOT]) == REPO_ROOT
    except ValueError:  # different drives/roots -> definitely outside
        inside = False
    ok(not inside, 'DECISION_JOURNAL_DB_PATH resolves outside the checkout',
       f'resolved path {rpath} is inside the checkout {REPO_ROOT}')

    # Initialize ONLY when the store does not yet exist (fresh dark setup). An existing store is
    # verified strictly READ-ONLY and is NEVER re-initialized, migrated, repaired, truncated or
    # replaced -- a failed integrity check must not trigger schema creation.
    if os.path.exists(path):
        init_ok = True
        NOTES.append('existing store present: verified read-only (not re-initialized)')
    else:
        try:
            dj.init_db(path)
            init_ok = True
        except Exception as e:  # noqa
            init_ok = False
            NOTES.append(f'init error class: {type(e).__name__}')
        ok(init_ok, 'empty database initializes cleanly')
    if not init_ok:
        return _emit()

    # permissions
    NOTES.append(f'dir mode {_mode(d)} / file mode {_mode(path)}')
    if os.name == 'posix':
        ok(_mode(d) == '0o700', 'directory permissions are 0700', f'dir mode {_mode(d)}')
        ok(_mode(path) == '0o600', 'database file permissions are 0600', f'file mode {_mode(path)}')
    else:
        NOTES.append('permission bits are POSIX; Windows uses ACLs (prod is Linux) — not asserted here')

    # schema version + PRAGMAs: open via the app's connect() to reflect its configured PRAGMAs, then
    # PRAGMA query_only=ON so verification cannot write/mutate the live store.
    c = dj.connect(path)
    c.execute('PRAGMA query_only=ON')
    try:
        ver = c.execute('SELECT version FROM schema_meta WHERE id=1').fetchone()
        ok(ver and ver[0] == dj.SCHEMA_VERSION, f'schema version is {dj.SCHEMA_VERSION}',
           f'version row={ver}')
        fk = c.execute('PRAGMA foreign_keys').fetchone()[0]
        jm = c.execute('PRAGMA journal_mode').fetchone()[0]
        sy = c.execute('PRAGMA synchronous').fetchone()[0]
        NOTES.append(f'PRAGMAs: foreign_keys={fk} journal_mode={jm} synchronous={sy}')
        ok(fk == 1, 'foreign_keys=ON', f'foreign_keys={fk}')
        ok(str(jm).lower() == 'wal', 'journal_mode=WAL', f'journal_mode={jm}')
        ok(sy == 2, 'synchronous=FULL', f'synchronous={sy} (want 2=FULL)')
    finally:
        c.close()

    # integrity (both checks) on the live store
    ic, nofk = _integrity(path)
    ok(ic, 'integrity_check=ok')
    ok(nofk, 'foreign_key_check returns no rows')
    jok = dj.JournalRepository(db_path=path, auto_init=False).integrity_report()
    ok(jok['ok'], 'orphan / invariant checks clean', str(jok.get('issues')))

    # empty-store assertion — this setup is for a NEW empty database (count asserted, never printed)
    empties = {t: _count(path, t) for t in ('tickets', 'legs', 'decision_revisions')}
    ok(all(v == 0 for v in empties.values()), 'new store is empty (tickets/legs/revisions)',
       'store is not empty — this runbook is for a fresh database only')

    # feature flag OFF + routes unavailable while dark
    flag = (os.environ.get('DECISION_JOURNAL_ENABLED', '') or '').strip().lower()
    ok(flag not in ('1', 'true', 'yes', 'on'), 'DECISION_JOURNAL_ENABLED is OFF', f'flag={flag!r}')
    try:
        import app as _app
        cli = _app.app.test_client()
        codes = [cli.get(p).status_code for p in ('/journal', '/journal/new', '/journal/report')]
        ok(all(x == 404 for x in codes), 'journal routes return 404 while dark', f'codes={codes}')
    except Exception as e:  # noqa
        ok(False, 'journal routes verified unavailable', f'route check error: {type(e).__name__}')

    # backup: the SAME Python SQLite routine the runbook uses (dj.backup) -> VACUUM INTO + chmod 0600
    # + both integrity checks. Assert backup-dir 0700 and backup-file 0600 (privacy under umask).
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bdir = os.path.join(d, 'backups')
    backup = os.path.join(bdir, f'verify_{ts}.db')
    try:
        healthy = dj.backup(path, backup)  # creates bdir 0700, chmods backup 0600, dual integrity check
        ok(healthy and os.path.exists(backup) and _rows_match(path, backup),
           'backup created via dj.backup, opens, passes both integrity checks')
        if os.name == 'posix':
            ok(_mode(bdir) == '0o700', 'backup directory permissions are 0700', f'dir mode {_mode(bdir)}')
            ok(_mode(backup) == '0o600', 'backup file permissions are 0600', f'file mode {_mode(backup)}')
        else:
            NOTES.append('backup perm bits are POSIX (prod is Linux) — not asserted here')
    except sqlite3.Error as e:
        ok(False, 'backup create/verify', f'{type(e).__name__}')

    # restore round-trip ON A COPY ONLY (never corrupt the live DB)
    work = os.path.join(d, f'restore_test_{ts}.db')
    try:
        shutil.copyfile(path, work)
        with open(work, 'wb') as fh:
            fh.write(b'corrupt' * 200)
        detected = not dj.JournalRepository(db_path=work, auto_init=False).integrity_ok()
        restored = False
        if os.path.exists(backup):
            shutil.copyfile(backup, work)
            ric, rnofk = _integrity(work)
            restored = ric and rnofk and _rows_match(path, work)
        ok(detected and restored, 'corruption detected and restore recovers a healthy store (temp copy only)')
    finally:
        # Remove EVERY artifact this verifier created -- including its own `verify_` backup, which lives
        # in the real backups dir and would otherwise accumulate and evade the daily_/monthly_ retention
        # prune (it never matches those prefixes).
        for p in (work, work + '-wal', work + '-shm',
                  backup, backup + '-wal', backup + '-shm'):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    return _emit()


def _emit() -> int:
    failed = [c for c in CHECKS if not c[0]]
    print('=' * 66)
    print('DECISION JOURNAL — DARK-PRODUCTION SETUP VERIFICATION (sanitized)')
    print('=' * 66)
    for n in NOTES:
        print(f'[NOTE] {n}')
    for good, label, detail in CHECKS:
        print(f'[{"PASS" if good else "FAIL"}] {label}' + (f' — {detail}' if detail else ''))
    print('-' * 66)
    print('DARK SETUP VERIFIED — ready for dark operation (routes still disabled).' if not failed
          else f'DARK SETUP NOT READY — {len(failed)} check(s) failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
