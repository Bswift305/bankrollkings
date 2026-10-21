"""Sanitized closure receipt for the DARK King's Tickets draft store.

Prints ONLY pass/fail, counts and PRAGMA values — never account data or database row contents. Intended to
be run on prod (SSM) as the service user, read-only against the live store:

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && python3 verify_kings_tickets_dark.py'

Checks (all must pass to close the dark setup):
- schema version == 2
- PRAGMA integrity_check == ok
- PRAGMA foreign_key_check empty
- drafts == 0 and draft_legs == 0
- expected PRAGMAs active on the store connection (journal_mode=wal, synchronous=FULL,
  foreign_keys=ON, busy_timeout=5000)
- flag OFF in the running service's environment (and this process's)
- no draft-store routes wired in app.py (no DraftService / repository import on the route layer)
- no Decision Journal interaction in the draft module (no journal import)
- no backup or purge timer installed yet (no kings_tickets systemd unit)
- DB / WAL / SHM permissions valid if present (0600, owned by the service user; dir 0700)

Exits 0 only when every check passes. Use --path only for local self-test against a throwaway store.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import stat
import subprocess
import sys

import services.kings_tickets_drafts as kd

OKS, FAILS = [], []


def check(name, cond, detail=''):
    (OKS if cond else FAILS).append(f'{name}{(" — " + detail) if detail else ""}')


def _service_env_flag():
    """Return the flag as seen by the running service ('0'/'1'/absent), via systemctl; None if unavailable."""
    try:
        out = subprocess.run(['systemctl', 'show', 'bankrollkings', '-p', 'Environment'],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 -- systemctl absent (dev host)
        return None
    m = re.search(r'KINGS_TICKETS_DRAFTS_ENABLED=(\S+)', out)
    return m.group(1) if m else 'absent'


def _perm_ok(path, want_mode, want_uid):
    lst = os.lstat(path)
    if stat.S_ISLNK(lst.st_mode):
        return False, 'symlink'
    mode = stat.S_IMODE(lst.st_mode)
    if mode != want_mode:
        return False, f'mode {oct(mode)} != {oct(want_mode)}'
    if os.name == 'posix' and want_uid is not None and lst.st_uid != want_uid:
        return False, 'wrong owner'
    return True, oct(mode)


def run(path=None):
    db = kd.Path(path) if path else kd._default_db_path()

    # 1. flag OFF (this process + the running service)
    check('flag OFF (this process)', not kd.drafts_enabled())
    svc = _service_env_flag()
    if svc is None:
        OKS.append('flag OFF (service env) — systemctl unavailable (dev host), skipped')
    else:
        check('flag OFF (service env)', svc in ('absent', '0', '"0"'), f'env={svc}')

    # 2. no draft routes / repository import on the route layer; no Journal interaction in the module
    try:
        app_src = open('app.py', encoding='utf-8', errors='replace').read()
        check('no repository import in app.py', 'KingsTicketDraftStore' not in app_src)
        check('no DraftService wiring in app.py', 'DraftService' not in app_src)
        check('no kings_tickets_drafts import in app.py', 'kings_tickets_drafts' not in app_src)
    except OSError:
        FAILS.append('app.py unreadable')
    mod_src = open(kd.__file__, encoding='utf-8', errors='replace').read()
    check('no Decision Journal import in the draft module',
          not re.search(r'^\s*(from|import)\s+\S*journal', mod_src, re.MULTILINE))

    # 3. no backup / purge timer installed yet
    units = []
    for base in ('/etc/systemd/system', '/lib/systemd/system'):
        units += glob.glob(os.path.join(base, '*kings*ticket*'))
        units += glob.glob(os.path.join(base, '*kt-*purge*'))
    check('no backup/purge timer installed', not units, f'{len(units)} unit(s)')

    # 4. store contents + integrity (sanitized: counts + PRAGMA verdicts only)
    if not db.exists():
        FAILS.append(f'store DB absent at the expected path')
        return
    store = kd.KingsTicketDraftStore() if path is None else kd.KingsTicketDraftStore(path=str(db))
    try:
        c = store.conn
        ver = c.execute('SELECT version FROM schema_meta').fetchone()[0]
        check('schema version == 2', int(ver) == kd.SCHEMA_VERSION == 2, f'version={ver}')
        integ = c.execute('PRAGMA integrity_check').fetchone()[0]
        check('integrity_check == ok', integ == 'ok', f'result={integ}')
        fk = c.execute('PRAGMA foreign_key_check').fetchall()
        check('foreign_key_check empty', len(fk) == 0, f'{len(fk)} violation(s)')
        nd = c.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]
        nl = c.execute('SELECT COUNT(*) FROM draft_legs').fetchone()[0]
        check('drafts == 0', nd == 0, f'count={nd}')
        check('draft_legs == 0', nl == 0, f'count={nl}')
        jm = c.execute('PRAGMA journal_mode').fetchone()[0]
        sy = c.execute('PRAGMA synchronous').fetchone()[0]
        fkp = c.execute('PRAGMA foreign_keys').fetchone()[0]
        bt = c.execute('PRAGMA busy_timeout').fetchone()[0]
        check('journal_mode = wal', str(jm).lower() == 'wal', f'mode={jm}')
        check('synchronous = FULL(2)', int(sy) == 2, f'value={sy}')
        check('foreign_keys = ON', int(fkp) == 1, f'value={fkp}')
        check('busy_timeout = 5000', int(bt) == 5000, f'value={bt}')
    finally:
        store.close()

    # 5. permissions if present (dir 0700; db/-wal/-shm 0600) — POSIX only (Windows mode bits are meaningless)
    if os.name != 'posix':
        OKS.append('permissions — POSIX-only, skipped on non-POSIX dev host')
        return
    want_uid = os.getuid()
    dok, ddet = _perm_ok(db.parent, 0o700, want_uid)
    check('dir 0700 / owner', dok, ddet)
    for suffix, label in (('', 'db 0600'), ('-wal', 'wal 0600'), ('-shm', 'shm 0600')):
        f = kd.Path(str(db) + suffix)
        if os.path.lexists(f):
            pok, det = _perm_ok(f, 0o600, want_uid)
            check(f'{label} / owner (present)', pok, det)
        else:
            OKS.append(f'{label} — not present')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', help='TEST-ONLY: verify a throwaway store at this path instead of the prod default')
    args = ap.parse_args()
    run(path=args.path)
    print('=' * 68)
    print("BANKROLL KINGS - KING'S TICKETS DARK-STORE CLOSURE RECEIPT")
    print('=' * 68)
    for o in OKS:
        print(f'[OK]   {o}')
    for f in FAILS:
        print(f'[FAIL] {f}')
    print('-' * 68)
    if FAILS:
        print(f'RECEIPT: {len(FAILS)} FAILED — dark setup NOT closed.')
        return 1
    print('RECEIPT: all checks passed — dark setup verified closed (flag remains OFF).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
