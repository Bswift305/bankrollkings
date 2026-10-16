#!/usr/bin/env python3
"""Decision Journal — dark-production SETUP VERIFIER (read-only on the live store).

Run AFTER creating the private directory and setting DECISION_JOURNAL_DB_PATH, with the feature flag
still OFF, as the application service user. Proves permissions, initialization, PRAGMAs, both integrity
checks, backup, and a restore round-trip -- WITHOUT enabling routes, WITHOUT migrating or creating
tickets, and WITHOUT destructively touching the live DB (the corrupt/restore test runs on a copy).

The report is SANITIZED: it prints no ticket contents, user IDs, row counts, environment secrets, or
database bytes -- only PASS/FAIL checkpoints and non-sensitive configuration (paths, modes, PRAGMAs).

    DECISION_JOURNAL_DB_PATH=/var/lib/bankrollkings/decision_journal/journal.db \
        python3 verify_decision_journal_setup.py
"""
from __future__ import annotations

import getpass
import os
import shutil
import sqlite3
import stat
from datetime import datetime, timezone

import services.decision_journal as dj

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
CHECKS, NOTES = [], []


def ok(cond, label, fail_detail=''):
    CHECKS.append((bool(cond), label, '' if cond else fail_detail))


def _mode(path):
    try:
        return oct(stat.S_IMODE(os.stat(path).st_mode))
    except OSError:
        return 'n/a'


def _rows_match(a, b):
    """True if two stores hold the same number of tickets. The count itself is never printed."""
    def n(p):
        c = sqlite3.connect(p)
        try:
            return c.execute('SELECT count(*) FROM tickets').fetchone()[0]
        finally:
            c.close()
    return n(a) == n(b)


def _integrity(path):
    """(ok, no_fk_rows) using a plain connection — both checks the director requires."""
    c = sqlite3.connect(path)
    try:
        ic = c.execute('PRAGMA integrity_check').fetchone()[0]
        fk = c.execute('PRAGMA foreign_key_check').fetchall()
        return ic == 'ok', (len(fk) == 0)
    except sqlite3.Error:
        return False, False
    finally:
        c.close()


def main() -> int:
    path = dj.resolve_db_path()
    d = os.path.dirname(os.path.abspath(path))
    NOTES.append(f'service user: {getpass.getuser()} (confirm this is the app service account)')
    NOTES.append(f'DB path: {path}')

    # service user is not root (prod)
    if os.name == 'posix':
        ok(os.geteuid() != 0, 'runs as a non-root service user', f'euid={os.geteuid()} (root)')

    # path resolves OUTSIDE the deploy checkout
    inside = os.path.abspath(path).startswith(REPO_ROOT + os.sep)
    ok(not inside, 'DECISION_JOURNAL_DB_PATH resolves outside the checkout',
       f'path is inside the checkout {REPO_ROOT}')

    # initialize (idempotent; empty DB in prod)
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

    # schema version
    c = dj.connect(path)
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

    # backup (consistent snapshot) + both integrity checks on the backup
    bdir = os.path.join(d, 'backups')
    os.makedirs(bdir, exist_ok=True)
    try:
        os.chmod(bdir, 0o700)
    except OSError:
        pass
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = os.path.join(bdir, f'verify_{ts}.db')
    try:
        cc = sqlite3.connect(path)
        cc.execute('VACUUM INTO ?', (backup,))
        cc.close()
        bic, bnofk = _integrity(backup)
        ok(os.path.exists(backup) and bic and bnofk and _rows_match(path, backup),
           'backup created, opens, passes both integrity checks (rows match live)')
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
        for p in (work, work + '-wal', work + '-shm'):
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
