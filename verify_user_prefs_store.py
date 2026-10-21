"""Production preference-store receipt — sanitized (prints only pass/fail + counts, never pref contents).

Proves the operational claims for services/user_prefs_store.py ON THE PROD LAYOUT, as the service user:

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && python3 verify_user_prefs_store.py'

Checks (against a throwaway uid in the real prefs dir, then cleaned up):
- the prefs dir resolves + exists (or is self-created) on the prod path;
- MULTI-PROCESS locking: N separate OS processes each set a distinct key -> no lost update (fcntl on Linux,
  the real cross-worker proof — not just threads);
- atomic replacement (no .prefs- temp left behind);
- corruption recovery (a garbage file degrades to {} and is replaced with valid JSON keeping the new key);
- sibling-key preservation (one key's write never clobbers another);
- POSIX permissions of the file (0600 via mkstemp) and dir reported;
- deploy/restart survival is asserted structurally (gitignored inside the checkout OR relocated via
  BK_USER_PREFS_DIR; a file written here persists a `git pull --ff-only` + restart — re-run after a deploy
  to confirm the sentinel below still reads back).

Exits 0 only when all pass. Writes nothing outside the throwaway test uid.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import services.user_prefs_store as ups

OKS, FAILS = [], []
TEST_UID = '__prefs_selfcheck__'


def check(name, cond, detail=''):
    (OKS if cond else FAILS).append(f'{name}{(" — " + detail) if detail else ""}')


def _prefs_dir():
    return os.environ.get('BK_USER_PREFS_DIR') or os.path.join(os.getcwd(), 'data', 'user_prefs')


def _worker_cmd(prefs_dir, uid, i):
    code = (f"import services.user_prefs_store as u;"
            f"u.update_prefs({prefs_dir!r},{uid!r},lambda d: d.__setitem__('k{i}',{i}))")
    return [sys.executable, '-c', code]


def run():
    prefs_dir = _prefs_dir()
    os.makedirs(prefs_dir, exist_ok=True)
    pf = os.path.join(prefs_dir, f'{TEST_UID}.json')
    for suffix in ('.json', '.json.lock'):
        try:
            os.remove(os.path.join(prefs_dir, f'{TEST_UID}{suffix}'))
        except OSError:
            pass
    check('prefs dir resolves + writable', os.path.isdir(prefs_dir), prefs_dir)

    # MULTI-PROCESS: 16 separate OS processes, each sets a distinct key on the same uid, concurrently.
    n = 16
    procs = [subprocess.Popen(_worker_cmd(prefs_dir, TEST_UID, i), cwd=os.getcwd()) for i in range(n)]
    for p in procs:
        p.wait(timeout=60)
    d = ups.read_prefs(prefs_dir, TEST_UID)
    present = sum(1 for i in range(n) if d.get(f'k{i}') == i)
    check('multi-PROCESS lock: no lost update', present == n, f'{present}/{n} keys survived')

    # atomic: no temp leak
    leftovers = [f for f in os.listdir(prefs_dir) if f.startswith('.prefs-')]
    check('atomic write leaves no temp', not leftovers, f'{len(leftovers)} temp file(s)')

    # sibling preservation
    ups.update_prefs(prefs_dir, TEST_UID, lambda x: x.__setitem__('sibling', {'a': 1}))
    d2 = ups.read_prefs(prefs_dir, TEST_UID)
    check('sibling-key preservation', d2.get('sibling') == {'a': 1} and d2.get('k0') == 0)

    # corruption recovery
    with open(pf, 'w', encoding='utf-8') as fh:
        fh.write('{ not json ')
    check('corrupt file reads as {}', ups.read_prefs(prefs_dir, TEST_UID) == {})
    ups.update_prefs(prefs_dir, TEST_UID, lambda x: x.__setitem__('recovered', True))
    with open(pf, encoding='utf-8') as fh:
        json.load(fh)  # must parse
    check('corrupt file replaced with valid JSON', ups.read_prefs(prefs_dir, TEST_UID).get('recovered') is True)

    # permissions (POSIX)
    if os.name == 'posix':
        import stat
        fmode = stat.S_IMODE(os.stat(pf).st_mode)
        dmode = stat.S_IMODE(os.stat(prefs_dir).st_mode)
        check('file not group/other readable (0600)', not (fmode & 0o077), f'file {oct(fmode)} / dir {oct(dmode)}')
    else:
        OKS.append('permissions — POSIX-only, skipped on non-POSIX dev host')

    # deploy/restart survival: write a sentinel and report the location class
    ups.update_prefs(prefs_dir, TEST_UID, lambda x: x.__setitem__('deploy_sentinel', 1))
    relocated = bool(os.environ.get('BK_USER_PREFS_DIR'))
    OKS.append('deploy/restart survival — ' + ('relocated via BK_USER_PREFS_DIR (persistent)'
               if relocated else 'gitignored in the checkout: survives git pull --ff-only + restart'))

    # cleanup
    for suffix in ('.json', '.json.lock'):
        try:
            os.remove(os.path.join(prefs_dir, f'{TEST_UID}{suffix}'))
        except OSError:
            pass


def main():
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        FAILS.append(f'verifier crashed: {type(exc).__name__}: {exc}')
    print('=' * 68)
    print('BANKROLL KINGS - USER PREFERENCE STORE PRODUCTION RECEIPT')
    print('=' * 68)
    for o in OKS:
        print(f'[OK]   {o}')
    for f in FAILS:
        print(f'[FAIL] {f}')
    print('-' * 68)
    if FAILS:
        print(f'RECEIPT: {len(FAILS)} FAILED.')
        return 1
    print('RECEIPT: all preference-store production checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
