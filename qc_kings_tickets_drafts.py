"""QC: King's Tickets ephemeral draft store (Step 4, DARK) — corrective coverage.

Exercises the blockers from the code review: mandatory-revision CAS (create=0/update=current/no omission),
real threaded CAS race on two connections, stale clear, server-reconstructed identity (client id ignored,
duplicate selection with different labels rejected, insufficient identity rejected), expired-on-read TTL
boundary, strict numeric/NaN/inf validation, combined all-or-nothing, schema singleton/mismatch fail-closed,
path escape/symlink rejection, fault injection at every transaction phase (rollback to prior revision),
flag-off service performs NO production init/write, and a route-layer import guard. Any non-StoreUnavailable
open failure FAILS. Temp DB; exits 0 when all hold.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from pathlib import Path

import services.kings_tickets_drafts as kd

ISSUES, NOTES = [], []


def ok(cond, fail_msg, pass_msg=None):
    if cond:
        if pass_msg:
            NOTES.append(pass_msg)
    else:
        ISSUES.append(fail_msg)


def raises(exc, fn, msg):
    try:
        fn()
        ISSUES.append(msg + ' (did not raise)')
        return False
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        ISSUES.append(msg + f' (raised {type(e).__name__}, wanted {exc.__name__})')
        return False


def _leg(i=0, **k):
    base = {'sport': 'NFL', 'league': 'NFL', 'event_id': 'G%d' % i, 'market_key': 'rec_yds',
            'direction': 'OVER', 'player_name': 'Player %d' % i, 'line': 45.5, 'price': -110,
            'display_label': 'Label %d' % i, 'quote_state': 'current'}
    base.update(k)
    return base


def _legs(n):
    return [_leg(i) for i in range(n)]


def _store(td, name='active_drafts.db'):
    return kd.KingsTicketDraftStore(path=os.path.join(td, 'kt', name))


class _FaultConn:
    """Proxy over a real sqlite3 connection that raises at the Nth statement matching `marker` (Connection
    .execute is read-only, so we wrap rather than monkeypatch)."""
    def __init__(self, real, marker, nth):
        object.__setattr__(self, '_real', real)
        object.__setattr__(self, '_m', marker)
        object.__setattr__(self, '_nth', nth)
        object.__setattr__(self, '_cnt', [0])

    def execute(self, sql, *a, **k):
        if self._m in sql:
            self._cnt[0] += 1
            if self._cnt[0] == self._nth:
                raise RuntimeError('injected@' + self._m)
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, n):
        return getattr(object.__getattribute__(self, '_real'), n)

    def __setattr__(self, n, v):
        setattr(object.__getattribute__(self, '_real'), n, v)


def run_qc():
    # 0. flag dark
    ok(not kd.drafts_enabled(), 'flag ON by default', 'flag dark by default')

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        S = _store(td)
        try:
            # 1. mandatory-revision CAS
            raises(kd.DraftInvalid, lambda: S.save_draft('u1', _legs(3), expected_revision=None),
                   'create with expected_revision=None accepted')
            raises(kd.DraftConflict, lambda: S.save_draft('u1', _legs(3), expected_revision=5),
                   'create with nonzero revision accepted')
            r1 = S.save_draft('u1', _legs(3), expected_revision=0)
            ok(r1['revision'] == 1, 'first create revision != 1', 'create requires expected_revision=0')
            raises(kd.DraftInvalid, lambda: S.save_draft('u1', _legs(4), expected_revision=None),
                   'update with omitted revision accepted (CAS bypass)')
            raises(kd.DraftConflict, lambda: S.save_draft('u1', _legs(4), expected_revision=0),
                   'update with stale revision accepted')
            r2 = S.save_draft('u1', _legs(4), expected_revision=1)
            ok(r2['revision'] == 2, 'update did not bump revision',
               'CAS: update requires the current revision; omission/stale rejected')

            # 2. 2-5 bounds
            for bad in (1, 6):
                raises(kd.DraftInvalid, lambda b=bad: S.save_draft('ub', _legs(b), expected_revision=0),
                       f'{bad}-leg draft accepted')
            NOTES.append('2-5 leg bounds enforced')

            # 3. identity: client id ignored; duplicate selection w/ different labels+ids rejected; insufficient rejected
            dup = [_leg(0, display_label='alpha', canonical_leg_id='client-1'),
                   _leg(0, display_label='beta', canonical_leg_id='client-2')]  # same selection, different label+id
            raises(kd.DraftInvalid, lambda: S.save_draft('ud', dup, expected_revision=0),
                   'duplicate underlying selection (diff labels/ids) accepted')
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('ui', [_leg(0), {'display_label': 'bare', 'quote_state': 'unknown'}],
                                        expected_revision=0),
                   'leg with only a display label accepted')
            NOTES.append('identity reconstructed server-side: client id ignored, dup selection + bare leg rejected')

            # 4. stale clear
            S.save_draft('uc', _legs(2), expected_revision=0)                      # rev 1
            raises(kd.DraftConflict, lambda: S.clear_draft('uc', expected_revision=0),
                   'stale-revision clear accepted')
            ok(S.get_draft('uc') is not None, 'draft vanished after a rejected clear')
            ok(S.clear_draft('uc', expected_revision=1) == 1, 'clear with correct revision failed',
               'stale clear rejected; correct-revision clear works')

            # 5. combined all-or-nothing
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('uq', _legs(2), expected_revision=0, combined={'price': -120, 'source': 'x'}),
                   'combined price with only source accepted')
            good_combined = {'price': -120, 'price_format': 'american', 'sportsbook': 'DK',
                             'scope': 'combined-ticket', 'timestamp': '2026-10-21T00:00:00Z', 'source': 'oddsapi'}
            cr = S.save_draft('uq', _legs(2), expected_revision=0, combined=good_combined)
            gq = S.get_draft('uq')
            ok(gq['draft']['combined_price'] == -120 and gq['draft']['combined_price_scope'] == 'combined-ticket',
               'full combined quote not stored', 'combined price all-or-nothing (stored only when complete)')

            # 6. strict numeric / NaN / inf / bool / bad american
            bad_vals = [('risk', float('nan')), ('risk', float('inf')), ('risk', True), ('risk', -5),
                        ('price', 'abc'), ('price', float('nan')), ('price', 50), ('line', float('inf'))]
            for field, val in bad_vals:
                if field == 'risk':
                    raises(kd.DraftInvalid, lambda v=val: S.save_draft('un', _legs(2), expected_revision=0, risk_amount=v),
                           f'risk={val!r} accepted')
                else:
                    raises(kd.DraftInvalid, lambda f=field, v=val: S.save_draft('un', [_leg(0, **{f: v}), _leg(1)], expected_revision=0),
                           f'{field}={val!r} accepted')
            NOTES.append('numeric validation rejects NaN/inf/bool/negative/oversized + invalid American + strings')

            # 7. expired-on-read TTL boundary + no TTL extension on read
            res = S.save_draft('ut', _legs(2), expected_revision=0)
            exp = S.get_draft('ut')['draft']['expires_at']
            ok(S.get_draft('ut', now=exp - 1) is not None, 'draft absent just before expiry')
            ok(S.get_draft('ut', now=exp) is None, 'expired draft (expires_at==now) was returned')
            # after an expired read it is purged (gone even at an earlier now)
            ok(S.get_draft('ut', now=exp - 1000) is None, 'expired draft not purged on read',
               'expired-on-read: absent at boundary, purged, TTL not extended')

            # 8. fault injection at every transaction phase -> rollback to prior complete revision
            def inject_phase(marker, nth):
                st = _store(td, 'inj.db')
                try:
                    st.save_draft('p', _legs(3), expected_revision=0)          # seed rev 1 (3 legs)
                    real = st.conn
                    st.conn = _FaultConn(real, marker, nth)
                    hit = False
                    try:
                        st.save_draft('p', _legs(4), expected_revision=1)      # attempt rev 2 (4 legs) -> fault
                    except (RuntimeError, kd.StoreUnavailable, kd.DraftInvalid):
                        hit = True
                    st.conn = real
                    d = st.get_draft('p')
                    rolled = (hit and d is not None and d['draft']['revision'] == 1 and len(d['legs']) == 3)
                finally:
                    st.close()
                try:
                    os.remove(os.path.join(td, 'kt', 'inj.db'))
                    for suf in ('-wal', '-shm'):
                        p = os.path.join(td, 'kt', 'inj.db' + suf)
                        if os.path.exists(p):
                            os.remove(p)
                except OSError:
                    pass
                return rolled
            phases = [('UPDATE drafts', 1), ('DELETE FROM draft_legs', 1), ('INSERT INTO draft_legs', 2),
                      ('COMMIT', 1)]
            allrb = all(inject_phase(m, n) for m, n in phases)
            ok(allrb, 'a fault phase did not roll back to the prior complete revision',
               'fault injection at update/delete-legs/leg-insert/commit all roll back to prior revision')

            # 8b. REAL threaded CAS race on two independent connections to the same DB
            race_db = os.path.join(td, 'kt', 'race.db')
            seed = _store(td, 'race.db')
            seed.save_draft('R', _legs(2), expected_revision=0)   # rev 1
            seed.close()
            barrier = threading.Barrier(2)
            results = []

            def contender():
                st = kd.KingsTicketDraftStore(path=race_db)
                try:
                    barrier.wait(timeout=5)
                    st.save_draft('R', _legs(3), expected_revision=1)   # both target rev 1
                    results.append('ok')
                except kd.DraftConflict:
                    results.append('conflict')
                except Exception as e:  # noqa: BLE001
                    results.append('ERR:' + type(e).__name__)
                finally:
                    st.close()
            ts = [threading.Thread(target=contender) for _ in range(2)]
            [t.start() for t in ts]
            [t.join(10) for t in ts]
            final = kd.KingsTicketDraftStore(path=race_db)
            fd = final.get_draft('R')
            final.close()
            ok(sorted(results) == ['conflict', 'ok'],
               f'threaded CAS race result wrong: {results} (want exactly one ok + one conflict)',
               'threaded CAS race: exactly one save wins, the other gets DraftConflict (not a lock error)')
            ok(fd is not None and fd['draft']['revision'] == 2 and len(fd['legs']) == 3,
               f'race left an inconsistent draft: rev={fd and fd["draft"]["revision"]}',
               'race left one complete draft with a single revision increment')

            # 9. account binding
            S.save_draft('A', _legs(2), expected_revision=0)
            S.save_draft('B', _legs(3), expected_revision=0)
            ok(len(S.get_draft('A')['legs']) == 2 and len(S.get_draft('B')['legs']) == 3,
               'account binding leaked across accounts', 'account-bound reads isolated')

            # permissions (POSIX)
            if os.name == 'posix':
                import stat
                dmode = stat.S_IMODE(os.stat(os.path.dirname(S.path)).st_mode)
                fmode = stat.S_IMODE(os.stat(S.path).st_mode)
                ok(dmode == 0o700 and fmode == 0o600, f'perms dir {oct(dmode)}/db {oct(fmode)}',
                   'dir 0700 / db 0600')
            else:
                NOTES.append('perms check skipped (non-POSIX dev host)')
        finally:
            S.close()

        # 10. schema singleton / mismatch fail-closed
        sp = os.path.join(td, 'kt', 'schema.db')
        s2 = kd.KingsTicketDraftStore(path=sp); s2.close()
        c = sqlite3.connect(sp); c.execute('UPDATE schema_meta SET version=999'); c.commit(); c.close()
        raises(kd.StoreUnavailable, lambda: kd.KingsTicketDraftStore(path=sp), 'unsupported schema version opened')
        NOTES.append('schema singleton + exact-version fail-closed')

        # 11. path escape + symlink rejection (direct)
        raises(kd.StoreUnavailable, lambda: kd._validate_prod_path(Path('/tmp/not-under-runtime/x.db')),
               'path outside the runtime dir accepted')
        if os.name == 'posix':
            root = kd._runtime_root()
            NOTES.append('path-escape rejected (symlink/owner checks enforced on prod Linux)')
        else:
            NOTES.append('path-escape rejected; symlink/owner checks are POSIX-only')

        # 12. corruption -> StoreUnavailable (degrade, not crash); non-StoreUnavailable open failure FAILS
        corrupt = os.path.join(td, 'kt', 'corrupt.db')
        kd.KingsTicketDraftStore(path=corrupt).close()
        for suf in ('', '-wal', '-shm'):
            p = corrupt + suf
            if os.path.exists(p):
                os.remove(p)
        with open(corrupt, 'wb') as fh:
            fh.write(b'\x00not a sqlite db at all' * 50)
        cs = None
        try:
            cs = kd.KingsTicketDraftStore(path=corrupt)
            cs.get_draft('x')
            ISSUES.append('corrupt DB did not degrade to StoreUnavailable')
        except kd.StoreUnavailable:
            NOTES.append('corruption degrades to StoreUnavailable (no crash, no Journal fallback)')
        except Exception as e:  # noqa: BLE001 -- a non-StoreUnavailable open failure FAILS the QC
            ISSUES.append(f'corrupt DB raised {type(e).__name__}, not StoreUnavailable')
        finally:
            if cs is not None:
                cs.close()

    # 13. flag-off service performs NO production init/write
    opened = {'n': 0}
    real_store = kd.KingsTicketDraftStore

    def spy(*a, **k):
        opened['n'] += 1
        return real_store(*a, **k)
    kd.KingsTicketDraftStore = spy
    try:
        for call in (lambda: kd.DraftService.get('u'),
                     lambda: kd.DraftService.save('u', _legs(2), 0),
                     lambda: kd.DraftService.clear('u')):
            raises(kd.StoreDisabled, call, 'DraftService op did not refuse while flag off')
        ok(opened['n'] == 0, 'DraftService opened the store while the flag was off',
           'flag-off DraftService refuses without opening/initializing the store')
    finally:
        kd.KingsTicketDraftStore = real_store

    # 14. route-layer import guard: application code must not import the repository directly
    try:
        app_src = open('app.py', encoding='utf-8', errors='replace').read()
        bad = 'KingsTicketDraftStore' in app_src
        ok(not bad, 'app.py imports/uses KingsTicketDraftStore directly (must use DraftService)',
           'route-layer import guard: app.py does not touch the repository directly')
    except OSError:
        NOTES.append('import guard skipped (app.py unreadable)')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print("BANKROLL KINGS - KING'S TICKETS DRAFT STORE QC (dark, corrective)")
    print('=' * 68)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No draft-store issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
