"""QC: atomic, multi-worker-safe per-user preference store (services/user_prefs_store.py).

Proves the store hardening the Green Light workspace depends on:
- atomic write (no lingering temp; readers see complete old-or-new);
- key-scoped mutation (updating one key preserves the others);
- concurrent-write safety (N threads each setting a different key -> no lost update);
- reset of one key preserves unrelated settings;
- corrupt/garbage file degrades to {} and is replaced with valid JSON, keeping the new key;
- anon/empty uid is a no-op (no file created);
- fail-safe reads.
Pure/stdlib; exits 0 when all hold.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

import services.user_prefs_store as ups

ISSUES, NOTES = [], []


def ok(cond, fail_msg, pass_msg=None):
    if cond:
        if pass_msg:
            NOTES.append(pass_msg)
    else:
        ISSUES.append(fail_msg)


def run_qc():
    with tempfile.TemporaryDirectory() as td:
        # 1. atomic write + fail-safe read round-trip; no lingering temp
        ups.update_prefs(td, 'u1', lambda d: d.__setitem__('card', {'sizes': [3, 4, 5]}))
        ok(ups.read_prefs(td, 'u1').get('card') == {'sizes': [3, 4, 5]}, 'round-trip failed')
        leftovers = [f for f in os.listdir(td) if f.startswith('.prefs-')]
        ok(not leftovers, f'temp file lingered after atomic write: {leftovers}', 'atomic write leaves no temp')

        # 2. key-scoped mutation preserves other keys
        ups.update_prefs(td, 'u1', lambda d: d.__setitem__('greenlight', {'lens_hidden': ['heat_map']}))
        ups.update_prefs(td, 'u1', lambda d: d.__setitem__('home', 'classic'))
        d = ups.read_prefs(td, 'u1')
        ok(d.get('card') == {'sizes': [3, 4, 5]} and d.get('greenlight') == {'lens_hidden': ['heat_map']}
           and d.get('home') == 'classic',
           f'key-scoped mutation clobbered a sibling: {d}', 'key-scoped mutation preserves other keys')

        # 3. concurrent writes: 24 threads each set a distinct key -> all survive (no lost update)
        n = 24
        barrier = threading.Barrier(n)

        def worker(i):
            barrier.wait(timeout=10)
            ups.update_prefs(td, 'race', lambda d, i=i: d.__setitem__(f'k{i}', i))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join(15) for t in threads]
        d = ups.read_prefs(td, 'race')
        present = sum(1 for i in range(n) if d.get(f'k{i}') == i)
        ok(present == n, f'lost update under concurrency: only {present}/{n} keys survived',
           'concurrent writes: every distinct key survives (no lost update)')

        # 4. reset one key preserves unrelated settings
        ups.update_prefs(td, 'u2', lambda d: d.update({'card': {'x': 1}, 'greenlight': {'y': 2}}))
        ups.update_prefs(td, 'u2', lambda d: d.pop('greenlight', None))
        d = ups.read_prefs(td, 'u2')
        ok(d.get('card') == {'x': 1} and 'greenlight' not in d,
           f'reset altered unrelated settings: {d}', 'reset of one key preserves unrelated settings')

        # 5. corrupt file degrades to {} and is replaced with valid JSON keeping the new key
        cp = os.path.join(td, 'corrupt.json')
        with open(cp, 'w', encoding='utf-8') as fh:
            fh.write('{ this is not json ')
        ok(ups.read_prefs(td, 'corrupt') == {}, 'corrupt file did not read as {}')
        ups.update_prefs(td, 'corrupt', lambda d: d.__setitem__('card', {'ok': True}))
        reread = ups.read_prefs(td, 'corrupt')
        with open(cp, encoding='utf-8') as fh:
            json.load(fh)  # must now parse
        ok(reread == {'card': {'ok': True}}, f'corrupt file not safely replaced: {reread}',
           'corrupt file degrades to {} then is replaced with valid JSON')

        # 6. anon/empty uid is a no-op (no file created)
        before = set(os.listdir(td))
        wrote = ups.update_prefs(td, '', lambda d: d.__setitem__('card', {'x': 1}))
        after = set(os.listdir(td))
        ok(wrote is False and before == after, 'anon write created a file', 'anon/empty uid writes nothing')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print('BANKROLL KINGS - USER PREFERENCE STORE QC (atomic + concurrency)')
    print('=' * 68)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No user-prefs-store issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
